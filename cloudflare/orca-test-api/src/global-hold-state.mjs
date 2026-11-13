/** Normalize broker HOLD state without inventing a zero unresolved-operation count. */
export function normalizeGlobalHoldState(state) {
  if (!state || typeof state !== "object" || Array.isArray(state)) {
    return { clear: false, value: null, unresolved_operations: null };
  }
  const unresolved = state.unresolved_operations;
  const validCount = Number.isSafeInteger(unresolved) && unresolved >= 0;
  return {
    clear: state.clear === true && state.value === "off" && state.blocked === false &&
      validCount && unresolved === 0,
    value: typeof state.value === "string" ? state.value : null,
    unresolved_operations: validCount ? unresolved : null,
  };
}
