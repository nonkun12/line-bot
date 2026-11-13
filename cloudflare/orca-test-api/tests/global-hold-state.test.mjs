import test from "node:test";
import assert from "node:assert/strict";
import { normalizeGlobalHoldState } from "../src/global-hold-state.mjs";

test("only explicit clear HOLD with zero unresolved operations is clear", () => {
  assert.deepEqual(
    normalizeGlobalHoldState({ clear: true, value: "off", blocked: false, unresolved_operations: 0 }),
    { clear: true, value: "off", unresolved_operations: 0 },
  );
  assert.equal(
    normalizeGlobalHoldState({ clear: true, value: "off", blocked: false, unresolved_operations: 1 }).clear,
    false,
  );
});

test("missing, malformed, negative, and unsafe unresolved counts fail closed", () => {
  const base = { clear: true, value: "off", blocked: false };
  for (const value of [
    { ...base },
    { ...base, unresolved_operations: null },
    { ...base, unresolved_operations: "0" },
    { ...base, unresolved_operations: -1 },
    { ...base, unresolved_operations: Number.MAX_SAFE_INTEGER + 1 },
  ]) {
    const result = normalizeGlobalHoldState(value);
    assert.equal(result.clear, false);
    assert.equal(result.unresolved_operations, null);
  }
});

test("missing or contradictory HOLD state fails closed", () => {
  for (const value of [null, undefined, {}, [], { clear: true, value: "on", blocked: false, unresolved_operations: 0 },
    { clear: true, value: "off", blocked: true, unresolved_operations: 0 }]) {
    assert.equal(normalizeGlobalHoldState(value).clear, false);
  }
});
