"""Tienda pública, marca, cobros propios y plantillas de catálogo (RS-3).

Revision ID: 20261104_0030
Revises: 20261104_0029
"""
from collections.abc import Sequence
from datetime import datetime, timezone
import json
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261104_0030"
down_revision: str | None = "20261104_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_PERMISSIONS = [
    (
        "20000000-0000-0000-0000-000000000053",
        "storefront.write",
        "Gestionar tienda pública y marca",
        "Editar marca, logo, banner y publicar tienda",
        "storefront",
        "tenant",
    ),
    (
        "20000000-0000-0000-0000-000000000054",
        "payment_methods.write",
        "Gestionar métodos de cobro",
        "Configurar QR, cuentas bancarias y cobros propios",
        "storefront",
        "tenant",
    ),
    (
        "20000000-0000-0000-0000-000000000055",
        "catalog_templates.write",
        "Gestionar plantillas de catálogo",
        "Crear y mantener plantillas globales de categorías y atributos",
        "platform",
        "platform",
    ),
    (
        "20000000-0000-0000-0000-000000000056",
        "upgrade_requests.manage",
        "Gestionar solicitudes de ampliación",
        "Atender y responder solicitudes de cambio de plan y cuotas",
        "platform",
        "platform",
    ),
]

ROLE_PLATFORM_ADMIN = uuid.UUID("10000000-0000-0000-0000-000000000006")
ROLE_PLATFORM_BILLING = uuid.UUID("10000000-0000-0000-0000-000000000007")

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


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Columnas en tenants
    with op.batch_alter_table("tenants") as batch_op:
        batch_op.add_column(sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.text("false")))
        batch_op.add_column(sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("logo_url", sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column("banner_url", sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column("brand_color", sa.String(length=7), nullable=True))
        batch_op.add_column(sa.Column("slogan", sa.String(length=160), nullable=True))
        batch_op.add_column(sa.Column("about", sa.String(length=1000), nullable=True))
        batch_op.add_column(sa.Column("whatsapp", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("social_links", sa.JSON(), nullable=True, server_default=sa.text("'{}'")))
        batch_op.add_column(sa.Column("shipping_policy", sa.String(length=1000), nullable=True))
        batch_op.add_column(sa.Column("seo_title", sa.String(length=70), nullable=True))
        batch_op.add_column(sa.Column("seo_description", sa.String(length=160), nullable=True))
        batch_op.add_column(sa.Column("city", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("is_featured", sa.Boolean(), nullable=False, server_default=sa.text("false")))

    # Publicar empresas activas que no sean sandbox
    now_utc = datetime.now(timezone.utc)
    bind.execute(
        sa.text(
            "UPDATE tenants SET is_published = true, published_at = :now "
            "WHERE status = 'ACTIVA' AND (is_sandbox IS FALSE OR is_sandbox IS NULL)"
        ),
        {"now": now_utc},
    )

    # 2. Tabla tenant_payment_methods
    op.create_table(
        "tenant_payment_methods",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("qr_image_url", sa.String(length=300), nullable=True),
        sa.Column("bank_name", sa.String(length=80), nullable=True),
        sa.Column("account_holder", sa.String(length=120), nullable=True),
        sa.Column("account_number", sa.String(length=40), nullable=True),
        sa.Column("instructions", sa.String(length=500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # 3. Tabla catalog_templates
    op.create_table(
        "catalog_templates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String(length=40), unique=True, nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # 4. Tabla catalog_template_imports
    op.create_table(
        "catalog_template_imports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("template_id", sa.Uuid(), sa.ForeignKey("catalog_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("imported_by", sa.Uuid(), nullable=True),
        sa.Column("counts", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # 5. Tabla upgrade_requests
    op.create_table(
        "upgrade_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("requested_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("target", sa.String(length=60), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False, server_default=sa.text("'ABIERTA'")),
        sa.Column("handled_by", sa.Uuid(), nullable=True),
        sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # 6. Tabla usage_alerts
    op.create_table(
        "usage_alerts",
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("limit_code", sa.String(length=40), primary_key=True),
        sa.Column("level", sa.SmallInteger(), primary_key=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # 7. Permisos nuevos
    for pid_str, code, name, desc, module_name, scope in NEW_PERMISSIONS:
        bind.execute(
            sa.text(
                "INSERT INTO permissions (id, code, name, description, module, scope, created_at, updated_at) "
                "VALUES (:id, :code, :name, :description, :module, :scope, :now, :now) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {
                "id": uuid.UUID(pid_str),
                "code": code,
                "name": name,
                "description": desc,
                "module": module_name,
                "scope": scope,
                "now": now_utc,
            },
        )

    # Asignar permisos 55 y 56 a roles de tenant admin
    bind.execute(
        sa.text(
            "INSERT INTO role_permissions (role_id, permission_id) "
            "SELECT r.id, p.id FROM roles r, permissions p "
            "WHERE r.name IN ('admin', 'superadmin', 'store_manager') "
            "AND p.code IN ('storefront.write', 'payment_methods.write') "
            "ON CONFLICT DO NOTHING"
        )
    )

    # Asignar permisos 57 y 58 a platform_admin
    bind.execute(
        sa.text(
            "INSERT INTO role_permissions (role_id, permission_id) "
            "SELECT r.id, p.id FROM roles r, permissions p "
            "WHERE r.name IN ('platform_admin', 'superadmin') "
            "AND p.code IN ('catalog_templates.write', 'upgrade_requests.manage') "
            "ON CONFLICT DO NOTHING"
        )
    )

    # Sembrar plantillas de catálogo
    for tpl in DEFAULT_TEMPLATES:
        bind.execute(
            sa.text(
                "INSERT INTO catalog_templates (id, code, name, description, payload, is_active, created_at, updated_at) "
                "VALUES (:id, :code, :name, :description, :payload, true, :now, :now) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {
                "id": uuid.uuid4(),
                "code": tpl["code"],
                "name": tpl["name"],
                "description": tpl["description"],
                "payload": json.dumps(tpl["payload"]),
                "now": now_utc,
            },
        )


def downgrade() -> None:
    op.drop_table("usage_alerts")
    op.drop_table("upgrade_requests")
    op.drop_table("catalog_template_imports")
    op.drop_table("catalog_templates")
    op.drop_table("tenant_payment_methods")

    with op.batch_alter_table("tenants") as batch_op:
        batch_op.drop_column("is_featured")
        batch_op.drop_column("city")
        batch_op.drop_column("seo_description")
        batch_op.drop_column("seo_title")
        batch_op.drop_column("shipping_policy")
        batch_op.drop_column("social_links")
        batch_op.drop_column("whatsapp")
        batch_op.drop_column("about")
        batch_op.drop_column("slogan")
        batch_op.drop_column("brand_color")
        batch_op.drop_column("banner_url")
        batch_op.drop_column("logo_url")
        batch_op.drop_column("published_at")
        batch_op.drop_column("is_published")

    for pid_str, _, _, _, _, _ in NEW_PERMISSIONS:
        op.execute(sa.text(f"DELETE FROM permissions WHERE id = '{pid_str}'"))
