"""drop unused work_blocks table

Revision ID: 6036065262b5
Revises: ee68bb2ed4fb
Create Date: 2026-07-19 22:40:42.102837

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '6036065262b5'
down_revision: Union[str, None] = 'ee68bb2ed4fb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index(op.f('ix_work_blocks_user_id'), table_name='work_blocks')
    op.drop_table('work_blocks')


def downgrade() -> None:
    op.create_table('work_blocks',
    sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('start_time', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=False),
    sa.Column('end_time', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=False),
    sa.Column('confidence', postgresql.ENUM('proven', 'estimated', 'gap', name='confidence_level', create_type=False), autoincrement=False, nullable=False),
    sa.Column('summary', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('work_blocks_user_id_fkey')),
    sa.PrimaryKeyConstraint('id', name=op.f('work_blocks_pkey'))
    )
    op.create_index(op.f('ix_work_blocks_user_id'), 'work_blocks', ['user_id'], unique=False)
