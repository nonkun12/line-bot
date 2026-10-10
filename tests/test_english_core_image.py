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



def test_circumstance_has_conservative_core_image():
    response = explain_core_image("circumstance")
    assert "周りに立っている事情" in response
    assert "circum-" in response
    assert "説明を保留" not in response


def test_environment_has_core_image_and_no_external_api():
    response = explain_core_image("environment")
    assert "取り巻くもの・条件" in response
    assert "環境" in response
    assert "外部API" in response



def test_postpone_has_core_image_and_related_words():
    response = explain_core_image("postpone")
    assert "延期する" in response
    assert "post-" in response
    assert "外部API" in response


def test_batch_two_common_words_have_local_core_images():
    cases = {
        "include": ("含める", "exclude"),
        "exclude": ("除外する", "include"),
        "connect": ("つなぐ", "disconnect"),
        "interrupt": ("中断する", "rupt"),
        "predict": ("予測する", "pre-"),
        "review": ("見直す", "再び"),
    }
    for word, (meaning, cue) in cases.items():
        response = explain_core_image(word)
        assert meaning in response, word
        assert cue in response, word
        assert "外部API" in response, word
        assert "説明を保留" not in response, word


def test_batch_three_common_words_have_local_core_images():
    cases = {
        "visible": ("目に見える", "vision"),
        "dictate": ("指示する", "dict"),
        "contradict": ("矛盾する", "contra-"),
        "attract": ("引きつける", "distract"),
        "distract": ("注意をそらす", "tract"),
    }
    for word, (meaning, cue) in cases.items():
        response = explain_core_image(word)
        assert meaning in response, word
        assert cue in response, word
        assert "外部API" in response, word
        assert "説明を保留" not in response, word



def test_expanded_core_image_lexicon_has_common_word_families():
    cases = {
        "preview": ("事前確認", "pre-"),
        "prevent": ("防ぐ", "venire"),
        "construct": ("建設する", "struct"),
        "inject": ("注入する", "ject"),
        "reject": ("拒否する", "ject"),
        "prescribe": ("処方する", "scribe"),
        "transcribe": ("書き起こす", "trans-"),
        "audience": ("聴衆", "audire"),
        "interact": ("相互作用", "inter-"),
        "emerge": ("現れる", "emergere"),
        "immerse": ("没頭", "merge"),
        "progress": ("進歩", "gress"),
        "regress": ("後退", "gress"),
        "transfer": ("移す", "trans-"),
        "refer": ("参照", "reference"),
        "prefer": ("好む", "pre-"),
        "offer": ("申し出る", "差し出す"),
    }
    for word, (meaning, cue) in cases.items():
        response = explain_core_image(word)
        assert meaning in response, word
        assert cue in response, word
        assert "外部API" in response, word
        assert "説明を保留" not in response, word


def test_expanded_lexicon_keeps_unknown_words_fail_closed():
    response = explain_core_image("unverifiedword")
    assert "説明を保留" in response
    assert "推測で断定しない" in response
