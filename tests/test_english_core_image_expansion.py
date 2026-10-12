
from agents.english.core_image import explain_core_image


def test_new_advanced_words_have_local_core_images():
    cases = {
        "abandon": "見捨てる",
        "acquire": "習得する",
        "adapt": "適応する",
        "ambiguous": "曖昧な",
        "assess": "評価する",
        "attain": "達成する",
        "coherent": "一貫した",
        "contradict": "矛盾する",
        "convey": "伝える",
        "feasible": "実行可能な",
        "inevitable": "避けられない",
    }
    for word, meaning in cases.items():
        response = explain_core_image(word)
        assert meaning in response, word
        assert "説明を保留" not in response, word
        assert "外部API" in response, word
