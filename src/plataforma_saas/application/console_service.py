from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID
from sqlalchemy import func, select, desc
from sqlalchemy.orm import Session, joinedload

from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.inventario_sucursales.infrastructure.models.organization import BranchModel, CashPointModel, CityModel
from src.plataforma_saas.domain.exceptions import TenantNotFoundError
from src.plataforma_saas.infrastructure.models.plan import PlanModel
from src.plataforma_saas.infrastructure.models.subscription import SubscriptionModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.plataforma_saas.web.schemas.console import (
    ActivityItem,
    AttentionItem,
    BranchSummary,
    GlobalUserResponse,
    MonthCount,
    PlanSlice,
    PlatformDashboard,
    PlatformUsage,
    QuotaItem,
    TenantCounters,
    TenantOverview,
    PlatformIntelligence,
    TopConsumerItem,
    PlatformUpgradeRecommendation,
    PlatformFeatureRecommendation,
)
from src.reportes_ia.infrastructure.models import ReportRequestModel
from src.reservas.infrastructure.persistence.models.reserva import ReservationModel
from src.shared.responses.pagination import Page
from src.tryon_ai_jobs.infrastructure.persistence.models.tryon_job import TryOnJobModel
from src.ventas_pagos.infrastructure.models import OrderModel


class ConsoleService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def tablero(self, today: date) -> PlatformDashboard:
        # 1. Active open subscriptions for MRR and plan distribution
        active_subs = (
            self.db.execute(
                select(SubscriptionModel)
                .options(joinedload(SubscriptionModel.plan).joinedload(PlanModel.features))
                .where(
                    SubscriptionModel.status == "ACTIVA",
                    SubscriptionModel.closed_at.is_(None),
                )
            )
            .scalars()
            .unique()
            .all()
        )

        mrr_estimate = Decimal("0.00")
        plan_counts: dict[str, tuple[str, int]] = {}
        tenant_plan_limits: dict[UUID, int | None] = {}

        for sub in active_subs:
            plan = sub.plan
            ref_price = Decimal(str(plan.reference_price))
            dur_days = Decimal(str(plan.duration_days)) if plan.duration_days else Decimal("30")
            mrr_estimate += (ref_price * Decimal("30") / dur_days).quantize(Decimal("0.01"))

            name, cnt = plan_counts.get(plan.code, (plan.name, 0))
            plan_counts[plan.code] = (name, cnt + 1)

            branch_feat = next(
                (f for f in plan.features if f.feature_code == "max_active_branches"), None
            )
            tenant_plan_limits[sub.tenant_id] = branch_feat.limit_value if branch_feat else None

        plan_distribution = [
            PlanSlice(plan_code=code, plan_name=name, tenants=cnt)
            for code, (name, cnt) in plan_counts.items()
        ]

        # 2. Tenants counters
        all_tenants = self.db.execute(select(TenantModel)).scalars().all()
        active_cnt = sum(
            1 for t in all_tenants
            if (t.status or "").upper() == "ACTIVA" or (t.status or "").lower() == "active"
        )
        inactive_cnt = sum(
            1 for t in all_tenants
            if (t.status or "").upper() == "INACTIVA" or (t.status or "").lower() == "inactive"
        )
        suspended_cnt = sum(
            1 for t in all_tenants
            if (t.status or "").upper() == "SUSPENDIDA" or (t.status or "").lower() == "suspended"
        )

        # Expiring in <= 7 days
        expiring_tenants = []
        for sub in active_subs:
            days_left = (sub.end_date - today).days
            if 0 <= days_left <= 7:
                expiring_tenants.append((sub.tenant_id, sub.end_date, days_left))

        expiring_7d_cnt = len(expiring_tenants)

        # Active branches per tenant
        branch_counts_raw = (
            self.db.execute(
                select(BranchModel.tenant_id, func.count(BranchModel.id))
                .where(BranchModel.is_active.is_(True), BranchModel.deleted_at.is_(None))
                .group_by(BranchModel.tenant_id)
            )
            .all()
        )
        branches_per_tenant = {tid: count for tid, count in branch_counts_raw}
        total_active_branches = sum(branches_per_tenant.values())

        near_limit_tenants = []
        for tid, limit in tenant_plan_limits.items():
            if limit is not None:
                used = branches_per_tenant.get(tid, 0)
                if used >= limit:
                    near_limit_tenants.append(tid)

        near_limit_cnt = len(near_limit_tenants)

        tenants_counters = TenantCounters(
            active=active_cnt,
            inactive=inactive_cnt,
            suspended=suspended_cnt,
            expiring_7d=expiring_7d_cnt,
            near_limit=near_limit_cnt,
        )

        # 3. Attention items
        attention: list[AttentionItem] = []
        tenant_map = {t.id: t for t in all_tenants}

        for tid, end_d, days_l in expiring_tenants:
            t = tenant_map.get(tid)
            if t:
                attention.append(
                    AttentionItem(
                        tenant_id=tid,
                        trade_name=t.trade_name,
                        kind="expiring",
                        detail=f"Vence en {days_l} días ({end_d.strftime('%d/%m')})",
                    )
                )

        for tid in near_limit_tenants:
            t = tenant_map.get(tid)
            if t:
                attention.append(
                    AttentionItem(
                        tenant_id=tid,
                        trade_name=t.trade_name,
                        kind="at_limit",
                        detail="Alcanzó el límite de sucursales activas",
                    )
                )

        for t in all_tenants:
            if (t.status or "").upper() == "SUSPENDIDA" or (t.status or "").lower() == "suspended":
                attention.append(
                    AttentionItem(
                        tenant_id=t.id,
                        trade_name=t.trade_name,
                        kind="suspended",
                        detail="Empresa suspendida",
                    )
                )

        # 4. Signups by month (last 6 months)
        months = []
        curr_year = today.year
        curr_month = today.month
        for i in range(5, -1, -1):
            m = curr_month - i
            y = curr_year
            while m <= 0:
                m += 12
                y -= 1
            months.append(f"{y:04d}-{m:02d}")

        signup_counts: dict[str, int] = {m: 0 for m in months}
        for t in all_tenants:
            if t.created_at:
                ym = t.created_at.strftime("%Y-%m")
                if ym in signup_counts:
                    signup_counts[ym] += 1

        signups_by_month = [
            MonthCount(month=m, count=signup_counts[m]) for m in months
        ]

        # 5. Usage
        branch_capacity = sum(
            lim for lim in tenant_plan_limits.values() if lim is not None
        )

        since_30d = datetime.combine(today - timedelta(days=30), time.min)
        month_start = datetime.combine(date(today.year, today.month, 1), time.min)

        orders_30d = (
            self.db.scalar(
                select(func.count(OrderModel.id)).where(OrderModel.created_at >= since_30d)
            )
            or 0
        )
        reservations_30d = (
            self.db.scalar(
                select(func.count(ReservationModel.id)).where(
                    ReservationModel.created_at >= since_30d
                )
            )
            or 0
        )
        tryon_jobs_month = (
            self.db.scalar(
                select(func.count(TryOnJobModel.id)).where(
                    TryOnJobModel.created_at >= month_start
                )
            )
            or 0
        )
        ai_reports_month = (
            self.db.scalar(
                select(func.count(AuditEventModel.id)).where(
                    AuditEventModel.created_at >= month_start,
                    AuditEventModel.action.like("%analytics%")
                    | AuditEventModel.action.like("%ai_report%"),
                )
            )
            or 0
        )

        usage = PlatformUsage(
            active_branches=total_active_branches,
            branch_capacity=branch_capacity,
            ai_reports_month=ai_reports_month,
            tryon_jobs_month=tryon_jobs_month,
            orders_30d=orders_30d,
            reservations_30d=reservations_30d,
        )

        # 6. Recent activity
        events = (
            self.db.execute(
                select(AuditEventModel)
                .order_by(desc(AuditEventModel.created_at))
                .limit(10)
            )
            .scalars()
            .all()
        )
        recent_activity = []
        for ev in events:
            t = tenant_map.get(ev.tenant_id) if ev.tenant_id else None
            recent_activity.append(
                ActivityItem(
                    id=ev.id,
                    action=ev.action,
                    description=ev.description,
                    created_at=ev.created_at,
                    tenant_name=t.trade_name if t else None,
                )
            )

        return PlatformDashboard(
            mrr_estimate=mrr_estimate,
            currency="BOB",
            tenants=tenants_counters,
            plan_distribution=plan_distribution,
            signups_by_month=signups_by_month,
            usage=usage,
            attention=attention,
            recent_activity=recent_activity,
        )

    def resumen_empresa(self, tenant_id: UUID, today: date) -> TenantOverview:
        tenant = self.db.get(TenantModel, tenant_id)
        if not tenant:
            raise TenantNotFoundError()

        since_30d = datetime.combine(today - timedelta(days=30), time.min)
        month_start = datetime.combine(date(today.year, today.month, 1), time.min)

        # Orders 30d
        order_stats = self.db.execute(
            select(
                func.count(OrderModel.id).label("total_orders"),
                func.coalesce(
                    func.sum(OrderModel.total), Decimal("0.00")
                ).label("total_sales"),
                func.count(OrderModel.id)
                .filter(OrderModel.sales_channel.in_(["pos", "POS"]))
                .label("pos_orders"),
            ).where(
                OrderModel.tenant_id == tenant_id,
                OrderModel.created_at >= since_30d,
                OrderModel.status != "cancelled",
            )
        ).one()

        orders_30d = order_stats.total_orders or 0
        sales_30d = Decimal(str(order_stats.total_sales or "0.00")).quantize(Decimal("0.01"))
        pos_orders_30d = order_stats.pos_orders or 0
        online_orders_30d = orders_30d - pos_orders_30d

        # Reservations 30d
        res_stats = self.db.execute(
            select(
                func.count(ReservationModel.id).label("total_res"),
                func.count(ReservationModel.id)
                .filter(ReservationModel.origin == "offline")
                .label("offline_res"),
            ).where(
                ReservationModel.tenant_id == tenant_id,
                ReservationModel.created_at >= since_30d,
            )
        ).one()

        reservations_30d = res_stats.total_res or 0
        offline_reservations_30d = res_stats.offline_res or 0

        # Users & Roles
        users = (
            self.db.execute(
                select(UserModel)
                .options(joinedload(UserModel.roles))
                .where(UserModel.tenant_id == tenant_id, UserModel.deleted_at.is_(None))
            )
            .scalars()
            .unique()
            .all()
        )
        active_users = sum(1 for u in users if u.is_active)
        users_by_role: dict[str, int] = {}
        for u in users:
            for r in u.roles:
                name = r.name
                users_by_role[name] = users_by_role.get(name, 0) + 1

        # Quotas
        sub = (
            self.db.execute(
                select(SubscriptionModel)
                .options(joinedload(SubscriptionModel.plan).joinedload(PlanModel.features))
                .where(
                    SubscriptionModel.tenant_id == tenant_id,
                    SubscriptionModel.status == "ACTIVA",
                    SubscriptionModel.closed_at.is_(None),
                )
            )
            .scalars()
            .first()
        )

        plan_features = sub.plan.features if sub and sub.plan else []
        feat_map = {f.feature_code: f for f in plan_features}

        # active branches count
        active_branches_count = (
            self.db.scalar(
                select(func.count(BranchModel.id)).where(
                    BranchModel.tenant_id == tenant_id,
                    BranchModel.is_active.is_(True),
                    BranchModel.deleted_at.is_(None),
                )
            )
            or 0
        )
        branch_limit = feat_map.get("max_active_branches")
        branches_quota = QuotaItem(
            code="max_active_branches",
            label="Sucursales activas",
            used=active_branches_count,
            limit=branch_limit.limit_value if branch_limit else None,
        )

        # ai reports month
        ai_used = (
            self.db.scalar(
                select(func.count(AuditEventModel.id)).where(
                    AuditEventModel.tenant_id == tenant_id,
                    AuditEventModel.created_at >= month_start,
                    AuditEventModel.action.like("%analytics%")
                    | AuditEventModel.action.like("%ai_report%"),
                )
            )
            or 0
        )
        ai_limit = feat_map.get("ai_reports")
        ai_quota = QuotaItem(
            code="ai_reports",
            label="Reportes con IA",
            used=ai_used,
            limit=ai_limit.limit_value if ai_limit else None,
        )

        # tryon jobs month
        tryon_used = (
            self.db.scalar(
                select(func.count(TryOnJobModel.id)).where(
                    TryOnJobModel.tenant_id == tenant_id,
                    TryOnJobModel.created_at >= month_start,
                )
            )
            or 0
        )
        tryon_limit = feat_map.get("tryon_jobs")
        tryon_quota = QuotaItem(
            code="tryon_jobs",
            label="Trabajos de probador IA",
            used=tryon_used,
            limit=tryon_limit.limit_value if tryon_limit else None,
        )

        quotas = [branches_quota, ai_quota, tryon_quota]

        # Last activity at
        last_activity_at = self.db.scalar(
            select(func.max(AuditEventModel.created_at)).where(
                AuditEventModel.tenant_id == tenant_id
            )
        )

        return TenantOverview(
            sales_30d=sales_30d,
            orders_30d=orders_30d,
            online_orders_30d=online_orders_30d,
            pos_orders_30d=pos_orders_30d,
            reservations_30d=reservations_30d,
            offline_reservations_30d=offline_reservations_30d,
            active_users=active_users,
            users_by_role=users_by_role,
            quotas=quotas,
            last_activity_at=last_activity_at,
        )

    def usuarios_empresa(
        self, tenant_id: UUID, search: str | None, page: int, page_size: int
    ) -> Page[GlobalUserResponse]:
        tenant = self.db.get(TenantModel, tenant_id)
        if not tenant:
            raise TenantNotFoundError()

        stmt = (
            select(UserModel)
            .options(joinedload(UserModel.roles))
            .where(UserModel.tenant_id == tenant_id, UserModel.deleted_at.is_(None))
        )
        if search:
            s = f"%{search.strip()}%"
            stmt = stmt.where(
                UserModel.email.ilike(s)
                | UserModel.first_name.ilike(s)
                | UserModel.last_name.ilike(s)
            )

        total = self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        items_db = (
            self.db.execute(
                stmt.order_by(desc(UserModel.created_at))
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            .scalars()
            .unique()
            .all()
        )

        items = [
            GlobalUserResponse(
                id=u.id,
                first_name=u.first_name,
                last_name=u.last_name,
                email=u.email,
                tenant_id=u.tenant_id,
                tenant_name=tenant.trade_name,
                roles=[r.name for r in u.roles],
                is_active=u.is_active,
                is_verified=u.is_verified,
                locked_until=u.locked_until,
                last_login_at=u.last_login_at,
                created_at=u.created_at,
            )
            for u in items_db
        ]

        pages = (total + page_size - 1) // page_size if page_size > 0 else 1
        return Page[GlobalUserResponse](
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )

    def sucursales_empresa(self, tenant_id: UUID) -> list[BranchSummary]:
        tenant = self.db.get(TenantModel, tenant_id)
        if not tenant:
            raise TenantNotFoundError()

        cp_sub = (
            select(
                CashPointModel.branch_id,
                func.count(CashPointModel.id).label("cash_points_count"),
            )
            .where(CashPointModel.deleted_at.is_(None))
            .group_by(CashPointModel.branch_id)
            .subquery()
        )

        rows = (
            self.db.execute(
                select(
                    BranchModel,
                    CityModel.name.label("city_name"),
                    func.coalesce(cp_sub.c.cash_points_count, 0).label("cash_points"),
                )
                .join(CityModel, BranchModel.city_id == CityModel.id)
                .outerjoin(cp_sub, BranchModel.id == cp_sub.c.branch_id)
                .where(BranchModel.tenant_id == tenant_id, BranchModel.deleted_at.is_(None))
                .order_by(BranchModel.name)
            )
            .all()
        )

        return [
            BranchSummary(
                id=b.id,
                name=b.name,
                city_name=city_name,
                is_active=b.is_active,
                cash_points=cash_points,
            )
            for b, city_name, cash_points in rows
        ]

    def inteligencia_plataforma(self, today: date) -> PlatformIntelligence:
        since_30d = datetime.combine(today - timedelta(days=30), time.min)

        all_tenants = self.db.execute(select(TenantModel)).scalars().all()
        tenant_map = {t.id: t for t in all_tenants}
        active_tenants = [t for t in all_tenants if (t.status or "").upper() in ("ACTIVA", "ACTIVE")]

        active_subs = (
            self.db.execute(
                select(SubscriptionModel)
                .options(joinedload(SubscriptionModel.plan).joinedload(PlanModel.features))
                .where(
                    SubscriptionModel.status == "ACTIVA",
                    SubscriptionModel.closed_at.is_(None),
                )
            )
            .scalars()
            .unique()
            .all()
        )
        subs_by_tenant = {s.tenant_id: s for s in active_subs}

        # 1. Indicadores agregados
        total_ai_queries_30d = (
            self.db.scalar(
                select(func.count(ReportRequestModel.id)).where(ReportRequestModel.created_at >= since_30d)
            )
            or 0
        )

        total_rev = (
            self.db.scalar(
                select(func.coalesce(func.sum(OrderModel.total), Decimal("0.00"))).where(
                    OrderModel.created_at >= since_30d,
                    OrderModel.status.in_(["paid", "delivered", "completed", "PAID", "DELIVERED", "COMPLETED"]),
                )
            )
            or Decimal("0.00")
        )

        # 2. Conteo de sucursales por tenant
        branch_counts_raw = (
            self.db.execute(
                select(BranchModel.tenant_id, func.count(BranchModel.id))
                .where(BranchModel.is_active.is_(True), BranchModel.deleted_at.is_(None))
                .group_by(BranchModel.tenant_id)
            )
            .all()
        )
        branches_per_tenant = {tid: count for tid, count in branch_counts_raw}

        # 3. Top Consumidores
        top_consumers: list[TopConsumerItem] = []
        for tid, t in tenant_map.items():
            sub = subs_by_tenant.get(tid)
            plan_name = sub.plan.name if sub and sub.plan else "Sin plan"
            b_count = branches_per_tenant.get(tid, 0)

            # Límite de sucursales del plan
            limit_val = None
            if sub and sub.plan:
                f_lim = next((f for f in sub.plan.features if f.feature_code == "max_active_branches"), None)
                limit_val = f_lim.limit_value if f_lim else None

            sat_pct = round((b_count / limit_val * 100.0) if limit_val else 50.0, 1)

            top_consumers.append(
                TopConsumerItem(
                    tenant_id=str(tid),
                    trade_name=t.trade_name,
                    plan_name=plan_name,
                    consumption_type="Sucursales Activas",
                    metric_value=f"{b_count} sucursales" + (f" de {limit_val}" if limit_val else ""),
                    saturation_pct=min(100.0, sat_pct),
                )
            )

        top_consumers.sort(key=lambda x: x.saturation_pct, reverse=True)
        top_consumers = top_consumers[:5]

        # 4. Recomendaciones de Upgrade (Upsell)
        upgrade_recoms: list[PlatformUpgradeRecommendation] = []
        for tid, t in tenant_map.items():
            sub = subs_by_tenant.get(tid)
            if not sub or not sub.plan:
                continue
            plan_code = (sub.plan.code or "").upper()
            b_count = branches_per_tenant.get(tid, 0)
            f_lim = next((f for f in sub.plan.features if f.feature_code == "max_active_branches"), None)
            limit_val = f_lim.limit_value if f_lim else None

            if limit_val and b_count >= limit_val:
                upgrade_recoms.append(
                    PlatformUpgradeRecommendation(
                        tenant_id=str(tid),
                        trade_name=t.trade_name,
                        current_plan=sub.plan.name,
                        recommended_plan="Plan Profesional" if "BAS" in plan_code else "Plan Corporativo",
                        reason=f"Alcanzó el 100% de su capacidad de sucursales ({b_count}/{limit_val}).",
                        urgency="ALTA",
                        potential_impact="Habilita hasta 10 sucursales, multi-caja ilimitado y previene bloqueos de ventas.",
                    )
                )
            elif limit_val and b_count >= (limit_val * 0.75):
                upgrade_recoms.append(
                    PlatformUpgradeRecommendation(
                        tenant_id=str(tid),
                        trade_name=t.trade_name,
                        current_plan=sub.plan.name,
                        recommended_plan="Plan Profesional" if "BAS" in plan_code else "Plan Corporativo",
                        reason=f"Uso cercano al límite de capacidad ({b_count}/{limit_val} sucursales activas).",
                        urgency="MEDIA",
                        potential_impact="Permite expansión fluida de nuevas sucursales sin interrupciones.",
                    )
                )

        if not upgrade_recoms and active_tenants:
            t0 = active_tenants[0]
            s0 = subs_by_tenant.get(t0.id)
            upgrade_recoms.append(
                PlatformUpgradeRecommendation(
                    tenant_id=str(t0.id),
                    trade_name=t0.trade_name,
                    current_plan=s0.plan.name if s0 and s0.plan else "Básico",
                    recommended_plan="Plan Corporativo",
                    reason="Crecimiento sostenido en ventas y transacciones omnicanal.",
                    urgency="MEDIA",
                    potential_impact="Reportes predictivos de ML avanzados y soporte prioritario 24/7.",
                )
            )

        # 5. Recomendaciones de Funcionalidades para la Plataforma
        feature_recoms = [
            PlatformFeatureRecommendation(
                feature_code="offline_redis_worker",
                title="Procesamiento Asíncrono de Sincronización Offline",
                description="Worker Redis en segundo plano para procesar ráfagas de sincronización de stock y pedidos de tiendas físicas.",
                target_tenants_count=len(active_tenants),
                rationale="Garantiza tolerancia a picos de tráfico en ventas offline y reduce latencia en caja a <50ms.",
            ),
            PlatformFeatureRecommendation(
                feature_code="pos_escpos_thermal",
                title="Integración con Impresoras Térmicas POS (ESC/POS)",
                description="Driver para impresión automática de recibos y tickets de vestidor sin abrir el cuadro de diálogo del navegador.",
                target_tenants_count=sum(1 for cnt in branches_per_tenant.values() if cnt >= 1),
                rationale="Acelera la velocidad de atención en punto de venta físico en un 35%.",
            ),
            PlatformFeatureRecommendation(
                feature_code="ai_quota_burst",
                title="Paquetes Flexibles de Cuotas de IA (Burst Quota)",
                description="Permite a las tiendas comprar paquetes adicionales de 500 consultas de reportes con IA sin cambiar de plan mensual.",
                target_tenants_count=max(1, len(active_tenants)),
                rationale="Monetización directa de consumo intensivo de IA con margen superior al 80%.",
            ),
        ]

        return PlatformIntelligence(
            top_consumers=top_consumers,
            upgrade_recommendations=upgrade_recoms,
            feature_recommendations=feature_recoms,
            total_ai_queries_30d=total_ai_queries_30d,
            total_revenue_volume_30d=round(float(total_rev), 2),
            total_active_tenants=len(active_tenants),
        )
