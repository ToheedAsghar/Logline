"""merge entry_versions and tracker_sync heads

Revision ID: 6866f50785b9
Revises: 283e0bebe749, d77b8f9a3c20
Create Date: 2026-08-04 10:56:10.052496

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '6866f50785b9'
down_revision: Union[str, None] = ('283e0bebe749', 'd77b8f9a3c20')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
