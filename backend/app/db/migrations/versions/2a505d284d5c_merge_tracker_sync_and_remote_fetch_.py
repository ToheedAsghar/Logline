"""merge tracker_sync and remote_fetch heads

No schema change -- this exists only to reconcile the two divergent heads `main` carried
(`4bb30b3d3a02` from the entries/password-reset line and `b1f3c7a9d204` from remote_fetch),
which left `alembic upgrade head` ambiguous and blocked any new migration from applying.

Revision ID: 2a505d284d5c
Revises: 4bb30b3d3a02, b1f3c7a9d204
Create Date: 2026-08-06 15:00:02.919109

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = '2a505d284d5c'
down_revision: Union[str, None] = ('4bb30b3d3a02', 'b1f3c7a9d204')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
