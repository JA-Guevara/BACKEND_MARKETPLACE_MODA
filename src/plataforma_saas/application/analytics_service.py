"""Indicadores SaaS: cobros reales y estimaciones claramente separados."""
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from sqlalchemy import select

from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.plataforma_saas.infrastructure.models.subscription import SubscriptionModel, SubscriptionInvoiceModel
from src.ventas_pagos.infrastructure.models import OrderModel
from src.shared.exceptions.domain_exception import ValidationError

TZ = ZoneInfo("America/La_Paz")


class PlatformAnalyticsService:
    def __init__(self, db):
        self.db = db

    def report(self, start=None, end=None, plan_code=None, state=None, horizon=14):
        today = datetime.now(TZ).date()
        end = end or today
        start = start or end - timedelta(days=89)
        if end < start or (end - start).days > 365 or end > today:
            raise ValidationError("Elegí un período de hasta 366 días que no termine en el futuro.")
        tenants = list(self.db.scalars(select(TenantModel).where(TenantModel.is_sandbox.is_(False))))
        subs = {sub.tenant_id: sub for sub in self.db.scalars(select(SubscriptionModel).where(SubscriptionModel.closed_at.is_(None)))}
        tenants = [tenant for tenant in tenants if (not plan_code or (subs.get(tenant.id) and subs[tenant.id].plan.code == plan_code))
                   and (not state or tenant.status == state)]
        ids = {tenant.id for tenant in tenants}
        if len(ids) > 10000:
            raise ValidationError("Aplicá un filtro para consultar hasta 10.000 empresas.")
        begin = datetime.combine(start, time.min, TZ)
        finish = datetime.combine(end + timedelta(days=1), time.min, TZ)
        invoices = list(self.db.scalars(select(SubscriptionInvoiceModel).where(
            SubscriptionInvoiceModel.tenant_id.in_(ids))))
        def local_day(value):
            if value is None:
                return None
            return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).astimezone(TZ).date()
        paid = [invoice for invoice in invoices if invoice.status == "paid" and invoice.currency == "BOB"
                and invoice.paid_at and start <= local_day(invoice.paid_at) <= end]
        open_invoices = [invoice for invoice in invoices if invoice.currency == "BOB" and local_day(invoice.issued_at) <= end
                         and (invoice.status == "issued" or (invoice.status == "paid" and invoice.paid_at and local_day(invoice.paid_at) > end))]
        daily = defaultdict(lambda: Decimal("0"))
        by_tenant = defaultdict(lambda: Decimal("0"))
        by_plan = defaultdict(lambda: Decimal("0"))
        for invoice in paid:
            daily[local_day(invoice.paid_at)] += invoice.amount
            by_tenant[invoice.tenant_id] += invoice.amount
            by_plan[invoice.subscription.plan.name] += invoice.amount
        series = [{"date": (start + timedelta(days=index)).isoformat(),
                   "value": str(daily[start + timedelta(days=index)].quantize(Decimal("0.01")))}
                  for index in range((end - start).days + 1)]
        projection = []
        sufficient = len({local_day(invoice.paid_at) for invoice in paid}) >= 7 and len(series) >= 28
        if sufficient:
            values = [float(point["value"]) for point in series[-90:]]
            n = len(values)
            mean_x, mean_y = (n - 1) / 2, sum(values) / n
            slope = sum((i - mean_x) * (value - mean_y) for i, value in enumerate(values)) / sum((i - mean_x)**2 for i in range(n))
            projection = [{"date": (end + timedelta(days=index + 1)).isoformat(),
                           "value": f"{max(0, mean_y + slope * (n + index - mean_x)):.2f}"}
                          for index in range(horizon)]
        orders = self.db.execute(select(OrderModel.tenant_id, OrderModel.total).where(
            OrderModel.tenant_id.in_(ids), OrderModel.payment_status == "paid",
            OrderModel.currency == "BOB",
            OrderModel.paid_at >= begin, OrderModel.paid_at < finish)).all()
        volume = defaultdict(lambda: Decimal("0"))
        counts = Counter()
        for tenant_id, total in orders:
            volume[tenant_id] += total
            counts[tenant_id] += 1
        states = Counter(tenant.status for tenant in tenants)
        plans = Counter(subs[tenant.id].plan.name if tenant.id in subs else "Sin suscripción" for tenant in tenants)
        mrr = Decimal("0")
        rows = []
        for tenant in tenants:
            sub = subs.get(tenant.id)
            active = bool(sub and sub.status == "ACTIVA" and sub.end_date >= today and tenant.status == "ACTIVA")
            estimate = (sub.plan.reference_price * Decimal(30) / Decimal(sub.plan.duration_days or 30)) if active else Decimal("0")
            mrr += estimate
            rows.append({"id": str(tenant.id), "name": tenant.trade_name, "slug": tenant.slug,
                         "state": tenant.status, "plan": sub.plan.name if sub else "Sin suscripción",
                         "end_date": sub.end_date.isoformat() if sub else None,
                         "collected": f"{by_tenant[tenant.id]:.2f}", "mrr_estimate": f"{estimate:.2f}",
                         "sales_volume": f"{volume[tenant.id]:.2f}", "paid_sales": counts[tenant.id]})
        rows.sort(key=lambda row: (-Decimal(row["collected"]), row["name"].casefold()))
        return {
            "meta": {"from": start.isoformat(), "to": end.isoformat(), "timezone": "America/La_Paz",
                     "currency": "BOB", "generated_at": datetime.now(TZ).isoformat(),
                     "plan_code": plan_code, "state": state, "sandbox_excluded": True,
                     "note": "Cobros de suscripciones registrados como pagados. El volumen comercial de empresas no es ingreso de la plataforma. MRR estimado a precios de referencia actuales."},
            "kpis": {"companies": len(tenants), "active": states["ACTIVA"],
                     "collected": f"{sum((invoice.amount for invoice in paid), Decimal(0)):.2f}",
                     "paid_invoices": len(paid), "mrr_estimate": f"{mrr:.2f}",
                     "receivable": f"{sum((invoice.amount for invoice in open_invoices), Decimal(0)):.2f}",
                     "overdue_invoices": sum(local_day(invoice.due_at) < end for invoice in open_invoices)},
            "states": [{"label": key, "value": value} for key, value in sorted(states.items())],
            "plans": [{"label": key, "value": value} for key, value in sorted(plans.items())],
            "collections_by_plan": [{"label": key, "value": str(value)} for key, value in sorted(by_plan.items())],
            "daily_collections": series,
            "signups": [{"label": (start + timedelta(days=i)).isoformat(),
                         "value": sum(local_day(tenant.created_at) == start + timedelta(days=i) for tenant in tenants)}
                        for i in range((end-start).days+1)],
            "projection": {"available": sufficient, "points": projection, "horizon_days": horizon,
                           "method": "Tendencia lineal de cobros diarios; estimación, no garantía ni modelo ML.",
                           "note": "Se requieren al menos 28 días de período y cobros en 7 fechas distintas." if not sufficient else "Los cobros de planes pueden ser irregulares; usá esta tendencia como orientación."},
            "companies": rows,
        }
