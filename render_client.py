from dotenv import load_dotenv
load_dotenv()

import os
import re
import requests
from contextlib import contextmanager


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


def _mcp_render_enabled() -> bool:
    """Enable MCP-on-demand Render control only with an explicit opt-in."""
    return os.getenv("MCP_RENDER_ON_DEMAND", "false").strip().lower() == "true"


def _mcp_service_id() -> str:
    """Return the dedicated MCP Render service ID and reject unsafe values."""
    service_id = os.getenv("MCP_RENDER_SERVICE_ID", "").strip()
    if not service_id:
        raise RuntimeError("MCP_RENDER_SERVICE_ID が設定されていません")
    if service_id == SERVICE_ID:
        raise RuntimeError("MCP_RENDER_SERVICE_ID はLINE-botのService IDと分離してください")
    if re.fullmatch(r"srv-[A-Za-z0-9]+", service_id) is None:
        raise RuntimeError("MCP_RENDER_SERVICE_ID の形式が不正です")
    return service_id


def _render_headers() -> dict:
    api_key = os.getenv("RENDER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("RENDER_API_KEY が設定されていません")
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def get_service(service_id: str) -> dict:
    """Read one Render service state without performing a mutation."""
    response = requests.get(
        f"https://api.render.com/v1/services/{service_id}",
        headers=_render_headers(),
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("Render service response is invalid")
    return data


def resume_service(service_id: str) -> dict:
    """Resume exactly one approved Render service."""
    response = requests.post(
        f"https://api.render.com/v1/services/{service_id}/resume",
        headers=_render_headers(),
        timeout=15,
    )
    response.raise_for_status()
    data = response.json() if response.content else {}
    return data if isinstance(data, dict) else {}


def suspend_service(service_id: str) -> dict:
    """Suspend exactly one approved Render service."""
    response = requests.post(
        f"https://api.render.com/v1/services/{service_id}/suspend",
        headers=_render_headers(),
        timeout=15,
    )
    response.raise_for_status()
    data = response.json() if response.content else {}
    return data if isinstance(data, dict) else {}


def wait_for_service_running(
    service_id: str,
    *,
    timeout_sec: float = 35.0,
    poll_sec: float = 2.0,
) -> dict:
    """Wait until Render reports the service as not suspended."""
    import time

    deadline = time.monotonic() + max(0.0, timeout_sec)
    last = get_service(service_id)
    while last.get("suspended") != "not_suspended":
        if time.monotonic() >= deadline:
            raise RuntimeError("MCP Render service did not become ready before timeout")
        time.sleep(max(0.1, poll_sec))
        last = get_service(service_id)
    return last


@contextmanager
def mcp_service_session():
    """
    Start the dedicated MCP Render service only when explicitly enabled.

    - Disabled: preserve the existing MCP behavior exactly.
    - Suspended at entry: resume, wait for not_suspended, then suspend on exit.
    - Already running at entry: do not suspend it on exit.
    - Any startup/configuration failure: fail closed before the MCP request.
    """
    if not _mcp_render_enabled():
        yield
        return

    service_id = _mcp_service_id()
    current = get_service(service_id)
    was_suspended = current.get("suspended") == "suspended"
    resumed_by_us = False

    try:
        if was_suspended:
            resume_service(service_id)
            resumed_by_us = True
            wait_for_service_running(service_id)

        yield
    finally:
        if resumed_by_us:
            try:
                suspend_service(service_id)
            except Exception:
                # Never hide the MCP operation result because cleanup failed;
                # leave an explicit operational log for follow-up.
                print("MCP Render service suspend failed", flush=True)
