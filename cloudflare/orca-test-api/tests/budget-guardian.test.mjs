import test from "node:test";
import assert from "node:assert/strict";
import { evaluateBudgetGuard } from "../src/budget-guardian.mjs";

const now = "2026-11-12T03:00:00.000Z";
const periodStart = "2026-11-01T00:00:00.000Z";
const periodEnd = "2026-12-01T00:00:00.000Z";
const names = ["cloudflare_workers", "cloudflare_d1", "cloudflare_durable_objects"];

function snapshots(overrides = {}) {
  return names.map((name) => ({
    name, enabled: true, used: 10, limit: 100, observed_at: now,
    period_start: periodStart, period_end: periodEnd, ...overrides[name],
  }));
}
function evaluate(sources = snapshots(), extra = {}) {
  return evaluateBudgetGuard({ now, sources, globalHoldClear: true, ...extra });
}

test("CLEAR permits new tasks and Actions dispatch with all fresh required sources", () => {
  const result = evaluate();
  assert.equal(result.status, "CLEAR");
  assert.equal(result.allowNewTasks, true);
  assert.equal(result.allowActionsDispatch, true);
});
test("70% is WARN and permits work; 69.99% remains CLEAR", () => {
  assert.equal(evaluate(snapshots({ cloudflare_d1: { used: 69.99 } })).status, "CLEAR");
  const result = evaluate(snapshots({ cloudflare_d1: { used: 70 } }));
  assert.equal(result.status, "WARN");
  assert.equal(result.allowNewTasks, true);
  assert.equal(result.allowActionsDispatch, true);
});
test("80% and 89.99% suppress new tasks and dispatch", () => {
  for (const percent of [80, 89.99]) {
    const result = evaluate(snapshots({ cloudflare_durable_objects: { used: percent } }));
    assert.equal(result.status, "SUPPRESS");
    assert.equal(result.allowNewTasks, false);
    assert.equal(result.allowActionsDispatch, false);
  }
});
test("90%, values above 90%, and 100% STOP both task admission and Actions dispatch", () => {
  for (const percent of [90, 90.01, 95, 100]) {
    const result = evaluate(snapshots({ cloudflare_workers: { used: percent } }));
    assert.equal(result.status, "STOP", `percent=${percent}`);
    assert.equal(result.allowNewTasks, false, `task admission percent=${percent}`);
    assert.equal(result.allowActionsDispatch, false, `dispatch percent=${percent}`);
    assert.equal(result.reason, "budget_stop_threshold_reached");
  }
});
test("any one of the three spend domains at 90% stops the whole decision", () => {
  for (const name of names) {
    const result = evaluate(snapshots({ [name]: { used: 90 } }));
    assert.equal(result.status, "STOP", name);
    assert.equal(result.allowNewTasks, false, name);
    assert.equal(result.allowActionsDispatch, false, name);
  }
});
test("worst status wins when multiple sources cross thresholds", () => {
  const result = evaluate(snapshots({
    cloudflare_workers: { used: 70 },
    cloudflare_d1: { used: 80 },
    cloudflare_durable_objects: { used: 90 },
  }));
  assert.equal(result.status, "STOP");
  assert.equal(result.allowNewTasks, false);
  assert.equal(result.allowActionsDispatch, false);
});
test("missing telemetry and missing required sources fail closed", () => {
  assert.equal(evaluate(undefined).status, "BLOCKED");
  assert.equal(evaluate(snapshots().slice(0, 2)).reason, "required_usage_source_missing");
});
test("stale, too-far-future, malformed and out-of-period snapshots fail closed", () => {
  for (const override of [
    { observed_at: "2026-11-12T01:29:59.999Z" },
    { observed_at: "2026-11-12T03:05:00.001Z" },
    { used: -1 }, { limit: 0 },
    { period_start: "2026-12-01T00:00:00.000Z" },
    { period_end: now },
  ]) assert.equal(evaluate(snapshots({ cloudflare_workers: override })).status, "BLOCKED");
});
test("freshness and future-skew exact boundaries are accepted", () => {
  assert.equal(evaluate(snapshots({ cloudflare_workers: { observed_at: "2026-11-12T01:30:00.000Z" } })).status, "CLEAR");
  assert.equal(evaluate(snapshots({ cloudflare_workers: { observed_at: "2026-11-12T03:05:00.000Z" } })).status, "CLEAR");
});
test("unknown or telemetry-supplied disabled state blocks instead of bypassing a spend domain", () => {
  const unknown = snapshots();
  delete unknown[0].enabled;
  assert.equal(evaluate(unknown).status, "BLOCKED");
  const disabled = evaluate(snapshots({ cloudflare_durable_objects: { enabled: false } }));
  assert.equal(disabled.status, "BLOCKED");
  assert.equal(disabled.allowNewTasks, false);
  assert.equal(disabled.allowActionsDispatch, false);
});
test("Global HOLD, invalid failure count, and three consecutive failures block", () => {
  assert.equal(evaluate(snapshots(), { globalHoldClear: false }).status, "BLOCKED");
  assert.equal(evaluate(snapshots(), { consecutiveFailures: 2 }).status, "CLEAR");
  assert.equal(evaluate(snapshots(), { consecutiveFailures: 3 }).status, "BLOCKED");
  assert.equal(evaluate(snapshots(), { consecutiveFailures: -1 }).status, "BLOCKED");
});
test("duplicate sources and invalid thresholds fail closed", () => {
  const duplicate = snapshots();
  duplicate.push({ ...duplicate[0] });
  assert.equal(evaluate(duplicate).status, "BLOCKED");
  assert.equal(evaluate(snapshots(), { thresholds: { warn: 80, suppress: 70, stop: 90 } }).status, "BLOCKED");
});

test("each required source independently suppresses at 89.99% and stops at 90%", () => {
  for (const name of names) {
    const suppressed = evaluate(snapshots({ [name]: { used: 89.99 } }));
    assert.equal(suppressed.status, "SUPPRESS", name);
    assert.equal(suppressed.allowNewTasks, false, name);
    assert.equal(suppressed.allowActionsDispatch, false, name);
    const stopped = evaluate(snapshots({ [name]: { used: 90 } }));
    assert.equal(stopped.status, "STOP", name);
    assert.equal(stopped.allowNewTasks, false, name);
    assert.equal(stopped.allowActionsDispatch, false, name);
  }
});
test("a lower reading immediately below 90% does not resume work; below 80% returns WARN", () => {
  const stopped = evaluate(snapshots({ cloudflare_workers: { used: 90 } }));
  assert.equal(stopped.status, "STOP");
  const justBelowStop = evaluate(snapshots({ cloudflare_workers: { used: 89.99 } }));
  assert.equal(justBelowStop.status, "SUPPRESS");
  assert.equal(justBelowStop.allowNewTasks, false);
  assert.equal(justBelowStop.allowActionsDispatch, false);
  const belowSuppress = evaluate(snapshots({ cloudflare_workers: { used: 79.99 } }));
  assert.equal(belowSuppress.status, "WARN");
  assert.equal(belowSuppress.allowNewTasks, true);
  assert.equal(belowSuppress.allowActionsDispatch, true);
});
test("one source at the STOP threshold dominates two sources at zero usage", () => {
  const result = evaluate(snapshots({
    cloudflare_workers: { used: 0 },
    cloudflare_d1: { used: 0 },
    cloudflare_durable_objects: { used: 90 },
  }));
  assert.equal(result.status, "STOP");
  assert.equal(result.allowNewTasks, false);
  assert.equal(result.allowActionsDispatch, false);
});
