"""add password reset and email verification support

Revision ID: 6aff4d503b81
Revises: 2e875f27d1e3
Create Date: 2026-07-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '6aff4d503b81'
down_revision: Union[str, None] = '2e875f27d1e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'email_verification_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_email_verification_tokens_user_id'), 'email_verification_tokens', ['user_id'], unique=False
    )
    op.create_index(
        'ix_email_verification_tokens_user_id_created_at',
        'email_verification_tokens',
        ['user_id', 'created_at'],
        unique=False,
    )

    op.create_table(
        'password_reset_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_password_reset_tokens_user_id'), 'password_reset_tokens', ['user_id'], unique=False
    )
    op.create_index(
        'ix_password_reset_tokens_user_id_created_at', 'password_reset_tokens', ['user_id', 'created_at'], unique=False
    )

    op.add_column('users', sa.Column('is_active', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('users', sa.Column('is_sso_user', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.alter_column('users', 'name', existing_type=sa.String(), type_=sa.String(length=100), existing_nullable=True)

    backfill_is_active_and_normalize_email(op.get_bind())


def backfill_is_active_and_normalize_email(conn) -> None:
    """Grandfather existing users in as active and normalize their email
    casing. Split out from upgrade() so it can be exercised on its own
    against an already-migrated schema (see
    tests/test_backfill_is_active_and_normalize_email_migration.py) without
    re-running the create_table/add_column calls above.
    """
    conn.execute(sa.text("UPDATE users SET is_active = true"))

    collisions = conn.execute(
        sa.text(
            "SELECT lower(trim(email)) AS normalized, array_agg(id ORDER BY id) AS ids "
            "FROM users GROUP BY lower(trim(email)) HAVING count(*) > 1"
        )
    ).fetchall()
    if collisions:
        details = ", ".join(f"{row.normalized} (ids {row.ids})" for row in collisions)
        raise RuntimeError(
            f"Email normalization would collide for existing users: {details}. "
            "Resolve manually before re-running this migration."
        )

    conn.execute(sa.text("UPDATE users SET email = lower(trim(email))"))


def downgrade() -> None:
    op.alter_column('users', 'name', existing_type=sa.String(length=100), type_=sa.String(), existing_nullable=True)
    op.drop_column('users', 'is_sso_user')
    op.drop_column('users', 'is_active')

    op.drop_index('ix_password_reset_tokens_user_id_created_at', table_name='password_reset_tokens')
    op.drop_index(op.f('ix_password_reset_tokens_user_id'), table_name='password_reset_tokens')
    op.drop_table('password_reset_tokens')

    op.drop_index('ix_email_verification_tokens_user_id_created_at', table_name='email_verification_tokens')
    op.drop_index(op.f('ix_email_verification_tokens_user_id'), table_name='email_verification_tokens')
    op.drop_table('email_verification_tokens')
