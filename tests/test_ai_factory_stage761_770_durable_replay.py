import importlib.util, threading
from pathlib import Path
import pytest
p=Path(__file__).parents[1]/"core/ai_factory_stage761_770_durable_replay.py"
s=importlib.util.spec_from_file_location("stage761",p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)

def ledger(tmp_path): return m.SQLiteReplayLedger(tmp_path/"replay.sqlite")
def test_nonce_persists_across_instances(tmp_path):
 a=ledger(tmp_path); assert a.consume("issuer/a","nonce-123456789012",9999999999,100)
 b=ledger(tmp_path); assert not b.consume("issuer/a","nonce-123456789012",9999999999,100)
 assert b.consume("issuer/b","nonce-123456789012",9999999999,100)

def test_expired_nonce_is_not_consumed(tmp_path):
 assert not ledger(tmp_path).consume("n","nonce-123456789012",99,100)

def test_atomic_concurrent_consumption(tmp_path):
 l=ledger(tmp_path); outcomes=[]
 def run(): outcomes.append(l.consume("n","nonce-concurrent-123456",9999999999,100))
 ts=[threading.Thread(target=run) for _ in range(8)]
 [t.start() for t in ts]; [t.join() for t in ts]
 assert outcomes.count(True)==1

def test_consume_and_audit_are_atomic_and_redacted(tmp_path):
 l=ledger(tmp_path)
 r=l.consume_with_audit("n","nonce-123456789012",9999999999,
   {"event":"verified","secret":"DO_NOT_LOG","signature":"private"},100)
 assert r["consumed"] is True
 assert l.audit_report()["status"]=="PASS"
 with l._connect() as c:
  raw=c.execute("SELECT event FROM audit").fetchone()[0]
 assert b"DO_NOT_LOG" not in raw and b"private" not in raw

def test_replay_does_not_add_second_audit_event(tmp_path):
 l=ledger(tmp_path)
 event={"event":"accepted"}
 assert l.consume_with_audit("n","nonce-123456789012",9999999999,event,100)["consumed"]
 assert not l.consume_with_audit("n","nonce-123456789012",9999999999,event,100)["consumed"]
 assert l.audit_report()["events"]==1

def test_integrity_check_and_audit_chain(tmp_path):
 l=ledger(tmp_path); l.consume_with_audit("n","nonce-123456789012",9999999999,{"event":"x"},100)
 assert l.integrity_check()["status"]=="PASS"
 assert l.audit_report()["status"]=="PASS"

def test_key_lifecycle_boundaries():
 k={"status":"ACTIVE","not_before":"2026-01-01T00:00:00Z",
 "not_after":"2027-01-01T00:00:00Z","key_version":"v2"}
 assert m.validate_key_lifecycle(k,"2026-11-23T12:00:00Z")["status"]=="PASS"
 assert "key_expired" in m.validate_key_lifecycle(k,"2027-01-01T00:00:00Z")["issues"]
 k["status"]="REVOKED"
 assert "key_not_active" in m.validate_key_lifecycle(k,"2026-11-23T12:00:00Z")["issues"]

def test_gate_fails_closed_without_verified_attestation_or_ledger(tmp_path):
 l=ledger(tmp_path)
 r=m.stage_770_durable_attestation_gate({"status":"BLOCKED"},l,"n","nonce-123456789012",9999999999,{},100)
 assert r["status"]=="BLOCKED" and not r["authorization_granted"]
 assert m.stage_770_durable_attestation_gate({"status":"PASS"},None,"n","nonce-123456789012",9999999999,{},100)["status"]=="BLOCKED"

def test_gate_consumes_nonce_but_never_authorizes_changes(tmp_path):
 l=ledger(tmp_path)
 r=m.stage_770_durable_attestation_gate({"status":"PASS"},l,"n","nonce-123456789012",9999999999,{"scope":"review"},100)
 assert r["status"]=="REPLAY_PROTECTED"
 assert r["authorization_granted"] is False
 assert m.stage_770_durable_attestation_gate({"status":"PASS"},l,"n","nonce-123456789012",9999999999,{},100)["status"]=="BLOCKED"

def test_invalid_database_path_rejected():
 with pytest.raises(ValueError): m.SQLiteReplayLedger(":memory:")
