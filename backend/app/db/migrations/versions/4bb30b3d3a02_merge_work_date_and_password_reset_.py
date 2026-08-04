"""merge work_date and password reset/google-sso branches

Originally a merge migration, but its intended reconciliation was already resolved by
c7e52807067a before this file landed via PR #20. Retained (not deleted) as a no-op stacked
revision, repointed to a valid single parent, solely to preserve the ID for any database
that may already have it stamped.

Revision ID: 4bb30b3d3a02
Revises: ccefa75771fd
Create Date: 2026-07-31 14:44:59.427694

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4bb30b3d3a02'
down_revision: Union[str, None] = 'ccefa75771fd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
