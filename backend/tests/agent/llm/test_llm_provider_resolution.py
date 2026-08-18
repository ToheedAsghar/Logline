"""Tests for provider resolution (app/agent/llm/__init__.py).

Which provider serves a call is resolved from the global `LLM_PROVIDER` setting, or from
`provider_override` when one is passed -- the override is for manual dev-time comparison between
providers only, never wired to API input.
"""

import pytest

from app.agent.llm import DEFAULT_PROVIDER, get_llm_provider
from app.agent.llm.gemini_provider import GeminiProvider
from app.agent.llm.openai_provider import OpenAIProvider


@pytest.fixture
def global_openai(monkeypatch):
    from app.agent.llm import _provider_cache, settings

    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test-openai-key")
    monkeypatch.setattr(settings, "gemini_api_key", "test-gemini-key")
    _provider_cache.clear()
    return settings


class TestGetLLMProvider:
    def test_default_is_openai(self, global_openai):
        provider = get_llm_provider()

        assert isinstance(provider, OpenAIProvider)

    def test_global_setting_selects_gemini(self, global_openai, monkeypatch):
        monkeypatch.setattr(global_openai, "llm_provider", "gemini")

        provider = get_llm_provider()

        assert isinstance(provider, GeminiProvider)

    def test_override_wins_over_global_setting(self, global_openai, monkeypatch):
        monkeypatch.setattr(global_openai, "llm_provider", "openai")

        provider = get_llm_provider(provider_override="gemini")

        assert isinstance(provider, GeminiProvider)

    def test_override_is_case_insensitive(self, global_openai):
        provider = get_llm_provider(provider_override="GEMINI")

        assert isinstance(provider, GeminiProvider)

    def test_gemini_provider_uses_gemini_model_not_llm_model(self, global_openai, monkeypatch):
        """`llm_model` defaults to an OpenAI model name; sending it to Gemini would fail every call."""
        monkeypatch.setattr(global_openai, "llm_model", "gpt-5-mini")
        monkeypatch.setattr(global_openai, "gemini_model", "gemini-2.5-flash")

        provider = get_llm_provider(provider_override="gemini")

        assert provider.model == "gemini-2.5-flash"

    def test_empty_global_setting_falls_back_to_default(self, global_openai, monkeypatch):
        """An unset LLM_PROVIDER must not resolve to "" and blow up as an unknown provider."""
        monkeypatch.setattr(global_openai, "llm_provider", "")

        provider = get_llm_provider()

        assert isinstance(provider, OpenAIProvider)
        assert DEFAULT_PROVIDER == "openai"

    def test_unknown_provider_raises(self, global_openai):
        with pytest.raises(NotImplementedError, match="llama"):
            get_llm_provider(provider_override="llama")

    def test_unknown_provider_error_lists_supported_providers(self, global_openai):
        with pytest.raises(NotImplementedError, match="gemini"):
            get_llm_provider(provider_override="llama")


class TestGetLLMProviderCaching:
    """A fresh provider means a fresh SDK client, which means a fresh connection pool -- calling `get_llm_provider()`
    on every request would open a new TCP/TLS connection per call and never close the old one. Instances must be
    reused across calls for the same (provider, model, api_key).
    """

    def test_repeated_calls_return_the_same_instance(self, global_openai):
        first = get_llm_provider()
        second = get_llm_provider()

        assert first is second

    def test_different_providers_get_different_instances(self, global_openai):
        openai_provider = get_llm_provider(provider_override="openai")
        gemini_provider = get_llm_provider(provider_override="gemini")

        assert openai_provider is not gemini_provider

    def test_changed_settings_produce_a_new_instance_not_a_stale_cached_one(self, global_openai, monkeypatch):
        """Regression guard for the cache key itself: keying on provider name alone would return a stale instance
        built from a previous model/api_key after settings change (as happens between test runs via monkeypatch,
        and in principle across a config reload)."""
        first = get_llm_provider(provider_override="gemini")

        monkeypatch.setattr(global_openai, "gemini_model", "gemini-3.0-pro")
        second = get_llm_provider(provider_override="gemini")

        assert first is not second
        assert second.model == "gemini-3.0-pro"
