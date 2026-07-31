"""merge work_date and password reset/google-sso branches

Revision ID: 4bb30b3d3a02
Revises: c44e99f2a0b1, ccefa75771fd
Create Date: 2026-07-31 14:44:59.427694

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4bb30b3d3a02'
down_revision: Union[str, None] = ('c44e99f2a0b1', 'ccefa75771fd')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
