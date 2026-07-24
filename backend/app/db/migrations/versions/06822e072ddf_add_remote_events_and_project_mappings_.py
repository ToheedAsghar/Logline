"""add remote_events and project_mappings tables

Revision ID: 06822e072ddf
Revises: 2e875f27d1e3
Create Date: 2026-07-24 12:29:12.343933

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '06822e072ddf'
down_revision: Union[str, None] = '2e875f27d1e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Reuse the existing `integration_source` enum type (created by
    # migration 5eea9c691db5, an ancestor of this one) -- create_type=False
    # so this migration references it instead of trying to create it again.
    integration_source_enum = postgresql.ENUM(
        'github', 'slack', 'jira', 'calendar', name='integration_source', create_type=False
    )

    op.create_table(
        'project_mappings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('local_project', sa.String(), nullable=False),
        sa.Column('source', integration_source_enum, nullable=False),
        sa.Column('remote_project_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'user_id', 'local_project', 'source', name='uq_project_mappings_user_local_project_source'
        ),
    )
    op.create_index(op.f('ix_project_mappings_user_id'), 'project_mappings', ['user_id'], unique=False)

    op.create_table(
        'remote_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('source', integration_source_enum, nullable=False),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('external_id', sa.String(), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('summary', sa.String(), nullable=True),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('match_keys', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('raw_data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('remote_project_id', sa.String(), nullable=True),
        sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'user_id', 'source', 'external_id', name='uq_remote_events_user_source_external_id'
        ),
    )
    op.create_index(op.f('ix_remote_events_user_id'), 'remote_events', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_remote_events_user_id'), table_name='remote_events')
    op.drop_table('remote_events')
    op.drop_index(op.f('ix_project_mappings_user_id'), table_name='project_mappings')
    op.drop_table('project_mappings')
