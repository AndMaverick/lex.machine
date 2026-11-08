import unittest

from python.governance.audit_report import render
from python.governance.compliance_scan import controls_for, readiness, scan

FULL = {
    "model": "triage-v2", "risk_class": "high", "risk_management": True, "data_governance": True,
    "bias_score": 0.04, "audit_logging": True, "transparency_notice": True,
    "human_oversight": True, "data_minimization": True, "owner": "Platform AI",
}


class ScanTests(unittest.TestCase):
    def test_complete_metadata_is_fully_ready(self):
        for framework in ("eu-ai-act", "nist-ai-rmf", "gdpr"):
            self.assertEqual(readiness(scan(FULL, framework)), 1.0)

    def test_missing_evidence_is_reported(self):
        partial = {k: v for k, v in FULL.items() if k != "audit_logging"}
        statuses = {f.control: f.status for f in scan(partial, "eu-ai-act")}
        self.assertEqual(statuses["record-keeping"], "missing")
        self.assertEqual(statuses["bias-testing"], "met")

    def test_high_bias_score_fails_the_control(self):
        findings = scan({**FULL, "bias_score": 0.3}, "eu-ai-act")
        failed = [f for f in findings if f.status == "failed"]
        self.assertEqual([f.control for f in failed], ["bias-testing"])

    def test_threshold_is_configurable(self):
        self.assertEqual(readiness(scan({**FULL, "bias_score": 0.3}, "gdpr", bias_threshold=0.5)), 1.0)

    def test_frameworks_cover_different_controls(self):
        self.assertIn("data-minimization", controls_for("gdpr"))
        self.assertNotIn("data-minimization", controls_for("eu-ai-act"))

    def test_unknown_framework_rejected(self):
        with self.assertRaises(ValueError):
            scan(FULL, "made-up")


class ReportTests(unittest.TestCase):
    def test_report_lists_gaps_and_marks(self):
        findings = scan({"model": "m"}, "nist-ai-rmf")
        text = render("m", "nist-ai-rmf", findings, {"bias_score": 0.2})
        self.assertIn("# Audit summary: m", text)
        self.assertIn("MISSING", text)
        self.assertIn("- [ ]", text)
        self.assertIn("bias_score: 0.2", text)

    def test_clean_report_has_no_open_gaps(self):
        text = render("m", "gdpr", scan(FULL, "gdpr"))
        self.assertIn("No open gaps.", text)
        self.assertIn("100%", text)


if __name__ == "__main__":
    unittest.main()
