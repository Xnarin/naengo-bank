"""Prevent duplicate card charges while preserving historical payments."""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("card_payments", sa.Column("idempotency_key", sa.String(64), nullable=True))
    op.add_column("card_payments", sa.Column("overseas", sa.Boolean(), nullable=True))
    op.create_unique_constraint("uq_card_payment_request", "card_payments", ["card_id", "idempotency_key"])


def downgrade():
    op.drop_constraint("uq_card_payment_request", "card_payments", type_="unique")
    op.drop_column("card_payments", "overseas")
    op.drop_column("card_payments", "idempotency_key")
