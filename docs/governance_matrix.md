# 🧩 Governance Matrix

## 🎯 Purpose

This matrix links **policy frameworks** → **governance controls** → **automated enforcement** within `lex.machine`.  
It serves as both documentation and an executable blueprint for compliance-as-code.

---

## ⚖️ Framework-to-Code Mapping

| Framework | Control Area | Objective | Code / Workflow |
|------------|---------------|------------|-----------------|
| **EU AI Act** | Risk Classification | Define AI system risk levels | `terraform/model_governance.yml` *(planned)* |
| **EU AI Act** | Bias & Fairness | Detect disparate outcomes | `python/governance/bias_check.py` + `bias-audit.yml` |
| **EU AI Act** | Record-Keeping | Store immutable audit logs | GitHub Actions Artifacts + Terraform storage |
| **NIST AI RMF** | Measure | Quantify and monitor system risks | `bias_check.py` + `compliance_scan.py` *(planned)* |
| **NIST AI RMF** | Manage | Run continuous audit workflows | `.github/workflows/bias-audit.yml` |
| **NIST AI RMF** | Govern | Maintain governance documentation | `docs/policy_frameworks.md` + `docs/architecture.md` |
| **GDPR** | Data Minimization | Validate scope of data used in models | Terraform variable enforcement *(planned)* |
| **GDPR** | Accountability | Produce versioned audit artifacts | GitHub Actions artifact uploads |
| **GDPR** | Right to Explanation | Generate transparency reports | `python/governance/audit_report.py` *(planned)* |

---

## 🧠 Matrix Logic

1. **Frameworks** define *what* compliance looks like.  
2. **Controls** define *how* that intent is implemented.  
3. **Code** enforces those controls automatically.  

This creates a living bridge between **policy** and **execution** — every push can be traced to a governance requirement.

---

## 🔄 Workflow Integration

Framework → Control → Code → CI/CD → Evidence


Each merge request becomes a governance event, leaving an immutable compliance trail.

---

## 🧱 Next Steps

- Expand Terraform modules for audit storage & classification.  
- Integrate Streamlit/Gradio dashboards for compliance visualization.  
- Add mapping for ISO/IEC 42001 and U.S. AI Bill of Rights.

---

**Maintainer:** **Maverick**  
**Project:** *lex.machine*  

> “From regulation to runtime.”
