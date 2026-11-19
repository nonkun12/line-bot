import os
import base64
import requests


OWNER = "nonkun12"
REPO = "line-bot"


def get_github_file(path):

    token = os.getenv("GITHUB_TOKEN")

    url = (
        f"https://api.github.com/"
        f"repos/{OWNER}/{REPO}/contents/{path}"
    )

    headers = {}

    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = requests.get(
        url,
        headers=headers,
        timeout=10
    )

    response.raise_for_status()

    data = response.json()

    content = base64.b64decode(
        data["content"]
    ).decode("utf-8")

    return content
