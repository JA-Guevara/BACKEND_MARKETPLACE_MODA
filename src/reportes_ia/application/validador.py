from dataclasses import dataclass, field
import uuid
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.inventario_sucursales.infrastructure.models.organization import BranchModel
from src.reportes_ia.domain.catalogo import REPORT_DEFINITIONS, compatible
from src.reportes_ia.domain.especificacion import ReportSpec
from src.reportes_ia.domain.texto import normalizar
from src.shared.exceptions.domain_exception import NotFoundError, ValidationError
from src.usuarios_catalogo.infrastructure.models.catalog import CategoryModel, ProductModel


@dataclass(frozen=True)
class SpecValidada:
    spec: ReportSpec
    tenant_id: uuid.UUID
    branch_ids: list[uuid.UUID] = field(default_factory=list)
    category_ids: list[uuid.UUID] = field(default_factory=list)
    product_ids: list[uuid.UUID] = field(default_factory=list)
    max_rows: int = 500


class Validador:
    def __init__(self, db: Session) -> None:
        self.db = db

    def validar(self, spec: ReportSpec, tenant_id: uuid.UUID) -> SpecValidada:
        defn = REPORT_DEFINITIONS.get(spec.definition_code)
        if not defn:
            raise ValidationError(f"El reporte '{spec.definition_code}' no existe en el catálogo.")

        errores = compatible(defn, spec)
        if errores:
            raise ValidationError("; ".join(errores))

        # Validar top_n
        if spec.top_n and spec.top_n > 50:
            raise ValidationError("top_n no puede exceder 50 filas.")

        # Resolver nombres de sucursales a IDs dentro del tenant
        branch_ids: list[uuid.UUID] = []
        if spec.filters.branch_names:
            branches = self.db.scalars(
                select(BranchModel).where(
                    BranchModel.tenant_id == tenant_id,
                    BranchModel.deleted_at.is_(None),
                )
            ).all()
            for bname in spec.filters.branch_names:
                norm_target = normalizar(bname).strip()
                match = next((b for b in branches if normalizar(b.name).strip() == norm_target), None)
                if match:
                    branch_ids.append(match.id)

        # Resolver nombres de categorías a IDs dentro del tenant
        category_ids: list[uuid.UUID] = []
        if spec.filters.category_names:
            cats = self.db.scalars(
                select(CategoryModel).where(CategoryModel.tenant_id == tenant_id)
            ).all()
            for cname in spec.filters.category_names:
                norm_target = normalizar(cname).strip()
                match = next((c for c in cats if normalizar(c.name).strip() == norm_target), None)
                if match:
                    category_ids.append(match.id)

        # Resolver nombres de productos a IDs dentro del tenant
        product_ids: list[uuid.UUID] = []
        if spec.filters.product_names:
            prods = self.db.scalars(
                select(ProductModel).where(ProductModel.tenant_id == tenant_id)
            ).all()
            for pname in spec.filters.product_names:
                norm_target = normalizar(pname).strip()
                match = next((p for p in prods if normalizar(p.name).strip() == norm_target), None)
                if match:
                    product_ids.append(match.id)

        return SpecValidada(
            spec=spec,
            tenant_id=tenant_id,
            branch_ids=branch_ids,
            category_ids=category_ids,
            product_ids=product_ids,
            max_rows=defn.max_rows,
        )
