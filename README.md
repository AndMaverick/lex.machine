# lex.machine

**Regulation, compiled.** Governance controls that run, pass, or fail, with the evidence written down. Built so an AI system can show a regulator what it did, not just what it meant to do.

A regulator asks whether your hiring model was tested for bias before it went live. The answer is a policy document, signed in March, describing a test that someone may have run. The document did not change when the model did. Nothing connects the claim to the system, so the claim can quietly stop being true.

lex.machine closes that gap by treating a control as code: each requirement from the EU AI Act, NIST AI RMF, GDPR and ISO/IEC 42001 is a control with a test, the evidence it relies on and how old that evidence may be. Evidence is dated and pinned to file digests, so a document edited after sign off is caught. Every run leaves an attestation, chained to the one before it. Standard library only, Python 3.10 to 3.13.

## Try it

```
python -m lex_machine scan examples/triage_v2.json      # exits 0: 58 of 58 applicable controls met, every gate passes
python -m lex_machine scan examples/hiring_screen.json  # exits 1: eight open controls, five failed gates
python -m lex_machine bias examples/artifacts/hiring_screen/predictions.csv --group group --label label --pred pred
```

From code:

```python
from pathlib import Path
from lex_machine.engine import evaluate, gates
from lex_machine.packs import load_pack
from lex_machine.record import load_record

record = load_record("examples/hiring_screen.json")
result = evaluate(record, [load_pack(p) for p in record.packs], base=Path("examples"))
result.readiness                    # Fraction(19, 26): exact, severity-weighted
[f.control for f in result.critical_gaps]
gates(result, record.gates)         # [(name, passed, why), ...]
```

## What a scan says

Each applicable control ends in exactly one status, strongest problem first: `tampered` (a file the evidence points at no longer matches its digest), `invalid` (a value of the wrong type), `missing` (evidence not in the record, or a file gone), `failed` (the test is false), `stale` (met, but the evidence is older than the control allows), `satisfied`. A control whose conditions on the system description are false is `not_applicable`; one the description cannot settle is `undetermined`, so leaving a fact out of the record cannot make an obligation disappear.

From `python -m lex_machine scan examples/hiring_screen.json` (a synthetic system with planted defects; every one is found, and no others):

```
cv-screen-assistant   (lex.machine, as of 2026-11-15)

Readiness 73.1%: 26 of 34 applicable controls met, 18 not applicable

Open: 1 tampered, 2 failed, 3 missing, 1 stale, 1 undetermined

eu-ai-act   50.0%
  MISSING   major    eu.art27.fria                          Regulation (EU) 2024/1689, Art. 27
            no evidence collected for: fria
  UNDECIDED major    eu.art50.interaction-disclosure        Regulation (EU) 2024/1689, Art. 50(1)
            cannot tell whether this applies; the record does not say system.interacts_with_people

nist-ai-rmf   73.8%
  FAILED    critical nist.measure-2.11                      NIST AI RMF 1.0, MEASURE 2.11
            the test is not met: evidence.bias_test.values.overall is fail
  STALE     major    nist.measure-2.10                      NIST AI RMF 1.0, MEASURE 2.10
            privacy_risk collected 2025-02-10, 643 days old, limit 365

gdpr   81.8%
  TAMPERED  critical gdpr.art35.dpia                        Regulation (EU) 2016/679, Art. 35
            changed since it was sealed: artifacts/hiring_screen/dpia.md (evidence dpia)

Gates
  FAIL  min_readiness: readiness 73.1%, required 80.0%
  FAIL  no_critical_gaps: 2 critical control(s) open: nist.measure-2.11, gdpr.art35.dpia
  FAIL  no_tampered: 1 control(s) rest on changed files
  FAIL  max_stale: 1 stale control(s), allowed 0
  FAIL  no_undetermined: 1 control(s) whose applicability is not decided

RESULT: FAIL
```

(The excerpt drops the controls that were met and the other open ones; the real output lists all of them, with what to do about each.) Note what was not flagged: the provider obligations are `not_applicable` because this organisation is the deployer, and the file the DPIA depends on was caught even though the values in the record still say it is complete.

## Fairness that says what the sample can show

`bias` does not compare a gap to a threshold as if it were exact. Every comparison carries a confidence interval (Newcombe for differences, Katz for the four fifths ratio), all pairs of groups are compared with the error rate shared across them, groups below a minimum size never decide anything, and the verdict is one of `fail` (the interval is wholly beyond the allowed gap), `pass` (wholly inside) or `inconclusive`. An inconclusive result does not satisfy a fairness control, because a sample too small to show a gap is not evidence there is none.

```
group                   n  selected      TPR      FPR
group_a               600     0.448    0.863    0.154
group_b               600     0.313    0.606    0.124
group_c                40     0.325    0.727    0.172

selection_rate_gap   INCONCLUSIVE   worst pair group_a vs group_b: +0.135 (interval +0.068 to +0.200), p < 0.0001 (Fisher exact)
four_fifths          INCONCLUSIVE   worst pair group_b vs group_a: +0.699 (interval +0.583 to +0.837)
tpr_gap              FAIL           worst pair group_a vs group_b: +0.258 (interval +0.163 to +0.347), p < 0.0001 (Fisher exact)
fpr_gap              INCONCLUSIVE   worst pair group_b vs group_c: -0.049 (interval -0.268 to +0.070), p 0.3950 (Fisher exact)

OVERALL: FAIL
```

The selection rate gap is clearly nonzero (p below 0.0001) yet `inconclusive` against a 0.10 limit, because its interval straddles the limit. The true positive rate gap is wholly beyond it, so that one fails. `bias --evidence-out` writes the result as a `bias_test` evidence item ready to drop into a record.

## The evidence record

One JSON file, strictly loaded: duplicate keys, unknown keys, NaN and wrong types are rejected.

```
{ "system": { "name": "triage-v2", "risk_class": "high", "role": "both", "personal_data": true,
              "automated_decisions": true, "interacts_with_people": true, "fria_scope": true, ... },
  "packs": ["eu-ai-act", "nist-ai-rmf", "gdpr", "iso-42001"],
  "as_of": "2026-11-15",
  "evidence": { "bias_test": { "collected": "2026-10-02",
                               "values": { "overall": "pass", ... },
                               "artifacts": [ { "path": "artifacts/triage_v2/predictions.csv", "sha256": "..." } ] },
                "risk_management": { "collected": "2026-09-14", "values": { "residual_risk_acceptable": true, ... } } },
  "gates": { "min_readiness": 1, "no_critical_gaps": true, "no_tampered": true, "max_stale": 0, "no_undetermined": true } }
```

`seal` records digests for files that have none (it never adopts a changed file unless you pass `--force`), `verify` hashes again them, `catalog` lists the evidence the packs ask for and the fields they read, and `explain <control>` shows one control in full. Exit codes: 0 everything asked for holds, 1 a gate failed or something was found changed, 2 the input could not be used.

## The catalog is data

62 controls in four packs (`eu-ai-act` 24, `nist-ai-rmf` 16, `gdpr` 12, `iso-42001` 10), as JSON in `lex_machine/packs/`. A control says when it applies and what must be true, in a small expression language whose logic has three values:

```
applies:  system.risk_class == "high" and system.role in ["provider", "both"]
requires: present(evidence.bias_test) and evidence.bias_test.values.overall == "pass"
```

Nothing is run with `eval`. A value that is not in the record is unknown, not false: `unknown and false` is false, `unknown or true` is true, anything else involving an unknown is unknown. Comparing a string with a number is an error, not a quiet false. Every expression is parsed and every path checked when a pack loads, so a typo in a pack is a load error and not a control that never fires. Write your own pack and point `--pack` at it; `lint` checks it. Each attestation records the digest of every pack it was measured against, so loosening a control changes the attestation. `docs/governance_matrix.md` is generated from the packs.

## History

`scan --history file.jsonl` appends the attestation (record fingerprint, catalog digests, a hash of every control's status, readiness) to a file where each line carries the hash of the line before it. `history verify` names the first line that was edited, reordered or removed. `docs/architecture.md` explains the design.

## How it is checked

`python examples/evaluate.py` compares the library with independent implementations (`tests/oracles.py`, which share no code with it) and by simulation, with fixed seeds. This is the output of a run:

```
expression language: 5000 of 5000 random expressions equal Python's own answer; with unknowns, 1500 of 3000 are decided and 0 are contradicted by any completion
statistics: Wilson interval within 2.1e-15 of its definition on 1000 cases; Fisher exact equals brute-force enumeration on 1049 of 1049 tables
coverage of the 95% interval, difference, n=100 each: 95.5%
coverage of the 95% interval, difference, n=400 each: 94.7%
coverage of the 95% interval, difference, n=1000 each: 94.9%
coverage of the 95% interval, ratio, n=200 each: 94.9%
coverage of the 95% interval, ratio, n=1000 each: 94.4%
verdicts, n=500 per group, true gap 0.00: fail 0.0%, pass 79.4%, inconclusive 20.6%
verdicts, n=500 per group, true gap 0.05: fail 0.0%, pass 39.4%, inconclusive 60.6%
verdicts, n=500 per group, true gap 0.10: fail 2.6%, pass 2.7%, inconclusive 94.7%
verdicts, n=500 per group, true gap 0.15: fail 39.0%, pass 0.1%, inconclusive 60.9%
verdicts, n=2000 per group, true gap 0.15: fail 92.7%, pass 0.0%, inconclusive 7.3%
verdicts, n=2000 per group, true gap 0.00: fail 0.0%, pass 100.0%, inconclusive 0.0%
catalog: 62 controls load; on the passing example 58 of 58 applicable controls are met
catalog mutation: 73 of 73 evidence values flip their control when made wrong; 58 of 58 controls go missing when their evidence is removed; 58 of 58 go stale when it is old
tamper evidence: 200 of 200 one-bit changes to an evidence file and 200 of 200 edits, drops or swaps in a history detected
speed on this machine (varies): 426 full scans per second of 62 controls, 5,097,310 rows per second audited
```

The speed line depends on the machine; the rest is deterministic. The 127 tests run on Python 3.10 to 3.13 in CI with ruff and strict mypy, and include a check that the output is identical byte for byte across different `PYTHONHASHSEED` values.

```
python -m unittest discover -s tests -t . -v
```

## Honest limits

- Mappings are the author's reading of each provision, written to make readiness checkable. They are not legal advice and do not decide what a regulation requires of you. Edit the packs to match your counsel's view.
- The packs do not encode when each obligation starts to apply, and the EU AI Act timeline has been the subject of amendment proposals. Check the current position.
- A scan shows that evidence exists, is current, is unchanged and says what the control needs. It does not judge whether a document is any good or whether what it says is true. A digest shows a file did not change after it was sealed, not that it was right when sealed.
- The fairness verdicts are only as good as the predictions and group labels they are given. With one decision per person they are sound; repeated decisions about the same people overstate the sample. Interval coverage is close to the nominal 95 percent in simulation (94.4 to 95.5 above) but not exact, and the Bonferroni split across pairs is conservative.
- Demonstrating fairness takes data. At 500 per group with no true gap, the audit reaches `pass` 79 percent of the time against a 0.10 limit, and at a true gap of 0.05 only 39 percent. The rest are `inconclusive`, by design. At 2,000 per group a gap of 0.15 is `fail` 93 percent of the time.
- The exact Fisher test is used up to 2,000 rows in a pair and a normal approximation beyond, and the report says which. The interval, not the p value, decides the verdict.
- The history chain shows an edit to an earlier entry. It cannot show that the newest entries were cut off, so publish the head somewhere the writer cannot edit.
- The example systems, evidence and predictions are synthetic.

## Original modules

The first version, `python/governance/` (`compliance_scan`, `audit_report`, `bias_check`), is unchanged and its tests still run. The new engine reads richer evidence, so use it for anything new. `requirements.txt` lists what only the original `bias_check.py` needs; `lex_machine` needs nothing.

## Principles

1. **Evidence has an age.** A test result from last year says little about this year's model, so every control states how old its evidence may be, and older evidence is marked `stale` and not silently accepted.
2. **A control that cannot run is a suggestion.** If nothing can pass or fail it, nobody finds out when it stops being true.
3. **Missing is not the same as fine.** A fact left out of the record leaves a control `undetermined`. It never makes the obligation disappear.

## Related

The same fail closed, evidence first approach for running systems is in [mao-framework](https://github.com/AndMaverick/mao-framework). Residency checks live in [sovereign.map](https://github.com/AndMaverick/sovereign.map) and incident handling in [incident.log](https://github.com/AndMaverick/incident.log).

MIT licensed. Built by [AndMaverick LLC](https://www.andmaverick.com).

---

**Read the thinking:** [Nobody Signs for the Agent](https://blog.andmaverick.com/nobody-signs-for-the-agent?utm_source=github&utm_medium=repo&utm_campaign=lex.machine)

**If this is your problem.** If a system you run can fail in ways that matter, the controls belong in the architecture, not in the postmortem. I am happy to talk through yours. [Begin a conversation](https://calendly.com/andmaverick?utm_source=github&utm_medium=repo&utm_campaign=lex.machine).
