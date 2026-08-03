"""Logging configuration tests."""

import logging
from pathlib import Path

import pytest

from tracker.constants import LOG_DIR
from tracker.logging_config import BACKUP_COUNT, MAX_BYTES, configure_logging


@pytest.fixture(autouse=True)
def _restore_root_handlers():
    """Save and restore root logger handlers so configure_logging() tests don't leak state."""
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    yield
    for handler in root.handlers[:]:
        handler.close()
    root.handlers.clear()
    for handler in original_handlers:
        root.addHandler(handler)
    root.setLevel(original_level)


class TestConfigureLogging:
    def test_creates_log_directory(self, tmp_path, monkeypatch):
        log_dir = tmp_path / "Logs" / "Logline"
        monkeypatch.setattr("tracker.constants.LOG_DIR", log_dir)
        configure_logging()
        assert log_dir.exists()

    def test_installs_file_handlers(self, tmp_path, monkeypatch):
        log_dir = tmp_path / "Logs" / "Logline"
        monkeypatch.setattr("tracker.constants.LOG_DIR", log_dir)
        configure_logging()

        root = logging.getLogger()
        handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
        paths = {Path(h.baseFilename).name for h in handlers}
        assert "tracker.log" in paths
        assert "tracker.error.log" in paths

    def test_info_and_error_handlers_have_separate_levels(self, tmp_path, monkeypatch):
        log_dir = tmp_path / "Logs" / "Logline"
        monkeypatch.setattr("tracker.constants.LOG_DIR", log_dir)
        configure_logging()

        root = logging.getLogger()
        info_handler = next(
            h for h in root.handlers
            if isinstance(h, logging.FileHandler)
            and Path(h.baseFilename).name == "tracker.log"
        )
        error_handler = next(
            h for h in root.handlers
            if isinstance(h, logging.FileHandler)
            and Path(h.baseFilename).name == "tracker.error.log"
        )
        assert info_handler.level == logging.INFO
        assert error_handler.level == logging.WARNING

    def test_file_handlers_use_utf8_encoding(self, tmp_path, monkeypatch):
        log_dir = tmp_path / "Logs" / "Logline"
        monkeypatch.setattr("tracker.constants.LOG_DIR", log_dir)
        configure_logging()

        root = logging.getLogger()
        for handler in root.handlers:
            if isinstance(handler, logging.FileHandler):
                assert handler.encoding == "utf-8"

    def test_file_handlers_use_expected_rotation_settings(self, tmp_path, monkeypatch):
        log_dir = tmp_path / "Logs" / "Logline"
        monkeypatch.setattr("tracker.constants.LOG_DIR", log_dir)
        configure_logging()

        root = logging.getLogger()
        for handler in root.handlers:
            if isinstance(handler, logging.handlers.RotatingFileHandler):
                assert handler.maxBytes == MAX_BYTES
                assert handler.backupCount == BACKUP_COUNT

    def test_root_logger_is_debug_so_handlers_filter(self, tmp_path, monkeypatch):
        log_dir = tmp_path / "Logs" / "Logline"
        monkeypatch.setattr("tracker.constants.LOG_DIR", log_dir)
        configure_logging()

        root = logging.getLogger()
        assert root.level == logging.DEBUG

    def test_clears_existing_handlers(self, tmp_path, monkeypatch):
        log_dir = tmp_path / "Logs" / "Logline"
        monkeypatch.setattr("tracker.constants.LOG_DIR", log_dir)
        root = logging.getLogger()
        root.addHandler(logging.NullHandler())
        configure_logging()

        # Only the two file handlers should remain (plus optional stdout handler).
        file_handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
        assert len(file_handlers) == 2

    def test_default_log_dir_value(self):
        assert LOG_DIR == Path.home() / "Library" / "Logs" / "Logline"

    def test_stdout_handler_respects_environment_variable(self, tmp_path, monkeypatch):
        log_dir = tmp_path / "Logs" / "Logline"
        monkeypatch.setattr("tracker.constants.LOG_DIR", log_dir)
        monkeypatch.setenv("LOGLINE_TRACKER_LOG_STDOUT", "1")
        configure_logging()

        root = logging.getLogger()
        stream_handlers = [h for h in root.handlers if type(h) is logging.StreamHandler]
        assert len(stream_handlers) == 1
        assert stream_handlers[0].level == logging.DEBUG

    def test_no_stdout_handler_without_environment_variable(self, tmp_path, monkeypatch):
        log_dir = tmp_path / "Logs" / "Logline"
        monkeypatch.setattr("tracker.constants.LOG_DIR", log_dir)
        monkeypatch.delenv("LOGLINE_TRACKER_LOG_STDOUT", raising=False)
        configure_logging()

        root = logging.getLogger()
        stream_handlers = [h for h in root.handlers if type(h) is logging.StreamHandler]
        assert len(stream_handlers) == 0
