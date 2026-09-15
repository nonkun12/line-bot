from scripts.universal_app_builder import validate_runtime_compatibility


def test_rejects_removed_flask_before_first_request_api():
    files = [
        {
            "path": "app.py",
            "content": "from flask import Flask\napp = Flask(__name__)\n@app.before_first_request\ndef init_db():\n    pass\n",
        }
    ]
    ok, detail = validate_runtime_compatibility(files)
    assert ok is False
    assert "before_first_request" in detail


def test_accepts_flask_startup_without_removed_api():
    files = [
        {
            "path": "app.py",
            "content": "from flask import Flask\napp = Flask(__name__)\nwith app.app_context():\n    init_db()\n",
        }
    ]
    ok, detail = validate_runtime_compatibility(files)
    assert ok is True
    assert detail == "ok"
