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
  const match = path.match(/^\/tasks\/([A-Za-z0-9_-]{1,100})(?:\/(claim|complete))?$/);
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

async function claimTask(id, request, env) {
  const body = await readJson(request);
  const leaseSeconds = Number.isInteger(body?.lease_seconds)
    ? Math.min(1800, Math.max(60, body.lease_seconds)) : 900;
  const token = crypto.randomUUID();
  const leaseUntil = new Date(Date.now() + leaseSeconds * 1000).toISOString();
  const row = await env.DB.prepare(
    `UPDATE tasks
       SET status = 'running', lease_token = ?, lease_until = ?,
           attempt_count = COALESCE(attempt_count, 0) + 1,
           updated_at = CURRENT_TIMESTAMP
     WHERE task_id = ? AND (status = 'queued' OR (status = 'running' AND datetime(lease_until) <= CURRENT_TIMESTAMP))
     RETURNING task_id, request_text, status, lease_until, attempt_count`
  ).bind(token, leaseUntil, id).first();
  if (!row) return json({ error: "task is not queued or does not exist" }, 409);
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

async function listTasks(url, env) {
  const limit = Math.min(100, Math.max(1, Number.parseInt(url.searchParams.get("limit") || "20", 10) || 20));
  const status = url.searchParams.get("status");
  const rows = status
    ? await env.DB.prepare(
        "SELECT task_id, request_text, status, created_at, updated_at FROM tasks WHERE status = ? ORDER BY created_at DESC LIMIT ?"
      ).bind(status, limit).all()
    : await env.DB.prepare(
        "SELECT task_id, request_text, status, created_at, updated_at FROM tasks ORDER BY created_at DESC LIMIT ?"
      ).bind(limit).all();
  return json({ tasks: rows.results || [] });
}

async function legacyUpdate(id, request, env) {
  const body = await readJson(request);
  if (!["running", "pass", "fail", "blocked"].includes(body?.status)) {
    return json({ error: "invalid status" }, 400);
  }
  // Legacy status transitions remain available for the existing test integration.
  // New workers must use /claim and /complete for lease-bound state changes.
  const result = await env.DB.prepare(
    `UPDATE tasks SET status = ?, updated_at = CURRENT_TIMESTAMP
      WHERE task_id = ? AND (
        (status = 'queued' AND ? IN ('running', 'blocked')) OR
        (status = 'running' AND ? IN ('pass', 'fail', 'blocked'))
      )`
  ).bind(body.status, id, body.status, body.status).run();
  if (!result.meta.changes) return json({ error: "invalid transition or task not found" }, 409);
  return getTask(id, env);
}

async function dispatchOutbox(env) {
  if (!env.LINE_CHANNEL_ACCESS_TOKEN) return;
  const due = await env.DB.prepare(
    `SELECT outbox_id, user_id, message, attempts
       FROM notification_outbox
      WHERE status = 'pending' AND next_attempt_at <= CURRENT_TIMESTAMP
      ORDER BY created_at LIMIT 20`
  ).all();
  for (const item of due.results || []) {
    let response;
    try {
      response = await fetch("https://api.line.me/v2/bot/message/push", {
        method: "POST",
        headers: {
          authorization: `Bearer ${env.LINE_CHANNEL_ACCESS_TOKEN}`,
          "content-type": "application/json",
        },
        body: JSON.stringify({
          to: item.user_id,
          messages: [{ type: "text", text: item.message }],
        }),
      });
    } catch {
      response = null;
    }
    if (response?.ok) {
      await env.DB.prepare(
        "UPDATE notification_outbox SET status = 'sent', sent_at = CURRENT_TIMESTAMP WHERE outbox_id = ? AND status = 'pending'"
      ).bind(item.outbox_id).run();
      continue;
    }
    const attempts = item.attempts + 1;
    const dead = attempts >= 8;
    const delay = Math.min(3600, 30 * (2 ** Math.min(attempts, 7)));
    await env.DB.prepare(
      `UPDATE notification_outbox
          SET attempts = ?, status = ?, last_error_code = ?,
              next_attempt_at = datetime('now', ?)
        WHERE outbox_id = ? AND status = 'pending'`
    ).bind(attempts, dead ? "dead" : "pending",
      response ? `LINE_HTTP_${response.status}` : "NETWORK_ERROR",
      `+${delay} seconds`, item.outbox_id).run();
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
    if (parsed.action === "claim" && request.method === "POST") return claimTask(parsed.id, request, env);
    if (parsed.action === "complete" && request.method === "POST") return completeTask(parsed.id, request, env);
    if (!parsed.action && request.method === "GET") return getTask(parsed.id, env);
    if (!parsed.action && request.method === "PUT") return legacyUpdate(parsed.id, request, env);
    return json({ error: "method not allowed" }, 405);
  },
  async scheduled(_event, env, ctx) {
    ctx.waitUntil(dispatchOutbox(env));
  },
};
