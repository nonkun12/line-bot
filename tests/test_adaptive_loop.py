from core.adaptive_loop import explicit_target, route_task

def test_explicit_target_is_detected():
    files = {"core/foo.py", "tests/test_foo.py"}
    assert explicit_target("fix core/foo.py", files) == "core/foo.py"

def test_explicit_safe_target_skips_manager():
    route = route_task("fix core/foo.py", {"core/foo.py"})
    assert route.manager_required is False
    assert route.idea_required is False

def test_ambiguous_target_keeps_manager():
    route = route_task("fix core/foo.py and tests/test_foo.py", {"core/foo.py", "tests/test_foo.py"})
    assert route.manager_required is True

def test_protected_target_keeps_manager():
    route = route_task("change Dockerfile", {"Dockerfile"})
    assert route.manager_required is True
