"""add oauth_tokens.authed_user_id

Stores the connected account's own user ID at the provider, which the Slack connect flow already parses but
previously discarded before it reached the database. Nullable because only Slack supplies one -- GitHub, Jira, and
Calendar tokens leave it NULL.

Revision ID: 808e7a2e4ee9
Revises: a3a236e45cad
Create Date: 2026-08-18 13:50:23.394104

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '808e7a2e4ee9'
down_revision: Union[str, None] = 'a3a236e45cad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('oauth_tokens', sa.Column('authed_user_id', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('oauth_tokens', 'authed_user_id')
