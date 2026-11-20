# How the frameworks are read

lex.machine turns four frameworks into controls that run: the EU AI Act, the NIST AI Risk Management Framework, the GDPR and ISO/IEC 42001. This page says how each was read, what is covered and what is deliberately not. The full list of controls, generated from the packs, is in [governance_matrix.md](governance_matrix.md).

None of this is legal advice. A control is the author's reading of a provision, written so that engineering readiness can be checked. It does not decide what a regulation requires of you. The packs are plain JSON: if your counsel reads a provision differently, edit the control and the change shows in the pack digest.

## EU AI Act (Regulation (EU) 2024/1689)

Covered: the prohibited-practices screen (Art. 5); classification (Art. 6); the provider obligations for high-risk systems (Arts. 9 to 15, 17, 43, 47, 49, 72, 73), including the bias examination in Art. 10; deployer obligations and the fundamental rights impact assessment (Arts. 26 and 27); AI literacy (Art. 4); the transparency duties for systems that talk to people or generate content (Art. 50); and the duties of general-purpose model providers, including systemic-risk models (Arts. 53 and 55).

Applicability is decided from the system description (`risk_class`, `role`, `gpai`, `systemic_risk`, `interacts_with_people`, `generates_synthetic_content`, `fria_scope`). A fact the record does not state leaves the control `undetermined` instead of making it vanish.

Not covered: the dates on which each obligation starts to apply, which have been the subject of amendment proposals; sector-specific rules for systems under Annex I; the content tests behind each Annex III category; and authority guidance as it is issued. Check the current position before you rely on a date.

## NIST AI RMF 1.0

Covered: sixteen subcategories across GOVERN, MAP, MEASURE and MANAGE that can be shown with evidence, among them legal requirements (GOVERN 1.1), roles (GOVERN 2.1), context (MAP 1.1), impacts (MAP 5.1), validity (MEASURE 2.5), safety and security (MEASURE 2.6 and 2.7), privacy (MEASURE 2.10), fairness and bias (MEASURE 2.11), and post-deployment monitoring and incidents (MANAGE 4.1 and 4.3). The framework is voluntary, so every control applies to every system.

Not covered: the remaining subcategories, and the NIST playbook's suggested actions. The packs check that evidence exists, is current and unchanged. They do not judge its quality.

## GDPR (Regulation (EU) 2016/679)

Covered, for systems that process personal data: lawful basis (Art. 6), minimisation and storage limitation (Art. 5), accountability (Art. 5(2)), information to people (Arts. 13 and 14), data subject rights (Arts. 12 to 22), automated decisions (Art. 22), protection by design (Art. 25), records of processing (Art. 30), security (Art. 32), breach notification (Arts. 33 and 34) and the data protection impact assessment (Art. 35).

Not covered: international transfers, joint controllership and processor contracts, and the national rules that sit on top of the Regulation.

## ISO/IEC 42001:2023

Covered at the level of the Annex A control categories (A.2 to A.10) and the internal audit clause (9.2). It maps to the same evidence as the other packs, which is the point: collect an item once and it counts wherever it is relevant.

Not covered: the management system clauses other than 9.2, and the individual Annex A controls beneath each category.

## How evidence is treated

A control is met only when the evidence exists, the test on its values is true, it is no older than the control allows, and any file it points at still matches the digest recorded for it. A value that is not in the record is unknown, never false, so a gap cannot make a control look met. A fairness result that is inconclusive does not satisfy a fairness control, because a sample that cannot show a gap is small is not evidence that it is small.
