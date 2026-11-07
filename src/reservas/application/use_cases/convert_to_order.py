"""A reservation transfers its stock hold to exactly one payable order."""
import hashlib
import json
import uuid
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from src.auth.infrastructure.persistence.models.user import UserModel
from src.reservas.infrastructure.persistence.models.reserva import ReservationModel
from src.shared.exceptions.domain_exception import ConflictError, NotFoundError, ValidationError
from src.ventas_pagos.application.promotions import PromotionService
from src.ventas_pagos.application.service import CommerceService
from src.ventas_pagos.application.stock_service import StockService
from src.ventas_pagos.infrastructure.models import OrderModel


def convert_to_order(db, tenant_id, reservation_id, actor, data, *, owner_only=True):
    reservation = db.scalar(select(ReservationModel).where(
        ReservationModel.id == reservation_id, ReservationModel.tenant_id == tenant_id,
    ).with_for_update().execution_options(populate_existing=True))
    if not reservation or (owner_only and reservation.user_id != actor.id):
        raise NotFoundError("Reserva no encontrada.")
    requested = Counter()
    for item in data.items or []:
        requested[str(item.variant_id)] += item.quantity
    held = {str(item['variant_id']): int(item['quantity']) for item in reservation.items}
    selected = dict(requested) if data.items is not None else held
    fingerprint = hashlib.sha256(json.dumps({
        'items': sorted(selected.items()), 'payment_method': data.payment_method,
    }, sort_keys=True).encode()).hexdigest()
    commerce = CommerceService(db, tenant_id)
    if reservation.order_id:
        order = commerce.order(reservation.order_id)
        if order.request_fingerprint != fingerprint:
            raise ConflictError("La reserva ya tiene un pedido con otras prendas o forma de pago.")
        return order
    if reservation.status not in {'pending', 'confirmed', 'ready', 'attended'}:
        raise ConflictError("Esta reserva no se puede convertir en pedido.")
    if not selected or any(q < 1 or q > held.get(vid, 0) for vid, q in selected.items()):
        raise ValidationError("Seleccioná cantidades que formen parte de la reserva.")
    commerce.branch(reservation.branch_id)
    if not owner_only and actor.tenant_id is not None:
        from src.inventario_sucursales.application.services.user_branch_service import UserBranchService
        from src.shared.exceptions.domain_exception import AuthorizationError
        if not UserBranchService(db, tenant_id).puede_operar(actor, reservation.branch_id):
            raise AuthorizationError('No tiene acceso a la sucursal de esta reserva.')
    customer = db.get(UserModel, reservation.user_id)
    if not customer or customer.deleted_at or not customer.is_active:
        raise ConflictError("El cliente de la reserva no está disponible.")
    snapshots = [commerce.snapshot(commerce.variant(uuid.UUID(vid)), qty, reservation.branch_id)
                 for vid, qty in sorted(selected.items())]
    quote = PromotionService(db, tenant_id).quote(customer, snapshots, None, lock=True)
    if data.payment_method == 'stripe' and Decimal(quote['total']) > 0:
        from src.plataforma_saas.application.stripe_connect_service import tarjeta_disponible, CardPaymentsUnavailableError
        if not tarjeta_disponible(db, tenant_id):
            raise CardPaymentsUnavailableError()
    try:
        inventory = StockService(db, tenant_id)
        for vid in sorted(held):
            # Held units are already absent from available stock. Release only
            # the clothes the customer declines; never decrement them twice.
            delta = held[vid] - selected.get(vid, 0) if reservation.inventory_held else -selected.get(vid, 0)
            if delta:
                inventory.change(uuid.UUID(vid), reservation.branch_id, delta,
                    'reservation_order_transfer', 'Conversión de reserva a pedido.',
                    reference=str(reservation.id), actor_id=actor.id)
        order = OrderModel(
            tenant_id=tenant_id, number='FS-' + uuid.uuid4().hex[:12].upper(),
            user_id=customer.id, customer_email=customer.email, branch_id=reservation.branch_id,
            payment_method=data.payment_method, sales_channel=data.channel,
            request_fingerprint=fingerprint, total=Decimal(quote['total']),
            subtotal=Decimal(quote['subtotal']), discount_total=Decimal(quote['discount_total']),
            discounts=quote['discounts'], currency='BOB', items=snapshots,
            address={'recipient': f'{customer.first_name} {customer.last_name}'.strip(), 'pickup': True},
            tracking=[{'status': 'pending_payment', 'note': 'Pedido creado desde la reserva; prendas apartadas.',
                       'date': datetime.now(timezone.utc).isoformat()}],
        )
        if order.total == 0:
            order.status = order.payment_status = 'paid'
            order.paid_at = datetime.now(timezone.utc)
        db.add(order)
        db.flush()
        reservation.order_id = order.id
        reservation.status = 'converted'
        reservation.inventory_held = False
        reservation.tracking = [*(reservation.tracking or []), {
            'status': 'converted', 'note': f'Convertida al pedido {order.number}.',
            'date': datetime.now(timezone.utc).isoformat(), 'order_id': str(order.id),
        }]
        PromotionService(db, tenant_id).record_uses(customer, order, quote)
        commerce.audit(order, 'reservation_converted', 'Reserva convertida sin duplicar el apartado de existencias.')
        db.commit()
    except Exception:
        db.rollback()
        raise
    return order
