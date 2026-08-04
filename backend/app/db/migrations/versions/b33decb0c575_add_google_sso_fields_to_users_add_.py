"""add google sso fields to users, add oauth_states table

Revision ID: b33decb0c575
Revises: 6036065262b5
Create Date: 2026-07-19 23:15:21.367360

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b33decb0c575'
down_revision: Union[str, None] = '6036065262b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'oauth_states',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('jti', sa.String(), nullable=False),
        sa.Column('purpose', sa.String(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_oauth_states_jti'), 'oauth_states', ['jti'], unique=True)
    op.create_index('ix_oauth_states_expires_at', 'oauth_states', ['expires_at'], unique=False)
    op.add_column('users', sa.Column('google_user_id', sa.String(), nullable=True))
    op.alter_column(
        'users',
        'hashed_password',
        existing_type=sa.VARCHAR(),
        nullable=True,
    )
    op.create_unique_constraint('uq_users_google_user_id', 'users', ['google_user_id'])


def downgrade() -> None:
    op.drop_constraint('uq_users_google_user_id', 'users', type_='unique')
    op.alter_column(
        'users',
        'hashed_password',
        existing_type=sa.VARCHAR(),
        nullable=False,
    )
    op.drop_column('users', 'google_user_id')
    op.drop_index(op.f('ix_oauth_states_jti'), table_name='oauth_states')
    op.drop_index('ix_oauth_states_expires_at', table_name='oauth_states')
    op.drop_table('oauth_states')
