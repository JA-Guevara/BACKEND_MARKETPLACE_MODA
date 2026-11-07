"""Counter exchanges use authoritative prices, shared quantities and stock locks."""
import hashlib
import json
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
from types import SimpleNamespace
from uuid import UUID, uuid5, NAMESPACE_URL

from sqlalchemy import select

from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.inventario_sucursales.application.services.user_branch_service import UserBranchService
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.shared.exceptions.domain_exception import AuthorizationError, ConflictError, NotFoundError, ValidationError
from src.ventas_pagos.application.returns_service import ReturnsService
from src.ventas_pagos.application.service import CommerceService
from src.ventas_pagos.application.stock_service import StockService
from src.ventas_pagos.application.pricing_service import PricingService
from src.ventas_pagos.domain.cambios import CalculadoraCambio, LineaCambioCalculo, VerificadorPlazoCambio
from src.ventas_pagos.domain import returns
from src.ventas_pagos.infrastructure import gateways
from src.ventas_pagos.infrastructure.exchange_models import GarmentExchangeModel, GarmentExchangeLineModel
from src.ventas_pagos.infrastructure.models import OrderModel


def execute(service, tenant_id, branch_id, actor_id, data):
    db = service.db
    if not data.get('client_request_id'):
        raise ValidationError('El cambio requiere una clave de intento para evitar duplicados.')
    request_id = UUID(str(data['client_request_id']))
    canonical = {k: data.get(k) for k in ['original_order_id', 'branch_id', 'payment_method', 'cash_received', 'cash_returned', 'notes', 'lines']}
    fingerprint = hashlib.sha256(json.dumps(canonical, sort_keys=True, default=str).encode()).hexdigest()
    order = db.scalar(select(OrderModel).where(
        OrderModel.id == UUID(str(data['original_order_id'])), OrderModel.tenant_id == tenant_id,
    ).with_for_update().execution_options(populate_existing=True))
    if not order:
        raise NotFoundError('Pedido no encontrado en esta empresa.')
    actor = db.get(UserModel, actor_id) if actor_id else None
    from src.shared.context.audit_context import get_audit_scope
    support_tenant,support_session=get_audit_scope()
    support=bool(actor and actor.tenant_id is None and support_tenant==tenant_id and support_session)
    if not actor or not (support or UserBranchService(db, tenant_id).puede_operar(actor, branch_id)):
        raise AuthorizationError('No tiene acceso a esta sucursal para registrar cambios.')
    existing = db.scalar(select(GarmentExchangeModel).where(GarmentExchangeModel.client_request_id == request_id))
    if existing:
        if existing.tenant_id != tenant_id or existing.user_id != actor_id or existing.request_fingerprint != fingerprint:
            raise ConflictError('La clave de intento ya fue utilizada para otro cambio.')
        return service.obtener_cambio(tenant_id, existing.id)
    if order.branch_id != branch_id:
        raise ValidationError('Atendé el cambio en la sucursal del pedido original.')
    if order.payment_status != 'paid' or order.status not in {'delivered', 'completed'}:
        raise ConflictError('Solo se cambian prendas de pedidos pagados y entregados.')
    tenant = db.get(TenantModel, tenant_id)
    VerificadorPlazoCambio.verificar(returns.fecha_de_entrega(order) or order.paid_at or order.created_at,
                                    tenant.exchange_days if tenant else 15)
    return_service = ReturnsService(db, tenant_id)
    requested = Counter()
    for row in data['lines']:
        requested[str(row['original_variant_id'])] += int(row['returned_quantity'])
    commitments=return_service.compromisos(order)
    try:
        returns.armar_detalle(order, commitments, list(requested.items()))
    except ValueError as error:
        raise ValidationError(str(error)) from error
    commerce = CommerceService(db, tenant_id)
    originals = {str(row['variant_id']): row for row in order.items}
    subtotal = Decimal(order.subtotal or 0) or sum((Decimal(str(row['unit_price'])) * row['quantity'] for row in order.items), Decimal(0))
    lines = []
    if len(requested)!=len(data['lines']):
        raise ValidationError('Agrupá cada prenda original en una sola línea de cambio.')
    for raw in data['lines']:
        old_id, new_id = UUID(str(raw['original_variant_id'])), UUID(str(raw['new_variant_id']))
        if old_id == new_id:
            raise ValidationError('Elegí una prenda o talla diferente.')
        original = originals.get(str(old_id))
        if not original:
            raise ValidationError('La prenda original no pertenece al pedido.')
        variant = commerce.variant(new_id)
        new_price = PricingService(db,tenant_id).precio(variant,canal='ONLINE').final
        credit=returns.paid_credit(order,old_id,int(raw['returned_quantity']),commitments)
        original_price=(credit/int(raw['returned_quantity'])).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
        lines.append(LineaCambioCalculo(old_id, int(raw['returned_quantity']), original_price,
                                       new_id, int(raw['delivered_quantity']), Decimal(new_price),original_credit=credit))
    result = CalculadoraCambio.calcular(lines)
    difference = result.difference_amount
    method = data.get('payment_method', 'none')
    received = Decimal(str(data.get('cash_received') or 0))
    returned = Decimal(str(data.get('cash_returned') or 0))
    if difference > 0 and (method != 'cash' or received < difference or returned != received - difference):
        raise ConflictError('Confirmá el efectivo recibido y el cambio exacto. Para tarjeta, utilizá la solicitud de cambio con cobro verificado.')
    if difference < 0 and order.payment_method != 'stripe' and (method != 'cash' or received != 0 or returned != -difference):
        raise ConflictError('Confirmá la entrega del reintegro exacto en efectivo.')
    exchange_id = uuid5(NAMESPACE_URL, f'fashionstore-exchange:{tenant_id}:{request_id}')
    exchange = GarmentExchangeModel(id=exchange_id, tenant_id=tenant_id, branch_id=branch_id,
        original_order_id=order.id, user_id=actor_id, customer_id=order.user_id,
        difference_amount=difference, payment_method='stripe' if difference < 0 and order.payment_method == 'stripe' else method,
        cash_received=received, cash_returned=returned, status='COMPLETED', notes=data.get('notes'),
        client_request_id=request_id, request_fingerprint=fingerprint)
    try:
        db.add(exchange)
        db.flush()
        # Acquire every variant in the same order used by online and offline sales.
        inventory = StockService(db, tenant_id)
        for vid in sorted({line.original_variant_id for line in lines} | {line.new_variant_id for line in lines}, key=str):
            inventory.locked_stock(vid, branch_id)
        for line in lines:
            inventory.change(line.new_variant_id, branch_id, -line.delivered_quantity, 'exchange_out',
                'Prenda entregada por cambio.', reference=str(exchange.id), actor_id=actor_id)
            inventory.change(line.original_variant_id, branch_id, line.returned_quantity, 'exchange_in',
                'Prenda recibida por cambio.', reference=str(exchange.id), actor_id=actor_id)
            db.add(GarmentExchangeLineModel(exchange_id=exchange.id,
                original_variant_id=line.original_variant_id, returned_quantity=line.returned_quantity,
                original_unit_price=line.original_unit_price, new_variant_id=line.new_variant_id,
                delivered_quantity=line.delivered_quantity, new_unit_price=line.new_unit_price,
                price_difference=line.difference))
        if difference < 0 and order.payment_method == 'stripe':
            gateways.refund_order_return(order, SimpleNamespace(id=exchange.id, refund_amount=-difference),
                **gateways.en_cuenta(order.stripe_account_id))
        RecordAuditEvent(db).execute(action='commerce.counter_exchange_completed', entity_type='garment_exchange',
            entity_id=str(exchange.id), description='Cambio de prendas recibido y liquidado en línea.',
            actor_user_id=actor_id, metadata={'difference': str(difference), 'order': order.number})
        db.commit()
    except Exception:
        db.rollback()
        raise
    return service.obtener_cambio(tenant_id, exchange.id)
