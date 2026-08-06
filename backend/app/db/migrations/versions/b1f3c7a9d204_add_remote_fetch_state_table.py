"""add remote_fetch_state table

Revision ID: b1f3c7a9d204
Revises: 6866f50785b9
Create Date: 2026-07-26 21:58:41.112905

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b1f3c7a9d204'
down_revision: Union[str, None] = '6866f50785b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Same reuse as 06822e072ddf: the `integration_source` enum type already
    # exists (created by 5eea9c691db5), so create_type=False references it
    # rather than failing on a duplicate CREATE TYPE.
    integration_source_enum = postgresql.ENUM(
        'github', 'slack', 'jira', 'calendar', name='integration_source', create_type=False
    )

    op.create_table(
        'remote_fetch_state',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('source', integration_source_enum, nullable=False),
        sa.Column('last_fetched_through', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_attempted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'source', name='uq_remote_fetch_state_user_source'),
    )
    op.create_index(op.f('ix_remote_fetch_state_user_id'), 'remote_fetch_state', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_remote_fetch_state_user_id'), table_name='remote_fetch_state')
    op.drop_table('remote_fetch_state')
