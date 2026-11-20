"""Command line: scan, bias, seal, verify, history, packs, explain, lint, catalog, fingerprint.

Exit codes: 0 everything asked for holds, 1 a gate failed or something was found changed, 2 the input could not be used.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

from . import chain, report
from ._version import __version__
from .engine import attestation, evaluate, gates
from .errors import LexError, RecordError
from .fairness import FairnessError, audit, read_rows
from .packs import Pack, builtin_names, evidence_catalog, load_pack
from .record import fingerprint, load_record, loads, parse_date, verify_artifacts


def _packs(names: list[str]) -> list[Pack]:
    if not names:
        raise RecordError("no packs to measure against: list them under 'packs' in the record or pass --pack (built in: " + ", ".join(builtin_names()) + ")")
    return [load_pack(n) for n in names]


def _read(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise LexError(f"cannot read {path}: {e.strerror or e}") from None


def cmd_scan(args: argparse.Namespace) -> int:
    rec = load_record(args.record)
    packs = _packs(args.pack or list(rec.packs))
    as_of = parse_date(args.as_of, "--as-of") if args.as_of else None
    base = Path(args.record).resolve().parent
    result = evaluate(rec, packs, as_of=as_of, base=base)
    spec = rec.gates or None
    if args.format == "text":
        sys.stdout.write(report.to_text(result, spec, verbose=args.all))
    else:
        sys.stdout.write((report.to_markdown if args.format == "markdown" else report.to_json)(result, spec))
    if args.history:
        entry = chain.append(Path(args.history), attestation(result))
        print(f"history: entry {entry['seq']} added, head {entry['hash'][:16]}...", file=sys.stderr)
    if spec:
        return 0 if all(ok for _, ok, _ in gates(result, spec)) else 1
    return 0


def cmd_bias(args: argparse.Namespace) -> int:
    rows = read_rows(_read(args.csv), args.group, args.pred, args.label)
    rep = audit(rows, max_gap=args.max_gap, min_ratio=args.min_ratio, alpha=args.alpha, min_group=args.min_group)
    if args.json:
        sys.stdout.write(json.dumps({"values": rep.values()}, indent=1, sort_keys=True) + "\n")
    else:
        sys.stdout.write(report.bias_text(rep))
    if args.evidence_out:
        item = {"collected": args.collected or _dt.date.today().isoformat(), "values": rep.values()}
        Path(args.evidence_out).write_text(json.dumps({"bias_test": item}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if rep.overall == "pass" else 1


def cmd_verify(args: argparse.Namespace) -> int:
    rec = load_record(args.record)
    rows = verify_artifacts(rec, Path(args.record).resolve().parent)
    bad = 0
    for eid, items in rows.items():
        for state, path in items:
            print(f"{state:<9} {eid}: {path}")
            bad += state in {"mismatch", "absent"}
    if not rows:
        print("no artifacts listed in the record")
    return 1 if bad else 0


def cmd_seal(args: argparse.Namespace) -> int:
    from .record import file_sha256
    path = Path(args.record)
    rec = load_record(path)
    base = path.resolve().parent
    raw = json.loads(_read(args.record))
    changed = 0
    for eid, ev in rec.evidence.items():
        for i, a in enumerate(ev.artifacts):
            target = (base / a.path).resolve()
            if not target.is_file():
                print(f"absent    {eid}: {a.path}")
                continue
            digest = file_sha256(target)
            if a.sha256 is None or (args.force and a.sha256 != digest):
                raw["evidence"][eid]["artifacts"][i]["sha256"] = digest
                changed += 1
                print(f"sealed    {eid}: {a.path}  {digest}")
            elif a.sha256 != digest:
                print(f"MISMATCH  {eid}: {a.path}  recorded {a.sha256[:16]}..., on disk {digest[:16]}...  (use --force only if the change is intended)")
            else:
                print(f"ok        {eid}: {a.path}")
    if args.write and changed:
        path.write_text(json.dumps(raw, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {changed} digest(s) to {args.record}")
    elif changed:
        print(f"{changed} digest(s) not written; add --write to record them")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    entries = chain.read(Path(args.file))
    if args.action == "verify":
        print(f"{len(entries)} entries, head {chain.head(entries)}")
        return 0
    for e in entries:
        a = e["attestation"]
        print(f"{e['seq']:>4}  {a['as_of']}  readiness {a['readiness']:>6}  {a['system']}  {e['hash'][:16]}...")
    return 0


def cmd_packs(args: argparse.Namespace) -> int:
    for name in builtin_names():
        p = load_pack(name)
        print(f"{p.name:<14} {len(p.controls):>3} controls  version {p.version}  digest {p.digest[:16]}...  {p.source}")
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    packs = [load_pack(n) for n in (args.pack or builtin_names())]
    for p in packs:
        for c in p.controls:
            if c.id == args.control:
                print(f"{c.id}   [{c.severity}]   {p.name}\n{c.title}\nReference: {c.reference}\nApplies when: {c.applies}\nMet when: {c.requires}")
                print(f"Evidence: {', '.join(c.evidence)} (no older than {c.max_age_days} days)\nTo do: {c.remedy}")
                return 0
    raise LexError(f"no control {args.control!r}")


def cmd_lint(args: argparse.Namespace) -> int:
    for name in args.packs:
        p = load_pack(name)
        print(f"ok  {p.name}: {len(p.controls)} controls, digest {p.digest}")
    return 0


def cmd_catalog(args: argparse.Namespace) -> int:
    cat = evidence_catalog([load_pack(n) for n in (args.pack or builtin_names())])
    for eid, row in cat.items():
        print(f"{eid}\n  values read: {', '.join(row['values']) or '(presence only)'}\n  used by: {', '.join(row['controls'])}")
    return 0


def cmd_matrix(args: argparse.Namespace) -> int:
    sys.stdout.write(report.matrix_markdown([load_pack(n) for n in (args.pack or builtin_names())]))
    return 0


def cmd_fingerprint(args: argparse.Namespace) -> int:
    print(fingerprint(loads(_read(args.record))))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lex-machine", description="Regulation, compiled: controls checked against dated, digest-pinned evidence.")
    p.add_argument("--version", action="version", version=f"lex.machine {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="measure a record against policy packs and apply its gates")
    s.add_argument("record")
    s.add_argument("--pack", action="append", help="built-in pack name or path to a pack file (repeatable); default: the record's own list")
    s.add_argument("--as-of", help="evaluate as of this date (YYYY-MM-DD); default: the record's as_of, else today")
    s.add_argument("--format", choices=["text", "markdown", "json"], default="text")
    s.add_argument("--all", action="store_true", help="in text output, also list the controls that are met")
    s.add_argument("--history", help="append an attestation to this hash-chained history file")
    s.set_defaults(fn=cmd_scan)
    b = sub.add_parser("bias", help="fairness audit of predictions with confidence intervals and a pass, fail or inconclusive verdict")
    b.add_argument("csv")
    b.add_argument("--group", required=True, help="column holding the group")
    b.add_argument("--pred", required=True, help="column holding the model's decision (1/0, true/false, yes/no)")
    b.add_argument("--label", help="column holding the true outcome; enables the TPR and FPR comparisons")
    b.add_argument("--max-gap", type=float, default=0.1)
    b.add_argument("--min-ratio", type=float, default=0.8)
    b.add_argument("--alpha", type=float, default=0.05)
    b.add_argument("--min-group", type=int, default=30)
    b.add_argument("--json", action="store_true")
    b.add_argument("--evidence-out", help="write a bias_test evidence item to this file, ready to paste into a record")
    b.add_argument("--collected", help="collected date for --evidence-out (default today)")
    b.set_defaults(fn=cmd_bias)
    v = sub.add_parser("verify", help="re-hash the files a record points at")
    v.add_argument("record")
    v.set_defaults(fn=cmd_verify)
    sl = sub.add_parser("seal", help="record SHA-256 digests for artifacts that have none")
    sl.add_argument("record")
    sl.add_argument("--write", action="store_true")
    sl.add_argument("--force", action="store_true", help="also replace digests that no longer match (only when the change is intended)")
    sl.set_defaults(fn=cmd_seal)
    h = sub.add_parser("history", help="check or list a scan history")
    h.add_argument("action", choices=["verify", "show"])
    h.add_argument("file")
    h.set_defaults(fn=cmd_history)
    sub.add_parser("packs", help="list the built-in packs").set_defaults(fn=cmd_packs)
    e = sub.add_parser("explain", help="show one control in full")
    e.add_argument("control")
    e.add_argument("--pack", action="append")
    e.set_defaults(fn=cmd_explain)
    ln = sub.add_parser("lint", help="check pack files")
    ln.add_argument("packs", nargs="+")
    ln.set_defaults(fn=cmd_lint)
    ct = sub.add_parser("catalog", help="the evidence the packs ask for, and the fields they read")
    ct.add_argument("--pack", action="append")
    ct.set_defaults(fn=cmd_catalog)
    mx = sub.add_parser("matrix", help="the controls as a Markdown table, generated from the packs")
    mx.add_argument("--pack", action="append")
    mx.set_defaults(fn=cmd_matrix)
    f = sub.add_parser("fingerprint", help="SHA-256 of a record in canonical form")
    f.add_argument("record")
    f.set_defaults(fn=cmd_fingerprint)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.fn(args))
    except (LexError, FairnessError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
