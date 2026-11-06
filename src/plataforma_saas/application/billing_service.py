from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A5
from reportlab.pdfgen import canvas
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.infrastructure.database.session import get_db
from src.infrastructure.security.authorization import require_permissions, require_platform_permissions
from src.infrastructure.security.tenancy import TenantScope
from src.plataforma_saas.application.jobs.suscripciones import CicloSuscripcion
from src.plataforma_saas.infrastructure.models.subscription import (
    SubscriptionInvoiceModel,
    SubscriptionModel,
)
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.shared.exceptions.domain_exception import NotFoundError
from src.shared.responses.api_response import ApiResponse

ACENTO = HexColor("#74394e")
TINTA = HexColor("#24231f")
PAPEL = HexColor("#faf9f6")
LINEA = HexColor("#e5e2da")
MUTED = HexColor("#736c65")
VERDE = HexColor("#2e7d32")
ROJO = HexColor("#c62828")


class InvoiceOut(BaseModel):
    id: UUID
    number: str
    tenant_id: UUID
    subscription_id: UUID
    period_start: date
    period_end: date
    amount: Decimal
    currency: str
    status: str
    issued_at: datetime
    due_at: datetime
    paid_at: datetime | None = None
    paid_reference: str | None = None
    plan_name: str | None = None

    class Config:
        from_attributes = True


class MarkPaidRequest(BaseModel):
    reference: str


class BillingService:
    def __init__(self, db: Session):
        self.db = db

    def _next_number(self, ano: int) -> str:
        prefix = f"FS-{ano}-"
        last = self.db.scalars(
            select(SubscriptionInvoiceModel.number)
            .where(SubscriptionInvoiceModel.number.like(f"{prefix}%"))
            .order_by(desc(SubscriptionInvoiceModel.number))
            .limit(1)
        ).first()

        if not last:
            return f"{prefix}0001"
        try:
            seq = int(last.replace(prefix, "")) + 1
        except ValueError:
            seq = 1
        return f"{prefix}{seq:04d}"

    def emitir_periodo(
        self,
        subscription: SubscriptionModel,
        ahora: datetime | None = None,
        *, inicio_periodo: date | None = None, fin_periodo: date | None = None,
    ) -> SubscriptionInvoiceModel:
        """Emite un comprobante de suscripción para el período actual.

        Idempotente por (subscription_id, period_start).
        """
        now = ahora or datetime.now(timezone.utc)
        period_start = inicio_periodo or subscription.start_date
        period_end = fin_periodo or subscription.end_date

        existente = self.db.scalars(
            select(SubscriptionInvoiceModel).where(
                SubscriptionInvoiceModel.subscription_id == subscription.id,
                SubscriptionInvoiceModel.period_start == period_start,
            )
        ).first()

        if existente:
            return existente

        price = Decimal("0.00")
        if subscription.plan and getattr(subscription.plan, "reference_price", None) is not None:
            price = Decimal(str(subscription.plan.reference_price))
        elif subscription.plan and getattr(subscription.plan, "price", None) is not None:
            price = Decimal(str(subscription.plan.price))

        number = self._next_number(now.year)
        invoice = SubscriptionInvoiceModel(
            id=uuid4(),
            number=number,
            tenant_id=subscription.tenant_id,
            subscription_id=subscription.id,
            period_start=period_start,
            period_end=period_end,
            amount=price,
            currency="BOB",
            status="issued",
            issued_at=now,
            due_at=now + timedelta(days=7),
            paid_at=None,
            paid_reference=None,
            created_by=None,
        )
        self.db.add(invoice)
        self.db.flush()
        return invoice

    def registrar_pago(
        self,
        invoice_id: UUID,
        referencia: str,
        actor_plataforma: UserModel | None = None,
    ) -> SubscriptionInvoiceModel:
        """Registra el pago de un comprobante y reactiva la suscripción."""
        invoice = self.db.get(SubscriptionInvoiceModel, invoice_id)
        if not invoice:
            raise NotFoundError("Comprobante de suscripción no encontrado.", code="invoice_not_found")

        now = datetime.now(timezone.utc)
        invoice.status = "paid"
        invoice.paid_at = now
        invoice.paid_reference = referencia.strip()

        # Reactivar la suscripción vinculada
        subscription = self.db.get(SubscriptionModel, invoice.subscription_id)
        if subscription:
            CicloSuscripcion(self.db).reactivar(subscription, actor=actor_plataforma)
            if subscription.end_date <= now.date():
                subscription.end_date = now.date() + timedelta(days=30)
                subscription.status = "ACTIVA"

        self.db.flush()
        return invoice

    def listar_por_empresa(
        self,
        tenant_id: UUID,
    ) -> list[SubscriptionInvoiceModel]:
        return self.db.scalars(
            select(SubscriptionInvoiceModel)
            .where(SubscriptionInvoiceModel.tenant_id == tenant_id)
            .order_by(desc(SubscriptionInvoiceModel.issued_at))
        ).all()

    def obtener_comprobante(
        self,
        invoice_id: UUID,
        tenant_id: UUID | None = None,
    ) -> SubscriptionInvoiceModel:
        invoice = self.db.get(SubscriptionInvoiceModel, invoice_id)
        if not invoice:
            raise NotFoundError("Comprobante de suscripción no encontrado.", code="invoice_not_found")
        if tenant_id and invoice.tenant_id != tenant_id:
            raise NotFoundError("Comprobante de suscripción no encontrado.", code="invoice_not_found")
        return invoice

    def emitir_invoices_pendientes(self, ahora: datetime | None = None) -> int:
        now = ahora or datetime.now(timezone.utc)
        subscripciones = self.db.scalars(
            select(SubscriptionModel).where(
                SubscriptionModel.closed_at.is_(None),
                SubscriptionModel.status.in_(["ACTIVA", "VENCIDA", "EN_GRACIA"]),
            )
        ).all()

        emitidos = 0
        for sub in subscripciones:
            previo = self.db.scalars(
                select(SubscriptionInvoiceModel).where(
                    SubscriptionInvoiceModel.subscription_id == sub.id,
                    SubscriptionInvoiceModel.period_start == sub.start_date,
                )
            ).first()
            if not previo:
                self.emitir_periodo(sub, now)
                emitidos += 1
        self.db.flush()
        return emitidos

    def pdf(self, invoice_id: UUID, tenant_id: UUID | None = None) -> bytes:
        """Genera el PDF con la marca de FashionStore y la leyenda obligatoria."""
        invoice = self.obtener_comprobante(invoice_id, tenant_id)
        tenant = self.db.get(TenantModel, invoice.tenant_id)
        subscription = self.db.get(SubscriptionModel, invoice.subscription_id)

        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A5, pageCompression=0)
        ancho, alto = A5

        # Encabezado
        pdf.setFillColor(ACENTO)
        pdf.rect(0, alto - 60, ancho, 60, fill=True, stroke=False)
        pdf.setFillColor(colors.white)
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(24, alto - 36, "FashionStore SaaS")
        pdf.setFont("Helvetica", 10)
        pdf.drawString(24, alto - 50, "Plataforma multitienda de moda")

        # Número de comprobante
        pdf.drawRightString(ancho - 24, alto - 36, invoice.number)
        pdf.drawRightString(
            ancho - 24,
            alto - 50,
            f"Emisión: {invoice.issued_at.strftime('%d/%m/%Y')}",
        )

        # Leyenda obligatoria (no válido como factura fiscal)
        y = alto - 85
        pdf.setFillColor(ROJO)
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawCentredString(
            ancho / 2,
            y,
            "*** COMPROBANTE DE SUSCRIPCIÓN · NO VÁLIDO COMO FACTURA FISCAL ***",
        )

        # Bloque de datos de la empresa
        y -= 25
        pdf.setFillColor(TINTA)
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(24, y, "Datos de la empresa:")
        y -= 15
        pdf.setFont("Helvetica", 9)
        pdf.drawString(24, y, f"Empresa: {tenant.trade_name if tenant else 'N/A'}")
        pdf.drawString(200, y, f"Slug: {tenant.slug if tenant else 'N/A'}")
        y -= 14
        plan_name = subscription.plan.name if (subscription and subscription.plan) else "Estándar"
        pdf.drawString(24, y, f"Plan: {plan_name}")
        pdf.drawString(200, y, f"Período: {invoice.period_start} al {invoice.period_end}")

        # Separador
        y -= 15
        pdf.setStrokeColor(LINEA)
        pdf.setLineWidth(1)
        pdf.line(24, y, ancho - 24, y)

        # Detalle del comprobante
        y -= 22
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(24, y, "Concepto")
        pdf.drawRightString(ancho - 24, y, "Importe")
        y -= 16
        pdf.setFont("Helvetica", 9)
        pdf.drawString(24, y, f"Suscripción mensual FashionStore SaaS ({plan_name})")
        pdf.drawRightString(ancho - 24, y, f"{invoice.currency} {invoice.amount:,.2f}")

        # Total
        y -= 20
        pdf.line(24, y + 8, ancho - 24, y + 8)
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(24, y - 4, "Total:")
        pdf.drawRightString(ancho - 24, y - 4, f"{invoice.currency} {invoice.amount:,.2f}")

        # Estado del pago
        y -= 35
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(24, y, "Estado del comprobante:")
        if invoice.status == "paid":
            pdf.setFillColor(VERDE)
            pdf.drawString(160, y, f"PAGADO ({invoice.paid_at.strftime('%d/%m/%Y') if invoice.paid_at else ''})")
            if invoice.paid_reference:
                y -= 14
                pdf.setFillColor(MUTED)
                pdf.setFont("Helvetica", 9)
                pdf.drawString(24, y, f"Referencia de pago: {invoice.paid_reference}")
        else:
            pdf.setFillColor(ROJO)
            pdf.drawString(160, y, f"EMITIDO / PENDIENTE (Vence: {invoice.due_at.strftime('%d/%m/%Y')})")

        # Pie de página
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica", 8)
        pdf.drawCentredString(
            ancho / 2,
            30,
            "FashionStore SaaS · Comprobante interno generado automáticamente por la plataforma.",
        )

        pdf.showPage()
        pdf.save()
        buffer.seek(0)
        return buffer.getvalue()


# --- Enrutador HTTP para la API ---

billing_tenant_router = APIRouter(prefix="/tenant/billing", tags=["PAQ-06 · Plataforma SaaS"])
billing_platform_router = APIRouter(prefix="/platform/tenants/{tenant_id}/invoices", tags=["PAQ-06 · Plataforma SaaS"])

BillingReader = Annotated[UserModel, Depends(require_permissions("billing.read"))]
PlatformWriter = Annotated[UserModel, Depends(require_platform_permissions("subscriptions.write"))]


@billing_tenant_router.get("/invoices", response_model=ApiResponse[list[InvoiceOut]])
def list_my_invoices(
    ctx: TenantScope,
    actor: BillingReader,
    db: Session = Depends(get_db),
):
    invoices = BillingService(db).listar_por_empresa(ctx.tenant_id)
    out = []
    for inv in invoices:
        item = InvoiceOut.model_validate(inv)
        if inv.subscription and inv.subscription.plan:
            item.plan_name = inv.subscription.plan.name
        out.append(item)
    return ApiResponse(message="Comprobantes obtenidos.", data=out)


@billing_tenant_router.get("/invoices/{invoice_id}/pdf")
def download_my_invoice_pdf(
    invoice_id: UUID,
    ctx: TenantScope,
    actor: BillingReader,
    db: Session = Depends(get_db),
):
    service = BillingService(db)
    inv = service.obtener_comprobante(invoice_id, tenant_id=ctx.tenant_id)
    pdf_bytes = service.pdf(invoice_id, tenant_id=ctx.tenant_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="comprobante-{inv.number}.pdf"'},
    )


@billing_platform_router.get("", response_model=ApiResponse[list[InvoiceOut]])
def list_tenant_invoices(
    tenant_id: UUID,
    actor: PlatformWriter,
    db: Session = Depends(get_db),
):
    service = BillingService(db)
    items = service.listar_por_empresa(tenant_id)
    out: list[InvoiceOut] = []
    for inv in items:
        dto = InvoiceOut.model_validate(inv)
        if inv.subscription and inv.subscription.plan:
            dto.plan_name = inv.subscription.plan.name
        out.append(dto)
    return ApiResponse(data=out)


@billing_platform_router.post("/{invoice_id}/mark-paid", response_model=ApiResponse[InvoiceOut])
def mark_invoice_paid(
    tenant_id: UUID,
    invoice_id: UUID,
    data: MarkPaidRequest,
    actor: PlatformWriter,
    db: Session = Depends(get_db),
):
    service = BillingService(db)
    # Validar que pertenece a la empresa indicada
    inv = service.obtener_comprobante(invoice_id, tenant_id=tenant_id)
    updated = service.registrar_pago(invoice_id, data.reference, actor_plataforma=actor)
    self_out = InvoiceOut.model_validate(updated)
    if updated.subscription and updated.subscription.plan:
        self_out.plan_name = updated.subscription.plan.name
    return ApiResponse(message="Pago registrado correctamente.", data=self_out)
