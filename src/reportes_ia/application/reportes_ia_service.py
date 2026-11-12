from datetime import date, datetime, timezone
import hashlib
import time
from typing import Any, Literal, Optional
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.inventario_sucursales.infrastructure.models.organization import BranchModel
from src.plataforma_saas.infrastructure.models.tenant import TenantModel
from src.reportes_ia.application.cache_interpretaciones import cache_interpretaciones
from src.reportes_ia.application.ejecutor import Ejecutor, ReportResult
from src.reportes_ia.application.exportador import Exportador
from src.reportes_ia.application.interprete import Interprete
from src.reportes_ia.application.narrador import Narrador
from src.reportes_ia.application.validador import Validador
from src.reportes_ia.domain.catalogo import REPORT_DEFINITIONS
from src.reportes_ia.domain.especificacion import InterpretResult, ReportSpec
from src.reportes_ia.infrastructure.models import ReportRequestModel
from src.shared.exceptions.domain_exception import NotFoundError, ValidationError
from src.usuarios_catalogo.infrastructure.models.catalog import CategoryModel, ProductModel


class ReportesIAService:
    def __init__(self, db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID | None = None) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.validador = Validador(db)
        self.ejecutor = Ejecutor(db)
        self.narrador = Narrador()
        self.exportador = Exportador()

    def obtener_definiciones(self) -> list[dict[str, Any]]:
        return [
            {
                "code": d.code,
                "title": d.title,
                "description": d.description,
                "metrics": [m.value for m in d.metrics],
                "dimensions": [dim.value for dim in d.dimensions],
                "default_chart": d.default_chart.value,
                "examples": list(d.examples),
            }
            for d in REPORT_DEFINITIONS.values()
        ]

    def interpretar(self, texto: str, canal: str = "TEXT", hoy: date | None = None) -> dict[str, Any]:
        cached_dict = cache_interpretaciones.get(self.tenant_id, texto)
        if cached_dict:
            result: InterpretResult = InterpretResult.model_validate(cached_dict)
            result.interpreter = "CACHE"
        else:
            # Cargar catálogo contextual de la empresa
            branches = [
                {"id": str(b.id), "name": b.name}
                for b in self.db.scalars(
                    select(BranchModel).where(BranchModel.tenant_id == self.tenant_id, BranchModel.deleted_at.is_(None))
                ).all()
            ]
            categories = [
                {"id": str(c.id), "name": c.name}
                for c in self.db.scalars(select(CategoryModel).where(CategoryModel.tenant_id == self.tenant_id)).all()
            ]
            products = [
                {"id": str(p.id), "name": p.name}
                for p in self.db.scalars(
                    select(ProductModel).where(ProductModel.tenant_id == self.tenant_id, ProductModel.is_active.is_(True))
                ).all()[:300]
            ]
            catalogo = {"branches": branches, "categories": categories, "products": products}

            interprete = Interprete(catalogo)
            result: InterpretResult = interprete.interpretar(texto, hoy)
            if result.status == "READY" and result.spec:
                cache_interpretaciones.set(self.tenant_id, texto, result)

        # Registrar solicitud en la base de datos
        spec_dict = result.spec.model_dump(mode="json") if result.spec else {}
        req = ReportRequestModel(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            prompt_sha256=hashlib.sha256(texto.encode("utf-8")).hexdigest(),
            prompt_length=len(texto),
            interpreted_spec=spec_dict,
            source=canal,
            definition_code=result.spec.definition_code if result.spec else None,
            status=result.status,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(req)
        self.db.commit()
        self.db.refresh(req)

        res_dict = result.model_dump(mode="json")
        res_dict["request_id"] = str(req.id)
        return res_dict

    def ejecutar(self, spec_data: dict[str, Any] | ReportSpec, request_id: uuid.UUID | None = None) -> dict[str, Any]:
        start_time = time.time()
        spec = spec_data if isinstance(spec_data, ReportSpec) else ReportSpec.model_validate(spec_data)

        # 1. Validar especificación y aislar tenant
        sv = self.validador.validar(spec, self.tenant_id)

        # 2. Ejecutar consulta parametrizada
        result: ReportResult = self.ejecutor.ejecutar(sv)

        # 3. Generar narrativa inteligente
        narrativa = self.narrador.narrar(spec, result)

        duration_ms = int((time.time() - start_time) * 1000)

        # 4. Actualizar solicitud si se proporcionó request_id
        if request_id:
            req = self.db.get(ReportRequestModel, request_id)
            if req and req.tenant_id == self.tenant_id:
                req.status = "EXECUTED"
                req.rows_count = len(result.rows)
                req.duration_ms = duration_ms
                req.execution_result = {
                    "rows_count": len(result.rows),
                    "totals": result.totals,
                    "narrative": narrativa,
                }
                self.db.commit()

        # Contador de uso mensual
        uso = self.uso_mensual()

        return {
            "request_id": str(request_id) if request_id else None,
            "definition_code": result.definition_code,
            "title": result.title,
            "columns": result.columns,
            "rows": result.rows,
            "groups": result.groups,
            "totals": result.totals,
            "chart": result.chart,
            "series": result.series,
            "narrative": narrativa,
            "truncated": result.truncated,
            "duration_ms": duration_ms,
            "usage": uso,
        }

    def exportar(
        self, spec_data: dict[str, Any] | ReportSpec, formato: Literal["xlsx", "pdf", "csv"], request_id: uuid.UUID | None = None
    ) -> tuple[bytes, str, str]:
        spec = spec_data if isinstance(spec_data, ReportSpec) else ReportSpec.model_validate(spec_data)
        sv = self.validador.validar(spec, self.tenant_id)
        result: ReportResult = self.ejecutor.ejecutar(sv)
        narrativa = self.narrador.narrar(spec, result)

        tenant = self.db.get(TenantModel, self.tenant_id)
        empresa = tenant.trade_name if tenant and tenant.trade_name else "FashionStore"

        formato_norm = formato.lower()
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M")
        base_name = f"reporte_{result.definition_code}_{timestamp_str}"

        if formato_norm == "xlsx":
            content = self.exportador.xlsx(spec, result, empresa)
            filename = f"{base_name}.xlsx"
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        elif formato_norm == "pdf":
            content = self.exportador.pdf(spec, result, empresa, narrativa)
            filename = f"{base_name}.pdf"
            media_type = "application/pdf"
        elif formato_norm == "csv":
            content = self.exportador.csv(spec, result, empresa)
            filename = f"{base_name}.csv"
            media_type = "text/csv; charset=utf-8"
        else:
            raise ValidationError(f"Formato no soportado: '{formato}'. Use xlsx, pdf o csv.")

        if request_id:
            req = self.db.get(ReportRequestModel, request_id)
            if req and req.tenant_id == self.tenant_id:
                req.export_format = formato_norm
                req.status = "EXPORTED"
                self.db.commit()

        return content, filename, media_type

    def historial(self, solo_mios: bool = False, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        stmt = select(ReportRequestModel).where(ReportRequestModel.tenant_id == self.tenant_id)
        if solo_mios and self.user_id:
            stmt = stmt.where(ReportRequestModel.user_id == self.user_id)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = self.db.scalar(count_stmt) or 0

        offset = max(0, (page - 1) * page_size)
        stmt = stmt.order_by(ReportRequestModel.created_at.desc()).offset(offset).limit(page_size)
        items = self.db.scalars(stmt).all()

        # Cache nombres de usuario
        user_ids = {item.user_id for item in items if item.user_id}
        users_map = {}
        if user_ids:
            u_rows = self.db.scalars(select(UserModel).where(UserModel.id.in_(user_ids))).all()
            for u in u_rows:
                users_map[u.id] = f"{u.first_name} {u.last_name}".strip() or u.email

        history_items = []
        for it in items:
            defn = REPORT_DEFINITIONS.get(it.definition_code or "")
            title = defn.title if defn else (it.definition_code or "Reporte")
            history_items.append({
                "id": str(it.id),
                "created_at": it.created_at.isoformat(),
                "prompt_length": it.prompt_length,
                "title": title,
                "definition_code": it.definition_code,
                "user_name": users_map.get(it.user_id, "Sistema"),
                "channel": it.source,
                "status": it.status,
                "rows": it.rows_count,
                "export_format": it.export_format,
                "spec": it.interpreted_spec,
            })

        return {
            "items": history_items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def uso_mensual(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        start_of_month = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        count = self.db.scalar(
            select(func.count(ReportRequestModel.id)).where(
                ReportRequestModel.tenant_id == self.tenant_id,
                ReportRequestModel.status.in_(["EXECUTED", "EXPORTED"]),
                ReportRequestModel.created_at >= start_of_month,
            )
        ) or 0
        limit = 1000
        return {"used": count, "limit": limit}
