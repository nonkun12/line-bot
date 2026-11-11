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

async function createTask(request, env) {
  const body = await readJson(request);
  if (!body || typeof body.task_id !== "string" ||
      !/^[A-Za-z0-9_-]{1,100}$/.test(body.task_id) ||
      typeof body.request_text !== "string" ||
      !body.request_text.trim() || new TextEncoder().encode(body.request_text).length > 6000) {
    return json({ error: "invalid task payload" }, 400);
  }
  const userId = typeof body.user_id === "string" && /^[A-Za-z0-9_-]{1,128}$/.test(body.user_id)
    ? body.user_id : null;
  try {
    await env.DB.prepare(
      `INSERT INTO tasks (task_id, request_text, status, source_event_id, user_id)
       VALUES (?, ?, 'queued', ?, ?)`
    ).bind(body.task_id, body.request_text, body.source_event_id || null, userId).run();
    return json({ task: { task_id: body.task_id, request_text: body.request_text, status: "queued" } }, 201);
  } catch (error) {
    if (body.source_event_id) {
      const existing = await env.DB.prepare(
        "SELECT task_id, request_text, status FROM tasks WHERE source_event_id = ?"
      ).bind(body.source_event_id).first();
      if (existing) return json({ task: existing, duplicate: true }, 200);
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
  const body = await readJson(request);
  const userId = typeof body?.approver_user_id === "string" ? body.approver_user_id : "";
  const requestHash = typeof body?.request_hash === "string" ? body.request_hash : "";
  const issuedAt = typeof body?.issued_at === "string" ? body.issued_at : "";
  const expiresAt = typeof body?.expires_at === "string" ? body.expires_at : "";
  const signature = typeof body?.signature === "string" ? body.signature : "";
  const nonce = typeof body?.nonce === "string" ? body.nonce : "";
  const approvalKey = env.ORCA_TASK_APPROVAL_HMAC_KEY || "";
  if (new TextEncoder().encode(approvalKey).length < 32 ||
      !/^U[0-9a-fA-F]{32}$/.test(userId) || !/^[0-9a-f]{64}$/.test(requestHash) ||
      !/^[0-9a-f]{64}$/.test(signature) || !/^[A-Za-z0-9_-]{32}$/.test(nonce)) return json({ error: "approval is not authorized" }, 403);
  const issued = Date.parse(issuedAt), expires = Date.parse(expiresAt), now = Date.now();
  if (!Number.isFinite(issued) || !Number.isFinite(expires) || issued > now + 60000 ||
      issued < now - 5 * 60000 || expires <= now || expires > issued + 60 * 60000)
    return json({ error: "approval timestamp is invalid or expired" }, 400);
  const canonical = ["v1", id, requestHash, userId, issuedAt, expiresAt, nonce].join("\n");
  if (!safeEqual(signature, await hmacHex(approvalKey, canonical)))
    return json({ error: "invalid approval signature" }, 403);
  const task = await env.DB.prepare("SELECT task_id, request_text, status, lease_until, user_id FROM tasks WHERE task_id = ?").bind(id).first();
  const expiredRunning = task?.status === "running" && task.lease_until && Date.parse(task.lease_until) <= Date.now();
  if (!task || (task.status !== "queued" && !expiredRunning))
    return json({ error: "task is not awaiting approval or its prior lease is still active" }, 409);
  if (typeof task.request_text !== "string" ||
      !task.request_text.startsWith("アプリ開発:") && !task.request_text.startsWith("アプリ開発："))
    return json({ error: "only explicit app-development tasks can be approved" }, 400);
  if (task.user_id !== userId) return json({ error: "only the verified task submitter may approve it" }, 403);
  if (!safeEqual(await sha256Hex(task.request_text), requestHash))
    return json({ error: "task content changed; approval rejected" }, 409);
  const approvalId = crypto.randomUUID();
  const saved = await env.DB.prepare(
    "INSERT INTO task_approvals (task_id, approval_id, approval_nonce, request_hash, approver_user_id, issued_at, expires_at, status) " +
    "VALUES (?, ?, ?, ?, ?, ?, ?, 'approved') ON CONFLICT(task_id) DO UPDATE SET " +
    "approval_id=excluded.approval_id, approval_nonce=excluded.approval_nonce, " +
    "request_hash=excluded.request_hash, approver_user_id=excluded.approver_user_id, " +
    "issued_at=excluded.issued_at, expires_at=excluded.expires_at, status='approved' " +
    "WHERE task_approvals.status != 'consumed' OR (excluded.approval_nonce != task_approvals.approval_nonce " +
    "AND EXISTS (SELECT 1 FROM tasks WHERE task_id = excluded.task_id AND status = 'running' " +
    "AND lease_until IS NOT NULL AND datetime(lease_until) <= CURRENT_TIMESTAMP))"
  ).bind(id, approvalId, nonce, requestHash, userId, issuedAt, expiresAt).run();
  if (!saved.meta?.changes) return json({ error: "task approval was already consumed" }, 409);
  return json({ task_id: id, approved: true, expires_at: expiresAt });
}

async function claimTask(id, request, env) {
  const body = await readJson(request);
  const leaseSeconds = Number.isInteger(body?.lease_seconds)
    ? Math.min(1800, Math.max(60, body.lease_seconds)) : 900;
  const token = crypto.randomUUID();
  const leaseUntil = new Date(Date.now() + leaseSeconds * 1000).toISOString();
  const approval = await env.DB.prepare(
    "SELECT approval_id, request_hash, expires_at, status FROM task_approvals WHERE task_id = ?"
  ).bind(id).first();
  if (!approval || approval.status !== "approved" || Date.parse(approval.expires_at) <= Date.now())
    return json({ error: "a valid task-bound LINE approval is required" }, 403);
  const task = await env.DB.prepare("SELECT request_text FROM tasks WHERE task_id = ?").bind(id).first();
  if (!task || !safeEqual(await sha256Hex(task.request_text), approval.request_hash))
    return json({ error: "approved task fingerprint no longer matches" }, 409);
  const results = await env.DB.batch([
    env.DB.prepare(
      `UPDATE tasks SET status = 'running', lease_token = ?, lease_until = ?,
          attempt_count = COALESCE(attempt_count, 0) + 1, updated_at = CURRENT_TIMESTAMP
        WHERE task_id = ? AND (status = 'queued' OR (status = 'running' AND datetime(lease_until) <= CURRENT_TIMESTAMP))
          AND EXISTS (SELECT 1 FROM task_approvals WHERE task_id = ? AND approval_id = ?
                      AND status = 'approved' AND datetime(expires_at) > CURRENT_TIMESTAMP)
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
          AND user_id IS NOT NULL`
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
    "SELECT task_id, request_text, status, created_at, updated_at FROM tasks WHERE task_id = ?"
  ).bind(id).first();
  return task ? json({ task }) : json({ error: "not found" }, 404);
}

async function getTaskStatus(id, url, env) {
  // Status lookup is intentionally scoped to the verified LINE submitter.
  // Return the same 404 for missing tasks and ownership mismatches.
  const userId = url.searchParams.get("user_id") || "";
  if (!/^U[0-9a-fA-F]{32}$/.test(userId)) return json({ error: "not found" }, 404);
  const task = await env.DB.prepare(
    "SELECT task_id, status, created_at, updated_at FROM tasks WHERE task_id = ? AND user_id = ?"
  ).bind(id, userId).first();
  return task ? json({ task }) : json({ error: "not found" }, 404);
}

async function listTasks(url, env) {
  const limit = Math.min(100, Math.max(1, Number.parseInt(url.searchParams.get("limit") || "20", 10) || 20));
  const status = url.searchParams.get("status");
  const approvedOnly = url.searchParams.get("approved") === "true";
  const approvalFilter = approvedOnly
    ? " AND EXISTS (SELECT 1 FROM task_approvals a WHERE a.task_id = tasks.task_id AND a.status = 'approved' AND datetime(a.expires_at) > CURRENT_TIMESTAMP)"
    : "";
  const claimableFilter = approvedOnly
    ? " AND (tasks.status = 'queued' OR (tasks.status = 'running' AND tasks.lease_until IS NOT NULL AND datetime(tasks.lease_until) <= CURRENT_TIMESTAMP))"
    : "";
  const order = approvedOnly ? "ASC" : "DESC";
  const select = "SELECT task_id, request_text, status, created_at, updated_at, lease_until, " +
    "EXISTS (SELECT 1 FROM task_approvals a WHERE a.task_id = tasks.task_id AND a.status = 'approved' " +
    "AND datetime(a.expires_at) > CURRENT_TIMESTAMP) AS approved FROM tasks";
  const rows = status
    ? await env.DB.prepare(select + " WHERE status = ?" + approvalFilter + claimableFilter +
        " ORDER BY created_at " + order + " LIMIT ?").bind(status, limit).all()
    : await env.DB.prepare(select + (approvedOnly ? " WHERE 1=1" + approvalFilter + claimableFilter : "") +
        " ORDER BY created_at " + order + " LIMIT ?").bind(limit).all();
  return json({ tasks: rows.results || [] });
}


async function dispatchOutbox(env) {
  if (!env.LINE_CHANNEL_ACCESS_TOKEN) return;
  const due = await env.DB.prepare(
    `SELECT outbox_id
       FROM notification_outbox
      WHERE status = 'pending' AND next_attempt_at <= CURRENT_TIMESTAMP
        AND (dispatch_until IS NULL OR datetime(dispatch_until) <= CURRENT_TIMESTAMP)
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
        RETURNING outbox_id, user_id, message, attempts`
    ).bind(dispatchToken, candidate.outbox_id).first();
    if (!claimed) continue;

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
    if (url.pathname === "/tasks" && request.method === "POST") return createTask(request, env);
    if (url.pathname === "/tasks" && request.method === "GET") return listTasks(url, env);
    const parsed = taskIdFrom(url.pathname);
    if (!parsed) return json({ error: "not found" }, 404);
    if (parsed.action === "approve" && request.method === "POST") return approveTask(parsed.id, request, env);
    if (parsed.action === "claim" && request.method === "POST") return claimTask(parsed.id, request, env);
    if (parsed.action === "complete" && request.method === "POST") return completeTask(parsed.id, request, env);
    if (parsed.action === "status" && request.method === "GET") return getTaskStatus(parsed.id, url, env);
    if (!parsed.action && request.method === "GET") return getTask(parsed.id, env);
    if (!parsed.action && request.method === "PUT") return json({ error: "legacy status updates are disabled; use /claim and /complete with the lease token" }, 410);
    return json({ error: "method not allowed" }, 405);
  },
  async scheduled(_event, env, ctx) {
    ctx.waitUntil(dispatchOutbox(env));
  },
};
