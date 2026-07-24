from sqlalchemy.dialects import postgresql


def integration_source_enum(create_type: bool = False) -> postgresql.ENUM:
    """Column type for the shared `integration_source` Postgres enum.

    The type itself is owned by migration 5eea9c691db5 (first created for the
    `integrations` table) -- any other table's migration that adds a column of
    this type must pass create_type=False so it references the existing type
    instead of trying to create a duplicate.

    The value list here is a frozen snapshot, not an import of the live
    IntegrationSource enum in app code -- migration files must stay
    self-contained so they don't drift if the app enum changes later. Adding a
    new source means a separate `ALTER TYPE integration_source ADD VALUE ...`
    migration, not just an app-code enum change.
    """
    return postgresql.ENUM(
        "github", "slack", "jira", "calendar", name="integration_source", create_type=create_type
    )
