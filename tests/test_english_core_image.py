from agents.english.core_image import (
    explain_core_image,
    extract_core_image_word,
    handle_core_image_command,
)


def test_explicit_japanese_command_extracts_word():
    assert extract_core_image_word("コアイメージ inspect") == "inspect"
    assert extract_core_image_word("語根 transport") == "transport"


def test_english_command_is_supported():
    assert extract_core_image_word("core image respect") == "respect"


def test_known_word_explains_core_image_and_related_words():
    response = handle_core_image_command("コアイメージ inspect")
    assert response is not None
    assert "中をよく見る" in response
    assert "spect" in response
    assert "関連語" in response
    assert "例文" in response
    assert "外部API" in response


def test_unknown_word_does_not_invent_etymology():
    response = explain_core_image("florbulate")
    assert "説明を保留" in response
    assert "推測で断定しない" in response


def test_plain_word_does_not_capture_normal_line_messages():
    assert handle_core_image_command("inspect") is None
    assert handle_core_image_command("コアイメージ") is None


def test_invalid_input_is_rejected():
    response = explain_core_image("../secret")
    assert "1語指定" in response
