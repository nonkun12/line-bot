"""Durable replay protection and lifecycle controls (Stages 761-770).

SQLite is the standard-library reference store. The caller owns the database path,
backup, filesystem permissions, and trust-policy/key provisioning. The module does
not store key material or claim tamper-proof audit or distributed consensus.
"""
from __future__ import annotations
import hashlib, json, sqlite3, time
from pathlib import Path
from datetime import datetime, timezone
from contextlib import contextmanager

SCHEMA_VERSION=1

def _canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,
                      allow_nan=False).encode("utf-8")

class SQLiteReplayLedger:
    """Transactional, process-safe nonce ledger backed by a local SQLite database."""
    def __init__(self, database_path, timeout_seconds=5.0):
        if not isinstance(database_path,(str,Path)) or str(database_path).strip() in ("",":memory:"):
            raise ValueError("persistent_database_path_required")
        self.path=str(database_path); self.timeout=float(timeout_seconds)
        if self.timeout<=0: raise ValueError("timeout_must_be_positive")
        self._initialize()

    def _connect(self):
        conn=sqlite3.connect(self.path,timeout=self.timeout,isolation_level=None)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=%d" % int(self.timeout*1000))
        return conn

    def _initialize(self):
        with self._connect() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            c.execute("CREATE TABLE IF NOT EXISTS nonces (namespace TEXT NOT NULL, nonce TEXT NOT NULL, expires_at REAL NOT NULL, PRIMARY KEY(namespace,nonce))")
            c.execute("CREATE TABLE IF NOT EXISTS audit (seq INTEGER PRIMARY KEY AUTOINCREMENT, event BLOB NOT NULL, previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL UNIQUE)")
            row=c.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
            if row is None: c.execute("INSERT INTO metadata(key,value) VALUES('schema_version',?)",(str(SCHEMA_VERSION),))
            elif row[0]!=str(SCHEMA_VERSION): raise RuntimeError("unsupported_schema_version")

    @contextmanager
    def _transaction(self):
        c=self._connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
        finally: c.close()

    def consume(self,namespace,nonce,expires_at,now=None):
        if not all(isinstance(x,str) and x.strip() for x in (namespace,nonce)):
            raise ValueError("namespace_and_nonce_required")
        if not isinstance(expires_at,(int,float)) or isinstance(expires_at,bool):
            raise ValueError("expires_at_epoch_required")
        current=time.time() if now is None else float(now)
        expiry=float(expires_at)
        if expiry<=current: return False
        with self._transaction() as c:
            c.execute("DELETE FROM nonces WHERE expires_at<=?",(current,))
            try:
                c.execute("INSERT INTO nonces(namespace,nonce,expires_at) VALUES(?,?,?)",
                          (namespace,nonce,expiry))
            except sqlite3.IntegrityError:
                return False
        return True

    def consume_with_audit(self,namespace,nonce,expires_at,event,now=None):
        if not isinstance(event,dict): raise ValueError("audit_event_must_be_object")
        current=time.time() if now is None else float(now)
        expiry=float(expires_at)
        if expiry<=current: return {"consumed":False,"reason":"nonce_expired"}
        safe_event={k:v for k,v in event.items() if k.lower() not in {"key","secret","token","signature","mac","private_key"}}
        with self._transaction() as c:
            c.execute("DELETE FROM nonces WHERE expires_at<=?",(current,))
            try: c.execute("INSERT INTO nonces(namespace,nonce,expires_at) VALUES(?,?,?)",(namespace,nonce,expiry))
            except sqlite3.IntegrityError: return {"consumed":False,"reason":"replay"}
            previous=c.execute("SELECT event_hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
            prev=previous[0] if previous else "0"*64
            raw=_canonical(safe_event)
            digest=hashlib.sha256(prev.encode()+b"\n"+raw).hexdigest()
            c.execute("INSERT INTO audit(event,previous_hash,event_hash) VALUES(?,?,?)",(raw,prev,digest))
        return {"consumed":True,"audit_hash":digest}

    def audit_report(self):
        with self._connect() as c:
            rows=c.execute("SELECT seq,event,previous_hash,event_hash FROM audit ORDER BY seq").fetchall()
        prev="0"*64; issues=[]
        for seq,event,declared_prev,declared_hash in rows:
            expected=hashlib.sha256(prev.encode()+b"\n"+bytes(event)).hexdigest()
            if declared_prev!=prev or declared_hash!=expected: issues.append("audit_chain_integrity_failure")
            prev=declared_hash
        return {"status":"PASS" if not issues else "BLOCKED","events":len(rows),
                "issues":sorted(set(issues)),"head_hash":prev,"externally_anchored":False}

    def integrity_check(self):
        with self._connect() as c:
            result=c.execute("PRAGMA integrity_check").fetchone()[0]
        return {"status":"PASS" if result=="ok" else "BLOCKED",
                "sqlite_integrity":result,"schema_version":SCHEMA_VERSION}

def validate_key_lifecycle(key_entry,now):
    issues=[]
    if not isinstance(key_entry,dict): return {"status":"BLOCKED","issues":["key_entry_invalid"]}
    if key_entry.get("status")!="ACTIVE": issues.append("key_not_active")
    def parse(v):
        try:
            d=datetime.fromisoformat(v.replace("Z","+00:00"))
            return d.astimezone(timezone.utc) if d.tzinfo else None
        except (AttributeError,ValueError): return None
    n=parse(now); start=parse(key_entry.get("not_before")); end=parse(key_entry.get("not_after"))
    if n is None: issues.append("verification_time_invalid")
    if start is None: issues.append("key_not_before_invalid")
    if end is None: issues.append("key_not_after_invalid")
    if start and end and end<=start: issues.append("key_validity_window_invalid")
    if n and start and n<start: issues.append("key_not_yet_valid")
    if n and end and n>=end: issues.append("key_expired")
    if not isinstance(key_entry.get("key_version"),str) or not key_entry["key_version"].strip():
        issues.append("key_version_missing")
    return {"status":"PASS" if not issues else "BLOCKED","issues":sorted(set(issues))}

def stage_770_durable_attestation_gate(attestation_result,ledger,namespace,nonce,
                                       expires_at_epoch,audit_context,now_epoch=None):
    issues=[]
    if not isinstance(attestation_result,dict) or attestation_result.get("status")!="PASS":
        issues.append("cryptographic_attestation_not_verified")
    if not isinstance(ledger,SQLiteReplayLedger): issues.append("trusted_replay_ledger_unavailable")
    if issues:
        return {"status":"BLOCKED","issues":issues,"nonce_consumed":False,
                "authorization_granted":False}
    event={"event":"attestation_nonce_consumed","namespace":namespace,
           "nonce_digest":hashlib.sha256(str(nonce).encode()).hexdigest(),
           "context":audit_context if isinstance(audit_context,dict) else {}}
    try:
        result=ledger.consume_with_audit(namespace,nonce,expires_at_epoch,event,now_epoch)
    except (ValueError,TypeError,sqlite3.Error):
        return {"status":"BLOCKED","issues":["replay_ledger_operation_failed"],
                "nonce_consumed":False,"authorization_granted":False}
    if not result.get("consumed"):
        return {"status":"BLOCKED","issues":["nonce_replay_or_expired"],
                "nonce_consumed":False,"authorization_granted":False}
    audit=ledger.audit_report()
    if audit["status"]!="PASS":
        return {"status":"BLOCKED","issues":["audit_chain_integrity_failure"],
                "nonce_consumed":True,"authorization_granted":False,
                "audit_hash":result["audit_hash"]}
    return {"status":"REPLAY_PROTECTED","issues":[],"nonce_consumed":True,
            "authorization_granted":False,"audit_hash":result["audit_hash"],
            "audit_events":audit["events"],"audit_externally_anchored":False}
