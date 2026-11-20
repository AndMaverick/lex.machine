import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lex_machine import chain, cli
from lex_machine.errors import HistoryError
from tests import oracles

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples"


def run(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main([str(a) for a in args])
    return code, out.getvalue(), err.getvalue()


class TestHistory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "h.jsonl"
        self.att = [{"as_of": f"2026-0{i}-01", "system": "s", "readiness": f"{i}0.0%", "n": i} for i in range(1, 6)]
        for a in self.att:
            chain.append(self.path, a)
        self.original = self.lines()

    def tearDown(self):
        self.tmp.cleanup()

    def lines(self):
        return self.path.read_text().splitlines()

    def write(self, lines):
        self.path.write_text("\n".join(lines) + "\n")

    def test_chain_matches_the_documented_recipe(self):
        prev = "0" * 64
        for e, a in zip(chain.read(self.path), self.att, strict=True):
            prev = oracles.history_hash(prev, a)
            self.assertEqual(e["hash"], prev)

    def test_clean_history_verifies(self):
        entries = chain.read(self.path)
        self.assertEqual([e["seq"] for e in entries], [1, 2, 3, 4, 5])
        self.assertEqual(chain.head(entries), entries[-1]["hash"])

    def test_editing_any_line_is_caught(self):
        for i in range(5):
            lines = list(self.original)
            e = json.loads(lines[i])
            e["attestation"]["readiness"] = "100.0%"
            lines[i] = json.dumps(e, sort_keys=True, separators=(",", ":"))
            self.write(lines)
            with self.assertRaises(HistoryError):
                chain.read(self.path)
            self.write(self.original)

    def test_removing_a_middle_line_is_caught(self):
        for i in range(4):
            lines = list(self.original)
            del lines[i]
            self.write(lines)
            with self.assertRaises(HistoryError):
                chain.read(self.path)
            self.write(self.original)

    def test_reordering_is_caught(self):
        lines = self.lines()
        lines[1], lines[2] = lines[2], lines[1]
        self.write(lines)
        with self.assertRaises(HistoryError):
            chain.read(self.path)

    def test_inserting_a_forged_line_is_caught(self):
        lines = self.lines()
        forged = {"seq": 3, "prev": json.loads(lines[1])["hash"], "attestation": {"as_of": "2026-03-01", "n": 99}, "hash": "0" * 64}
        lines.insert(2, json.dumps(forged))
        self.write(lines)
        with self.assertRaises(HistoryError):
            chain.read(self.path)

    def test_dropping_the_latest_entries_changes_the_head(self):
        full = chain.head(chain.read(self.path))
        self.write(self.lines()[:3])
        self.assertNotEqual(chain.head(chain.read(self.path)), full)       # truncation is visible only against a published head

    def test_garbage_lines(self):
        for junk in ("not json", "[1]", '{"seq":1}', ""):
            self.write([junk])
            with self.assertRaises(HistoryError):
                chain.read(self.path)

    def test_append_refuses_a_broken_chain(self):
        lines = self.lines()
        del lines[1]
        self.write(lines)
        with self.assertRaises(HistoryError):
            chain.append(self.path, {"x": 1})


class TestCli(unittest.TestCase):
    def test_exit_codes_for_scan(self):
        self.assertEqual(run("scan", EX / "triage_v2.json")[0], 0)
        self.assertEqual(run("scan", EX / "hiring_screen.json")[0], 1)
        code, _, err = run("scan", EX / "missing.json")
        self.assertEqual(code, 2)
        self.assertIn("cannot read", err)

    def test_scan_without_packs_is_an_input_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "r.json"
            p.write_text(json.dumps({"system": {"name": "s"}}))
            code, _, err = run("scan", p)
            self.assertEqual(code, 2)
            self.assertIn("no packs", err)
            code, out, _ = run("scan", p, "--pack", "gdpr")
            self.assertEqual(code, 0)                                         # no gates asked for: report only
            self.assertIn("UNDECIDED", out)

    def test_unknown_pack_and_bad_date(self):
        self.assertEqual(run("scan", EX / "triage_v2.json", "--pack", "nope")[0], 2)
        self.assertEqual(run("scan", EX / "triage_v2.json", "--as-of", "soon")[0], 2)

    def test_as_of_changes_staleness(self):
        code, out, _ = run("scan", EX / "triage_v2.json", "--as-of", "2031-01-01")
        self.assertEqual(code, 1)
        self.assertIn("STALE", out)

    def test_formats(self):
        code, out, _ = run("scan", EX / "hiring_screen.json", "--format", "json")
        data = json.loads(out)
        self.assertEqual(code, 1)
        self.assertFalse(data["passed"])
        self.assertEqual(data["attestation"]["counts"]["tampered"], 1)
        _, md, _ = run("scan", EX / "hiring_screen.json", "--format", "markdown")
        self.assertIn("# Audit summary: cv-screen-assistant", md)
        self.assertIn("- [ ] **gdpr.art35.dpia**", md)

    def test_text_report_has_no_em_dash_and_names_each_gap(self):
        _, out, _ = run("scan", EX / "hiring_screen.json")
        self.assertNotIn(chr(0x2014), out)
        for needle in ("TAMPERED", "FAILED", "MISSING", "STALE", "UNDECIDED", "RESULT: FAIL", "What to do"):
            self.assertIn(needle, out)

    def test_all_flag_lists_met_controls(self):
        _, short, _ = run("scan", EX / "triage_v2.json")
        _, full, _ = run("scan", EX / "triage_v2.json", "--all")
        self.assertNotIn("eu.art9.risk-management", short)
        self.assertIn("eu.art9.risk-management", full)

    def test_history_flag_builds_a_verifiable_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = Path(tmp) / "h.jsonl"
            run("scan", EX / "triage_v2.json", "--history", h)
            run("scan", EX / "hiring_screen.json", "--history", h)
            code, out, _ = run("history", "verify", h)
            self.assertEqual(code, 0)
            self.assertIn("2 entries", out)
            _, shown, _ = run("history", "show", h)
            self.assertIn("triage-v2", shown)
            self.assertIn("cv-screen-assistant", shown)
            text = h.read_text().replace("triage-v2", "triage-v3")
            h.write_text(text)
            code, _, err = run("history", "verify", h)
            self.assertEqual(code, 2)
            self.assertIn("line 1", err)

    def test_seal_and_verify_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            shutil.copytree(EX / "artifacts", tmp / "artifacts")
            rec = json.loads((EX / "triage_v2.json").read_text())
            for item in rec["evidence"].values():
                for a in item.get("artifacts", []):
                    a.pop("sha256")
            (tmp / "r.json").write_text(json.dumps(rec))
            code, out, _ = run("verify", tmp / "r.json")
            self.assertEqual((code, out.count("unsealed")), (0, 5))
            code, out, _ = run("seal", tmp / "r.json")
            self.assertIn("5 digest(s) not written", out)
            self.assertNotIn("sha256", (tmp / "r.json").read_text())
            run("seal", tmp / "r.json", "--write")
            code, out, _ = run("verify", tmp / "r.json")
            self.assertEqual((code, out.count("ok ")), (0, 5))
            (tmp / "artifacts/triage_v2/dpia.md").write_text("changed after sealing")
            code, out, _ = run("verify", tmp / "r.json")
            self.assertEqual(code, 1)
            self.assertIn("mismatch", out)
            code, out, _ = run("seal", tmp / "r.json")
            self.assertIn("MISMATCH", out)                                    # sealing never silently adopts a changed file
            self.assertEqual(run("scan", tmp / "r.json")[0], 1)
            run("seal", tmp / "r.json", "--write", "--force")
            self.assertEqual(run("scan", tmp / "r.json")[0], 0)

    def test_bias_command(self):
        code, out, _ = run("bias", EX / "artifacts/hiring_screen/predictions.csv", "--group", "group", "--label", "label", "--pred", "pred")
        self.assertEqual(code, 1)
        self.assertIn("OVERALL: FAIL", out)
        code, out, _ = run("bias", EX / "artifacts/triage_v2/predictions.csv", "--group", "group", "--label", "label", "--pred", "pred", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["values"]["overall"], "pass")
        code, _, err = run("bias", EX / "artifacts/triage_v2/predictions.csv", "--group", "nope", "--pred", "pred")
        self.assertEqual(code, 2)
        self.assertIn("nope", err)

    def test_bias_evidence_out_feeds_a_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "bias.json"
            run("bias", EX / "artifacts/triage_v2/predictions.csv", "--group", "group", "--label", "label", "--pred", "pred", "--evidence-out", out,
                "--collected", "2026-11-01")
            item = json.loads(out.read_text())["bias_test"]
            rec = {"system": {"name": "s", "risk_class": "high", "role": "provider"}, "packs": ["nist-ai-rmf"], "as_of": "2026-11-15", "evidence": {"bias_test": item}}
            (Path(tmp) / "r.json").write_text(json.dumps(rec))
            _, text, _ = run("scan", Path(tmp) / "r.json", "--all")
            self.assertRegex(text, r"MET\s+critical nist\.measure-2\.11")

    def test_introspection_commands(self):
        code, out, _ = run("packs")
        self.assertEqual(code, 0)
        self.assertEqual(out.count("controls"), 4)
        self.assertIn("Art. 10(2)(f)", run("explain", "eu.art10.bias-testing")[1])
        self.assertEqual(run("explain", "nope")[0], 2)
        self.assertIn("retention_days", run("catalog", "--pack", "eu-ai-act")[1])
        self.assertEqual(run("lint", "gdpr", "nist-ai-rmf")[0], 0)
        self.assertEqual(run("lint", "nope")[0], 2)
        code, out, _ = run("fingerprint", EX / "triage_v2.json")
        self.assertEqual(len(out.strip()), 64)

    def test_the_governance_matrix_document_is_what_the_packs_say(self):
        code, out, _ = run("matrix")
        self.assertEqual(code, 0)
        self.assertEqual(out, (ROOT / "docs" / "governance_matrix.md").read_text(encoding="utf-8"))

    def test_module_entry_point_is_deterministic_across_hash_seeds(self):
        outs = []
        for seed in ("0", "11", "9999"):
            env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(ROOT)}
            p = subprocess.run([sys.executable, "-m", "lex_machine", "scan", str(EX / "hiring_screen.json"), "--format", "json"],
                               capture_output=True, text=True, env=env, cwd=ROOT, check=False)
            self.assertEqual(p.returncode, 1, p.stderr)
            outs.append(p.stdout)
        self.assertEqual(outs[0], outs[1])
        self.assertEqual(outs[0], outs[2])


if __name__ == "__main__":
    unittest.main()
