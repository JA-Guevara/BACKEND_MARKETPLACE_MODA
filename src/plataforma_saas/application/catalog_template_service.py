"""Servicio de plantillas globales de catálogo e importación a empresas (RS-3)."""
import re
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.plataforma_saas.infrastructure.models.storefront import (
    CatalogTemplateImportModel,
    CatalogTemplateModel,
)
from src.plataforma_saas.web.schemas.storefront import (
    CatalogTemplateIn,
    CatalogTemplateOut,
    ImportResult,
)
from src.shared.exceptions.domain_exception import ConflictError, NotFoundError, ValidationError
from src.usuarios_catalogo.infrastructure.models.catalog import (
    CategoryModel,
    ColorModel,
    SeasonModel,
    SizeModel,
)

DEFAULT_COLOR_HEX = {
    "Negro": "#000000",
    "Blanco": "#FFFFFF",
    "Marfil": "#FFFFF0",
    "Rosa Palo": "#E8C5C8",
    "Vino": "#722F37",
    "Azul Noche": "#0A1172",
    "Gris Melange": "#808080",
    "Gris": "#808080",
    "Verde Militar": "#4B5320",
    "Beige": "#F5F5DC",
    "Café": "#4B2E1E",
    "Miel": "#D99B26",
    "Azul Marino": "#000080",
    "Fucsia Neón": "#FF007F",
    "Azul Eléctrico": "#0066FF",
    "Verde Lima": "#32CD32",
}


def _slugify(text: str) -> str:
    s = text.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "-", s)
    return s.strip("-")


class CatalogTemplateService:
    def __init__(self, db: Session):
        self.db = db

    def listar(self) -> list[CatalogTemplateOut]:
        items = self.db.scalars(
            select(CatalogTemplateModel).where(CatalogTemplateModel.is_active.is_(True)).order_by(CatalogTemplateModel.name.asc())
        ).all()

        results: list[CatalogTemplateOut] = []
        for tpl in items:
            usage = (
                self.db.scalar(
                    select(func.count(CatalogTemplateImportModel.id)).where(
                        CatalogTemplateImportModel.template_id == tpl.id
                    )
                )
                or 0
            )
            out = CatalogTemplateOut(
                id=tpl.id,
                code=tpl.code,
                name=tpl.name,
                description=tpl.description,
                payload=tpl.payload,
                is_active=tpl.is_active,
                usage_count=usage,
            )
            results.append(out)
        return results

    def crear(self, data: CatalogTemplateIn, actor: UserModel | None = None) -> CatalogTemplateOut:
        existente = self.db.scalar(
            select(CatalogTemplateModel).where(CatalogTemplateModel.code == data.code)
        )
        if existente:
            raise ConflictError("Ya existe una plantilla con ese código.")

        if not data.payload.get("categories"):
            raise ValidationError("La plantilla debe contener al menos una categoría.")

        tpl = CatalogTemplateModel(
            code=data.code,
            name=data.name,
            description=data.description,
            payload=data.payload,
            is_active=True,
        )
        self.db.add(tpl)
        self.db.flush()

        if actor:
            RecordAuditEvent(self.db).execute(
                actor_user_id=actor.id,
                action="platform.catalog_template_created",
                entity_type="catalog_template",
                entity_id=str(tpl.id),
                description=f"Plantilla de catálogo creada: {tpl.name} ({tpl.code}).",
            )

        self.db.commit()
        return CatalogTemplateOut(
            id=tpl.id,
            code=tpl.code,
            name=tpl.name,
            description=tpl.description,
            payload=tpl.payload,
            is_active=tpl.is_active,
            usage_count=0,
        )

    def actualizar(
        self, tpl_id: UUID, data: CatalogTemplateIn, actor: UserModel | None = None
    ) -> CatalogTemplateOut:
        tpl = self.db.get(CatalogTemplateModel, tpl_id)
        if tpl is None:
            raise NotFoundError("Plantilla no encontrada.")

        if not data.payload.get("categories"):
            raise ValidationError("La plantilla debe contener al menos una categoría.")

        tpl.name = data.name
        tpl.description = data.description
        tpl.payload = data.payload

        if actor:
            RecordAuditEvent(self.db).execute(
                actor_user_id=actor.id,
                action="platform.catalog_template_updated",
                entity_type="catalog_template",
                entity_id=str(tpl.id),
                description=f"Plantilla de catálogo actualizada: {tpl.name}.",
            )

        self.db.commit()
        return CatalogTemplateOut(
            id=tpl.id,
            code=tpl.code,
            name=tpl.name,
            description=tpl.description,
            payload=tpl.payload,
            is_active=tpl.is_active,
            usage_count=0,
        )

    def importar(
        self, tenant_id: UUID, template_code: str, actor: UserModel | None = None
    ) -> ImportResult:
        tpl = self.db.scalar(
            select(CatalogTemplateModel).where(
                CatalogTemplateModel.code == template_code,
                CatalogTemplateModel.is_active.is_(True),
            )
        )
        if tpl is None:
            raise NotFoundError(f"Plantilla '{template_code}' no encontrada.")

        payload = tpl.payload or {}
        cat_count = 0
        size_count = 0
        color_count = 0
        season_count = 0

        # Categorías
        for cat_name in payload.get("categories", []):
            slug = _slugify(cat_name)
            existe = self.db.scalar(
                select(CategoryModel).where(
                    CategoryModel.tenant_id == tenant_id,
                    (CategoryModel.slug == slug) | (CategoryModel.name == cat_name),
                )
            )
            if not existe:
                cat = CategoryModel(
                    tenant_id=tenant_id,
                    name=cat_name,
                    slug=slug,
                    description=f"Categoría importada de la plantilla {tpl.name}",
                    is_active=True,
                )
                self.db.add(cat)
                cat_count += 1

        # Tallas
        for idx, size_code in enumerate(payload.get("sizes", [])):
            existe = self.db.scalar(
                select(SizeModel).where(
                    SizeModel.tenant_id == tenant_id,
                    SizeModel.code == size_code,
                )
            )
            if not existe:
                sz = SizeModel(
                    tenant_id=tenant_id,
                    code=size_code,
                    name=f"Talla {size_code}",
                    sort_order=idx,
                    is_active=True,
                )
                self.db.add(sz)
                size_count += 1

        # Colores
        for color_name in payload.get("colors", []):
            existe = self.db.scalar(
                select(ColorModel).where(
                    ColorModel.tenant_id == tenant_id,
                    ColorModel.name == color_name,
                )
            )
            if not existe:
                hex_code = DEFAULT_COLOR_HEX.get(color_name, "#74394E")
                col = ColorModel(
                    tenant_id=tenant_id,
                    name=color_name,
                    hex_code=hex_code,
                    is_active=True,
                )
                self.db.add(col)
                color_count += 1

        # Temporadas
        for season_name in payload.get("seasons", []):
            existe = self.db.scalar(
                select(SeasonModel).where(
                    SeasonModel.tenant_id == tenant_id,
                    SeasonModel.name == season_name,
                )
            )
            if not existe:
                sea = SeasonModel(
                    tenant_id=tenant_id,
                    name=season_name,
                    description=f"Temporada importada de {tpl.name}",
                    is_active=True,
                )
                self.db.add(sea)
                season_count += 1

        counts = {
            "categories": cat_count,
            "sizes": size_count,
            "colors": color_count,
            "seasons": season_count,
        }

        # Registrar importación
        record = CatalogTemplateImportModel(
            tenant_id=tenant_id,
            template_id=tpl.id,
            imported_by=actor.id if actor else None,
            counts=counts,
        )
        self.db.add(record)

        if actor:
            RecordAuditEvent(self.db).execute(
                actor_user_id=actor.id,
                action="tenant.catalog_template_imported",
                entity_type="catalog_template",
                entity_id=str(tpl.id),
                description=f"Plantilla {tpl.name} importada a la empresa.",
                metadata=counts,
            )

        self.db.commit()
        return ImportResult(
            template_code=template_code,
            imported_counts=counts,
            message=f"Plantilla {tpl.name} importada con éxito.",
        )
