# このファイルは本番LangGraph (graph.graph.graph) 経由の手動確認用フォームUIです。
# mini_debug_app/main.py + service.py (agents/debug/collector・analyzer・fixerを
# 直接呼び出す独立DEBUG TOOL) とは別のエントリーポイントであり、今回のDEBUG TOOL
# 完成対象ではありません。現状維持のため、ロジックには手を入れていません。

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse
from graph.graph import graph

app = FastAPI(
    title="AI Debug Agent Mini App"
)


@app.get("/", response_class=HTMLResponse)
def index():
    return """
    <html>
    <head>
        <title>AI Debug Agent</title>
    </head>
    <body>
        <h1>AI Debug Agent</h1>

        <form method="post">
            <textarea
                name="error"
                rows="15"
                cols="80"
                placeholder="Tracebackを入力してください">
            </textarea>
            <br>
            <button type="submit">
                Analyze
            </button>
        </form>

    </body>
    </html>
    """


@app.post("/", response_class=HTMLResponse)
def analyze(error: str = Form(...)):

    result = None

    for chunk in graph.stream(
        {
            "raw_message": f"debug {error}",
            "user_id": "mini-debug-user"
        }
    ):
        if "finalizer" in chunk:
            result = chunk["finalizer"].get(
                "final_reply",
                ""
            )

    return f"""
    <html>
    <body>

    <h1>AI Debug Result</h1>

    <pre>
    {result}
    </pre>

    <a href="/">
    Back
    </a>

    </body>
    </html>
    """
