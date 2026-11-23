"""Post-recovery service assurance declarations (AI Factory Stages 681-690).

Validates caller-supplied evidence metadata only. It does not probe services,
measure SLOs, monitor telemetry, enforce change freezes, or operate rollback.
"""
from __future__ import annotations
import math
from datetime import datetime

REQUIRED = (
    "assurance_ref", "recovery_ref", "subject_ref", "assurance_window",
    "service_observations", "slo_results", "monitoring_coverage",
    "recurrence_checks", "change_control", "rollback_readiness",
    "impact_review", "followup_actions", "handover", "audit_ref",
    "automatic_enforcement", "created_at",
)
STATUSES = {"PASS_DECLARED", "FAIL_DECLARED", "UNKNOWN"}
def _text(v):
    return isinstance(v, str) and bool(v.strip())
def _time(v):
    if not _text(v): return None
    try: d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError: return None
    return d if d.tzinfo is not None else None
def _texts(v, allow_empty=False):
    return isinstance(v, list) and (allow_empty or bool(v)) and all(_text(x) for x in v) and len(v)==len(set(v))
def _finite(v):
    return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)

def validate_post_recovery_assurance(record):
    if not isinstance(record,dict):
        return {"status":"BLOCKED","missing":["record_not_object"],"issues":["invalid_record"]}
    missing=[k for k in REQUIRED if k not in record or record[k] is None]
    issues=[]
    for k in ("assurance_ref","recovery_ref","subject_ref","audit_ref"):
        if not _text(record.get(k)): issues.append(f"{k}_invalid")
    created=_time(record.get("created_at"))
    if created is None: issues.append("created_at_invalid")

    window=record.get("assurance_window")
    if not isinstance(window,dict):
        issues.append("assurance_window_invalid")
    else:
        start,end=_time(window.get("start")), _time(window.get("end"))
        if start is None or end is None or end<=start: issues.append("assurance_window_order_invalid")
        if created is not None and end is not None and end>created:
            issues.append("assurance_window_after_creation")
        if window.get("coverage_declared_complete") is not True:
            issues.append("assurance_window_incomplete")
        if not _text(window.get("schedule_ref")): issues.append("assurance_schedule_ref_invalid")

    observations=record.get("service_observations")
    if not isinstance(observations,list) or not observations:
        issues.append("service_observations_invalid"); observations=[]
    obs_refs=[]
    for item in observations:
        if not isinstance(item,dict):
            issues.append("service_observation_invalid"); continue
        for k in ("observation_ref","service_ref","observed_at","evidence_ref","observer_ref"):
            if not _text(item.get(k)): issues.append(f"observation_{k}_invalid")
        if _text(item.get("observation_ref")): obs_refs.append(item["observation_ref"])
        if _time(item.get("observed_at")) is None: issues.append("observation_time_invalid")
        if item.get("status") not in STATUSES: issues.append("observation_status_invalid")
        if item.get("probe_executed_by_validator") is not False:
            issues.append("validator_probe_must_not_be_claimed")
    if len(obs_refs)!=len(set(obs_refs)): issues.append("observation_refs_duplicate")

    slo=record.get("slo_results")
    if not isinstance(slo,list) or not slo:
        issues.append("slo_results_invalid"); slo=[]
    slo_refs=[]
    for item in slo:
        if not isinstance(item,dict):
            issues.append("slo_result_invalid"); continue
        for k in ("slo_ref","metric_ref","target","observed_value","unit","evidence_ref"):
            if k in ("target","observed_value","unit"):
                if not _finite(item.get(k)) if k!="unit" else not _text(item.get(k)):
                    issues.append(f"slo_{k}_invalid")
            elif not _text(item.get(k)):
                issues.append(f"slo_{k}_invalid")
        if _text(item.get("slo_ref")): slo_refs.append(item["slo_ref"])
        if item.get("comparison") not in ("AT_MOST","AT_LEAST","EQUALS"):
            issues.append("slo_comparison_invalid")
        if item.get("status") not in STATUSES: issues.append("slo_status_invalid")
        if item.get("measurement_verified") is not False:
            issues.append("slo_measurement_verification_must_not_be_claimed")
    if len(slo_refs)!=len(set(slo_refs)): issues.append("slo_refs_duplicate")

    coverage=record.get("monitoring_coverage")
    if not isinstance(coverage,dict):
        issues.append("monitoring_coverage_invalid")
    else:
        for k in ("required_signal_refs","observed_signal_refs","gap_refs"):
            if not _texts(coverage.get(k), allow_empty=(k=="gap_refs")):
                issues.append(f"monitoring_{k}_invalid")
        required=coverage.get("required_signal_refs")
        observed=coverage.get("observed_signal_refs")
        gaps=coverage.get("gap_refs")
        if isinstance(required,list) and isinstance(observed,list) and not set(required).issubset(set(observed)):
            issues.append("monitoring_required_signals_missing")
        if isinstance(gaps,list) and gaps: issues.append("monitoring_gaps_present")
        if coverage.get("coverage_verified") is not False:
            issues.append("monitoring_coverage_verification_must_not_be_claimed")

    recurrence=record.get("recurrence_checks")
    if not isinstance(recurrence,list) or not recurrence:
        issues.append("recurrence_checks_invalid"); recurrence=[]
    rec_refs=[]
    for item in recurrence:
        if not isinstance(item,dict):
            issues.append("recurrence_check_invalid"); continue
        for k in ("check_ref","failure_mode_ref","procedure_ref","evidence_ref"):
            if not _text(item.get(k)): issues.append(f"recurrence_{k}_invalid")
        if _text(item.get("check_ref")): rec_refs.append(item["check_ref"])
        if item.get("status") not in STATUSES: issues.append("recurrence_status_invalid")
        if item.get("status") != "PASS_DECLARED": issues.append("recurrence_not_pass_declared")
    if len(rec_refs)!=len(set(rec_refs)): issues.append("recurrence_refs_duplicate")

    change=record.get("change_control")
    if not isinstance(change,dict):
        issues.append("change_control_invalid")
    else:
        if change.get("freeze_status") not in ("ACTIVE_DECLARED","NOT_REQUIRED_DECLARED","EXPIRED_DECLARED"):
            issues.append("change_freeze_status_invalid")
        if not _text(change.get("policy_ref")): issues.append("change_policy_ref_invalid")
        if not _text(change.get("exception_register_ref")): issues.append("change_exception_register_invalid")
        if change.get("unapproved_changes_present") is not False:
            issues.append("unapproved_changes_must_be_absent")
        if change.get("enforced_by_validator") is not False:
            issues.append("validator_change_enforcement_must_be_false")

    rollback=record.get("rollback_readiness")
    if not isinstance(rollback,dict):
        issues.append("rollback_readiness_invalid")
    else:
        for k in ("plan_ref","recovery_point_ref","owner_ref","readiness_evidence_ref"):
            if not _text(rollback.get(k)): issues.append(f"rollback_{k}_invalid")
        if rollback.get("status") not in STATUSES: issues.append("rollback_readiness_status_invalid")
        if rollback.get("status") != "PASS_DECLARED": issues.append("rollback_not_pass_declared")
        if rollback.get("rollback_executed") is not False: issues.append("rollback_execution_must_not_be_claimed")

    impact=record.get("impact_review")
    if not isinstance(impact,dict):
        issues.append("impact_review_invalid")
    else:
        for k in ("customer_impact_ref","support_signal_ref","reviewer_ref"):
            if not _text(impact.get(k)): issues.append(f"impact_{k}_invalid")
        if impact.get("status") not in STATUSES: issues.append("impact_review_status_invalid")
        if impact.get("status") != "PASS_DECLARED": issues.append("impact_review_not_pass_declared")
        if impact.get("reviewer_authenticated") is not False:
            issues.append("impact_reviewer_authentication_must_not_be_claimed")

    actions=record.get("followup_actions")
    if not isinstance(actions,list):
        issues.append("followup_actions_invalid"); actions=[]
    action_refs=[]
    for item in actions:
        if not isinstance(item,dict):
            issues.append("followup_action_invalid"); continue
        for k in ("action_ref","owner_ref","due_at","tracking_ref"):
            if not _text(item.get(k)): issues.append(f"followup_{k}_invalid")
        if _text(item.get("action_ref")): action_refs.append(item["action_ref"])
        if _time(item.get("due_at")) is None: issues.append("followup_due_at_invalid")
        if item.get("status") not in ("OPEN","IN_PROGRESS","COMPLETED_DECLARED","CANCELLED_DECLARED"):
            issues.append("followup_status_invalid")
        if item.get("status")=="COMPLETED_DECLARED" and not _text(item.get("completion_evidence_ref")):
            issues.append("followup_completion_evidence_missing")
    if len(action_refs)!=len(set(action_refs)): issues.append("followup_action_refs_duplicate")

    handover=record.get("handover")
    if not isinstance(handover,dict):
        issues.append("handover_invalid")
    else:
        for k in ("receiving_owner_ref","runbook_ref","known_issues_ref","handover_evidence_ref"):
            if not _text(handover.get(k)): issues.append(f"handover_{k}_invalid")
        if handover.get("accepted_declared") is not True: issues.append("handover_not_accepted_declared")
        if handover.get("recipient_authenticated") is not False:
            issues.append("handover_authentication_must_not_be_claimed")

    if record.get("automatic_enforcement") is not False:
        issues.append("automatic_enforcement_must_be_false")
    if missing or issues:
        return {"status":"BLOCKED","missing":missing,"issues":sorted(set(issues))}
    return {"status":"DECLARATIONS_COMPLETE","missing":[],"issues":[],
            "live_monitoring_performed":False,"slo_values_independently_measured":False,
            "service_probed":False,"change_freeze_enforced":False}

def stage_690_post_recovery_gate(record):
    result=validate_post_recovery_assurance(record)
    ready=result["status"]=="DECLARATIONS_COMPLETE"
    return {**result,"gate":"READY_FOR_INDEPENDENT_REVIEW" if ready else "BLOCKED",
            "production_stability_certified":False,"automatic_enforcement":False,
            "rollback_executed":False}
