from dotenv import load_dotenv

load_dotenv()

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
        "Accept": "application/json",
    }
    url = "https://api.render.com/v1/logs"
    params = {
        "resource": SERVICE_ID,
        "ownerId": OWNER_ID,
        "limit": 20,
        "type": "app",
    }
    response = requests.get(url, headers=headers, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()
    return "\n".join(item.get("message", "") for item in data.get("logs", []))


def trigger_deploy(clear_cache: bool = False) -> dict:
    api_key = os.getenv("RENDER_API_KEY")
    if not api_key:
        return {
            "triggered": False,
            "deploy_id": None,
            "status": None,
            "error": "RENDER_API_KEY が設定されていません",
        }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    url = f"https://api.render.com/v1/services/{SERVICE_ID}/deploys"
    payload = {"clearCache": "clear" if clear_cache else "do_not_clear"}
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        return {
            "triggered": True,
            "deploy_id": data.get("id"),
            "status": data.get("status"),
            "error": None,
        }
    except Exception as exc:
        return {
            "triggered": False,
            "deploy_id": None,
            "status": None,
            "error": str(exc),
        }
