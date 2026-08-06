"""Config loading, and the https rule that must hold structurally rather than by convention.

Window titles, project paths and branch names travel in the sync payload. A base URL that silently accepts
`http://` to a remote host would put all of it on the wire in plaintext, and nothing downstream would notice.
"""

import json

import pytest

from tracker.constants import SYNC_BATCH_SIZE, SYNC_DEFAULT_BASE_URL
from tracker.sync.config import ENV_BASE_URL, ENV_BATCH_SIZE, SyncConfigError, load_config


def _write(tmp_path, data):
    path = tmp_path / "sync.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TestBaseUrlEnforcement:
    def test_https_is_accepted(self, tmp_path):
        config = load_config(_write(tmp_path, {"base_url": "https://api.logline.dev"}), env={})
        assert config.base_url == "https://api.logline.dev"

    @pytest.mark.parametrize("url", ["http://localhost:8000", "http://127.0.0.1:8000", "http://[::1]:8000"])
    def test_loopback_http_is_accepted(self, tmp_path, url):
        assert load_config(_write(tmp_path, {"base_url": url}), env={}).base_url == url

    @pytest.mark.parametrize(
        "url",
        [
            "http://api.logline.dev",
            "http://192.168.1.10:8000",
            "http://localhost.evil.example",
        ],
    )
    def test_non_loopback_http_is_rejected(self, tmp_path, url):
        with pytest.raises(SyncConfigError, match="https"):
            load_config(_write(tmp_path, {"base_url": url}), env={})

    @pytest.mark.parametrize("url", ["ftp://example.com", "not-a-url", "https://"])
    def test_non_http_urls_are_rejected(self, tmp_path, url):
        with pytest.raises(SyncConfigError):
            load_config(_write(tmp_path, {"base_url": url}), env={})

    def test_blank_base_url_falls_back_to_the_default(self, tmp_path):
        """Blank means "not configured", not "configured to nothing" — an empty value in the file or the
        environment must not become an unusable URL."""
        assert load_config(_write(tmp_path, {"base_url": ""}), env={ENV_BASE_URL: ""}).base_url == (
            SYNC_DEFAULT_BASE_URL
        )

    def test_rejection_happens_at_load_not_at_first_request(self, tmp_path):
        """Loading is the only gate — nothing later re-checks, so a bad value must stop the run here."""
        with pytest.raises(SyncConfigError):
            load_config(_write(tmp_path, {"base_url": "http://remote.example"}), env={})

    def test_trailing_slash_is_normalized(self, tmp_path):
        config = load_config(_write(tmp_path, {"base_url": "https://api.logline.dev/"}), env={})
        assert config.base_url == "https://api.logline.dev"


class TestSources:
    def test_missing_file_falls_back_to_defaults(self, tmp_path):
        config = load_config(tmp_path / "absent.json", env={})
        assert config.base_url == SYNC_DEFAULT_BASE_URL
        assert config.batch_size == SYNC_BATCH_SIZE

    def test_environment_overrides_the_file(self, tmp_path):
        path = _write(tmp_path, {"base_url": "https://file.example", "batch_size": 10})
        config = load_config(path, env={ENV_BASE_URL: "https://env.example", ENV_BATCH_SIZE: "25"})
        assert config.base_url == "https://env.example"
        assert config.batch_size == 25

    def test_environment_override_is_validated_too(self, tmp_path):
        with pytest.raises(SyncConfigError, match="https"):
            load_config(_write(tmp_path, {}), env={ENV_BASE_URL: "http://remote.example"})

    def test_malformed_file_is_an_error_not_a_silent_default(self, tmp_path):
        path = tmp_path / "sync.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(SyncConfigError):
            load_config(path, env={})

    @pytest.mark.parametrize("value", [0, -1, "abc"])
    def test_non_positive_or_non_numeric_sizes_are_rejected(self, tmp_path, value):
        with pytest.raises(SyncConfigError):
            load_config(_write(tmp_path, {"batch_size": value}), env={})
