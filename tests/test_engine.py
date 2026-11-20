import copy
import datetime
import json
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from lex_machine.engine import OPEN, STATUSES, attestation, evaluate, gates
from lex_machine.packs import builtin_names, load_pack, parse_pack
from lex_machine.record import parse_record
from tests import oracles

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples"
D = datetime.date
MARCH_1 = D(2026, 3, 1)


def mk(requires="evidence.a.values.ok == true", applies="true", sev="major", age=365, ev=("a",), cid="t.one"):
    return {"id": cid, "title": cid, "reference": "R", "applies": applies, "requires": requires, "evidence": list(ev), "max_age_days": age, "severity": sev,
            "remedy": "do it"}


def pk(*controls):
    return parse_pack({"name": "t", "title": "T", "version": "1", "source": "S", "controls": list(controls)})


def rec(system=None, evidence=None):
    return parse_record({"system": {"name": "s", **(system or {})}, "evidence": evidence if evidence is not None else
                         {"a": {"collected": "2026-01-01", "values": {"ok": True}}}})


def status(control, record, as_of=MARCH_1, base=None):
    return evaluate(record, [pk(control)], as_of=as_of, base=base).findings[0]


class TestStatuses(unittest.TestCase):
    def test_satisfied(self):
        self.assertEqual(status(mk(), rec()).status, "satisfied")

    def test_failed_shows_what_the_evidence_said(self):
        f = status(mk(), rec(evidence={"a": {"collected": "2026-01-01", "values": {"ok": False}}}))
        self.assertEqual(f.status, "failed")
        self.assertIn("evidence.a.values.ok is false", f.detail)

    def test_missing_evidence_item(self):
        f = status(mk(), rec(evidence={}))
        self.assertEqual((f.status, f.detail), ("missing", "no evidence collected for: a"))

    def test_missing_value_inside_present_evidence(self):
        f = status(mk(), rec(evidence={"a": {"collected": "2026-01-01", "values": {}}}))
        self.assertEqual(f.status, "missing")
        self.assertIn("evidence.a.values.ok", f.detail)

    def test_stale_boundary_is_exact(self):
        r = rec(evidence={"a": {"collected": "2026-01-01", "values": {"ok": True}}})
        c = mk(age=59)                                   # 2026-01-01 to 2026-03-01 is 59 days
        self.assertEqual(status(c, r).status, "satisfied")
        self.assertEqual(status(mk(age=58), r).status, "stale")
        self.assertEqual(status(c, r, as_of=D(2026, 3, 2)).status, "stale")

    def test_failed_beats_stale(self):
        r = rec(evidence={"a": {"collected": "2020-01-01", "values": {"ok": False}}})
        self.assertEqual(status(mk(), r).status, "failed")

    def test_not_applicable_and_undetermined(self):
        c = mk(applies='system.risk_class == "high"')
        self.assertEqual(status(c, rec({"risk_class": "minimal"})).status, "not_applicable")
        self.assertEqual(status(c, rec({"risk_class": "high"})).status, "satisfied")
        f = status(c, rec())
        self.assertEqual(f.status, "undetermined")
        self.assertIn("system.risk_class", f.detail)

    def test_a_decided_applicability_ignores_an_unrelated_unknown(self):
        c = mk(applies='system.risk_class == "high" and system.role in ["provider"]')
        self.assertEqual(status(c, rec({"risk_class": "minimal"})).status, "not_applicable")

    def test_invalid_type(self):
        f = status(mk(requires="evidence.a.values.ok == 1"), rec())
        self.assertEqual(f.status, "invalid")
        self.assertIn("boolean", f.detail)

    def test_status_names_are_the_documented_ones(self):
        self.assertEqual(set(STATUSES), {"satisfied", "stale", "failed", "missing", "invalid", "tampered", "undetermined", "not_applicable"})
        self.assertTrue(set(STATUSES) > OPEN)
        self.assertNotIn("satisfied", OPEN)


class TestTampering(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "doc.md").write_text("original")
        sha = oracles.file_digest(self.dir / "doc.md")
        self.record = rec(evidence={"a": {"collected": "2026-01-01", "values": {"ok": True}, "artifacts": [{"path": "doc.md", "sha256": sha}]}})

    def tearDown(self):
        self.tmp.cleanup()

    def test_untouched_file_satisfies(self):
        self.assertEqual(status(mk(), self.record, base=self.dir).status, "satisfied")

    def test_changed_file_is_tampered_even_when_the_values_look_fine(self):
        (self.dir / "doc.md").write_text("original, edited")
        f = status(mk(), self.record, base=self.dir)
        self.assertEqual(f.status, "tampered")
        self.assertIn("doc.md", f.detail)

    def test_deleted_file_is_missing(self):
        (self.dir / "doc.md").unlink()
        self.assertEqual(status(mk(), self.record, base=self.dir).status, "missing")

    def test_without_a_base_folder_files_are_not_checked(self):
        (self.dir / "doc.md").write_text("changed")
        self.assertEqual(status(mk(), self.record, base=None).status, "satisfied")

    def test_tamper_counts_for_every_control_that_reads_the_evidence(self):
        (self.dir / "doc.md").write_text("changed")
        res = evaluate(self.record, [pk(mk(cid="t.one"), mk(cid="t.two"), mk(cid="t.three", ev=("a", "b"), requires="present(evidence.a)"))],
                       as_of=D(2026, 3, 1), base=self.dir)
        self.assertEqual([f.status for f in res.findings], ["tampered", "tampered", "tampered"])   # a changed file outranks a missing item


class TestReadinessAndGates(unittest.TestCase):
    def test_readiness_matches_the_oracle_on_random_records(self):
        import random
        rng = random.Random(4)
        packs = [load_pack(n) for n in builtin_names()]
        for _ in range(40):
            system = {"name": "s", "risk_class": rng.choice(["high", "minimal", "limited"]), "role": rng.choice(["provider", "deployer", "both"]),
                      "personal_data": rng.random() < 0.5, "automated_decisions": rng.random() < 0.5, "gpai": False, "interacts_with_people": True,
                      "generates_synthetic_content": False, "fria_scope": rng.random() < 0.5, "systemic_risk": False}
            ev = json.loads((EX / "triage_v2.json").read_text())["evidence"]
            for k in list(ev):
                if rng.random() < 0.3:
                    del ev[k]
                elif rng.random() < 0.2:
                    ev[k]["collected"] = "2020-01-01"
            r = parse_record({"system": system, "evidence": ev})
            res = evaluate(r, packs, as_of=D(2026, 11, 15))
            self.assertEqual(res.readiness, oracles.weighted_readiness([(f.severity, f.status) for f in res.findings]))
            for p in builtin_names():
                self.assertEqual(res.pack_readiness(p), oracles.weighted_readiness([(f.severity, f.status) for f in res.findings if f.pack == p]))

    def test_counts_add_up(self):
        raw = json.loads((EX / "hiring_screen.json").read_text())
        res = evaluate(parse_record(raw), [load_pack(n) for n in raw["packs"]], base=EX)
        self.assertEqual(sum(res.counts().values()), len(res.findings))

    def test_readiness_is_zero_with_nothing_applicable(self):
        res = evaluate(rec({"risk_class": "minimal"}), [pk(mk(applies='system.risk_class == "high"'))], as_of=D(2026, 3, 1))
        self.assertEqual(res.readiness, Fraction(0))

    def test_gates(self):
        c = [mk(cid="t.crit", sev="critical", requires="evidence.a.values.ok == false"), mk(cid="t.ok", sev="minor")]
        res = evaluate(rec(), [pk(*c)], as_of=D(2026, 3, 1))
        out = {n: ok for n, ok, _ in gates(res, {"min_readiness": 0.5, "no_critical_gaps": True, "no_tampered": True, "max_stale": 0, "no_undetermined": True})}
        self.assertEqual(out, {"min_readiness": False, "no_critical_gaps": False, "no_tampered": True, "max_stale": True, "no_undetermined": True})
        self.assertTrue({n: ok for n, ok, _ in gates(res, {"min_readiness": Fraction(1, 6)})}["min_readiness"])   # exactly 1 of 6 weight units

    def test_gate_exactly_at_the_limit_passes(self):
        res = evaluate(rec(), [pk(mk(), mk(cid="t.bad", requires="evidence.a.values.ok == false"))], as_of=D(2026, 3, 1))
        self.assertEqual(res.readiness, Fraction(1, 2))
        self.assertTrue(gates(res, {"min_readiness": 0.5})[0][1])
        self.assertFalse(gates(res, {"min_readiness": 0.51})[0][1])


class TestExamples(unittest.TestCase):
    def run_example(self, name):
        raw = json.loads((EX / name).read_text())
        return raw, evaluate(parse_record(raw), [load_pack(n) for n in raw["packs"]], base=EX)

    def test_triage_is_fully_ready(self):
        raw, res = self.run_example("triage_v2.json")
        self.assertEqual(res.readiness, Fraction(1))
        self.assertEqual(res.counts()["satisfied"], 58)
        self.assertEqual(res.counts()["not_applicable"], 4)
        self.assertTrue(all(ok for _, ok, _ in gates(res, raw["gates"])))

    def test_hiring_screen_has_each_planted_defect_and_only_those(self):
        raw, res = self.run_example("hiring_screen.json")
        got = {f.control: f.status for f in res.findings if f.status in OPEN}
        self.assertEqual(got, {
            "gdpr.art35.dpia": "tampered", "nist.measure-2.11": "failed", "gdpr.art5-1c.minimisation": "failed",
            "eu.art26.deployer-obligations": "missing", "eu.art27.fria": "missing", "nist.manage-4.3": "missing",
            "nist.measure-2.10": "stale", "eu.art50.interaction-disclosure": "undetermined"})
        self.assertEqual({n: ok for n, ok, _ in gates(res, raw["gates"])},
                         {"min_readiness": False, "no_critical_gaps": False, "no_tampered": False, "max_stale": False, "no_undetermined": False})

    def test_the_planted_bias_is_in_the_real_numbers(self):
        raw, _ = self.run_example("hiring_screen.json")
        vals = raw["evidence"]["bias_test"]["values"]
        self.assertEqual(vals["overall"], "fail")
        self.assertEqual(vals["metrics"]["tpr_gap"]["verdict"], "fail")
        self.assertGreater(vals["metrics"]["tpr_gap"]["worst_low"], 0.1)

    def test_the_hiring_dpia_really_differs_from_its_seal(self):
        raw = json.loads((EX / "hiring_screen.json").read_text())
        sealed = raw["evidence"]["dpia"]["artifacts"][0]["sha256"]
        self.assertNotEqual(sealed, oracles.file_digest(EX / "artifacts/hiring_screen/dpia.md"))


class TestAttestation(unittest.TestCase):
    def test_deterministic_and_sensitive(self):
        raw = json.loads((EX / "triage_v2.json").read_text())
        packs = [load_pack(n) for n in raw["packs"]]
        a = attestation(evaluate(parse_record(raw), packs, base=EX))
        b = attestation(evaluate(parse_record(copy.deepcopy(raw)), packs, base=EX))
        self.assertEqual(a, b)
        raw["evidence"]["logging"]["values"]["retention_days"] = 90
        c = attestation(evaluate(parse_record(raw), packs, base=EX))
        self.assertNotEqual(a["id"], c["id"])
        self.assertNotEqual(a["findings"], c["findings"])
        self.assertNotEqual(a["record"], c["record"])

    def test_it_names_the_catalog_it_was_measured_against(self):
        raw = json.loads((EX / "triage_v2.json").read_text())
        packs = [load_pack(n) for n in raw["packs"]]
        a = attestation(evaluate(parse_record(raw), packs, base=EX))
        self.assertEqual(a["packs"], {p.name: p.digest for p in packs})

    def test_a_changed_catalog_changes_the_attestation(self):
        raw = json.loads((EX / "triage_v2.json").read_text())
        p = load_pack("gdpr")
        loosened = parse_pack({"name": "gdpr", "title": p.title, "version": p.version, "source": p.source,
                               "controls": [{"id": c.id, "title": c.title, "reference": c.reference, "applies": c.applies, "requires": "true",
                                             "evidence": list(c.evidence), "severity": c.severity, "remedy": c.remedy, "max_age_days": c.max_age_days}
                                            for c in p.controls]})
        r = parse_record(raw)
        self.assertNotEqual(attestation(evaluate(r, [p], base=EX))["id"], attestation(evaluate(r, [loosened], base=EX))["id"])


if __name__ == "__main__":
    unittest.main()
