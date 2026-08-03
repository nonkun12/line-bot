from fastapi.testclient import TestClient

from mini_debug_app.main import app


client = TestClient(app)


def test_analyze_error():

    response = client.post(
        "/debug/",
        json={
            "error_content": """
Traceback (most recent call last):
ZeroDivisionError: division by zero
"""
        }
    )

    assert response.status_code == 200

    result = response.json()["error_analysis"]

    assert "error_info" in result
    assert "analysis" in result
    assert "fix_suggestion" in result
