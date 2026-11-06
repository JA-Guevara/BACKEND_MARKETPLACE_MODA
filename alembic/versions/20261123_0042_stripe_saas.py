"""Stripe SaaS: Billing de la plataforma y Connect por empresa (PS-PX O1.5).

- plans.stripe_price_id_month · tenants.stripe_customer_id · subscriptions.stripe_subscription_id
- tenant_payment_accounts: cuenta Express de cada empresa (solo id y estado, RN-ST1)
- stripe_events: idempotencia por id de evento (RN-ST4)
- permiso 065 billing.manage (tenant) para la plantilla Administrador de empresa;
  falla si el id está ocupado por otro código (nunca reasigna permisos)

Revision ID: 20261123_0042
Revises: 20261122_0041
"""
from collections.abc import Sequence
from datetime import datetime, timezone
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "20261123_0042"
down_revision: str | None = "20261122_0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PERMISSION = (
    "20000000-0000-0000-0000-000000000065",
    "billing.manage",
    "Pagar el plan con tarjeta",
    "Iniciar el pago del plan con Stripe y abrir el portal de facturación",
    "billing",
    "tenant",
)


def upgrade() -> None:
    bind = op.get_bind()
    now_utc = datetime.now(timezone.utc)

    with op.batch_alter_table("plans") as batch:
        batch.add_column(sa.Column("stripe_price_id_month", sa.String(length=100), nullable=True))
    with op.batch_alter_table("tenants") as batch:
        batch.add_column(sa.Column("stripe_customer_id", sa.String(length=255), nullable=True))
        batch.create_unique_constraint(op.f("uq_tenants_stripe_customer_id"), ["stripe_customer_id"])
    with op.batch_alter_table("subscriptions") as batch:
        batch.add_column(sa.Column("stripe_subscription_id", sa.String(length=255), nullable=True))
        batch.create_unique_constraint(op.f("uq_subscriptions_stripe_subscription_id"), ["stripe_subscription_id"])

    op.create_table(
        "tenant_payment_accounts",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("stripe_account_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("charges_enabled", sa.Boolean(), nullable=False),
        sa.Column("payouts_enabled", sa.Boolean(), nullable=False),
        sa.Column("details_submitted", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'active', 'restricted')", name=op.f("ck_tenant_payment_accounts_status")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_tenant_payment_accounts_tenant_id_tenants"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_tenant_payment_accounts")),
        sa.UniqueConstraint("stripe_account_id", name=op.f("uq_tenant_payment_accounts_stripe_account_id")),
    )
    op.create_table(
        "stripe_events",
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("source IN ('billing', 'connect')", name=op.f("ck_stripe_events_source")),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_stripe_events")),
    )

    perm_id, code, name, description, module_name, scope = PERMISSION
    perm_uuid = uuid.UUID(perm_id)
    real_perm_id = bind.execute(sa.text("SELECT id FROM permissions WHERE code = :code"), {"code": code}).scalar()
    if real_perm_id is None:
        occupied = bind.execute(sa.text("SELECT code FROM permissions WHERE id = :id"), {"id": perm_uuid}).scalar()
        if occupied is not None:
            raise RuntimeError(f"Conflicto de permisos: el id {perm_id} ya está ocupado por {occupied} al sembrar {code}.")
        bind.execute(
            sa.text(
                "INSERT INTO permissions (id, code, name, description, module, scope, is_active, created_at, updated_at) "
                "VALUES (:id, :code, :name, :description, :module, :scope, true, :now, :now)"
            ),
            {"id": perm_uuid, "code": code, "name": name, "description": description,
             "module": module_name, "scope": scope, "now": now_utc},
        )
        real_perm_id = perm_uuid

    admin_roles = bind.execute(sa.text(
        "SELECT id FROM roles WHERE code IN ('admin', 'company_admin') AND is_active = true AND tenant_id IS NULL"
    )).scalars().all()
    for role_id in admin_roles:
        assigned = bind.execute(
            sa.text("SELECT 1 FROM role_permissions WHERE role_id = :role_id AND permission_id = :perm_id"),
            {"role_id": role_id, "perm_id": real_perm_id},
        ).scalar()
        if not assigned:
            bind.execute(
                sa.text("INSERT INTO role_permissions (role_id, permission_id) VALUES (:role_id, :perm_id)"),
                {"role_id": role_id, "perm_id": real_perm_id},
            )


def downgrade() -> None:
    bind = op.get_bind()
    perm_uuid = uuid.UUID(PERMISSION[0])
    bind.execute(sa.text("DELETE FROM role_permissions WHERE permission_id = :id"), {"id": perm_uuid})
    bind.execute(sa.text("DELETE FROM permissions WHERE id = :id"), {"id": perm_uuid})

    op.drop_table("stripe_events")
    op.drop_table("tenant_payment_accounts")
    with op.batch_alter_table("subscriptions") as batch:
        batch.drop_constraint(op.f("uq_subscriptions_stripe_subscription_id"), type_="unique")
        batch.drop_column("stripe_subscription_id")
    with op.batch_alter_table("tenants") as batch:
        batch.drop_constraint(op.f("uq_tenants_stripe_customer_id"), type_="unique")
        batch.drop_column("stripe_customer_id")
    with op.batch_alter_table("plans") as batch:
        batch.drop_column("stripe_price_id_month")
