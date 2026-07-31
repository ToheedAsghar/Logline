"""merge remote_events/project_mappings and local_sessions heads

Revision ID: 57c86df30809
Revises: 06822e072ddf, ca7739816e69
Create Date: 2026-07-31 17:36:28.086456

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '57c86df30809'
down_revision: Union[str, None] = ('06822e072ddf', 'ca7739816e69')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
