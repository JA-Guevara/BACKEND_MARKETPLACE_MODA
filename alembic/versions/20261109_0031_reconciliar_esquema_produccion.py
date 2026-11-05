"""Reconcilia el esquema de produccion con la cabeza real de Alembic.

Revision ID: 20261109_0031
Revises: 20261108_0028

Produccion tenia el sello ``20261108_0030``, una revision que no existe en el
repositorio, y un esquema mixto: le faltaban objetos de 0024, 0026 y 0030.
``scripts/reconciliar_produccion.py`` corrige el sello a ``20261108_0028`` y
ejecuta esta migracion dentro de la misma transaccion.

La migracion es idempotente. En una base que ya esta en ``20261108_0028`` solo:

- agrega el indice ``ix_report_requests_user_id`` que declara el ORM;
- elimina la tabla temporal vacia ``_rs_catalog_copies`` que dejo 0019;
- revoca permisos de plataforma asignados a roles de empresa.

El downgrade es deliberadamente conservador: no elimina objetos que pertenecen
a migraciones anteriores, porque no puede distinguir si ya existian antes de
esta reparacion. Solo revierte el indice nuevo y recrea la tabla temporal.
"""
from collections.abc import Sequence
from datetime import datetime, timezone
import json
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "20261109_0031"
down_revision: str | None = "20261108_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


NEW_PERMISSIONS = [
    # 0026 · Reportes con IA
    (
        "20000000-0000-0000-0000-000000000039",
        "ai_reports.use",
        "Generar reportes con IA",
        "Interpretar consultas en lenguaje natural y voz, y ejecutar reportes inteligentes",
        "ai_reports",
        "tenant",
    ),
    (
        "20000000-0000-0000-0000-000000000040",
        "ai_reports.history",
        "Consultar historial de reportes IA",
        "Ver consultas y reportes previamente ejecutados con IA",
        "ai_reports",
        "tenant",
    ),
    # 0030 · Tienda publica, marca y cobros propios
    (
        "20000000-0000-0000-0000-000000000053",
        "storefront.write",
        "Gestionar tienda publica y marca",
        "Editar marca, logo, banner y publicar tienda",
        "storefront",
        "tenant",
    ),
    (
        "20000000-0000-0000-0000-000000000054",
        "payment_methods.write",
        "Gestionar metodos de cobro",
        "Configurar QR, cuentas bancarias y cobros propios",
        "storefront",
        "tenant",
    ),
    (
        "20000000-0000-0000-0000-000000000055",
        "catalog_templates.write",
        "Gestionar plantillas de catalogo",
        "Crear y mantener plantillas globales de categorias y atributos",
        "platform",
        "platform",
    ),
    (
        "20000000-0000-0000-0000-000000000056",
        "upgrade_requests.manage",
        "Gestionar solicitudes de ampliacion",
        "Atender y responder solicitudes de cambio de plan y cuotas",
        "platform",
        "platform",
    ),
]


DEFAULT_TEMPLATES = [
    {
        "code": "boutique",
        "name": "Boutique Femenina",
        "description": "Vestidos, blusas, faldas y conjuntos elegantes",
        "payload": {
            "categories": ["Vestidos de Fiesta", "Blusas de Seda", "Faldas Midi", "Conjuntos Sastre"],
            "sizes": ["XS", "S", "M", "L", "XL"],
            "colors": ["Negro", "Marfil", "Rosa Palo", "Vino", "Azul Noche"],
            "seasons": ["Otoño - Invierno", "Primavera - Verano"],
        },
    },
    {
        "code": "urbana",
        "name": "Moda Urbana Streetwear",
        "description": "Poleras oversized, hoodies, joggers y chaquetas bomber",
        "payload": {
            "categories": ["Poleras Oversized", "Hoodies", "Pantalones Cargo", "Chaquetas Bomber"],
            "sizes": ["S", "M", "L", "XL", "XXL"],
            "colors": ["Negro", "Blanco", "Gris Melange", "Verde Militar", "Beige"],
            "seasons": ["Atemporal", "Invierno"],
        },
    },
    {
        "code": "calzado",
        "name": "Calzado y Zapatillas",
        "description": "Zapatos formales, zapatillas urbanas y sandalias",
        "payload": {
            "categories": ["Zapatillas Urbanas", "Zapatos Formales", "Botines de Cuero", "Sandalias"],
            "sizes": ["36", "37", "38", "39", "40", "41", "42", "43"],
            "colors": ["Negro", "Blanco", "Café", "Miel", "Azul Marino"],
            "seasons": ["Atemporal"],
        },
    },
    {
        "code": "deportiva",
        "name": "Ropa Deportiva & Fitness",
        "description": "Leggings, tops deportivos, shorts y rompevientos",
        "payload": {
            "categories": ["Leggings de Compresión", "Tops Deportivos", "Shorts Running", "Rompevientos"],
            "sizes": ["XS", "S", "M", "L"],
            "colors": ["Negro", "Gris", "Fucsia Neón", "Azul Eléctrico", "Verde Lima"],
            "seasons": ["Continuo"],
        },
    },
]


def _table_exists(bind, table: str) -> bool:
    return table in sa.inspect(bind).get_table_names()


def _column_names(bind, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def _index_exists(bind, table: str, index: str) -> bool:
    return index in {item["name"] for item in sa.inspect(bind).get_indexes(table)}


def _unique_exists(bind, table: str, name: str) -> bool:
    return name in {item["name"] for item in sa.inspect(bind).get_unique_constraints(table)}


def _bool_default(bind, value: bool):
    return sa.text("1" if bind.dialect.name == "sqlite" else ("true" if value else "false"))


def _create_table_if_missing(bind, name, columns, indexes=()):
    """Crea la tabla si falta; si existe, exige que tenga todas las columnas."""
    if _table_exists(bind, name):
        expected = {column.name for column in columns if isinstance(column, sa.Column)}
        missing = sorted(expected - _column_names(bind, name))
        if missing:
            raise RuntimeError(
                f"La tabla {name} existe pero le faltan columnas: {', '.join(missing)}. "
                "Revisar el esquema antes de continuar."
            )
    else:
        op.create_table(name, *columns)

    for index_name, index_columns in indexes:
        if not _index_exists(bind, name, index_name):
            op.create_index(index_name, name, index_columns)


def _ensure_tenants(bind) -> None:
    if not _table_exists(bind, "tenants"):
        raise RuntimeError("No existe la tabla tenants; no se puede reconciliar la tienda publica.")

    columns = {
        "is_published": sa.Column("is_published", sa.Boolean(), nullable=False, server_default=_bool_default(bind, False)),
        "published_at": sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        "logo_url": sa.Column("logo_url", sa.String(length=300), nullable=True),
        "banner_url": sa.Column("banner_url", sa.String(length=300), nullable=True),
        "brand_color": sa.Column("brand_color", sa.String(length=7), nullable=True),
        "slogan": sa.Column("slogan", sa.String(length=160), nullable=True),
        "about": sa.Column("about", sa.String(length=1000), nullable=True),
        "whatsapp": sa.Column("whatsapp", sa.String(length=30), nullable=True),
        "social_links": sa.Column("social_links", sa.JSON(), nullable=True, server_default=sa.text("'{}'")),
        "shipping_policy": sa.Column("shipping_policy", sa.String(length=1000), nullable=True),
        "seo_title": sa.Column("seo_title", sa.String(length=70), nullable=True),
        "seo_description": sa.Column("seo_description", sa.String(length=160), nullable=True),
        "city": sa.Column("city", sa.String(length=80), nullable=True),
        "is_featured": sa.Column("is_featured", sa.Boolean(), nullable=False, server_default=_bool_default(bind, False)),
    }
    existing = _column_names(bind, "tenants")
    for name, column in columns.items():
        if name not in existing:
            op.add_column("tenants", column)

    # Publicar las empresas activas que no sean sandbox, igual que 0030.
    existing = _column_names(bind, "tenants")
    if {"is_published", "published_at"} <= existing:
        sandbox = ""
        if "is_sandbox" in existing:
            sandbox = " AND (is_sandbox = :sandbox_false OR is_sandbox IS NULL)"
        bind.execute(
            sa.text(
                "UPDATE tenants SET is_published = :published, published_at = :now "
                "WHERE status = 'ACTIVA'"
                f"{sandbox} AND (is_published = :not_published OR published_at IS NULL)"
            ),
            {
                "published": True,
                "not_published": False,
                "sandbox_false": False,
                "now": datetime.now(timezone.utc),
            },
        )


def _ensure_users(bind) -> None:
    if _table_exists(bind, "users") and "must_change_password" not in _column_names(bind, "users"):
        op.add_column(
            "users",
            sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=_bool_default(bind, False)),
        )


def _create_ml_models(bind) -> None:
    op.create_table(
        "ml_models",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("model_type", sa.String(50), nullable=False),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("artifact", sa.LargeBinary(), nullable=False),
        sa.Column("artifact_bytes", sa.Integer(), nullable=False),
        sa.Column("artifact_sha256", sa.CHAR(64), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=_bool_default(bind, True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_ml_models_tenant_id_tenants"),
        sa.PrimaryKeyConstraint("id", name="pk_ml_models"),
    )
    op.create_index("ix_ml_models_tenant_active", "ml_models", ["tenant_id", "is_active"])


def _ensure_ml_models(bind) -> None:
    if not _table_exists(bind, "ml_models"):
        _create_ml_models(bind)
        return

    rows = bind.execute(sa.text("SELECT count(*) FROM ml_models")).scalar() or 0
    missing = [
        name
        for name in ("artifact", "artifact_bytes", "artifact_sha256")
        if name not in _column_names(bind, "ml_models")
    ]
    if rows and missing:
        raise RuntimeError(
            "ml_models contiene filas y le faltan columnas de artefacto. "
            "No se puede convertir file_path a BYTEA automaticamente; revisar los datos."
        )

    if "artifact" not in _column_names(bind, "ml_models"):
        op.add_column("ml_models", sa.Column("artifact", sa.LargeBinary(), nullable=False))
    if "artifact_bytes" not in _column_names(bind, "ml_models"):
        op.add_column("ml_models", sa.Column("artifact_bytes", sa.Integer(), nullable=False))
    if "artifact_sha256" not in _column_names(bind, "ml_models"):
        op.add_column("ml_models", sa.Column("artifact_sha256", sa.CHAR(64), nullable=False))

    if "file_path" in _column_names(bind, "ml_models"):
        if rows:
            raise RuntimeError(
                "ml_models contiene filas con file_path; migrarlas a artifact antes de eliminar la columna."
            )
        with op.batch_alter_table("ml_models") as batch:
            batch.drop_column("file_path")


def _ensure_report_requests(bind) -> None:
    _create_table_if_missing(
        bind,
        "report_requests",
        [
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=True),
            sa.Column("prompt_sha256", sa.CHAR(64), nullable=False),
            sa.Column("prompt_length", sa.Integer(), nullable=False),
            sa.Column("interpreted_spec", sa.JSON(), nullable=False),
            sa.Column("execution_result", sa.JSON(), nullable=True),
            sa.Column("audio_duration_seconds", sa.Float(), nullable=True),
            sa.Column("source", sa.String(length=20), nullable=False, server_default="TEXT"),
            sa.Column("definition_code", sa.String(length=50), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=True, server_default="EXECUTED"),
            sa.Column("export_format", sa.String(length=10), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("rows_count", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_report_requests_tenant_id_tenants"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL", name="fk_report_requests_user_id_users"),
            sa.PrimaryKeyConstraint("id", name="pk_report_requests"),
        ],
        indexes=[
            ("ix_report_requests_tenant_id", ["tenant_id"]),
            ("ix_report_requests_created_at", ["created_at"]),
            ("ix_report_requests_user_id", ["user_id"]),
        ],
    )


def _ensure_storefront(bind) -> None:
    _create_table_if_missing(
        bind,
        "tenant_payment_methods",
        [
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("kind", sa.String(length=16), nullable=False),
            sa.Column("label", sa.String(length=80), nullable=False),
            sa.Column("qr_image_url", sa.String(length=300), nullable=True),
            sa.Column("bank_name", sa.String(length=80), nullable=True),
            sa.Column("account_holder", sa.String(length=120), nullable=True),
            sa.Column("account_number", sa.String(length=40), nullable=True),
            sa.Column("instructions", sa.String(length=500), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=_bool_default(bind, True)),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_tenant_payment_methods_tenant_id_tenants"),
            sa.PrimaryKeyConstraint("id", name="pk_tenant_payment_methods"),
        ],
        indexes=[("ix_tenant_payment_methods_tenant_id", ["tenant_id"])],
    )

    _create_table_if_missing(
        bind,
        "catalog_templates",
        [
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("code", sa.String(length=40), nullable=False),
            sa.Column("name", sa.String(length=80), nullable=False),
            sa.Column("description", sa.String(length=300), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=_bool_default(bind, True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("code", name="uq_catalog_templates_code"),
            sa.PrimaryKeyConstraint("id", name="pk_catalog_templates"),
        ],
    )

    _create_table_if_missing(
        bind,
        "catalog_template_imports",
        [
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("template_id", sa.Uuid(), nullable=False),
            sa.Column("imported_by", sa.Uuid(), nullable=True),
            sa.Column("counts", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_catalog_template_imports_tenant_id_tenants"),
            sa.ForeignKeyConstraint(["template_id"], ["catalog_templates.id"], ondelete="CASCADE", name="fk_catalog_template_imports_template_id_catalog_templates"),
            sa.PrimaryKeyConstraint("id", name="pk_catalog_template_imports"),
        ],
        indexes=[("ix_catalog_template_imports_tenant_id", ["tenant_id"])],
    )

    _create_table_if_missing(
        bind,
        "upgrade_requests",
        [
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("requested_by", sa.Uuid(), nullable=False),
            sa.Column("kind", sa.String(length=12), nullable=False),
            sa.Column("target", sa.String(length=60), nullable=False),
            sa.Column("message", sa.String(length=500), nullable=True),
            sa.Column("status", sa.String(length=10), nullable=False, server_default=sa.text("'ABIERTA'")),
            sa.Column("handled_by", sa.Uuid(), nullable=True),
            sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("response", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_upgrade_requests_tenant_id_tenants"),
            sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="CASCADE", name="fk_upgrade_requests_requested_by_users"),
            sa.PrimaryKeyConstraint("id", name="pk_upgrade_requests"),
        ],
        indexes=[("ix_upgrade_requests_tenant_id", ["tenant_id"])],
    )

    _create_table_if_missing(
        bind,
        "usage_alerts",
        [
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("limit_code", sa.String(length=40), nullable=False),
            sa.Column("level", sa.SmallInteger(), nullable=False),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_usage_alerts_tenant_id_tenants"),
            sa.PrimaryKeyConstraint("tenant_id", "limit_code", "level", name="pk_usage_alerts"),
        ],
    )

    now = datetime.now(timezone.utc)
    for template in DEFAULT_TEMPLATES:
        exists = bind.execute(
            sa.text("SELECT 1 FROM catalog_templates WHERE code = :code"),
            {"code": template["code"]},
        ).scalar()
        if exists:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO catalog_templates (id, code, name, description, payload, is_active, created_at, updated_at) "
                "VALUES (:id, :code, :name, :description, :payload, :is_active, :now, :now)"
            ),
            {
                "id": uuid.uuid4(),
                "code": template["code"],
                "name": template["name"],
                "description": template["description"],
                "payload": json.dumps(template["payload"]),
                "is_active": True,
                "now": now,
            },
        )


def _ensure_permissions(bind) -> None:
    if not _table_exists(bind, "permissions"):
        raise RuntimeError("No existe la tabla permissions; no se pueden sembrar los permisos nuevos.")

    now = datetime.now(timezone.utc)
    for pid, code, name, description, module, scope in NEW_PERMISSIONS:
        perm_uuid = uuid.UUID(pid)
        existing_by_code = bind.execute(
            sa.text("SELECT id FROM permissions WHERE code = :code"),
            {"code": code},
        ).scalar()
        if existing_by_code:
            continue

        existing_by_id = bind.execute(
            sa.text("SELECT code FROM permissions WHERE id = :id"),
            {"id": perm_uuid},
        ).scalar()
        if existing_by_id:
            bind.execute(
                sa.text(
                    "UPDATE permissions SET "
                    "code = :code, name = :name, description = :description, "
                    "module = :module, scope = :scope, is_active = True, updated_at = :now "
                    "WHERE id = :id"
                ),
                {
                    "id": perm_uuid,
                    "code": code,
                    "name": name,
                    "description": description,
                    "module": module,
                    "scope": scope,
                    "now": now,
                },
            )
            continue

        bind.execute(
            sa.text(
                "INSERT INTO permissions (id, code, name, description, module, scope, is_active, created_at, updated_at) "
                "VALUES (:id, :code, :name, :description, :module, :scope, :is_active, :now, :now)"
            ),
            {
                "id": perm_uuid,
                "code": code,
                "name": name,
                "description": description,
                "module": module,
                "scope": scope,
                "is_active": True,
                "now": now,
            },
        )

    # Asignaciones de 0026: ai_reports.* al rol admin.
    bind.execute(
        sa.text(
            "INSERT INTO role_permissions (role_id, permission_id) "
            "SELECT r.id, p.id FROM roles r, permissions p "
            "WHERE r.code = 'admin' AND p.code IN ('ai_reports.use', 'ai_reports.history') "
            "AND NOT EXISTS (SELECT 1 FROM role_permissions rp "
            "WHERE rp.role_id = r.id AND rp.permission_id = p.id)"
        )
    )
    # Asignaciones de 0030: tienda y cobros a roles de empresa.
    bind.execute(
        sa.text(
            "INSERT INTO role_permissions (role_id, permission_id) "
            "SELECT r.id, p.id FROM roles r, permissions p "
            "WHERE r.code IN ('admin', 'superadmin', 'store_manager') "
            "AND p.code IN ('storefront.write', 'payment_methods.write') "
            "AND NOT EXISTS (SELECT 1 FROM role_permissions rp "
            "WHERE rp.role_id = r.id AND rp.permission_id = p.id)"
        )
    )
    # Asignaciones de 0030: plantillas y solicitudes a plataforma.
    bind.execute(
        sa.text(
            "INSERT INTO role_permissions (role_id, permission_id) "
            "SELECT r.id, p.id FROM roles r, permissions p "
            "WHERE r.code = 'platform_admin' AND r.audience = 'PLATFORM' "
            "AND p.code IN ('catalog_templates.write', 'upgrade_requests.manage') "
            "AND NOT EXISTS (SELECT 1 FROM role_permissions rp "
            "WHERE rp.role_id = r.id AND rp.permission_id = p.id)"
        )
    )

    # 0024 y 0030 asignaban permisos globales a roles de empresa. Corregir
    # tambien las asignaciones ya existentes, tanto en el camino limpio como
    # en el esquema mixto; no alcanza con dejar de insertarlas.
    tenant_role = "r.audience <> 'PLATFORM'"
    if "tenant_id" in _column_names(bind, "roles"):
        tenant_role += " OR r.tenant_id IS NOT NULL"
    bind.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM permissions WHERE scope = 'platform') "
            f"AND role_id IN (SELECT r.id FROM roles r WHERE {tenant_role})"
        )
    )

    if _table_exists(bind, "module_permissions") and _table_exists(bind, "platform_modules"):
        bind.execute(
            sa.text(
                "INSERT INTO module_permissions (module_code, permission_id) "
                "SELECT 'ai_reports', p.id FROM permissions p "
                "WHERE p.code IN ('ai_reports.use', 'ai_reports.history') "
                "AND EXISTS (SELECT 1 FROM platform_modules m WHERE m.code = 'ai_reports') "
                "AND NOT EXISTS (SELECT 1 FROM module_permissions mp "
                "WHERE mp.module_code = 'ai_reports' AND mp.permission_id = p.id)"
            )
        )


def _ensure_module_permissions_unique(bind) -> None:
    if not _table_exists(bind, "module_permissions"):
        return
    if _unique_exists(bind, "module_permissions", "uq_module_permissions_permission_id"):
        return

    duplicates = bind.execute(
        sa.text(
            "SELECT permission_id FROM module_permissions "
            "GROUP BY permission_id HAVING count(*) > 1"
        )
    ).fetchall()
    if duplicates:
        raise RuntimeError(
            "module_permissions tiene permission_id duplicados; limpiar antes de crear la restriccion unica."
        )

    with op.batch_alter_table("module_permissions") as batch:
        batch.create_unique_constraint("uq_module_permissions_permission_id", ["permission_id"])


def _drop_catalog_copies(bind) -> None:
    if not _table_exists(bind, "_rs_catalog_copies"):
        return
    rows = bind.execute(sa.text("SELECT count(*) FROM _rs_catalog_copies")).scalar() or 0
    if rows:
        raise RuntimeError(
            "_rs_catalog_copies contiene filas; no se elimina automaticamente. Revisar el respaldo de 0019."
        )
    op.drop_table("_rs_catalog_copies")


def upgrade() -> None:
    bind = op.get_bind()
    _ensure_tenants(bind)
    _ensure_users(bind)
    _ensure_ml_models(bind)
    _ensure_report_requests(bind)
    _ensure_storefront(bind)
    _ensure_permissions(bind)
    _ensure_module_permissions_unique(bind)
    _drop_catalog_copies(bind)


def downgrade() -> None:
    bind = op.get_bind()

    if _table_exists(bind, "report_requests") and _index_exists(bind, "report_requests", "ix_report_requests_user_id"):
        op.drop_index("ix_report_requests_user_id", table_name="report_requests")

    if not _table_exists(bind, "_rs_catalog_copies"):
        op.create_table(
            "_rs_catalog_copies",
            sa.Column("table_name", sa.String(50), nullable=False),
            sa.Column("copy_id", sa.Uuid(), nullable=False, primary_key=True),
            sa.Column("original_id", sa.Uuid(), nullable=False),
        )
