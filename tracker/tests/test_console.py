import tracker.console as console


def test_detail_values_are_escaped_and_truncated():
    output = console._detail_summary({"cwd": "A\x1b[31m\r" + "x" * 100})
    assert "\\x1b" in output
    assert "\\r" in output
    assert len(output) < 100
