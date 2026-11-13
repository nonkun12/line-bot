"""Signed budget evidence verifier. Only the trusted collector may hold the HMAC key."""
import hashlib,hmac,json,re
from datetime import datetime,timedelta,timezone
from typing import Any
REQUIRED_SOURCES=("cloudflare_workers","cloudflare_d1","cloudflare_durable_objects")
MAX_AGE=timedelta(minutes=10)
class EvidenceRejected(ValueError): pass
def _dt(v):
    if not isinstance(v,str) or not v.strip(): raise EvidenceRejected("timestamp_missing_or_invalid")
    try: d=datetime.fromisoformat(v.replace("Z","+00:00"))
    except ValueError: raise EvidenceRejected("timestamp_missing_or_invalid") from None
    if d.tzinfo is None: raise EvidenceRejected("timestamp_timezone_missing")
    return d.astimezone(timezone.utc)
def verify(payload:Any,key:str,now:datetime):
    if not isinstance(payload,dict): raise EvidenceRejected("budget_snapshot_missing")
    if not isinstance(key,str) or len(key.encode())<32: raise EvidenceRejected("budget_evidence_verification_key_missing")
    if payload.get("schema_version")!=1 or payload.get("collector_id")!="orca-budget-collector": raise EvidenceRejected("budget_evidence_collector_identity_invalid")
    if not isinstance(payload.get("account_id"),str) or not payload["account_id"].strip(): raise EvidenceRejected("budget_evidence_account_identity_missing")
    sig=payload.get("signature")
    if not isinstance(sig,str) or not re.fullmatch(r"[0-9a-f]{64}",sig): raise EvidenceRejected("budget_evidence_signature_missing_or_invalid")
    unsigned={k:v for k,v in payload.items() if k!="signature"}
    try: raw=json.dumps(unsigned,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
    except (TypeError,ValueError): raise EvidenceRejected("budget_evidence_not_canonicalizable") from None
    if not hmac.compare_digest(sig,hmac.new(key.encode(),raw,hashlib.sha256).hexdigest()): raise EvidenceRejected("budget_evidence_signature_invalid")
    now=now.astimezone(timezone.utc); observed=_dt(payload.get("observed_at")); start=_dt(payload.get("period_start")); end=_dt(payload.get("period_end"))
    if observed>now+timedelta(minutes=5) or now-observed>MAX_AGE: raise EvidenceRejected("budget_snapshot_stale_or_future")
    if start>=end or not start<=now<end: raise EvidenceRejected("budget_period_not_current")
    rows=payload.get("sources")
    if not isinstance(rows,list): raise EvidenceRejected("budget_snapshot_missing")
    sources={}
    for row in rows:
        if not isinstance(row,dict) or not isinstance(row.get("name"),str) or not row["name"] or row["name"] in sources: raise EvidenceRejected("budget_source_identity_invalid")
        sources[row["name"]]=row
    if set(sources)!=set(REQUIRED_SOURCES): raise EvidenceRejected("budget_source_set_incomplete_or_unexpected")
    for name,row in sources.items():
        if row.get("enabled") is not True: raise EvidenceRejected("budget_source_not_confirmed_enabled")
        if row.get("quality")!="exact" or row.get("coverage_complete") is not True or row.get("exact_counter") is not True or row.get("sampling_mode")!="none": raise EvidenceRejected("budget_source_not_exact_and_complete")
        for f in ("source_api","unit","limit_source","limit_evidence_id"):
            if not isinstance(row.get(f),str) or not row[f].strip(): raise EvidenceRejected("budget_unit_or_limit_evidence_missing")
        count,digest=row.get("resource_count"),row.get("resource_digest")
        if isinstance(count,bool) or not isinstance(count,int) or count<0 or not isinstance(digest,str) or not re.fullmatch(r"[0-9a-f]{64}",digest): raise EvidenceRejected("budget_resource_coverage_invalid")
        watermark=_dt(row.get("source_watermark_at"))
        if watermark>now+timedelta(minutes=5) or now-watermark>MAX_AGE: raise EvidenceRejected("budget_source_watermark_stale_or_future")
        # Some providers expose source-specific quota windows. If either boundary
        # is supplied, require both and verify that the window contains `now`.
        # This prevents a fresh poll from masking an expired source period.
        has_start = "period_start" in row
        has_end = "period_end" in row
        if has_start != has_end:
            raise EvidenceRejected("budget_source_period_boundary_incomplete")
        if has_start:
            source_start = _dt(row.get("period_start"))
            source_end = _dt(row.get("period_end"))
            if source_start >= source_end or not source_start <= now < source_end:
                raise EvidenceRejected("budget_period_not_current")
    return payload
