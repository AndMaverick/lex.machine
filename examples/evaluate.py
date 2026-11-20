"""Measure lex.machine against independent oracles and by simulation, and print the figures the README quotes.

Everything except the last two lines is deterministic (fixed seeds). The oracles in tests/oracles.py share no code with the library.

Run from the repository root:  python examples/evaluate.py"""
from __future__ import annotations

import copy
import itertools
import json
import random
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lex_machine import chain, expr, fairness  # noqa: E402
from lex_machine.engine import evaluate  # noqa: E402
from lex_machine.fairness import Group, Row  # noqa: E402
from lex_machine.packs import builtin_names, load_pack  # noqa: E402
from lex_machine.record import parse_record  # noqa: E402
from tests import oracles  # noqa: E402

EX = ROOT / "examples"


def expression_check() -> tuple[int, int, int, int, int]:
    import datetime
    rng = random.Random(1)
    names = ["system.a", "system.b", "system.c", "system.d"]
    agree = 0
    n_full = 5000
    for _ in range(n_full):
        text = oracles.random_expression(rng, names)
        vals = {n: rng.randint(0, 3) for n in names}
        ctx = expr.Context({n.split(".")[1]: v for n, v in vals.items()}, {}, datetime.date(2026, 1, 1))
        agree += expr.truth(expr.parse(text), ctx) is oracles.py_eval(text, vals)
    decided = contradictions = 0
    n_partial = 3000
    for _ in range(n_partial):
        text = oracles.random_expression(rng, names)
        known = {n: rng.randint(0, 3) for n in names if rng.random() < 0.5}
        unknown = [n for n in names if n not in known]
        ctx = expr.Context({n.split(".")[1]: v for n, v in known.items()}, {}, datetime.date(2026, 1, 1))
        got = expr.truth(expr.parse(text), ctx)
        if got is None:
            continue
        decided += 1
        contradictions += any(oracles.py_eval(text, {**known, **fill}) is not got for fill in oracles.completions(unknown, [-1, 0, 1, 2, 3, 4]))
    return n_full, agree, n_partial, decided, contradictions


def statistics_check() -> tuple[int, float, int, int]:
    worst = 0.0
    rng = random.Random(2)
    for _ in range(1000):
        n = rng.randint(1, 500)
        k = rng.randint(0, n)
        lo, hi = fairness.wilson(k, n, 1.96)
        olo, ohi = oracles.wilson_bounds(k, n, 1.96)
        worst = max(worst, abs(lo - olo), abs(hi - ohi))
    tables = exact = 0
    for n1, n2 in itertools.product(range(1, 8), repeat=2):
        if n1 + n2 > 12:
            continue
        for k1 in range(n1 + 1):
            for k2 in range(n2 + 1):
                tables += 1
                exact += abs(fairness.fisher_exact(k1, n1, k2, n2) - float(oracles.fisher_by_enumeration(k1, n1, k2, n2))) < 1e-12
    return 1000, worst, tables, exact


def binom(rng: random.Random, n: int, p: float) -> int:
    return sum(rng.random() < p for _ in range(n))


def coverage(trials: int = 3000) -> list[tuple[str, float]]:
    rng = random.Random(3)
    out = []
    for label, p1, p2, n in (("difference, n=100 each", 0.30, 0.20, 100), ("difference, n=400 each", 0.45, 0.40, 400), ("difference, n=1000 each", 0.10, 0.10, 1000)):
        hit = sum(lo <= p1 - p2 <= hi for k1, k2 in ((binom(rng, n, p1), binom(rng, n, p2)) for _ in range(trials))
                  for _d, lo, hi in [fairness.newcombe(k1, n, k2, n, 1.959964)])
        out.append((label, hit / trials))
    for label, p1, p2, n in (("ratio, n=200 each", 0.25, 0.40, 200), ("ratio, n=1000 each", 0.30, 0.38, 1000)):
        hit = 0
        for _ in range(trials):
            k1, k2 = binom(rng, n, p1), binom(rng, n, p2)
            _r, lo, hi = fairness.katz(k1, n, k2, n, 1.959964)
            hit += lo <= p1 / p2 <= hi
        out.append((label, hit / trials))
    return out


def verdict_rates(trials: int = 1000) -> list[tuple[str, float, float, float]]:
    """For two groups of n, the share of simulated audits ending in each verdict, by the true gap in selection rate (limit 0.10)."""
    rng = random.Random(4)
    out = []
    for n, gap in ((500, 0.00), (500, 0.05), (500, 0.10), (500, 0.15), (2000, 0.15), (2000, 0.00)):
        counts = {"fail": 0, "pass": 0, "inconclusive": 0}
        for _ in range(trials):
            groups = [Group(name, n, binom(rng, n, p), None, None, None, None) for name, p in (("a", 0.40), ("b", 0.40 - gap))]
            counts[fairness.gap_metric(groups, "selection_rate", max_gap=0.10, alpha=0.05, min_group=30).verdict] += 1
        out.append((f"n={n} per group, true gap {gap:.2f}", counts["fail"] / trials, counts["pass"] / trials, counts["inconclusive"] / trials))
    return out


def catalog_check() -> tuple[int, int, int, int, int, int, int]:
    raw = json.loads((EX / "triage_v2.json").read_text())
    packs = [load_pack(n) for n in builtin_names()]
    controls = sum(len(p.controls) for p in packs)
    base = evaluate(parse_record(raw), packs, base=EX)
    applicable = [f for f in base.findings if f.status != "not_applicable"]
    met = sum(f.status == "satisfied" for f in applicable)
    by_id = {c.id: (p, c) for p in packs for c in p.controls}
    flips = fields = removed = aged = 0
    for f in applicable:
        pack, c = by_id[f.control]
        for path in sorted(p for p in expr.references(c.requires_ast) if p.count(".") == 3):
            _, eid, _, field = path.split(".")
            doc = copy.deepcopy(raw)
            v = doc["evidence"][eid]["values"][field]
            doc["evidence"][eid]["values"][field] = False if v is True else 0 if isinstance(v, (int, float)) else "none"
            fields += 1
            flips += evaluate(parse_record(doc), [pack], base=EX).findings[[x.id for x in pack.controls].index(c.id)].status == "failed"
        idx = [x.id for x in pack.controls].index(c.id)
        doc = copy.deepcopy(raw)
        del doc["evidence"][c.evidence[0]]
        removed += evaluate(parse_record(doc), [pack], base=EX).findings[idx].status == "missing"
        doc = copy.deepcopy(raw)
        doc["evidence"][c.evidence[0]]["collected"] = "2000-01-01"
        aged += evaluate(parse_record(doc), [pack], base=EX).findings[idx].status == "stale"
    return controls, len(applicable), met, fields, flips, removed, aged


def tamper_check(trials: int = 200) -> tuple[int, int, int, int]:
    rng = random.Random(5)
    raw = json.loads((EX / "triage_v2.json").read_text())
    packs = [load_pack(n) for n in raw["packs"]]
    caught = 0
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        (base / "artifacts").mkdir()
        for sub in (EX / "artifacts").iterdir():
            (base / "artifacts" / sub.name).mkdir()
            for f in sub.iterdir():
                (base / "artifacts" / sub.name / f.name).write_bytes(f.read_bytes())
        files = sorted((base / "artifacts" / "triage_v2").iterdir())
        for _ in range(trials):
            target = rng.choice(files)
            original = target.read_bytes()
            data = bytearray(original)
            data[rng.randrange(len(data))] ^= 1 << rng.randrange(8)
            target.write_bytes(bytes(data))
            res = evaluate(parse_record(raw), packs, base=base)
            caught += res.counts()["tampered"] > 0
            target.write_bytes(original)
    edits = edit_caught = 0
    with tempfile.TemporaryDirectory() as tmp:
        h = Path(tmp) / "h.jsonl"
        for i in range(30):
            chain.append(h, {"as_of": "2026-01-01", "n": i})
        lines = h.read_text().splitlines()
        for _ in range(trials):
            mode = rng.choice(["edit", "drop", "swap"])
            ls = list(lines)
            i = rng.randrange(len(ls) - 1)
            if mode == "edit":
                e = json.loads(ls[i])
                e["attestation"]["n"] += 1
                ls[i] = json.dumps(e, sort_keys=True, separators=(",", ":"))
            elif mode == "drop":
                del ls[i]
            else:
                ls[i], ls[i + 1] = ls[i + 1], ls[i]
            h.write_text("\n".join(ls) + "\n")
            edits += 1
            try:
                chain.read(h)
            except chain.HistoryError:
                edit_caught += 1
    return trials, caught, edits, edit_caught


def speed() -> tuple[float, float]:
    raw = json.loads((EX / "triage_v2.json").read_text())
    packs = [load_pack(n) for n in raw["packs"]]
    rec = parse_record(raw)
    t = time.perf_counter()
    for _ in range(50):
        evaluate(rec, packs, base=EX)
    scans = 50 / (time.perf_counter() - t)
    rows = [Row(g, rng_bit, rng_bit) for g, rng_bit in zip(["a", "b"] * 50000, [i % 3 == 0 for i in range(100000)], strict=True)]
    t = time.perf_counter()
    fairness.audit(rows)
    return scans, 100000 / (time.perf_counter() - t)


def main() -> None:
    nf, agree, npart, decided, bad = expression_check()
    print(f"expression language: {agree} of {nf} random expressions equal Python's own answer; with unknowns, {decided} of {npart} are decided and {bad} are contradicted by any completion")
    n, worst, tables, exact = statistics_check()
    print(f"statistics: Wilson interval within {worst:.1e} of its definition on {n} cases; Fisher exact equals brute-force enumeration on {exact} of {tables} tables")
    for label, got in coverage():
        print(f"coverage of the 95% interval, {label}: {got:.1%}")
    for label, fail, ok, inc in verdict_rates():
        print(f"verdicts, {label}: fail {fail:.1%}, pass {ok:.1%}, inconclusive {inc:.1%}")
    controls, applicable, met, fields, flips, removed, aged = catalog_check()
    print(f"catalog: {controls} controls load; on the passing example {met} of {applicable} applicable controls are met")
    print(f"catalog mutation: {flips} of {fields} evidence values flip their control when made wrong; {removed} of {applicable} controls go missing when their evidence is removed; "
          f"{aged} of {applicable} go stale when it is old")
    trials, caught, edits, edit_caught = tamper_check()
    print(f"tamper evidence: {caught} of {trials} one-bit changes to an evidence file and {edit_caught} of {edits} edits, drops or swaps in a history detected")
    scans, rows = speed()
    print(f"speed on this machine (varies): {scans:,.0f} full scans per second of {controls} controls, {rows:,.0f} rows per second audited")


if __name__ == "__main__":
    main()
