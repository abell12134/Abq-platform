from __future__ import annotations

import unittest

from app.factors.eval_ic import forward_returns
from app.factors.ir import parse_formula, print_expr
from app.factors.mine_gp_cs import (
    CS_PRIMITIVES,
    cs_fitness,
    expand_cs_expr,
    random_tree,
)
from app.factors.panel import synthetic_panel


class GpCsTests(unittest.TestCase):
    def test_primitives_expand(self) -> None:
        for name, src in CS_PRIMITIVES.items():
            expanded = expand_cs_expr(parse_formula(name, extra_vars=frozenset(CS_PRIMITIVES)))
            text = print_expr(expanded)
            self.assertNotIn("prim_", text)

    def test_random_tree_fitness(self) -> None:
        panel = synthetic_panel(n_stocks=10, n_days=100, seed=5)
        fwd = forward_returns(panel["close"], 5)
        rng_tree = random_tree(__import__("random").Random(1))
        fit, meta = cs_fitness(rng_tree, panel, fwd, {})
        self.assertIsInstance(fit, float)
        self.assertGreaterEqual(fit, 0.0)
        if fit > 0:
            self.assertIn("ic_mean", meta)


if __name__ == "__main__":
    unittest.main()
