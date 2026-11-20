"""Text, Markdown and JSON renderings of a result."""
from __future__ import annotations

import json
from fractions import Fraction
from typing import Any

from .engine import OPEN, Finding, Result, attestation, gates
from .fairness import FairnessReport

LABEL = {"satisfied": "MET", "stale": "STALE", "failed": "FAILED", "missing": "MISSING", "invalid": "INVALID", "tampered": "TAMPERED",
         "undetermined": "UNDECIDED", "not_applicable": "n/a"}
ORDER = {"tampered": 0, "invalid": 1, "failed": 2, "missing": 3, "stale": 4, "undetermined": 5, "satisfied": 6, "not_applicable": 7}
SEV = {"critical": 0, "major": 1, "minor": 2}


def pct(x: Fraction) -> str:
    return f"{float(x) * 100:.1f}%"


def _sorted(rows: list[Finding]) -> list[Finding]:
    return sorted(rows, key=lambda f: (ORDER[f.status], SEV[f.severity], f.control))


def to_text(result: Result, spec: dict[str, Any] | None = None, verbose: bool = False) -> str:
    counts = result.counts()
    applicable = sum(v for k, v in counts.items() if k != "not_applicable")
    lines = [f"{result.system}   (lex.machine, as of {result.as_of.isoformat()})", "",
             f"Readiness {pct(result.readiness)}: {counts['satisfied']} of {applicable} applicable controls met, "
             f"{counts['not_applicable']} not applicable",
             "Record fingerprint " + result.record_fingerprint[:32] + "...", ""]
    open_n = {k: counts[k] for k in ("tampered", "invalid", "failed", "missing", "stale", "undetermined") if counts[k]}
    if open_n:
        lines.append("Open: " + ", ".join(f"{v} {k}" for k, v in open_n.items()))
        lines.append("")
    for pack, rows in result.by_pack().items():
        lines.append(f"{pack}   {pct(result.pack_readiness(pack))}")
        met = sum(f.status == "satisfied" for f in rows)
        if met and not verbose:
            lines.append(f"  {met} control(s) met (list them with --all)")
        for f in _sorted(rows):
            if f.status == "not_applicable" or (f.status == "satisfied" and not verbose):
                continue
            lines.append(f"  {LABEL[f.status]:<9} {f.severity:<8} {f.control:<38} {f.reference}")
            if f.status != "satisfied":
                lines.append(f"            {f.detail}")
        na = sum(f.status == "not_applicable" for f in rows)
        if na:
            lines.append(f"  ({na} not applicable to this system)")
        lines.append("")
    unsealed = [(e, p) for e, rows in result.artifacts.items() for state, p in rows if state == "unsealed"]
    if unsealed:
        lines.append("Files with no digest recorded (not verified): " + ", ".join(f"{p}" for _, p in unsealed))
        lines.append("")
    todo = [f for f in _sorted(list(result.findings)) if f.status in OPEN]
    if todo:
        lines.append("What to do, most serious first")
        for f in todo:
            lines.append(f"  [{f.severity}] {f.control}: {f.remedy}")
        lines.append("")
    if spec is not None:
        results = gates(result, spec)
        if results:
            lines.append("Gates")
            lines += [f"  {'PASS' if ok else 'FAIL'}  {name}: {why}" for name, ok, why in results]
            lines.append("")
            lines.append("RESULT: " + ("PASS" if all(ok for _, ok, _ in results) else "FAIL"))
    lines.append("Readiness aid, not legal advice: it shows which evidence is present, current and unchanged, not what a regulation requires of you.")
    return "\n".join(lines) + "\n"


def to_markdown(result: Result, spec: dict[str, Any] | None = None) -> str:
    counts = result.counts()
    applicable = sum(v for k, v in counts.items() if k != "not_applicable")
    out = [f"# Audit summary: {result.system}", "", f"- As of: {result.as_of.isoformat()}",
           f"- Readiness: {pct(result.readiness)} ({counts['satisfied']} of {applicable} applicable controls met)",
           f"- Record fingerprint: `{result.record_fingerprint}`", "- Note: readiness aid, not legal advice", ""]
    for pack, rows in result.by_pack().items():
        out += [f"## {pack} ({pct(result.pack_readiness(pack))})", "", "| Control | Reference | Severity | Status | Detail |", "|---|---|---|---|---|"]
        for f in _sorted(rows):
            if f.status != "not_applicable":
                out.append(f"| {f.title} | {f.reference} | {f.severity} | {LABEL[f.status]} | {f.detail or '-'} |")
        out.append("")
    todo = [f for f in _sorted(list(result.findings)) if f.status in OPEN]
    out += ["## Actions", ""]
    out += [f"- [ ] **{f.control}** ({f.severity}): {f.remedy}" for f in todo] or ["- No open gaps."]
    if spec is not None and (results := gates(result, spec)):
        out += ["", "## Gates", ""] + [f"- {'PASS' if ok else 'FAIL'} `{name}`: {why}" for name, ok, why in results]
    return "\n".join(out) + "\n"


def to_json(result: Result, spec: dict[str, Any] | None = None) -> str:
    data: dict[str, Any] = {
        "attestation": attestation(result),
        "findings": [{"pack": f.pack, "control": f.control, "reference": f.reference, "severity": f.severity, "status": f.status, "detail": f.detail}
                     for f in result.findings],
        "artifacts": {e: [{"state": s, "path": p} for s, p in rows] for e, rows in result.artifacts.items()},
    }
    if spec is not None:
        data["gates"] = [{"gate": n, "passed": ok, "why": why} for n, ok, why in gates(result, spec)]
        data["passed"] = all(ok for _, ok, _ in gates(result, spec))
    return json.dumps(data, indent=1, sort_keys=True) + "\n"


def bias_text(report: FairnessReport) -> str:
    lines = [f"Fairness audit: {report.rows} rows, {len(report.groups)} groups, error rate {report.alpha:g}, "
             f"allowed gap {report.max_gap:g}, minimum ratio {report.min_ratio:g}, groups under {report.min_group} rows never decide", ""]
    lines.append(f"{'group':<18}{'n':>7}{'selected':>10}{'TPR':>9}{'FPR':>9}")
    for g in report.groups:
        tpr, fpr = g.cells("tpr"), g.cells("fpr")
        lines.append(f"{g.name:<18}{g.n:>7}{g.selected / g.n:>10.3f}{(tpr[0] / tpr[1] if tpr else float('nan')):>9.3f}{(fpr[0] / fpr[1] if fpr else float('nan')):>9.3f}")
    lines.append("")
    for m in report.metrics:
        head = f"{m.name:<20} {m.verdict.upper()}"
        if m.worst:
            w = m.worst
            head += f"   worst pair {w.a} vs {w.b}: {w.estimate:+.3f} (interval {w.low:+.3f} to {w.high:+.3f})"
            if w.p_value is not None:
                head += f", p {'< 0.0001' if w.p_value < 0.0001 else format(w.p_value, '.4f')} ({w.p_method})"
        elif m.note:
            head += f"   {m.note}"
        lines.append(head)
    lines += ["", f"OVERALL: {report.overall.upper()}"]
    if report.overall == "inconclusive":
        lines.append("Inconclusive means the sample cannot show the gap is small, or cannot show it is large. It does not satisfy the control.")
    return "\n".join(lines) + "\n"


def matrix_markdown(packs: list[Any]) -> str:
    """The controls of each pack as a Markdown table, generated from the packs so the documentation cannot drift from what runs."""
    out = ["# Governance matrix", "",
           "Generated by `python -m lex_machine matrix`. Each row is a control that runs: when it applies, what evidence it reads and how serious a gap is.", ""]
    for p in packs:
        out += [f"## {p.title}", "", f"Source: {p.source}. Catalog version {p.version}, digest `{p.digest[:16]}`.", "",
                "| Control | Reference | Severity | Evidence | Max age (days) |", "|---|---|---|---|---|"]
        for c in p.controls:
            out.append(f"| `{c.id}` {c.title} | {c.reference} | {c.severity} | {', '.join(c.evidence)} | {c.max_age_days} |")
        out.append("")
    return "\n".join(out)
