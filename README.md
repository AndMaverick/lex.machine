# lex.machine

**Governance as engineering.** A working blueprint for turning AI regulation into checks that run in CI: measure, gate, and keep evidence on every push.

AI governance fails when it lives in documents. lex.machine treats a control as code that can pass or fail, and maps each regulatory requirement to the check that enforces it.

## What works today

| Piece | Status | Where |
|---|---|---|
| Bias check: positive-outcome rate gap between groups, written to a JSON report | Working demo on simulated predictions | `python/governance/bias_check.py` |
| Governance matrix: EU AI Act, NIST AI RMF, and GDPR controls mapped to code | Documented | `docs/governance_matrix.md` |
| Architecture and framework notes | Documented | `docs/architecture.md`, `docs/policy_frameworks.md` |

Run the bias check:

```
pip install -r requirements.txt
python python/governance/bias_check.py
```

It generates seeded mock predictions, computes the gap in positive rates across groups, and writes `bias_report.json`. Swap the loader for your model's predictions and protected attributes to use it on real data.

## Roadmap

These are designed in the docs and not built yet. They are listed so the scope is honest.

- `compliance_scan.py`: scan model metadata against a chosen framework
- `audit_report.py`: roll audit artifacts into a Markdown or PDF summary
- Terraform modules for audit logging, retention, and access control
- A CI workflow that fails the build when the bias score crosses a threshold

## Design principles

1. **Everything is evidence.** Logs, configs, and metrics are the product, not side effects.
2. **Policy is code.** A control you cannot run is a suggestion.
3. **Compliance without ceremony.** Automation for the most human problem: trust.

## Related

The same fail-closed, evidence-first approach, applied to running AI systems, is in [mao-framework](https://github.com/AndMaverick/mao-framework). Residency checks live in [sovereign.map](https://github.com/AndMaverick/sovereign.map) and incident handling in [incident.log](https://github.com/AndMaverick/incident.log).

MIT licensed. Built by [AndMaverick LLC](https://www.andmaverick.com).
