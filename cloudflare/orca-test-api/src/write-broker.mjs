const json = (value, status = 200) => new Response(JSON.stringify(value), {
  status,
  headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
});

const encoder = new TextEncoder();
const b64url = (bytes) => btoa(String.fromCharCode(...new Uint8Array(bytes)))
  .replace(/=/g, "").replace(/\\+/g, "-").replace(/\\//g, "_");

function pemBytes(pem) {
  const normalized = String(pem || "").replace(/\\\\n/g, "\n");
  const body = normalized.replace(/-----BEGIN PRIVATE KEY-----|-----END PRIVATE KEY-----|\\s/g, "");
  if (!body || !/^[A-Za-z0-9+/=]+$/.test(body)) throw new Error("invalid GitHub App private key");
  return Uint8Array.from(atob(body), (char) => char.charCodeAt(0));
}

async function appJwt(env) {
  if (!env.GITHUB_APP_ID || !env.GITHUB_APP_PRIVATE_KEY) throw new Error("GitHub App credentials are not configured");
  const now = Math.floor(Date.now() / 1000);
  const unsigned = b64url(encoder.encode(JSON.stringify({ alg: "RS256", typ: "JWT" }))) + "." +
    b64url(encoder.encode(JSON.stringify({ iat: now - 30, exp: now + 480, iss: String(env.GITHUB_APP_ID) })));
  const key = await crypto.subtle.importKey(
    "pkcs8", pemBytes(env.GITHUB_APP_PRIVATE_KEY),
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["sign"],
  );
  const signature = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, encoder.encode(unsigned));
  return unsigned + "." + b64url(signature);
}

async function installationToken(env) {
  if (!env.GITHUB_APP_INSTALLATION_ID) throw new Error("GitHub App installation ID is not configured");
  const jwt = await appJwt(env);
  const response = await fetch(
    `https://api.github.com/app/installations/${encodeURIComponent(env.GITHUB_APP_INSTALLATION_ID)}/access_tokens`,
    {
      method: "POST",
      headers: {
        authorization: `Bearer ${jwt}`,
        accept: "application/vnd.github+json",
        "x-github-api-version": "2022-11-28",
        "content-type": "application/json",
      },
      body: JSON.stringify({}),
      signal: AbortSignal.timeout(7000),
    },
  );
  if (!response.ok) throw new Error(`GitHub App token request failed: HTTP ${response.status}`);
  const payload = await response.json();
  if (typeof payload.token !== "string" || !payload.token) throw new Error("GitHub App token response was malformed");
  return payload.token;
}

function equalSecret(left, right) {
  if (typeof left !== "string" || typeof right !== "string" || left.length !== right.length) return false;
  let mismatch = 0;
  for (let i = 0; i < left.length; i++) mismatch |= left.charCodeAt(i) ^ right.charCodeAt(i);
  return mismatch === 0;
}

async function sha256(value) {
  const digest = await crypto.subtle.digest("SHA-256", encoder.encode(value));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

export class OrcaWriteBroker {
  constructor(state, env) {
    this.state = state;
    this.env = env;
  }

  fetch(request) {
    // Every request, including HOLD transitions, enters the same serialized
    // critical section. A HOLD=ON response is not returned until an earlier
    // GitHub request has completed or reached a bounded failure outcome.
    return this.state.blockConcurrencyWhile(() => this.handle(request));
  }

  async holdState() {
    const stored = await this.state.storage.get("global_hold");
    const value = stored?.value === "off" ? "off" : "on";
    return { clear: value === "off", value, blocked: value !== "off" };
  }

  async handle(request) {
    const url = new URL(request.url);
    if (url.pathname === "/hold" && request.method === "GET") return json(await this.holdState());

    if (url.pathname === "/hold" && request.method === "PUT") {
      const body = await request.json().catch(() => null);
      if (!body || !["on", "off"].includes(body.value)) return json({ error: "value must be on or off" }, 400);
      if (body.value === "off" &&
          (typeof body.operator_id !== "string" || !body.operator_id.trim() ||
           typeof body.reason !== "string" || body.reason.trim().length < 8)) {
        return json({ error: "explicit operator_id and reason are required to release HOLD" }, 400);
      }
      const event = {
        value: body.value,
        operator_id: body.value === "off" ? body.operator_id.trim().slice(0, 128) : "system",
        reason: String(body.reason || (body.value === "on" ? "operator requested HOLD" : "")).trim().slice(0, 500),
        changed_at: new Date().toISOString(),
      };
      await this.state.storage.put("global_hold", event);
      await this.state.storage.put(`hold_event:${Date.now()}:${crypto.randomUUID()}`, event);
      return json({ clear: body.value === "off", value: body.value, blocked: body.value !== "off", acknowledged: true });
    }

    if (url.pathname === "/issues/create" && request.method === "POST") {
      const hold = await this.holdState();
      if (!hold.clear) return json({ error: "Global HOLD is active or unavailable" }, 423);
      return this.createReviewIssue(request);
    }
    return json({ error: "not found" }, 404);
  }

  async validateClaim(taskId, claimToken) {
    if (!this.env.DB || typeof taskId !== "string" || !/^[A-Za-z0-9_-]{1,100}$/.test(taskId) ||
        typeof claimToken !== "string" || claimToken.length < 20 || claimToken.length > 100) return null;
    const row = await this.env.DB.prepare(
      `SELECT t.task_id, t.request_text, t.status, t.lease_token, t.lease_until,
              t.task_type, t.max_tasks, a.request_hash, a.status AS approval_status,
              a.task_type AS approval_task_type, a.max_tasks AS approval_max_tasks
         FROM tasks t JOIN task_approvals a ON a.task_id = t.task_id
        WHERE t.task_id = ?`
    ).bind(taskId).first();
    if (!row || row.status !== "running" || !equalSecret(row.lease_token, claimToken) ||
        !Number.isFinite(Date.parse(row.lease_until)) || Date.parse(row.lease_until) <= Date.now() ||
        row.task_type !== "app_development" || row.max_tasks !== 1 ||
        row.approval_status !== "consumed" || row.approval_task_type !== row.task_type ||
        row.approval_max_tasks !== row.max_tasks ||
        !equalSecret(row.request_hash, await sha256(row.request_text)) ||
        !(row.request_text.startsWith("アプリ開発:") || row.request_text.startsWith("アプリ開発："))) return null;
    return row;
  }

  async createReviewIssue(request) {
    const body = await request.json().catch(() => null);
    if (!body || typeof body !== "object" || Array.isArray(body)) return json({ error: "invalid JSON body" }, 400);
    const { task_id: taskId, claim_token: claimToken, idempotency_key: key } = body;
    const title = body.title;
    const description = body.body;
    if (typeof key !== "string" || !/^[A-Za-z0-9_-]{16,100}$/.test(key) ||
        typeof title !== "string" || !title.trim() || title.length > 256 ||
        typeof description !== "string" || !description.trim() || description.length > 50000) {
      return json({ error: "invalid bounded issue payload or idempotency key" }, 400);
    }
    const task = await this.validateClaim(taskId, claimToken);
    if (!task) return json({ error: "a current claimed app-development task is required" }, 403);

    const recordKey = `issue:${taskId}:${key}`;
    const prior = await this.state.storage.get(recordKey);
    if (prior?.state === "completed") return json({ ...prior.result, idempotent_replay: true }, 200);
    if (prior) return json({ error: "operation outcome is already recorded as in-flight or uncertain; manual reconciliation required" }, 409);

    const repository = String(this.env.GITHUB_REPOSITORY || "");
    if (!/^[A-Za-z0-9_.-]+\\/[A-Za-z0-9_.-]+$/.test(repository)) {
      return json({ error: "fixed GitHub repository is not configured" }, 503);
    }
    const [owner, repo] = repository.split("/");
    await this.state.storage.put(recordKey, {
      state: "in_flight", task_id: taskId, started_at: new Date().toISOString(),
    });

    try {
      const token = await installationToken(this.env);
      const response = await fetch(`https://api.github.com/repos/${owner}/${repo}/issues`, {
        method: "POST",
        headers: {
          authorization: `Bearer ${token}`,
          accept: "application/vnd.github+json",
          "x-github-api-version": "2022-11-28",
          "content-type": "application/json",
        },
        body: JSON.stringify({
          title: title.trim(),
          body: `${description.trim()}\\n\\n<!-- ORCA_TASK_ID:${taskId} ORCA_IDEMPOTENCY_KEY:${key} -->`,
          labels: ["orca-task-review"],
        }),
        signal: AbortSignal.timeout(7000),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        const uncertain = response.status >= 500 || response.status === 408 || response.status === 429;
        await this.state.storage.put(recordKey, {
          state: uncertain ? "uncertain" : "rejected",
          http_status: response.status,
          updated_at: new Date().toISOString(),
        });
        return json({ error: `GitHub issue creation returned HTTP ${response.status}`, outcome: uncertain ? "uncertain" : "rejected" }, 502);
      }
      const saved = {
        number: result.number,
        html_url: result.html_url,
        title: result.title,
        state: result.state,
      };
      await this.state.storage.put(recordKey, {
        state: "completed", task_id: taskId, result: saved, completed_at: new Date().toISOString(),
      });
      return json(saved, 201);
    } catch (error) {
      await this.state.storage.put(recordKey, {
        state: "uncertain", task_id: taskId, updated_at: new Date().toISOString(),
        error: String(error).slice(0, 300),
      });
      return json({ error: "GitHub write outcome is uncertain; automatic retry is disabled" }, 503);
    }
  }
}
