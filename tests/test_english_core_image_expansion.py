from agents.english.core_image import _ENTRIES, explain_core_image


def test_dictionary_keys_match_word_entry_names():
    assert all(key == entry.word for key, entry in _ENTRIES.items())


def test_reviewed_batch_words_have_local_core_image_explanations():
    expected = {
        "abandon": "見捨てる",
        "acquire": "得る",
        "adapt": "適応する",
        "adequate": "十分な",
        "advocate": "提唱する",
        "anticipate": "予期する",
        "apparent": "明白な",
        "assess": "評価する",
        "attain": "達成する",
        "bias": "偏り",
        "cease": "停止する",
        "constrain": "制約する",
        "contemplate": "熟考する",
        "convey": "伝える",
        "crucial": "極めて重要な",
        "diminish": "減少する",
        "elaborate": "詳しく説明する",
        "enhance": "高める",
        "explicit": "明確な",
        "fluctuate": "変動する",
        "fundamental": "根本的な",
        "inevitable": "避けられない",
    }
    for word, expected_meaning in expected.items():
        response = explain_core_image(word)
        assert word in response, word
        assert expected_meaning in response, word
        assert "説明を保留" not in response, word
        assert "外部APIへの問い合わせは行いません" in response, word


def test_second_reviewed_batch_words_have_local_core_image_explanations():
    expected = {
        "achieve": "達成する",
        "adjust": "調整する",
        "approach": "方法",
        "avoid": "避ける",
        "compare": "比較する",
        "consider": "検討する",
        "create": "創造する",
        "decide": "決める",
        "define": "定義する",
        "develop": "開発する",
        "encourage": "励ます",
        "establish": "確立する",
        "expect": "予期する",
        "explain": "説明する",
        "improve": "改善する",
        "maintain": "維持する",
        "require": "必要とする",
        "understand": "理解する",
        "provide": "提供する",
        "respond": "返答する",
        "solve": "解決する",
    }
    for word, expected_meaning in expected.items():
        response = explain_core_image(word)
        assert word in response, word
        assert expected_meaning in response, word
        assert "説明を保留" not in response, word
        assert "外部APIへの問い合わせは行いません" in response
