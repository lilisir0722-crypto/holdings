from holdings.web import format_beijing


def test_format_beijing_from_utc_iso():
    assert format_beijing("2026-08-19T23:20:43.478909+00:00") == "2026-08-20 07:20:43"


def test_format_beijing_zulu_and_naive():
    assert format_beijing("2026-08-19T23:20:43Z") == "2026-08-20 07:20:43"
    assert format_beijing("2026-08-19T23:20:43") == "2026-08-20 07:20:43"


def test_format_beijing_empty_and_junk():
    assert format_beijing(None) == ""
    assert format_beijing("") == ""
    assert format_beijing("not-a-time") == "not-a-time"
