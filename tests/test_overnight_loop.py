from standalone_agent.graph.graph import route_from_debug, route_from_test


def test_failed_test_routes_back_to_debug():
    assert route_from_test({"test_result": {"passed": False, "skipped": False}}) == "debug_agent"


def test_passing_test_routes_to_commit():
    assert route_from_test({"test_result": {"passed": True, "skipped": False}}) == "commit_agent"


def test_skipped_test_does_not_enter_debug_loop():
    assert route_from_test({"test_result": {"passed": None, "skipped": True}}) == "commit_agent"


def test_failed_test_debug_goes_directly_to_fix():
    state = {
        "test_result": {"passed": False, "skipped": False},
        "agent_results": {"debug": {"structured": {"error_info": {"has_traceback": False}}}},
    }
    assert route_from_debug(state) == "fix_agent"


def test_original_traceback_debug_behavior_is_preserved():
    state = {
        "agent_results": {"debug": {"structured": {"error_info": {"has_traceback": True}}}},
    }
    assert route_from_debug(state) == "fix_agent"
