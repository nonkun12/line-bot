"""Trust drift monitoring declarations (AI Factory Stages 651-660).

Validates supplied monitoring/event metadata only; no live monitoring,
source authentication, revocation lookup, quarantine, or remediation occurs.
"""
from __future__ import annotations
import re
from datetime import datetime

REQUIRED = (
    "monitor_ref", "subject_ref", "trust_evaluation_ref", "policy_ref",
    "monitoring_window", "events", "source_attestations", "impact_scope",
    "reassessment", "containment", "closure", "audit_ref",
    "automatic_action", "created_at",
)
EVENT_TYPES = {
    "ATTESTATION_REVOKED", "KEY_COMPROMISE_DECLARED", "POLICY_CHANGED",
    "EVIDENCE_EXPIRED", "SCOPE_CHANGED", "CONFLICT_DISCOVERED",
    "INTEGRITY_ALERT", "SOURCE_UNAVAILABLE", "OTHER",
}
SEVERITIES = {"INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN"}
CONTAINMENT = {"NOT_REQUIRED_DECLARED", "RECOMMENDED", "REQUESTED", "APPLIED_DECLARED", "UNKNOWN"}
CLOSURE = {"OPEN", "RESOLVED_DECLARED", "DISMISSED_DECLARED", "SUPERSEDED_DECLARED"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")

def _text(v):
    return isinstance(v, str) and bool(v.strip())

def _time(v):
    if not _text(v): return None
    try: d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError: return None
    return d if d.tzinfo is not None else None

def _text_list(v, allow_empty=False):
    return (isinstance(v, list) and (allow_empty or bool(v))
            and all(_text(x) for x in v) and len(v) == len(set(v)))

def validate_trust_drift_monitor(record):
    if not isinstance(record, dict):
        return {"status":"BLOCKED","missing":["record_not_object"],"issues":["invalid_record"]}
    missing=[k for k in REQUIRED if k not in record or record[k] is None]
    issues=[]
    for k in ("monitor_ref","subject_ref","trust_evaluation_ref","policy_ref","audit_ref"):
        if not _text(record.get(k)): issues.append(f"{k}_invalid")
    created=_time(record.get("created_at"))
    if created is None: issues.append("created_at_invalid")

    window=record.get("monitoring_window")
    if not isinstance(window,dict):
        issues.append("monitoring_window_invalid")
    else:
        start,end=_time(window.get("start")), _time(window.get("end"))
        if start is None or end is None or end<=start: issues.append("monitoring_window_order_invalid")
        if created is not None and end is not None and end>created:
            issues.append("monitoring_window_after_record_creation")
        if window.get("coverage_declared_complete") is not True:
            issues.append("monitoring_window_coverage_incomplete")
        if not _text(window.get("schedule_ref")): issues.append("monitoring_schedule_ref_invalid")

    events=record.get("events")
    if not isinstance(events,list) or not events:
        issues.append("events_invalid")
        events=[]
    event_ids=[]
    previous=None
    for e in events:
        if not isinstance(e,dict):
            issues.append("event_record_invalid"); continue
        for k in ("event_ref","source_ref","observed_at","recorded_at","summary_ref"):
            if not _text(e.get(k)): issues.append(f"event_{k}_invalid")
        if _text(e.get("event_ref")): event_ids.append(e["event_ref"])
        if e.get("event_type") not in EVENT_TYPES: issues.append("event_type_invalid")
        if e.get("severity") not in SEVERITIES: issues.append("event_severity_invalid")
        observed,recorded=_time(e.get("observed_at")),_time(e.get("recorded_at"))
        if observed is None: issues.append("event_observed_at_invalid")
        if recorded is None: issues.append("event_recorded_at_invalid")
        if observed is not None and recorded is not None and recorded<observed:
            issues.append("event_recorded_before_observed")
        if observed is not None and previous is not None and observed<previous:
            issues.append("event_order_invalid")
        if observed is not None: previous=observed
        if e.get("status") not in ("ACTIVE_DECLARED","RESOLVED_DECLARED","DISMISSED_DECLARED"):
            issues.append("event_status_invalid")
        if e.get("source_authenticated") is not False:
            issues.append("source_authentication_must_not_be_claimed")
    if len(event_ids)!=len(set(event_ids)): issues.append("event_refs_duplicate")

    sources=record.get("source_attestations")
    if not isinstance(sources,list) or not sources:
        issues.append("source_attestations_invalid")
        sources=[]
    source_refs=[]
    for s in sources:
        if not isinstance(s,dict):
            issues.append("source_attestation_invalid"); continue
        for k in ("source_ref","provenance_ref","captured_at"):
            if not _text(s.get(k)): issues.append(f"source_{k}_invalid")
        if _text(s.get("source_ref")): source_refs.append(s["source_ref"])
        if not _text(s.get("content_digest")) or not HEX64.fullmatch(s.get("content_digest","")):
            issues.append("source_content_digest_invalid")
        if s.get("integrity_verified") is not False:
            issues.append("source_integrity_verification_must_not_be_claimed")
    if len(source_refs)!=len(set(source_refs)): issues.append("source_refs_duplicate")
    if isinstance(events,list):
        known=set(source_refs)
        for e in events:
            if isinstance(e,dict) and _text(e.get("source_ref")) and known and e["source_ref"] not in known:
                issues.append("event_source_not_declared")

    impact=record.get("impact_scope")
    if not isinstance(impact,dict):
        issues.append("impact_scope_invalid")
    else:
        for k in ("resource_refs","claim_refs"):
            if not _text_list(impact.get(k)): issues.append(f"impact_{k}_invalid")
        if impact.get("wildcard") is not False: issues.append("impact_wildcard_must_be_false")
        if impact.get("blast_radius") not in ("SINGLE_SUBJECT","BOUNDED_SET","UNKNOWN"):
            issues.append("impact_blast_radius_invalid")

    reassess=record.get("reassessment")
    if not isinstance(reassess,dict):
        issues.append("reassessment_invalid")
    else:
        due=_time(reassess.get("due_at"))
        if due is None: issues.append("reassessment_due_at_invalid")
        if created is not None and due is not None and due<created:
            issues.append("reassessment_due_before_creation")
        if not _text(reassess.get("owner_ref")): issues.append("reassessment_owner_invalid")
        if not _text(reassess.get("procedure_ref")): issues.append("reassessment_procedure_invalid")
        if reassess.get("required") is not True: issues.append("reassessment_must_be_required")
        if reassess.get("triggered_by_event_refs") is not None:
            if not _text_list(reassess.get("triggered_by_event_refs")):
                issues.append("reassessment_event_refs_invalid")
            elif not set(reassess["triggered_by_event_refs"]).issubset(set(event_ids)):
                issues.append("reassessment_unknown_event_ref")

    containment=record.get("containment")
    if not isinstance(containment,dict):
        issues.append("containment_invalid")
    else:
        if containment.get("status") not in CONTAINMENT: issues.append("containment_status_invalid")
        if containment.get("status") in ("RECOMMENDED","REQUESTED","APPLIED_DECLARED"):
            if not _text(containment.get("action_ref")): issues.append("containment_action_ref_invalid")
        if containment.get("executed_by_system") is not False:
            issues.append("automatic_containment_must_be_false")
        if containment.get("authorization_ref") is not None and not _text(containment.get("authorization_ref")):
            issues.append("containment_authorization_ref_invalid")

    closure=record.get("closure")
    if not isinstance(closure,dict):
        issues.append("closure_invalid")
    else:
        if closure.get("status") not in CLOSURE: issues.append("closure_status_invalid")
        if closure.get("status") in ("RESOLVED_DECLARED","DISMISSED_DECLARED","SUPERSEDED_DECLARED"):
            if not _text(closure.get("resolution_ref")): issues.append("closure_resolution_ref_missing")
        if closure.get("status")=="RESOLVED_DECLARED" and any(
            isinstance(e,dict) and e.get("status")=="ACTIVE_DECLARED" for e in events
        ):
            issues.append("resolved_with_active_events")

    if record.get("automatic_action") is not False:
        issues.append("automatic_action_must_be_false")
    if missing or issues:
        return {"status":"BLOCKED","missing":missing,"issues":sorted(set(issues))}
    return {"status":"DECLARATIONS_COMPLETE","missing":[],"issues":[],
            "live_monitoring_performed":False,"event_sources_authenticated":False,
            "event_payloads_verified":False,"revocation_checked_live":False}

def stage_660_trust_drift_gate(record):
    result=validate_trust_drift_monitor(record)
    ready=result["status"]=="DECLARATIONS_COMPLETE"
    return {**result,
            "gate":"READY_FOR_INDEPENDENT_REVIEW" if ready else "BLOCKED",
            "trust_suspended":False,"quarantine_executed":False,
            "remediation_executed":False,"automatic_action":False}
