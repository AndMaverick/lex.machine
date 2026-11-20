"""A small, safe expression language for controls, with three-valued logic.

A control says when it applies and what must be true for it to be met, for example::

    system.risk_class == "high" and evidence.bias_test.values.overall == "pass" and age(evidence.bias_test) <= 365

Nothing is executed with ``eval``. The text is parsed into a tree and walked. A value that is not in the record is *unknown*, not false:
``unknown and false`` is false, ``unknown or true`` is true, and everything else involving an unknown is unknown, so a missing piece of
evidence can never make a control look met, and a control that is already decided is not blocked by an unrelated gap.
Comparing a string with a number, or using a non-boolean as a condition, is an error rather than a quiet false.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from typing import Any

from .errors import ExprError

KEYWORDS = {"and", "or", "not", "in", "true", "false"}
FUNCTIONS = {"present", "age", "count"}
ROOTS = {"system", "evidence"}
_TOKEN = re.compile(
    r"""\s*(?:
    (?P<num>\d+(?:\.\d+)?)
  | (?P<str>"(?:[^"\\]|\\.)*")
  | (?P<op><=|>=|==|!=|<|>|\(|\)|\[|\]|,)
  | (?P<name>[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*)
  | (?P<minus>-)
    )""",
    re.VERBOSE,
)

Node = tuple[Any, ...]


def tokenize(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    pos = 0
    text = text.rstrip()
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise ExprError(f"unexpected character {text[pos:].lstrip()[:1]!r} at position {pos}")
        pos = m.end()
        kind = m.lastgroup or ""
        out.append((kind, m.group(kind)))
    return out


class _Parser:
    def __init__(self, text: str):
        self.toks = tokenize(text)
        self.i = 0

    def peek(self) -> tuple[str, str] | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def take(self) -> tuple[str, str]:
        t = self.peek()
        if t is None:
            raise ExprError("the expression ends too soon")
        self.i += 1
        return t

    def accept(self, value: str) -> bool:
        t = self.peek()
        if t is not None and t[1] == value and t[0] in {"op", "name"}:
            self.i += 1
            return True
        return False

    def expect(self, value: str) -> None:
        if not self.accept(value):
            got = self.peek()
            raise ExprError(f"expected {value!r}, found {got[1]!r}" if got else f"expected {value!r} at the end")

    def parse(self) -> Node:
        if not self.toks:
            raise ExprError("empty expression")
        node = self.or_expr()
        if self.peek() is not None:
            raise ExprError(f"unexpected {self.peek()[1]!r}")  # type: ignore[index]
        return node

    def or_expr(self) -> Node:
        node = self.and_expr()
        while self.accept("or"):
            node = ("or", node, self.and_expr())
        return node

    def and_expr(self) -> Node:
        node = self.not_expr()
        while self.accept("and"):
            node = ("and", node, self.not_expr())
        return node

    def not_expr(self) -> Node:
        if self.accept("not"):
            return ("not", self.not_expr())
        return self.comparison()

    def comparison(self) -> Node:
        left = self.atom()
        t = self.peek()
        if t and t[0] == "op" and t[1] in {"==", "!=", "<", "<=", ">", ">="}:
            self.i += 1
            return ("cmp", t[1], left, self.atom())
        if self.accept("in"):
            self.expect("[")
            items: list[Any] = []
            while True:
                lit = self.atom()
                if lit[0] != "lit":
                    raise ExprError("a list after 'in' holds only literals")
                items.append(lit[1])
                if self.accept("]"):
                    break
                self.expect(",")
            return ("in", left, tuple(items))
        return left

    def atom(self) -> Node:
        kind, val = self.take()
        if kind == "num":
            return ("lit", float(val) if "." in val else int(val))
        if kind == "minus":
            k2, v2 = self.take()
            if k2 != "num":
                raise ExprError("a minus sign must be followed by a number")
            return ("lit", -(float(v2) if "." in v2 else int(v2)))
        if kind == "str":
            return ("lit", _unquote(val))
        if kind == "op" and val == "(":
            node = self.or_expr()
            self.expect(")")
            return node
        if kind == "name":
            if val == "true":
                return ("lit", True)
            if val == "false":
                return ("lit", False)
            if val in KEYWORDS:
                raise ExprError(f"unexpected keyword {val!r}")
            if val in FUNCTIONS:
                self.expect("(")
                arg = self.take()
                if arg[0] != "name" or arg[1] in KEYWORDS or arg[1] in FUNCTIONS:
                    raise ExprError(f"{val}() takes a path such as evidence.risk_management")
                self.expect(")")
                return ("call", val, arg[1])
            root = val.split(".", 1)[0]
            if root not in ROOTS or "." not in val:
                raise ExprError(f"{val!r}: a path is system.<field> or evidence.<id>...")
            return ("path", val)
        raise ExprError(f"unexpected {val!r}")


def _unquote(s: str) -> str:
    body = s[1:-1]
    out, i = [], 0
    while i < len(body):
        ch = body[i]
        if ch == "\\":
            i += 1
            nxt = body[i]
            if nxt not in {'"', "\\"}:
                raise ExprError(f"unsupported escape \\{nxt} in a string")
            out.append(nxt)
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def parse(text: str) -> Node:
    if not isinstance(text, str):
        raise ExprError("an expression is a string")
    return _Parser(text).parse()


def references(node: Node) -> set[str]:
    """Every path the expression reads (including the argument of present, age and count)."""
    kind = node[0]
    if kind == "path":
        return {node[1]}
    if kind == "call":
        return {node[2]}
    if kind in {"and", "or"}:
        return references(node[1]) | references(node[2])
    if kind == "not":
        return references(node[1])
    if kind == "cmp":
        return references(node[2]) | references(node[3])
    if kind == "in":
        return references(node[1])
    return set()


@dataclass
class Context:
    system: dict[str, Any]
    evidence: dict[str, dict[str, Any]]
    as_of: _dt.date
    missing: set[str] = field(default_factory=set)

    def lookup(self, path: str, *, note: bool = True) -> Any:
        node: Any = {"system": self.system, "evidence": self.evidence}
        for part in path.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                if note:
                    self.missing.add(path)
                return None
        return node


def _kind(v: Any) -> str:
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    return type(v).__name__


def _as_bool(v: Any, what: str) -> bool | None:
    if v is None or isinstance(v, bool):
        return v
    raise ExprError(f"{what} is a {_kind(v)} but a true or false value is needed here")


def evaluate(node: Node, ctx: Context) -> Any:
    """Value of the expression: a bool, number or string, or None for unknown."""
    kind = node[0]
    if kind == "lit":
        return node[1]
    if kind == "path":
        return ctx.lookup(node[1])
    if kind == "call":
        return _call(node[1], node[2], ctx)
    if kind == "not":
        v = _as_bool(evaluate(node[1], ctx), "the operand of 'not'")
        return None if v is None else not v
    if kind in {"and", "or"}:
        a = _as_bool(evaluate(node[1], ctx), f"an operand of '{kind}'")
        b = _as_bool(evaluate(node[2], ctx), f"an operand of '{kind}'")
        decisive = kind == "or"
        if a is decisive or b is decisive:
            return decisive
        return None if a is None or b is None else (not decisive)
    if kind == "in":
        v = evaluate(node[1], ctx)
        if v is None:
            return None
        items = node[2]
        for it in items:
            if _kind(it) != _kind(v):
                raise ExprError(f"cannot test a {_kind(v)} against a list that holds a {_kind(it)}")
        return v in items
    if kind == "cmp":
        a, b = evaluate(node[2], ctx), evaluate(node[3], ctx)
        if a is None or b is None:
            return None
        if _kind(a) != _kind(b):
            raise ExprError(f"cannot compare a {_kind(a)} with a {_kind(b)}")
        op = node[1]
        if op in {"==", "!="}:
            return (a == b) if op == "==" else (a != b)
        if _kind(a) == "boolean":
            raise ExprError(f"cannot order booleans with {op}")
        return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
    raise ExprError(f"unknown node {kind!r}")


def _call(name: str, path: str, ctx: Context) -> Any:
    v = ctx.lookup(path, note=False)
    if name == "present":
        return v is not None
    if name == "count":
        if v is None:
            ctx.missing.add(path)
            return None
        if not isinstance(v, (list, dict)):
            raise ExprError(f"count({path}) needs a list, found a {_kind(v)}")
        return len(v)
    # age
    if v is None:
        ctx.missing.add(path)
        return None
    collected = v.get("collected") if isinstance(v, dict) else None
    if not isinstance(collected, _dt.date):
        raise ExprError(f"age({path}) needs an evidence item with a collected date")
    return (ctx.as_of - collected).days


def truth(node: Node, ctx: Context) -> bool | None:
    """Evaluate as a condition: True, False or None (unknown)."""
    return _as_bool(evaluate(node, ctx), "the whole expression")


def render(node: Node) -> str:
    """The expression written back out in a canonical form (used to fingerprint a pack)."""
    kind = node[0]
    if kind == "lit":
        return _render_literal(node[1])
    if kind == "path":
        return str(node[1])
    if kind == "call":
        return f"{node[1]}({node[2]})"
    if kind == "not":
        return f"not ({render(node[1])})"
    if kind in {"and", "or"}:
        return f"({render(node[1])} {kind} {render(node[2])})"
    if kind == "cmp":
        return f"{render(node[2])} {node[1]} {render(node[3])}"
    if kind == "in":
        return f"{render(node[1])} in [{', '.join(_render_literal(x) for x in node[2])}]"
    raise ExprError(f"unknown node {kind!r}")


def _render_literal(v: Any) -> str:
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return repr(v)
