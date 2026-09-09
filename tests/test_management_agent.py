from agents.management.node import assign_agent, management_agent_node


def test_assign_agent_routes_refactoring_requests():
    assert assign_agent("このコードをリファクタリングして") == "refactoring_agent"
    assert assign_agent("refactor duplicated validation") == "refactoring_agent"


def test_assign_agent_routes_feature_work_to_development():
    assert assign_agent("LINEの新機能を追加して") == "development_agent"


def test_management_node_records_assignment():
    state = {"raw_message": "可読性を改善して", "agent_results": {}}
    result = management_agent_node(state)
    assert result["next_agent"] == "refactoring_agent"
    assert result["management_plan"]["assigned_agent"] == "refactoring_agent"
    assert result["agent_results"]["management"]["assigned_agent"] == "refactoring_agent"
