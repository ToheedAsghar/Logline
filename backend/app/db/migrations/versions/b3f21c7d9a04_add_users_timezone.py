"""add users.timezone

Stores the IANA timezone name used to decide which calendar day a work block belongs to. Nullable because existing
users have none yet; reconciliation rejects a request from a user without one rather than assuming UTC, which is
the misattribution this column exists to fix.

Revision ID: b3f21c7d9a04
Revises: ffd7483b9a45
Create Date: 2026-08-09 14:20:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b3f21c7d9a04'
down_revision: Union[str, None] = 'ffd7483b9a45'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('timezone', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'timezone')
