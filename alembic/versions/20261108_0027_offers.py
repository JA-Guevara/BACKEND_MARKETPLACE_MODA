"""Ofertas por empresa sobre commerce_promotions (CU-11).

Revision ID: 20261108_0027
Revises: 20261105_0021
"""
from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import UUID

from alembic import op
import sqlalchemy as sa


revision: str = "20261108_0027"
down_revision: str | None = "20261108_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_PERMISSIONS = [
    (
        "20000000-0000-0000-0000-000000000043",
        "promotions.read",
        "Consultar promociones y ofertas",
        "Ver promociones, descuentos y cupones de la empresa",
        "promotions",
        "tenant",
    ),
    (
        "20000000-0000-0000-0000-000000000044",
        "promotions.write",
        "Gestionar promociones y ofertas",
        "Crear, modificar, activar y desactivar promociones y ofertas",
        "promotions",
        "tenant",
    ),
]


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.now(timezone.utc)

    # 1. Agregar columnas a commerce_promotions
    with op.batch_alter_table("commerce_promotions") as batch:
        batch.add_column(sa.Column("applies_online", sa.Boolean(), server_default=sa.text("true"), nullable=False))
        batch.add_column(sa.Column("applies_pos", sa.Boolean(), server_default=sa.text("true"), nullable=False))
        batch.add_column(sa.Column("applies_offline", sa.Boolean(), server_default=sa.text("false"), nullable=False))
        batch.add_column(sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("deactivated_by", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("updated_by", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_commerce_promotions_deactivated_by_users", "users", ["deactivated_by"], ["id"], ondelete="SET NULL"
        )
        batch.create_foreign_key(
            "fk_commerce_promotions_updated_by_users", "users", ["updated_by"], ["id"], ondelete="SET NULL"
        )

    # 2. Tabla promotion_targets
    op.create_table(
        "promotion_targets",
        sa.Column("promotion_id", sa.Uuid(), nullable=False),
        sa.Column("target_type", sa.String(12), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("promotion_id", "target_type", "target_id"),
        sa.ForeignKeyConstraint(
            ["promotion_id"], ["commerce_promotions.id"], name="fk_promotion_targets_promotion_id", ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "target_type IN ('PRODUCT', 'VARIANT', 'CATEGORY', 'SEASON', 'COLLECTION', 'ALL')",
            name="ck_promotion_targets_type",
        ),
    )
    op.create_index("ix_promotion_targets_type_id", "promotion_targets", ["target_type", "target_id"])

    # 3. Copiar category_id / product_id existentes a promotion_targets
    try:
        bind.execute(sa.text("""
            INSERT INTO promotion_targets (promotion_id, target_type, target_id)
            SELECT id, 'CATEGORY', category_id
            FROM commerce_promotions
            WHERE category_id IS NOT NULL
        """))
        bind.execute(sa.text("""
            INSERT INTO promotion_targets (promotion_id, target_type, target_id)
            SELECT id, 'PRODUCT', product_id
            FROM commerce_promotions
            WHERE product_id IS NOT NULL
        """))
    except Exception:
        pass

    # 4. Columna channel en commerce_promotion_uses
    with op.batch_alter_table("commerce_promotion_uses") as batch:
        batch.add_column(sa.Column("channel", sa.String(10), server_default=sa.text("'ONLINE'"), nullable=False))

    # 5. Índices en commerce_promotions
    op.create_index(
        "ix_promotions_vigentes",
        "commerce_promotions",
        ["tenant_id", "is_active", "starts_at", "ends_at"],
    )

    # 6. Insertar permisos 43 y 44
    for pid_str, code, name, desc, module, scope in NEW_PERMISSIONS:
        pid = UUID(pid_str)
        bind.execute(
            sa.text("""
                INSERT INTO permissions (id, code, name, description, module, scope, is_active, created_at, updated_at)
                VALUES (:id, :code, :name, :desc, :module, :scope, :is_active, :now, :now)
            """),
            {
                "id": pid,
                "code": code,
                "name": name,
                "desc": desc,
                "module": module,
                "scope": scope,
                "is_active": True,
                "now": now,
            },
        )

    # 7. Asignar permisos a roles de tenant
    # admin, superadmin, store_manager -> 43, 44
    # cashier -> 43
    p43 = UUID("20000000-0000-0000-0000-000000000043")
    p44 = UUID("20000000-0000-0000-0000-000000000044")

    target_roles = bind.execute(sa.text("SELECT id, code FROM roles")).mappings().all()
    for r in target_roles:
        rcode = r.get("code") or ""
        rid = r["id"]
        # cashier recibe 43 (read)
        if rcode == "cashier":
            exists = bind.scalar(
                sa.text("SELECT 1 FROM role_permissions WHERE role_id = :rid AND permission_id = :pid"),
                {"rid": rid, "pid": p43},
            )
            if not exists:
                bind.execute(
                    sa.text("INSERT INTO role_permissions (role_id, permission_id) VALUES (:rid, :pid)"),
                    {"rid": rid, "pid": p43},
                )
        # admin, superadmin, store_manager reciben 43 y 44
        elif rcode in ("admin", "superadmin", "store_manager"):
            for pid in (p43, p44):
                exists = bind.scalar(
                    sa.text("SELECT 1 FROM role_permissions WHERE role_id = :rid AND permission_id = :pid"),
                    {"rid": rid, "pid": pid},
                )
                if not exists:
                    bind.execute(
                        sa.text("INSERT INTO role_permissions (role_id, permission_id) VALUES (:rid, :pid)"),
                        {"rid": rid, "pid": pid},
                    )


    # Integración RS2: permisos vinculados al módulo que regula el acceso.
    bind = op.get_bind()
    if "module_permissions" in sa.inspect(bind).get_table_names():
        association = sa.table("module_permissions", sa.column("module_code", sa.String()), sa.column("permission_id", sa.Uuid()))
        permission = sa.table("permissions", sa.column("id", sa.Uuid()), sa.column("code", sa.String()))
        for permission_code in ['promotions.read', 'promotions.write']:
            permission_id = bind.scalar(sa.select(permission.c.id).where(permission.c.code == permission_code))
            if permission_id is not None:
                bind.execute(association.insert().values(module_code='promotions', permission_id=permission_id))


def downgrade() -> None:
    p43 = UUID("20000000-0000-0000-0000-000000000043")
    p44 = UUID("20000000-0000-0000-0000-000000000044")
    bind = op.get_bind()

    bind.execute(
        sa.text("DELETE FROM role_permissions WHERE permission_id IN (:p1, :p2)"),
        {"p1": p43, "p2": p44},
    )
    bind.execute(
        sa.text("DELETE FROM permissions WHERE id IN (:p1, :p2)"),
        {"p1": p43, "p2": p44},
    )

    op.drop_index("ix_promotions_vigentes", table_name="commerce_promotions")

    with op.batch_alter_table("commerce_promotion_uses") as batch:
        batch.drop_column("channel")

    op.drop_table("promotion_targets")

    with op.batch_alter_table("commerce_promotions") as batch:
        batch.drop_column("updated_by")
        batch.drop_column("deactivated_by")
        batch.drop_column("deactivated_at")
        batch.drop_column("applies_offline")
        batch.drop_column("applies_pos")
        batch.drop_column("applies_online")
