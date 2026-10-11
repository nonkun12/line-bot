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

def test_batch_four_common_words_have_local_core_images():
    cases = {
        "benefit": ("恩恵", "beneficial"),
        "support": ("下から支える", "支援"),
        "transfer": ("向こうへ運ぶ", "trans-"),
        "transform": ("変形", "form"),
        "prevent": ("防ぐ", "pre-"),
        "discover": ("発見", "cover"),
        "describe": ("描写", "description"),
        "construct": ("建設", "structure"),
        "reduce": ("減らす", "duc"),
        "produce": ("生産", "product"),
    }
    for word, (meaning, cue) in cases.items():
        response = explain_core_image(word)
        assert meaning in response, word
        assert cue in response, word
        assert "外部API" in response, word
        assert "説明を保留" not in response, word



def test_batch_five_advanced_exam_words_have_local_core_images():
    cases = {
        "alleviate": ("緩和", "mitigate"),
        "exacerbate": ("悪化", "worsen"),
        "mitigate": ("軽減", "alleviate"),
        "substantiate": ("裏付け", "evidence"),
        "scrutinize": ("精査", "scrutiny"),
        "undermine": ("損なう", "confidence"),
        "foster": ("育む", "innovation"),
        "ubiquitous": ("至る所", "widespread"),
        "plausible": ("もっともらしい", "credible"),
        "arbitrary": ("恣意的", "discretion"),
        "inherent": ("固有", "intrinsic"),
        "subsequent": ("その後", "subsequently"),
        "preliminary": ("予備的", "tentative"),
        "ambiguous": ("曖昧", "ambiguity"),
        "compel": ("余儀なく", "compulsory"),
        "relinquish": ("手放す", "surrender"),
        "stringent": ("厳格", "rigorous"),
        "detrimental": ("悪影響", "harmful"),
        "feasible": ("実現可能", "feasibility"),
        "discrepancy": ("食い違い", "inconsistency"),
        "coherent": ("首尾一貫", "coherence"),
        "consensus": ("合意", "agreement"),
        "tentative": ("暫定", "provisional"),
        "resilient": ("回復力", "resilience"),
        "allocate": ("配分", "allocation"),
    }
    for word, (meaning, cue) in cases.items():
        response = explain_core_image(word)
        assert meaning in response, word
        assert cue in response, word
        assert "外部API" in response, word
        assert "説明を保留" not in response, word


def test_batch_six_advanced_academic_words_have_local_core_images():
    cases = {
        "corroborate": ("裏付ける", "corroboration"),
        "concede": ("しぶしぶ認める", "concession"),
        "contend": ("主張する", "contention"),
        "assert": ("断言する", "assertion"),
        "refute": ("反論する", "refutation"),
        "reconcile": ("和解させる", "reconciliation"),
        "infer": ("推論する", "inference"),
        "deduce": ("演繹する", "deduction"),
        "implication": ("含意", "imply"),
        "contention": ("主張", "contend"),
        "premise": ("前提", "premise"),
        "conjecture": ("推測", "conjecture"),
        "scrupulous": ("綿密な", "scrupulously"),
        "pervasive": ("広く浸透した", "pervade"),
        "obsolete": ("廃れた", "obsolescence"),
        "intricate": ("入り組んだ", "intricacy"),
        "indispensable": ("不可欠な", "indispensability"),
        "profound": ("深遠な", "profoundly"),
        "ambivalent": ("相反する気持ちのある", "ambivalence"),
        "conspicuous": ("目立つ", "conspicuously"),
        "diligent": ("勤勉な", "diligence"),
        "meticulous": ("細心の", "meticulously"),
        "plight": ("苦境", "in dire straits"),
        "incentive": ("動機", "incentivize"),
        "disparity": ("格差", "disparate"),
    }
    for word, (meaning, cue) in cases.items():
        response = explain_core_image(word)
        assert meaning in response, word
        assert cue in response, word
        assert "外部API" in response, word
        assert "説明を保留" not in response, word


def test_core_image_dictionary_has_no_duplicate_literal_word_keys():
    import ast
    from pathlib import Path

    source = Path("agents/english/core_image.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    entries = next(
        node for node in module.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "_ENTRIES"
    )
    keys = [key.value for key in entries.value.keys if isinstance(key, ast.Constant)]
    assert len(keys) == len(set(keys))
    assert len(keys) >= 55

