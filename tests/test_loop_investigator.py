import unittest
from scripts.loop_investigator import investigate

class LoopInvestigatorTests(unittest.TestCase):
    def test_malformed_report_blocks(self):
        r=investigate(None)
        self.assertEqual(r["status"],"BLOCKED")
        self.assertFalse(r["dispatch_allowed"])
    def test_blocked_monitor_is_critical(self):
        r=investigate({"status":"BLOCKED","failure_reason":"bad","checks":{}})
        self.assertEqual(r["status"],"BLOCKED")
        self.assertEqual(r["findings"][0]["code"],"MONITOR_BLOCKED")
    def test_failed_check_named(self):
        r=investigate({"status":"BLOCKED","checks":{"actions_api":{"status":"BLOCKED","detail":"unavailable"}}})
        self.assertIn("CHECK_ACTIONS_API",[f["code"] for f in r["findings"]])
    def test_hold_remains_hold_not_auto_cleared(self):
        r=investigate({"status":"HOLD","checks":{"recovery_safety":{"status":"HOLD","detail":"held"}}})
        self.assertTrue(any(f["code"].startswith("SAFETY_HOLD") for f in r["findings"]))
        self.assertFalse(r["state_mutation_allowed"])
    def test_scheduler_gaps_aggregated(self):
        r=investigate({"status":"BLOCKED","checks":{"schedule_slot_coverage":{"status":"BLOCKED","missing_slots":[{"status":"SCHEDULER_MISSING"},{"status":"ARTIFACT_MISSING"}]}}})
        f=next(f for f in r["findings"] if f["code"]=="SCHEDULER_SLOT_GAPS")
        self.assertEqual(f["evidence"]["count"],2)
    def test_queue_exhaustion_detected(self):
        r=investigate({"status":"BLOCKED","checks":{"queue_and_approval":{"status":"BLOCKED","detail":"catalog exhausted"}}})
        self.assertTrue(any(f["code"]=="QUEUE_OR_APPROVAL_BLOCK" for f in r["findings"]))
    def test_clean_report_stays_readonly(self):
        r=investigate({"status":"PASS","checks":{}})
        self.assertEqual(r["status"],"INVESTIGATED")
        self.assertFalse(r["dispatch_allowed"])
        self.assertFalse(r["state_mutation_allowed"])
    def test_findings_bounded(self):
        checks={f"c{i}":{"status":"BLOCKED","detail":"fail"} for i in range(30)}
        r=investigate({"status":"BLOCKED","checks":checks})
        self.assertLessEqual(r["finding_count"],20)
if __name__=="__main__": unittest.main()
