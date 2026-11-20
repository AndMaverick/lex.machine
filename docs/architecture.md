# Architecture

lex.machine has one job: show, with evidence that can be checked, which controls a system meets today and what changed since the last time anyone looked.

## Pieces

| Module | What it does |
|---|---|
| `expr` | A small expression language for controls with three-valued logic. Parsed and walked; nothing is executed. |
| `packs` | The catalog of controls as JSON. Every expression is parsed and every path checked when a pack loads. |
| `record` | The evidence record, loaded strictly, and the re-hashing of the files it points at. |
| `engine` | Evaluates a record against packs. Each control ends in exactly one status. Computes exact readiness and applies gates. |
| `fairness` | Group comparisons with confidence intervals and a pass, fail or inconclusive verdict. |
| `chain` | A hash-chained scan history, so an edit to an earlier result is visible. |
| `report` | Text, Markdown and JSON renderings, and the governance matrix. |
| `cli` | `scan`, `bias`, `seal`, `verify`, `history`, `packs`, `explain`, `lint`, `catalog`, `matrix`, `fingerprint`. |

The modules under `python/governance/` are the first version and are unchanged.

## Flow

```
system description + evidence (dated, with file digests)
        |
        v
  packs (what must be true)  ->  engine  ->  findings, readiness, gates
                                      |
                                      v
                          attestation (record + catalog + result hashes)
                                      |
                                      v
                          history (each entry hashes the one before)
```

## Decisions worth knowing

- **Three-valued logic.** Missing evidence is unknown, and unknown never satisfies a control. A decided control is not held up by an unrelated gap.
- **Statuses, not a score.** A readiness percentage is reported, but every control also ends in a named status with the reason: `satisfied`, `failed`, `missing`, `stale`, `tampered`, `invalid`, `undetermined` or `not_applicable`.
- **Evidence is pinned.** A file recorded with a digest that no longer matches turns every control that relies on it to `tampered`, even if the values in the record still look fine.
- **The catalog is pinned too.** Each attestation names the digest of every pack it was measured against, so loosening a control changes the attestation.
- **Statistics say what they cannot show.** A fairness gap is reported with an interval, and a sample too small to decide is `inconclusive`, which does not satisfy a control.
- **Exact arithmetic where it is cheap.** Readiness is a fraction of integer weights, and the exact Fisher test compares integers.

## What it does not do

It does not decide what a regulation requires, judge the quality of a document, or prove the evidence is true. It shows that the evidence is present, current, unchanged and, where it is numeric, what it says. Publish the history head somewhere the writer cannot edit, because a chain shows edits but cannot show that its newest entries were cut off.
