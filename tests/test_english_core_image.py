from agents.english.core_image import (
    available_core_images,
    format_core_image_lesson,
    get_core_image,
)


def test_core_image_is_conceptual_center_not_translation_only():
    entry = get_core_image("improve")
    assert entry is not None
    assert entry.core_image == "今より良い状態へ持っていく"
    assert entry.common_senses == ("改善する", "向上させる")
    assert "improve" in entry.example


def test_core_image_lookup_is_normalized_and_unknown_fails_closed():
    assert get_core_image(" Improve ") == get_core_image("improve")
    assert get_core_image("unknown-word") is None
    assert format_core_image_lesson("unknown-word") is None


def test_core_image_lesson_keeps_the_core_image_visible():
    text = format_core_image_lesson("schedule")
    assert text is not None
    assert "コアイメージ:" in text
    assert "時間の流れ" in text


def test_initial_core_image_set_is_bounded():
    words = tuple(entry.word for entry in available_core_images())
    assert words == ("improve", "schedule", "recommend")
