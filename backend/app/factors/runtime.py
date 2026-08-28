"""Compute factor values for catalog and synth records."""

from __future__ import annotations

import pandas as pd

from app.factors.compute import compute_expr
from app.factors.ir import expr_from_dict, uses_cross_section
from app.factors.panel import Panel
from app.models.factors import FactorRecord


def compute_factor_panel(rec: FactorRecord, panel: Panel) -> pd.DataFrame:
    if rec.origin == "synth":
        from app.factors.synth import compute_synth_panel

        return compute_synth_panel(rec, panel)

    expr = expr_from_dict(rec.expr)
    allow_cs = rec.universe != "market"
    return compute_expr(expr, panel, allow_cross_section=allow_cs or uses_cross_section(expr))
