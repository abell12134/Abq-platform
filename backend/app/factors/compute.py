"""Walk a FactorExpr tree on a panel dict. Never eval()."""

from __future__ import annotations

import pandas as pd

from app.factors import ops
from app.factors.ir import (
    ALL_VARS,
    BINARY_OPS,
    CORR_OPS,
    UNARY_OPS,
    WINDOW_OPS,
    Const,
    Expr,
    FactorExprError,
    Op,
    Var,
)

Panel = dict[str, pd.DataFrame]


class FactorComputeError(FactorExprError):
    pass


def _window_int(node: Expr, op: str) -> int:
    if not isinstance(node, Const) or not node.is_int:
        raise FactorComputeError(f"{op} 窗口必须是整数常量")
    n = node.as_int
    if n < 1:
        raise FactorComputeError(f"{op} 禁止 n<1")
    return n


def _const_frame(value: float, shape: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(value, index=shape.index, columns=shape.columns)


def _ref_shape(panel: Panel) -> pd.DataFrame:
    for key in ("close", "mkt_close", "open", "mkt_open"):
        if key in panel and isinstance(panel[key], pd.DataFrame) and not panel[key].empty:
            return panel[key]
    for df in panel.values():
        if isinstance(df, pd.DataFrame) and not df.empty:
            return df
    raise FactorComputeError("面板为空，无法计算因子")


def compute_expr(expr: Expr, panel: Panel, *, allow_cross_section: bool = True) -> pd.DataFrame:
    """Return a wide DataFrame of factor values."""
    shape = _ref_shape(panel)

    def walk(node: Expr) -> pd.DataFrame:
        if isinstance(node, Var):
            if node.name not in ALL_VARS:
                raise FactorComputeError(f"未知终端: {node.name}")
            if node.name not in panel:
                raise FactorComputeError(f"面板缺少字段: {node.name}")
            df = panel[node.name]
            if not isinstance(df, pd.DataFrame):
                raise FactorComputeError(f"{node.name} 不是 DataFrame")
            return df.reindex(index=shape.index, columns=shape.columns)
        if isinstance(node, Const):
            return _const_frame(node.value, shape)
        if not isinstance(node, Op):
            raise FactorComputeError("非法表达式节点")
        if node.op in {"rank", "zscore"} and not allow_cross_section:
            raise FactorComputeError("择时轨道禁止截面算子 rank/zscore")
        if node.op in UNARY_OPS:
            fn = {
                "abs": ops.op_abs,
                "log": ops.op_log,
                "sign": ops.op_sign,
                "sqrt": ops.op_sqrt,
                "rank": ops.op_rank,
                "zscore": ops.op_zscore,
            }[node.op]
            return fn(walk(node.args[0]))
        if node.op in BINARY_OPS:
            fn = {
                "add": ops.op_add,
                "sub": ops.op_sub,
                "mul": ops.op_mul,
                "div": ops.op_div,
            }[node.op]
            return fn(walk(node.args[0]), walk(node.args[1]))
        if node.op in WINDOW_OPS:
            n = _window_int(node.args[1], node.op)
            x = walk(node.args[0])
            fn = {
                "delay": ops.op_delay,
                "delta": ops.op_delta,
                "ts_mean": ops.op_ts_mean,
                "ts_std": ops.op_ts_std,
                "ts_max": ops.op_ts_max,
                "ts_min": ops.op_ts_min,
                "ts_rank": ops.op_ts_rank,
                "ts_sum": ops.op_ts_sum,
            }[node.op]
            return fn(x, n)
        if node.op in CORR_OPS:
            n = _window_int(node.args[2], node.op)
            return ops.op_ts_corr(walk(node.args[0]), walk(node.args[1]), n)
        raise FactorComputeError(f"未实现算子: {node.op}")

    return walk(expr)
