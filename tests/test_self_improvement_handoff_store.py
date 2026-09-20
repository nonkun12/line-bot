from core.control_tower import task_hash
from core.multi_agent import AgentRole, AgentTask
from core.self_improvement_handoff import ApprovedImprovementHandoff
from core.self_improvement_handoff_store import ApprovedImprovementHandoffStore


def make_handoff() -> ApprovedImprovementHandoff:
    task = AgentTask(
        task_id="self-improvement:test",
        role=AgentRole.DEBUGGER,
        instruction="Investigate and add a regression test.",
        resources=frozenset({"runtime"}),
        priority=10,
    )
    return ApprovedImprovementHandoff(
        task=task,
        task_hash=task_hash(task) or "",
        allowed_paths=("tests/test_agent_runtime.py",),
    )


def test_store_round_trips_valid_handoff(tmp_path):
    path = tmp_path / "handoffs.jsonl"
    store = ApprovedImprovementHandoffStore(path)

    handoff = make_handoff()
    store.append(handoff)

    loaded = store.load()
    assert loaded == (handoff,)
    assert loaded[0].task_hash == task_hash(loaded[0].task)


def test_store_rejects_tampered_task_hash(tmp_path):
    path = tmp_path / "handoffs.jsonl"
    path.write_text(
        '{"schema_version":1,"task_id":"x","role":"debugger","instruction":"safe","resources":[],"depends_on":[],"priority":0,"task_hash":"tampered","allowed_paths":["tests/test_agent_runtime.py"]}\n',
        encoding="utf-8",
    )

    assert ApprovedImprovementHandoffStore(path).load() == ()


def test_store_rejects_protected_paths(tmp_path):
    path = tmp_path / "handoffs.jsonl"
    handoff = make_handoff()
    store = ApprovedImprovementHandoffStore(path)
    store.append(handoff)

    raw = path.read_text(encoding="utf-8").replace("tests/test_agent_runtime.py", "core/self_improvement_policy.py")
    path.write_text(raw, encoding="utf-8")

    assert store.load() == ()


def test_store_deduplicates_same_handoff(tmp_path):
    path = tmp_path / "handoffs.jsonl"
    store = ApprovedImprovementHandoffStore(path)
    handoff = make_handoff()

    store.append(handoff)
    store.append(handoff)

    assert len(store.load()) == 1


def test_store_rejects_role_escalation(tmp_path):
    path = tmp_path / "handoffs.jsonl"
    task = AgentTask("self-improvement:test", AgentRole.IMPLEMENTER, "unsafe")
    handoff = ApprovedImprovementHandoff(
        task=task,
        task_hash=task_hash(task) or "",
        allowed_paths=("tests/test_agent_runtime.py",),
    )

    try:
        store = ApprovedImprovementHandoffStore(path)
        store.append(handoff)
    except PermissionError:
        pass
    else:
        raise AssertionError("expected PermissionError")
