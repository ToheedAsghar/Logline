"""add tracker device token_hash and revocation

Replaces the reversibly-encrypted `tracker_devices.token` with a SHA-256 `token_hash`, and adds `revoked_at`.

`token_hash` is nullable so devices enrolled under the old scheme keep their rows, and with them the
`tracker_sync_states` checkpoints a cascade delete would have destroyed. Those rows cannot authenticate and must
re-enroll. The downgrade cannot repopulate `token`, since plaintext is unrecoverable from a hash.

Revision ID: ffd7483b9a45
Revises: 2a505d284d5c
Create Date: 2026-08-06 15:00:13.084379

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import app.db.encrypted_types

# revision identifiers, used by Alembic.
revision: str = 'ffd7483b9a45'
down_revision: Union[str, None] = '2a505d284d5c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tracker_devices', sa.Column('token_hash', sa.String(length=64), nullable=True))
    op.add_column('tracker_devices', sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f('ix_tracker_devices_token_hash'), 'tracker_devices', ['token_hash'], unique=True)
    op.drop_column('tracker_devices', 'token')


def downgrade() -> None:
    op.add_column(
        'tracker_devices',
        sa.Column('token', app.db.encrypted_types.EncryptedString(), nullable=True),
    )
    op.drop_index(op.f('ix_tracker_devices_token_hash'), table_name='tracker_devices')
    op.drop_column('tracker_devices', 'revoked_at')
    op.drop_column('tracker_devices', 'token_hash')
