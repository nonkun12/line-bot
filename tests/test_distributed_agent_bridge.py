from core.distributed_agent_bridge import build_agent_registry
from core.multi_agent import AgentRole


class FakeAgent:
    name = "ai_news"
    enabled = True

    def can_handle(self, request):
        return request.message == "AI NEWSをテスト"

    def handle(self, request):
        class Response:
            text = "news-ready"
        return Response()


def test_bridge_registers_explicit_news_executor():
    class Registry:
        def get(self, name):
            if name == "ai_news":
                return FakeAgent()
            return None

    executors = build_agent_registry(Registry()).build()
    assert AgentRole.NEWS in executors
    result = executors[AgentRole.NEWS].execute(
        __import__("core.multi_agent", fromlist=["AgentTask"]).AgentTask(
            task_id="req-1",
            role=AgentRole.NEWS,
            instruction="AI NEWSをテスト",
        )
    )
    assert result.success is True
    assert result.summary == "news-ready"
