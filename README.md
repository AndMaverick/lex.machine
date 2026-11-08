# lex.machine

**Regulation, compiled.** Governance controls that run, pass, or fail, with the evidence written down. Built so an AI system can show a regulator what it did, not just what it meant to do.

AI governance fails when it lives in documents. lex.machine treats a control as code: each requirement from the EU AI Act, NIST AI RMF, and GDPR maps to a check, and every check leaves a record.

## What works today

| Piece | What it does | Where |
|---|---|---|
| **Compliance scan** | Checks a model's metadata against a controls catalog for EU AI Act, NIST AI RMF, or GDPR. Each control comes back met, missing, or failed, with its article or function reference. | `python/governance/compliance_scan.py` |
| **Audit report** | Renders scan results and bias metrics into a Markdown audit summary with a readiness score and an action checklist. | `python/governance/audit_report.py` |
| **Bias check** | Computes the positive-outcome rate gap between groups and writes a JSON report. Runs on simulated predictions today, ready to point at real ones. | `python/governance/bias_check.py` |
| **Controls map** | Frameworks mapped to controls mapped to code. | `docs/governance_matrix.md` |
| **Tests and CI** | The scan and report modules are covered by a test suite that runs on every push. | `tests/` |

## Try it

```python
from python.governance.compliance_scan import scan, readiness
from python.governance.audit_report import render

metadata = {
    "model": "triage-v2", "risk_class": "high", "audit_logging": True,
    "human_oversight": True, "bias_score": 0.04, "owner": "Platform AI",
}
findings = scan(metadata, "eu-ai-act")
print(f"{readiness(findings):.0%} ready")
print(render("triage-v2", "eu-ai-act", findings))
```

Or from files:

```
python -m python.governance.audit_report metadata.json eu-ai-act bias_report.json
```

The scan is a readiness aid. It tells you which evidence is missing and which test failed against thresholds you set. It does not decide what a regulation legally requires.

## Roadmap

- Terraform modules for audit logging, retention, and access control
- A CI workflow that fails the build when readiness or the bias score crosses a threshold
- ISO/IEC 42001 control mapping

## Principles

1. **Everything is evidence.** Logs, configs, and metrics are the product, not side effects.
2. **Policy is code.** A control you cannot run is a suggestion.
3. **Compliance without ceremony.** Automation for the most human problem: trust.

## Related

The same fail-closed, evidence-first approach for running systems is in [mao-framework](https://github.com/AndMaverick/mao-framework). Residency checks live in [sovereign.map](https://github.com/AndMaverick/sovereign.map) and incident handling in [incident.log](https://github.com/AndMaverick/incident.log).

MIT licensed. Built by [AndMaverick LLC](https://www.andmaverick.com).
