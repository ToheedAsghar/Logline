"""persist reconciliation drafts

Revision ID: 84f6dbe2a901
Revises: b3f21c7d9a04
Create Date: 2026-08-10 22:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "84f6dbe2a901"
down_revision: Union[str, None] = "b3f21c7d9a04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE entry_status ADD VALUE IF NOT EXISTS 'discarded'")
    draft_state_owner = postgresql.ENUM(
        "active", "superseded", "approved", "discarded", name="reconciliation_draft_state"
    )
    draft_state_owner.create(op.get_bind(), checkfirst=True)
    op.execute("ALTER TYPE reconciliation_draft_state ADD VALUE IF NOT EXISTS 'discarded'")
    draft_state = postgresql.ENUM(
        "active", "superseded", "approved", "discarded", name="reconciliation_draft_state", create_type=False
    )
    op.create_table(
        "reconciliation_drafts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("date_range_start", sa.Date(), nullable=False),
        sa.Column("date_range_end", sa.Date(), nullable=False),
        sa.Column("state", draft_state, nullable=False),
        sa.Column("draft", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("verification", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("supersedes_id", sa.Integer(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("date_range_start <= date_range_end", name="ck_reconciliation_drafts_date_range"),
        sa.ForeignKeyConstraint(["supersedes_id"], ["reconciliation_drafts.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reconciliation_drafts_user_id", "reconciliation_drafts", ["user_id"])
    op.create_index(
        "ix_reconciliation_drafts_scope",
        "reconciliation_drafts",
        ["user_id", "date_range_start", "date_range_end", "state"],
    )
    op.add_column("entries", sa.Column("reconciliation_draft_id", sa.Integer(), nullable=True))
    op.add_column("entries", sa.Column("draft_position", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_entries_reconciliation_draft_id",
        "entries",
        "reconciliation_drafts",
        ["reconciliation_draft_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_entries_reconciliation_draft_id", "entries", ["reconciliation_draft_id"])


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM entries WHERE status = 'discarded') THEN
                RAISE EXCEPTION
                    'Cannot downgrade while discarded reconciliation entries exist; archive or remove them explicitly';
            END IF;
        END
        $$
        """
    )
    op.drop_index("ix_entries_reconciliation_draft_id", table_name="entries")
    op.drop_constraint("fk_entries_reconciliation_draft_id", "entries", type_="foreignkey")
    op.drop_column("entries", "draft_position")
    op.drop_column("entries", "reconciliation_draft_id")
    op.drop_index("ix_reconciliation_drafts_scope", table_name="reconciliation_drafts")
    op.drop_index("ix_reconciliation_drafts_user_id", table_name="reconciliation_drafts")
    op.drop_table("reconciliation_drafts")
    postgresql.ENUM(name="reconciliation_draft_state").drop(op.get_bind(), checkfirst=True)
    op.execute("CREATE TYPE entry_status_without_discarded AS ENUM ('draft', 'pending', 'approved')")
    op.execute(
        "ALTER TABLE entries ALTER COLUMN status TYPE entry_status_without_discarded "
        "USING status::text::entry_status_without_discarded"
    )
    op.execute("DROP TYPE entry_status")
    op.execute("ALTER TYPE entry_status_without_discarded RENAME TO entry_status")
