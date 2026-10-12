import json

from scripts import recovery_ai_mac_smoke


def test_smoke_runs_with_temporary_state_and_no_advisor_by_default(capsys):
    result = recovery_ai_mac_smoke.main([])
    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["state_persisted_and_read_back"] is True
    assert payload["advisor_requested"] is False
    assert payload["live_queue_touched"] is False
    assert payload["patch_or_deploy_performed"] is False
