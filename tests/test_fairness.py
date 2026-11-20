import json
import math
import random
import unittest

from lex_machine import fairness as fx
from lex_machine.fairness import FairnessError, Row
from tests import oracles


def rows_for(spec, seed=0):
    return fx.synthetic_predictions(spec, seed)


def g(name, n, tpr, fpr, prevalence=0.3):
    return {"name": name, "n": n, "prevalence": prevalence, "tpr": tpr, "fpr": fpr}


class TestIntervals(unittest.TestCase):
    def test_wilson_matches_its_definition(self):
        rng = random.Random(1)
        for _ in range(200):
            n = rng.randint(1, 400)
            k = rng.randint(0, n)
            z = rng.choice([1.2816, 1.6449, 1.96, 2.5758])
            lo, hi = fx.wilson(k, n, z)
            olo, ohi = oracles.wilson_bounds(k, n, z)
            self.assertAlmostEqual(lo, olo, places=9, msg=(k, n, z))
            self.assertAlmostEqual(hi, ohi, places=9, msg=(k, n, z))

    def test_wilson_published_value(self):
        lo, hi = fx.wilson(7, 20, 1.96)
        self.assertAlmostEqual(lo, 0.181, places=3)
        self.assertAlmostEqual(hi, 0.567, places=3)

    def test_wilson_edges(self):
        self.assertEqual(fx.wilson(0, 0, 1.96), (0.0, 1.0))
        self.assertEqual(fx.wilson(0, 50, 1.96)[0], 0.0)
        self.assertEqual(fx.wilson(50, 50, 1.96)[1], 1.0)
        for k in (0, 1, 49, 50):
            lo, hi = fx.wilson(k, 50, 1.96)
            self.assertTrue(0 <= lo <= k / 50 <= hi <= 1)

    def test_newcombe_matches_the_published_example(self):
        d, lo, hi = fx.newcombe(56, 70, 48, 80, 1.959964)           # Newcombe (1998), method 10
        self.assertAlmostEqual(d, 0.2, places=4)
        self.assertAlmostEqual(lo, 0.0524, places=4)
        self.assertAlmostEqual(hi, 0.3339, places=4)

    def test_newcombe_properties(self):
        rng = random.Random(2)
        for _ in range(300):
            n1, n2 = rng.randint(5, 300), rng.randint(5, 300)
            k1, k2 = rng.randint(0, n1), rng.randint(0, n2)
            d, lo, hi = fx.newcombe(k1, n1, k2, n2, 1.96)
            self.assertLessEqual(lo, d + 1e-12)
            self.assertGreaterEqual(hi, d - 1e-12)
            self.assertTrue(lo >= -1 and hi <= 1)
            d2, lo2, hi2 = fx.newcombe(k2, n2, k1, n1, 1.96)           # swapping the groups mirrors the interval
            self.assertAlmostEqual(d2, -d)
            self.assertAlmostEqual(lo2, -hi, places=12)
            self.assertAlmostEqual(hi2, -lo, places=12)

    def test_more_data_gives_a_narrower_interval(self):
        widths = [fx.newcombe(n // 2, n, n * 3 // 10, n, 1.96)[2] - fx.newcombe(n // 2, n, n * 3 // 10, n, 1.96)[1] for n in (50, 200, 800, 3200)]
        self.assertEqual(widths, sorted(widths, reverse=True))

    def test_katz_by_hand(self):
        ratio, lo, hi = fx.katz(20, 100, 40, 100, 1.959964)
        se = math.sqrt(0.8 / 20 + 0.6 / 40)
        self.assertAlmostEqual(ratio, 0.5)
        self.assertAlmostEqual(lo, math.exp(math.log(0.5) - 1.959964 * se), places=9)
        self.assertAlmostEqual(hi, math.exp(math.log(0.5) + 1.959964 * se), places=9)

    def test_katz_zero_cells(self):
        ratio, lo, hi = fx.katz(0, 50, 20, 50, 1.96)
        self.assertEqual(ratio, 0.0)
        self.assertTrue(0 < lo < hi < 1)
        self.assertTrue(math.isnan(fx.katz(0, 50, 0, 50, 1.96)[0]))

    def test_z_values(self):
        self.assertAlmostEqual(fx.z_for(0.05), 1.959964, places=5)
        self.assertAlmostEqual(fx.z_for(0.01), 2.575829, places=5)
        for bad in (0, 1, -0.1, 2):
            with self.assertRaises(FairnessError):
                fx.z_for(bad)


class TestFisher(unittest.TestCase):
    def test_known_value(self):
        self.assertAlmostEqual(fx.fisher_exact(3, 10, 7, 10), 0.1789, places=4)

    def test_matches_enumeration_on_every_small_table(self):
        count = 0
        for n1 in range(1, 7):
            for n2 in range(1, 7):
                for k1 in range(n1 + 1):
                    for k2 in range(n2 + 1):
                        want = float(oracles.fisher_by_enumeration(k1, n1, k2, n2))
                        self.assertAlmostEqual(fx.fisher_exact(k1, n1, k2, n2), want, places=12, msg=(k1, n1, k2, n2))
                        count += 1
        self.assertEqual(count, sum((a + 1) * (b + 1) for a in range(1, 7) for b in range(1, 7)))

    def test_symmetric_and_bounded(self):
        rng = random.Random(3)
        for _ in range(100):
            n1, n2 = rng.randint(1, 60), rng.randint(1, 60)
            k1, k2 = rng.randint(0, n1), rng.randint(0, n2)
            p = fx.fisher_exact(k1, n1, k2, n2)
            self.assertTrue(0 < p <= 1 + 1e-12)
            self.assertAlmostEqual(p, fx.fisher_exact(k2, n2, k1, n1), places=12)
            self.assertAlmostEqual(p, fx.fisher_exact(n1 - k1, n1, n2 - k2, n2), places=12)     # relabelling success and failure

    def test_equal_proportions_give_p_one(self):
        self.assertAlmostEqual(fx.fisher_exact(5, 10, 5, 10), 1.0)

    def test_large_samples_switch_to_the_normal_approximation_and_say_so(self):
        self.assertEqual(fx.p_value(3, 10, 7, 10)[1], "Fisher exact")
        p, method = fx.p_value(900, 1500, 800, 1500)
        self.assertEqual(method, "normal approximation")
        pooled = 1700 / 3000
        z = (900 / 1500 - 800 / 1500) / math.sqrt(pooled * (1 - pooled) * 2 / 1500)
        self.assertAlmostEqual(p, math.erfc(z / math.sqrt(2)), places=10)           # the two-sided normal tail, written another way


class TestVerdicts(unittest.TestCase):
    def test_clear_fairness_passes(self):
        rep = fx.audit(rows_for([g("a", 3000, 0.8, 0.1), g("b", 3000, 0.8, 0.1)], 1))
        self.assertEqual(rep.overall, "pass")
        self.assertEqual({m.name: m.verdict for m in rep.metrics}, {"selection_rate_gap": "pass", "four_fifths": "pass", "tpr_gap": "pass", "fpr_gap": "pass"})

    def test_a_large_clear_gap_fails(self):
        rep = fx.audit(rows_for([g("a", 2000, 0.85, 0.1), g("b", 2000, 0.45, 0.1)], 1))
        self.assertEqual(rep.overall, "fail")
        tpr = next(m for m in rep.metrics if m.name == "tpr_gap")
        self.assertEqual(tpr.verdict, "fail")
        assert tpr.worst is not None
        self.assertGreater(tpr.worst.low, 0.1)

    def test_a_small_sample_is_inconclusive_not_a_pass(self):
        rep = fx.audit(rows_for([g("a", 60, 0.8, 0.1), g("b", 60, 0.8, 0.1)], 1))
        self.assertEqual(rep.overall, "inconclusive")

    def test_an_apparent_gap_in_a_small_sample_is_inconclusive_not_a_fail(self):
        rep = fx.audit(rows_for([g("a", 40, 0.8, 0.2), g("b", 40, 0.6, 0.2)], 3), min_group=30)
        self.assertNotEqual(next(m for m in rep.metrics if m.name == "tpr_gap").verdict, "fail")

    def test_a_tiny_group_never_decides(self):
        big = [g("a", 3000, 0.8, 0.1), g("b", 3000, 0.8, 0.1)]
        rep = fx.audit(rows_for(big + [g("tiny", 12, 0.1, 0.9)], 1))
        self.assertEqual(rep.overall, "inconclusive")                      # the tiny group's pairs cannot pass, and cannot fail either
        self.assertNotIn("fail", [m.verdict for m in rep.metrics])

    def test_pairs_are_all_compared_and_the_error_rate_is_shared(self):
        rows = rows_for([g("a", 800, 0.8, 0.1), g("b", 800, 0.7, 0.1), g("c", 800, 0.8, 0.1)], 5)
        groups = {x.name: x for x in fx.summarize(rows)}
        rep = fx.audit(rows)
        worst = next(m for m in rep.metrics if m.name == "selection_rate_gap").worst
        assert worst is not None
        ka, na = groups[worst.a].cells("selection_rate")
        kb, nb = groups[worst.b].cells("selection_rate")
        _, lo3, hi3 = fx.newcombe(ka, na, kb, nb, fx.z_for(0.05 / 3))          # three pairs: the error rate is divided by three
        _, lo1, hi1 = fx.newcombe(ka, na, kb, nb, fx.z_for(0.05))
        self.assertAlmostEqual(worst.low, lo3)
        self.assertAlmostEqual(worst.high, hi3)
        self.assertGreater(hi3 - lo3, hi1 - lo1)

    def test_four_fifths_rule(self):
        # selection rates about 0.30 and 0.45: ratio about 0.67, below the 0.8 line
        rep = fx.audit(rows_for([g("a", 4000, 0.8, 0.1), g("b", 4000, 0.4, 0.1)], 7))
        ff = next(m for m in rep.metrics if m.name == "four_fifths")
        self.assertEqual(ff.verdict, "fail")
        assert ff.worst is not None
        self.assertLess(ff.worst.high, 0.8)

    def test_without_labels_only_selection_metrics_are_judged(self):
        rows = [Row(r.group, r.pred) for r in rows_for([g("a", 3000, 0.8, 0.1), g("b", 3000, 0.8, 0.1)], 1)]
        rep = fx.audit(rows)
        self.assertEqual([m.name for m in rep.metrics], ["selection_rate_gap", "four_fifths"])
        self.assertEqual(rep.overall, "pass")

    def test_a_group_with_no_actual_positives_cannot_be_compared_on_tpr(self):
        rows = [Row("a", True, True)] * 40 + [Row("a", False, False)] * 40 + [Row("b", False, False)] * 80
        rep = fx.audit(rows)
        tpr = next(m for m in rep.metrics if m.name == "tpr_gap")
        self.assertEqual(tpr.verdict, "inconclusive")
        self.assertIn("fewer than two", tpr.note)

    def test_arguments_are_checked(self):
        rows = rows_for([g("a", 50, 0.5, 0.5), g("b", 50, 0.5, 0.5)])
        for kw in ({"max_gap": 0}, {"max_gap": 1}, {"min_ratio": 1}, {"min_group": 0}, {"alpha": 0}):
            with self.subTest(kw), self.assertRaises(FairnessError):
                fx.audit(rows, **kw)
        with self.assertRaises(FairnessError):
            fx.audit([Row("a", True)] * 10)

    def test_values_are_json_safe_and_deterministic(self):
        rep = fx.audit(rows_for([g("a", 500, 0.8, 0.1), g("b", 500, 0.5, 0.1)], 9))
        text = json.dumps(rep.values(), sort_keys=True, allow_nan=False)
        again = json.dumps(fx.audit(rows_for([g("a", 500, 0.8, 0.1), g("b", 500, 0.5, 0.1)], 9)).values(), sort_keys=True, allow_nan=False)
        self.assertEqual(text, again)
        v = rep.values()
        self.assertEqual(v["overall"], rep.overall)
        self.assertEqual(v["groups"], 2)
        self.assertIn("group_rates", v)


class TestReading(unittest.TestCase):
    CSV = "group,label,pred\nx,1,1\nx,0,0\ny,1,0\ny,0,0\n"

    def test_reads_rows(self):
        rows = fx.read_rows(self.CSV, "group", "pred", "label")
        self.assertEqual(rows[0], Row("x", True, True))
        self.assertEqual(len(rows), 4)

    def test_yes_no_forms(self):
        rows = fx.read_rows("g,p\na,yes\nb,No\nc,TRUE\nd,f\n", "g", "p")
        self.assertEqual([r.pred for r in rows], [True, False, True, False])

    def test_errors(self):
        for text, cols in ((self.CSV, ("nope", "pred", "label")), ("group,pred\n", ("group", "pred", None)), ("group,pred\na,maybe\n", ("group", "pred", None)),
                           ("group,pred\n,1\n", ("group", "pred", None)), ("group,pred\na,\n", ("group", "pred", None)), ("", ("group", "pred", None))):
            with self.subTest(text[:12]), self.assertRaises(FairnessError):
                fx.read_rows(text, *cols)

    def test_synthetic_is_reproducible_and_round_trips(self):
        spec = [g("a", 200, 0.7, 0.2), g("b", 200, 0.6, 0.2)]
        self.assertEqual(rows_for(spec, 4), rows_for(spec, 4))
        self.assertNotEqual(rows_for(spec, 4), rows_for(spec, 5))
        self.assertEqual(fx.read_rows(fx.to_csv(rows_for(spec, 4)), "group", "pred", "label"), rows_for(spec, 4))


if __name__ == "__main__":
    unittest.main()
