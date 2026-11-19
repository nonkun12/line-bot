from dotenv import load_dotenv

load_dotenv()

from graph.graph import route_from_debug


def test_debug_request_with_traceback_routes_to_fix_agent():
    state = {
        "agent_results": {
            "debug": {
                "structured": {
                    "error_info": {
                        "has_traceback": True,
                    }
                }
            }
        },
    }

    assert route_from_debug(state) == "fix_agent"


def test_debug_request_without_traceback_routes_to_finalizer():
    state = {
        "agent_results": {
            "debug": {
                "structured": {
                    "error_info": {
                        "has_traceback": False,
                    }
                }
            }
        },
    }

    assert route_from_debug(state) == "finalizer"


def test_debug_request_with_missing_traceback_flag_routes_to_finalizer():
    state = {
        "agent_results": {
            "debug": {
                "structured": {
                    "error_info": {},
                }
            }
        },
    }

    assert route_from_debug(state) == "finalizer"
