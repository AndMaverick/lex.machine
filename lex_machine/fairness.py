"""Fairness verdicts that say what the sample can and cannot show.

A gap in outcome rates between two groups is a point estimate from a finite sample. Reporting it against a threshold as if it were exact
produces both false alarms (small groups, noisy gap) and false comfort (a gap that is small only because there is little data). Here every
comparison carries a confidence interval and ends in one of three verdicts:

- ``fail``          the interval lies wholly beyond the allowed gap: the data show the gap is too large
- ``pass``          the interval lies wholly inside the allowed gap: the data show it is small enough
- ``inconclusive``  the interval straddles the limit, or a group is too small to decide: the data cannot say

Gaps use Newcombe's hybrid-score interval (Wilson intervals for each rate, combined). Ratios for the four-fifths rule use the Katz log
interval. With several groups every pair is compared and the error rate is divided across the pairs (Bonferroni), so looking at many
pairs does not manufacture a failure. A group smaller than ``min_group`` is never used to pass or fail anything.
"""
from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations
from statistics import NormalDist
from typing import Any

from .errors import LexError

EXACT_LIMIT = 2000       # exact Fisher test up to this many rows in a pair; a normal approximation beyond
TRUE = {"1", "true", "yes", "y", "t"}
FALSE = {"0", "false", "no", "n", "f"}


class FairnessError(LexError):
    """Predictions that cannot be audited as given."""


def z_for(alpha: float) -> float:
    if not 0 < alpha < 1:
        raise FairnessError("alpha must be between 0 and 1")
    return NormalDist().inv_cdf(1 - alpha / 2)


def wilson(k: int, n: int, z: float) -> tuple[float, float]:
    """Wilson score interval for a proportion k/n."""
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    z2 = z * z
    centre = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def newcombe(k1: int, n1: int, k2: int, n2: int, z: float) -> tuple[float, float, float]:
    """Difference p1 - p2 with Newcombe's hybrid-score interval (method 10)."""
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = wilson(k1, n1, z)
    l2, u2 = wilson(k2, n2, z)
    d = p1 - p2
    lo = d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    hi = d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return d, max(-1.0, lo), min(1.0, hi)


def katz(k1: int, n1: int, k2: int, n2: int, z: float) -> tuple[float, float, float]:
    """Ratio p1 / p2 with the Katz log interval. A zero count adds one half to each cell for the interval only."""
    if k2 == 0 and k1 == 0:
        return math.nan, math.nan, math.nan
    ratio = math.inf if k2 == 0 else (k1 / n1) / (k2 / n2)
    a, b = (k1, k2) if k1 and k2 else (k1 + 0.5, k2 + 0.5)
    m, n = (n1, n2) if k1 and k2 else (n1 + 0.5, n2 + 0.5)
    se = math.sqrt((1 - a / m) / a + (1 - b / n) / b) if a and b else math.inf
    centre = math.log((a / m) / (b / n))
    return ratio, math.exp(centre - z * se), math.exp(centre + z * se)


def fisher_exact(k1: int, n1: int, k2: int, n2: int) -> float:
    """Two-sided exact p-value for equal proportions (sum of tables no more likely than the observed one), compared in exact integers."""
    big_k, total, draw = k1 + k2, n1 + n2, n1
    lo, hi = max(0, draw - (total - big_k)), min(draw, big_k)
    weights = {x: math.comb(big_k, x) * math.comb(total - big_k, draw - x) for x in range(lo, hi + 1)}
    cut = weights[k1]
    return float(Fraction(sum(w for w in weights.values() if w <= cut), math.comb(total, draw)))


def two_proportion_p(k1: int, n1: int, k2: int, n2: int) -> float:
    pooled = (k1 + k2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    return 2 * (1 - NormalDist().cdf(abs((k1 / n1 - k2 / n2) / se)))


def p_value(k1: int, n1: int, k2: int, n2: int) -> tuple[float, str]:
    if n1 + n2 <= EXACT_LIMIT:
        return fisher_exact(k1, n1, k2, n2), "Fisher exact"
    return two_proportion_p(k1, n1, k2, n2), "normal approximation"


@dataclass(frozen=True)
class Row:
    group: str
    pred: bool
    label: bool | None = None


def _flag(x: str, where: str) -> bool:
    v = x.strip().lower()
    if v in TRUE:
        return True
    if v in FALSE:
        return False
    raise FairnessError(f"{where}: {x!r} is not a yes/no value (use 1/0, true/false or yes/no)")


def read_rows(text: str, group: str, pred: str, label: str | None = None) -> list[Row]:
    """Rows from CSV text. Blank cells, a missing column or a value that is not yes/no is an error, not a skipped row."""
    reader = csv.DictReader(io.StringIO(text))
    cols = reader.fieldnames or []
    for c in (group, pred, *([label] if label else [])):
        if c not in cols:
            raise FairnessError(f"column {c!r} is not in the file; columns are {', '.join(cols) or '(none)'}")
    rows = []
    for i, rec in enumerate(reader, start=2):
        g = (rec.get(group) or "").strip()
        if not g:
            raise FairnessError(f"line {i}: the {group!r} cell is empty")
        rows.append(Row(g, _flag(rec.get(pred) or "", f"line {i} {pred}"), _flag(rec.get(label) or "", f"line {i} {label}") if label else None))
    if not rows:
        raise FairnessError("the file has no rows")
    return rows


@dataclass(frozen=True)
class Group:
    name: str
    n: int
    selected: int
    positives: int | None
    true_pos: int | None
    negatives: int | None
    false_pos: int | None

    def cells(self, metric: str) -> tuple[int, int] | None:
        """(successes, trials) for a metric, or None where it is not defined for this group."""
        if metric == "selection_rate":
            return self.selected, self.n
        if self.positives is None:
            return None
        if metric == "tpr":
            return (self.true_pos or 0, self.positives) if self.positives else None
        return (self.false_pos or 0, self.negatives or 0) if self.negatives else None


def summarize(rows: list[Row]) -> list[Group]:
    names = sorted({r.group for r in rows})
    labelled = all(r.label is not None for r in rows)
    out = []
    for g in names:
        rs = [r for r in rows if r.group == g]
        if labelled:
            pos = [r for r in rs if r.label]
            neg = [r for r in rs if not r.label]
            out.append(Group(g, len(rs), sum(r.pred for r in rs), len(pos), sum(r.pred for r in pos), len(neg), sum(r.pred for r in neg)))
        else:
            out.append(Group(g, len(rs), sum(r.pred for r in rs), None, None, None, None))
    return out


@dataclass(frozen=True)
class Pair:
    a: str
    b: str
    estimate: float
    low: float
    high: float
    verdict: str
    p_value: float | None
    p_method: str


@dataclass(frozen=True)
class MetricVerdict:
    name: str
    verdict: str
    worst: Pair | None
    note: str = ""


def _verdict_gap(lo: float, hi: float, limit: float) -> str:
    if lo > limit or hi < -limit:
        return "fail"
    if lo > -limit and hi < limit:
        return "pass"
    return "inconclusive"


def _combine(verdicts: list[str]) -> str:
    if "fail" in verdicts:
        return "fail"
    return "pass" if verdicts and all(v == "pass" for v in verdicts) else "inconclusive"


def gap_metric(groups: list[Group], metric: str, *, max_gap: float, alpha: float, min_group: int) -> MetricVerdict:
    usable = [(g, c) for g in groups if (c := g.cells(metric)) is not None]
    if len(usable) < 2:
        return MetricVerdict(f"{metric}_gap", "inconclusive", None, "fewer than two groups have data for this metric")
    pairs = list(combinations(usable, 2))
    z = z_for(alpha / len(pairs))
    results = []
    for (ga, (ka, na)), (gb, (kb, nb)) in pairs:
        d, lo, hi = newcombe(ka, na, kb, nb, z)
        v = _verdict_gap(lo, hi, max_gap)
        if min(na, nb) < min_group:
            v = "inconclusive"
        p, method = p_value(ka, na, kb, nb)
        results.append(Pair(ga.name, gb.name, d, lo, hi, v, p, method))
    worst = max(results, key=lambda r: (abs(r.estimate), r.a, r.b))
    return MetricVerdict(f"{metric}_gap", _combine([r.verdict for r in results]), worst)


def four_fifths(groups: list[Group], *, min_ratio: float, alpha: float, min_group: int) -> MetricVerdict:
    usable = [(g, g.cells("selection_rate")) for g in groups]
    pairs = list(combinations(usable, 2))
    if not pairs:
        return MetricVerdict("four_fifths", "inconclusive", None, "fewer than two groups")
    z = z_for(alpha / len(pairs))
    results = []
    for (ga, ca), (gb, cb) in pairs:
        assert ca is not None and cb is not None
        low, high = ((ga, ca), (gb, cb)) if ca[0] / ca[1] <= cb[0] / cb[1] else ((gb, cb), (ga, ca))
        if high[1][0] == 0:
            results.append(Pair(low[0].name, high[0].name, math.nan, math.nan, math.nan, "inconclusive", None, ""))
            continue
        ratio, lo, hi = katz(low[1][0], low[1][1], high[1][0], high[1][1], z)
        v = "fail" if hi < min_ratio else "pass" if lo >= min_ratio else "inconclusive"
        if min(low[1][1], high[1][1]) < min_group:
            v = "inconclusive"
        results.append(Pair(low[0].name, high[0].name, ratio, lo, hi, v, None, ""))
    finite = [r for r in results if not math.isnan(r.estimate)]
    worst = min(finite, key=lambda r: (r.estimate, r.a, r.b)) if finite else None
    return MetricVerdict("four_fifths", _combine([r.verdict for r in results]), worst)


@dataclass(frozen=True)
class FairnessReport:
    rows: int
    groups: tuple[Group, ...]
    metrics: tuple[MetricVerdict, ...]
    overall: str
    max_gap: float
    min_ratio: float
    alpha: float
    min_group: int

    def values(self) -> dict[str, Any]:
        """The result as the ``values`` of a ``bias_test`` evidence item."""
        def r(x: float) -> float | None:
            return None if math.isnan(x) or math.isinf(x) else round(x, 6)

        out: dict[str, Any] = {
            "overall": self.overall, "rows": self.rows, "groups": len(self.groups), "smallest_group": min(g.n for g in self.groups),
            "alpha": self.alpha, "max_gap": self.max_gap, "min_ratio": self.min_ratio, "min_group": self.min_group,
            "metrics": {m.name: {"verdict": m.verdict, **({"worst_estimate": r(m.worst.estimate), "worst_low": r(m.worst.low), "worst_high": r(m.worst.high),
                                                          "worst_pair": [m.worst.a, m.worst.b]} if m.worst else {})} for m in self.metrics},
        }
        out["group_rates"] = {g.name: {"n": g.n, **{k: round(c[0] / c[1], 6) for k in ("selection_rate", "tpr", "fpr")
                                                    if (c := g.cells(k)) is not None}} for g in self.groups}
        return out


def audit(rows: list[Row], *, max_gap: float = 0.1, min_ratio: float = 0.8, alpha: float = 0.05, min_group: int = 30) -> FairnessReport:
    if max_gap <= 0 or max_gap >= 1:
        raise FairnessError("max_gap must be between 0 and 1")
    if not 0 < min_ratio < 1:
        raise FairnessError("min_ratio must be between 0 and 1")
    if min_group < 1:
        raise FairnessError("min_group must be at least 1")
    groups = summarize(rows)
    if len(groups) < 2:
        raise FairnessError("a comparison needs at least two groups")
    metrics = [gap_metric(groups, "selection_rate", max_gap=max_gap, alpha=alpha, min_group=min_group),
               four_fifths(groups, min_ratio=min_ratio, alpha=alpha, min_group=min_group)]
    if groups[0].positives is not None:
        metrics += [gap_metric(groups, "tpr", max_gap=max_gap, alpha=alpha, min_group=min_group),
                    gap_metric(groups, "fpr", max_gap=max_gap, alpha=alpha, min_group=min_group)]
    overall = _combine([m.verdict for m in metrics])
    return FairnessReport(len(rows), tuple(groups), tuple(metrics), overall, max_gap, min_ratio, alpha, min_group)


def synthetic_predictions(spec: list[dict[str, Any]], seed: int = 0) -> list[Row]:
    """Reproducible rows. Each group: {name, n, prevalence, tpr, fpr}."""
    import random
    rng = random.Random(seed)
    rows = []
    for g in spec:
        for _ in range(g["n"]):
            label = rng.random() < g["prevalence"]
            pred = rng.random() < (g["tpr"] if label else g["fpr"])
            rows.append(Row(g["name"], pred, label))
    return rows


def to_csv(rows: list[Row], group: str = "group", pred: str = "pred", label: str = "label") -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow([group, label, pred])
    for r in rows:
        w.writerow([r.group, int(bool(r.label)), int(r.pred)])
    return out.getvalue()
