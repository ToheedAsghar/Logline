"""Add tracker device and sync state schemas and rich context to local sessions

Revision ID: d77b8f9a3c20
Revises: ca7739816e69, 06822e072ddf
Create Date: 2026-07-30 05:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

import app.db.encrypted_types

# revision identifiers, used by Alembic.
revision: str = 'd77b8f9a3c20'
down_revision: Union[str, Sequence[str], None] = ('ca7739816e69', '06822e072ddf')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add new columns to local_sessions
    op.add_column('local_sessions', sa.Column('project_path', sa.String(), nullable=True))
    op.add_column('local_sessions', sa.Column('context_detail', sa.String(), nullable=True))

    # 2. Create tracker_devices table
    op.create_table('tracker_devices',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('device_id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('token', app.db.encrypted_types.EncryptedString(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tracker_devices_device_id'), 'tracker_devices', ['device_id'], unique=True)
    op.create_index(op.f('ix_tracker_devices_user_id'), 'tracker_devices', ['user_id'], unique=False)

    # 3. Create tracker_sync_states table
    op.create_table('tracker_sync_states',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('device_id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['device_id'], ['tracker_devices.device_id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('user_id', 'device_id')
    )


def downgrade() -> None:
    op.drop_table('tracker_sync_states')
    op.drop_index(op.f('ix_tracker_devices_user_id'), table_name='tracker_devices')
    op.drop_index(op.f('ix_tracker_devices_device_id'), table_name='tracker_devices')
    op.drop_table('tracker_devices')
    op.drop_column('local_sessions', 'context_detail')
    op.drop_column('local_sessions', 'project_path')
