"""Cambios de prenda en plazo (CU-08).

Revision ID: 20261107_0025
Revises: 20261107_0024
"""
from collections.abc import Sequence
from datetime import datetime, timezone
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "20261107_0025"
down_revision: str | None = "20261107_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_PERMISSIONS = [
    (
        "20000000-0000-0000-0000-000000000037",
        "exchanges.read",
        "Consultar cambios de prendas",
        "Consultar cambios realizados y políticas de plazo de cambio",
        "exchanges",
        "tenant",
    ),
    (
        "20000000-0000-0000-0000-000000000038",
        "exchanges.write",
        "Realizar cambios de prendas",
        "Registrar cambios de prenda en plazo con recálculo de diferencia y movimientos de stock",
        "exchanges",
        "tenant",
    ),
]


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.now(timezone.utc)

    # 1. Agregar exchange_days a tenants si no existe
    with op.batch_alter_table("tenants") as batch:
        batch.add_column(
            sa.Column("exchange_days", sa.Integer(), nullable=False, server_default="15")
        )

    # 2. Crear tabla commerce_garment_exchanges
    op.create_table(
        "commerce_garment_exchanges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("branch_id", sa.Uuid(), nullable=False),
        sa.Column("original_order_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("customer_id", sa.Uuid(), nullable=True),
        sa.Column("difference_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("payment_method", sa.String(length=30), nullable=False),
        sa.Column("cash_received", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("cash_returned", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="COMPLETED"),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column("client_request_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["original_order_id"], ["commerce_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_request_id"),
    )
    op.create_index(
        "ix_commerce_garment_exchanges_tenant_id",
        "commerce_garment_exchanges",
        ["tenant_id"],
    )
    op.create_index(
        "ix_commerce_garment_exchanges_branch_id",
        "commerce_garment_exchanges",
        ["branch_id"],
    )
    op.create_index(
        "ix_commerce_garment_exchanges_original_order_id",
        "commerce_garment_exchanges",
        ["original_order_id"],
    )

    # 3. Crear tabla commerce_garment_exchange_lines
    op.create_table(
        "commerce_garment_exchange_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("exchange_id", sa.Uuid(), nullable=False),
        sa.Column("original_variant_id", sa.Uuid(), nullable=False),
        sa.Column("returned_quantity", sa.Integer(), nullable=False),
        sa.Column("original_unit_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("new_variant_id", sa.Uuid(), nullable=False),
        sa.Column("delivered_quantity", sa.Integer(), nullable=False),
        sa.Column("new_unit_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("price_difference", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["exchange_id"],
            ["commerce_garment_exchanges.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["new_variant_id"],
            ["product_variants.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["original_variant_id"],
            ["product_variants.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_commerce_garment_exchange_lines_exchange_id",
        "commerce_garment_exchange_lines",
        ["exchange_id"],
    )

    # 4. Insertar permisos
    permissions_table = sa.table(
        "permissions",
        sa.column("id", sa.Uuid()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("description", sa.String()),
        sa.column("module", sa.String()),
        sa.column("scope", sa.String()),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )

    for pid, code, name, desc, mod, scope in NEW_PERMISSIONS:
        bind.execute(
            permissions_table.insert().values(
                id=uuid.UUID(pid),
                code=code,
                name=name,
                description=desc,
                module=mod,
                scope=scope,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )

    # Asociar permisos al rol admin del sistema
    role_permissions = sa.table(
        "role_permissions",
        sa.column("role_id", sa.Uuid()),
        sa.column("permission_id", sa.Uuid()),
    )
    roles = sa.table(
        "roles",
        sa.column("id", sa.Uuid()),
        sa.column("code", sa.String()),
    )
    admin_roles = bind.execute(
        sa.select(roles.c.id).where(roles.c.code == "admin")
    ).fetchall()
    for (rid,) in admin_roles:
        for pid, *_ in NEW_PERMISSIONS:
            bind.execute(
                role_permissions.insert().values(
                    role_id=rid,
                    permission_id=uuid.UUID(pid),
                )
            )


    # Integración RS2: permisos vinculados al módulo que regula el acceso.
    bind = op.get_bind()
    if "module_permissions" in sa.inspect(bind).get_table_names():
        association = sa.table("module_permissions", sa.column("module_code", sa.String()), sa.column("permission_id", sa.Uuid()))
        permission = sa.table("permissions", sa.column("id", sa.Uuid()), sa.column("code", sa.String()))
        for permission_code in ['exchanges.read', 'exchanges.write']:
            permission_id = bind.scalar(sa.select(permission.c.id).where(permission.c.code == permission_code))
            if permission_id is not None:
                bind.execute(association.insert().values(module_code='exchanges', permission_id=permission_id))


def downgrade() -> None:
    bind = op.get_bind()

    # Revertir permisos
    perm_ids = [uuid.UUID(pid) for pid, *_ in NEW_PERMISSIONS]
    op.execute(
        sa.delete(sa.table("role_permissions", sa.column("permission_id", sa.Uuid())))
        .where(sa.column("permission_id").in_(perm_ids))
    )
    op.execute(
        sa.delete(sa.table("permissions", sa.column("id", sa.Uuid())))
        .where(sa.column("id").in_(perm_ids))
    )

    op.drop_table("commerce_garment_exchange_lines")
    op.drop_table("commerce_garment_exchanges")

    with op.batch_alter_table("tenants") as batch:
        batch.drop_column("exchange_days")
