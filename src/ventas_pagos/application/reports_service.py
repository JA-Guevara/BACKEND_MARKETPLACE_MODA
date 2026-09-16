import uuid
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.config.settings import settings
from src.inventario_sucursales.infrastructure.models.organization import BranchModel
from src.reservas.infrastructure.persistence.models.reserva import ReservationModel
from src.usuarios_catalogo.infrastructure.models.catalog import ProductModel, ProductVariantModel
from src.ventas_pagos.infrastructure.models import OrderModel, StockModel

WEEKDAY_LABELS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
DEFAULT_WINDOW_DAYS = 90
PROJECTION_DAYS = 7
BUSINESS_TZ = timezone(timedelta(hours=-4), name="America/La_Paz")
LOW_STOCK_DEFAULT = 5


def _as_utc(value: datetime) -> datetime:
    """Normaliza un datetime al instante UTC. Las fechas sin offset enviadas
    por el cliente se interpretan en America/La_Paz (UTC-4, sin horario de
    verano) para que los limites de los presets coincidan con la zona de la
    operacion."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=BUSINESS_TZ)
    return value.astimezone(timezone.utc)


def _utc_of(value: datetime) -> datetime:
    """Convierte un created_at (que puede venir naive en SQLite o aware en
    Postgres) a instante UTC para comparaciones seguras en cualquier dialecto.
    Los valores naive se interpretan como UTC (es como se escriben en SQLite)."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _local(value: datetime) -> datetime:
    """Convierte created_at (UTC) a America/La_Paz para agrupaciones del
    dashboard (hora, dia de semana, fecha) y devuelve un valor naive."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(BUSINESS_TZ).replace(tzinfo=None)


def _shift_year(value: datetime) -> datetime:
    """Mueve un instante al mismo lapso calendario del ano anterior respetando
    anos bisiestos (el 29 de febrero cae al 28) y conserva la hora local."""
    local = value.astimezone(BUSINESS_TZ)
    try:
        shifted = local.replace(year=local.year - 1)
    except ValueError:
        shifted = local.replace(year=local.year - 1, month=2, day=28)
    return shifted.astimezone(timezone.utc)


def _line_amount(item: dict) -> Decimal:
    """Importe de una linea de pedido. Prefiere el total por linea que guardo el
    snapshot en el carrito; si no (datos viejos o fixtures) lo recalcula.
    Se normaliza a 2 decimales para que el payload quede identico al resto de
    los montos del dashboard."""
    if "line_total" in item and item.get("line_total"):
        value = Decimal(item["line_total"])
    else:
        value = Decimal(item.get("unit_price", "0")) * int(item.get("quantity", 0) or 0)
    return value.quantize(Decimal("0.01"))


def _line_qty(item: dict) -> int:
    return int(item.get("quantity", 0) or 0)


class ReportsService:
    """Agregados para el dashboard administrativo (RF24/CU25).

    Contrato de compatibilidad: conserva todas las claves previas del payload
    (orders, paid_orders, revenue, by_status, ...) y amplia con un bloque
    ``meta``, metricas de ``period``, ``units_sold``, ``comparison``,
    ``low_stock_variants``, ``reservations_by_status`` y ``payment_methods``.

    Semantica de una categoria: cuando hay un filtro de categoria, los ingresos
    y unidades corresponden UNICAMENTE a las lineas de esa categoria (no al
    total del pedido que la contiene), los pedidos pagados cuentan los pedidos
    que contienen al menos una linea de esa categoria, y todos los desgloses
    (diario, mensual, horario, categorias, sucursales, top prendas) se calculan
    sobre ese mismo conjunto. Asi dashboard = export = contexto de IA.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def dashboard(
        self,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        branch_id: uuid.UUID | None = None,
        category_id: uuid.UUID | None = None,
        status: str | None = None,
        low_stock_lt: int | None = None,
    ) -> dict:
        threshold = low_stock_lt if low_stock_lt is not None else settings.low_stock_threshold

        all_orders = list(self.db.scalars(select(OrderModel)))
        if status:
            all_orders = [o for o in all_orders if o.status == status]
        if branch_id:
            all_orders = [o for o in all_orders if o.branch_id == branch_id]

        # Totales historicos (compatibilidad hacia atras), dentro del alcance
        # de los filtros aplicados (estado y sucursal).
        statuses = Counter(o.status for o in all_orders)
        paid_total = sum(1 for o in all_orders if o.payment_status == "paid")
        revenue_total = sum(o.total for o in all_orders if o.payment_status == "paid") or Decimal(0)
        cancelled_total = sum(1 for o in all_orders if o.status == "cancelled")
        orders_total = len(all_orders)

        start, end = self._window(date_from, date_to)
        windowed_all = [o for o in all_orders if self._in_window(o, start, end)]

        paid = [o for o in all_orders if o.payment_status == "paid"]
        # Cobros del periodo: se usa la fecha de pago (paid_at) cuando existe y
        # la de creacion como respaldo verificable para datos historicos.
        windowed_paid = [o for o in paid if self._in_payment_window(o, start, end)]

        kept = None
        if category_id:
            kept = self._product_ids_by_category(windowed_paid, category_id)
        lines = self._lines(windowed_paid, kept)

        period_orders = len(windowed_all)
        period_paid = self._order_count(lines)
        period_revenue = self._revenue(lines) or Decimal(0)
        period_units = self._units(lines)
        period_pending = sum(1 for o in windowed_all if o.status == "pending_payment")
        period_cancelled = sum(1 for o in windowed_all if o.status == "cancelled")

        daily = self._daily_sales(lines, days=30)
        comparison = self._comparison(start, end, paid, kept)
        low_stock = self._low_stock_variants(threshold, branch_id)
        projection = self._projection(daily)

        stripe_mode = (
            "test"
            if settings.stripe_secret_key.startswith("sk_test_")
            else "live"
            if settings.stripe_secret_key.startswith("sk_live_")
            else "none"
        )
        return {
            # Totales historicos (compatibilidad hacia atras).
            "orders": orders_total,
            "paid_orders": paid_total,
            "pending_orders": statuses.get("pending_payment", 0),
            "revenue": str(revenue_total),
            "currency": settings.commerce_currency,
            "products": self.db.scalar(select(func.count()).select_from(ProductModel).where(ProductModel.deleted_at.is_(None))),
            "customers": self.db.scalar(select(func.count()).select_from(UserModel)),
            "low_stock": len(low_stock),
            "by_status": dict(Counter(o.status for o in windowed_all)),
            "daily_sales": [{"date": d, "total": str(total)} for d, total in daily],
            "top_products": self._top_products(windowed_paid, kept, limit=5),
            "stripe_ready": bool(settings.stripe_secret_key) and bool(settings.stripe_webhook_secret),
            "stripe_mode": stripe_mode,
            "ai_ready": bool(settings.ai_api_key),
            "average_ticket": str(revenue_total / paid_total) if paid_total else "0",
            "cancellation_rate": round(cancelled_total / orders_total, 4) if orders_total else 0,
            "monthly_sales": self._monthly_sales(lines, months=12, start=start, end=end),
            "hourly_distribution": self._hourly_distribution(lines),
            "weekday_distribution": self._weekday_distribution(lines),
            "category_breakdown": self._category_breakdown(windowed_paid, kept),
            "branch_performance": self._branch_performance(lines),
            "projection": projection,
            # Extensiones nuevas del dashboard.
            "meta": {
                "period": {"from": start.isoformat() if start else None, "to": end.isoformat() if end else None},
                "timezone": "America/La_Paz",
                "currency": settings.commerce_currency,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "coverage": "todo el historial" if not start else "ventana definida",
                "stripe_mode": stripe_mode,
                "note": ("Ingresos: fecha de pago (paid_at) cuando existe; en datos historicos sin ella, "
                         "fecha de creacion. Filtro por categoria = solo las lineas de esa categoria. "
                         "Stock bajo = fotografia del momento. by_status y reservas corresponden al periodo."),
            },
            "period": {
                "orders": period_orders,
                "paid_orders": period_paid,
                "pending_orders": period_pending,
                "revenue": str(period_revenue),
                "units_sold": period_units,
                "ticket_avg": str(period_revenue / period_paid) if period_paid else "0",
                "cancellation_rate": round(period_cancelled / period_orders, 4) if period_orders else 0,
            },
            "units_sold": period_units,
            "comparison": comparison,
            "low_stock_variants": low_stock,
            "reservations_by_status": self._reservations_by_status(branch_id, start, end),
            "payment_methods": self._payment_methods(windowed_all, kept),
        }

    # ---------- ventanas y lineas ----------

    @staticmethod
    def _in_window(order: OrderModel, start: datetime | None, end: datetime | None) -> bool:
        created = _utc_of(order.created_at)
        if start and created < start:
            return False
        if end and created > end:
            return False
        return True

    def _in_payment_window(self, order: OrderModel, start: datetime | None, end: datetime | None) -> bool:
        instant = self._payment_instant(order)
        if start and instant < start:
            return False
        if end and instant > end:
            return False
        return True

    @staticmethod
    def _in_instant_window(instant: datetime, start: datetime | None, end: datetime | None) -> bool:
        if start and instant < start:
            return False
        if end and instant > end:
            return False
        return True

    def _payment_instant(self, order: OrderModel) -> datetime:
        """Instante al que se atribuye el cobro. Si el pedido tiene fecha de
        pago la usa; si no (historico) cae a la fecha de creacion y queda
        documentado en meta.note. Nunca se inventa una fecha."""
        if order.paid_at:
            return _utc_of(order.paid_at)
        return _utc_of(order.created_at)

    @staticmethod
    def _window(date_from: datetime | None, date_to: datetime | None) -> tuple[datetime | None, datetime | None]:
        if not date_from and not date_to:
            return None, None
        end = _as_utc(date_to) if date_to else datetime.now(timezone.utc)
        start = _as_utc(date_from) if date_from else end - timedelta(days=DEFAULT_WINDOW_DAYS)
        return start, end

    @staticmethod
    def _lines(orders: list[OrderModel], kept: set[uuid.UUID] | None) -> list[tuple]:
        """Una tupla (pedido, linea|None, es_linea_filtrada) por cada unidad de
        agregacion. Sin categoria: un pseudo-linea por pedido (total completo).
        Con categoria: una linea por cada item de esa categoria."""
        if kept is None:
            return [(o, None, False) for o in orders]
        out = []
        for order in orders:
            for item in order.items:
                try:
                    product_id = uuid.UUID(item["product_id"])
                except (KeyError, TypeError, ValueError):
                    continue
                if product_id in kept:
                    out.append((order, item, True))
        return out

    @staticmethod
    def _amount(order: OrderModel, item: dict | None, scoped: bool) -> Decimal:
        if scoped and item is not None:
            return _line_amount(item)
        return Decimal(order.total)

    @staticmethod
    def _units(lines: list[tuple]) -> int:
        total = 0
        for order, item, scoped in lines:
            if item is None:
                total += sum(_line_qty(i) for i in order.items)
            elif scoped:
                total += _line_qty(item)
        return total

    @staticmethod
    def _revenue(lines: list[tuple]) -> Decimal:
        return sum((ReportsService._amount(order, item, scoped) for order, item, scoped in lines), Decimal(0))

    @staticmethod
    def _order_count(lines: list[tuple]) -> int:
        return len({order.id for order, _, _ in lines})

    # ---------- comparaciones ----------

    def _comparison(self, start: datetime | None, end: datetime | None, paid: list[OrderModel], kept: set[uuid.UUID] | None) -> dict:
        if not start or not end:
            return {
                "available": False,
                "mode": "none",
                "note": "Sin periodo de referencia: el dato cubre todo el historial.",
                "previous": None,
                "year_ago": None,
            }
        span = end - start
        previous = self._aggregate(paid, kept, start - span, start)
        year_ago = self._aggregate(paid, kept, _shift_year(start), _shift_year(end))
        current = self._aggregate(paid, kept, start, end)

        def delta(current_value: Decimal, base: Decimal) -> float | None:
            return None if not base else round(float((current_value - base) / base), 4)

        return {
            "available": True,
            "mode": "period",
            "note": ("Comparacion respecto de la ventana anterior equivalente y del mismo lapso "
                     "calendario del anio anterior (con anos bisiestos compensados)."),
            "previous": {
                "revenue": str(previous[0]),
                "paid_orders": previous[1],
                "revenue_delta_pct": delta(current[0], previous[0]),
                "paid_delta_pct": delta(current[1], previous[1]) if previous[1] else None,
                "base_note": None if previous[0] else "Sin base comparable",
            },
            "year_ago": {
                "revenue": str(year_ago[0]),
                "paid_orders": year_ago[1],
                "revenue_delta_pct": delta(current[0], year_ago[0]),
                "paid_delta_pct": delta(current[1], year_ago[1]) if year_ago[1] else None,
                "base_note": None if year_ago[0] else "Sin base comparable",
            },
        }

    def _aggregate(self, paid: list[OrderModel], kept: set[uuid.UUID] | None, lo: datetime, hi: datetime) -> tuple[Decimal, int]:
        total = Decimal(0)
        ids: set = set()
        for order in paid:
            instant = self._payment_instant(order)
            if not (lo <= instant < hi):
                continue
            if kept is None:
                total += order.total
                ids.add(order.id)
                continue
            matched = [item for item in order.items if self._product_in(item, kept)]
            if matched:
                ids.add(order.id)
                total += sum(_line_amount(item) for item in matched)
        return total, len(ids)

    @staticmethod
    def _product_in(item: dict, kept: set[uuid.UUID]) -> bool:
        try:
            return uuid.UUID(item["product_id"]) in kept
        except (KeyError, TypeError, ValueError):
            return False

    def _product_ids_by_category(self, paid: list[OrderModel], category_id: uuid.UUID) -> set[uuid.UUID]:
        ids = {uuid.UUID(item["product_id"]) for o in paid for item in o.items}
        if not ids:
            return set()
        return set(
            self.db.scalars(
                select(ProductModel.id).where(ProductModel.id.in_(ids), ProductModel.category_id == category_id)
            )
        )

    # ---------- desgloses ----------

    @staticmethod
    def _daily_sales(lines: list[tuple], days: int) -> list[tuple[str, Decimal]]:
        daily: dict[str, Decimal] = {}
        for order, item, scoped in lines:
            key = _local(order.created_at).date().isoformat()
            daily[key] = daily.get(key, Decimal(0)) + ReportsService._amount(order, item, scoped)
        return sorted(daily.items())[-days:] if days else sorted(daily.items())

    @staticmethod
    def _month_keys(start: datetime | None, end: datetime | None, months: int) -> list[str]:
        if start is None:
            today = _local(datetime.now(timezone.utc)).date().replace(day=1)
            cursor = today
            keys = []
            for _ in range(months):
                keys.append(cursor.isoformat()[:7])
                cursor = (cursor.replace(day=1) - timedelta(days=1)).replace(day=1)
            keys.reverse()
            return keys
        lo = _as_utc(start).astimezone(BUSINESS_TZ).date().replace(day=1)
        hi = _as_utc(end).astimezone(BUSINESS_TZ).date().replace(day=1)
        keys = []
        cursor = lo
        guard = 0
        while cursor <= hi and guard < 120:
            keys.append(cursor.isoformat()[:7])
            cursor = (cursor.replace(day=1) + timedelta(days=32)).replace(day=1)
            guard += 1
        return keys

    def _monthly_sales(self, lines: list[tuple], months: int = 12, start: datetime | None = None, end: datetime | None = None) -> list[dict]:
        keys = self._month_keys(start, end, months)
        buckets: dict[str, Decimal] = {key: Decimal(0) for key in keys}
        orders: dict[str, set] = {key: set() for key in keys}
        for order, item, scoped in lines:
            key = _local(order.created_at).date().isoformat()[:7]
            if key in buckets:
                buckets[key] += self._amount(order, item, scoped)
                orders[key].add(order.id)
        return [{"month": key, "total": str(buckets[key]), "orders": len(orders[key])} for key in keys]

    @staticmethod
    def _hourly_distribution(lines: list[tuple]) -> list[dict]:
        totals = {h: Decimal(0) for h in range(24)}
        counts = {h: set() for h in range(24)}
        for order, item, scoped in lines:
            hour = _local(order.created_at).hour
            totals[hour] += ReportsService._amount(order, item, scoped)
            counts[hour].add(order.id)
        return [{"hour": h, "total": str(totals[h]), "orders": len(counts[h])} for h in range(24)]

    @staticmethod
    def _weekday_distribution(lines: list[tuple]) -> list[dict]:
        totals = {i: Decimal(0) for i in range(7)}
        counts = {i: set() for i in range(7)}
        for order, item, scoped in lines:
            day = _local(order.created_at).weekday()
            totals[day] += ReportsService._amount(order, item, scoped)
            counts[day].add(order.id)
        return [{"weekday": WEEKDAY_LABELS[i], "total": str(totals[i]), "orders": len(counts[i])} for i in range(7)]

    def _top_products(self, paid: list[OrderModel], kept: set[uuid.UUID] | None, limit: int) -> list[dict]:
        top: dict[str, int] = {}
        for order in paid:
            items = order.items if kept is None else [item for item in order.items if self._product_in(item, kept)]
            for item in items:
                top[item["name"]] = top.get(item["name"], 0) + _line_qty(item)
        return [{"name": name, "quantity": qty} for name, qty in sorted(top.items(), key=lambda x: -x[1])[:limit]]

    def _category_breakdown(self, paid: list[OrderModel], kept: set[uuid.UUID] | None) -> list[dict]:
        product_ids = {uuid.UUID(item["product_id"]) for order in paid for item in order.items}
        if not product_ids:
            return []
        products = self.db.scalars(select(ProductModel).where(ProductModel.id.in_(product_ids)))
        category_by_product = {str(p.id): p.category.name for p in products}
        totals: dict[str, Decimal] = {}
        quantities: dict[str, int] = {}
        for order in paid:
            items = order.items if kept is None else [item for item in order.items if self._product_in(item, kept)]
            for item in items:
                category = category_by_product.get(item["product_id"], "Sin categoria")
                totals[category] = totals.get(category, Decimal(0)) + _line_amount(item)
                quantities[category] = quantities.get(category, 0) + _line_qty(item)
        return [{"category": c, "total": str(totals[c]), "quantity": quantities[c]} for c in sorted(totals, key=lambda c: -totals[c])]

    def _branch_performance(self, lines: list[tuple]) -> list[dict]:
        branch_ids = {order.branch_id for order, _, _ in lines}
        if not branch_ids:
            return []
        branches = self.db.scalars(select(BranchModel).where(BranchModel.id.in_(branch_ids)))
        name_by_id = {b.id: b.name for b in branches}
        totals: dict[str, Decimal] = {}
        counts: dict[str, set] = {}
        for order, item, scoped in lines:
            name = name_by_id.get(order.branch_id, "Sucursal eliminada")
            totals[name] = totals.get(name, Decimal(0)) + self._amount(order, item, scoped)
            counts.setdefault(name, set()).add(order.id)
        return [{"branch": b, "total": str(totals[b]), "orders": len(counts[b])} for b in sorted(totals, key=lambda b: -totals[b])]

    @staticmethod
    def _payment_methods(orders: list[OrderModel], kept: set[uuid.UUID] | None) -> list[dict]:
        relevant = orders if kept is None else [o for o in orders if any(ReportsService._product_in(item, kept) for item in o.items)]
        counts = Counter(o.payment_method for o in relevant)
        return [{"method": method, "orders": counts[method]} for method in sorted(counts, key=lambda m: -counts[m])]

    def _low_stock_variants(self, threshold: int, branch_id: uuid.UUID | None) -> list[dict]:
        query = (
            select(ProductVariantModel, ProductModel, StockModel, BranchModel)
            .join(ProductModel, ProductVariantModel.product_id == ProductModel.id)
            .join(StockModel, StockModel.variant_id == ProductVariantModel.id)
            .join(BranchModel, BranchModel.id == StockModel.branch_id)
            .where(StockModel.quantity < threshold, ProductModel.deleted_at.is_(None))
            .order_by(StockModel.quantity.asc())
        )
        if branch_id:
            query = query.where(StockModel.branch_id == branch_id)
        rows = []
        for variant, product, stock, branch in self.db.execute(query):
            rows.append(
                {
                    "variant_id": str(variant.id),
                    "product_id": str(product.id),
                    "sku": variant.sku,
                    "name": product.name,
                    "size": variant.size.name,
                    "color": variant.color.name,
                    "branch": branch.name,
                    "branch_id": str(branch.id),
                    "quantity": stock.quantity,
                }
            )
        return rows

    def _reservations_by_status(self, branch_id: uuid.UUID | None, start: datetime | None, end: datetime | None) -> list[dict]:
        query = select(ReservationModel)
        if branch_id:
            query = query.where(ReservationModel.branch_id == branch_id)
        reservations = list(self.db.scalars(query))
        if start is not None or end is not None:
            reservations = [
                r for r in reservations
                if self._in_instant_window(_as_utc(r.scheduled_at), start, end)
            ]
        counts = Counter(r.status for r in reservations)
        return [{"status": status, "count": counts[status]} for status in sorted(counts)]

    @staticmethod
    def _projection(daily: list[tuple[str, Decimal]]) -> dict:
        base = {"dates": [], "values": [], "trend": "stable"}
        if len(daily) < 2:
            base["meta"] = {"method": "regresion lineal simple sobre ventas diarias", "horizon_days": PROJECTION_DAYS,
                            "observations": len(daily), "note": "Datos insuficientes para estimar"}
            return base
        xs = list(range(len(daily)))
        ys = [float(total) for _, total in daily]
        mean_x = sum(xs) / len(xs)
        mean_y = sum(ys) / len(ys)
        denominator = sum((x - mean_x) ** 2 for x in xs)
        slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator if denominator else 0.0
        intercept = mean_y - slope * mean_x
        last_day = date.fromisoformat(daily[-1][0])
        base_index = len(daily) - 1
        values = [max(0.0, slope * (base_index + i) + intercept) for i in range(1, PROJECTION_DAYS + 1)]
        dates = [(last_day + timedelta(days=i)).isoformat() for i in range(1, PROJECTION_DAYS + 1)]
        trend = "up" if slope > 0.01 * (mean_y or 1) else "down" if slope < -0.01 * (mean_y or 1) else "stable"
        return {"dates": dates, "values": [str(round(v, 2)) for v in values], "trend": trend,
                "meta": {"method": "regresion lineal simple sobre ventas diarias", "horizon_days": PROJECTION_DAYS,
                         "observations": len(daily), "note": "Estimacion lineal; separar real vs estimado en la vista."}}

    # ---------- exportacion ----------

    def export_report(
        self,
        report: str,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        branch_id: uuid.UUID | None = None,
        category_id: uuid.UUID | None = None,
        status: str | None = None,
    ) -> tuple[str, list[str], list[dict]]:
        """Construye filas para exportar. Devuelve (titulo, cabeceras, filas)
        sobre el MISMO conjunto que el dashboard: una categoria solo suma sus
        lineas, los ingresos son cobros del periodo y ``sucursales`` usa pedidos
        pagados, igual que las tarjetas del centro de reportes."""
        all_orders = list(self.db.scalars(select(OrderModel)))
        if status:
            all_orders = [o for o in all_orders if o.status == status]
        if branch_id:
            all_orders = [o for o in all_orders if o.branch_id == branch_id]
        start, end = self._window(date_from, date_to)
        windowed = [o for o in all_orders if self._in_window(o, start, end)]
        paid = [o for o in all_orders if o.payment_status == "paid"]
        windowed_paid = [o for o in paid if self._in_payment_window(o, start, end)]

        kept = None
        if category_id and report in {"ventas", "pedidos", "pagos", "prendas_vendidas"}:
            kept = self._product_ids_by_category(windowed_paid, category_id)

        branches = {b.id: b.name for b in self.db.scalars(select(BranchModel))}
        currency = settings.commerce_currency.upper()

        def order_contains_category(order: OrderModel) -> bool:
            return any(self._product_in(item, kept) for item in order.items)

        if report == "pedidos":
            orders = [o for o in windowed if kept is None or order_contains_category(o)]
            headers = ["numero", "fecha", "correo", "sucursal", "estado", "pago", "metodo", "total", "moneda"]
            rows = []
            for o in sorted(orders, key=lambda o: _utc_of(o.created_at), reverse=True):
                row = {
                    "numero": o.number, "fecha": _local(o.created_at).strftime("%Y-%m-%d %H:%M"),
                    "correo": o.customer_email, "sucursal": branches.get(o.branch_id, "-"),
                    "estado": o.status, "pago": o.payment_status, "metodo": o.payment_method,
                    "total": float(o.total), "moneda": currency,
                }
                if kept is not None:
                    row["total_categoria"] = float(sum(_line_amount(it) for it in o.items if self._product_in(it, kept)))
                rows.append(row)
            if kept is not None:
                headers = headers + ["total_categoria"]
            return ("Pedidos", headers, rows)

        if report == "pagos":
            orders = [o for o in windowed_paid if kept is None or order_contains_category(o)]
            rows = []
            for o in sorted(orders, key=lambda o: _utc_of(o.created_at), reverse=True):
                monto = float(sum(_line_amount(it) for it in o.items if self._product_in(it, kept))) if kept is not None else float(o.total)
                row = {
                    "numero": o.number, "fecha": _local(self._payment_instant(o)).strftime("%Y-%m-%d %H:%M"),
                    "correo": o.customer_email, "sucursal": branches.get(o.branch_id, "-"),
                    "metodo": o.payment_method, "referencia": o.payment_reference or "-",
                    "total": monto, "moneda": currency,
                }
                rows.append(row)
            return ("Pagos confirmados", ["numero", "fecha", "correo", "sucursal", "metodo", "referencia", "total", "moneda"], rows)

        if report == "prendas_vendidas":
            product_ids = {uuid.UUID(item["product_id"]) for o in windowed_paid for item in o.items}
            products = {str(p.id): p for p in self.db.scalars(select(ProductModel).where(ProductModel.id.in_(product_ids)))} if product_ids else {}
            variants = {v.id: v for v in self.db.scalars(select(ProductVariantModel))}
            agg: dict[str, dict] = {}
            for o in windowed_paid:
                items = o.items if kept is None else [item for item in o.items if self._product_in(item, kept)]
                for item in items:
                    variant = variants.get(uuid.UUID(item["variant_id"]))
                    product = products.get(item["product_id"])
                    key = item["variant_id"]
                    entry = agg.setdefault(key, {"sku": variant.sku if variant else item.get("sku", "-"),
                        "nombre": product.name if product else item["name"], "talla": variant.size.name if variant else "-",
                        "color": variant.color.name if variant else "-", "cantidad": 0,
                        "unit_price": Decimal(item["unit_price"]), "total": Decimal(0)})
                    entry["cantidad"] += _line_qty(item)
                    entry["total"] += _line_amount(item)
            rows = [{"sku": e["sku"], "nombre": e["nombre"], "talla": e["talla"], "color": e["color"],
                     "cantidad": e["cantidad"], "precio_unitario": float(e["unit_price"]),
                     "total": float(e["total"]), "moneda": currency}
                    for e in sorted(agg.values(), key=lambda e: -e["total"])]
            return ("Prendas vendidas", ["sku", "nombre", "talla", "color", "cantidad", "precio_unitario", "total", "moneda"], rows)

        if report == "existencias":
            query = (select(ProductVariantModel, ProductModel, StockModel, BranchModel)
                     .join(ProductModel, ProductVariantModel.product_id == ProductModel.id)
                     .join(StockModel, StockModel.variant_id == ProductVariantModel.id)
                     .join(BranchModel, BranchModel.id == StockModel.branch_id)
                     .where(ProductModel.deleted_at.is_(None)))
            if branch_id:
                query = query.where(StockModel.branch_id == branch_id)
            rows = [{"sku": v.sku, "nombre": p.name, "talla": v.size.name, "color": v.color.name,
                     "sucursal": b.name, "cantidad": s.quantity}
                    for v, p, s, b in self.db.execute(query)]
            return ("Existencias por sucursal", ["sku", "nombre", "talla", "color", "sucursal", "cantidad"], rows)

        if report == "sucursales":
            lines = self._lines(windowed_paid, kept)
            data: dict[uuid.UUID, tuple[str, Decimal, set]] = {}
            for order, item, scoped in lines:
                name = branches.get(order.branch_id, "Sucursal eliminada")
                amount = self._amount(order, item, scoped)
                entry = data.setdefault(order.branch_id, (name, Decimal(0), set()))
                data[order.branch_id] = (name, entry[1] + amount, entry[2] | {order.id})
            rows = [{"sucursal": name, "pedidos_pagados": len(order_ids), "ingresos": float(total), "moneda": currency}
                    for name, total, order_ids in data.values() if order_ids]
            return ("Rendimiento por sucursal (ingresos cobrados)", ["sucursal", "pedidos_pagados", "ingresos", "moneda"], rows)

        lines = self._daily_sales(self._lines(windowed_paid, kept), days=0)
        orders_by_day: dict[str, set] = {}
        for order, item, scoped in self._lines(windowed_paid, kept):
            key = _local(order.created_at).date().isoformat()
            orders_by_day.setdefault(key, set()).add(order.id)
        rows = [{"fecha": d, "pedidos_pagados": len(orders_by_day.get(d, set())),
                 "total": float(total), "moneda": currency}
                for d, total in lines]
        return ("Ventas diarias (ingresos cobrados)", ["fecha", "pedidos_pagados", "total", "moneda"], rows)