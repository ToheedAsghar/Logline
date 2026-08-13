"""Sync configuration, loaded from a JSON file with environment overrides.

A file rather than environment variables alone because launchd agents inherit no shell environment; the env vars
exist for foreground development runs. The base URL is validated on load rather than at call time, so an
https-or-loopback rule cannot be left to convention.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional
from urllib.parse import urlparse

from tracker.constants import (
    SYNC_BATCH_SIZE, SYNC_CONFIG_PATH, SYNC_DEFAULT_BASE_URL, SYNC_HTTP_TIMEOUT_SECONDS, SYNC_INTERVAL_SECONDS,
    SYNC_LOOPBACK_HOSTS,
)

ENV_BASE_URL = "LOGLINE_SYNC_BASE_URL"
ENV_BATCH_SIZE = "LOGLINE_SYNC_BATCH_SIZE"


class SyncConfigError(RuntimeError):
    """Configuration is unusable. Raised at load time so a bad value stops the run before any data is read."""


@dataclass(frozen=True)
class SyncConfig:
    base_url: str
    batch_size: int
    interval_seconds: int
    timeout_seconds: int


def _require_secure_base_url(url: str) -> str:
    """Only https, or http to a loopback host for local development. No opt-out flag, unlike the backend's
    `ALLOW_INSECURE_BASE_URLS` -- that exists for deployments terminating TLS elsewhere, which cannot apply to a
    laptop talking to a remote API."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise SyncConfigError(f"base_url must be an absolute http(s) URL (got {url!r})")
    if parsed.scheme == "http" and parsed.hostname not in SYNC_LOOPBACK_HOSTS:
        raise SyncConfigError(
            f"base_url must use https:// for any non-loopback host (got {url!r})"
        )
    return url.rstrip("/")


def _read_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SyncConfigError(f"could not read sync config at {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SyncConfigError(f"sync config at {path} must be a JSON object")
    return raw


def _positive_int(value, name: str, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise SyncConfigError(f"{name} must be an integer (got {value!r})") from exc
    if parsed <= 0:
        raise SyncConfigError(f"{name} must be positive (got {parsed})")
    return parsed


def load_config(path: Optional[Path] = None, env: Optional[Mapping[str, str]] = None) -> SyncConfig:
    """Loads config from `path` (default SYNC_CONFIG_PATH), with environment variables taking precedence. A missing
    file is not an error -- the defaults point at a local backend."""
    path = path if path is not None else SYNC_CONFIG_PATH
    env = env if env is not None else os.environ
    data = _read_file(path)

    base_url = env.get(ENV_BASE_URL) or data.get("base_url") or SYNC_DEFAULT_BASE_URL
    batch_size = _positive_int(env.get(ENV_BATCH_SIZE) or data.get("batch_size"), "batch_size", SYNC_BATCH_SIZE)
    interval_seconds = _positive_int(data.get("interval_seconds"), "interval_seconds", SYNC_INTERVAL_SECONDS)
    timeout_seconds = _positive_int(data.get("timeout_seconds"), "timeout_seconds", SYNC_HTTP_TIMEOUT_SECONDS)

    return SyncConfig(
        base_url=_require_secure_base_url(str(base_url)),
        batch_size=batch_size,
        interval_seconds=interval_seconds,
        timeout_seconds=timeout_seconds,
    )
