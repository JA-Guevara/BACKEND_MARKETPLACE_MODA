import uuid
from datetime import datetime
from typing import Annotated
import httpx
from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.web.dependencies import get_current_user, get_optional_user
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_permissions
from src.infrastructure.config.settings import settings
from src.shared.responses.api_response import ApiResponse
from src.usuarios_catalogo.infrastructure.models.catalog import CategoryModel, ProductVariantModel
from src.inventario_sucursales.infrastructure.models.organization import BranchModel
from src.ventas_pagos.infrastructure.models import StockModel, CartItemModel, OrderModel
from src.ventas_pagos.infrastructure.gateways import verify_event
from src.ventas_pagos.application.service import CommerceService
from src.ventas_pagos.application.reports_service import ReportsService
from src.ventas_pagos.application.reports_ai import ReportsAI
from src.ventas_pagos.application import exporter
from src.ventas_pagos.application.multi_export_service import MultiExportService
from src.ventas_pagos.application.assistant_tools import AssistantTools, UnknownToolError
from src.ventas_pagos.web.schemas import Quantity, StockQuantity, CheckoutOrder, TrackingUpdate, ManualPayment, ProfileUpdate, AssistantMessage, ReportFilters, InterpretRequest, ExplainRequest, InsightsRequest, MultiExportRequest, AssistantToolRequest, REPORT_TYPES

router = APIRouter(prefix="/commerce", tags=["commerce"])
analytics_router = APIRouter(prefix="/analytics", tags=["analytics"])
User = Annotated[UserModel, Depends(get_current_user)]
OptionalUser = Annotated[UserModel | None, Depends(get_optional_user)]
Reader = Annotated[UserModel, Depends(require_permissions("commerce.read"))]
Writer = Annotated[UserModel, Depends(require_permissions("commerce.write"))]
StockReader = Annotated[UserModel, Depends(require_permissions("stock.read"))]
StockWriter = Annotated[UserModel, Depends(require_permissions("stock.write"))]
Analyst = Annotated[UserModel, Depends(require_permissions("dashboard.read"))]


def response(data=None):
    return ApiResponse(message="Operacion completada.", data=jsonable_encoder(data))


def order_data(order):
    data = {column.name: getattr(order, column.name) for column in OrderModel.__table__.columns if column.name not in {"stripe_url", "stripe_session_id"}}
    data["total"] = str(order.total)
    return data


@router.get("/branches")
def branches(db: Session = Depends(get_db)):
    return response([{"id": row.id, "name": row.name, "address": row.address} for row in db.scalars(select(BranchModel).where(BranchModel.is_active.is_(True), BranchModel.deleted_at.is_(None))).all()])


@router.get("/recommendations")
def recommendations(user: OptionalUser, db: Session = Depends(get_db)):
    return response(CommerceService(db).recommendations(user))


ASSISTANT_SYSTEM_PROMPT = """Sos el asistente virtual de FashionStore, una tienda de ropa con venta presencial \
y digital. Respondes en espanol, en 2 a 4 oraciones o una lista corta de pasos. No inventes precios, \
stock, promociones ni datos que no esten en este mensaje: si te preguntan eso, indica que lo revisen \
en el catalogo o en su sucursal mas cercana.

Podes ayudar de dos formas: (1) responder dudas de compra (tallas, colores, temporadas, como usar el \
vestidor virtual) y (2) explicar COMO USAR la plataforma. Catalogo de modulos para la segunda parte:
- Catalogo: buscar y filtrar prendas por categoria, talla, color, temporada y precio.
- Ficha de producto: elegir talla/color, agregar al carrito, agregar a una reserva o probar con camara \
(vestidor virtual, solo si la prenda tiene ese recurso cargado).
- Carrito y checkout: revisar cantidades y pagar con tarjeta (Stripe) o coordinar pago presencial.
- Reservas (Nueva reserva / Mis reservas): el cliente junta varias prendas, elige sucursal y \
horario, confirma la reserva, y despues puede seguir el estado (pendiente, confirmada, prendas \
preparadas, atendida) o cancelarla.
- Vestidor virtual: se abre desde la ficha del producto con el boton "Probar con camara"; usa la camara \
del navegador para superponer la prenda.
- Mi cuenta: perfil, direcciones guardadas y mis pedidos.
- Panel de administracion (solo staff): gestion de catalogo, sucursales, usuarios y roles, reservas \
(confirmar/preparar/atender), pedidos y pagos, existencias por sucursal, bitacora de auditoria y el \
dashboard de reportes (KPIs, comparativas por mes/categoria/sucursal/hora/dia y proyeccion de ventas).

Si quien te escribe es staff con permiso de catalogo, tambien podes ACTUAR ademas de explicar (no lo \
hagas vos mismo por este chat: decile que lo pida con los datos completos, por ejemplo "registrame una \
campera de cuero negra a 450 Bs" para dar de alta una prenda, "exportame el reporte de ventas del ultimo \
mes en excel" para descargar un reporte filtrado, o "explicame por que bajaron los pedidos" para que el \
asistente interprete las metricas reales del dashboard)."""


@router.post("/assistant")
def assistant(data: AssistantMessage, user: User, db: Session = Depends(get_db)):
    if not settings.ai_api_key:
        return response({"available": False, "reply": "El asistente de IA no esta configurado todavia. Mientras tanto podes consultar el catalogo o contactar a una sucursal."})
    user_content = data.message
    if data.context:
        user_content = f"Seccion actual del sitio: {data.context}\n\nPregunta: {data.message}"
    try:
        result = httpx.post("https://api.openai.com/v1/chat/completions", headers={"Authorization": "Bearer " + settings.ai_api_key},
            json={"model": settings.ai_model, "messages": [
                {"role": "system", "content": ASSISTANT_SYSTEM_PROMPT},
                {"role": "user", "content": user_content}], "max_tokens": 350}, timeout=25)
        result.raise_for_status()
        return response({"available": True, "reply": result.json()["choices"][0]["message"]["content"]})
    except (httpx.HTTPError, KeyError, ValueError, IndexError):
        return response({"available": False, "reply": "No pude responder en este momento. Intenta de nuevo en unos minutos."})


@router.patch("/profile")
def profile(data: ProfileUpdate, user: User, db: Session = Depends(get_db)):
    for key, value in data.model_dump().items():
        setattr(user, key, value)
    RecordAuditEvent(db).execute(action="commerce.profile_updated", entity_type="user", entity_id=str(user.id), description="Cliente actualizo su perfil.", actor_user_id=user.id)
    db.commit()
    return response({"id": user.id, "email": user.email, "first_name": user.first_name, "last_name": user.last_name, "phone": user.phone})


@router.get("/cart")
def cart(user: User, branch_id: uuid.UUID | None = None, db: Session = Depends(get_db)):
    return response(CommerceService(db).cart(user, branch_id))


@router.put("/cart/items/{variant_id}")
def set_cart(variant_id: uuid.UUID, data: Quantity, user: User, db: Session = Depends(get_db)):
    CommerceService(db).set_cart(user, variant_id, data.quantity)
    return response()


@router.delete("/cart/items/{variant_id}")
def delete_cart(variant_id: uuid.UUID, user: User, db: Session = Depends(get_db)):
    db.execute(select(UserModel.id).where(UserModel.id == user.id).with_for_update())
    db.execute(delete(CartItemModel).where(CartItemModel.user_id == user.id, CartItemModel.variant_id == variant_id))
    db.commit()
    return response()


@router.post("/orders", status_code=201)
def create_order(data: CheckoutOrder, user: User, db: Session = Depends(get_db)):
    return response(order_data(CommerceService(db).create_order(user, data)))


@router.get("/orders")
def orders(user: User, db: Session = Depends(get_db), limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    return response([order_data(o) for o in db.scalars(select(OrderModel).where(OrderModel.user_id == user.id).order_by(OrderModel.created_at.desc()).offset(offset).limit(limit))])


@router.get("/orders/{order_id}")
def get_order(order_id: uuid.UUID, user: User, db: Session = Depends(get_db)):
    return response(order_data(CommerceService(db).order(order_id, user)))


@router.post("/orders/{order_id}/checkout")
def checkout(order_id: uuid.UUID, user: User, db: Session = Depends(get_db)):
    service = CommerceService(db)
    return response(service.checkout(service.order(order_id, user)))


@router.post("/orders/{order_id}/cancel")
def cancel(order_id: uuid.UUID, user: User, db: Session = Depends(get_db)):
    service = CommerceService(db)
    return response(order_data(service.cancel(service.order(order_id, user))))


@router.post("/orders/{order_id}/payment-status")
def reconcile_payment(order_id: uuid.UUID, user: User, db: Session = Depends(get_db)):
    service = CommerceService(db)
    return response(order_data(service.reconcile_payment(service.order(order_id, user))))


@router.post("/admin/orders/{order_id}/payment-status")
def admin_reconcile_payment(order_id: uuid.UUID, user: Writer, db: Session = Depends(get_db)):
    service = CommerceService(db)
    return response(order_data(service.reconcile_payment(service.order(order_id))))


@router.get("/admin/orders")
def admin_orders(user: Reader, db: Session = Depends(get_db), limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    return response([order_data(o) for o in db.scalars(select(OrderModel).order_by(OrderModel.created_at.desc()).offset(offset).limit(limit))])


@router.patch("/admin/orders/{order_id}/tracking")
def tracking(order_id: uuid.UUID, data: TrackingUpdate, user: Writer, db: Session = Depends(get_db)):
    service = CommerceService(db)
    return response(order_data(service.tracking(service.order(order_id), data)))


@router.post("/admin/orders/{order_id}/payment")
def payment(order_id: uuid.UUID, data: ManualPayment, user: Writer, db: Session = Depends(get_db)):
    service = CommerceService(db)
    return response(order_data(service.manual_payment(service.order(order_id), data)))


@router.get("/admin/stock")
def stock(user: StockReader, branch_id: uuid.UUID, db: Session = Depends(get_db)):
    service = CommerceService(db)
    service.branch(branch_id)
    variants = db.scalars(select(ProductVariantModel).where(ProductVariantModel.is_active.is_(True))).all()
    rows_by_variant = {row.variant_id: row.quantity for row in db.execute(
        select(StockModel).where(StockModel.branch_id == branch_id)
    ).scalars()}
    return response([{**service.snapshot(v, 1, branch_id), "branch_id": str(branch_id), "quantity": rows_by_variant.get(v.id, 0)} for v in variants if v.product.is_active and not v.product.deleted_at])


@router.put("/admin/stock/{variant_id}")
def update_stock(variant_id: uuid.UUID, data: StockQuantity, user: StockWriter, db: Session = Depends(get_db)):
    service = CommerceService(db)
    service.branch(data.branch_id)
    service.variant(variant_id)
    # Serialize inserts as well as updates by locking the existing variant.
    db.execute(select(ProductVariantModel.id).where(ProductVariantModel.id == variant_id).with_for_update())
    row = db.scalar(select(StockModel).where(StockModel.variant_id == variant_id, StockModel.branch_id == data.branch_id).with_for_update())
    if row:
        previous = row.quantity
        row.quantity = data.quantity
    else:
        previous = 0
        db.add(StockModel(variant_id=variant_id, branch_id=data.branch_id, quantity=data.quantity))
    RecordAuditEvent(db).execute(action="commerce.stock_adjusted", entity_type="stock", entity_id=str(variant_id), description="Existencias ajustadas por sucursal.", actor_user_id=user.id, metadata={"branch_id":str(data.branch_id),"previous":previous,"quantity":data.quantity})
    db.commit()
    return response({"variant_id": variant_id, **data.model_dump()})


@router.post("/stripe/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    return CommerceService(db).webhook(verify_event(body, request.headers.get("stripe-signature", "")))


@analytics_router.get("/dashboard")
def dashboard(user: Analyst, db: Session = Depends(get_db), date_from: datetime | None = None, date_to: datetime | None = None,
              branch_id: uuid.UUID | None = None, category_id: uuid.UUID | None = None,
              status: str | None = Query(default=None, max_length=30), low_stock_lt: int | None = Query(default=None, ge=0, le=10000)):
    return response(ReportsService(db).dashboard(date_from, date_to, branch_id, category_id, status, low_stock_lt))


@analytics_router.post("/insights")
def insights(user: Analyst, data: InsightsRequest | None = None, db: Session = Depends(get_db)):
    """Recomendaciones de la IA sobre el contexto real (retrocompatible: si no
    se envia cuerpo se usa el dashboard completo)."""
    if not settings.ai_api_key:
        return response({"available": False, "message": "Configure AI_API_KEY para habilitar recomendaciones. Las metricas reales ya estan disponibles."})
    filters = data.filters if data and data.filters else ReportFilters()
    snapshot = ReportsService(db).dashboard(filters.date_from, filters.date_to, filters.branch_id, filters.category_id, filters.status)
    try:
        result = httpx.post("https://api.openai.com/v1/chat/completions", headers={"Authorization": "Bearer " + settings.ai_api_key},
            json={"model": settings.ai_model, "messages": [{"role": "system", "content": "Eres analista de FashionStore. Da 3 recomendaciones breves en espanol basadas solo en metricas agregadas. No inventes tendencias ni causalidad. Senala cuando faltan datos."},
            {"role": "user", "content": str(snapshot)}], "max_tokens": min(450, settings.ai_max_tokens)}, timeout=settings.ai_timeout)
        result.raise_for_status()
        return response({"available": True, "message": result.json()["choices"][0]["message"]["content"]})
    except (httpx.HTTPError, KeyError, ValueError, IndexError):
        return response({"available": False, "message": "El servicio de IA no respondio. Puede continuar usando las metricas reales."})


@analytics_router.post("/assistant/interpret", tags=["analytics"])
def interpret(data: InterpretRequest, user: Analyst, db: Session = Depends(get_db)):
    """Funcion A del asistente de reportes: consulta en lenguaje natural a una
    estructura validada (vista, filtros, agrupacion, metrica, comparacion).
    No modifica datos y resuelve nombres contra el catalogo autorizado."""
    branches = [
        {"id": str(row.id), "name": row.name}
        for row in db.scalars(select(BranchModel).where(BranchModel.is_active.is_(True), BranchModel.deleted_at.is_(None)))
        if row.name
    ]
    categories = [{"id": str(row.id), "name": row.name} for row in db.scalars(select(CategoryModel)) if row.name]
    result = ReportsAI(db).interpret(data.message, data.current, {"branches": branches, "categories": categories})
    return response(result)


@analytics_router.post("/assistant/explain", tags=["analytics"])
def explain(data: ExplainRequest, user: Analyst, db: Session = Depends(get_db)):
    """Funcion B del asistente de reportes: explica metricas agregadas usando
    el contexto de filtros visible. El servidor recalcula las metricas; no
    confia en cifras del navegador."""
    return response(ReportsAI(db).explain(data.question, data.filters or ReportFilters()))


@analytics_router.post("/assistant/execute", tags=["analytics"])
def execute_tool(data: AssistantToolRequest, user: Analyst, db: Session = Depends(get_db)):
    """Ejecuta una herramienta tipada del asistente (hoy export_report) con
    parametros validados en esta capa y datos autorizados. Deja bitacora con el
    correo del actor; si llega una request_id repetida dentro de la ventana,
    no vuelve a auditar la accion (X-Idempotent-Replay: true)."""
    try:
        result = AssistantTools(db).execute(data.tool, data.params, user, data.request_id)
    except UnknownToolError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    headers = {
        "Content-Disposition": f'attachment; filename="{result.filename}"',
        "X-Tool": data.tool,
        "X-Reports": "+".join(result.reports),
        "X-Truncated": "true" if result.truncated else "false",
        "X-Audited": "true" if result.audited else "false",
    }
    if result.replay:
        headers["X-Idempotent-Replay"] = "true"
    return StreamingResponse(
        iter([result.payload]), media_type=result.media_type, headers=headers
    )


@analytics_router.get("/reports/export", tags=["analytics"])
def export_reports(user: Analyst, db: Session = Depends(get_db), report: str = Query(default="ventas"),
                   format: str = Query(default="xlsx"), date_from: datetime | None = None, date_to: datetime | None = None,
                   branch_id: uuid.UUID | None = None, category_id: uuid.UUID | None = None,
                   status: str | None = Query(default=None, max_length=30)):
    """Exporta el conjunto filtrado autorizado (max report_export_max_rows),
    con totales consistentes con el dashboard. xlsx principal, csv tabular."""
    if format not in {"xlsx", "csv"}:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="Formato no soportado: use xlsx o csv.")
    if report not in {"ventas", "pedidos", "pagos", "prendas_vendidas", "existencias", "sucursales"}:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="Reporte no soportado.")
    fif = ReportFilters(date_from=date_from, date_to=date_to, branch_id=branch_id, category_id=category_id, status=status)
    title, headers, rows = ReportsService(db).export_report(report, fif.date_from, fif.date_to, fif.branch_id, fif.category_id, fif.status)
    truncated = len(rows) > settings.report_export_max_rows
    rows = rows[: settings.report_export_max_rows]
    period = ReportsService(db)._window(fif.date_from, fif.date_to)
    period_text = f"{period[0].isoformat() if period[0] else 'inicio'} a {period[1].isoformat() if period[1] else 'hoy'}"
    filtro_text = "; ".join(
        part for part in [
            f"sucursal={str(fif.branch_id)}" if fif.branch_id else "",
            f"categoria={str(fif.category_id)}" if fif.category_id else "",
            f"estado={fif.status}" if fif.status else "",
        ] if part
    )
    metadata = exporter.build_metadata(title, period_text, filtro_text, settings.commerce_currency.upper(), truncated=truncated)
    filename = f"fashionstore_{report}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{format}"
    if format == "csv":
        content = exporter.to_csv(title, headers, rows, metadata)
        return StreamingResponse(iter([content]), media_type="text/csv; charset=utf-8",
                                 headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    content = exporter.to_xlsx(title, headers, rows, metadata)
    return StreamingResponse(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@analytics_router.post("/reports/export-multiple", tags=["analytics"])
def export_reports_multiple(data: MultiExportRequest, user: Analyst, db: Session = Depends(get_db)):
    """Exportacion multiple (NUEVO): varios reportes en una sola operacion.

    - xlsx: un archivo con una hoja por reporte + hoja "Criterios".
    - pdf: un documento con cabecera, criterios y una seccion por reporte,
      encabezados repetidos y paginas numeradas.
    - csv: un reporte => .csv; varios => .zip con un CSV por reporte y
      criterios.txt (nunca se concatenan tablas incompatibles).

    Mantiene el endpoint individual GET /analytics/reports/export compatible.
    Valida tipos, formato, filtros y permiso (dashboard.read) en el servidor;
    respeta el limite de filas y comunica el truncamiento por encabezado.
    """
    from fastapi import HTTPException

    invalid = [key for key in data.reports if key not in REPORT_TYPES]
    if invalid:
        raise HTTPException(status_code=422, detail=f"Reportes no soportados: {', '.join(invalid)}.")
    reports = list(dict.fromkeys(data.reports))
    if not reports:
        raise HTTPException(status_code=422, detail="Selecciona al menos un reporte.")

    payload, media_type, filename, summary = MultiExportService(db).export(reports, data.format, data.filters)
    RecordAuditEvent(db).execute(
        action="analytics.reports_export_multiple",
        entity_type="report",
        description=f"Exportacion multiple en {data.format}: {', '.join(summary['reports'])}.",
        actor_user_id=user.id,
        metadata={"reports": reports, "format": data.format, **{k: v for k, v in summary.items() if k != "reports"}},
    )
    db.commit()
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Export-Reports": ",".join(reports),
        "X-Export-Format": data.format,
        "X-Export-Truncated": "true" if summary["truncated"] else "false",
    }
    return StreamingResponse(iter([payload.getvalue()] if hasattr(payload, "getvalue") else [payload]),
                             media_type=media_type, headers=headers)
