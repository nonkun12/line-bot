"""End-to-end tests against Wrangler's local workerd + D1 runtime.

These tests never bind to a remote database. They create a temporary Wrangler
config and isolated persistence directory, seed only the legacy baseline
schema, apply the repository migrations locally, and exercise the real Worker
HTTP handlers over localhost.
"""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import hashlib
import hmac
import json
import os
import pathlib
import secrets
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
API_TOKEN = "local-integration-api-token"
HMAC_KEY = "local-integration-hmac-key-at-least-32-bytes"
USER_A = "U" + "a" * 32
USER_B = "U" + "b" * 32


def request_json(url: str, method: str = "GET", body=None, owner=None):
    headers = {"Authorization": f"Bearer {API_TOKEN}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if owner:
        headers["X-ORCA-Task-Owner"] = owner
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


@unittest.skipUnless(
    os.environ.get("ORCA_D1_INTEGRATION") == "1",
    "set ORCA_D1_INTEGRATION=1 in the isolated Wrangler CI job",
)
class WorkerD1IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        wrangler = shutil.which("wrangler")
        if not wrangler:
            raise RuntimeError("Wrangler CLI is required for D1 integration tests")
        cls.temp = tempfile.TemporaryDirectory(prefix="orca-d1-it-")
        cls.temp_path = pathlib.Path(cls.temp.name)
        cls.state = cls.temp_path / "d1-state"
        cls.config = ROOT / f".wrangler.integration.{os.getpid()}.toml"
        cls.log_path = cls.temp_path / "wrangler.log"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        config = f'''
name = "orca-d1-integration-test"
main = "src/index.js"
compatibility_date = "2026-11-11"
[vars]
API_TOKEN = "{API_TOKEN}"
ORCA_TASK_APPROVAL_HMAC_KEY = "{HMAC_KEY}"

[[d1_databases]]
binding = "DB"
database_name = "orca-test-ledger-integration"
database_id = "00000000-0000-0000-0000-000000000000"
migrations_dir = "migrations"
'''
        cls.config.write_text(config, encoding="utf-8")
        cls.wrangler = wrangler
        cls._cli(
            "d1", "execute", "orca-test-ledger-integration", "--local",
            "--persist-to", str(cls.state),
            "--command",
            "CREATE TABLE tasks (task_id TEXT PRIMARY KEY, request_text TEXT NOT NULL, "
            "status TEXT NOT NULL, source_event_id TEXT UNIQUE, "
            "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        )
        cls._cli(
            "d1", "migrations", "apply", "orca-test-ledger-integration",
            "--local", "--persist-to", str(cls.state), "--yes",
        )
        cls.log = cls.log_path.open("w+", encoding="utf-8")
        cls.server = subprocess.Popen(
            [wrangler, "dev", "--local", "--ip", "127.0.0.1",
             "--port", str(cls.port), "--config", str(cls.config),
             "--persist-to", str(cls.state)],
            cwd=ROOT, stdout=cls.log, stderr=subprocess.STDOUT, text=True,
        )
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if cls.server.poll() is not None:
                cls._dump_log()
                raise RuntimeError("Wrangler local Worker exited during startup")
            try:
                status, _ = request_json(cls.base + "/control/global-hold")
                if status == 200:
                    return
            except Exception:
                time.sleep(0.25)
        cls._dump_log()
        raise RuntimeError("Wrangler local Worker did not become ready")

    @classmethod
    def tearDownClass(cls):
        server = getattr(cls, "server", None)
        if server and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
        log = getattr(cls, "log", None)
        if log:
            log.close()
        config = getattr(cls, "config", None)
        if config and config.exists():
            config.unlink()
        temp = getattr(cls, "temp", None)
        if temp:
            temp.cleanup()

    @classmethod
    def _dump_log(cls):
        try:
            cls.log.flush()
            print(cls.log_path.read_text(encoding="utf-8")[-12000:])
        except Exception:
            pass

    @classmethod
    def _cli(cls, *args):
        command = [
            cls.wrangler, "--config", str(cls.config), *args,
        ]
        result = subprocess.run(
            command, cwd=ROOT, text=True, capture_output=True, timeout=90,
            env={**os.environ, "NO_D1_WARNING": "true"},
        )
        if result.returncode:
            raise RuntimeError(
                f"Wrangler command failed: {' '.join(command)}\n"
                f"{result.stdout[-5000:]}\n{result.stderr[-5000:]}"
            )
        return result.stdout + result.stderr

    @classmethod
    def sql(cls, statement: str):
        outputs = []
        for sql_statement in (part.strip() for part in statement.split(";")):
            if not sql_statement:
                continue
            outputs.append(cls._cli(
                "d1", "execute", "orca-test-ledger-integration", "--local",
                "--persist-to", str(cls.state), "--command", sql_statement,
            ))
        return "\n".join(outputs)

    def setUp(self):
        self.sql("UPDATE system_controls SET value='off' WHERE control_key='global_hold'")
        self.sql("DELETE FROM notification_outbox; DELETE FROM task_approval_nonces; "
                 "DELETE FROM task_approvals; DELETE FROM tasks;")

    def api(self, path, method="GET", body=None, owner=None):
        return request_json(self.base + path, method, body, owner)

    def create(self, task_id, owner=USER_A, request_text=None, event_id=None):
        request_text = request_text or f"アプリ開発: integration test {task_id}"
        return self.api("/tasks", "POST", {
            "task_id": task_id,
            "request_text": request_text,
            "source_event_id": event_id or f"event-{task_id}",
            "user_id": owner,
        })

    def approve(self, task_id, owner=USER_A, request_text=None):
        request_text = request_text or f"アプリ開発: integration test {task_id}"
        issued = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        expires = issued + dt.timedelta(minutes=10)
        issued_at = issued.isoformat().replace("+00:00", "Z")
        expires_at = expires.isoformat().replace("+00:00", "Z")
        request_hash = hashlib.sha256(request_text.encode()).hexdigest()
        nonce = secrets.token_urlsafe(24)
        canonical = "\n".join([
            "v1", task_id, request_hash, owner, issued_at, expires_at, nonce,
        ])
        signature = hmac.new(
            HMAC_KEY.encode(), canonical.encode(), hashlib.sha256
        ).hexdigest()
        return self.api(f"/tasks/{task_id}/approve", "POST", {
            "approver_user_id": owner,
            "request_hash": request_hash,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "nonce": nonce,
            "signature": signature,
        })

    def test_initial_global_hold_blocks_intake_until_explicit_local_release(self):
        self.sql("UPDATE system_controls SET value='on' WHERE control_key='global_hold'")
        status, state = self.api("/control/global-hold")
        self.assertEqual(status, 200)
        self.assertEqual(state, {"clear": False, "value": "on", "blocked": True})
        status, body = self.create("hold-blocked")
        self.assertEqual(status, 423)
        self.assertIn("global HOLD", body["error"])
        self.sql("UPDATE system_controls SET value='off' WHERE control_key='global_hold'")
        self.assertEqual(self.create("hold-released")[0], 201)

    def test_invalid_or_missing_line_owner_is_rejected_by_real_worker(self):
        status, _ = self.api("/tasks", "POST", {
            "task_id": "no-owner", "request_text": "アプリ開発: no owner",
            "source_event_id": "no-owner-event",
        })
        self.assertEqual(status, 400)
        status, _ = self.api("/tasks", "POST", {
            "task_id": "bad-owner", "request_text": "アプリ開発: bad owner",
            "source_event_id": "bad-owner-event", "user_id": "U123",
        })
        self.assertEqual(status, 400)

    def test_signed_approval_owner_binding_and_duplicate_event_idempotency(self):
        request_text = "アプリ開発: owner-bound test"
        status, created = self.create(
            "owner-bound", request_text=request_text, event_id="same-event"
        )
        self.assertEqual(status, 201)
        status, duplicate = self.create(
            "owner-bound", request_text=request_text, event_id="same-event"
        )
        self.assertEqual(status, 200)
        self.assertTrue(duplicate["duplicate"])
        status, conflict = self.create(
            "other-owner", owner=USER_B, request_text=request_text,
            event_id="same-event",
        )
        self.assertEqual(status, 409)
        status, denied = self.approve("owner-bound", owner=USER_B, request_text=request_text)
        self.assertEqual(status, 403)
        self.assertIn("submitter", denied["error"])
        status, approved = self.approve("owner-bound", request_text=request_text)
        self.assertEqual(status, 200)
        self.assertTrue(approved["approved"])
        self.assertEqual(self.api("/tasks/owner-bound/status", owner=USER_B)[0], 404)
        self.assertEqual(self.api("/tasks/owner-bound/status", owner=USER_A)[0], 200)

    def test_concurrent_claim_has_exactly_one_winner_and_consumes_approval(self):
        request_text = "アプリ開発: concurrent claim test"
        self.assertEqual(self.create("race", request_text=request_text)[0], 201)
        self.assertEqual(self.approve("race", request_text=request_text)[0], 200)
        barrier = threading.Barrier(2)

        def claim():
            barrier.wait(timeout=5)
            return self.api("/tasks/race/claim", "POST", {"lease_seconds": 600})

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: claim(), range(2)))
        self.assertEqual(sorted(status for status, _ in results), [200, 409])
        winning = next(body for status, body in results if status == 200)
        token = winning["claim_token"]
        status, completed = self.api("/tasks/race/complete", "POST", {
            "claim_token": token, "status": "pass", "message": "integration passed",
        })
        self.assertEqual(status, 200)
        self.assertTrue(completed["notification_queued"])
        self.assertEqual(self.api("/tasks/race/complete", "POST", {
            "claim_token": token, "status": "pass",
        })[0], 409)
        self.assertEqual(self.api("/tasks/race/status", owner=USER_A)[1]["task"]["status"], "pass")

    def test_global_hold_blocks_claim_but_allows_completion_evidence_without_outbox(self):
        request_text = "アプリ開発: hold during execution test"
        self.assertEqual(self.create("hold-midflight", request_text=request_text)[0], 201)
        self.assertEqual(self.approve("hold-midflight", request_text=request_text)[0], 200)
        status, claimed = self.api("/tasks/hold-midflight/claim", "POST", {})
        self.assertEqual(status, 200)
        token = claimed["claim_token"]
        self.sql("UPDATE system_controls SET value='on' WHERE control_key='global_hold'")
        status, blocked = self.api("/tasks/hold-midflight/claim", "POST", {})
        self.assertEqual(status, 423)
        status, completed = self.api("/tasks/hold-midflight/complete", "POST", {
            "claim_token": token, "status": "pass",
        })
        self.assertEqual(status, 200)
        self.assertFalse(completed["notification_queued"])
        self.assertEqual(
            self.api("/tasks/hold-midflight/status", owner=USER_A)[1]["task"]["status"],
            "pass",
        )
        outbox = self.sql("SELECT COUNT(*) AS count FROM notification_outbox;")
        self.assertIn('"count": 0', outbox)

    def test_stale_claim_token_cannot_complete_task(self):
        request_text = "アプリ開発: stale token test"
        self.assertEqual(self.create("stale-token", request_text=request_text)[0], 201)
        self.assertEqual(self.approve("stale-token", request_text=request_text)[0], 200)
        status, claimed = self.api("/tasks/stale-token/claim", "POST", {})
        self.assertEqual(status, 200)
        status, denied = self.api("/tasks/stale-token/complete", "POST", {
            "claim_token": "not-the-claim-token", "status": "pass",
        })
        self.assertEqual(status, 409)
        self.assertIn("invalid", denied["error"])
