"""add is_sso_user to users, composite index on email_verification_tokens

Revision ID: 2b5726fe701e
Revises: 0262b5e3d90e
Create Date: 2026-07-18 19:05:47.500807

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '2b5726fe701e'
down_revision: Union[str, None] = '0262b5e3d90e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('is_sso_user', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.create_index('ix_email_verification_tokens_user_id_created_at', 'email_verification_tokens', ['user_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_email_verification_tokens_user_id_created_at', table_name='email_verification_tokens')
    op.drop_column('users', 'is_sso_user')
