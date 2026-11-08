"""audit_report: render scan results and optional bias metrics as a Markdown audit summary."""

from __future__ import annotations

import json
import sys

from .compliance_scan import FRAMEWORKS, readiness, scan

MARK = {"met": "MET", "missing": "MISSING", "failed": "FAILED"}


def render(model: str, framework: str, findings: list, bias_metrics: dict | None = None) -> str:
    score = readiness(findings)
    lines = [
        f"# Audit summary: {model}", "",
        f"- Framework: {framework}",
        f"- Controls met: {sum(f.status == 'met' for f in findings)} of {len(findings)} ({score:.0%})",
        "- Note: readiness aid, not legal advice", "",
        "## Controls", "",
        "| Control | Reference | Status | Detail |", "|---|---|---|---|",
    ]
    for f in findings:
        lines.append(f"| {f.title} | {f.reference} | {MARK[f.status]} | {f.detail or '-'} |")
    if bias_metrics:
        lines += ["", "## Bias metrics", ""]
        lines += [f"- {key}: {value}" for key, value in sorted(bias_metrics.items())]
    gaps = [f for f in findings if f.status != "met"]
    lines += ["", "## Actions", ""]
    lines += [f"- [ ] {f.title}: {f.detail}" for f in gaps] or ["- No open gaps."]
    return "\n".join(lines) + "\n"


def main(argv: list) -> int:
    """python -m python.governance.audit_report metadata.json framework [bias_report.json]"""
    if len(argv) < 2 or argv[1] not in FRAMEWORKS:
        print(f"usage: audit_report metadata.json {{{'|'.join(FRAMEWORKS)}}} [bias_report.json]", file=sys.stderr)
        return 2
    with open(argv[0], encoding="utf-8") as handle:
        metadata = json.load(handle)
    bias = None
    if len(argv) > 2:
        with open(argv[2], encoding="utf-8") as handle:
            bias = json.load(handle)
        metadata.setdefault("bias_score", bias.get("bias_score"))
    print(render(metadata.get("model", "unnamed model"), argv[1], scan(metadata, argv[1]), bias))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
