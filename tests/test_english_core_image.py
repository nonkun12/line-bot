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


def test_bulk_fourth_batch_common_words_have_local_core_images():
    cases = {
        "achieve": ("達成する", "achievement"),
        "accept": ("受け入れる", "reject"),
        "affect": ("影響する", "effect"),
        "appear": ("現れる", "disappear"),
        "apply": ("申し込む", "application"),
        "approach": ("取り組み方", "method"),
        "avoid": ("避ける", "prevent"),
        "benefit": ("恩恵", "advantage"),
        "compare": ("比較する", "comparison"),
        "complete": ("完了する", "incomplete"),
        "consider": ("検討する", "consideration"),
        "decide": ("決める", "decision"),
        "develop": ("開発する", "development"),
        "discover": ("発見する", "discovery"),
        "explain": ("説明する", "explanation"),
        "express": ("表現する", "expression"),
        "improve": ("改善する", "improvement"),
        "involve": ("含む", "involvement"),
        "maintain": ("維持する", "maintenance"),
        "manage": ("管理する", "manager"),
        "prevent": ("防ぐ", "prevention"),
        "provide": ("提供する", "provision"),
        "reduce": ("減らす", "reduction"),
        "require": ("必要とする", "requirement"),
        "respond": ("返答する", "response"),
        "support": ("支援する", "supporter"),
        "understand": ("理解する", "misunderstand"),
        "transform": ("変形させる", "transformation"),
        "transfer": ("移す", "transport"),
        "prepare": ("準備する", "preparation"),
    }
    for word, (meaning, cue) in cases.items():
        response = explain_core_image(word)
        assert meaning in response, word
        assert cue in response, word
        assert "外部API" in response, word
        assert "説明を保留" not in response, word


def test_opaque_word_parts_are_not_misrepresented_as_etymology():
    for word in ("achieve", "accept", "appear", "approach", "consider", "decide", "develop", "discover", "explain", "express", "improve", "understand"):
        response = explain_core_image(word)
        assert "語源分解ではありません" in response, word
