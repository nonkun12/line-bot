from pathlib import Path


def test_debug_agent_auto_apply_is_disabled_by_default_and_env_gated():
    source = (Path(__file__).resolve().parents[1] / "debug_agent.py").read_text(encoding="utf-8")

    assert 'os.getenv("AUTO_APPLY_PATCH", "false").strip().lower() == "true"' in source
    assert "auto_apply_enabled and" in source
