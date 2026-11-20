import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from lex_machine import expr
from lex_machine.errors import PackError, RecordError
from lex_machine.packs import PACK_DIR, builtin_names, evidence_catalog, load_pack, parse_pack
from lex_machine.record import fingerprint, load_record, loads, parse_record, safe_relative, verify_artifacts
from tests import oracles

ROOT = Path(__file__).resolve().parent.parent

GOOD = {"system": {"name": "demo", "risk_class": "high", "role": "provider"},
        "evidence": {"risk_management": {"collected": "2026-01-01", "values": {"residual_risk_acceptable": True}}}}

CONTROL = {"id": "t.one", "title": "T", "reference": "R", "applies": "true", "requires": "present(evidence.a)", "evidence": ["a"], "severity": "major",
           "remedy": "do it"}


def pack(**over):
    c = {**CONTROL, **over}
    return {"name": "t", "title": "T", "version": "1", "source": "S", "controls": [c]}


class TestRecordLoading(unittest.TestCase):
    def test_good_record(self):
        r = parse_record(copy.deepcopy(GOOD))
        self.assertEqual(r.system["name"], "demo")
        self.assertEqual(r.evidence["risk_management"].collected.isoformat(), "2026-01-01")

    def test_strict_json(self):
        for text in ('{"a": 1, "a": 2}', "[1,", '{"x": NaN}', '{"x": Infinity}'):
            with self.subTest(text), self.assertRaises(RecordError):
                loads(text)

    def test_rejections(self):
        def mut(f):
            d = copy.deepcopy(GOOD)
            f(d)
            return d

        cases = {
            "not an object": [],
            "unknown top key": mut(lambda d: d.update(extra=1)),
            "no system": {"evidence": {}},
            "no name": mut(lambda d: d["system"].pop("name")),
            "blank name": mut(lambda d: d["system"].update(name="  ")),
            "unknown system field": mut(lambda d: d["system"].update(colour="red")),
            "bad risk class": mut(lambda d: d["system"].update(risk_class="severe")),
            "bad role": mut(lambda d: d["system"].update(role="vendor")),
            "bool field as string": mut(lambda d: d["system"].update(personal_data="yes")),
            "bad evidence id": mut(lambda d: d["evidence"].update({"Bad-Id": {"collected": "2026-01-01"}})),
            "no collected": mut(lambda d: d["evidence"]["risk_management"].pop("collected")),
            "bad date format": mut(lambda d: d["evidence"]["risk_management"].update(collected="01/02/2026")),
            "impossible date": mut(lambda d: d["evidence"]["risk_management"].update(collected="2026-02-30")),
            "unknown evidence key": mut(lambda d: d["evidence"]["risk_management"].update(foo=1)),
            "values not an object": mut(lambda d: d["evidence"]["risk_management"].update(values=[1])),
            "artifact not a list": mut(lambda d: d["evidence"]["risk_management"].update(artifacts={"path": "a"})),
            "artifact bad sha": mut(lambda d: d["evidence"]["risk_management"].update(artifacts=[{"path": "a", "sha256": "XYZ"}])),
            "artifact absolute path": mut(lambda d: d["evidence"]["risk_management"].update(artifacts=[{"path": "/etc/passwd"}])),
            "artifact parent path": mut(lambda d: d["evidence"]["risk_management"].update(artifacts=[{"path": "../secret"}])),
            "artifact backslash": mut(lambda d: d["evidence"]["risk_management"].update(artifacts=[{"path": "a\\b"}])),
            "packs duplicated": mut(lambda d: d.update(packs=["gdpr", "gdpr"])),
            "bad as_of": mut(lambda d: d.update(as_of="yesterday")),
            "unknown gate": mut(lambda d: d.update(gates={"nope": True})),
            "bad min_readiness": mut(lambda d: d.update(gates={"min_readiness": 1.5})),
            "bad max_stale": mut(lambda d: d.update(gates={"max_stale": -1})),
            "gate not bool": mut(lambda d: d.update(gates={"no_tampered": "yes"})),
        }
        for label, raw in cases.items():
            with self.subTest(label), self.assertRaises(RecordError):
                parse_record(raw)

    def test_fingerprint_ignores_order_and_whitespace(self):
        a = loads(json.dumps(GOOD))
        b = loads(json.dumps(dict(reversed(list(GOOD.items()))), indent=4))
        self.assertEqual(fingerprint(a), fingerprint(b))
        c = copy.deepcopy(GOOD)
        c["system"]["name"] = "other"
        self.assertNotEqual(fingerprint(a), fingerprint(c))
        self.assertEqual(fingerprint(a), hashlib.sha256(json.dumps(a, sort_keys=True, separators=(",", ":")).encode()).hexdigest())

    def test_safe_relative(self):
        self.assertEqual(safe_relative("a/b.md", "x"), "a/b.md")
        for bad in ("", "..", "a/../b", "/abs", None, 3):
            with self.assertRaises(RecordError):
                safe_relative(bad, "x")


class TestArtifacts(unittest.TestCase):
    def make(self, tmp, text="hello"):
        (Path(tmp) / "doc.md").write_text(text)
        raw = copy.deepcopy(GOOD)
        raw["evidence"]["risk_management"]["artifacts"] = [{"path": "doc.md", "sha256": hashlib.sha256(b"hello").hexdigest()}]
        return parse_record(raw)

    def test_states(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = self.make(tmp)
            self.assertEqual(verify_artifacts(rec, Path(tmp))["risk_management"], [("ok", "doc.md")])
            (Path(tmp) / "doc.md").write_text("hello!")
            self.assertEqual(verify_artifacts(rec, Path(tmp))["risk_management"], [("mismatch", "doc.md")])
            (Path(tmp) / "doc.md").unlink()
            self.assertEqual(verify_artifacts(rec, Path(tmp))["risk_management"], [("absent", "doc.md")])

    def test_unsealed_is_reported_not_trusted(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "doc.md").write_text("x")
            raw = copy.deepcopy(GOOD)
            raw["evidence"]["risk_management"]["artifacts"] = [{"path": "doc.md"}]
            self.assertEqual(verify_artifacts(parse_record(raw), Path(tmp))["risk_management"], [("unsealed", "doc.md")])

    def test_one_byte_change_is_always_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = bytes(range(256)) * 40
            for i in range(0, len(body), 997):
                (Path(tmp) / "f.bin").write_bytes(body)
                raw = copy.deepcopy(GOOD)
                raw["evidence"]["risk_management"]["artifacts"] = [{"path": "f.bin", "sha256": oracles.file_digest(Path(tmp) / "f.bin")}]
                rec = parse_record(raw)
                changed = bytearray(body)
                changed[i] ^= 1
                (Path(tmp) / "f.bin").write_bytes(bytes(changed))
                self.assertEqual(verify_artifacts(rec, Path(tmp))["risk_management"][0][0], "mismatch")

    def test_symlink_out_of_the_folder_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            (Path(outside) / "secret.txt").write_text("s")
            (Path(tmp) / "link.txt").symlink_to(Path(outside) / "secret.txt")
            raw = copy.deepcopy(GOOD)
            raw["evidence"]["risk_management"]["artifacts"] = [{"path": "link.txt"}]
            with self.assertRaises(RecordError):
                verify_artifacts(parse_record(raw), Path(tmp))

    def test_load_record_errors(self):
        with self.assertRaises(RecordError):
            load_record("/no/such/file.json")


class TestPacks(unittest.TestCase):
    def test_every_builtin_pack_loads_and_is_pinned(self):
        pinned = json.loads((ROOT / "tests" / "pack_digests.json").read_text())
        self.assertEqual(sorted(pinned), builtin_names())
        for name in builtin_names():
            self.assertEqual(load_pack(name).digest, pinned[name], f"{name} changed: update tests/pack_digests.json on purpose, not by accident")

    def test_builtin_pack_sizes(self):
        counts = {n: len(load_pack(n).controls) for n in builtin_names()}
        self.assertEqual(counts, {"eu-ai-act": 24, "gdpr": 12, "iso-42001": 10, "nist-ai-rmf": 16})

    def test_control_ids_are_unique_across_packs(self):
        ids = [c.id for n in builtin_names() for c in load_pack(n).controls]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_control_expression_round_trips(self):
        for n in builtin_names():
            for c in load_pack(n).controls:
                for ast in (c.applies_ast, c.requires_ast):
                    self.assertEqual(expr.parse(expr.render(ast)), ast)

    def test_digest_changes_with_any_semantic_edit(self):
        base = parse_pack(pack()).digest
        for over in ({"requires": "present(evidence.a) and true"}, {"severity": "minor"}, {"max_age_days": 30}, {"applies": "false"}, {"reference": "Q"}):
            self.assertNotEqual(parse_pack(pack(**over)).digest, base, over)
        self.assertEqual(parse_pack(pack(title="Different words")).digest, base)       # wording is not meaning

    def test_pack_errors(self):
        bad = {
            "unknown pack key": {**pack(), "extra": 1},
            "no controls": {**pack(), "controls": []},
            "duplicate id": {**pack(), "controls": [CONTROL, CONTROL]},
            "unknown control key": pack(foo=1),
            "bad severity": pack(severity="huge"),
            "bad max age": pack(max_age_days=0),
            "unknown system field": pack(applies="system.colour == \"red\""),
            "evidence not declared": pack(requires="present(evidence.b)"),
            "applies reads evidence": pack(applies="present(evidence.a)"),
            "bad expression": pack(requires="present(evidence.a) and"),
            "age needs an item": pack(requires="age(evidence.a.values.x) < 3"),
            "empty evidence": pack(evidence=[]),
            "bad evidence id": pack(evidence=["A-b"]),
            "blank remedy": pack(remedy=" "),
        }
        for label, raw in bad.items():
            with self.subTest(label), self.assertRaises(PackError):
                parse_pack(raw)

    def test_pack_loading_from_a_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "mine.json"
            p.write_text(json.dumps(pack()))
            self.assertEqual(load_pack(str(p)).name, "t")
            p.write_text("{not json")
            with self.assertRaises(PackError):
                load_pack(str(p))
        with self.assertRaises(PackError):
            load_pack("no-such-pack")

    def test_catalog_lists_what_the_packs_read(self):
        cat = evidence_catalog([load_pack(n) for n in builtin_names()])
        self.assertIn("bias_test", cat)
        self.assertEqual(cat["bias_test"]["values"], ["overall"])
        self.assertIn("eu-ai-act:eu.art10.bias-testing", cat["bias_test"]["controls"])
        self.assertIn("nist-ai-rmf:nist.measure-2.11", cat["bias_test"]["controls"])
        self.assertIn("retention_days", cat["logging"]["values"])

    def test_pack_files_are_where_the_package_expects(self):
        self.assertEqual(sorted(p.stem for p in PACK_DIR.glob("*.json")), builtin_names())


if __name__ == "__main__":
    unittest.main()
