const REQUIRED_SOURCES = Object.freeze(["cloudflare_workers", "cloudflare_d1", "github_actions"]);
const DEFAULT_THRESHOLDS = Object.freeze({ warn: 70, suppress: 80, stop: 90 });
const MAX_SNAPSHOT_AGE_MS = 90 * 60 * 1000;
const MAX_FUTURE_SKEW_MS = 5 * 60 * 1000;

function validDate(value) {
  const time = typeof value === "string" || value instanceof Date ? Date.parse(value) : NaN;
  return Number.isFinite(time) ? time : null;
}

function blocked(reason, details = []) {
  return { status: "BLOCKED", allowNewTasks: false, allowActionsDispatch: false, reason, sources: details };
}

/** Pure evaluator: no network, AI inference, retries, or state mutation. Unknown telemetry fails closed. */
export function evaluateBudgetGuard({ now = new Date(), sources, globalHoldClear, consecutiveFailures = 0,
  requiredSources = REQUIRED_SOURCES, thresholds = DEFAULT_THRESHOLDS, maxSnapshotAgeMs = MAX_SNAPSHOT_AGE_MS } = {}) {
  const nowMs = validDate(now);
  if (nowMs === null) return blocked("clock_unavailable");
  if (globalHoldClear !== true) return blocked("global_hold_active_or_unknown");
  if (!Number.isInteger(consecutiveFailures) || consecutiveFailures < 0) return blocked("failure_counter_invalid");
  if (consecutiveFailures >= 3) return blocked("consecutive_failure_limit_reached");
  if (!Array.isArray(requiredSources) || requiredSources.length === 0 || requiredSources.some((n) => typeof n !== "string" || !n) || new Set(requiredSources).size !== requiredSources.length) return blocked("required_source_configuration_invalid");
  if (!Array.isArray(sources)) return blocked("usage_telemetry_missing");
  if (!thresholds || ![thresholds.warn, thresholds.suppress, thresholds.stop].every(Number.isFinite) || !(0 <= thresholds.warn && thresholds.warn < thresholds.suppress && thresholds.suppress < thresholds.stop && thresholds.stop <= 100)) return blocked("threshold_configuration_invalid");
  if (!Number.isFinite(maxSnapshotAgeMs) || maxSnapshotAgeMs <= 0) return blocked("snapshot_freshness_configuration_invalid");
  const byName = new Map();
  for (const source of sources) {
    if (!source || typeof source.name !== "string" || !source.name || byName.has(source.name)) return blocked("usage_source_identity_invalid");
    byName.set(source.name, source);
  }
  const details = [];
  for (const name of requiredSources) {
    const source = byName.get(name);
    if (!source) return blocked("required_usage_source_missing", details.concat({ name }));
    if (source.enabled === false) return blocked("usage_source_disabled_without_trusted_operator_config", details.concat({ name, enabled: false }));
    if (source.enabled !== true) return blocked("usage_source_enabled_state_unknown", details.concat({ name }));
    const used = source.used, limit = source.limit;
    const observedAt = validDate(source.observed_at), periodStart = validDate(source.period_start), periodEnd = validDate(source.period_end);
    if (!Number.isFinite(used) || used < 0 || !Number.isFinite(limit) || limit <= 0 || observedAt === null || periodStart === null || periodEnd === null || periodStart >= periodEnd) return blocked("usage_snapshot_invalid", details.concat({ name }));
    if (observedAt > nowMs + MAX_FUTURE_SKEW_MS || nowMs - observedAt > maxSnapshotAgeMs) return blocked("usage_snapshot_stale_or_future", details.concat({ name }));
    if (nowMs < periodStart || nowMs >= periodEnd) return blocked("usage_period_not_current", details.concat({ name }));
    const percent = used / limit * 100;
    const status = percent >= thresholds.stop ? "STOP" : percent >= thresholds.suppress ? "SUPPRESS" : percent >= thresholds.warn ? "WARN" : "CLEAR";
    details.push({ name, enabled: true, used, limit, percent, status, observed_at: source.observed_at });
  }
  if (!details.some((item) => item.enabled === true)) return blocked("no_enabled_budget_sources", details);
  const rank = { CLEAR: 0, WARN: 1, SUPPRESS: 2, STOP: 3 };
  const worst = details.reduce((current, item) => item.enabled === true && rank[item.status] > rank[current] ? item.status : current, "CLEAR");
  return { status: worst, allowNewTasks: worst === "CLEAR" || worst === "WARN", allowActionsDispatch: worst === "CLEAR" || worst === "WARN",
    reason: worst === "CLEAR" ? "within_budget" : worst === "WARN" ? "budget_warning_threshold_reached" : worst === "SUPPRESS" ? "budget_suppression_threshold_reached" : "budget_stop_threshold_reached",
    sources: details };
}

export { DEFAULT_THRESHOLDS, REQUIRED_SOURCES, MAX_SNAPSHOT_AGE_MS };
