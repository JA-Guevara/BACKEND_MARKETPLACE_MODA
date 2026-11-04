"""Diccionarios del catalogo por empresa (categorias, tallas, colores, temporadas, colecciones, proveedores).

Revision ID: 20261105_0019
Revises: 20261029_0018
"""
from collections.abc import Sequence
from uuid import UUID, uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "20261105_0019"
down_revision: str | None = "20261029_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INITIAL_TENANT = UUID("30000000-0000-0000-0000-000000000001")
TABLES = ("categories", "sizes", "colors", "seasons", "collections", "suppliers")


def _get_tenant_mappings(bind, table: str) -> dict[UUID, list[UUID]]:
    """Devuelve un dict {item_id: [tenant_id_1, tenant_id_2, ...]} segun las prendas que lo usan."""
    if table == "categories":
        query = sa.text("SELECT DISTINCT category_id AS item_id, tenant_id FROM products WHERE category_id IS NOT NULL AND tenant_id IS NOT NULL")
    elif table == "seasons":
        query = sa.text("SELECT DISTINCT season_id AS item_id, tenant_id FROM products WHERE season_id IS NOT NULL AND tenant_id IS NOT NULL")
    elif table == "collections":
        query = sa.text("SELECT DISTINCT collection_id AS item_id, tenant_id FROM products WHERE collection_id IS NOT NULL AND tenant_id IS NOT NULL")
    elif table == "sizes":
        query = sa.text("""
            SELECT DISTINCT pv.size_id AS item_id, p.tenant_id
            FROM product_variants pv
            JOIN products p ON pv.product_id = p.id
            WHERE pv.size_id IS NOT NULL AND p.tenant_id IS NOT NULL
        """)
    elif table == "colors":
        query = sa.text("""
            SELECT DISTINCT pv.color_id AS item_id, p.tenant_id
            FROM product_variants pv
            JOIN products p ON pv.product_id = p.id
            WHERE pv.color_id IS NOT NULL AND p.tenant_id IS NOT NULL
        """)
    elif table == "suppliers":
        query = sa.text("""
            SELECT DISTINCT ps.supplier_id AS item_id, p.tenant_id
            FROM product_suppliers ps
            JOIN products p ON ps.product_id = p.id
            WHERE ps.supplier_id IS NOT NULL AND p.tenant_id IS NOT NULL
        """)
    else:
        return {}

    rows = bind.execute(query).fetchall()
    mapping: dict[UUID, list[UUID]] = {}
    for item_id, tenant_id in rows:
        item_uuid = UUID(str(item_id))
        tenant_uuid = UUID(str(tenant_id))
        if item_uuid not in mapping:
            mapping[item_uuid] = []
        if tenant_uuid not in mapping[item_uuid]:
            mapping[item_uuid].append(tenant_uuid)
    return mapping


def _repoint_tenant_references(bind, table: str, old_id: UUID, new_id: UUID, tenant_id: UUID) -> None:
    """Reapunta las referencias de productos/variantes de ese tenant al nuevo duplicado."""
    if table == "categories":
        bind.execute(
            sa.text("UPDATE products SET category_id = :new_id WHERE category_id = :old_id AND tenant_id = :tenant_id"),
            {"new_id": new_id, "old_id": old_id, "tenant_id": tenant_id},
        )
    elif table == "seasons":
        bind.execute(
            sa.text("UPDATE products SET season_id = :new_id WHERE season_id = :old_id AND tenant_id = :tenant_id"),
            {"new_id": new_id, "old_id": old_id, "tenant_id": tenant_id},
        )
    elif table == "collections":
        bind.execute(
            sa.text("UPDATE products SET collection_id = :new_id WHERE collection_id = :old_id AND tenant_id = :tenant_id"),
            {"new_id": new_id, "old_id": old_id, "tenant_id": tenant_id},
        )
    elif table == "sizes":
        bind.execute(
            sa.text("""
                UPDATE product_variants
                SET size_id = :new_id
                WHERE size_id = :old_id
                  AND product_id IN (SELECT id FROM products WHERE tenant_id = :tenant_id)
            """),
            {"new_id": new_id, "old_id": old_id, "tenant_id": tenant_id},
        )
    elif table == "colors":
        bind.execute(
            sa.text("""
                UPDATE product_variants
                SET color_id = :new_id
                WHERE color_id = :old_id
                  AND product_id IN (SELECT id FROM products WHERE tenant_id = :tenant_id)
            """),
            {"new_id": new_id, "old_id": old_id, "tenant_id": tenant_id},
        )
    elif table == "suppliers":
        bind.execute(
            sa.text("""
                UPDATE product_suppliers
                SET supplier_id = :new_id
                WHERE supplier_id = :old_id
                  AND product_id IN (SELECT id FROM products WHERE tenant_id = :tenant_id)
            """),
            {"new_id": new_id, "old_id": old_id, "tenant_id": tenant_id},
        )


def _repoint_all_references(bind, table: str, copy_id: UUID, original_id: UUID) -> None:
    """En downgrade, reapunta todas las referencias del duplicado a la fila original."""
    if table == "categories":
        bind.execute(
            sa.text("UPDATE products SET category_id = :orig_id WHERE category_id = :copy_id"),
            {"orig_id": original_id, "copy_id": copy_id},
        )
    elif table == "seasons":
        bind.execute(
            sa.text("UPDATE products SET season_id = :orig_id WHERE season_id = :copy_id"),
            {"orig_id": original_id, "copy_id": copy_id},
        )
    elif table == "collections":
        bind.execute(
            sa.text("UPDATE products SET collection_id = :orig_id WHERE collection_id = :copy_id"),
            {"orig_id": original_id, "copy_id": copy_id},
        )
    elif table == "sizes":
        bind.execute(
            sa.text("UPDATE product_variants SET size_id = :orig_id WHERE size_id = :copy_id"),
            {"orig_id": original_id, "copy_id": copy_id},
        )
    elif table == "colors":
        bind.execute(
            sa.text("UPDATE product_variants SET color_id = :orig_id WHERE color_id = :copy_id"),
            {"orig_id": original_id, "copy_id": copy_id},
        )
    elif table == "suppliers":
        bind.execute(
            sa.text("UPDATE product_suppliers SET supplier_id = :orig_id WHERE supplier_id = :copy_id"),
            {"orig_id": original_id, "copy_id": copy_id},
        )


def upgrade() -> None:
    bind = op.get_bind()

    # Tabla auxiliar para rastrear duplicados en caso de downgrade
    op.create_table(
        "_rs_catalog_copies",
        sa.Column("table_name", sa.String(50), nullable=False),
        sa.Column("copy_id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column("original_id", sa.Uuid(), nullable=False),
    )

    # Paso 1: Agregar columna tenant_id nullable en cada tabla
    for table in TABLES:
        op.add_column(table, sa.Column("tenant_id", sa.Uuid(), nullable=True))

    # Paso 1.5: Eliminar restricciones de unicidad globales antes de duplicar
    def _safe_drop(b, name):
        try:
            b.drop_constraint(name, type_="unique")
        except Exception:
            pass

    with op.batch_alter_table("categories") as batch:
        _safe_drop(batch, "uq_categories_slug")
    with op.batch_alter_table("sizes") as batch:
        _safe_drop(batch, "uq_sizes_code")
    with op.batch_alter_table("colors") as batch:
        _safe_drop(batch, "uq_colors_name")
        _safe_drop(batch, "uq_colors_hex_code")
    with op.batch_alter_table("seasons") as batch:
        _safe_drop(batch, "uq_seasons_name")
    with op.batch_alter_table("collections") as batch:
        _safe_drop(batch, "uq_collections_name")
    with op.batch_alter_table("suppliers") as batch:
        _safe_drop(batch, "uq_suppliers_tax_id")

    # Pasos 2 y 3: Asignar duenios y duplicar compartidas
    for table in TABLES:
        mappings = _get_tenant_mappings(bind, table)
        all_rows = bind.execute(sa.text(f"SELECT * FROM {table}")).mappings().all()

        for row in all_rows:
            row_id = UUID(str(row["id"]))
            using_tenants = mappings.get(row_id, [])

            if not using_tenants:
                # Ninguna prenda la usa: toma la empresa inicial
                bind.execute(
                    sa.text(f"UPDATE {table} SET tenant_id = :tid WHERE id = :id"),
                    {"tid": INITIAL_TENANT, "id": row_id},
                )
            else:
                # El primer tenant conserva la fila original
                first_tenant = using_tenants[0]
                bind.execute(
                    sa.text(f"UPDATE {table} SET tenant_id = :tid WHERE id = :id"),
                    {"tid": first_tenant, "id": row_id},
                )

                # Tenants adicionales (2+): crear duplicado y reapuntar
                for additional_tenant in using_tenants[1:]:
                    new_id = uuid4()
                    new_row = dict(row)
                    new_row["id"] = new_id
                    new_row["tenant_id"] = additional_tenant

                    # Construir INSERT dinamico con las columnas existentes
                    cols = list(new_row.keys())
                    col_names = ", ".join(cols)
                    val_placeholders = ", ".join(f":{c}" for c in cols)
                    insert_stmt = sa.text(f"INSERT INTO {table} ({col_names}) VALUES ({val_placeholders})")
                    bind.execute(insert_stmt, new_row)

                    # Registrar duplicado
                    bind.execute(
                        sa.text("INSERT INTO _rs_catalog_copies (table_name, copy_id, original_id) VALUES (:t, :c, :o)"),
                        {"t": table, "c": new_id, "o": row_id},
                    )

                    # Reapuntar referencias
                    _repoint_tenant_references(bind, table, row_id, new_id, additional_tenant)

        # Respaldo: asegurar que ninguna fila quede con tenant_id nulo
        bind.execute(
            sa.text(f"UPDATE {table} SET tenant_id = :tid WHERE tenant_id IS NULL"),
            {"tid": INITIAL_TENANT},
        )

    # Paso 4: batch_alter_table NOT NULL, FK e indice
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.alter_column("tenant_id", existing_type=sa.Uuid(), nullable=False)
            batch.create_foreign_key(
                f"fk_{table}_tenant_id_tenants",
                "tenants",
                ["tenant_id"],
                ["id"],
                ondelete="RESTRICT",
            )
            batch.create_index(f"ix_{table}_tenant_id", ["tenant_id"])

    # Paso 5: Unicidad por empresa
    with op.batch_alter_table("categories") as batch:
        batch.create_unique_constraint("uq_categories_tenant_slug", ["tenant_id", "slug"])

    with op.batch_alter_table("sizes") as batch:
        batch.create_unique_constraint("uq_sizes_tenant_code", ["tenant_id", "code"])

    with op.batch_alter_table("colors") as batch:
        batch.create_unique_constraint("uq_colors_tenant_name", ["tenant_id", "name"])
        batch.create_unique_constraint("uq_colors_tenant_hex_code", ["tenant_id", "hex_code"])

    with op.batch_alter_table("seasons") as batch:
        batch.create_unique_constraint("uq_seasons_tenant_name", ["tenant_id", "name"])

    with op.batch_alter_table("collections") as batch:
        batch.create_unique_constraint("uq_collections_tenant_name", ["tenant_id", "name", "season_id"])

    with op.batch_alter_table("suppliers") as batch:
        batch.create_unique_constraint("uq_suppliers_tenant_tax_id", ["tenant_id", "tax_id"])


def downgrade() -> None:
    bind = op.get_bind()

    # Revertir referencias de copias a original y borrar copias
    copies = bind.execute(sa.text("SELECT table_name, copy_id, original_id FROM _rs_catalog_copies")).fetchall()
    for table_name, copy_id, original_id in copies:
        _repoint_all_references(bind, table_name, UUID(str(copy_id)), UUID(str(original_id)))
        bind.execute(sa.text(f"DELETE FROM {table_name} WHERE id = :cid"), {"cid": copy_id})

    op.drop_table("_rs_catalog_copies")

    # Revertir Unicidad por empresa a global
    def _safe_drop_down(b, name):
        try:
            b.drop_constraint(name, type_="unique")
        except Exception:
            pass

    with op.batch_alter_table("suppliers") as batch:
        _safe_drop_down(batch, "uq_suppliers_tenant_tax_id")
        batch.create_unique_constraint("uq_suppliers_tax_id", ["tax_id"])

    with op.batch_alter_table("collections") as batch:
        _safe_drop_down(batch, "uq_collections_tenant_name")
        batch.create_unique_constraint("uq_collections_name", ["name", "season_id"])

    with op.batch_alter_table("seasons") as batch:
        _safe_drop_down(batch, "uq_seasons_tenant_name")
        batch.create_unique_constraint("uq_seasons_name", ["name"])

    with op.batch_alter_table("colors") as batch:
        _safe_drop_down(batch, "uq_colors_tenant_hex_code")
        _safe_drop_down(batch, "uq_colors_tenant_name")
        batch.create_unique_constraint("uq_colors_hex_code", ["hex_code"])
        batch.create_unique_constraint("uq_colors_name", ["name"])

    with op.batch_alter_table("sizes") as batch:
        _safe_drop_down(batch, "uq_sizes_tenant_code")
        batch.create_unique_constraint("uq_sizes_code", ["code"])

    with op.batch_alter_table("categories") as batch:
        _safe_drop_down(batch, "uq_categories_tenant_slug")
        batch.create_unique_constraint("uq_categories_slug", ["slug"])

    # Eliminar indices, FK y columnas tenant_id
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f"ix_{table}_tenant_id")
            batch.drop_constraint(f"fk_{table}_tenant_id_tenants", type_="foreignkey")
            batch.drop_column("tenant_id")
