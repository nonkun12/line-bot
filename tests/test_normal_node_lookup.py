from agents.normal.node import _is_note_lookup_question, _format_note_lookup_result


def test_lookup_question_is_detected():
    assert _is_note_lookup_question("明日15時の予定は？") is True
    assert _is_note_lookup_question("さっきのメモは？") is True
    assert _is_note_lookup_question("予定を教えて？") is True


def test_explicit_note_save_is_not_treated_as_lookup():
    assert _is_note_lookup_question("メモ：明日15時に病院へ電話") is False
    assert _is_note_lookup_question("メモ:明日15時に病院へ電話") is False


def test_lookup_result_formatting():
    result = '[{"title":"病院電話","body":"明日15時に病院へ電話"}]'
    text = _format_note_lookup_result(result)
    assert "病院電話" in text
    assert "明日15時に病院へ電話" in text
