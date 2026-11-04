from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, joinedload

from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.infrastructure.security.tenancy import TenantContext
from src.inventario_sucursales.infrastructure.models.organization import BranchModel
from src.plataforma_saas.application.support_service import SupportService
from src.plataforma_saas.domain.exceptions import TenantNotFoundError
from src.plataforma_saas.infrastructure.models.plan import PlanModel
from src.plataforma_saas.infrastructure.models.subscription import SubscriptionModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.plataforma_saas.web.schemas.support import SupportSessionResponse
from src.plataforma_saas.web.schemas.tenant_admin import (
    OrderBrief,
    PlanUsage,
    ReservationBrief,
    TenantDashboard,
    TenantProfile,
    TenantProfileUpdate,
)
from src.reservas.infrastructure.persistence.models.reserva import ReservationModel
from src.shared.exceptions.domain_exception import NotFoundError
from src.shared.responses.pagination import Page
from src.ventas_pagos.infrastructure.models import OrderModel, StockModel


class TenantAdminService:
    def __init__(self, db: Session, ctx: TenantContext) -> None:
        self.db = db
        self.ctx = ctx

    def panel(self, branch_id: UUID | None, today: date) -> TenantDashboard:
        tenant_id = self.ctx.tenant_id

        if branch_id is not None:
            branch = self.db.scalar(
                select(BranchModel).where(
                    BranchModel.id == branch_id,
                    BranchModel.tenant_id == tenant_id,
                    BranchModel.deleted_at.is_(None),
                )
            )
            if not branch:
                raise NotFoundError("Sucursal no encontrada.")

        today_start = datetime.combine(today, time.min)
        today_end = datetime.combine(today, time.max)
        yesterday_start = datetime.combine(today - timedelta(days=1), time.min)
        yesterday_end = datetime.combine(today - timedelta(days=1), time.max)

        # 1. Orders today
        order_stmt = select(
            func.count(OrderModel.id).label("count"),
            func.coalesce(func.sum(OrderModel.total), Decimal("0.00")).label("sales"),
        ).where(
            OrderModel.tenant_id == tenant_id,
            OrderModel.created_at >= today_start,
            OrderModel.created_at <= today_end,
            OrderModel.status != "cancelled",
        )
        if branch_id is not None:
            order_stmt = order_stmt.where(OrderModel.branch_id == branch_id)

        order_res = self.db.execute(order_stmt).one()
        orders_today = order_res.count or 0
        sales_today = Decimal(str(order_res.sales or "0.00")).quantize(Decimal("0.01"))

        # Sales yesterday for delta
        order_y_stmt = select(
            func.coalesce(func.sum(OrderModel.total), Decimal("0.00"))
        ).where(
            OrderModel.tenant_id == tenant_id,
            OrderModel.created_at >= yesterday_start,
            OrderModel.created_at <= yesterday_end,
            OrderModel.status != "cancelled",
        )
        if branch_id is not None:
            order_y_stmt = order_y_stmt.where(OrderModel.branch_id == branch_id)

        sales_yesterday = Decimal(str(self.db.scalar(order_y_stmt) or "0.00"))
        if sales_yesterday > Decimal("0.00"):
            sales_delta_pct = round(
                float((sales_today - sales_yesterday) / sales_yesterday * 100), 1
            )
        else:
            sales_delta_pct = None

        # 2. Reservations today
        res_stmt = select(func.count(ReservationModel.id)).where(
            ReservationModel.tenant_id == tenant_id,
            ReservationModel.scheduled_at >= today_start,
            ReservationModel.scheduled_at <= today_end,
        )
        if branch_id is not None:
            res_stmt = res_stmt.where(ReservationModel.branch_id == branch_id)
        reservations_today = self.db.scalar(res_stmt) or 0

        # In fitting room
        fit_stmt = select(func.count(ReservationModel.id)).where(
            ReservationModel.tenant_id == tenant_id,
            ReservationModel.status.in_(["in_fitting_room", "fitting", "in_progress"]),
        )
        if branch_id is not None:
            fit_stmt = fit_stmt.where(ReservationModel.branch_id == branch_id)
        in_fitting_room = self.db.scalar(fit_stmt) or 0

        # 3. Critical stock (quantity <= 2)
        stock_stmt = (
            select(func.count(StockModel.id))
            .join(BranchModel, StockModel.branch_id == BranchModel.id)
            .where(
                BranchModel.tenant_id == tenant_id,
                BranchModel.deleted_at.is_(None),
                StockModel.quantity <= 2,
            )
        )
        if branch_id is not None:
            stock_stmt = stock_stmt.where(StockModel.branch_id == branch_id)
        critical_stock = self.db.scalar(stock_stmt) or 0

        # 4. Plan usage
        active_branches = (
            self.db.scalar(
                select(func.count(BranchModel.id)).where(
                    BranchModel.tenant_id == tenant_id,
                    BranchModel.is_active.is_(True),
                    BranchModel.deleted_at.is_(None),
                )
            )
            or 0
        )
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
        max_branches = None
        if sub and sub.plan:
            f = next(
                (
                    feat
                    for feat in sub.plan.features
                    if feat.feature_code == "max_active_branches"
                ),
                None,
            )
            if f:
                max_branches = f.limit_value

        plan_usage = PlanUsage(
            active_branches=active_branches,
            max_branches=max_branches,
        )

        # 5. Recent orders
        rec_orders_stmt = select(OrderModel).where(OrderModel.tenant_id == tenant_id)
        if branch_id is not None:
            rec_orders_stmt = rec_orders_stmt.where(OrderModel.branch_id == branch_id)

        rec_orders_db = (
            self.db.execute(
                rec_orders_stmt.order_by(desc(OrderModel.created_at)).limit(5)
            )
            .scalars()
            .all()
        )
        recent_orders = [
            OrderBrief(
                id=o.id,
                code=o.number,
                total=o.total,
                channel="pos" if (o.sales_channel or "").lower() == "pos" else "online",
                payment_method=o.payment_method,
                status=o.status,
                created_at=o.created_at,
            )
            for o in rec_orders_db
        ]

        # 6. Upcoming reservations
        rec_res_stmt = select(ReservationModel).where(
            ReservationModel.tenant_id == tenant_id
        )
        if branch_id is not None:
            rec_res_stmt = rec_res_stmt.where(ReservationModel.branch_id == branch_id)

        rec_res_db = (
            self.db.execute(
                rec_res_stmt.order_by(ReservationModel.scheduled_at.asc()).limit(5)
            )
            .scalars()
            .all()
        )
        upcoming_reservations = []
        for r in rec_res_db:
            cust_name = "Cliente"
            if r.user_id:
                u = self.db.get(UserModel, r.user_id)
                if u:
                    cust_name = f"{u.first_name} {u.last_name}".strip()
            item_count = len(r.items) if isinstance(r.items, list) else 1
            upcoming_reservations.append(
                ReservationBrief(
                    id=r.id,
                    customer_name=cust_name,
                    items=item_count,
                    starts_at=r.scheduled_at,
                    status=r.status,
                    origin="offline" if r.origin == "offline" else "online",
                )
            )

        return TenantDashboard(
            sales_today=sales_today,
            orders_today=orders_today,
            sales_delta_pct=sales_delta_pct,
            reservations_today=reservations_today,
            in_fitting_room=in_fitting_room,
            critical_stock=critical_stock,
            plan_usage=plan_usage,
            recent_orders=recent_orders,
            upcoming_reservations=upcoming_reservations,
        )

    def perfil(self) -> TenantProfile:
        tenant = self.db.get(TenantModel, self.ctx.tenant_id)
        if not tenant:
            raise TenantNotFoundError()
        return TenantProfile(
            id=tenant.id,
            legal_name=tenant.legal_name,
            trade_name=tenant.trade_name,
            tax_id=tenant.tax_id,
            slug=tenant.slug,
            contact_email=tenant.contact_email,
            phone=tenant.phone,
        )

    def actualizar_perfil(self, data: TenantProfileUpdate) -> TenantProfile:
        tenant = self.db.get(TenantModel, self.ctx.tenant_id)
        if not tenant:
            raise TenantNotFoundError()

        if data.trade_name is not None:
            tenant.trade_name = data.trade_name.strip()
        if data.contact_email is not None:
            tenant.contact_email = str(data.contact_email).lower()
        if data.phone is not None:
            tenant.phone = data.phone.strip()

        event = AuditEventModel(
            tenant_id=self.ctx.tenant_id,
            support_session_id=self.ctx.support_session_id,
            actor_user_id=self.ctx.user.id if self.ctx.user else None,
            action="tenant.profile_updated",
            entity_type="tenant",
            entity_id=str(tenant.id),
            description="Perfil de empresa actualizado",
        )
        self.db.add(event)
        self.db.commit()
        return self.perfil()

    def accesos_soporte(
        self, page: int, page_size: int
    ) -> Page[SupportSessionResponse]:
        tenant_id = self.ctx.tenant_id
        service = SupportService(self.db, self.ctx.user)
        return service.listar(tenant_id=tenant_id, page=page, page_size=page_size)
