"""Alta autoservicio con prueba de 14 dias y aceptacion legal (PX-1.3).

Revision ID: 20261115_0038
Revises: 20261115_0037
"""
from collections.abc import Sequence
from datetime import datetime, timezone
import hashlib

from alembic import op
import sqlalchemy as sa


revision: str = "20261115_0038"
down_revision: str | None = "20261115_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(bind, table_name: str) -> bool:
    insp = sa.inspect(bind)
    return table_name in insp.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    now_utc = datetime.now(timezone.utc)

    # 1. legal_documents
    if not _table_exists(bind, "legal_documents"):
        op.create_table(
            "legal_documents",
            sa.Column("code", sa.String(50), nullable=False),
            sa.Column("version", sa.String(50), nullable=False),
            sa.Column("content_sha256", sa.String(64), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("code", "version", name="pk_legal_documents"),
        )

        # Sembrar documentos iniciales (términos y privacidad versión 1.0.0)
        terms_sha = hashlib.sha256("TERMINOS_Y_CONDICIONES_FASHIONSTORE_V1".encode("utf-8")).hexdigest()
        privacy_sha = hashlib.sha256("POLITICA_DE_PRIVACIDAD_FASHIONSTORE_V1".encode("utf-8")).hexdigest()

        legal_docs_table = sa.table(
            "legal_documents",
            sa.column("code", sa.String),
            sa.column("version", sa.String),
            sa.column("content_sha256", sa.String),
            sa.column("published_at", sa.DateTime(timezone=True)),
        )
        op.bulk_insert(
            legal_docs_table,
            [
                {
                    "code": "terms",
                    "version": "1.0.0",
                    "content_sha256": terms_sha,
                    "published_at": now_utc,
                },
                {
                    "code": "privacy",
                    "version": "1.0.0",
                    "content_sha256": privacy_sha,
                    "published_at": now_utc,
                },
            ],
        )

    # 2. legal_acceptances
    if not _table_exists(bind, "legal_acceptances"):
        op.create_table(
            "legal_acceptances",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("document_code", sa.String(50), nullable=False),
            sa.Column("version", sa.String(50), nullable=False),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ip_hash", sa.String(64), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_legal_acceptances"),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                name="fk_legal_acceptances_user_id_users",
                ondelete="CASCADE",
            ),
        )
        op.create_index(
            "ix_legal_acceptances_user_id",
            "legal_acceptances",
            ["user_id"],
        )

    # 3. tenant_signups
    if not _table_exists(bind, "tenant_signups"):
        op.create_table(
            "tenant_signups",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("email", sa.String(255), nullable=False),
            sa.Column("company_name", sa.String(255), nullable=False),
            sa.Column("slug", sa.String(100), nullable=False),
            sa.Column("password_hash", sa.String(255), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.PrimaryKeyConstraint("id", name="pk_tenant_signups"),
            sa.ForeignKeyConstraint(
                ["tenant_id"],
                ["tenants.id"],
                name="fk_tenant_signups_tenant_id_tenants",
                ondelete="SET NULL",
            ),
        )
        op.create_index("ix_tenant_signups_email", "tenant_signups", ["email"])
        op.create_index("ix_tenant_signups_slug", "tenant_signups", ["slug"])
        op.create_index("ix_tenant_signups_token_hash", "tenant_signups", ["token_hash"])


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "tenant_signups"):
        op.drop_index("ix_tenant_signups_token_hash", table_name="tenant_signups")
        op.drop_index("ix_tenant_signups_slug", table_name="tenant_signups")
        op.drop_index("ix_tenant_signups_email", table_name="tenant_signups")
        op.drop_table("tenant_signups")

    if _table_exists(bind, "legal_acceptances"):
        op.drop_index("ix_legal_acceptances_user_id", table_name="legal_acceptances")
        op.drop_table("legal_acceptances")

    if _table_exists(bind, "legal_documents"):
        op.drop_table("legal_documents")
