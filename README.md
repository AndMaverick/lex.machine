# ⚖️ lex.machine

> **Infrastructure-as-Governance** — Automating AI compliance for the age of accountability.

AI governance isn’t paperwork. It’s engineering discipline.  
`lex.machine` defines the operational layer for Responsible AI — reproducible, auditable, and automated.

---

## 🧩 Overview

The future of AI regulation isn’t waiting for anyone.  
Every model, every dataset, every decision pipeline will need to prove that it’s **compliant, explainable, and bias-aware**.

`lex.machine` is an open framework for automating those checks. It brings together:

- **Terraform** → Compliance infrastructure as code.  
- **GitHub Actions** → Automated workflows for bias scans and audit reports.  
- **Python modules** → Governance logic, reporting engines, and risk evaluation tools.

Think of it as **DevOps for AI Ethics** — a blueprint for building systems that regulators wish existed.

---

## 🚀 Core Features

| Category | Description |
|-----------|--------------|
| 🧠 **Bias Audits** | Plug in your ML models → get automated fairness metrics (powered by `fairlearn`, `aif360`, or your own metrics). |
| 🔍 **Compliance Scans** | Run automated checks against GDPR, NIST AI RMF, and EU AI Act readiness templates. |
| 🪄 **Audit Reports** | Generate audit-ready Markdown/PDF summaries for internal review or regulatory submission. |
| 🧱 **Terraform Blueprints** | Spin up compliance-ready infrastructure for model governance, data retention, and traceability. |
| 🔐 **Policy Hooks** | Embed policy-as-code validators into CI/CD pipelines. |

---

## 🧭 Philosophy

AI is outpacing oversight.  
`lex.machine` is for those who build systems that *govern themselves.*

You don’t “talk about responsible AI” here — you **ship it**.

---

## 🧰 Repository Structure

lex.machine/
│
├── terraform/
│ ├── modules/
│ └── examples/
│
├── actions/
│ ├── compliance-scan.yml
│ ├── bias-audit.yml
│ └── model-governance.yml
│
├── python/
│ ├── governance/
│ │ ├── bias_check.py
│ │ ├── compliance_scan.py
│ │ ├── audit_report.py
│ │ └── risk_assessment.py
│ ├── cli.py
│ └── utils.py
│
├── docs/
│ ├── architecture.md
│ ├── policy_frameworks.md
│ ├── governance_matrix.md
│ └── examples.md
│
└── README.md


---

## 🏗️ Example: Bias Audit Workflow

```yaml
name: Bias Audit
on: [push, pull_request]
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run Bias Check
        run: |
          pip install -r requirements.txt
          python python/governance/bias_check.py --input model.pkl --report bias_report.json
      - name: Upload Report
        uses: actions/upload-artifact@v4
        with:
          name: bias-report
          path: bias_report.json

```
Result:
✅ Model scanned.
📊 Bias report generated.
📁 Report stored as an immutable artifact.

🧮 Example: Compliance Scan via Terraform
```
terraform init
terraform apply -var 'policy_framework=gdpr'

```
Creates audit logs, compliance markers, and traceable resource configurations aligned with policy templates.

🧱 Design Principles

Everything is auditable.
Logs, configs, and metrics aren’t side effects — they’re the product.

Compliance ≠ Bureaucracy.
This is automation for the most human problem: trust.

Policy is Code.
Governance should compile.

🧾 License

MIT — because compliance should be open-source.

🗣️ Author

Built by Maverick,
for the people still wondering if he codes.

“I don’t tweet opinions about governance.
I deploy them.”
