import test from "node:test";
import assert from "node:assert/strict";
import { createHash, generateKeyPairSync, webcrypto } from "node:crypto";
import { OrcaWriteBroker } from "../src/write-broker.mjs";

if (!globalThis.crypto) globalThis.crypto = webcrypto;

class Storage {
  values = new Map();
  async get(key) { return this.values.get(key); }
  async put(key, value) { this.values.set(key, structuredClone(value)); }
}

class State {
  storage = new Storage();
  chain = Promise.resolve();
  blockConcurrencyWhile(fn) {
    const result = this.chain.then(fn, fn);
    this.chain = result.then(() => undefined, () => undefined);
    return result;
  }
}

const { privateKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
const privatePem = privateKey.export({ type: "pkcs8", format: "pem" }).toString();
const requestText = "アプリ開発: broker integration test";
const claimToken = "claim-token-which-is-long-enough-123";
const taskId = "task-broker-001";
const taskRow = {
  task_id: taskId,
  request_text: requestText,
  status: "running",
  lease_token: claimToken,
  lease_until: new Date(Date.now() + 5 * 60_000).toISOString(),
  task_type: "app_development",
  max_tasks: 1,
  request_hash: createHash("sha256").update(requestText).digest("hex"),
  approval_status: "consumed",
  approval_task_type: "app_development",
  approval_max_tasks: 1,
};

function makeBroker(privateKeyPem = privatePem) {
  const state = new State();
  const env = {
    DB: { prepare: () => ({ bind: () => ({ first: async () => taskRow }) }) },
    GITHUB_APP_ID: "12345",
    GITHUB_APP_INSTALLATION_ID: "98765",
    GITHUB_APP_PRIVATE_KEY: privateKeyPem,
    GITHUB_REPOSITORY: "nonkun12/line-bot",
  };
  return { state, broker: new OrcaWriteBroker(state, env) };
}

async function call(broker, path, method = "GET", body = null) {
  return broker.fetch(new Request("https://broker.test" + path, {
    method,
    headers: body === null ? {} : { "content-type": "application/json" },
    body: body === null ? undefined : JSON.stringify(body),
  }));
}

async function releaseHold(broker) {
  const response = await call(broker, "/hold", "PUT", {
    value: "off", operator_id: "test-operator", reason: "approved isolated test release",
  });
  assert.equal(response.status, 200);
}

function mockGithub(createIssue) {
  const original = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    if (String(url).includes("/app/installations/")) {
      return new Response(JSON.stringify({ token: "installation-token" }), { status: 201 });
    }
    if (String(url).endsWith("/issues")) return createIssue(url, options);
    throw new Error("unexpected outbound URL: " + url);
  };
  return () => { globalThis.fetch = original; };
}

const issueBody = {
  task_id: taskId,
  claim_token: claimToken,
  idempotency_key: "idem-key-00000000000001",
  title: "ORCA review: bounded task",
  body: "Review-only task output.",
};

test("Durable Object starts fail-closed and rejects issue writes under HOLD", async () => {
  const { broker } = makeBroker();
  const state = await (await call(broker, "/hold")).json();
  assert.deepEqual(state, { clear: false, value: "on", blocked: true });
  const response = await call(broker, "/issues/create", "POST", issueBody);
  assert.equal(response.status, 423);
});

test("HOLD release requires an explicit operator and reason", async () => {
  const { broker } = makeBroker();
  const denied = await call(broker, "/hold", "PUT", { value: "off" });
  assert.equal(denied.status, 400);
  await releaseHold(broker);
  const state = await (await call(broker, "/hold")).json();
  assert.equal(state.clear, true);
});

test("HOLD ON waits for an in-flight GitHub write and blocks later writes", async () => {
  const { broker } = makeBroker();
  await releaseHold(broker);
  let startedResolve;
  let finishIssue;
  const started = new Promise((resolve) => { startedResolve = resolve; });
  const restore = mockGithub(() => new Promise((resolve) => {
    finishIssue = () => resolve(new Response(JSON.stringify({
      number: 42, html_url: "https://github.com/nonkun12/line-bot/issues/42",
      title: issueBody.title, state: "open",
    }), { status: 201 }));
    startedResolve();
  }));

  try {
    const writePromise = call(broker, "/issues/create", "POST", issueBody);
    await started;
    let holdResolved = false;
    const holdPromise = call(broker, "/hold", "PUT", { value: "on", reason: "operator requested hold" })
      .then((response) => { holdResolved = true; return response; });
    await new Promise((resolve) => setTimeout(resolve, 25));
    assert.equal(holdResolved, false, "HOLD must wait while the GitHub request is in flight");
    finishIssue();
    const write = await writePromise;
    assert.equal(write.status, 201);
    const hold = await holdPromise;
    assert.equal(hold.status, 200);
    const blocked = await call(broker, "/issues/create", "POST", {
      ...issueBody, idempotency_key: "idem-key-00000000000002",
    });
    assert.equal(blocked.status, 423);
  } finally {
    restore();
  }
});

test("completed idempotency key replays the saved result without a second GitHub write", async () => {
  const { broker } = makeBroker();
  await releaseHold(broker);
  let writes = 0;
  const restore = mockGithub(async () => {
    writes += 1;
    return new Response(JSON.stringify({
      number: 77, html_url: "https://github.com/nonkun12/line-bot/issues/77",
      title: issueBody.title, state: "open",
    }), { status: 201 });
  });
  try {
    const first = await call(broker, "/issues/create", "POST", issueBody);
    assert.equal(first.status, 201);
    const replay = await call(broker, "/issues/create", "POST", issueBody);
    assert.equal(replay.status, 200);
    assert.equal((await replay.json()).idempotent_replay, true);
    assert.equal(writes, 1);
  } finally {
    restore();
  }
});

test("uncertain GitHub outcome is never automatically retried", async () => {
  const { broker } = makeBroker();
  await releaseHold(broker);
  let writes = 0;
  const restore = mockGithub(async () => {
    writes += 1;
    throw new Error("simulated network disconnect after request dispatch");
  });
  try {
    const first = await call(broker, "/issues/create", "POST", issueBody);
    assert.equal(first.status, 503);
    const retry = await call(broker, "/issues/create", "POST", issueBody);
    assert.equal(retry.status, 409);
    assert.equal(writes, 1);
  } finally {
    restore();
  }
});

test("expired or mismatched claim cannot authorize a GitHub issue", async () => {
  const { broker } = makeBroker();
  await releaseHold(broker);
  const original = broker.env.DB;
  broker.env.DB = { prepare: () => ({ bind: () => ({ first: async () => ({
    ...taskRow, lease_until: new Date(Date.now() - 1000).toISOString(),
  }) }) }) };
  const denied = await call(broker, "/issues/create", "POST", issueBody);
  assert.equal(denied.status, 403);
  broker.env.DB = original;
});

test("GitHub App RSA PKCS1 PEM is accepted", async () => {
  const pkcs1Pem = privateKey.export({ type: "pkcs1", format: "pem" }).toString();
  const { broker } = makeBroker(pkcs1Pem);
  await releaseHold(broker);
  const restore = mockGithub(async () => new Response(JSON.stringify({
    number: 88, html_url: "https://github.com/nonkun12/line-bot/issues/88",
    title: issueBody.title, state: "open",
  }), { status: 201 }));
  try {
    const response = await call(broker, "/issues/create", "POST", {
      ...issueBody, idempotency_key: "idem-key-pkcs1-00000001",
    });
    assert.equal(response.status, 201);
  } finally {
    restore();
  }
});
