"""Policy packs: a catalog of controls as data, so the catalog can be reviewed, versioned, pinned and replaced.

Each control says when it applies, what must be true for it to be met, which evidence it relies on and how old that evidence may be.
Every expression is parsed and checked when the pack loads: a path to a system field that does not exist, evidence the control does not
declare, or a malformed expression is a load error, not a control that quietly never fires.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import expr
from .errors import ExprError, PackError
from .record import SYSTEM_FIELDS, canonical, loads, sha256_text

PACK_DIR = Path(__file__).resolve().parent / "packs"
SEVERITIES = ("critical", "major", "minor")
WEIGHT = {"critical": 5, "major": 3, "minor": 1}
PACK_KEYS = {"name", "title", "version", "source", "note", "controls"}
CONTROL_KEYS = {"id", "title", "reference", "applies", "requires", "evidence", "max_age_days", "severity", "remedy"}
_ID = re.compile(r"^[a-z][a-z0-9_.\-]*$")
_EVID = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class Control:
    id: str
    title: str
    reference: str
    applies: str
    requires: str
    evidence: tuple[str, ...]
    max_age_days: int
    severity: str
    remedy: str
    applies_ast: expr.Node
    requires_ast: expr.Node


@dataclass(frozen=True)
class Pack:
    name: str
    title: str
    version: str
    source: str
    note: str
    controls: tuple[Control, ...]

    @property
    def digest(self) -> str:
        body = {"name": self.name, "version": self.version,
                "controls": [{"id": c.id, "reference": c.reference, "applies": expr.render(c.applies_ast), "requires": expr.render(c.requires_ast),
                              "evidence": list(c.evidence), "max_age_days": c.max_age_days, "severity": c.severity} for c in self.controls]}
        return sha256_text(canonical(body))

    def get(self, control_id: str) -> Control:
        for c in self.controls:
            if c.id == control_id:
                return c
        raise PackError(f"no control {control_id!r} in pack {self.name}")


def _check_paths(paths: set[str], evidence: tuple[str, ...], where: str) -> None:
    for p in sorted(paths):
        parts = p.split(".")
        if parts[0] == "system":
            if len(parts) < 2 or parts[1] not in SYSTEM_FIELDS:
                raise PackError(f"{where}: {p!r} is not a system field; known: {sorted(SYSTEM_FIELDS)}")
        elif len(parts) < 2 or parts[1] not in evidence:
            raise PackError(f"{where}: {p!r} reads evidence the control does not list in 'evidence'")


def parse_pack(raw: Any) -> Pack:
    if not isinstance(raw, dict):
        raise PackError("a pack is a JSON object")
    extra = sorted(set(raw) - PACK_KEYS)
    if extra:
        raise PackError(f"unknown pack keys {extra}")
    for k in ("name", "title", "version", "source", "controls"):
        if k not in raw:
            raise PackError(f"pack.{k}: required")
    for k in ("name", "title", "version", "source", "note"):
        if k in raw and not isinstance(raw[k], str):
            raise PackError(f"pack.{k}: a string")
    if not _ID.match(raw["name"]):
        raise PackError("pack.name: lowercase letters, digits, dots, hyphens")
    if not isinstance(raw["controls"], list) or not raw["controls"]:
        raise PackError("pack.controls: a non-empty list")
    controls, seen = [], set()
    for i, c in enumerate(raw["controls"]):
        where = f"controls[{i}]"
        if not isinstance(c, dict):
            raise PackError(f"{where}: an object")
        extra = sorted(set(c) - CONTROL_KEYS)
        if extra:
            raise PackError(f"{where}: unknown keys {extra}")
        for k in ("id", "title", "reference", "applies", "requires", "evidence", "severity", "remedy"):
            if k not in c:
                raise PackError(f"{where}.{k}: required")
        cid = c["id"]
        if not isinstance(cid, str) or not _ID.match(cid) or cid in seen:
            raise PackError(f"{where}.id: unique, lowercase letters, digits, dots, hyphens")
        seen.add(cid)
        where = f"control {cid}"
        for k in ("title", "reference", "applies", "requires", "remedy"):
            if not isinstance(c[k], str) or not c[k].strip():
                raise PackError(f"{where}.{k}: a non-empty string")
        ev = c["evidence"]
        if not isinstance(ev, list) or not ev or any(not isinstance(x, str) or not _EVID.match(x) for x in ev) or len(set(ev)) != len(ev):
            raise PackError(f"{where}.evidence: a non-empty list of distinct evidence ids")
        if c["severity"] not in SEVERITIES:
            raise PackError(f"{where}.severity: one of {', '.join(SEVERITIES)}")
        age = c.get("max_age_days", 365)
        if isinstance(age, bool) or not isinstance(age, int) or age < 1:
            raise PackError(f"{where}.max_age_days: a whole number of days, one or more")
        try:
            a_ast, r_ast = expr.parse(c["applies"]), expr.parse(c["requires"])
        except ExprError as e:
            raise PackError(f"{where}: {e}") from None
        evidence = tuple(ev)
        _check_paths(expr.references(a_ast), evidence, f"{where}.applies")
        _check_paths(expr.references(r_ast), evidence, f"{where}.requires")
        for ast in (a_ast, r_ast):
            _check_calls(ast, where)
        if any(p.startswith("evidence.") for p in expr.references(a_ast)):
            raise PackError(f"{where}.applies: applicability reads the system description, not evidence")
        controls.append(Control(cid, c["title"], c["reference"], c["applies"], c["requires"], evidence, age, c["severity"], c["remedy"], a_ast, r_ast))
    return Pack(raw["name"], raw["title"], raw["version"], raw["source"], raw.get("note", ""), tuple(controls))


def _check_calls(node: expr.Node, where: str) -> None:
    if node[0] == "call" and node[1] == "age" and len(node[2].split(".")) != 2:
        raise PackError(f"{where}: age() takes an evidence item such as evidence.bias_test, not {node[2]!r}")
    for child in node[1:]:
        if isinstance(child, tuple) and child and isinstance(child[0], str):
            _check_calls(child, where)


def builtin_names() -> list[str]:
    return sorted(p.stem for p in PACK_DIR.glob("*.json"))


def load_pack(name_or_path: str) -> Pack:
    """A built-in pack by name, or a pack file by path."""
    path = PACK_DIR / f"{name_or_path}.json" if name_or_path in builtin_names() else Path(name_or_path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise PackError(f"cannot read pack {name_or_path!r}: {e.strerror or e}. Built in: {', '.join(builtin_names())}") from None
    try:
        return parse_pack(loads(text))
    except PackError:
        raise
    except ValueError as e:
        raise PackError(f"pack {name_or_path}: {e}") from None


def evidence_catalog(packs: list[Pack]) -> dict[str, dict[str, Any]]:
    """Every evidence id the packs ask for, with the controls that use it and the value fields they read. Derived, so it cannot drift."""
    cat: dict[str, dict[str, Any]] = {}
    for pack in packs:
        for c in pack.controls:
            refs = expr.references(c.requires_ast)
            for e in c.evidence:
                row = cat.setdefault(e, {"controls": [], "values": set()})
                row["controls"].append(f"{pack.name}:{c.id}")
                prefix = f"evidence.{e}.values."
                row["values"].update(p[len(prefix):] for p in refs if p.startswith(prefix))
    return {k: {"controls": v["controls"], "values": sorted(v["values"])} for k, v in sorted(cat.items())}
