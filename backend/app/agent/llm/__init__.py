"""Factory for the configured LLMProvider.

Nothing outside this package should import `openai` or `google.genai` directly —
callers ask for a provider via `get_llm_provider()` and talk to it only through
the `LLMProvider` interface in `app.agent.llm.base`.

Which provider a call uses is resolved per user, falling back to the global
setting — see `resolve_provider_name()`.
"""

from typing import TYPE_CHECKING, Optional

from app.agent.llm.base import LLMProvider
from app.config import settings

if TYPE_CHECKING:
    from app.auth.models import User

OPENAI = "openai"
GEMINI = "gemini"

SUPPORTED_PROVIDERS = frozenset({OPENAI, GEMINI})

DEFAULT_PROVIDER = OPENAI

# Providers wrap an SDK client that opens its own connection pool; building a fresh one per call
# forces a new TCP/TLS handshake every time and, since the underlying httpx client is never
# explicitly closed, risks socket exhaustion under load. Cached here instead, keyed by everything
# that determines a provider's identity -- (name, model, api_key) -- so a settings change (as
# tests do via monkeypatch) produces a genuinely different provider rather than a stale one.
_provider_cache: dict[tuple[str, str, str], LLMProvider] = {}


def resolve_provider_name(user: Optional["User"] = None) -> str:
    """Decide which provider to use: the user's preference, else the global setting, else the default.

    `user` is optional so existing callers keep working untouched. A user with no preference set
    (NULL) is the normal case rather than an error -- it means "whatever the server is configured
    for", which is how every user starts out.
    """
    preferred = getattr(user, "preferred_llm_provider", None) if user is not None else None
    return (preferred or settings.llm_provider or DEFAULT_PROVIDER).lower()


def get_llm_provider(user: Optional["User"] = None) -> LLMProvider:
    """Build (or reuse) the LLMProvider for `user`, or the globally configured one when no user is given.

    Note for callers on the tool-calling path: `GeminiProvider` implements structured output only
    and raises from `run_turn`. `app/agent/runner.py` therefore deliberately calls this without a
    user, so a Gemini preference can never reach a code path Gemini does not serve.

    Returns a cached instance when one exists for this exact (provider, model, api_key) -- see
    `_provider_cache` above.
    """
    provider = resolve_provider_name(user)

    if provider == OPENAI:
        model, api_key = settings.llm_model, settings.openai_api_key
    elif provider == GEMINI:
        model, api_key = settings.gemini_model, settings.gemini_api_key
    else:
        raise NotImplementedError(
            f"LLM_PROVIDER={provider!r} is not implemented. Supported providers are "
            f"{sorted(SUPPORTED_PROVIDERS)} — add a provider module under app/agent/llm/ "
            "and wire it in here."
        )

    key = (provider, model, api_key)
    cached = _provider_cache.get(key)
    if cached is not None:
        return cached

    if provider == OPENAI:
        from app.agent.llm.openai_provider import OpenAIProvider

        instance: LLMProvider = OpenAIProvider(model=model, api_key=api_key)
    else:
        from app.agent.llm.gemini_provider import GeminiProvider

        instance = GeminiProvider(model=model, api_key=api_key)

    _provider_cache[key] = instance
    return instance
