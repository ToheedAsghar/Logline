import os

from dotenv import load_dotenv

load_dotenv()


def _require_env(name: str) -> str:
    """Read a required env var, raising instead of silently defaulting to "".

    Some settings (e.g. SMTP credentials) are unsafe to fall back to an
    empty string for -- a misconfigured deploy should fail loudly at
    startup, not send mail with a blank host or crash later with an opaque
    error the first time the feature is used.
    """
    value = os.getenv(name, "")
    if not value:
        raise RuntimeError(f"Required environment variable {name!r} is not set")
    return value


class Settings:
    database_url: str = os.getenv("DATABASE_URL", "")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    encryption_key: str = os.getenv("ENCRYPTION_KEY", "")

    llm_provider: str = os.getenv("LLM_PROVIDER", "openai")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-5-mini")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")

    jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", "")
    jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    jwt_expire_minutes: int = int(os.getenv("JWT_EXPIRE_MINUTES", str(60 * 24)))

    itsdangerous_secret_key: str = os.getenv("ITSDANGEROUS_SECRET_KEY", "")

    smtp_host: str = _require_env("SMTP_HOST")
    smtp_port: int = int(_require_env("SMTP_PORT"))
    smtp_username: str = _require_env("SMTP_USERNAME")
    smtp_password: str = _require_env("SMTP_PASSWORD")
    smtp_from_address: str = _require_env("SMTP_FROM_ADDRESS")

    github_client_id: str = os.getenv("GITHUB_CLIENT_ID", "")
    github_client_secret: str = os.getenv("GITHUB_CLIENT_SECRET", "")
    github_redirect_uri: str = os.getenv("GITHUB_REDIRECT_URI", "")

    slack_client_id: str = os.getenv("SLACK_CLIENT_ID", "")
    slack_client_secret: str = os.getenv("SLACK_CLIENT_SECRET", "")
    slack_signing_secret: str = os.getenv("SLACK_SIGNING_SECRET", "")
    slack_redirect_uri: str = os.getenv("SLACK_REDIRECT_URI", "")
    slack_bot_token: str = os.getenv("SLACK_BOT_TOKEN", "")

    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    google_redirect_uri: str = os.getenv("GOOGLE_REDIRECT_URI", "")

    jira_client_id: str = os.getenv("JIRA_CLIENT_ID", "")
    jira_client_secret: str = os.getenv("JIRA_CLIENT_SECRET", "")
    jira_redirect_uri: str = os.getenv("JIRA_REDIRECT_URI", "")

    frontend_base_url: str = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173")

    cors_origins: list[str] = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]


settings = Settings()
