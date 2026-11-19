from agents.patch.generator import generate_patch_candidates


VALID_DIFF = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -10,7 +10,7 @@ def handler(data):
     user = data
-    user_id = data["user_id"]
+    user_id = data.get("user_id")
     return user_id
"""


MULTI_FILE_DIFF = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,3 +1,3 @@
-a = 1
+a = 2
diff --git a/utils.py b/utils.py
--- a/utils.py
+++ b/utils.py
@@ -5,3 +5,3 @@
-b = 1
+b = 2
"""


# ---------------------------------------------------------------------------
# 正常系: Patch候補生成
# ---------------------------------------------------------------------------

def test_generate_patch_candidates_from_valid_fix_result():
    fix_result = {
        "summary": "KeyErrorを避けるためget()に変更",
        "patch": VALID_DIFF,
        "confidence": 0.9,
        "patch_valid": True,
    }

    candidates = generate_patch_candidates(fix_result)

    assert len(candidates) == 1

    candidate = candidates[0]

    assert candidate["target_file"] == "app.py"
    assert 'data["user_id"]' in candidate["before"]
    assert 'data.get("user_id")' in candidate["after"]
    assert candidate["reason"] == "KeyErrorを避けるためget()に変更"
    assert candidate["confidence"] == 0.9
    assert candidate["safe_to_apply"] is True


def test_generate_patch_candidates_handles_multiple_files():
    fix_result = {
        "summary": "複数ファイルの修正",
        "patch": MULTI_FILE_DIFF,
        "confidence": 0.8,
        "patch_valid": True,
    }

    candidates = generate_patch_candidates(fix_result)

    assert len(candidates) == 2

    target_files = [c["target_file"] for c in candidates]
    assert "app.py" in target_files
    assert "utils.py" in target_files


def test_generate_patch_candidates_confidence_is_clamped_between_0_and_1():
    over_confidence_result = {
        "summary": "reason",
        "patch": VALID_DIFF,
        "confidence": 5.0,
    }

    candidates = generate_patch_candidates(over_confidence_result)
    assert candidates[0]["confidence"] == 1.0

    negative_confidence_result = {
        "summary": "reason",
        "patch": VALID_DIFF,
        "confidence": -3.0,
    }

    candidates = generate_patch_candidates(negative_confidence_result)
    assert candidates[0]["confidence"] == 0.0


def test_generate_patch_candidates_default_reason_when_summary_missing():
    fix_result = {
        "patch": VALID_DIFF,
        "confidence": 0.9,
    }

    candidates = generate_patch_candidates(fix_result)

    assert candidates[0]["reason"] == "修正理由は生成されませんでした"


# ---------------------------------------------------------------------------
# 不正データ処理テスト
# ---------------------------------------------------------------------------

def test_generate_patch_candidates_with_none_fix_result_returns_empty_list():
    assert generate_patch_candidates(None) == []


def test_generate_patch_candidates_with_non_dict_fix_result_returns_empty_list():
    assert generate_patch_candidates("not a dict") == []
    assert generate_patch_candidates(["also", "not", "a", "dict"]) == []


def test_generate_patch_candidates_with_empty_dict_returns_empty_list():
    assert generate_patch_candidates({}) == []


def test_generate_patch_candidates_with_empty_patch_returns_empty_list():
    fix_result = {
        "summary": "reason",
        "patch": "",
        "confidence": 0.9,
    }

    assert generate_patch_candidates(fix_result) == []


def test_generate_patch_candidates_with_non_string_patch_returns_empty_list():
    fix_result = {
        "summary": "reason",
        "patch": 12345,
        "confidence": 0.9,
    }

    assert generate_patch_candidates(fix_result) == []


def test_generate_patch_candidates_with_malformed_diff_does_not_raise():
    fix_result = {
        "summary": "reason",
        "patch": "this is not a valid unified diff at all",
        "confidence": 0.9,
    }

    # 例外を投げず、target_fileが特定できない候補を返すか
    # 空リストになる(いずれにせよクラッシュしない)
    candidates = generate_patch_candidates(fix_result)
    assert isinstance(candidates, list)

    if candidates:
        assert candidates[0]["target_file"] == "unknown"
        assert candidates[0]["safe_to_apply"] is False


def test_generate_patch_candidates_with_invalid_confidence_type_defaults_to_zero():
    fix_result = {
        "summary": "reason",
        "patch": VALID_DIFF,
        "confidence": "not-a-number",
    }

    candidates = generate_patch_candidates(fix_result)

    assert candidates[0]["confidence"] == 0.0


# ---------------------------------------------------------------------------
# safe_to_apply = False になるケースの確認
# ---------------------------------------------------------------------------

def test_safe_to_apply_is_false_when_confidence_below_threshold():
    fix_result = {
        "summary": "reason",
        "patch": VALID_DIFF,
        "confidence": 0.3,
        "patch_valid": True,
    }

    candidates = generate_patch_candidates(fix_result)

    assert candidates[0]["safe_to_apply"] is False


def test_safe_to_apply_is_false_when_patch_valid_is_false():
    fix_result = {
        "summary": "reason",
        "patch": VALID_DIFF,
        "confidence": 0.99,
        "patch_valid": False,
    }

    candidates = generate_patch_candidates(fix_result)

    assert candidates[0]["safe_to_apply"] is False


def test_safe_to_apply_is_false_when_target_file_unknown():
    fix_result = {
        "summary": "reason",
        "patch": "not a real diff, no file markers here",
        "confidence": 0.99,
        "patch_valid": True,
    }

    candidates = generate_patch_candidates(fix_result)

    if candidates:
        assert candidates[0]["safe_to_apply"] is False


def test_safe_to_apply_is_false_when_no_actual_change():
    no_change_diff = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,3 +1,3 @@
 def foo():
     pass
"""

    fix_result = {
        "summary": "reason",
        "patch": no_change_diff,
        "confidence": 0.99,
        "patch_valid": True,
    }

    candidates = generate_patch_candidates(fix_result)

    assert candidates[0]["safe_to_apply"] is False


def test_safe_to_apply_is_true_only_when_all_conditions_met():
    fix_result = {
        "summary": "reason",
        "patch": VALID_DIFF,
        "confidence": 0.85,
        "patch_valid": True,
    }

    candidates = generate_patch_candidates(fix_result)

    assert candidates[0]["safe_to_apply"] is True
