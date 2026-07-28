import os
import requests


SERVICE_ID = "srv-d93loivlk1mc739gssvg"
OWNER_ID = "tea-d8v5glvavr4c73812ii0"


def get_render_logs():

    api_key = os.getenv("RENDER_API_KEY")

    if not api_key:
        return "RENDER_API_KEY が設定されていません"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json"
    }

    url = "https://api.render.com/v1/logs"

    params = {
        "resource": SERVICE_ID,
        "ownerId": OWNER_ID,
        "limit": 20,
        "type": "app"
    }

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=10
    )

    response.raise_for_status()

    data = response.json()

    logs = []

    for item in data.get("logs", []):
        logs.append(
            item.get("message", "")
        )

    return "\n".join(logs)
