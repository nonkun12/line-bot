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


def trigger_deploy(clear_cache: bool = False) -> dict:
    """
    Render上のサービスに対して新規デプロイを開始する。

    安全設計:
    - RENDER_API_KEYが無い場合は何もせずエラー内容を返す(誤動作防止)
    - 例外はここで吸収し、呼び出し側には成功/失敗を表す辞書のみを返す

    Args:
        clear_cache: Trueの場合ビルドキャッシュをクリアしてデプロイする

    Returns:
        dict:
            triggered: bool             デプロイ開始に成功したか
            deploy_id: Optional[str]    RenderのデプロイID
            status: Optional[str]       Render側のステータス
            error: Optional[str]        失敗理由(成功時はNone)
    """

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

    payload = {
        "clearCache": "clear" if clear_cache else "do_not_clear",
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=15,
        )

        response.raise_for_status()

        data = response.json()

        return {
            "triggered": True,
            "deploy_id": data.get("id"),
            "status": data.get("status"),
            "error": None,
        }

    except Exception as e:
        return {
            "triggered": False,
            "deploy_id": None,
            "status": None,
            "error": str(e),
        }
