"""add connect_link_tokens table

Revision ID: 3ac407252b4a
Revises: b33decb0c575
Create Date: 2026-07-23 19:31:15.359096

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.db.pg_enums import integration_source_enum

# revision identifiers, used by Alembic.
revision: str = '3ac407252b4a'
down_revision: Union[str, None] = 'b33decb0c575'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'connect_link_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('source', integration_source_enum(create_type=False), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_connect_link_tokens_user_id'), 'connect_link_tokens', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_connect_link_tokens_user_id'), table_name='connect_link_tokens')
    op.drop_table('connect_link_tokens')
