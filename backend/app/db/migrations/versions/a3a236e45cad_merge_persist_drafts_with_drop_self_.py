"""merge persist drafts with drop self captures

Revision ID: a3a236e45cad
Revises: 84f6dbe2a901, fa0c8c09a6d8
Create Date: 2026-08-18 12:16:07.535412

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3a236e45cad'
down_revision: Union[str, None] = ('84f6dbe2a901', 'fa0c8c09a6d8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
