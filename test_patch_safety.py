from patch_validator import calculate_patch_safety_score


def test_patch_safety_ok():
    ok_patch = """--- app.py
+++ app.py.fixed
@@ -10,6 +10,6 @@
 def my_func():
-    x = 1
+    x = 2
     return x
"""
    result = calculate_patch_safety_score(ok_patch, target_function="my_func")
    assert result["score"] >= 80, f"Expected score >= 80, got {result['score']}"
    assert result["safe"] is True, f"Expected safe=True, got {result['safe']}"


def test_patch_safety_ng():
    lines = [f"+ line_{i} = {i}" for i in range(50)]
    ng_patch = """--- app.py
+++ app.py.fixed
@@ -1,50 +1,100 @@
+import os
+import sys
+def other_func():
+    pass
""" + "\n".join(lines) + "\n```python\nsome markdown\n```"

    result = calculate_patch_safety_score(ng_patch, target_function="my_func")
    assert result["score"] < 80, f"Expected score < 80, got {result['score']}"
    assert result["safe"] is False, f"Expected safe=False, got {result['safe']}"


if __name__ == "__main__":
    test_patch_safety_ok()
    test_patch_safety_ng()
    print("All patch safety tests passed!")
