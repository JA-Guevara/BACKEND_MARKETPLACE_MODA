"""Ventas, promociones y probador por empresa (commerce_orders, order_returns, promotions, tryon assets/jobs).

Revision ID: 20261105_0020
Revises: 20261105_0019
"""
from collections.abc import Sequence
from uuid import UUID

from alembic import op
import sqlalchemy as sa


revision: str = "20261105_0020"
down_revision: str | None = "20261105_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INITIAL_TENANT = UUID("30000000-0000-0000-0000-000000000001")


def upgrade() -> None:
    bind = op.get_bind()

    # 1. commerce_orders
    op.add_column("commerce_orders", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    bind.execute(sa.text("""
        UPDATE commerce_orders
        SET tenant_id = (SELECT b.tenant_id FROM branches b WHERE b.id = commerce_orders.branch_id)
        WHERE tenant_id IS NULL AND branch_id IS NOT NULL
    """))
    bind.execute(sa.text("UPDATE commerce_orders SET tenant_id = :tid WHERE tenant_id IS NULL"), {"tid": INITIAL_TENANT})
    with op.batch_alter_table("commerce_orders") as batch:
        batch.alter_column("tenant_id", existing_type=sa.Uuid(), nullable=False)
        batch.create_foreign_key("fk_commerce_orders_tenant_id_tenants", "tenants", ["tenant_id"], ["id"], ondelete="RESTRICT")
        batch.create_index("ix_commerce_orders_tenant_id", ["tenant_id"])

    # 2. commerce_order_returns
    op.add_column("commerce_order_returns", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    bind.execute(sa.text("""
        UPDATE commerce_order_returns
        SET tenant_id = (SELECT b.tenant_id FROM branches b WHERE b.id = commerce_order_returns.branch_id)
        WHERE tenant_id IS NULL AND branch_id IS NOT NULL
    """))
    bind.execute(sa.text("""
        UPDATE commerce_order_returns
        SET tenant_id = (SELECT o.tenant_id FROM commerce_orders o WHERE o.id = commerce_order_returns.order_id)
        WHERE tenant_id IS NULL AND order_id IS NOT NULL
    """))
    bind.execute(sa.text("UPDATE commerce_order_returns SET tenant_id = :tid WHERE tenant_id IS NULL"), {"tid": INITIAL_TENANT})
    with op.batch_alter_table("commerce_order_returns") as batch:
        batch.alter_column("tenant_id", existing_type=sa.Uuid(), nullable=False)
        batch.create_foreign_key("fk_commerce_order_returns_tenant_id_tenants", "tenants", ["tenant_id"], ["id"], ondelete="RESTRICT")
        batch.create_index("ix_commerce_order_returns_tenant_id", ["tenant_id"])

    # 3. commerce_promotions
    op.add_column("commerce_promotions", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    bind.execute(sa.text("""
        UPDATE commerce_promotions
        SET tenant_id = (SELECT p.tenant_id FROM products p WHERE p.id = commerce_promotions.product_id)
        WHERE tenant_id IS NULL AND product_id IS NOT NULL
    """))
    bind.execute(sa.text("""
        UPDATE commerce_promotions
        SET tenant_id = (SELECT c.tenant_id FROM categories c WHERE c.id = commerce_promotions.category_id)
        WHERE tenant_id IS NULL AND category_id IS NOT NULL
    """))
    bind.execute(sa.text("UPDATE commerce_promotions SET tenant_id = :tid WHERE tenant_id IS NULL"), {"tid": INITIAL_TENANT})
    with op.batch_alter_table("commerce_promotions") as batch:
        batch.alter_column("tenant_id", existing_type=sa.Uuid(), nullable=False)
        batch.create_foreign_key("fk_commerce_promotions_tenant_id_tenants", "tenants", ["tenant_id"], ["id"], ondelete="RESTRICT")
        batch.create_index("ix_commerce_promotions_tenant_id", ["tenant_id"])
        # Reemplazar unique global en code por unique compuesto (tenant_id, code)
        try:
            batch.drop_constraint("uq_commerce_promotions_code", type_="unique")
        except Exception:
            pass
        batch.create_unique_constraint("uq_commerce_promotions_tenant_code", ["tenant_id", "code"])

    # 4. virtual_tryon_assets
    op.add_column("virtual_tryon_assets", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    bind.execute(sa.text("""
        UPDATE virtual_tryon_assets
        SET tenant_id = (SELECT p.tenant_id FROM products p WHERE p.id = virtual_tryon_assets.product_id)
        WHERE tenant_id IS NULL AND product_id IS NOT NULL
    """))
    bind.execute(sa.text("UPDATE virtual_tryon_assets SET tenant_id = :tid WHERE tenant_id IS NULL"), {"tid": INITIAL_TENANT})
    with op.batch_alter_table("virtual_tryon_assets") as batch:
        batch.alter_column("tenant_id", existing_type=sa.Uuid(), nullable=False)
        batch.create_foreign_key("fk_virtual_tryon_assets_tenant_id_tenants", "tenants", ["tenant_id"], ["id"], ondelete="RESTRICT")
        batch.create_index("ix_virtual_tryon_assets_tenant_id", ["tenant_id"])

    # 5. tryon_ai_jobs
    op.add_column("tryon_ai_jobs", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    bind.execute(sa.text("""
        UPDATE tryon_ai_jobs
        SET tenant_id = (SELECT p.tenant_id FROM products p WHERE p.id = tryon_ai_jobs.product_id)
        WHERE tenant_id IS NULL AND product_id IS NOT NULL
    """))
    bind.execute(sa.text("""
        UPDATE tryon_ai_jobs
        SET tenant_id = (SELECT u.tenant_id FROM users u WHERE u.id = tryon_ai_jobs.user_id)
        WHERE tenant_id IS NULL AND user_id IS NOT NULL
    """))
    bind.execute(sa.text("UPDATE tryon_ai_jobs SET tenant_id = :tid WHERE tenant_id IS NULL"), {"tid": INITIAL_TENANT})
    with op.batch_alter_table("tryon_ai_jobs") as batch:
        batch.alter_column("tenant_id", existing_type=sa.Uuid(), nullable=False)
        batch.create_foreign_key("fk_tryon_ai_jobs_tenant_id_tenants", "tenants", ["tenant_id"], ["id"], ondelete="RESTRICT")
        batch.create_index("ix_tryon_ai_jobs_tenant_id", ["tenant_id"])


def downgrade() -> None:
    # 5. tryon_ai_jobs
    with op.batch_alter_table("tryon_ai_jobs") as batch:
        batch.drop_index("ix_tryon_ai_jobs_tenant_id")
        batch.drop_constraint("fk_tryon_ai_jobs_tenant_id_tenants", type_="foreignkey")
        batch.drop_column("tenant_id")

    # 4. virtual_tryon_assets
    with op.batch_alter_table("virtual_tryon_assets") as batch:
        batch.drop_index("ix_virtual_tryon_assets_tenant_id")
        batch.drop_constraint("fk_virtual_tryon_assets_tenant_id_tenants", type_="foreignkey")
        batch.drop_column("tenant_id")

    # 3. commerce_promotions
    with op.batch_alter_table("commerce_promotions") as batch:
        batch.drop_constraint("uq_commerce_promotions_tenant_code", type_="unique")
        batch.create_unique_constraint("uq_commerce_promotions_code", ["code"])
        batch.drop_index("ix_commerce_promotions_tenant_id")
        batch.drop_constraint("fk_commerce_promotions_tenant_id_tenants", type_="foreignkey")
        batch.drop_column("tenant_id")

    # 2. commerce_order_returns
    with op.batch_alter_table("commerce_order_returns") as batch:
        batch.drop_index("ix_commerce_order_returns_tenant_id")
        batch.drop_constraint("fk_commerce_order_returns_tenant_id_tenants", type_="foreignkey")
        batch.drop_column("tenant_id")

    # 1. commerce_orders
    with op.batch_alter_table("commerce_orders") as batch:
        batch.drop_index("ix_commerce_orders_tenant_id")
        batch.drop_constraint("fk_commerce_orders_tenant_id_tenants", type_="foreignkey")
        batch.drop_column("tenant_id")
