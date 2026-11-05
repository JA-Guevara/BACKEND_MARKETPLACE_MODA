"""Servicio de cálculo de uso, cuotas de plan, avisos 80%/100% y onboarding (RS-3)."""
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.inventario_sucursales.infrastructure.models.organization import BranchModel, CashPointModel
from src.plataforma_saas.infrastructure.models.module import TenantLimitModel
from src.plataforma_saas.infrastructure.models.storefront import TenantPaymentMethodModel, UsageAlertModel
from src.plataforma_saas.infrastructure.models.subscription import SubscriptionModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.plataforma_saas.web.schemas.storefront import OnboardingOut, UsageItem
from src.usuarios_catalogo.infrastructure.models.catalog import ProductImageModel, ProductModel


class UsageService:
    def __init__(self, db: Session):
        self.db = db

    def _obtener_limite(self, tenant_id: UUID, limit_code: str, default_val: int) -> int:
        now = datetime.now(timezone.utc)
        # 1. Override específico
        try:
            stmt = select(TenantLimitModel).where(
                TenantLimitModel.tenant_id == tenant_id,
                TenantLimitModel.limit_code == limit_code,
                TenantLimitModel.revoked_at.is_(None),
            )
            override = self.db.scalars(stmt).first()
            if override and (override.expires_at is None or override.expires_at > now):
                return override.value
        except Exception:
            pass

        # 2. Límite del plan de la suscripción activa
        sub = self.db.scalar(
            select(SubscriptionModel).where(
                SubscriptionModel.tenant_id == tenant_id,
                SubscriptionModel.status == "ACTIVA",
                SubscriptionModel.closed_at.is_(None),
            )
        )
        if sub and sub.plan and sub.plan.features:
            for f in sub.plan.features:
                if f.feature_code == limit_code and f.limit_value is not None:
                    return f.limit_value
                if limit_code == "branches" and f.feature_code == "max_active_branches" and f.limit_value is not None:
                    return f.limit_value

        return default_val

    def uso(self, tenant_id: UUID) -> list[UsageItem]:
        branch_limit = self._obtener_limite(tenant_id, "branches", 2)
        product_limit = self._obtener_limite(tenant_id, "products", 100)
        user_limit = self._obtener_limite(tenant_id, "users", 5)
        ai_limit = self._obtener_limite(tenant_id, "ai_reports_monthly", 20)

        # 1. Sucursales
        branch_count = (
            self.db.scalar(
                select(func.count(BranchModel.id)).where(
                    BranchModel.tenant_id == tenant_id,
                    BranchModel.is_active.is_(True),
                )
            )
            or 0
        )

        # 2. Prendas
        product_count = (
            self.db.scalar(
                select(func.count(ProductModel.id)).where(
                    ProductModel.tenant_id == tenant_id,
                    ProductModel.is_active.is_(True),
                )
            )
            or 0
        )

        # 3. Usuarios
        user_count = (
            self.db.scalar(
                select(func.count(UserModel.id)).where(
                    UserModel.tenant_id == tenant_id,
                    UserModel.is_active.is_(True),
                )
            )
            or 0
        )

        # 4. Reportes IA del mes
        ai_count = 0

        def make_item(code: str, name: str, used: int, lim: int | None) -> UsageItem:
            pct = round((used / lim * 100), 1) if lim and lim > 0 else 0.0
            return UsageItem(
                limit_code=code,
                name=name,
                used=used,
                limit=lim,
                percentage=pct,
                has_warning=pct >= 80.0,
            )

        return [
            make_item("branches", "Sucursales activas", branch_count, branch_limit),
            make_item("products", "Prendas registradas", product_count, product_limit),
            make_item("users", "Usuarios de equipo", user_count, user_limit),
            make_item("ai_reports_monthly", "Reportes IA este mes", ai_count, ai_limit),
        ]

    def avisar_si_corresponde(self, tenant_id: UUID, limit_code: str) -> None:
        """Registra un aviso único al alcanzar el 80% o el 100% de una cuota."""
        items = {item.limit_code: item for item in self.uso(tenant_id)}
        item = items.get(limit_code)
        if not item or not item.limit:
            return

        level_to_alert = None
        if item.percentage >= 100.0:
            level_to_alert = 100
        elif item.percentage >= 80.0:
            level_to_alert = 80

        if level_to_alert is None:
            return

        # Verificar si ya se envió este aviso
        ya_enviado = self.db.scalar(
            select(UsageAlertModel).where(
                UsageAlertModel.tenant_id == tenant_id,
                UsageAlertModel.limit_code == limit_code,
                UsageAlertModel.level == level_to_alert,
            )
        )
        if ya_enviado:
            return

        alert = UsageAlertModel(
            tenant_id=tenant_id,
            limit_code=limit_code,
            level=level_to_alert,
            sent_at=datetime.now(timezone.utc),
        )
        self.db.add(alert)
        self.db.flush()

        RecordAuditEvent(self.db).execute(
            actor_user_id=None,
            action=f"tenant.quota_warning_{level_to_alert}",
            entity_type="usage_alert",
            entity_id=f"{tenant_id}:{limit_code}:{level_to_alert}",
            description=f"Aviso de cuota alcanzada al {level_to_alert}% para {limit_code} ({item.used}/{item.limit}).",
            metadata={"limit_code": limit_code, "level": level_to_alert, "used": item.used, "limit": item.limit},
        )
        self.db.commit()

    def onboarding(self, tenant_id: UUID) -> OnboardingOut:
        tenant = self.db.get(TenantModel, tenant_id)
        if tenant is None:
            return OnboardingOut(completed_steps=[], pending_steps=[], is_ready_to_publish=False, progress_percentage=0)

        # Evaluaciones
        has_branch = bool(
            self.db.scalar(
                select(func.count(BranchModel.id)).where(
                    BranchModel.tenant_id == tenant_id, BranchModel.is_active.is_(True)
                )
            )
        )
        has_cash_point = bool(
            self.db.scalar(
                select(func.count(CashPointModel.id)).where(
                    CashPointModel.tenant_id == tenant_id, CashPointModel.is_active.is_(True)
                )
            )
        )
        sucursal_y_caja = has_branch and has_cash_point

        marca_configurada = bool(tenant.logo_url and tenant.brand_color)

        products_with_photo = (
            self.db.scalar(
                select(func.count(func.distinct(ProductModel.id)))
                .join(ProductImageModel, ProductImageModel.product_id == ProductModel.id)
                .where(
                    ProductModel.tenant_id == tenant_id,
                    ProductModel.is_active.is_(True),
                )
            )
            or 0
        )
        prendas_publicadas = products_with_photo >= 3

        has_payment = bool(
            self.db.scalar(
                select(func.count(TenantPaymentMethodModel.id)).where(
                    TenantPaymentMethodModel.tenant_id == tenant_id,
                    TenantPaymentMethodModel.is_active.is_(True),
                )
            )
        )

        tienda_publicada = tenant.is_published

        all_steps = [
            ("empresa_creada", True),
            ("sucursal_y_caja", sucursal_y_caja),
            ("marca_configurada", marca_configurada),
            ("prendas_publicadas", prendas_publicadas),
            ("metodo_cobro", has_payment),
            ("tienda_publicada", tienda_publicada),
        ]

        completed = [name for name, done in all_steps if done]
        pending = [name for name, done in all_steps if not done]
        pct = int(len(completed) / len(all_steps) * 100)

        is_ready = sucursal_y_caja and marca_configurada and prendas_publicadas and has_payment

        return OnboardingOut(
            completed_steps=completed,
            pending_steps=pending,
            is_ready_to_publish=is_ready,
            progress_percentage=pct,
        )
