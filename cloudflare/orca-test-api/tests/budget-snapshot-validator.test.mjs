import test from "node:test";
import assert from "node:assert/strict";
import {
  validateBudgetSnapshot, REQUIRED_METERS,
} from "../src/budget-snapshot-validator.mjs";

const NOW = new Date("2026-11-13T12:00:00.000Z");
const SECRET = "test-only-budget-evidence-secret";
const ACCOUNT = "cf-account-test";
const GH_ACCOUNT = "github-account-test";
const COLLECTOR = "trusted-test-collector";
const iso = "2026-11-13T12:00:00.000Z";

function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((k) => [k, stable(value[k])]));
  }
  return value;
}
async function sign(payload) {
  const unsigned = structuredClone(payload);
  delete unsigned.attestation.signature;
  delete unsigned.attestation.signed_payload;
  const canonical = JSON.stringify(stable(unsigned));
  payload.attestation.signed_payload = canonical;
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(SECRET),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const bytes = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(canonical));
  payload.attestation.signature = [...new Uint8Array(bytes)].map((b) => b.toString(16).padStart(2, "0")).join("");
  return payload;
}
function makePayload() {
  const meters = Object.entries(REQUIRED_METERS).map(([meter_id, [provider, product_id, unit, period_kind]]) => ({
    meter_id, provider, product_id, account_id: provider === "github" ? GH_ACCOUNT : ACCOUNT,
    enabled: true, enforcement_eligible: true, quality: "exact", limit_verified: true,
    limit_evidence_id: "evidence-" + meter_id, unit, limit_source: "authoritative-test-source",
    dataset: "complete-account-meter", complete_account_coverage: true, exact_counter: true,
    sampling_mode: "none", coverage_status: "complete", used: 10, limit: 100,
    observed_at: iso, watermark_at: iso, period_kind,
    period_start: period_kind === "daily" ? "2026-11-13T00:00:00.000Z" :
      period_kind === "monthly" ? "2026-11-01T00:00:00.000Z" : null,
    period_end: period_kind === "daily" ? "2026-11-14T00:00:00.000Z" :
      period_kind === "monthly" ? "2026-12-01T00:00:00.000Z" : null,
  }));
  return {
    schema_version: 2, consecutive_failures: 0, meters,
    meter_inventory: {
      complete_account_coverage: true, unresolved_products: [],
      cloudflare_account_id: ACCOUNT, github_account_id: GH_ACCOUNT,
      github_repository_visibility: "public",
      github_runner_policy: "standard_github_hosted_only",
      enabled_products: ["workers", "workers_logs", "d1", "durable_objects", "actions", "actions_packages"],
      observed_at: iso, watermark_at: iso,
    },
    attestation: { algorithm: "hmac-sha256", account_id: ACCOUNT,
      collector_id: COLLECTOR, issued_at: iso, expires_at: "2026-11-13T12:10:00.000Z" },
  };
}
const options = { now: NOW, secret: SECRET, expectedAccountId: ACCOUNT,
  trustedCollectorId: COLLECTOR, expectedGithubAccountId: GH_ACCOUNT };

test("accepts complete fresh signed schema-v2 snapshot and derives status", async () => {
  const result = await validateBudgetSnapshot(await sign(makePayload()), options);
  assert.equal(result.status, "CLEAR");
  assert.equal(result.allowed, true);
  assert.equal(result.meters.length, 14);
});
test("rejects tampered payload after HMAC signing", async () => {
  const payload = await sign(makePayload());
  payload.meters[0].used = 99;
  await assert.rejects(validateBudgetSnapshot(payload, options), { code: "budget_attestation_signature_invalid" });
});
test("rejects missing, duplicate, and unexpected meter identities", async () => {
  const missing = makePayload(); missing.meters.pop(); await sign(missing);
  await assert.rejects(validateBudgetSnapshot(missing, options), { code: "budget_meter_set_incomplete_or_unexpected" });
  const duplicate = makePayload(); duplicate.meters[1].meter_id = duplicate.meters[0].meter_id; await sign(duplicate);
  await assert.rejects(validateBudgetSnapshot(duplicate, options), { code: "budget_meter_identity_invalid" });
  const extra = makePayload(); extra.meters[0].meter_id = "unknown.meter"; await sign(extra);
  await assert.rejects(validateBudgetSnapshot(extra, options), { code: "budget_meter_set_incomplete_or_unexpected" });
});
test("rejects stale evidence, partial inventory, and wrong account", async () => {
  const stale = makePayload(); stale.meters[0].watermark_at = "2026-11-13T11:00:00.000Z"; await sign(stale);
  await assert.rejects(validateBudgetSnapshot(stale, options), { code: "budget_snapshot_stale_or_future" });
  const partial = makePayload(); partial.meter_inventory.complete_account_coverage = false; await sign(partial);
  await assert.rejects(validateBudgetSnapshot(partial, options), { code: "budget_product_inventory_incomplete" });
  const wrong = makePayload(); wrong.meters[0].account_id = "other-account"; await sign(wrong);
  await assert.rejects(validateBudgetSnapshot(wrong, options), { code: "budget_meter_provider_product_or_account_invalid" });
});
test("derives 70/80/90 thresholds server-side without trusting caller status", async () => {
  for (const [used, status, allowed] of [[70, "WARN", true], [80, "SUPPRESS", false], [90, "STOP", false]]) {
    const payload = makePayload(); payload.meters[0].used = used; payload.status = "CLEAR"; await sign(payload);
    const result = await validateBudgetSnapshot(payload, options);
    assert.equal(result.status, status);
    assert.equal(result.allowed, allowed);
  }
});
test("rejects invalid periods and three consecutive collector failures", async () => {
  const badPeriod = makePayload(); badPeriod.meters[0].period_start = "2026-11-13T00:01:00.000Z"; await sign(badPeriod);
  await assert.rejects(validateBudgetSnapshot(badPeriod, options), { code: "budget_daily_period_alignment_invalid" });
  const failed = makePayload(); failed.consecutive_failures = 3; await sign(failed);
  await assert.rejects(validateBudgetSnapshot(failed, options), { code: "consecutive_failure_limit_reached" });
});
