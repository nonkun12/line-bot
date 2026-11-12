import test from "node:test";
import assert from "node:assert/strict";
import { evaluateBudgetGuard } from "../src/budget-guardian.mjs";
const now = "2026-11-12T03:00:00.000Z";
const periodStart = "2026-11-01T00:00:00.000Z";
const periodEnd = "2026-12-01T00:00:00.000Z";
function snapshots(overrides = {}) { return ["cloudflare_workers", "cloudflare_d1", "github_actions"].map((name) => ({ name, enabled: true, used: 10, limit: 100, observed_at: now, period_start: periodStart, period_end: periodEnd, ...overrides[name] })); }
function evaluate(sources = snapshots(), extra = {}) { return evaluateBudgetGuard({ now, sources, globalHoldClear: true, ...extra }); }
test("allows new work only with fresh required sources below warning", () => { const r = evaluate(); assert.equal(r.status, "CLEAR"); assert.equal(r.allowActionsDispatch, true); });
test("70 percent warns but does not suppress", () => { const r = evaluate(snapshots({ cloudflare_d1: { used: 70 } })); assert.equal(r.status, "WARN"); assert.equal(r.allowNewTasks, true); });
test("80 percent suppresses new work", () => { const r = evaluate(snapshots({ github_actions: { used: 80 } })); assert.equal(r.status, "SUPPRESS"); assert.equal(r.allowNewTasks, false); assert.equal(r.allowActionsDispatch, false); });
test("89.99 percent remains SUPPRESS but does not allow new work", () => { const r = evaluate(snapshots({ cloudflare_workers: { used: 89.99 } })); assert.equal(r.status, "SUPPRESS"); assert.equal(r.allowNewTasks, false); assert.equal(r.allowActionsDispatch, false); });
test("90 percent and above STOP both task registration and Actions dispatch for every spend domain", () => {
  for (const name of ["cloudflare_workers", "cloudflare_d1", "github_actions"]) {
    for (const used of [90, 90.01, 100]) {
      const r = evaluate(snapshots({ [name]: { used } }));
      assert.equal(r.status, "STOP", `${name} at ${used}%`);
      assert.equal(r.allowNewTasks, false, `${name} at ${used}% must reject task registration`);
      assert.equal(r.allowActionsDispatch, false, `${name} at ${used}% must reject Actions dispatch`);
    }
  }
});
test("worst status wins when multiple domains cross stop", () => { const r = evaluate(snapshots({ cloudflare_workers: { used: 90 }, github_actions: { used: 95 } })); assert.equal(r.status, "STOP"); assert.equal(r.allowNewTasks, false); assert.equal(r.allowActionsDispatch, false); });
test("missing telemetry and missing required sources fail closed", () => { assert.equal(evaluate(undefined).status, "BLOCKED"); assert.equal(evaluate(snapshots().slice(0, 2)).reason, "required_usage_source_missing"); });
test("stale, future, malformed and out-of-period snapshots fail closed", () => { for (const override of [{ observed_at: "2026-11-12T00:00:00.000Z" }, { observed_at: "2026-11-12T04:00:00.000Z" }, { used: -1 }, { limit: 0 }, { period_start: "2026-12-01T00:00:00.000Z" }]) assert.equal(evaluate(snapshots({ cloudflare_workers: override })).status, "BLOCKED"); });
test("unknown enabled state is not treated as disabled", () => { const s = snapshots(); delete s[0].enabled; assert.equal(evaluate(s).status, "BLOCKED"); });
test("any disabled spend path without a separately trusted operator control fails closed", () => { for (const name of ["cloudflare_workers", "cloudflare_d1", "github_actions"]) { const r = evaluate(snapshots({ [name]: { enabled: false } })); assert.equal(r.status, "BLOCKED"); assert.equal(r.allowNewTasks, false); assert.equal(r.allowActionsDispatch, false); assert.equal(r.reason, "usage_source_disabled_without_trusted_operator_config"); } });
test("Global HOLD and three consecutive failures independently block", () => { assert.equal(evaluate(snapshots(), { globalHoldClear: false }).status, "BLOCKED"); assert.equal(evaluate(snapshots(), { consecutiveFailures: 3 }).status, "BLOCKED"); });
test("duplicate sources and invalid thresholds fail closed", () => { const s = snapshots(); s.push({ ...s[0] }); assert.equal(evaluate(s).status, "BLOCKED"); assert.equal(evaluate(snapshots(), { thresholds: { warn: 80, suppress: 70, stop: 90 } }).status, "BLOCKED"); });
