"""Factory for the configured LLMProvider.

Nothing outside this package should import `openai` or `google.genai` directly —
callers ask for a provider via `get_llm_provider()` and talk to it only through
the `LLMProvider` interface in `app.agent.llm.base`.

Which provider a call uses is resolved from the global `LLM_PROVIDER` setting.
"""

from app.agent.llm.base import LLMProvider
from app.config import settings

OPENAI = "openai"
GEMINI = "gemini"

SUPPORTED_PROVIDERS = frozenset({OPENAI, GEMINI})

DEFAULT_PROVIDER = OPENAI

_provider_cache: dict[tuple[str, str, str], LLMProvider] = {}


def get_llm_provider(provider_override: str | None = None) -> LLMProvider:
    """Build (or reuse) the globally configured LLMProvider.

    `provider_override` takes priority over `settings.llm_provider` when given -- for manual dev-time comparison
    between providers only, never wire this to API input or a user-facing parameter.

    Returns a cached instance when one exists for this exact (provider, model, api_key) -- see `_provider_cache`
    above.
    """
    provider = (provider_override or settings.llm_provider or DEFAULT_PROVIDER).lower()

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
