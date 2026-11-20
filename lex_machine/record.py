"""Evidence records: what a system is, and the evidence collected about it, loaded strictly.

A record is one JSON file. Duplicate keys, NaN, unknown keys and wrong types are rejected, because a loose loader is how a typo turns a
failed control into a silent pass. Evidence may point at files (``artifacts``) with their SHA-256, which ``verify_artifacts`` re-checks
against the bytes on disk.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from .errors import RecordError

RISK_CLASSES = ("prohibited", "high", "limited", "minimal", "unclassified")
ROLES = ("provider", "deployer", "both")
BOOL_FIELDS = ("gpai", "systemic_risk", "personal_data", "automated_decisions", "interacts_with_people", "generates_synthetic_content", "fria_scope")
SYSTEM_FIELDS = {"name", "version", "intended_purpose", "risk_class", "role", *BOOL_FIELDS}
EVIDENCE_KEYS = {"collected", "values", "artifacts", "note"}
TOP_KEYS = {"system", "evidence", "packs", "as_of", "gates"}
GATE_KEYS = {"min_readiness", "no_critical_gaps", "no_tampered", "max_stale", "no_undetermined"}
_ID = re.compile(r"^[a-z][a-z0-9_]*$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


def parse_date(x: Any, where: str) -> _dt.date:
    if not isinstance(x, str) or not _DATE.match(x):
        raise RecordError(f"{where}: a date written YYYY-MM-DD")
    try:
        return _dt.date.fromisoformat(x)
    except ValueError as e:
        raise RecordError(f"{where}: {e}") from None


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in pairs:
        if k in out:
            raise RecordError(f"duplicate key {k!r} in the file")
        out[k] = v
    return out


def _reject_constant(name: str) -> Any:
    raise RecordError(f"{name} is not allowed in the file")


def loads(text: str) -> Any:
    try:
        return json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_reject_constant)
    except json.JSONDecodeError as e:
        raise RecordError(f"not valid JSON: {e}") from None


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fingerprint(raw: Any) -> str:
    """SHA-256 of the record in canonical form: stable across key order and whitespace."""
    return sha256_text(canonical(raw))


@dataclass(frozen=True)
class Artifact:
    path: str
    sha256: str | None = None


@dataclass(frozen=True)
class Evidence:
    id: str
    collected: _dt.date
    values: dict[str, Any]
    artifacts: tuple[Artifact, ...] = ()
    note: str = ""


@dataclass(frozen=True)
class Record:
    system: dict[str, Any]
    evidence: dict[str, Evidence]
    packs: tuple[str, ...] = ()
    as_of: _dt.date | None = None
    gates: dict[str, Any] = field(default_factory=dict)
    raw: Any = None

    def context_evidence(self) -> dict[str, dict[str, Any]]:
        return {k: {"collected": e.collected, "values": e.values, "note": e.note,
                    "artifacts": [{"path": a.path, "sha256": a.sha256} for a in e.artifacts]} for k, e in self.evidence.items()}


def _clean_json(x: Any, where: str) -> Any:
    if isinstance(x, dict):
        for k in x:
            if not isinstance(k, str):
                raise RecordError(f"{where}: keys are strings")
        return {k: _clean_json(v, f"{where}.{k}") for k, v in x.items()}
    if isinstance(x, list):
        return [_clean_json(v, f"{where}[{i}]") for i, v in enumerate(x)]
    if x is None or isinstance(x, (bool, int, str)):
        return x
    if isinstance(x, float):
        return x
    raise RecordError(f"{where}: unsupported value")


def safe_relative(path: Any, where: str) -> str:
    if not isinstance(path, str) or not path:
        raise RecordError(f"{where}: a relative file path")
    p = PurePosixPath(path)
    if p.is_absolute() or ".." in p.parts or "\\" in path:
        raise RecordError(f"{where}: {path!r} must be a relative path that stays inside the record's folder")
    return path


def parse_record(raw: Any) -> Record:
    if not isinstance(raw, dict):
        raise RecordError("the record is a JSON object")
    extra = sorted(set(raw) - TOP_KEYS)
    if extra:
        raise RecordError(f"unknown keys {extra}; allowed: {sorted(TOP_KEYS)}")
    system = _parse_system(raw.get("system"))
    ev_raw = raw.get("evidence", {})
    if not isinstance(ev_raw, dict):
        raise RecordError("evidence: an object keyed by evidence id")
    evidence = {k: _parse_evidence(k, v) for k, v in ev_raw.items()}
    packs = raw.get("packs", [])
    if not isinstance(packs, list) or any(not isinstance(p, str) or not p for p in packs) or len(set(packs)) != len(packs):
        raise RecordError("packs: a list of distinct pack names or paths")
    as_of = parse_date(raw["as_of"], "as_of") if "as_of" in raw else None
    gates = _parse_gates(raw.get("gates", {}))
    return Record(system, evidence, tuple(packs), as_of, gates, raw)


def _parse_system(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise RecordError("system: an object describing the AI system")
    extra = sorted(set(raw) - SYSTEM_FIELDS)
    if extra:
        raise RecordError(f"system: unknown fields {extra}; allowed: {sorted(SYSTEM_FIELDS)}")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise RecordError("system.name: a non-empty string")
    out: dict[str, Any] = {}
    for k, v in raw.items():
        if k in BOOL_FIELDS:
            if not isinstance(v, bool):
                raise RecordError(f"system.{k}: true or false")
        elif k == "risk_class":
            if v not in RISK_CLASSES:
                raise RecordError(f"system.risk_class: one of {', '.join(RISK_CLASSES)}")
        elif k == "role":
            if v not in ROLES:
                raise RecordError(f"system.role: one of {', '.join(ROLES)}")
        elif not isinstance(v, str):
            raise RecordError(f"system.{k}: a string")
        out[k] = v
    return out


def _parse_evidence(eid: str, raw: Any) -> Evidence:
    where = f"evidence.{eid}"
    if not _ID.match(eid):
        raise RecordError(f"{where}: ids are lowercase letters, digits and underscores, starting with a letter")
    if not isinstance(raw, dict):
        raise RecordError(f"{where}: an object")
    extra = sorted(set(raw) - EVIDENCE_KEYS)
    if extra:
        raise RecordError(f"{where}: unknown keys {extra}; allowed: {sorted(EVIDENCE_KEYS)}")
    if "collected" not in raw:
        raise RecordError(f"{where}.collected: required, a date written YYYY-MM-DD")
    collected = parse_date(raw["collected"], f"{where}.collected")
    values = raw.get("values", {})
    if not isinstance(values, dict):
        raise RecordError(f"{where}.values: an object")
    values = _clean_json(values, f"{where}.values")
    arts_raw = raw.get("artifacts", [])
    if not isinstance(arts_raw, list):
        raise RecordError(f"{where}.artifacts: a list")
    arts = []
    for i, a in enumerate(arts_raw):
        w = f"{where}.artifacts[{i}]"
        if not isinstance(a, dict) or set(a) - {"path", "sha256"}:
            raise RecordError(f"{w}: an object with path and optionally sha256")
        sha = a.get("sha256")
        if sha is not None and (not isinstance(sha, str) or not _SHA.match(sha)):
            raise RecordError(f"{w}.sha256: 64 lowercase hex characters")
        arts.append(Artifact(safe_relative(a.get("path"), f"{w}.path"), sha))
    note = raw.get("note", "")
    if not isinstance(note, str):
        raise RecordError(f"{where}.note: a string")
    return Evidence(eid, collected, values, tuple(arts), note)


def _parse_gates(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise RecordError("gates: an object")
    extra = sorted(set(raw) - GATE_KEYS)
    if extra:
        raise RecordError(f"gates: unknown gates {extra}; allowed: {sorted(GATE_KEYS)}")
    for k, v in raw.items():
        if k == "min_readiness":
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1:
                raise RecordError("gates.min_readiness: a number from 0 to 1")
        elif k == "max_stale":
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise RecordError("gates.max_stale: a whole number, zero or more")
        elif not isinstance(v, bool):
            raise RecordError(f"gates.{k}: true or false")
    return dict(raw)


def load_record(path: str | Path) -> Record:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise RecordError(f"cannot read {path}: {e.strerror or e}") from None
    return parse_record(loads(text))


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_artifacts(record: Record, base: Path) -> dict[str, list[tuple[str, str]]]:
    """For each evidence id: a list of (state, path), state being ok, unsealed, mismatch or absent.

    ``mismatch`` means the file on disk is not the file the digest was taken from. ``unsealed`` means no digest was recorded, so the
    file's content is not pinned (it is reported, never counted as verified)."""
    base = base.resolve()
    out: dict[str, list[tuple[str, str]]] = {}
    for eid, ev in record.evidence.items():
        rows = []
        for a in ev.artifacts:
            target = (base / a.path).resolve()
            if base not in target.parents and target != base:
                raise RecordError(f"evidence.{eid}: {a.path!r} escapes the record's folder")
            if not target.is_file():
                rows.append(("absent", a.path))
            elif a.sha256 is None:
                rows.append(("unsealed", a.path))
            else:
                rows.append(("ok" if file_sha256(target) == a.sha256 else "mismatch", a.path))
        if rows:
            out[eid] = rows
    return out
