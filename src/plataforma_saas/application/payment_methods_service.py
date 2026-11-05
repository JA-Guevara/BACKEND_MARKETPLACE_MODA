"""Servicio de gestión de métodos de cobro propios por empresa (RS-3)."""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.plataforma_saas.domain.marca import enmascarar_cuenta
from src.plataforma_saas.infrastructure.models.storefront import TenantPaymentMethodModel
from src.plataforma_saas.web.schemas.storefront import PaymentInstructions, PaymentMethodIn, PaymentMethodOut
from src.shared.exceptions.domain_exception import NotFoundError
from src.ventas_pagos.infrastructure.models import OrderModel


class PaymentMethodsService:
    def __init__(self, db: Session):
        self.db = db

    def listar(self, tenant_id: UUID, *, publico: bool = False) -> list[PaymentMethodOut]:
        query = select(TenantPaymentMethodModel).where(
            TenantPaymentMethodModel.tenant_id == tenant_id
        )
        if publico:
            query = query.where(TenantPaymentMethodModel.is_active.is_(True))

        items = self.db.scalars(
            query.order_by(TenantPaymentMethodModel.sort_order.asc())
        ).all()

        results: list[PaymentMethodOut] = []
        for m in items:
            acc_num = m.account_number
            if publico and acc_num:
                acc_num = enmascarar_cuenta(acc_num)
            results.append(
                PaymentMethodOut(
                    id=m.id,
                    kind=m.kind,
                    label=m.label,
                    qr_image_url=m.qr_image_url,
                    bank_name=m.bank_name,
                    account_holder=m.account_holder,
                    account_number=acc_num,
                    instructions=m.instructions,
                    is_active=m.is_active,
                    sort_order=m.sort_order,
                )
            )
        return results

    def crear(
        self, tenant_id: UUID, data: PaymentMethodIn, actor: UserModel | None = None
    ) -> PaymentMethodOut:
        m = TenantPaymentMethodModel(
            tenant_id=tenant_id,
            kind=data.kind,
            label=data.label,
            qr_image_url=data.qr_image_url,
            bank_name=data.bank_name,
            account_holder=data.account_holder,
            account_number=data.account_number,
            instructions=data.instructions,
            is_active=data.is_active,
            sort_order=data.sort_order,
        )
        self.db.add(m)
        self.db.flush()

        if actor:
            RecordAuditEvent(self.db).execute(
                actor_user_id=actor.id,
                action="tenant.payment_method_created",
                entity_type="tenant_payment_method",
                entity_id=str(m.id),
                description=f"Método de cobro creado: {m.label} ({m.kind}).",
            )

        self.db.commit()
        return PaymentMethodOut.model_validate(m)

    def actualizar(
        self, method_id: UUID, tenant_id: UUID, data: PaymentMethodIn, actor: UserModel | None = None
    ) -> PaymentMethodOut:
        m = self.db.scalar(
            select(TenantPaymentMethodModel).where(
                TenantPaymentMethodModel.id == method_id,
                TenantPaymentMethodModel.tenant_id == tenant_id,
            )
        )
        if m is None:
            raise NotFoundError("Método de cobro no encontrado.")

        m.kind = data.kind
        m.label = data.label
        m.qr_image_url = data.qr_image_url
        m.bank_name = data.bank_name
        m.account_holder = data.account_holder
        m.account_number = data.account_number
        m.instructions = data.instructions
        m.is_active = data.is_active
        m.sort_order = data.sort_order

        if actor:
            RecordAuditEvent(self.db).execute(
                actor_user_id=actor.id,
                action="tenant.payment_method_updated",
                entity_type="tenant_payment_method",
                entity_id=str(m.id),
                description=f"Método de cobro actualizado: {m.label}.",
            )

        self.db.commit()
        return PaymentMethodOut.model_validate(m)

    def desactivar(
        self, method_id: UUID, tenant_id: UUID, actor: UserModel | None = None
    ) -> None:
        m = self.db.scalar(
            select(TenantPaymentMethodModel).where(
                TenantPaymentMethodModel.id == method_id,
                TenantPaymentMethodModel.tenant_id == tenant_id,
            )
        )
        if m is None:
            raise NotFoundError("Método de cobro no encontrado.")

        m.is_active = False

        if actor:
            RecordAuditEvent(self.db).execute(
                actor_user_id=actor.id,
                action="tenant.payment_method_deactivated",
                entity_type="tenant_payment_method",
                entity_id=str(m.id),
                description=f"Método de cobro desactivado: {m.label}.",
            )

        self.db.commit()

    def instrucciones_pedido(self, order_id: UUID, user: UserModel) -> PaymentInstructions:
        order = self.db.get(OrderModel, order_id)
        if order is None:
            raise NotFoundError("Pedido no encontrado.")

        # Verificar que el usuario sea el dueño del pedido o admin de la empresa
        es_dueno = order.user_id == user.id
        es_admin = user.tenant_id == order.tenant_id and any(
            getattr(r, "name", "") in ("admin", "superadmin", "store_manager")
            for r in getattr(user, "roles", [])
        )
        if not (es_dueno or es_admin):
            raise NotFoundError("Pedido no encontrado.")

        methods = self.listar(order.tenant_id, publico=False)
        return PaymentInstructions(
            order_id=order.id,
            order_number=order.number,
            total=order.total,
            methods=methods,
        )
