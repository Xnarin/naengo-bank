"""Bind schedule registrations to a request ID."""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("auto_transfers", sa.Column("registration_fingerprint", sa.String(64), nullable=True))


def downgrade():
    op.drop_column("auto_transfers", "registration_fingerprint")
