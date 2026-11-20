import datetime
import random
import re
import unittest
from pathlib import Path

from lex_machine import expr
from lex_machine.errors import ExprError
from tests import oracles

D = datetime.date
MARCH_1 = D(2026, 3, 1)


def ctx(system=None, evidence=None, as_of=MARCH_1):
    return expr.Context(system or {}, evidence or {}, as_of)


def run(text, **kw):
    return expr.truth(expr.parse(text), ctx(**kw))


class TestParsing(unittest.TestCase):
    def test_precedence(self):
        self.assertIs(run("true or false and false"), True)             # and binds tighter than or
        self.assertIs(run("not false and false"), False)                # not binds tighter than and
        self.assertIs(run("(true or false) and false"), False)
        self.assertIs(run("not (true and false)"), True)

    def test_comparisons_and_literals(self):
        self.assertIs(run("1 < 2"), True)
        self.assertIs(run("2.5 >= 2.5"), True)
        self.assertIs(run("-3 < 0"), True)
        self.assertIs(run('"a" == "a"'), True)
        self.assertIs(run('"a" != "b"'), True)
        self.assertIs(run('"a\\"b" == "a\\"b"'), True)

    def test_in_lists(self):
        self.assertIs(run('system.role in ["provider", "both"]', system={"role": "both"}), True)
        self.assertIs(run('system.role in ["provider"]', system={"role": "deployer"}), False)
        self.assertIs(run("system.n in [1, 2, 3]", system={"n": 2}), True)

    def test_syntax_errors(self):
        for bad in ("", "   ", "1 <", "and true", "true and", "(true", "true)", "x == 1", "system", "evidence", "system.a == ", "1 < < 2",
                    '"unclosed', "system.a in", "system.a in [system.b]", "system.a in [1,", "present()", "present(1)", "age(true)", "- x",
                    "true false", "system.a == 1 == 2", "foo(system.a)", "1 + 2", 'system.a == "x\\n"', "system.a;", "__import__('os')", "system.a.b.",
                    "system..a", "not", "in [1]"):
            with self.subTest(bad), self.assertRaises(ExprError):
                expr.parse(bad)

    def test_rejects_python_that_is_not_the_language(self):
        for bad in ("system.a.__class__", "(lambda: 1)()", "[1,2][0]", "system.a if true else false", "open('x')", "system.a and __import__('os')"):
            with self.subTest(bad), self.assertRaises(ExprError):
                expr.parse(bad)

    def test_the_module_never_calls_eval(self):
        src = (Path(expr.__file__)).read_text()
        self.assertIsNone(re.search(r"(?<![A-Za-z_.])(eval|exec|compile)\(", src))

    def test_render_round_trips(self):
        rng = random.Random(1)
        for _ in range(300):
            text = oracles.random_expression(rng, ["system.a", "evidence.b.values.c", "evidence.d.values.e"])
            ast = expr.parse(text)
            self.assertEqual(expr.parse(expr.render(ast)), ast)


class TestThreeValuedLogic(unittest.TestCase):
    def test_kleene_tables(self):
        T, F, U = "true", "false", "system.u == 1"
        table = {
            ("and", T, T): True, ("and", T, F): False, ("and", F, U): False, ("and", U, F): False, ("and", T, U): None, ("and", U, U): None,
            ("or", T, U): True, ("or", U, T): True, ("or", F, U): None, ("or", F, F): False, ("or", U, U): None,
        }
        for (op, a, b), want in table.items():
            with self.subTest(op=op, a=a, b=b):
                self.assertIs(run(f"({a}) {op} ({b})"), want)
        self.assertIsNone(run(f"not ({U})"))
        self.assertIs(run("not false"), True)

    def test_unknown_comparison_and_membership(self):
        self.assertIsNone(run("system.x > 3"))
        self.assertIsNone(run('system.x in ["a"]'))
        self.assertIsNone(run("evidence.a.values.b == true"))

    def test_missing_paths_are_recorded(self):
        c = ctx(system={"a": 1})
        expr.truth(expr.parse("system.a == 1 and evidence.x.values.y == true and system.z == 2"), c)
        self.assertEqual(c.missing, {"evidence.x.values.y", "system.z"})

    def test_a_decided_expression_ignores_an_unrelated_gap(self):
        self.assertIs(run("system.risk_class == \"low\" and system.missing_thing == true", system={"risk_class": "high"}), False)

    def test_definite_results_are_never_contradicted_by_any_completion(self):
        """Soundness: if the engine says true or false with some variables unknown, every way of filling them in agrees."""
        rng = random.Random(2)
        names = ["system.a", "system.b", "system.c", "system.d"]
        decided = 0
        for _ in range(600):
            text = oracles.random_expression(rng, names)
            known = {n: rng.randint(0, 3) for n in names if rng.random() < 0.5}
            unknown = [n for n in names if n not in known]
            sysd = {n.split(".")[1]: v for n, v in known.items()}
            got = expr.truth(expr.parse(text), ctx(system=sysd))
            if got is None:
                continue
            decided += 1
            for fill in oracles.completions(unknown, [-1, 0, 1, 2, 3, 4]):
                self.assertIs(oracles.py_eval(text, {**known, **fill}), got, f"{text} with {known}, filled {fill}")
        self.assertGreater(decided, 100)

    def test_matches_python_when_everything_is_known(self):
        rng = random.Random(3)
        names = ["system.a", "system.b", "system.c"]
        for _ in range(1000):
            text = oracles.random_expression(rng, names)
            vals = {n: rng.randint(0, 3) for n in names}
            got = expr.truth(expr.parse(text), ctx(system={n.split(".")[1]: v for n, v in vals.items()}))
            self.assertIs(got, oracles.py_eval(text, vals), f"{text} {vals}")


class TestTypesAndFunctions(unittest.TestCase):
    def test_type_mismatch_is_an_error_not_a_quiet_false(self):
        for text, system in (('system.x == 1', {"x": "1"}), ("system.x < 1", {"x": "a"}), ("system.x == true", {"x": 1}),
                             ("system.x and true", {"x": 1}), ("not system.x", {"x": "yes"}), ("system.x in [1]", {"x": "1"}),
                             ("system.x < system.y", {"x": True, "y": False}), ("system.x", {"x": 3})):
            with self.subTest(text), self.assertRaises(ExprError):
                run(text, system=system)

    def test_booleans_do_not_equal_numbers(self):
        with self.assertRaises(ExprError):
            run("system.x == 1", system={"x": True})

    def test_present(self):
        ev = {"a": {"collected": D(2026, 1, 1), "values": {"flag": False}}}
        self.assertIs(run("present(evidence.a)", evidence=ev), True)
        self.assertIs(run("present(evidence.b)", evidence=ev), False)
        self.assertIs(run("present(evidence.a.values.flag)", evidence=ev), True)       # false is a recorded value
        self.assertIs(run("present(system.x)", system={}), False)

    def test_age_counts_days_exactly(self):
        for collected, as_of in ((D(2026, 1, 1), D(2026, 3, 1)), (D(2025, 3, 1), D(2026, 3, 1)), (D(2024, 2, 29), D(2026, 3, 1)), (D(2026, 3, 1), D(2026, 3, 1))):
            ev = {"a": {"collected": collected}}
            want = oracles.age_days(collected.isoformat(), as_of.isoformat())
            self.assertIs(run(f"age(evidence.a) == {want}", evidence=ev, as_of=as_of), True)
            self.assertIs(run(f"age(evidence.a) == {want + 1}", evidence=ev, as_of=as_of), False)

    def test_age_of_missing_evidence_is_unknown(self):
        self.assertIsNone(run("age(evidence.a) < 30"))

    def test_age_needs_a_collected_date(self):
        with self.assertRaises(ExprError):
            run("age(evidence.a) < 30", evidence={"a": {"values": {}}})

    def test_count(self):
        ev = {"a": {"collected": D(2026, 1, 1), "values": {"items": [1, 2, 3], "n": 4}}}
        self.assertIs(run("count(evidence.a.values.items) == 3", evidence=ev), True)
        self.assertIsNone(run("count(evidence.a.values.nothing) == 3", evidence=ev))
        with self.assertRaises(ExprError):
            run("count(evidence.a.values.n) == 3", evidence=ev)

    def test_references(self):
        ast = expr.parse('system.a == 1 and (present(evidence.b) or age(evidence.c) < 3) and evidence.d.values.e in ["x"]')
        self.assertEqual(expr.references(ast), {"system.a", "evidence.b", "evidence.c", "evidence.d.values.e"})


if __name__ == "__main__":
    unittest.main()
