const REQUIRED_METERS = Object.freeze({
  "cloudflare.workers.requests.daily": ["cloudflare", "workers", "requests", "daily"],
  "cloudflare.workers.cpu_ms_per_invocation.max": ["cloudflare", "workers", "ms", "per_invocation"],
  "cloudflare.workers_logs.events.daily": ["cloudflare", "workers_logs", "events", "daily"],
  "cloudflare.d1.rows_read.daily": ["cloudflare", "d1", "rows", "daily"],
  "cloudflare.d1.rows_written.daily": ["cloudflare", "d1", "rows", "daily"],
  "cloudflare.d1.storage_bytes.total": ["cloudflare", "d1", "bytes", "total"],
  "cloudflare.durable_objects.requests.daily": ["cloudflare", "durable_objects", "requests", "daily"],
  "cloudflare.durable_objects.duration_gb_seconds.daily": ["cloudflare", "durable_objects", "GB-seconds", "daily"],
  "cloudflare.durable_objects.sqlite_rows_read.daily": ["cloudflare", "durable_objects", "rows", "daily"],
  "cloudflare.durable_objects.sqlite_rows_written.daily": ["cloudflare", "durable_objects", "rows", "daily"],
  "cloudflare.durable_objects.sqlite_storage_bytes.total": ["cloudflare", "durable_objects", "bytes", "total"],
  "github.actions.compute_cost_usd.monthly": ["github", "actions", "USD", "monthly"],
  "github.actions_packages.shared_storage_gb_hours.monthly": ["github", "actions_packages", "GB-hours", "monthly"],
  "github.actions.cache_storage_gb_hours.monthly": ["github", "actions", "GB-hours", "monthly"],
});
const REQUIRED_PRODUCTS = Object.freeze([
  "workers", "workers_logs", "d1", "durable_objects", "actions", "actions_packages",
]);
const MAX_AGE_MS = 10 * 60 * 1000;
const FUTURE_SKEW_MS = 5 * 60 * 1000;
const MAX_ATTESTATION_LIFETIME_MS = 15 * 60 * 1000;

export class BudgetSnapshotError extends Error {
  constructor(code) { super(code); this.name = "BudgetSnapshotError"; this.code = code; }
}
function fail(code) { throw new BudgetSnapshotError(code); }
function parseTime(value) {
  if (typeof value !== "string" || !value.trim() || !/(Z|[+-]\d{2}:\d{2})$/i.test(value)) fail("timestamp_missing_or_timezone_invalid");
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) fail("timestamp_missing_or_invalid");
  return parsed;
}
function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === "object") {
    const out = {};
    for (const key of Object.keys(value).sort()) out[key] = stable(value[key]);
    return out;
  }
  if (typeof value === "number" && !Number.isFinite(value)) fail("budget_attestation_payload_not_canonicalizable");
  return value;
}
function canonicalPayload(payload) {
  const unsigned = structuredClone(payload);
  unsigned.attestation = { ...unsigned.attestation };
  delete unsigned.attestation.signature;
  const signedPayload = unsigned.attestation.signed_payload;
  delete unsigned.attestation.signed_payload;
  if (typeof signedPayload !== "string" || !signedPayload) fail("budget_attestation_canonical_payload_missing");
  let parsed;
  try { parsed = JSON.parse(signedPayload); }
  catch { fail("budget_attestation_canonical_payload_not_json"); }
  if (JSON.stringify(stable(parsed)) !== JSON.stringify(stable(unsigned)))
    fail("budget_attestation_canonical_payload_mismatch");
  return signedPayload;
}
function hex(bytes) {
  return [...new Uint8Array(bytes)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
async function verifyHmac(payload, secret) {
  const signature = payload.attestation?.signature;
  if (typeof secret !== "string" || !secret ||
      payload.attestation?.algorithm !== "hmac-sha256" ||
      typeof signature !== "string" || !/^[0-9a-f]{64}$/i.test(signature)) fail("budget_attestation_identity_invalid");
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const expected = hex(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(canonicalPayload(payload))));
  let mismatch = signature.length ^ expected.length;
  for (let i = 0; i < Math.min(signature.length, expected.length); i++)
    mismatch |= signature.toLowerCase().charCodeAt(i) ^ expected.charCodeAt(i);
  if (mismatch !== 0) fail("budget_attestation_signature_invalid");
}
function validateFresh(value, now, issuedAt, watermarkLabel) {
  const observed = parseTime(value.observed_at);
  const watermark = parseTime(value.watermark_at);
  if (watermark > observed) fail(watermarkLabel + "_watermark_after_observation");
  if (observed > issuedAt + FUTURE_SKEW_MS ||
      observed > now + FUTURE_SKEW_MS || watermark > now + FUTURE_SKEW_MS ||
      now - observed > MAX_AGE_MS || now - watermark > MAX_AGE_MS)
    fail(watermarkLabel + "_stale_or_future");
}
function validatePeriod(meter, kind, now) {
  if (meter.period_kind !== kind) fail("budget_period_kind_invalid");
  if (kind === "total" || kind === "per_invocation") {
    if (meter.period_start !== null || meter.period_end !== null) fail("budget_nonreset_meter_has_period_boundary");
    return;
  }
  const start = parseTime(meter.period_start), end = parseTime(meter.period_end);
  if (start >= end || !(start <= now && now < end)) fail("budget_period_not_current");
  const duration = end - start;
  if (kind === "daily") {
    const d = new Date(start);
    if (d.getUTCHours() !== 0 || d.getUTCMinutes() !== 0 || d.getUTCSeconds() !== 0 ||
        d.getUTCMilliseconds() !== 0 || duration !== 86400000) fail("budget_daily_period_alignment_invalid");
  } else if (kind === "monthly") {
    const startDate = new Date(start);
    const endDate = new Date(end);
    const expectedEnd = Date.UTC(startDate.getUTCFullYear(), startDate.getUTCMonth() + 1, 1);
    if (startDate.getUTCDate() !== 1 || startDate.getUTCHours() !== 0 ||
        startDate.getUTCMinutes() !== 0 || startDate.getUTCSeconds() !== 0 ||
        startDate.getUTCMilliseconds() !== 0 || end !== expectedEnd) {
      fail("budget_monthly_period_alignment_invalid");
    }
  }
}

/** Validates the exact schema-v2 contract used by scripts/distributed_loop_30m_gate.py.
 * Does not persist state and never trusts a caller-supplied aggregate status.
 */
export async function validateBudgetSnapshot(payload, {
  now = new Date(), secret = "", expectedAccountId = "",
  trustedCollectorId = "", expectedGithubAccountId = "",
} = {}) {
  const nowMs = now instanceof Date ? now.getTime() : Date.parse(now);
  if (!Number.isFinite(nowMs)) fail("clock_unavailable");
  if (!payload || typeof payload !== "object" || Array.isArray(payload) ||
      !Array.isArray(payload.meters) || !payload.attestation || typeof payload.attestation !== "object")
    fail("budget_meter_inventory_v2_missing");
  if (!secret || !expectedAccountId || !trustedCollectorId || !expectedGithubAccountId)
    fail("budget_attestation_trust_configuration_missing");
  const a = payload.attestation;
  if (a.algorithm !== "hmac-sha256" || a.account_id !== expectedAccountId ||
      a.collector_id !== trustedCollectorId) fail("budget_attestation_identity_invalid");
  await verifyHmac(payload, secret);
  if (payload.schema_version !== 2) fail("budget_meter_schema_unsupported");
  const issuedAt = parseTime(a.issued_at), expiresAt = parseTime(a.expires_at);
  if (issuedAt > nowMs + FUTURE_SKEW_MS || issuedAt > expiresAt ||
      expiresAt <= nowMs || expiresAt - issuedAt > MAX_ATTESTATION_LIFETIME_MS ||
      nowMs - issuedAt > MAX_AGE_MS) fail("budget_attestation_stale_or_out_of_window");

  const inventory = payload.meter_inventory;
  if (!inventory || typeof inventory !== "object" || Array.isArray(inventory) ||
      inventory.complete_account_coverage !== true || !Array.isArray(inventory.unresolved_products) ||
      inventory.unresolved_products.length !== 0 ||
      inventory.cloudflare_account_id !== expectedAccountId ||
      inventory.github_account_id !== expectedGithubAccountId ||
      inventory.github_repository_visibility !== "public" ||
      inventory.github_runner_policy !== "standard_github_hosted_only")
    fail("budget_product_inventory_incomplete");
  const products = inventory.enabled_products;
  if (!Array.isArray(products) || products.some((p) => typeof p !== "string") ||
      new Set(products).size !== products.length ||
      [...products].sort().join("|") !== [...REQUIRED_PRODUCTS].sort().join("|"))
    fail("budget_product_inventory_unexpected_or_incomplete");
  validateFresh(inventory, nowMs, issuedAt, "budget_product_inventory");
  const failures = payload.consecutive_failures;
  if (!Number.isInteger(failures) || failures < 0) fail("failure_counter_invalid");
  if (failures >= 3) fail("consecutive_failure_limit_reached");

  const byId = new Map();
  for (const meter of payload.meters) {
    if (!meter || typeof meter !== "object" || Array.isArray(meter) ||
        typeof meter.meter_id !== "string" || !meter.meter_id || byId.has(meter.meter_id))
      fail("budget_meter_identity_invalid");
    byId.set(meter.meter_id, meter);
  }
  const expectedIds = Object.keys(REQUIRED_METERS);
  if (byId.size !== expectedIds.length || expectedIds.some((id) => !byId.has(id)))
    fail("budget_meter_set_incomplete_or_unexpected");

  const results = [];
  for (const [meterId, [provider, productId, unit, periodKind]] of Object.entries(REQUIRED_METERS)) {
    const meter = byId.get(meterId);
    const accountId = provider === "github" ? expectedGithubAccountId : expectedAccountId;
    if (meter.provider !== provider || meter.product_id !== productId ||
        meter.account_id !== accountId || meter.enabled !== true)
      fail("budget_meter_provider_product_or_account_invalid");
    if (meter.enforcement_eligible !== true || meter.quality !== "exact" ||
        meter.limit_verified !== true || typeof meter.limit_evidence_id !== "string" ||
        !meter.limit_evidence_id.trim()) fail("budget_limit_not_authoritatively_verified");
    if (meter.unit !== unit || typeof meter.limit_source !== "string" || !meter.limit_source.trim() ||
        typeof meter.dataset !== "string" || !meter.dataset.trim())
      fail("budget_meter_unit_dataset_or_limit_evidence_missing");
    if (meter.complete_account_coverage !== true || meter.exact_counter !== true ||
        meter.sampling_mode !== "none" || meter.coverage_status !== "complete")
      fail("budget_meter_coverage_or_exactness_unproven");
    const { used, limit } = meter;
    if (typeof used !== "number" || !Number.isFinite(used) || used < 0 ||
        typeof limit !== "number" || !Number.isFinite(limit) || limit <= 0)
      fail("budget_values_invalid");
    validateFresh(meter, nowMs, issuedAt, "budget_snapshot");
    validatePeriod(meter, periodKind, nowMs);
    const percent = used / limit * 100;
    results.push({ meter_id: meterId, unit, used, limit, percent,
      status: percent >= 90 ? "STOP" : percent >= 80 ? "SUPPRESS" : percent >= 70 ? "WARN" : "CLEAR",
      observed_at: meter.observed_at, watermark_at: meter.watermark_at,
      period_kind: periodKind, period_start: meter.period_start, period_end: meter.period_end });
  }
  const rank = { CLEAR: 0, WARN: 1, SUPPRESS: 2, STOP: 3 };
  const status = results.reduce((worst, item) => rank[item.status] > rank[worst] ? item.status : worst, "CLEAR");
  return { status, allowed: status === "CLEAR" || status === "WARN",
    reason: status === "CLEAR" ? "within_budget" : status === "WARN" ? "budget_warning_threshold_reached" :
      status === "SUPPRESS" ? "budget_suppression_threshold_reached" : "budget_stop_threshold_reached",
    attestation: { account_id: a.account_id, collector_id: a.collector_id, issued_at: a.issued_at, expires_at: a.expires_at },
    inventory: { observed_at: inventory.observed_at, watermark_at: inventory.watermark_at,
      enabled_products: [...products].sort() },
    meters: results };
}
export { REQUIRED_METERS, REQUIRED_PRODUCTS, MAX_AGE_MS, FUTURE_SKEW_MS };
