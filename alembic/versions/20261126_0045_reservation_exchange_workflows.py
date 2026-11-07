"""Reservation-to-order linkage and confirmed exchange settlements."""
from alembic import op
import sqlalchemy as sa

revision = '20261126_0045'
down_revision = '20261125_0044'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('commerce_garment_exchanges', sa.Column('request_fingerprint', sa.String(64)))
    op.add_column('reservations', sa.Column('order_id', sa.Uuid(), nullable=True))
    op.create_foreign_key('fk_reservations_order_id_commerce_orders', 'reservations', 'commerce_orders', ['order_id'], ['id'], ondelete='RESTRICT')
    op.create_unique_constraint('uq_reservations_order_id', 'reservations', ['order_id'])
    for column in [
        sa.Column('difference_amount', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('settlement_status', sa.String(30), nullable=False, server_default='not_required'),
        sa.Column('settlement_method', sa.String(30)), sa.Column('settlement_reference', sa.String(255)),
        sa.Column('settlement_attempt', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('stripe_account_id', sa.String(255)), sa.Column('stripe_session_id', sa.String(255)),
        sa.Column('stripe_url', sa.String(2000)),
    ]:
        op.add_column('commerce_order_returns', column)
    op.create_unique_constraint('uq_commerce_order_returns_stripe_session_id', 'commerce_order_returns', ['stripe_session_id'])


def downgrade():
    op.drop_column('commerce_garment_exchanges', 'request_fingerprint')
    op.drop_constraint('uq_commerce_order_returns_stripe_session_id', 'commerce_order_returns', type_='unique')
    for name in ['stripe_url', 'stripe_session_id', 'stripe_account_id', 'settlement_attempt', 'settlement_reference', 'settlement_method', 'settlement_status', 'difference_amount']:
        op.drop_column('commerce_order_returns', name)
    op.drop_constraint('uq_reservations_order_id', 'reservations', type_='unique')
    op.drop_constraint('fk_reservations_order_id_commerce_orders', 'reservations', type_='foreignkey')
    op.drop_column('reservations', 'order_id')
