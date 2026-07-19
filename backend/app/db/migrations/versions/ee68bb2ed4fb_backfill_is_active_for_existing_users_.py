"""backfill is_active for existing users, normalize existing emails

Revision ID: ee68bb2ed4fb
Revises: b38507f673d4
Create Date: 2026-07-19 16:40:46.111227

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ee68bb2ed4fb'
down_revision: Union[str, None] = 'b38507f673d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Every user existing at this point signed up before the email
    # verification flow existed, so there's no verification for them to have
    # completed -- grandfather them in as active. The column's server_default
    # stays false (set in 0262b5e3d90e), so this only affects rows already
    # present; it does not touch how future inserts default.
    conn.execute(sa.text("UPDATE users SET is_active = true"))

    # crud.normalize_email (lower + strip) now applies to every lookup and
    # new write, so an existing row with mixed-case email would otherwise
    # become unreachable. Refuse to proceed if normalizing would collide two
    # existing rows into the same email -- that's a data decision for a
    # human, not something to silently merge.
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
    # Data-only migration, no schema change to revert. Backfilling is_active
    # and normalizing email casing are one-way: some grandfathered users may
    # have genuinely verified since upgrade() ran, and original email casing
    # isn't retained anywhere, so there's no reliable prior state to restore.
    pass
