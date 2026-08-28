from datetime import datetime, timedelta, timezone

import httpx

from agents.github.intents import is_github_intent  # noqa: F401
from ai_client import generate_secretary_report
from config import AI_REPORT_GITHUB_REPO, GITHUB_TOKEN
from mcp_client import call_mcp_tool


def _parse_mcp_json_list(raw):
    """Parse the MCP list format used by the existing report implementation."""
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        data = __import__("json").loads(raw)
        if isinstance(data, dict):
            content = data.get("result", {}).get("content", [])
            if content and isinstance(content[0], dict):
                text = content[0].get("text", "")
                try:
                    parsed = __import__("json").loads(text)
                    return parsed if isinstance(parsed, list) else []
                except Exception:
                    return []
        return data if isinstance(data, list) else []
    except Exception:
        return []


def fetch_recent_github_commits(hours=24):
    if not AI_REPORT_GITHUB_REPO:
        return []

    url = f"https://api.github.com/repos/{AI_REPORT_GITHUB_REPO}/commits"
    headers = {"Accept": "vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    try:
        since_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        params = {"since": since_time.isoformat()}
        res = httpx.get(url, headers=headers, params=params, timeout=10.0)
        if res.status_code != 200:
            print("AI REPORT: GITHUB API ERROR STATUS:", res.status_code, res.text)
            return []

        commits = []
        for commit in res.json():
            commit_info = commit.get("commit", {})
            message = commit_info.get("message", "").split("\n")[0].strip()
            author_date = commit_info.get("author", {}).get("date", "")
            if message:
                commits.append({"message": message, "date": author_date})

        commits.reverse()
        return commits
    except Exception as exc:
        print("AI REPORT: GITHUB FETCH ERROR:", exc)
        return []


def fetch_ai_secretary_facts(user_id):
    facts = {"commits": [], "memories": [], "reminders": []}
    facts["commits"] = fetch_recent_github_commits(hours=24)

    try:
        memories_raw = call_mcp_tool("get_all_memory", {"user_id": user_id})
        facts["memories"] = _parse_mcp_json_list(memories_raw)
    except Exception as exc:
        print("AI REPORT: GET_ALL_MEMORY ERROR:", exc)

    try:
        reminders_raw = call_mcp_tool("list_reminders", {"user_id": user_id})
        facts["reminders"] = _parse_mcp_json_list(reminders_raw)
    except Exception as exc:
        print("AI REPORT: LIST_REMINDERS ERROR:", exc)

    return facts


def build_ai_secretary_fact_block(facts):
    if facts["commits"]:
        commits_text = "\n".join(f"- {c['message']}" for c in facts["commits"])
    else:
        commits_text = "(昨日24時間以内のコミットは記録されていません)"

    if facts["memories"]:
        memories_text = "\n".join(
            f"- {m.get('key')}: {m.get('value')}" for m in facts["memories"]
        )
    else:
        memories_text = "(保存済みメモはありません)"

    if facts["reminders"]:
        reminders_text = "\n".join(
            f"- {r.get('message')}" for r in facts["reminders"]
        )
    else:
        reminders_text = "(未完了のタスク・リマインダーはありません)"

    return (
        "【昨日の実際のコミット(GitHubより取得・事実)】\n"
        f"{commits_text}\n\n"
        "【保存済みメモ(事実)】\n"
        f"{memories_text}\n\n"
        "【今日の予定・未完了リマインダー(事実)】\n"
        f"{reminders_text}"
    )


def generate_ai_secretary_report(user_id):
    facts = fetch_ai_secretary_facts(user_id)
    fact_block = build_ai_secretary_fact_block(facts)
    now_jst = datetime.now(timezone(timedelta(hours=9)))
    today_str = now_jst.strftime("%Y年%m月%d日")
    prompt_body = f"""
今日は {today_str} です。

以下の【事実データ】のみに基づいて、AI秘書としてユーザーへの「朝の進捗・予定レポート」を作成してください。

{fact_block}

【注意事項】

- 事実データに書かれている内容だけを元に作成してください。
- データにない実績、予定、目標、感想、励まし文を追加してはいけません。
- 「新たなチャンスです」「頑張りましょう」など事実に基づかない文章は禁止です。
- データが空の場合は「記録はありません」とだけ書いてください。
- 丁寧で簡潔なAI秘書口調で出力してください。
- 箇条書きや段落を適度に使って読みやすくしてください。
- 事実データに存在しない「今日の目標」「注目ポイント」「参考資料」などの項目は作成しないでください。
- 情報がない場合は「ありません」と簡潔に記載してください。
- レポートは「昨日の進捗」「保存済みメモ」「今日の予定」の3項目を基本構成にしてください。
"""
    res = generate_secretary_report(prompt_body)
    return res.choices[0].message.content
