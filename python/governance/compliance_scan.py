"""compliance_scan: check a model's metadata against a controls catalog and report gaps.

This is a readiness aid, not legal advice. The catalog maps each control to the
evidence a system should be able to show. It does not decide what a regulation requires.
"""

from __future__ import annotations

from dataclasses import dataclass

# control id -> (title, evidence key expected in the metadata, frameworks that reference it)
CONTROLS = {
    "risk-classification": ("Risk classification recorded", "risk_class",
                            {"eu-ai-act": "Art. 6 and Annex III", "nist-ai-rmf": "MAP"}),
    "risk-management": ("Risk management process documented", "risk_management",
                        {"eu-ai-act": "Art. 9", "nist-ai-rmf": "MANAGE"}),
    "data-governance": ("Training data governance documented", "data_governance",
                        {"eu-ai-act": "Art. 10", "nist-ai-rmf": "MAP"}),
    "bias-testing": ("Bias or fairness test with a result", "bias_score",
                     {"eu-ai-act": "Art. 10", "nist-ai-rmf": "MEASURE"}),
    "record-keeping": ("Audit logging enabled", "audit_logging",
                       {"eu-ai-act": "Art. 12", "gdpr": "Art. 5(2)"}),
    "transparency": ("User-facing transparency notice", "transparency_notice",
                     {"eu-ai-act": "Art. 13", "gdpr": "Arts. 13 to 15"}),
    "human-oversight": ("Human oversight mechanism", "human_oversight",
                        {"eu-ai-act": "Art. 14", "nist-ai-rmf": "GOVERN", "gdpr": "Art. 22"}),
    "data-minimization": ("Data minimization reviewed", "data_minimization",
                          {"gdpr": "Art. 5(1)(c)"}),
    "accountable-owner": ("Named accountable owner", "owner",
                          {"nist-ai-rmf": "GOVERN", "gdpr": "Art. 5(2)"}),
}

FRAMEWORKS = ("eu-ai-act", "nist-ai-rmf", "gdpr")


@dataclass(frozen=True)
class Finding:
    control: str
    title: str
    reference: str
    status: str  # "met", "missing", or "failed"
    detail: str = ""


def controls_for(framework: str) -> list:
    if framework not in FRAMEWORKS:
        raise ValueError(f"unknown framework: {framework}. Choose from {', '.join(FRAMEWORKS)}")
    return [cid for cid, (_, _, refs) in CONTROLS.items() if framework in refs]


def scan(metadata: dict, framework: str, bias_threshold: float = 0.1) -> list:
    """Evaluate every control for a framework against the metadata.

    A control is met when its evidence key is present and truthy. The bias control
    also fails when the recorded score exceeds bias_threshold.
    """
    findings = []
    for cid in controls_for(framework):
        title, key, refs = CONTROLS[cid]
        value = metadata.get(key)
        if value in (None, "", False):
            findings.append(Finding(cid, title, refs[framework], "missing", f"no evidence for '{key}'"))
        elif cid == "bias-testing" and float(value) > bias_threshold:
            findings.append(Finding(cid, title, refs[framework], "failed",
                                    f"bias score {value} exceeds threshold {bias_threshold}"))
        else:
            findings.append(Finding(cid, title, refs[framework], "met"))
    return findings


def readiness(findings: list) -> float:
    """Share of controls met, from 0 to 1."""
    return sum(f.status == "met" for f in findings) / len(findings) if findings else 0.0
