"""add preferred_llm_provider to users

Nullable with no server default: NULL means "no preference", which the provider factory reads as
"fall back to the LLM_PROVIDER setting". Backfilling a literal 'openai' would instead pin every
existing user to OpenAI forever, so changing the server-wide provider later would silently do
nothing for them.

Revision ID: a3f1c9d47b2e
Revises: 6866f50785b9
Create Date: 2026-08-05 13:20:41.882314

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a3f1c9d47b2e'
down_revision: Union[str, None] = '6866f50785b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('preferred_llm_provider', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'preferred_llm_provider')
