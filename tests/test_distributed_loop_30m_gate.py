import hashlib,hmac,json,unittest,os,tempfile
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
from scripts.distributed_loop_30m_gate import GateBlocked,decide_slot,evaluate_budget_snapshot,main
NOW=datetime(2026,11,13,0,0,tzinfo=timezone.utc); KEY="test-only-hmac-key-that-is-at-least-32-bytes"
NAMES=("cloudflare_workers","cloudflare_d1","cloudflare_durable_objects")
def signed(overrides=None,failures=0):
 overrides=overrides or {}; units={"cloudflare_workers":"requests","cloudflare_d1":"rows","cloudflare_durable_objects":"requests"}
 rows=[]
 for n in NAMES:
  rows.append({"name":n,"enabled":True,"used":10,"limit":100,"unit":units[n],"limit_source":"provider","limit_evidence_id":"limit-evidence",
   "quality":"exact","coverage_complete":True,"exact_counter":True,"sampling_mode":"none","source_api":"account-meter",
   "resource_count":1,"resource_digest":hashlib.sha256(n.encode()).hexdigest(),"source_watermark_at":"2026-11-13T00:00:00Z",**overrides.get(n,{})})
 p={"schema_version":1,"collector_id":"orca-budget-collector","account_id":"test-account","observed_at":"2026-11-13T00:00:00Z",
    "period_start":"2026-11-01T00:00:00Z","period_end":"2026-12-01T00:00:00Z","consecutive_failures":failures,"sources":rows}
 raw=json.dumps(p,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode(); p["signature"]=hmac.new(KEY.encode(),raw,hashlib.sha256).hexdigest(); return p
def resign(p):
 p=dict(p); p.pop("signature",None); raw=json.dumps(p,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
 p["signature"]=hmac.new(KEY.encode(),raw,hashlib.sha256).hexdigest(); return p
class BudgetGateTests(unittest.TestCase):
 def run_gate(self,p): return evaluate_budget_snapshot(p,now=NOW,evidence_key=KEY)
 def test_clear_warn_and_thresholds(self):
  self.assertEqual(self.run_gate(signed())["status"],"CLEAR"); self.assertEqual(self.run_gate(signed({"cloudflare_d1":{"used":70}}))["status"],"WARN")
  for used,reason in ((80,"budget_suppress"),(90,"budget_stop")):
   with self.assertRaisesRegex(GateBlocked,reason): self.run_gate(signed({"cloudflare_d1":{"used":used}}))
 def test_signature_tamper_and_missing_key_block(self):
  p=signed(); p["sources"][0]["used"]=1
  with self.assertRaisesRegex(GateBlocked,"signature_invalid"): self.run_gate(p)
  p=signed(); p.pop("signature")
  with self.assertRaisesRegex(GateBlocked,"signature_missing"): self.run_gate(p)
  with self.assertRaisesRegex(GateBlocked,"verification_key_missing"): evaluate_budget_snapshot(signed(),now=NOW,evidence_key="")
 def test_incomplete_or_sampled_data_blocks(self):
  for v in ({"quality":"estimated"},{"coverage_complete":False},{"exact_counter":False},{"sampling_mode":"adaptive"},{"limit_evidence_id":""},{"source_watermark_at":"2026-11-12T00:00:00Z"}):
   with self.subTest(v=v),self.assertRaises(GateBlocked): self.run_gate(signed({"cloudflare_d1":v}))
 def test_source_period_boundaries_are_complete_and_current(self):
  with self.assertRaisesRegex(GateBlocked,"budget_period_not_current"):
   self.run_gate(signed({"cloudflare_d1":{"period_start":"2026-11-01T00:00:00Z","period_end":"2026-11-12T00:00:00Z"}}))
  with self.assertRaisesRegex(GateBlocked,"budget_source_period_boundary_incomplete"):
   self.run_gate(signed({"cloudflare_d1":{"period_start":"2026-11-01T00:00:00Z"}}))
  with self.assertRaisesRegex(GateBlocked,"budget_source_period_boundary_incomplete"):
   self.run_gate(signed({"cloudflare_d1":{"period_end":"2026-11-12T00:00:00Z"}}))
  with self.assertRaisesRegex(GateBlocked,"budget_period_not_current"):
   self.run_gate(signed({"cloudflare_d1":{"period_start":"2026-11-12T00:00:00Z","period_end":"2026-11-13T00:00:00Z"}}))
 def test_missing_or_extra_sources_block(self):
  p=signed(); p["sources"]=p["sources"][:-1]
  with self.assertRaisesRegex(GateBlocked,"source_set_incomplete"): self.run_gate(resign(p))
  p=signed(); p["sources"].append(dict(p["sources"][0],name="github_actions"))
  with self.assertRaisesRegex(GateBlocked,"source_set_incomplete"): self.run_gate(resign(p))
 def test_bad_period_and_failures_block(self):
  with self.assertRaisesRegex(GateBlocked,"budget_period_not_current"): self.run_gate(signed({"cloudflare_d1":{"period_start":"2026-11-01T00:00:00Z","period_end":"2026-11-12T00:00:00Z"}}))
  with self.assertRaisesRegex(GateBlocked,"consecutive_failure_limit"): self.run_gate(signed(failures=3))
class SlotGateTests(unittest.TestCase):
 def test_continuation_gate(self):
  from scripts.distributed_loop_30m_gate import requires_slot_gate
  self.assertTrue(requires_slot_gate("schedule","0")); self.assertTrue(requires_slot_gate("workflow_dispatch","1"))
  self.assertFalse(requires_slot_gate("workflow_dispatch","0")); self.assertFalse(requires_slot_gate("issue_comment","0"))
 def test_slot_interval(self):
  self.assertTrue(decide_slot([],current_run_id="2",now=NOW)[0])
  old=[{"id":1,"run_started_at":(NOW-timedelta(minutes=31)).isoformat()}]
  self.assertEqual(decide_slot(old,current_run_id="2",now=NOW),(True,"slot_available"))
  recent=[{"id":1,"run_started_at":(NOW-timedelta(minutes=20)).isoformat()}]
  self.assertFalse(decide_slot(recent,current_run_id="2",now=NOW)[0])

class GateProcessTests(unittest.TestCase):
 def test_blocked_gate_exits_nonzero_and_writes_false_output(self):
  with tempfile.TemporaryDirectory() as tmp:
   output=os.path.join(tmp,"output"); summary=os.path.join(tmp,"summary")
   env={"GITHUB_OUTPUT":output,"GITHUB_STEP_SUMMARY":summary,"GITHUB_EVENT_NAME":"schedule","CONTINUATION_DEPTH":"0"}
   with patch.dict(os.environ,env,clear=False):
    with patch("scripts.distributed_loop_30m_gate.check_global_hold",side_effect=GateBlocked("global_hold_active_or_unknown")):
     self.assertEqual(main(),1)
   with open(output,encoding="utf-8") as f: self.assertIn("allow=false",f.read())
   with open(summary,encoding="utf-8") as f: self.assertIn("BLOCKED",f.read())

if __name__=="__main__": unittest.main()
