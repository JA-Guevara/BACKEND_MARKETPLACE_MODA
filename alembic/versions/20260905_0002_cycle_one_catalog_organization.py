"""Create Cycle I catalog, suppliers, branches and cash points."""

import uuid
from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260905_0002"
down_revision: str | None = "20260903_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PERMISSION_IDS = {
    "catalog.read": uuid.UUID("20000000-0000-0000-0000-000000000006"),
    "catalog.write": uuid.UUID("20000000-0000-0000-0000-000000000007"),
    "suppliers.read": uuid.UUID("20000000-0000-0000-0000-000000000008"),
    "suppliers.write": uuid.UUID("20000000-0000-0000-0000-000000000009"),
    "branches.read": uuid.UUID("20000000-0000-0000-0000-000000000010"),
    "branches.write": uuid.UUID("20000000-0000-0000-0000-000000000011"),
}
ADMIN_ROLE_IDS = (
    uuid.UUID("10000000-0000-0000-0000-000000000001"),
    uuid.UUID("10000000-0000-0000-0000-000000000002"),
)


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    op.create_table(
        "cities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("department", sa.String(100), nullable=False),
        sa.Column("country", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_cities"),
        sa.UniqueConstraint("country", "department", "name", name="uq_cities_country"),
    )
    op.create_index("ix_cities_name", "cities", ["name"])

    op.create_table(
        "suppliers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_name", sa.String(180), nullable=False),
        sa.Column("trade_name", sa.String(180)),
        sa.Column("tax_id", sa.String(50), nullable=False),
        sa.Column("contact_name", sa.String(150)),
        sa.Column("email", sa.String(320)),
        sa.Column("phone", sa.String(30)),
        sa.Column("address", sa.String(255)),
        sa.Column("city", sa.String(100)),
        sa.Column("notes", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        *timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_suppliers"),
        sa.UniqueConstraint("tax_id", name="uq_suppliers_tax_id"),
    )
    op.create_index("ix_suppliers_business_name", "suppliers", ["business_name"])
    op.create_index("ix_suppliers_tax_id", "suppliers", ["tax_id"])
    op.create_index("ix_suppliers_deleted_at", "suppliers", ["deleted_at"])

    op.create_table(
        "branches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("city_id", sa.Uuid(), nullable=False),
        sa.Column("address", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(30)),
        sa.Column("latitude", sa.Numeric(10, 7)),
        sa.Column("longitude", sa.Numeric(10, 7)),
        sa.Column("opening_hours", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        *timestamps(),
        sa.ForeignKeyConstraint(["city_id"], ["cities.id"], ondelete="RESTRICT", name="fk_branches_city_id_cities"),
        sa.PrimaryKeyConstraint("id", name="pk_branches"),
        sa.UniqueConstraint("code", name="uq_branches_code"),
        sa.UniqueConstraint("city_id", "name", name="uq_branches_city_id"),
    )
    for column in ("code", "name", "city_id", "deleted_at"):
        op.create_index(f"ix_branches_{column}", "branches", [column])

    op.create_table(
        "cash_points",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("branch_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        *timestamps(),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="RESTRICT", name="fk_cash_points_branch_id_branches"),
        sa.PrimaryKeyConstraint("id", name="pk_cash_points"),
        sa.UniqueConstraint("branch_id", "code", name="uq_cash_points_branch_id"),
    )
    op.create_index("ix_cash_points_branch_id", "cash_points", ["branch_id"])
    op.create_index("ix_cash_points_deleted_at", "cash_points", ["deleted_at"])

    op.create_table(
        "categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(140), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("parent_id", sa.Uuid()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamps(),
        sa.ForeignKeyConstraint(["parent_id"], ["categories.id"], ondelete="RESTRICT", name="fk_categories_parent_id_categories"),
        sa.PrimaryKeyConstraint("id", name="pk_categories"),
        sa.UniqueConstraint("slug", name="uq_categories_slug"),
    )
    for column in ("name", "slug", "parent_id"):
        op.create_index(f"ix_categories_{column}", "categories", [column])

    op.create_table(
        "sizes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_sizes"),
        sa.UniqueConstraint("code", name="uq_sizes_code"),
    )
    op.create_index("ix_sizes_code", "sizes", ["code"])

    op.create_table(
        "colors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("hex_code", sa.String(7), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_colors"),
        sa.UniqueConstraint("name", name="uq_colors_name"),
        sa.UniqueConstraint("hex_code", name="uq_colors_hex_code"),
    )
    op.create_index("ix_colors_name", "colors", ["name"])

    op.create_table(
        "seasons",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("start_date", sa.Date()),
        sa.Column("end_date", sa.Date()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_seasons"),
        sa.UniqueConstraint("name", name="uq_seasons_name"),
    )
    op.create_index("ix_seasons_name", "seasons", ["name"])

    op.create_table(
        "collections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("season_id", sa.Uuid()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamps(),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"], ondelete="RESTRICT", name="fk_collections_season_id_seasons"),
        sa.PrimaryKeyConstraint("id", name="pk_collections"),
        sa.UniqueConstraint("name", "season_id", name="uq_collections_name"),
    )
    op.create_index("ix_collections_name", "collections", ["name"])
    op.create_index("ix_collections_season_id", "collections", ["season_id"])

    op.create_table(
        "products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("brand", sa.String(100)),
        sa.Column("gender", sa.String(30)),
        sa.Column("base_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("season_id", sa.Uuid()),
        sa.Column("collection_id", sa.Uuid()),
        sa.Column("is_featured", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        *timestamps(),
        sa.CheckConstraint("base_price >= 0", name="ck_products_base_price_nonnegative"),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], ondelete="RESTRICT", name="fk_products_category_id_categories"),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"], ondelete="RESTRICT", name="fk_products_season_id_seasons"),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.id"], ondelete="RESTRICT", name="fk_products_collection_id_collections"),
        sa.PrimaryKeyConstraint("id", name="pk_products"),
        sa.UniqueConstraint("slug", name="uq_products_slug"),
    )
    for column in ("name", "slug", "brand", "gender", "category_id", "season_id", "collection_id", "is_featured", "is_active", "deleted_at"):
        op.create_index(f"ix_products_{column}", "products", [column])

    op.create_table(
        "product_variants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("size_id", sa.Uuid(), nullable=False),
        sa.Column("color_id", sa.Uuid(), nullable=False),
        sa.Column("sku", sa.String(80), nullable=False),
        sa.Column("barcode", sa.String(80)),
        sa.Column("price_override", sa.Numeric(12, 2)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamps(),
        sa.CheckConstraint("price_override IS NULL OR price_override >= 0", name="ck_product_variants_price_override_nonnegative"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE", name="fk_product_variants_product_id_products"),
        sa.ForeignKeyConstraint(["size_id"], ["sizes.id"], ondelete="RESTRICT", name="fk_product_variants_size_id_sizes"),
        sa.ForeignKeyConstraint(["color_id"], ["colors.id"], ondelete="RESTRICT", name="fk_product_variants_color_id_colors"),
        sa.PrimaryKeyConstraint("id", name="pk_product_variants"),
        sa.UniqueConstraint("product_id", "size_id", "color_id", name="uq_product_variants_product_id"),
        sa.UniqueConstraint("sku", name="uq_product_variants_sku"),
        sa.UniqueConstraint("barcode", name="uq_product_variants_barcode"),
    )
    for column in ("product_id", "size_id", "color_id", "sku", "barcode"):
        op.create_index(f"ix_product_variants_{column}", "product_variants", [column])

    op.create_table(
        "product_images",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.String(1000), nullable=False),
        sa.Column("alt_text", sa.String(255)),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        *timestamps(),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE", name="fk_product_images_product_id_products"),
        sa.PrimaryKeyConstraint("id", name="pk_product_images"),
    )
    op.create_index("ix_product_images_product_id", "product_images", ["product_id"])

    op.create_table(
        "ar_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("asset_type", sa.String(40), nullable=False),
        sa.Column("asset_url", sa.String(1000), nullable=False),
        sa.Column("preview_url", sa.String(1000)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamps(),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE", name="fk_ar_assets_product_id_products"),
        sa.PrimaryKeyConstraint("id", name="pk_ar_assets"),
    )
    op.create_index("ix_ar_assets_product_id", "ar_assets", ["product_id"])

    op.create_table(
        "product_suppliers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_sku", sa.String(100)),
        sa.Column("unit_cost", sa.Numeric(12, 2)),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        *timestamps(),
        sa.CheckConstraint("unit_cost IS NULL OR unit_cost >= 0", name="ck_product_suppliers_unit_cost_nonnegative"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE", name="fk_product_suppliers_product_id_products"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="RESTRICT", name="fk_product_suppliers_supplier_id_suppliers"),
        sa.PrimaryKeyConstraint("id", name="pk_product_suppliers"),
        sa.UniqueConstraint("product_id", "supplier_id", name="uq_product_suppliers_product_id"),
    )
    op.create_index("ix_product_suppliers_product_id", "product_suppliers", ["product_id"])
    op.create_index("ix_product_suppliers_supplier_id", "product_suppliers", ["supplier_id"])

    _seed_permissions()


def _seed_permissions() -> None:
    permissions = sa.table(
        "permissions",
        sa.column("id", sa.Uuid()), sa.column("code", sa.String()), sa.column("name", sa.String()),
        sa.column("description", sa.String()), sa.column("module", sa.String()), sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)), sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(timezone.utc)
    rows = [
        ("catalog.read", "Consultar catalogo", "Consultar productos y datos maestros.", "catalog"),
        ("catalog.write", "Gestionar catalogo", "Crear y modificar productos y datos maestros.", "catalog"),
        ("suppliers.read", "Consultar proveedores", "Consultar proveedores registrados.", "suppliers"),
        ("suppliers.write", "Gestionar proveedores", "Crear y modificar proveedores.", "suppliers"),
        ("branches.read", "Consultar sucursales", "Consultar ciudades, sucursales y cajas.", "branches"),
        ("branches.write", "Gestionar sucursales", "Crear y modificar ciudades, sucursales y cajas.", "branches"),
    ]
    op.bulk_insert(permissions, [
        {"id": PERMISSION_IDS[code], "code": code, "name": name, "description": description, "module": module, "is_active": True, "created_at": now, "updated_at": now}
        for code, name, description, module in rows
    ])
    role_permissions = sa.table("role_permissions", sa.column("role_id", sa.Uuid()), sa.column("permission_id", sa.Uuid()))
    op.bulk_insert(role_permissions, [
        {"role_id": role_id, "permission_id": permission_id}
        for role_id in ADMIN_ROLE_IDS for permission_id in PERMISSION_IDS.values()
    ])


def downgrade() -> None:
    role_permissions = sa.table("role_permissions", sa.column("permission_id", sa.Uuid()))
    permissions = sa.table("permissions", sa.column("id", sa.Uuid()))
    permission_ids = list(PERMISSION_IDS.values())
    op.execute(role_permissions.delete().where(role_permissions.c.permission_id.in_(permission_ids)))
    op.execute(permissions.delete().where(permissions.c.id.in_(permission_ids)))
    for table in ("product_suppliers", "ar_assets", "product_images", "product_variants", "products", "collections", "seasons", "colors", "sizes", "categories", "cash_points", "branches", "suppliers", "cities"):
        op.drop_table(table)
