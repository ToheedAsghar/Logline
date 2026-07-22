"""Regression tests for terminal title redaction."""

import pytest

from tracker.constants import KNOWN_TERMINAL_BUNDLE_IDS
from tracker.redaction import redact_title


@pytest.mark.parametrize("bundle_id", sorted(KNOWN_TERMINAL_BUNDLE_IDS))
def test_known_terminal_titles_are_redacted(bundle_id):
    assert redact_title(bundle_id, "ssh prod-db -- rm -rf /") is None


def test_non_terminal_titles_are_not_redacted():
    assert redact_title("com.example.Editor", "notes.txt") == "notes.txt"
