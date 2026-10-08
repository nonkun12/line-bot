from core.hermes_obsidian_bridge import is_verified_hermes_result


def test_verified_hermes_pass_is_eligible():
    result = {
        "source": "hermes-kanban",
        "status": "PASS",
        "verified": True,
        "auto_apply_patch": False,
        "auto_deploy": False,
    }
    assert is_verified_hermes_result(result) is True


def test_hermes_fail_is_blocked():
    result = {
        "source": "hermes-kanban",
        "status": "FAIL",
        "verified": True,
        "auto_apply_patch": False,
        "auto_deploy": False,
    }
    assert is_verified_hermes_result(result) is False


def test_hermes_blocked_is_blocked():
    result = {
        "source": "hermes-kanban",
        "status": "BLOCKED",
        "verified": True,
        "auto_apply_patch": False,
        "auto_deploy": False,
    }
    assert is_verified_hermes_result(result) is False


def test_unverified_or_unsafe_result_is_blocked():
    assert is_verified_hermes_result(
        {
            "source": "hermes-kanban",
            "status": "PASS",
            "verified": False,
            "auto_apply_patch": False,
            "auto_deploy": False,
        }
    ) is False
    assert is_verified_hermes_result(
        {
            "source": "hermes-kanban",
            "status": "PASS",
            "verified": True,
            "auto_apply_patch": True,
            "auto_deploy": False,
        }
    ) is False
