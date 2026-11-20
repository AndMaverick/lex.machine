"""A scan history that shows when it has been edited.

Each line of the history file holds one attestation and the hash of the line before it, so changing, removing, inserting or reordering
any earlier line breaks every hash after it. The head is the hash of the whole history: publish it somewhere the writer cannot edit.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import HistoryError
from .record import canonical, sha256_text

GENESIS = "0" * 64


def entry_hash(prev: str, attestation: dict[str, Any]) -> str:
    return sha256_text(f"{prev}\n{canonical(attestation)}")


def read(path: Path) -> list[dict[str, Any]]:
    """The entries, each checked against its predecessor. Raises HistoryError naming the first line that does not fit."""
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    prev = GENESIS
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            raise HistoryError(f"line {i}: not valid JSON") from None
        if not isinstance(e, dict) or set(e) != {"seq", "prev", "attestation", "hash"} or not isinstance(e["attestation"], dict):
            raise HistoryError(f"line {i}: not a history entry")
        if e["seq"] != i or e["prev"] != prev:
            raise HistoryError(f"line {i}: does not follow line {i - 1}; the history has been changed, reordered or cut")
        if e["hash"] != entry_hash(prev, e["attestation"]):
            raise HistoryError(f"line {i}: the content does not match its hash; this line has been changed")
        prev = e["hash"]
        out.append(e)
    return out


def head(entries: list[dict[str, Any]]) -> str:
    return entries[-1]["hash"] if entries else GENESIS


def append(path: Path, attestation: dict[str, Any]) -> dict[str, Any]:
    """Add an attestation after checking the whole existing chain."""
    entries = read(path)
    prev = head(entries)
    e = {"seq": len(entries) + 1, "prev": prev, "attestation": attestation, "hash": entry_hash(prev, attestation)}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(e, sort_keys=True, separators=(",", ":")) + "\n")
    return e
