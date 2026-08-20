"""add composite index on remote_events for keyset pagination

The single-column ix_remote_events_user_id is redundant once the composite index's leading column covers
the same lookup pattern. Dropping it avoids maintaining a duplicate index on every insert/update.

Revision ID: 16f64f48b32d
Revises: 808e7a2e4ee9
Create Date: 2026-08-20 14:07:45.110090

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "16f64f48b32d"
down_revision: Union[str, None] = "808e7a2e4ee9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_remote_events_user_id", table_name="remote_events")
    op.create_index(
        "ix_remote_events_user_id_occurred_at_id",
        "remote_events",
        [sa.text("user_id"), sa.text("occurred_at DESC"), sa.text("id DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_remote_events_user_id_occurred_at_id", table_name="remote_events")
    op.create_index("ix_remote_events_user_id", "remote_events", ["user_id"])
