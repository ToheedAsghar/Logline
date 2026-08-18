"""drop self_captures, events, and confidence_level enum

Revision ID: fa0c8c09a6d8
Revises: ffd7483b9a45
Create Date: 2026-08-17 11:32:47.103586

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'fa0c8c09a6d8'
down_revision: Union[str, None] = 'ffd7483b9a45'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # self_captures holds the FK to events, so it must drop first.
    op.drop_index(op.f('ix_self_captures_user_id'), table_name='self_captures')
    op.drop_table('self_captures')

    op.drop_index(op.f('ix_events_user_id'), table_name='events')
    op.drop_table('events')

    # Only drop the enum after both tables that reference it are gone.
    sa.Enum(name='confidence_level').drop(op.get_bind(), checkfirst=False)


def downgrade() -> None:
    confidence_level = postgresql.ENUM('proven', 'estimated', 'gap', name='confidence_level')
    confidence_level.create(op.get_bind(), checkfirst=False)

    op.create_table(
        'events',
        sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column('source', sa.VARCHAR(), autoincrement=False, nullable=False),
        sa.Column('type', sa.VARCHAR(), autoincrement=False, nullable=False),
        sa.Column('timestamp', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=False),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=True),
        sa.Column(
            'confidence',
            postgresql.ENUM('proven', 'estimated', 'gap', name='confidence_level', create_type=False),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            'created_at',
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text('now()'),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column('external_id', sa.VARCHAR(), autoincrement=False, nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('events_user_id_fkey')),
        sa.PrimaryKeyConstraint('id', name=op.f('events_pkey')),
        sa.UniqueConstraint(
            'user_id', 'source', 'type', 'external_id', name='uq_events_user_source_type_external_id'
        ),
    )
    op.create_index(op.f('ix_events_user_id'), 'events', ['user_id'], unique=False)

    op.create_table(
        'self_captures',
        sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column('text', sa.TEXT(), autoincrement=False, nullable=False),
        sa.Column('timestamp', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=False),
        sa.Column('linked_gap_id', sa.INTEGER(), autoincrement=False, nullable=True),
        sa.Column(
            'created_at',
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text('now()'),
            autoincrement=False,
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['linked_gap_id'], ['events.id'], name=op.f('self_captures_linked_gap_id_fkey')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('self_captures_user_id_fkey')),
        sa.PrimaryKeyConstraint('id', name=op.f('self_captures_pkey')),
    )
    op.create_index(op.f('ix_self_captures_user_id'), 'self_captures', ['user_id'], unique=False)
