"""Cimientos SaaS y migración de los datos existentes a FashionStore."""
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4
from alembic import op
import sqlalchemy as sa

revision = "20261024_0016"
down_revision = "20260920_0015"
branch_labels = None
depends_on = None
TENANT = UUID("30000000-0000-0000-0000-000000000001")
BASIC = UUID("40000000-0000-0000-0000-000000000001")
PRO = UUID("40000000-0000-0000-0000-000000000002")


def stamps():
    return [sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False)]


def upgrade():
    op.create_table("tenants", sa.Column("id", sa.Uuid(), primary_key=True), *stamps(),
        sa.Column("legal_name", sa.String(200), nullable=False), sa.Column("trade_name", sa.String(150), nullable=False),
        sa.Column("tax_id", sa.String(30), nullable=False, unique=True), sa.Column("slug", sa.String(60), nullable=False, unique=True),
        sa.Column("contact_email", sa.String(255), nullable=False), sa.Column("phone", sa.String(30)),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("deactivation_reason", sa.Text()))
    op.create_table("plans", sa.Column("id", sa.Uuid(), primary_key=True), *stamps(),
        sa.Column("code", sa.String(30), nullable=False, unique=True), sa.Column("name", sa.String(80), nullable=False),
        sa.Column("reference_price", sa.Numeric(10, 2), nullable=False), sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False))
    op.create_table("plan_features", sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("plan_id", sa.Uuid(), sa.ForeignKey("plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("feature_code", sa.String(40), nullable=False), sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("limit_value", sa.Integer()), sa.UniqueConstraint("plan_id", "feature_code"))
    op.create_table("subscriptions", sa.Column("id", sa.Uuid(), primary_key=True), *stamps(),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("plan_id", sa.Uuid(), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False), sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("reason", sa.Text()),
        sa.Column("changed_by", sa.Uuid(), sa.ForeignKey("users.id")), sa.Column("closed_at", sa.DateTime(timezone=True)))
    op.create_index("ix_subscriptions_tenant_id", "subscriptions", ["tenant_id"])
    op.create_index("uq_subscriptions_tenant_open", "subscriptions", ["tenant_id"], unique=True,
                    postgresql_where=sa.text("closed_at IS NULL"), sqlite_where=sa.text("closed_at IS NULL"))
    now = datetime.now(timezone.utc)
    bind = op.get_bind()
    def insert(table, values):
        fields = {key: sa.Uuid() if isinstance(value, UUID) else sa.DateTime(timezone=True) if isinstance(value, datetime)
                  else sa.Date() if isinstance(value, date) else sa.Boolean() if isinstance(value, bool)
                  else sa.Integer() if isinstance(value, int) else sa.String() for key, value in values.items()}
        op.bulk_insert(sa.table(table, *[sa.column(k, v) for k, v in fields.items()]), [values])
    insert("tenants", dict(id=TENANT, legal_name="FashionStore", trade_name="FashionStore", tax_id="0000000001", slug="fashionstore", contact_email="contacto@fashionstore.local", status="ACTIVA", created_at=now, updated_at=now))
    for pid, code, name, price, limit in [(BASIC, "BASICO", "Básico", 350, 2), (PRO, "PROFESIONAL", "Profesional", 890, 10)]:
        insert("plans", dict(id=pid, code=code, name=name, reference_price=price, duration_days=30, is_active=True, created_at=now, updated_at=now))
        for code in ("products", "sales", "reservations", "offline", "conventional_reports", "ai_reports", "ml_analytics", "max_active_branches"):
            insert("plan_features", dict(id=uuid4(), plan_id=pid, feature_code=code, enabled=pid == PRO or code not in ("ai_reports", "ml_analytics"), limit_value=limit if code == "max_active_branches" else None))
    for table in ("users", "branches", "cash_points", "products", "reservations"):
        op.add_column(table, sa.Column("tenant_id", sa.Uuid(), nullable=True))
        target = sa.table(table, sa.column("tenant_id", sa.Uuid()))
        bind.execute(target.update().values(tenant_id=TENANT))
        with op.batch_alter_table(table) as batch:
            batch.create_foreign_key(f"fk_{table}_tenant_id_tenants", "tenants", ["tenant_id"], ["id"])
            if table != "users": batch.alter_column("tenant_id", existing_type=sa.Uuid(), nullable=False)
            batch.create_index(f"ix_{table}_tenant_id", ["tenant_id"])
    for table, column in (("branches", "code"), ("products", "slug")):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"uq_{table}_{column}", type_="unique")
            batch.create_unique_constraint(f"uq_{table}_tenant_id", ["tenant_id", column])
    with op.batch_alter_table("branches") as batch:
        batch.drop_constraint("uq_branches_city_id", type_="unique")
        batch.create_unique_constraint("uq_branches_tenant_city_name", ["tenant_id", "city_id", "name"])
    role = UUID("10000000-0000-0000-0000-000000000006")
    insert("roles", dict(id=role, code="platform_admin", name="Administrador de plataforma", description="Gestiona empresas, planes y suscripciones.", is_system=True, is_active=True, created_at=now, updated_at=now))
    for num, code in enumerate(("tenants.read", "tenants.write", "plans.read", "plans.write", "subscriptions.read", "subscriptions.write", "my_subscription.read"), 19):
        pid = UUID(f"20000000-0000-0000-0000-{num:012d}")
        insert("permissions", dict(id=pid, code=code, name=code, description=code, module="platform", is_active=True, created_at=now, updated_at=now))
        for rid in ([role] if num < 25 else [UUID("10000000-0000-0000-0000-000000000001"), UUID("10000000-0000-0000-0000-000000000002")]):
            insert("role_permissions", dict(role_id=rid, permission_id=pid))
    insert("subscriptions", dict(id=uuid4(), tenant_id=TENANT, plan_id=PRO, start_date=now.date(), end_date=now.date()+timedelta(days=365), status="ACTIVA", created_at=now, updated_at=now))


def downgrade():
    bind = op.get_bind()
    permission_ids = [UUID(f"20000000-0000-0000-0000-{n:012d}") for n in range(19, 26)]
    rp = sa.table("role_permissions", sa.column("permission_id", sa.Uuid()))
    bind.execute(rp.delete().where(rp.c.permission_id.in_(permission_ids)))
    ur = sa.table("user_roles", sa.column("role_id", sa.Uuid()))
    rid = UUID("10000000-0000-0000-0000-000000000006")
    bind.execute(ur.delete().where(ur.c.role_id == rid))
    for table, ids in (("permissions", permission_ids), ("roles", [rid])):
        target = sa.table(table, sa.column("id", sa.Uuid()))
        bind.execute(target.delete().where(target.c.id.in_(ids)))
    op.drop_table("subscriptions")
    for table in ("reservations", "products", "cash_points", "branches", "users"):
        with op.batch_alter_table(table) as batch:
            if table in ("products", "branches"):
                col = "slug" if table == "products" else "code"
                batch.drop_constraint(f"uq_{table}_tenant_id", type_="unique")
                batch.create_unique_constraint(f"uq_{table}_{col}", [col])
            if table == "branches":
                batch.drop_constraint("uq_branches_tenant_city_name", type_="unique")
                batch.create_unique_constraint("uq_branches_city_id", ["city_id", "name"])
            batch.drop_index(f"ix_{table}_tenant_id")
            batch.drop_constraint(f"fk_{table}_tenant_id_tenants", type_="foreignkey")
            batch.drop_column("tenant_id")
    op.drop_table("plan_features")
    op.drop_table("plans")
    op.drop_table("tenants")
