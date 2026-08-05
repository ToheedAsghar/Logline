import os
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()


def _require_env(name: str) -> str:
    """Read a required env var, raising instead of silently defaulting to an empty string."""
    value = os.getenv(name, "")
    if not value:
        raise RuntimeError(f"Required environment variable {name!r} is not set")
    return value


class Settings:
    database_url: str = _require_env("DATABASE_URL")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    encryption_key: str = os.getenv("ENCRYPTION_KEY", "")

    llm_provider: str = os.getenv("LLM_PROVIDER", "openai")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-5-mini")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    jwt_secret_key: str = _require_env("JWT_SECRET_KEY")
    jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    jwt_expire_minutes: int = int(os.getenv("JWT_EXPIRE_MINUTES", str(60 * 24)))

    itsdangerous_secret_key: str = _require_env("ITSDANGEROUS_SECRET_KEY")

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

    google_client_id: str = _require_env("GOOGLE_CLIENT_ID")
    google_client_secret: str = _require_env("GOOGLE_CLIENT_SECRET")
    google_redirect_uri: str = _require_env("GOOGLE_REDIRECT_URI")

    jira_client_id: str = os.getenv("JIRA_CLIENT_ID", "")
    jira_client_secret: str = os.getenv("JIRA_CLIENT_SECRET", "")
    jira_redirect_uri: str = os.getenv("JIRA_REDIRECT_URI", "")

    frontend_base_url: str = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173")
    backend_base_url: str = os.getenv("BACKEND_BASE_URL", "http://localhost:8000")
    environment: str = os.getenv("ENVIRONMENT", "development")

    cors_origins: list[str] = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]


settings = Settings()

LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
ALLOW_INSECURE = os.getenv("ALLOW_INSECURE_BASE_URLS", "").strip().lower() in ("1", "true", "yes")


_SUPPORTED_LLM_PROVIDERS = frozenset({"openai", "gemini"})


def _require_supported_llm_provider(provider: str) -> None:
    """Fail at boot on an unknown LLM_PROVIDER rather than at first reconciliation call. Duplicates
    `SUPPORTED_PROVIDERS` from `app.agent.llm` as a literal snapshot instead of importing it -- that module imports
    `settings` from here, so importing back would cycle.
    """
    if provider.lower() not in _SUPPORTED_LLM_PROVIDERS:
        raise RuntimeError(
            f"LLM_PROVIDER must be one of {sorted(_SUPPORTED_LLM_PROVIDERS)} (got {provider!r})"
        )


def _require_secure_url(name: str, url: str) -> None:
    """Fail closed: only https, loopback http, or an explicit opt-out (ALLOW_INSECURE_BASE_URLS=true) is accepted."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise RuntimeError(f"{name} must be an absolute http(s) URL (got {url!r})")
    if parsed.scheme == "https":
        return
    if parsed.hostname in LOOPBACK_HOSTS:
        return
    if ALLOW_INSECURE:
        return
    raise RuntimeError(
        f"{name} must use https:// (got {url!r}). "
        f"Set ALLOW_INSECURE_BASE_URLS=true only for non-production, non-loopback setups."
    )


_require_secure_url("BACKEND_BASE_URL", settings.backend_base_url)
_require_secure_url("FRONTEND_BASE_URL", settings.frontend_base_url)
_require_supported_llm_provider(settings.llm_provider)
