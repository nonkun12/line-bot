from app import (
    LINE_MAX_MESSAGE_LENGTH,
    _line_text_length,
    split_line_message,
)


def test_ascii_messages_stay_within_line_limit():
    chunks = split_line_message("a" * 12000)
    assert len(chunks) <= 5
    assert all(_line_text_length(chunk) <= LINE_MAX_MESSAGE_LENGTH for chunk in chunks)
    assert "".join(chunks).startswith("a" * 12000)


def test_supplementary_unicode_is_counted_as_two_utf16_units():
    chunks = split_line_message("😀" * 6000)
    assert len(chunks) <= 5
    assert all(_line_text_length(chunk) <= LINE_MAX_MESSAGE_LENGTH for chunk in chunks)
    assert all(chunk.encode("utf-16-le").decode("utf-16-le") == chunk for chunk in chunks)


def test_newline_preferred_without_exceeding_budget():
    source = ("x" * 100 + "\n") * 60
    chunks = split_line_message(source, max_len=120, max_messages=5, max_total=600)
    assert all(_line_text_length(chunk) <= 120 for chunk in chunks)
    assert chunks[0].endswith("\\n")
    assert "一部を省略しました" in chunks[-1]


def test_truncation_notice_is_also_within_utf16_budget():
    chunks = split_line_message("😀" * 30000, max_len=4500, max_messages=2, max_total=9000)
    assert len(chunks) == 2
    assert all(_line_text_length(chunk) <= 4500 for chunk in chunks)
    assert "一部を省略しました" in chunks[-1]
