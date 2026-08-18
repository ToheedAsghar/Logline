"""Tests for startup validation in app/config.py.

`_require_supported_llm_provider` is called at module import time, right after `settings` is built,
so an invalid `LLM_PROVIDER` fails the process at boot rather than at first reconciliation call.
"""

import pytest

from app.config import (
    GOOGLE_REDIRECT_URI_CONFLICT_MESSAGE, _require_distinct_google_redirect_uris, _require_supported_llm_provider,
)


class TestRequireSupportedLLMProvider:
    def test_openai_is_accepted(self):
        _require_supported_llm_provider("openai")

    def test_gemini_is_accepted(self):
        _require_supported_llm_provider("gemini")

    def test_accepted_values_are_case_insensitive(self):
        _require_supported_llm_provider("OpenAI")

    def test_unknown_provider_raises(self):
        with pytest.raises(RuntimeError, match="llama"):
            _require_supported_llm_provider("llama")

    def test_error_lists_supported_providers(self):
        with pytest.raises(RuntimeError, match="gemini"):
            _require_supported_llm_provider("llama")


class TestRequireDistinctGoogleRedirectUris:
    def test_distinct_uris_are_accepted(self):
        _require_distinct_google_redirect_uris(
            "https://app.example.com/auth/google/callback",
            "https://app.example.com/integrations/calendar/callback",
        )

    def test_identical_uris_raise(self):
        with pytest.raises(RuntimeError, match=GOOGLE_REDIRECT_URI_CONFLICT_MESSAGE):
            _require_distinct_google_redirect_uris(
                "https://app.example.com/auth/google/callback",
                "https://app.example.com/auth/google/callback",
            )
