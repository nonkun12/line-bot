"""Audit checkpoint anchoring and backup resilience (AI Factory Stages 771-780).

This module verifies caller-supplied external anchor receipts and performs local
SQLite backup/restore rehearsals. It never contacts an external anchor service.
"""
from __future__ import annotations
import hashlib, hmac, json, sqlite3, time
from pathlib import Path

def _canonical(obj):
    return json.dumps(obj,sort_keys=True,separators=(",",":"),ensure_ascii=False,
                      allow_nan=False).encode("utf-8")

def create_audit_checkpoint(ledger):
    if not hasattr(ledger,"audit_report") or not hasattr(ledger,"_connect"):
        return {"status":"BLOCKED","issues":["ledger_interface_invalid"]}
    report=ledger.audit_report()
    integrity=ledger.integrity_check()
    if report.get("status")!="PASS" or integrity.get("status")!="PASS":
        return {"status":"BLOCKED","issues":["ledger_integrity_not_verified"]}
    with ledger._connect() as c:
        nonce_count=c.execute("SELECT COUNT(*) FROM nonces").fetchone()[0]
    checkpoint={"format":"ai-factory-audit-checkpoint-v1",
        "schema_version":integrity.get("schema_version"),
        "event_count":report.get("events"),"audit_head_hash":report.get("head_hash"),
        "nonce_count":nonce_count}
    return {"status":"READY_FOR_EXTERNAL_ANCHOR","checkpoint":checkpoint,
            "checkpoint_sha256":hashlib.sha256(_canonical(checkpoint)).hexdigest(),
            "externally_anchored":False}

def verify_anchor_receipt(checkpoint_result,receipt,anchor_key,now_epoch=None,
                          max_age_seconds=86400):
    issues=[]
    if not isinstance(checkpoint_result,dict) or checkpoint_result.get("status")!="READY_FOR_EXTERNAL_ANCHOR":
        issues.append("checkpoint_not_ready")
    checkpoint=checkpoint_result.get("checkpoint") if isinstance(checkpoint_result,dict) else None
    digest=hashlib.sha256(_canonical(checkpoint)).hexdigest() if isinstance(checkpoint,dict) else None
    if not isinstance(receipt,dict): receipt={}
    required=("provider_ref","anchor_ref","checkpoint_sha256","anchored_at_epoch","signature")
    for field in required:
        if field not in receipt: issues.append(f"receipt_{field}_missing")
    if receipt.get("checkpoint_sha256")!=digest: issues.append("anchor_checkpoint_digest_mismatch")
    key_id=receipt.get("key_id")
    if not isinstance(key_id,str) or not key_id.strip(): issues.append("anchor_key_id_missing")
    if not isinstance(anchor_key,(bytes,bytearray)) or len(anchor_key)<32:
        issues.append("anchor_verification_key_invalid")
    ts=receipt.get("anchored_at_epoch")
    if not isinstance(ts,(int,float)) or isinstance(ts,bool):
        issues.append("anchor_timestamp_invalid")
    else:
        now=time.time() if now_epoch is None else float(now_epoch)
        if ts>now: issues.append("anchor_timestamp_in_future")
        if now-ts>max_age_seconds: issues.append("anchor_receipt_too_old")
    signed={k:v for k,v in receipt.items() if k!="signature"}
    if isinstance(anchor_key,(bytes,bytearray)) and len(anchor_key)>=32:
        expected=hmac.new(bytes(anchor_key),b"AI_FACTORY_EXTERNAL_ANCHOR_V1\n"+_canonical(signed),hashlib.sha256).hexdigest()
        sig=receipt.get("signature")
        if not isinstance(sig,str) or not hmac.compare_digest(sig,expected):
            issues.append("anchor_receipt_signature_invalid")
    return {"status":"PASS" if not issues else "BLOCKED",
            "issues":sorted(set(issues)),"anchor_receipt_verified":not issues,
            "external_service_identity_authenticated":False}

def create_sqlite_backup(ledger,destination_path):
    if not hasattr(ledger,"_connect") or not isinstance(destination_path,(str,Path)):
        return {"status":"BLOCKED","issues":["backup_arguments_invalid"]}
    destination=Path(destination_path)
    if destination.resolve()==Path(ledger.path).resolve():
        return {"status":"BLOCKED","issues":["backup_destination_must_differ"]}
    destination.parent.mkdir(parents=True,exist_ok=True)
    try:
        with ledger._connect() as source, sqlite3.connect(str(destination)) as target:
            source.backup(target)
        with sqlite3.connect(str(destination)) as check:
            integrity=check.execute("PRAGMA integrity_check").fetchone()[0]
            event_count=check.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
            nonce_count=check.execute("SELECT COUNT(*) FROM nonces").fetchone()[0]
            head=check.execute("SELECT event_hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        digest=hashlib.sha256(destination.read_bytes()).hexdigest()
        return {"status":"PASS" if integrity=="ok" else "BLOCKED",
                "backup_sha256":digest,"event_count":event_count,"nonce_count":nonce_count,
                "audit_head_hash":head[0] if head else "0"*64,
                "backup_path":str(destination),"issues":[] if integrity=="ok" else ["backup_integrity_failure"]}
    except (OSError,sqlite3.Error):
        return {"status":"BLOCKED","issues":["backup_operation_failed"]}

def verify_sqlite_backup(backup_path,expected_manifest):
    try:
        path=Path(backup_path)
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        with sqlite3.connect(str(path)) as c:
            integrity=c.execute("PRAGMA integrity_check").fetchone()[0]
            events=c.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
            nonces=c.execute("SELECT COUNT(*) FROM nonces").fetchone()[0]
            rows=c.execute("SELECT event,previous_hash,event_hash FROM audit ORDER BY seq").fetchall()
    except (OSError,sqlite3.Error):
        return {"status":"BLOCKED","issues":["backup_unreadable"]}
    prev="0"*64; issues=[]
    for event,declared_prev,declared_hash in rows:
        expected=hashlib.sha256(prev.encode()+b"\n"+bytes(event)).hexdigest()
        if declared_prev!=prev or declared_hash!=expected: issues.append("backup_audit_chain_invalid")
        prev=declared_hash
    if integrity!="ok": issues.append("backup_sqlite_integrity_failure")
    if not isinstance(expected_manifest,dict): issues.append("backup_manifest_invalid")
    else:
        for field,value in (("backup_sha256",digest),("event_count",events),
                            ("nonce_count",nonces),("audit_head_hash",prev)):
            if expected_manifest.get(field)!=value: issues.append(f"backup_{field}_mismatch")
    return {"status":"PASS" if not issues else "BLOCKED","issues":sorted(set(issues)),
            "backup_sha256":digest,"event_count":events,"nonce_count":nonces,
            "audit_head_hash":prev}

def rehearse_sqlite_restore(backup_path,restore_path,expected_manifest):
    source=Path(backup_path); target=Path(restore_path)
    if source.resolve()==target.resolve():
        return {"status":"BLOCKED","issues":["restore_target_must_differ"]}
    verified=verify_sqlite_backup(source,expected_manifest)
    if verified["status"]!="PASS":
        return {"status":"BLOCKED","issues":["backup_verification_failed"]}
    try:
        target.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(str(source)) as src, sqlite3.connect(str(target)) as dst:
            src.backup(dst)
        restored=verify_sqlite_backup(target,expected_manifest)
    except (OSError,sqlite3.Error):
        return {"status":"BLOCKED","issues":["restore_rehearsal_failed"]}
    return {"status":"PASS" if restored["status"]=="PASS" else "BLOCKED",
            "issues":restored["issues"],"restore_verified":restored["status"]=="PASS",
            "restore_path":str(target),"production_restore_performed":False}

def validate_retention_policy(policy):
    issues=[]
    if not isinstance(policy,dict): return {"status":"BLOCKED","issues":["retention_policy_invalid"]}
    for field in ("minimum_backup_copies","maximum_backup_age_days","audit_retention_days"):
        value=policy.get(field)
        if not isinstance(value,int) or isinstance(value,bool) or value<=0:
            issues.append(f"{field}_invalid")
    if policy.get("offsite_copy_required") is not True: issues.append("offsite_copy_not_required")
    if policy.get("restore_test_interval_days",0)<=0: issues.append("restore_test_interval_invalid")
    return {"status":"PASS" if not issues else "BLOCKED","issues":sorted(set(issues))}

def stage_780_resilience_gate(checkpoint,anchor_receipt_result,backup_result,
                              restore_result,retention_result):
    checks={"checkpoint":isinstance(checkpoint,dict) and checkpoint.get("status")=="READY_FOR_EXTERNAL_ANCHOR",
            "anchor":isinstance(anchor_receipt_result,dict) and anchor_receipt_result.get("status")=="PASS",
            "backup":isinstance(backup_result,dict) and backup_result.get("status")=="PASS",
            "restore":isinstance(restore_result,dict) and restore_result.get("status")=="PASS",
            "retention":isinstance(retention_result,dict) and retention_result.get("status")=="PASS"}
    issues=[f"{k}_not_verified" for k,v in checks.items() if not v]
    return {"status":"READY_FOR_EXTERNAL_REVIEW" if not issues else "BLOCKED",
            "checks":checks,"issues":issues,"production_restore_performed":False,
            "external_anchor_write_performed":False,"authorization_granted":False}
