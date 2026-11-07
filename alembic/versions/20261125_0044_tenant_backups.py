"""Cola, políticas y archivos cifrados de copias de negocio por empresa."""
from alembic import op
import sqlalchemy as sa

revision='20261125_0044'
down_revision='20261124_0043'
branch_labels=None
depends_on=None


def timestamps():
    return [sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
            sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False)]


def upgrade():
    op.create_table('tenant_backup_policies',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('tenant_id',sa.Uuid(),sa.ForeignKey('tenants.id',ondelete='CASCADE'),nullable=False),
        sa.Column('enabled',sa.Boolean(),nullable=False),sa.Column('frequency',sa.String(10),nullable=False),
        sa.Column('hour',sa.Integer(),nullable=False),sa.Column('timezone',sa.String(80),nullable=False),
        sa.Column('retention',sa.Integer(),nullable=False),sa.Column('next_run_at',sa.DateTime(timezone=True)),
        *timestamps(),sa.UniqueConstraint('tenant_id',name='uq_tenant_backup_policies_tenant'))
    op.create_index('ix_tenant_backup_policies_tenant_id','tenant_backup_policies',['tenant_id'])
    op.create_index('ix_tenant_backup_policies_next_run_at','tenant_backup_policies',['next_run_at'])
    op.create_table('tenant_backup_runs',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('tenant_id',sa.Uuid(),sa.ForeignKey('tenants.id',ondelete='CASCADE'),nullable=False),
        sa.Column('requested_by',sa.Uuid(),sa.ForeignKey('users.id',ondelete='SET NULL')),
        sa.Column('request_key',sa.String(80),nullable=False),sa.Column('kind',sa.String(10),nullable=False),
        sa.Column('status',sa.String(20),nullable=False),sa.Column('started_at',sa.DateTime(timezone=True)),
        sa.Column('finished_at',sa.DateTime(timezone=True)),sa.Column('lease_until',sa.DateTime(timezone=True)),
        sa.Column('lease_token',sa.String(36)),sa.Column('sha256',sa.String(64)),
        sa.Column('size_bytes',sa.Integer(),nullable=False),sa.Column('report',sa.JSON()),
        sa.Column('error',sa.String(300)),sa.Column('artifact',sa.LargeBinary()),*timestamps(),
        sa.UniqueConstraint('tenant_id','request_key',name='uq_tenant_backup_runs_request'))
    op.create_index('ix_tenant_backup_runs_tenant_id','tenant_backup_runs',['tenant_id'])
    op.create_index('ix_tenant_backup_runs_status_created','tenant_backup_runs',['status','created_at'])
    if op.get_bind().dialect.name=='postgresql':
        for name in ('tenant_backup_policies','tenant_backup_runs'):
            op.execute(f'ALTER TABLE {name} ENABLE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE {name} NO FORCE ROW LEVEL SECURITY')
            expression="tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid OR current_setting('app.platform',true) = '1'"
            op.execute(f'CREATE POLICY tenant_isolation_{name} ON {name} USING ({expression}) WITH CHECK ({expression})')
        op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='fashionstore_app') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_backup_policies, tenant_backup_runs TO fashionstore_app;
            END IF; END $$""")


def downgrade():
    op.drop_table('tenant_backup_runs')
    op.drop_table('tenant_backup_policies')
