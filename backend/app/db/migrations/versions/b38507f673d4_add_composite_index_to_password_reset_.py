"""add composite index to password_reset_tokens, bound users name length

Revision ID: b38507f673d4
Revises: 2b5726fe701e
Create Date: 2026-07-19 10:30:34.710969

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b38507f673d4'
down_revision: Union[str, None] = '2b5726fe701e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_password_reset_tokens_user_id_created_at', 'password_reset_tokens', ['user_id', 'created_at'], unique=False)
    op.alter_column('users', 'name', existing_type=sa.String(), type_=sa.String(length=100), existing_nullable=True)


def downgrade() -> None:
    op.alter_column('users', 'name', existing_type=sa.String(length=100), type_=sa.String(), existing_nullable=True)
    op.drop_index('ix_password_reset_tokens_user_id_created_at', table_name='password_reset_tokens')
