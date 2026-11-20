"""Regenerate the two example records, their artifacts and prediction files. The systems and data are synthetic.

Run from the repository root:  python examples/generate_examples.py"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lex_machine import expr  # noqa: E402
from lex_machine.fairness import audit, synthetic_predictions, to_csv  # noqa: E402
from lex_machine.packs import builtin_names, load_pack  # noqa: E402

EX = ROOT / "examples"


def full_evidence(collected: str) -> dict[str, Any]:
    """Evidence that satisfies every control in every built-in pack, derived from the packs so it cannot drift from them."""
    ev: dict[str, Any] = {}
    for name in builtin_names():
        for c in load_pack(name).controls:
            for e in c.evidence:
                ev.setdefault(e, {"collected": collected, "values": {}})
            for path in expr.references(c.requires_ast):
                parts = path.split(".")
                if parts[0] == "evidence" and len(parts) == 4 and parts[2] == "values":
                    ev[parts[1]]["values"][parts[3]] = 365 if parts[3].endswith("retention_days") else True
    ev["lawful_basis"]["values"]["basis"] = "legitimate_interests"
    return ev


def write(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def doc(title: str, body: str) -> str:
    return f"# {title}\n\n{body}\n\nSynthetic example document for lex.machine.\n"


def triage() -> dict[str, Any]:
    rows = synthetic_predictions([{"name": n, "n": 1500, "prevalence": 0.3, "tpr": 0.82, "fpr": 0.12} for n in ("group_a", "group_b", "group_c")], seed=11)
    csv_sha = write(EX / "artifacts/triage_v2/predictions.csv", to_csv(rows))
    rep = audit(rows)
    ev = full_evidence("2026-09-14")
    ev["bias_test"] = {"collected": "2026-10-02", "values": rep.values(),
                       "artifacts": [{"path": "artifacts/triage_v2/predictions.csv", "sha256": csv_sha}],
                       "note": "python -m lex_machine bias artifacts/triage_v2/predictions.csv --group group --label label --pred pred"}
    for eid, title, body in (("risk_management", "Risk management file", "Hazards, foreseeable misuse, residual risk and its acceptance."),
                             ("data_governance", "Data governance record", "Provenance, representativeness and bias examination of the training data."),
                             ("technical_documentation", "Technical documentation index", "Annex IV items and where each is kept."),
                             ("dpia", "Data protection impact assessment", "Purposes, necessity, risks to people and the measures taken.")):
        sha = write(EX / f"artifacts/triage_v2/{eid}.md", doc(title, body))
        ev[eid]["artifacts"] = [{"path": f"artifacts/triage_v2/{eid}.md", "sha256": sha}]
    return {
        "system": {"name": "triage-v2", "version": "2.3.1", "intended_purpose": "Prioritise incoming patient messages for clinical staff",
                   "risk_class": "high", "role": "both", "gpai": False, "systemic_risk": False, "personal_data": True, "automated_decisions": True,
                   "interacts_with_people": True, "generates_synthetic_content": False, "fria_scope": True},
        "packs": ["eu-ai-act", "nist-ai-rmf", "gdpr", "iso-42001"], "as_of": "2026-11-15", "evidence": ev,
        "gates": {"min_readiness": 1, "no_critical_gaps": True, "no_tampered": True, "max_stale": 0, "no_undetermined": True},
    }


def hiring() -> dict[str, Any]:
    spec = [{"name": "group_a", "n": 600, "prevalence": 0.4, "tpr": 0.80, "fpr": 0.15},
            {"name": "group_b", "n": 600, "prevalence": 0.4, "tpr": 0.55, "fpr": 0.15},
            {"name": "group_c", "n": 40, "prevalence": 0.4, "tpr": 0.70, "fpr": 0.15}]
    rows = synthetic_predictions(spec, seed=5)
    csv_sha = write(EX / "artifacts/hiring_screen/predictions.csv", to_csv(rows))
    ev = full_evidence("2026-08-20")
    ev["bias_test"] = {"collected": "2026-10-20", "values": audit(rows).values(),
                       "artifacts": [{"path": "artifacts/hiring_screen/predictions.csv", "sha256": csv_sha}]}
    ev["privacy_risk"]["collected"] = "2025-02-10"                                      # stale
    ev["data_minimisation"]["values"]["reviewed"] = False                               # evidence present, test fails
    ev["dpia"]["values"]["residual_risk_accepted"] = False
    for gone in ("human_oversight", "fria", "incident_reporting", "deployer_controls"):  # never collected
        ev.pop(gone)
    original = doc("Data protection impact assessment", "Purposes, necessity, risks to people and the measures taken.")
    sha = write(EX / "artifacts/hiring_screen/dpia.md", original)
    ev["dpia"]["artifacts"] = [{"path": "artifacts/hiring_screen/dpia.md", "sha256": sha}]
    write(EX / "artifacts/hiring_screen/dpia.md", original + "\nAmended after sign-off: residual risk reviewed and accepted.\n")   # changed after it was sealed
    return {
        "system": {"name": "cv-screen-assistant", "version": "0.9", "intended_purpose": "Rank job applications for recruiters", "risk_class": "high",
                   "role": "deployer", "personal_data": True, "automated_decisions": True, "fria_scope": True},
        "packs": ["eu-ai-act", "nist-ai-rmf", "gdpr"], "as_of": "2026-11-15", "evidence": ev,
        "gates": {"min_readiness": 0.8, "no_critical_gaps": True, "no_tampered": True, "max_stale": 0, "no_undetermined": True},
    }


def main() -> None:
    for name, build in (("triage_v2", triage), ("hiring_screen", hiring)):
        (EX / f"{name}.json").write_text(json.dumps(build(), indent=1, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
