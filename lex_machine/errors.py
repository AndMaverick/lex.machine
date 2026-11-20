"""One error family, so the command line can tell bad input (exit 2) from a failed gate (exit 1)."""
from __future__ import annotations


class LexError(ValueError):
    """Base class for every input problem lex.machine reports."""


class ExprError(LexError):
    """A control expression that does not parse, refers to something unknown, or compares things that cannot be compared."""


class RecordError(LexError):
    """An evidence record that is malformed."""


class PackError(LexError):
    """A policy pack that is malformed."""


class HistoryError(LexError):
    """A scan history file that is malformed or has been altered."""
