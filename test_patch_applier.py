import os
import shutil
from patch_applier import apply_patch, check_patch
from patch_validator import calculate_patch_safety_score


def test_patch_applier_ok():
    target_file = "test_target_tmp.py"
    try:
        with open(target_file, "w", encoding="utf-8") as f:
            f.write("""def target_func():
    a = 1
    return a
""")

        valid_patch = f"""--- {target_file}
+++ {target_file}.fixed
@@ -1,3 +1,3 @@
 def target_func():
-    a = 1
+    a = 2
     return a
"""

        # 1. check_patch 検証
        check_res = check_patch(valid_patch, filename=target_file)
        assert check_res["ok"] is True, f"check_patch failed: {check_res['message']}"

        # 2. apply_patch 実行
        apply_res = apply_patch(valid_patch, filename=target_file)
        assert apply_res["ok"] is True, f"apply_patch failed: {apply_res['message']}"

        # バックアップ存在確認
        assert os.path.exists(f"{target_file}.before_auto_apply")

        # 内容検証
        with open(target_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert "a = 2" in content

    finally:
        if os.path.exists(target_file):
            os.remove(target_file)
        if os.path.exists(f"{target_file}.before_auto_apply"):
            os.remove(f"{target_file}.before_auto_apply")


def test_patch_applier_ng_import():
    import_patch = """--- app.py
+++ app.py.fixed
@@ -1,3 +1,4 @@
+import os
 def foo():
     pass
"""
    safety = calculate_patch_safety_score(import_patch, target_function="foo")
    assert safety["score"] < 90, f"Expected score < 90 for import patch, got {safety['score']}"


def test_patch_applier_invalid_diff():
    invalid_patch = "invalid diff format string"
    check_res = check_patch(invalid_patch, filename="app.py")
    assert check_res["ok"] is False


if __name__ == "__main__":
    test_patch_applier_ok()
    test_patch_applier_ng_import()
    test_patch_applier_invalid_diff()
    print("All patch applier tests passed!")
