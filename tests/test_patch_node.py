from agents.patch.node import patch_generate_node, patch_apply_node


VALID_DIFF = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -10,7 +10,7 @@ def handler(data):
     user = data
-    user_id = data["user_id"]
+    user_id = data.get("user_id")
     return user_id
"""


def test_patch_generate_node_produces_candidates_from_fix_result():
    state = {
        "agent_results": {
            "fix": {
                "summary": "KeyError回避",
                "patch": VALID_DIFF,
                "confidence": 0.9,
                "patch_valid": True,
            }
        }
    }

    result = patch_generate_node(state)

    assert "patch_candidates" in result
    assert len(result["patch_candidates"]) == 1
    assert result["patch_candidates"][0]["target_file"] == "app.py"

    stored = result["agent_results"]["patch_candidates"]
    assert stored["count"] == 1
    assert "error" not in stored


def test_patch_generate_node_with_missing_fix_result_returns_empty_candidates():
    state = {
        "agent_results": {}
    }

    result = patch_generate_node(state)

    assert result["patch_candidates"] == []
    assert result["agent_results"]["patch_candidates"]["count"] == 0


def test_patch_generate_node_does_not_mutate_other_agent_results():
    state = {
        "agent_results": {
            "debug": {"text": "debug info"},
            "fix": {
                "summary": "reason",
                "patch": VALID_DIFF,
                "confidence": 0.9,
                "patch_valid": True,
            },
        }
    }

    result = patch_generate_node(state)

    # 既存のdebug/fix結果はそのまま保持される
    assert result["agent_results"]["debug"] == {"text": "debug info"}
    assert result["agent_results"]["fix"]["summary"] == "reason"


def test_patch_generate_node_never_writes_files(tmp_path, monkeypatch):
    """
    Phase3の重要な制約: patch_generate_nodeは
    実ファイルへの書き込みを一切行わない。
    """

    monkeypatch.chdir(tmp_path)

    before_files = set(tmp_path.iterdir())

    state = {
        "agent_results": {
            "fix": {
                "summary": "reason",
                "patch": VALID_DIFF,
                "confidence": 0.9,
                "patch_valid": True,
            }
        }
    }

    patch_generate_node(state)

    after_files = set(tmp_path.iterdir())

    assert before_files == after_files


# ---------------------------------------------------------------------------
# 既存の patch_apply_node (Phase4a) が無変更であることの回帰確認
# ---------------------------------------------------------------------------

def test_patch_apply_node_still_skips_by_default(monkeypatch):
    monkeypatch.delenv("AUTO_APPLY_PATCH", raising=False)

    state = {
        "agent_results": {
            "fix": {
                "patch": VALID_DIFF,
            }
        }
    }

    result = patch_apply_node(state)

    patch_result = result["agent_results"]["patch"]

    assert patch_result["skipped"] is True
    assert patch_result["applied"] is False
    assert patch_result["reason"] == "AUTO_APPLY_PATCH is disabled"
