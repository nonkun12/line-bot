from core.management_contract import ManagementRequest, Specialist
from core.management_router import route
from graph.supervisor import classify_intent, supervisor_node


def test_management_router_recognizes_job_seeking():
    assert route(ManagementRequest("u", "転職の求人を探したい")).specialist is Specialist.JOBS


def test_supervisor_routes_job_seeking_to_agent():
    assert classify_intent("面接対策をしたい") == "jobs"
    state = supervisor_node({"user_id": "u", "raw_message": "面接対策をしたい"})
    assert state["next_agent"] == "job_seeking"
