"""merge auth/connect-link-token track with entries/tracker track

Revision ID: c7e52807067a
Revises: 3ac407252b4a, 57c86df30809
Create Date: 2026-07-31 17:36:42.773608

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7e52807067a'
down_revision: Union[str, None] = ('3ac407252b4a', '57c86df30809')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
