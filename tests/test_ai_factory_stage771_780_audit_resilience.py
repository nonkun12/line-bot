import importlib.util, hashlib, hmac, json
from pathlib import Path
p=Path(__file__).parents[1]/"core/ai_factory_stage771_780_audit_resilience.py"
s=importlib.util.spec_from_file_location("stage771",p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
from importlib.util import spec_from_file_location, module_from_spec
q=Path(__file__).parents[1]/"core/ai_factory_stage761_770_durable_replay.py"
sp=spec_from_file_location("stage761",q); ledger_mod=module_from_spec(sp); sp.loader.exec_module(ledger_mod)

def make_ledger(tmp_path):
 l=ledger_mod.SQLiteReplayLedger(tmp_path/"source.sqlite")
 l.consume_with_audit("issuer","nonce-123456789012",9999999999,{"event":"verified"},100)
 return l

def test_checkpoint_is_canonical_and_unanchored(tmp_path):
 r=m.create_audit_checkpoint(make_ledger(tmp_path))
 assert r["status"]=="READY_FOR_EXTERNAL_ANCHOR"
 assert len(r["checkpoint_sha256"])==64 and not r["externally_anchored"]

def test_anchor_receipt_hmac_and_digest_binding(tmp_path):
 cp=m.create_audit_checkpoint(make_ledger(tmp_path)); key=b"A"*32
 receipt={"provider_ref":"anchor-provider","anchor_ref":"receipt-1",
 "checkpoint_sha256":cp["checkpoint_sha256"],"anchored_at_epoch":1000,
 "key_id":"anchor-key-v1"}
 raw=json.dumps(receipt,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
 receipt["signature"]=hmac.new(key,b"AI_FACTORY_EXTERNAL_ANCHOR_V1\n"+raw,hashlib.sha256).hexdigest()
 assert m.verify_anchor_receipt(cp,receipt,key,1100,86400)["status"]=="PASS"
 receipt["checkpoint_sha256"]="0"*64
 assert m.verify_anchor_receipt(cp,receipt,key,1100,86400)["status"]=="BLOCKED"

def test_anchor_rejects_expired_future_and_wrong_key(tmp_path):
 cp=m.create_audit_checkpoint(make_ledger(tmp_path)); key=b"A"*32
 receipt={"provider_ref":"p","anchor_ref":"r","checkpoint_sha256":cp["checkpoint_sha256"],
 "anchored_at_epoch":1000,"key_id":"k"}
 raw=json.dumps(receipt,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
 receipt["signature"]=hmac.new(key,b"AI_FACTORY_EXTERNAL_ANCHOR_V1\n"+raw,hashlib.sha256).hexdigest()
 assert "anchor_receipt_too_old" in m.verify_anchor_receipt(cp,receipt,key,90000,86400)["issues"]
 assert "anchor_timestamp_in_future" in m.verify_anchor_receipt(cp,receipt,key,900,86400)["issues"]
 assert "anchor_receipt_signature_invalid" in m.verify_anchor_receipt(cp,receipt,b"B"*32,1100,86400)["issues"]

def test_backup_verify_and_restore_rehearsal(tmp_path):
 l=make_ledger(tmp_path); backup=tmp_path/"backup.sqlite"; restore=tmp_path/"restore.sqlite"
 manifest=m.create_sqlite_backup(l,backup)
 assert manifest["status"]=="PASS"
 assert m.verify_sqlite_backup(backup,manifest)["status"]=="PASS"
 r=m.rehearse_sqlite_restore(backup,restore,manifest)
 assert r["status"]=="PASS" and r["production_restore_performed"] is False

def test_backup_manifest_tamper_is_detected(tmp_path):
 l=make_ledger(tmp_path); backup=tmp_path/"backup.sqlite"
 manifest=m.create_sqlite_backup(l,backup); manifest["event_count"]+=1
 assert m.verify_sqlite_backup(backup,manifest)["status"]=="BLOCKED"

def test_restore_rejects_same_source_and_target(tmp_path):
 l=make_ledger(tmp_path); backup=tmp_path/"backup.sqlite"
 manifest=m.create_sqlite_backup(l,backup)
 assert m.rehearse_sqlite_restore(backup,backup,manifest)["status"]=="BLOCKED"

def test_retention_policy_requires_offsite_and_restore_interval():
 good={"minimum_backup_copies":2,"maximum_backup_age_days":7,
 "audit_retention_days":365,"offsite_copy_required":True,"restore_test_interval_days":30}
 assert m.validate_retention_policy(good)["status"]=="PASS"
 good["offsite_copy_required"]=False
 assert m.validate_retention_policy(good)["status"]=="BLOCKED"

def test_final_gate_never_grants_authorization(tmp_path):
 l=make_ledger(tmp_path); cp=m.create_audit_checkpoint(l)
 b=m.create_sqlite_backup(l,tmp_path/"backup.sqlite")
 r=m.rehearse_sqlite_restore(tmp_path/"backup.sqlite",tmp_path/"restore.sqlite",b)
 retention=m.validate_retention_policy({"minimum_backup_copies":2,"maximum_backup_age_days":7,
 "audit_retention_days":365,"offsite_copy_required":True,"restore_test_interval_days":30})
 gate=m.stage_780_resilience_gate(cp,{"status":"BLOCKED"},b,r,retention)
 assert gate["status"]=="BLOCKED" and not gate["authorization_granted"]
 assert gate["external_anchor_write_performed"] is False
