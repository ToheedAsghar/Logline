"""add work_date to entries

Revision ID: ccefa75771fd
Revises: ca7739816e69
Create Date: 2026-07-22 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ccefa75771fd'
down_revision: Union[str, None] = '2e875f27d1e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable first so existing rows can be backfilled, then tightened to NOT NULL --
    # a straight NOT NULL add_column would fail against any existing entries.
    op.add_column('entries', sa.Column('work_date', sa.Date(), nullable=True))
    # Best-effort backfill for pre-existing rows: created_at's date is the closest
    # approximation available for data written before work_date existed. New rows are
    # written with a real, explicit work_date going forward (see
    # app/agent/tools/write_draft_entry.py).
    op.execute("UPDATE entries SET work_date = created_at::date WHERE work_date IS NULL")
    op.alter_column('entries', 'work_date', nullable=False)


def downgrade() -> None:
    op.drop_column('entries', 'work_date')
