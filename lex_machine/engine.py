"""Evaluate a record against policy packs and say, control by control, what is met and why not.

Each applicable control ends in exactly one status, strongest problem first:

- ``tampered``  a file the evidence points at no longer matches the digest recorded for it
- ``invalid``   the evidence has a value of the wrong type for what the control tests
- ``missing``   evidence the control needs is not in the record, or a file it points at is not there
- ``failed``    the evidence is there and the test comes out false
- ``stale``     the test is met but the evidence is older than the control allows
- ``satisfied`` met, fresh, and (where digests are recorded) verified

``not_applicable`` is for a control whose conditions on the system description are false, and ``undetermined`` is for one where the
description does not say enough to tell, so a record that omits a fact cannot make obligations disappear.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from . import expr
from ._version import __version__
from .errors import ExprError
from .packs import WEIGHT, Control, Pack
from .record import Record, canonical, fingerprint, sha256_text, verify_artifacts

STATUSES = ("satisfied", "stale", "failed", "missing", "invalid", "tampered", "undetermined", "not_applicable")
OPEN = {"stale", "failed", "missing", "invalid", "tampered", "undetermined"}


@dataclass(frozen=True)
class Finding:
    pack: str
    control: str
    title: str
    reference: str
    severity: str
    status: str
    detail: str
    evidence: tuple[str, ...]
    remedy: str


@dataclass(frozen=True)
class Result:
    system: str
    as_of: _dt.date
    record_fingerprint: str
    findings: tuple[Finding, ...]
    packs: tuple[tuple[str, str], ...]          # (name, digest)
    artifacts: dict[str, list[tuple[str, str]]]

    def counts(self) -> dict[str, int]:
        out = dict.fromkeys(STATUSES, 0)
        for f in self.findings:
            out[f.status] += 1
        return out

    @property
    def readiness(self) -> Fraction:
        """Severity-weighted share of applicable controls that are satisfied (critical 5, major 3, minor 1). Exact."""
        total = sum(WEIGHT[f.severity] for f in self.findings if f.status != "not_applicable")
        met = sum(WEIGHT[f.severity] for f in self.findings if f.status == "satisfied")
        return Fraction(met, total) if total else Fraction(0)

    def by_pack(self) -> dict[str, list[Finding]]:
        out: dict[str, list[Finding]] = {}
        for f in self.findings:
            out.setdefault(f.pack, []).append(f)
        return out

    def pack_readiness(self, pack: str) -> Fraction:
        rows = [f for f in self.findings if f.pack == pack and f.status != "not_applicable"]
        total = sum(WEIGHT[f.severity] for f in rows)
        return Fraction(sum(WEIGHT[f.severity] for f in rows if f.status == "satisfied"), total) if total else Fraction(0)

    @property
    def critical_gaps(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "critical" and f.status in OPEN]


def evaluate_control(control: Control, record: Record, as_of: _dt.date, tamper: dict[str, list[tuple[str, str]]], pack: str) -> Finding:
    def finding(status: str, detail: str = "") -> Finding:
        return Finding(pack, control.id, control.title, control.reference, control.severity, status, detail, control.evidence, control.remedy)

    ctx = expr.Context(record.system, record.context_evidence(), as_of)
    try:
        applies = expr.truth(control.applies_ast, ctx)
    except ExprError as e:
        return finding("invalid", f"applicability: {e}")
    if applies is False:
        return finding("not_applicable")
    if applies is None:
        names = ", ".join(sorted(ctx.missing)) or "the system description"
        return finding("undetermined", f"cannot tell whether this applies; the record does not say {names}")
    bad = [(e, p) for e in control.evidence for state, p in tamper.get(e, []) if state == "mismatch"]
    if bad:
        return finding("tampered", "changed since it was sealed: " + ", ".join(f"{p} (evidence {e})" for e, p in bad))
    absent_ids = [e for e in control.evidence if e not in record.evidence]
    if absent_ids:
        return finding("missing", "no evidence collected for: " + ", ".join(absent_ids))
    ctx = expr.Context(record.system, record.context_evidence(), as_of)
    try:
        ok = expr.truth(control.requires_ast, ctx)
    except ExprError as e:
        return finding("invalid", str(e))
    absent = [(e, p) for e in control.evidence for state, p in tamper.get(e, []) if state == "absent"]
    if absent:
        return finding("missing", "file not found: " + ", ".join(f"{p} (evidence {e})" for e, p in absent))
    if ok is None:
        gone = sorted(ctx.missing)
        return finding("missing", "not in the record: " + ", ".join(gone) if gone else "not in the record")
    if ok is False:
        return finding("failed", _why_failed(control, ctx))
    old = []
    for eid in control.evidence:
        item = record.evidence.get(eid)
        if item is not None and (as_of - item.collected).days > control.max_age_days:
            old.append(f"{eid} collected {item.collected.isoformat()}, {(as_of - item.collected).days} days old, limit {control.max_age_days}")
    if old:
        return finding("stale", "; ".join(old))
    return finding("satisfied")


def _why_failed(control: Control, ctx: expr.Context) -> str:
    """The values the test read, so the reader sees what the evidence actually said."""
    seen = []
    for path in sorted(expr.references(control.requires_ast)):
        if path.startswith("evidence.") and path.count(".") == 1:
            continue
        v = ctx.lookup(path, note=False)
        seen.append(f"{path} is {_show(v)}")
    return "the test is not met: " + "; ".join(seen)


def _show(v: Any) -> str:
    return "true" if v is True else "false" if v is False else "not recorded" if v is None else str(v)


def evaluate(record: Record, packs: list[Pack], *, as_of: _dt.date | None = None, base: Path | None = None) -> Result:
    day = as_of or record.as_of or _dt.date.today()
    tamper = verify_artifacts(record, base) if base is not None else {}
    findings = []
    for pack in packs:
        for c in pack.controls:
            findings.append(evaluate_control(c, record, day, tamper, pack.name))
    return Result(record.system["name"], day, fingerprint(record.raw), tuple(findings), tuple((p.name, p.digest) for p in packs), tamper)


def attestation(result: Result) -> dict[str, Any]:
    """A small signed-by-hash statement of the result: what was measured, against which catalog versions, and what came out."""
    rows = [[f.pack, f.control, f.status] for f in result.findings]
    body = {
        "lex_machine": __version__, "system": result.system, "as_of": result.as_of.isoformat(),
        "record": result.record_fingerprint, "packs": dict(result.packs),
        "findings": sha256_text(canonical(rows)), "readiness": _pct(result.readiness), "counts": result.counts(),
    }
    return {**body, "id": sha256_text(canonical(body))}


def _pct(x: Fraction) -> str:
    return f"{float(x) * 100:.1f}%"


def gates(result: Result, spec: dict[str, Any]) -> list[tuple[str, bool, str]]:
    """(name, passed, why) for each gate the record asks for."""
    out = []
    counts = result.counts()
    if "min_readiness" in spec:
        need = Fraction(str(spec["min_readiness"]))
        out.append(("min_readiness", result.readiness >= need, f"readiness {_pct(result.readiness)}, required {_pct(need)}"))
    if spec.get("no_critical_gaps"):
        gaps = result.critical_gaps
        out.append(("no_critical_gaps", not gaps, f"{len(gaps)} critical control(s) open" + (": " + ", ".join(f.control for f in gaps) if gaps else "")))
    if spec.get("no_tampered"):
        out.append(("no_tampered", counts["tampered"] == 0, f"{counts['tampered']} control(s) rest on changed files"))
    if "max_stale" in spec:
        out.append(("max_stale", counts["stale"] <= spec["max_stale"], f"{counts['stale']} stale control(s), allowed {spec['max_stale']}"))
    if spec.get("no_undetermined"):
        out.append(("no_undetermined", counts["undetermined"] == 0, f"{counts['undetermined']} control(s) whose applicability is not decided"))
    return out
