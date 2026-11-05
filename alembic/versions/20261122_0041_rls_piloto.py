"""RLS piloto en 3 tablas (products, commerce_orders, reservations)

Revision ID: 20261122_0041
Revises: 20261120_0040
Create Date: 2026-11-22 00:41:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = '20261122_0041'
down_revision: Union[str, None] = '20261120_0040'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PILOT_TABLES = ['products', 'commerce_orders', 'reservations']


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return

    # ENABLE ROW LEVEL SECURITY + CREATE POLICY
    for table in PILOT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table};")
        op.execute(f"""
            CREATE POLICY tenant_isolation_{table} ON {table}
            AS PERMISSIVE
            FOR ALL
            USING (
                (NULLIF(current_setting('app.tenant_id', true), '')::uuid IS NOT NULL 
                 AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
                OR current_setting('app.platform', true) = '1'
            )
            WITH CHECK (
                (NULLIF(current_setting('app.tenant_id', true), '')::uuid IS NOT NULL 
                 AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
                OR current_setting('app.platform', true) = '1'
            );
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return

    for table in PILOT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
