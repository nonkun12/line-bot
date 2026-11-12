export { OrcaWriteBroker } from "./write-broker.mjs";

const json = (value, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });

function safeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

async function authorized(request, env) {
  const supplied = request.headers.get("authorization") || "";
  const expected = `Bearer ${env.API_TOKEN || ""}`;
  return Boolean(env.API_TOKEN) && safeEqual(supplied, expected);
}

// The serialized Durable Object is authoritative. Missing binding/state or
// any transport error is HOLD=ON; D1 is only a compatibility mirror.
async function brokerStub(env) {
  if (!env.ORCA_WRITE_BROKER) throw new Error("ORCA_WRITE_BROKER binding unavailable");
  const id = env.ORCA_WRITE_BROKER.idFromName("nonkun12/line-bot");
  return env.ORCA_WRITE_BROKER.get(id);
}

async function brokerRequest(env, path, method = "GET", body = null) {
  const stub = await brokerStub(env);
  return stub.fetch(`https://orca-write-broker.internal${path}`, {
    method,
    headers: { "content-type": "application/json" },
    body: body === null ? undefined : JSON.stringify(body),
  });
}

async function globalHoldState(env) {
  try {
    const response = await brokerRequest(env, "/hold");
    if (!response.ok) return { clear: false, value: null };
    const state = await response.json();
    return { clear: state.clear === true && state.value === "off" && state.blocked === false,
      value: state.value ?? null, unresolved_operations: state.unresolved_operations ?? 0 };
  } catch {
    return { clear: false, value: null };
  }
}

function taskIdFrom(path) {
  const match = path.match(/^\/tasks\/([A-Za-z0-9_-]{1,100})(?:\/(approve|claim|complete|status))?$/);
  return match ? { id: match[1], action: match[2] || null } : null;
}

async function readJson(request) {
  try {
    const value = await request.json();
    return value && typeof value === "object" && !Array.isArray(value) ? value : null;
  } catch {
    return null;
  }
}

function isValidLineUserId(value) {
  return typeof value === "string" && /^U[0-9a-fA-F]{32}$/.test(value);
}

function distributedLoopMaxTasks(value) {
  if (typeof value !== "string") return null;
  const command = value.normalize("NFKC").replace(/[\u200b-\u200d\ufeff]/g, "").replace(/\s+/g, "");
  const starts = new Set([
    "分散ループ開始", "分散Loop開始", "分散AIループ開始", "分散AILoop開始",
    "分散AI回して", "distributedloopstart", "分散ループを起動",
    "分散Loopを起動", "分散AIループを起動", "分散AILoopを起動",
  ]);
  const naturalFourTaskCommands = new Set([
    "分散Loopを起動。4タスクまで安全に実行し、各タスクをSafetyGate付きで確認。問題があれば即停止し、最後にTaskID/PASS・FAIL/SHA/変更ファイル/成果を報告してください。",
    "分散Loopを起動。4タスクまで安全に実行し、各タスクをSafetyGate付きで確認。問題があれば即停止し、最後にTaskID/PASS・FAIL/SHA/変更ファイル/成果を報告してください",
    "分散Loopを起動。4タスクまで安全確認付きで実行し、各タスクをSafetyGate付きで確認。問題があれば即停止し、最後にTaskID/PASS・FAIL/SHA/変更ファイル/成果を報告してください。",
    "分散Loopを起動。4タスクまで安全確認付きで実行し、各タスクをSafetyGate付きで確認。問題があれば即停止し、最後にTaskID/PASS・FAIL/SHA/変更ファイル/成果を報告してください",
  ]);
  if (naturalFourTaskCommands.has(command)) return 4;
  if (starts.has(command)) return command.includes("起動") ? 4 : 1;
  const match = command.match(/^(?:分散ループ|分散Loop|分散AIループ|分散AILoop)を([1-4])回、?安全確認付きで実行(?:してください)?$/);
  return match ? Number(match[1]) : null;
}

async function createTask(request, env) {
  if (!(await globalHoldState(env)).clear) return json({ error: "global HOLD is active or unavailable" }, 423);
  const body = await readJson(request);
  const taskType = body?.task_type ?? "app_development";
  const maxTasks = body?.max_tasks ?? 1;
  const validTaskType = taskType === "app_development" || taskType === "distributed_loop";
  const validTaskKind = typeof body?.request_text === "string" && (taskType === "app_development"
    ? maxTasks === 1 && (body.request_text.startsWith("アプリ開発:") || body.request_text.startsWith("アプリ開発："))
    : Number.isInteger(maxTasks) && distributedLoopMaxTasks(body.request_text) === maxTasks);
  if (!body || typeof body.task_id !== "string" ||
      !/^[A-Za-z0-9_-]{1,100}$/.test(body.task_id) ||
      typeof body.request_text !== "string" ||
      !body.request_text.trim() || new TextEncoder().encode(body.request_text).length > 6000 ||
      typeof body.source_event_id !== "string" || !body.source_event_id.trim() ||
      !isValidLineUserId(body.user_id) || !validTaskType || !validTaskKind) {
    return json({ error: "invalid typed task payload, command, bound, or verified LINE owner is missing" }, 400);
  }
  const userId = body.user_id;
  try {
    const inserted = await env.DB.prepare(
      `INSERT INTO tasks (task_id, request_text, status, source_event_id, user_id, task_type, max_tasks)
       SELECT ?, ?, 'queued', ?, ?, ?, ?
        WHERE EXISTS (SELECT 1 FROM system_controls WHERE control_key = 'global_hold' AND value = 'off')`
    ).bind(body.task_id, body.request_text, body.source_event_id, userId, taskType, maxTasks).run();
    if (!inserted.meta?.changes) return json({ error: "global HOLD is active or unavailable" }, 423);
    return json({ task: { task_id: body.task_id, request_text: body.request_text, status: "queued", task_type: taskType, max_tasks: maxTasks } }, 201);
  } catch (error) {
    if (body.source_event_id) {
      const existing = await env.DB.prepare(
        "SELECT task_id, request_text, status, user_id, task_type, max_tasks FROM tasks WHERE source_event_id = ?"
      ).bind(body.source_event_id).first();
      if (existing && existing.user_id === userId && existing.request_text === body.request_text &&
          existing.task_type === taskType && existing.max_tasks === maxTasks) {
        const { user_id: _owner, ...safeTask } = existing;
        return json({ task: safeTask, duplicate: true }, 200);
      }
      if (existing) return json({ error: "source event ID conflicts with an existing task" }, 409);
    }
    if (String(error).includes("UNIQUE")) return json({ error: "task already exists" }, 409);
    throw error;
  }
}

async function sha256Hex(value) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function hmacHex(secret, value) {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const signature = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(value));
  return [...new Uint8Array(signature)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function approveTask(id, request, env) {
  if (!(await globalHoldState(env)).clear) return json({ error: "global HOLD is active or unavailable" }, 423);
  const body = await readJson(request);
  const userId = typeof body?.approver_user_id === "string" ? body.approver_user_id : "";
  const requestHash = typeof body?.request_hash === "string" ? body.request_hash : "";
  const issuedAt = typeof body?.issued_at === "string" ? body.issued_at : "";
  const expiresAt = typeof body?.expires_at === "string" ? body.expires_at : "";
  const signature = typeof body?.signature === "string" ? body.signature : "";
  const nonce = typeof body?.nonce === "string" ? body.nonce : "";
  const requestedType = body?.task_type ?? "app_development";
  const requestedMaxTasks = body?.max_tasks ?? 1;
  const approvalKey = env.ORCA_TASK_APPROVAL_HMAC_KEY || "";
  if (new TextEncoder().encode(approvalKey).length < 32 ||
      !/^U[0-9a-fA-F]{32}$/.test(userId) || !/^[0-9a-f]{64}$/.test(requestHash) ||
      !/^[0-9a-f]{64}$/.test(signature) || !/^[A-Za-z0-9_-]{32}$/.test(nonce)) return json({ error: "approval is not authorized" }, 403);
  const issued = Date.parse(issuedAt), expires = Date.parse(expiresAt), now = Date.now();
  if (!Number.isFinite(issued) || !Number.isFinite(expires) || issued > now + 60000 ||
      issued < now - 5 * 60000 || expires <= issued || expires <= now || expires > issued + 60 * 60000)
    return json({ error: "approval timestamp is invalid or expired" }, 400);
  const task = await env.DB.prepare("SELECT task_id, request_text, status, lease_until, user_id, task_type, max_tasks FROM tasks WHERE task_id = ?").bind(id).first();
  if (!task || task.task_type !== requestedType || task.max_tasks !== requestedMaxTasks)
    return json({ error: "approval task type or task bound does not match the stored task" }, 409);
  const canonical = task.task_type === "distributed_loop"
    ? ["v2", id, requestHash, userId, task.task_type, String(task.max_tasks), issuedAt, expiresAt, nonce].join("\n")
    : ["v1", id, requestHash, userId, issuedAt, expiresAt, nonce].join("\n");
  if (!safeEqual(signature, await hmacHex(approvalKey, canonical)))
    return json({ error: "invalid approval signature" }, 403);
  const expiredRunning = task?.status === "running" && task.lease_until && Date.parse(task.lease_until) <= Date.now();
  if (!task || (task.status !== "queued" && !expiredRunning))
    return json({ error: "task is not awaiting approval or its prior lease is still active" }, 409);
  if (task.task_type === "app_development" &&
      (typeof task.request_text !== "string" ||
       !task.request_text.startsWith("アプリ開発:") && !task.request_text.startsWith("アプリ開発：")))
    return json({ error: "only explicit app-development tasks can be approved" }, 400);
  if (task.task_type === "distributed_loop" &&
      distributedLoopMaxTasks(task.request_text) !== task.max_tasks)
    return json({ error: "distributed-loop command or bound is invalid" }, 400);
  if (task.user_id !== userId) return json({ error: "only the verified task submitter may approve it" }, 403);
  if (!safeEqual(await sha256Hex(task.request_text), requestHash))
    return json({ error: "task content changed; approval rejected" }, 409);
  const approvalId = crypto.randomUUID();
  // The nonce ledger is append-only. D1 batch is transactional: a duplicate
  // nonce aborts the batch, while a stale-but-new nonce is retained in history
  // even when it cannot replace the current approval.
  let results;
  try {
    results = await env.DB.batch([
      env.DB.prepare(
        "INSERT INTO task_approval_nonces " +
        "(approval_nonce, task_id, approval_id, request_hash, approver_user_id, issued_at, expires_at) " +
        "VALUES (?, ?, ?, ?, ?, ?, ?)"
      ).bind(nonce, id, approvalId, requestHash, userId, issuedAt, expiresAt),
      env.DB.prepare(
        "INSERT INTO task_approvals " +
        "(task_id, approval_id, approval_nonce, request_hash, approver_user_id, issued_at, expires_at, status, task_type, max_tasks) " +
        "SELECT ?, ?, ?, ?, ?, ?, ?, 'approved', task_type, max_tasks FROM tasks " +
        "WHERE task_id = ? AND (status = 'queued' OR " +
        "(status = 'running' AND lease_until IS NOT NULL AND datetime(lease_until) <= CURRENT_TIMESTAMP)) " +
        "AND EXISTS (SELECT 1 FROM system_controls WHERE control_key = 'global_hold' AND value = 'off') " +
        "ON CONFLICT(task_id) DO UPDATE SET " +
        "approval_id=excluded.approval_id, approval_nonce=excluded.approval_nonce, " +
        "request_hash=excluded.request_hash, approver_user_id=excluded.approver_user_id, " +
        "issued_at=excluded.issued_at, expires_at=excluded.expires_at, status='approved', " +
        "task_type=excluded.task_type, max_tasks=excluded.max_tasks " +
        "WHERE julianday(excluded.issued_at) > julianday(task_approvals.issued_at) " +
        "AND (task_approvals.status = 'approved' OR " +
        "(task_approvals.status = 'consumed' AND EXISTS (" +
        "SELECT 1 FROM tasks WHERE task_id = excluded.task_id AND status = 'running' " +
        "AND lease_until IS NOT NULL AND datetime(lease_until) <= CURRENT_TIMESTAMP)))"
      ).bind(id, approvalId, nonce, requestHash, userId, issuedAt, expiresAt, id),
    ]);
  } catch (error) {
    // Only uniqueness conflicts are treated as replay; surface operational
    // failures so they are not silently mislabeled as an invalid approval.
    if (String(error).includes("UNIQUE constraint failed")) {
      return json({ error: "approval nonce has already been used" }, 409);
    }
    throw error;
  }
  if (!results[0]?.meta?.changes) return json({ error: "approval nonce has already been used" }, 409);
  if (!results[1]?.meta?.changes)
    return json({ error: "approval is stale or the previous lease is still active" }, 409);
  return json({ task_id: id, approved: true, expires_at: expiresAt });
}

async function claimTask(id, request, env) {
  if (!(await globalHoldState(env)).clear) return json({ error: "global HOLD is active or unavailable" }, 423);
  const body = await readJson(request);
  const leaseSeconds = Number.isInteger(body?.lease_seconds)
    ? Math.min(1800, Math.max(60, body.lease_seconds)) : 900;
  const token = crypto.randomUUID();
  const leaseUntil = new Date(Date.now() + leaseSeconds * 1000).toISOString();
  const approval = await env.DB.prepare(
    "SELECT approval_id, request_hash, expires_at, status, task_type, max_tasks FROM task_approvals WHERE task_id = ?"
  ).bind(id).first();
  if (!approval || approval.status !== "approved" || Date.parse(approval.expires_at) <= Date.now())
    return json({ error: "a valid task-bound LINE approval is required" }, 403);
  const task = await env.DB.prepare("SELECT request_text, task_type, max_tasks FROM tasks WHERE task_id = ?").bind(id).first();
  if (!task || task.task_type !== approval.task_type || task.max_tasks !== approval.max_tasks ||
      !safeEqual(await sha256Hex(task.request_text), approval.request_hash))
    return json({ error: "approved task fingerprint or type no longer matches" }, 409);
  // The generic CPU worker only implements app-development tasks. Keep loop
  // tasks unclaimable until a dedicated distributed-loop handler is reviewed.
  if (task.task_type !== "app_development")
    return json({ error: "distributed-loop execution handler is not enabled" }, 409);
  const results = await env.DB.batch([
    env.DB.prepare(
      `UPDATE tasks SET status = 'running', lease_token = ?, lease_until = ?,
          attempt_count = COALESCE(attempt_count, 0) + 1, updated_at = CURRENT_TIMESTAMP
        WHERE task_id = ? AND (status = 'queued' OR (status = 'running' AND datetime(lease_until) <= CURRENT_TIMESTAMP))
          AND EXISTS (SELECT 1 FROM task_approvals WHERE task_id = ? AND approval_id = ?
                      AND status = 'approved' AND datetime(expires_at) > CURRENT_TIMESTAMP)
          AND EXISTS (SELECT 1 FROM system_controls WHERE control_key = 'global_hold' AND value = 'off')
        RETURNING task_id, request_text, status, lease_until, attempt_count`
    ).bind(token, leaseUntil, id, id, approval.approval_id),
    env.DB.prepare(
      `UPDATE task_approvals SET status = 'consumed' WHERE task_id = ? AND approval_id = ? AND status = 'approved'
        AND EXISTS (SELECT 1 FROM tasks WHERE task_id = ? AND status = 'running' AND lease_token = ?)`
    ).bind(id, approval.approval_id, id, token),
  ]);
  const row = results[0]?.results?.[0];
  if (!results[0]?.meta?.changes || !results[1]?.meta?.changes)
    return json({ error: "task approval is missing, expired, consumed, or task is already claimed" }, 409);
  return json({ task: row, claim_token: token });
}

async function completeTask(id, request, env) {
  const body = await readJson(request);
  const token = typeof body?.claim_token === "string" ? body.claim_token : "";
  const status = body?.status;
  if (!token || !["pass", "fail", "blocked"].includes(status)) {
    return json({ error: "claim_token and terminal status are required" }, 400);
  }
  const message = typeof body.message === "string" && body.message.trim()
    ? body.message.trim().slice(0, 1800)
    : `ORCA task ${id}: ${status}`;
  const outboxId = crypto.randomUUID();
  // D1 batch is transactional. First consume the lease into a terminal
  // state, then create the outbox row only if that update actually succeeded.
  // The claim token is cleared only after the outbox INSERT in this same batch.
  const results = await env.DB.batch([
    env.DB.prepare(
      `UPDATE tasks
          SET status = ?, updated_at = CURRENT_TIMESTAMP
        WHERE task_id = ? AND status = 'running' AND lease_token = ?
          AND datetime(lease_until) > CURRENT_TIMESTAMP`
    ).bind(status, id, token),
    env.DB.prepare(
      `INSERT INTO notification_outbox
         (outbox_id, task_id, user_id, message)
       SELECT ?, task_id, user_id, ?
         FROM tasks
        WHERE task_id = ? AND status = ? AND lease_token = ?
          AND user_id IS NOT NULL
          AND EXISTS (SELECT 1 FROM system_controls WHERE control_key = 'global_hold' AND value = 'off')`
    ).bind(outboxId, message, id, status, token),
    env.DB.prepare(
      `UPDATE tasks SET lease_token = NULL, lease_until = NULL
        WHERE task_id = ? AND status = ? AND lease_token = ?`
    ).bind(id, status, token),
  ]);
  if (!results[0]?.meta?.changes) return json({ error: "claim is invalid, expired, or already completed" }, 409);
  return json({
    task_id: id,
    status,
    notification_queued: Boolean(results[1]?.meta?.changes),
  });
}

async function getTask(id, env) {
  const task = await env.DB.prepare(
    "SELECT task_id, request_text, status, task_type, max_tasks, created_at, updated_at FROM tasks WHERE task_id = ?"
  ).bind(id).first();
  return task ? json({ task }) : json({ error: "not found" }, 404);
}

async function getTaskStatus(id, request, env) {
  // Status lookup is intentionally scoped to the verified LINE submitter.
  // Return the same 404 for missing tasks and ownership mismatches.
  const userId = request.headers.get("x-orca-task-owner") || "";
  if (!/^U[0-9a-fA-F]{32}$/.test(userId)) return json({ error: "not found" }, 404);
  const task = await env.DB.prepare(
    "SELECT task_id, status, created_at, updated_at FROM tasks WHERE task_id = ? AND user_id = ?"
  ).bind(id, userId).first();
  return task ? json({ task }) : json({ error: "not found" }, 404);
}

async function listTasks(url, env) {
  if (!(await globalHoldState(env)).clear) return json({ tasks: [], blocked: true, reason: "global_hold" });
  const limit = Math.min(100, Math.max(1, Number.parseInt(url.searchParams.get("limit") || "20", 10) || 20));
  const status = url.searchParams.get("status");
  const approvedOnly = url.searchParams.get("approved") === "true";
  const requestedType = url.searchParams.get("task_type") || "app_development";
  if (!["app_development", "distributed_loop"].includes(requestedType))
    return json({ tasks: [], blocked: true, reason: "invalid_task_type" }, 400);
  const typeFilter = " AND tasks.task_type = ?";
  const approvalFilter = approvedOnly
    ? " AND EXISTS (SELECT 1 FROM task_approvals a WHERE a.task_id = tasks.task_id AND a.status = 'approved' AND datetime(a.expires_at) > CURRENT_TIMESTAMP)"
    : "";
  const claimableFilter = approvedOnly
    ? " AND (tasks.status = 'queued' OR (tasks.status = 'running' AND tasks.lease_until IS NOT NULL AND datetime(tasks.lease_until) <= CURRENT_TIMESTAMP))"
    : "";
  const order = approvedOnly ? "ASC" : "DESC";
  const select = "SELECT task_id, request_text, status, created_at, updated_at, " +
    "EXISTS (SELECT 1 FROM task_approvals a WHERE a.task_id = tasks.task_id AND a.status = 'approved' " +
    "AND datetime(a.expires_at) > CURRENT_TIMESTAMP) AS approved FROM tasks";
  const rows = status
    ? await env.DB.prepare(select + " WHERE status = ?" + typeFilter + approvalFilter + claimableFilter +
        " ORDER BY created_at " + order + " LIMIT ?").bind(status, requestedType, limit).all()
    : await env.DB.prepare(select + " WHERE 1=1" + typeFilter + approvalFilter + claimableFilter +
        " ORDER BY created_at " + order + " LIMIT ?").bind(requestedType, limit).all();
  return json({ tasks: rows.results || [] });
}


async function dispatchOutbox(env) {
  if (!env.LINE_CHANNEL_ACCESS_TOKEN || !(await globalHoldState(env)).clear) return;
  const due = await env.DB.prepare(
    `SELECT outbox_id
       FROM notification_outbox
      WHERE status = 'pending' AND next_attempt_at <= CURRENT_TIMESTAMP
        AND (dispatch_until IS NULL OR datetime(dispatch_until) <= CURRENT_TIMESTAMP)
        AND EXISTS (SELECT 1 FROM system_controls WHERE control_key = 'global_hold' AND value = 'off')
      ORDER BY created_at LIMIT 10`
  ).all();
  for (const candidate of due.results || []) {
    const dispatchToken = crypto.randomUUID();
    const claimed = await env.DB.prepare(
      `UPDATE notification_outbox
          SET dispatch_token = ?, dispatch_until = datetime('now', '+5 minutes')
        WHERE outbox_id = ? AND status = 'pending'
          AND next_attempt_at <= CURRENT_TIMESTAMP
          AND (dispatch_until IS NULL OR datetime(dispatch_until) <= CURRENT_TIMESTAMP)
          AND EXISTS (SELECT 1 FROM system_controls WHERE control_key = 'global_hold' AND value = 'off')
        RETURNING outbox_id, user_id, message, attempts`
    ).bind(dispatchToken, candidate.outbox_id).first();
    if (!claimed) continue;

    // Recheck immediately before the external side effect. D1 cannot make a
    // database state transition atomic with LINE's remote API call.
    if (!(await globalHoldState(env)).clear) {
      await env.DB.prepare(
        "UPDATE notification_outbox SET dispatch_token = NULL, dispatch_until = NULL WHERE outbox_id = ? AND status = 'pending' AND dispatch_token = ?"
      ).bind(claimed.outbox_id, dispatchToken).run();
      return;
    }
    let response;
    try {
      response = await fetch("https://api.line.me/v2/bot/message/push", {
        method: "POST",
        headers: {
          authorization: `Bearer ${env.LINE_CHANNEL_ACCESS_TOKEN}`,
          "content-type": "application/json",
        },
        body: JSON.stringify({
          to: claimed.user_id,
          messages: [{ type: "text", text: claimed.message }],
        }),
        // Bound network time so a stalled LINE API cannot consume the worker invocation.
        signal: AbortSignal.timeout(10_000),
      });
    } catch {
      response = null;
    }
    if (response?.ok) {
      await env.DB.prepare(
        `UPDATE notification_outbox
            SET status = 'sent', sent_at = CURRENT_TIMESTAMP,
                dispatch_token = NULL, dispatch_until = NULL
          WHERE outbox_id = ? AND status = 'pending' AND dispatch_token = ?`
      ).bind(claimed.outbox_id, dispatchToken).run();
      continue;
    }
    const attempts = claimed.attempts + 1;
    const dead = attempts >= 8;
    const delay = Math.min(3600, 30 * (2 ** Math.min(attempts, 7)));
    await env.DB.prepare(
      `UPDATE notification_outbox
          SET attempts = ?, status = ?, last_error_code = ?,
              next_attempt_at = datetime('now', ?),
              dispatch_token = NULL, dispatch_until = NULL
        WHERE outbox_id = ? AND status = 'pending' AND dispatch_token = ?`
    ).bind(attempts, dead ? "dead" : "pending",
      response ? `LINE_HTTP_${response.status}` : "NETWORK_ERROR",
      `+${delay} seconds`, claimed.outbox_id, dispatchToken).run();
  }
}

export default {
  async fetch(request, env) {
    if (!await authorized(request, env)) return json({ error: "unauthorized" }, 401);
    const url = new URL(request.url);
    if (url.pathname === "/control/global-hold" && request.method === "GET") {
      const state = await globalHoldState(env);
      return json({ clear: state.clear, value: state.value, blocked: !state.clear,
        unresolved_operations: state.unresolved_operations ?? 0 }, 200);
    }
    if (url.pathname === "/control/global-hold" && request.method === "POST") {
      const supplied = request.headers.get("x-orca-hold-operator") || "";
      if (!env.ORCA_HOLD_OPERATOR_TOKEN || !safeEqual(supplied, env.ORCA_HOLD_OPERATOR_TOKEN)) {
        return json({ error: "separate human operator credential required" }, 403);
      }
      const body = await readJson(request);
      if (!body || !["on", "off"].includes(body.value)) return json({ error: "value must be on or off" }, 400);
      if (typeof body.operator_id !== "string" || !body.operator_id.trim() ||
          typeof body.reason !== "string" || body.reason.trim().length < 8) {
        return json({ error: "operator_id and reason are required for every HOLD transition" }, 400);
      }
      try {
        const result = await brokerRequest(env, "/hold", "PUT", body);
        const resultBody = await result.json().catch(() => ({}));
        return json(resultBody, result.status);
      } catch {
        return json({ error: "HOLD transition failed; broker state remains authoritative" }, 503);
      }
      }
    if (url.pathname === "/control/global-hold/reconcile" && request.method === "POST") {
      const supplied = request.headers.get("x-orca-hold-operator") || "";
      if (!env.ORCA_HOLD_OPERATOR_TOKEN || !safeEqual(supplied, env.ORCA_HOLD_OPERATOR_TOKEN)) {
        return json({ error: "separate human operator credential required" }, 403);
      }
      try {
        const body = await request.text();
        if (body.length > 5000) return json({ error: "reconciliation payload too large" }, 413);
        const response = await (await brokerStub(env)).fetch("https://orca-write-broker.internal/operations/reconcile", {
          method: "POST", headers: { "content-type": "application/json" }, body,
        });
        return new Response(await response.text(), { status: response.status,
          headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });
      } catch {
        return json({ error: "write broker unavailable; reconciliation blocked" }, 503);
      }
    }
    if (url.pathname === "/internal/github/issues" && request.method === "POST") {
      try {
        const declaredLength = Number(request.headers.get("content-length") || 0);
        if (declaredLength > 52000) return json({ error: "issue request too large" }, 413);
        const body = await request.text();
        if (body.length > 52000) return json({ error: "issue request too large" }, 413);
        const response = await (await brokerStub(env)).fetch("https://orca-write-broker.internal/issues/create", {
          method: "POST", headers: { "content-type": "application/json" }, body,
        });
        return new Response(await response.text(), { status: response.status,
          headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });
      } catch {
        return json({ error: "write broker unavailable; GitHub mutation blocked" }, 503);
      }
    }
    if (url.pathname === "/tasks" && request.method === "POST") return createTask(request, env);
    if (url.pathname === "/tasks" && request.method === "GET") return listTasks(url, env);
    const parsed = taskIdFrom(url.pathname);
    if (!parsed) return json({ error: "not found" }, 404);
    if (parsed.action === "approve" && request.method === "POST") return approveTask(parsed.id, request, env);
    if (parsed.action === "claim" && request.method === "POST") return claimTask(parsed.id, request, env);
    if (parsed.action === "complete" && request.method === "POST") return completeTask(parsed.id, request, env);
    if (parsed.action === "status" && request.method === "GET") return getTaskStatus(parsed.id, request, env);
    if (!parsed.action && request.method === "GET") return getTask(parsed.id, env);
    if (!parsed.action && request.method === "PUT") return json({ error: "legacy status updates are disabled; use /claim and /complete with the lease token" }, 410);
    return json({ error: "method not allowed" }, 405);
  },
  async scheduled(_event, env, ctx) {
    ctx.waitUntil(dispatchOutbox(env));
  },
};
