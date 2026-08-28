"""FactorExpr IR: whitelist operator trees. No eval, no negative shifts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Union

STOCK_VARS = frozenset({"open", "high", "low", "close", "volume", "amount"})
MARKET_VARS = frozenset(
    {
        "mkt_close",
        "mkt_open",
        "mkt_high",
        "mkt_low",
        "mkt_volume",
        "mkt_amount",
        "mkt_advance",
        "mkt_decline",
        "mkt_limit_up",
    }
)
ALL_VARS = STOCK_VARS | MARKET_VARS

UNARY_OPS = frozenset({"abs", "log", "sign", "sqrt", "rank", "zscore"})
BINARY_OPS = frozenset({"add", "sub", "mul", "div"})
WINDOW_OPS = frozenset(
    {"delay", "delta", "ts_mean", "ts_std", "ts_max", "ts_min", "ts_rank", "ts_sum"}
)
CORR_OPS = frozenset({"ts_corr"})
ALL_OPS = UNARY_OPS | BINARY_OPS | WINDOW_OPS | CORR_OPS
CROSS_SECTION_OPS = frozenset({"rank", "zscore"})

_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_IDENT_RE = re.compile(r"[a-z][a-z0-9_]*")


class FactorExprError(ValueError):
    pass


@dataclass(frozen=True)
class Var:
    name: str


@dataclass(frozen=True)
class Const:
    value: float

    @property
    def is_int(self) -> bool:
        return float(self.value).is_integer()

    @property
    def as_int(self) -> int:
        if not self.is_int:
            raise FactorExprError(f"expected integer constant, got {self.value}")
        return int(self.value)


@dataclass(frozen=True)
class Op:
    op: str
    args: tuple[Expr, ...]


Expr = Union[Var, Const, Op]


def validate_factor_id(factor_id: str) -> None:
    if not _ID_RE.match(factor_id) or len(factor_id) > 64:
        raise FactorExprError("id 须以小写字母开头，仅含小写字母、数字与下划线，最长 64")


def node_count(expr: Expr) -> int:
    if isinstance(expr, Op):
        return 1 + sum(node_count(a) for a in expr.args)
    return 1


def collect_vars(expr: Expr) -> set[str]:
    if isinstance(expr, Var):
        return {expr.name}
    if isinstance(expr, Op):
        out: set[str] = set()
        for arg in expr.args:
            out |= collect_vars(arg)
        return out
    return set()


def uses_market(expr: Expr) -> bool:
    return bool(collect_vars(expr) & MARKET_VARS)


def uses_cross_section(expr: Expr) -> bool:
    if isinstance(expr, Op):
        if expr.op in CROSS_SECTION_OPS:
            return True
        return any(uses_cross_section(a) for a in expr.args)
    return False


def print_expr(expr: Expr) -> str:
    if isinstance(expr, Var):
        return expr.name
    if isinstance(expr, Const):
        if expr.is_int:
            return str(int(expr.value))
        return str(expr.value)
    inner = ", ".join(print_expr(a) for a in expr.args)
    return f"{expr.op}({inner})"


def expr_to_dict(expr: Expr) -> dict:
    if isinstance(expr, Var):
        return {"var": expr.name}
    if isinstance(expr, Const):
        val: float | int = int(expr.value) if expr.is_int else expr.value
        return {"const": val}
    return {"op": expr.op, "args": [expr_to_dict(a) for a in expr.args]}


def expr_from_dict(data: object) -> Expr:
    if not isinstance(data, dict):
        raise FactorExprError("expr 必须是对象")
    if "var" in data:
        name = str(data["var"])
        if name not in ALL_VARS:
            raise FactorExprError(f"未知终端: {name}")
        return Var(name)
    if "const" in data or "n" in data:
        raw = data.get("const", data.get("n"))
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise FactorExprError(f"非法常量: {raw}") from exc
        return Const(value)
    op = str(data.get("op", ""))
    args_raw = data.get("args")
    if not isinstance(args_raw, list):
        raise FactorExprError(f"算子 {op} 缺少 args")
    return _checked_op(op, tuple(expr_from_dict(a) for a in args_raw))


def parse_formula(text: str, extra_vars: frozenset[str] | None = None) -> Expr:
    parser = _Parser(text, extra_vars=extra_vars or frozenset())
    expr = parser.parse_expr()
    parser.skip_ws()
    if parser.i < len(parser.s):
        raise FactorExprError(f"公式尾部有多余字符: {parser.s[parser.i:]!r}")
    return expr


def substitute_vars(expr: Expr, mapping: dict[str, Expr]) -> Expr:
    """Replace named terminals with subtrees (used to expand GP primitives)."""
    if isinstance(expr, Var) and expr.name in mapping:
        return mapping[expr.name]
    if isinstance(expr, Op):
        return Op(expr.op, tuple(substitute_vars(a, mapping) for a in expr.args))
    return expr


def _checked_op(op: str, args: tuple[Expr, ...]) -> Op:
    if op not in ALL_OPS:
        raise FactorExprError(f"未知算子: {op}")
    if op in UNARY_OPS and len(args) != 1:
        raise FactorExprError(f"{op} 需要 1 个参数，得到 {len(args)}")
    if op in BINARY_OPS and len(args) != 2:
        raise FactorExprError(f"{op} 需要 2 个参数，得到 {len(args)}")
    if op in WINDOW_OPS:
        if len(args) != 2:
            raise FactorExprError(f"{op} 需要 (x, n) 两个参数")
        n = _window_n(args[1], op)
        if op in {"ts_std"} and n < 2:
            raise FactorExprError("ts_std 窗口必须 >= 2")
    if op in CORR_OPS:
        if len(args) != 3:
            raise FactorExprError("ts_corr 需要 (x, y, n) 三个参数")
        n = _window_n(args[2], op)
        if n < 2:
            raise FactorExprError("ts_corr 窗口必须 >= 2")
    return Op(op, args)


def _window_n(node: Expr, op: str) -> int:
    if not isinstance(node, Const) or not node.is_int:
        raise FactorExprError(f"{op} 的窗口必须是正整数常量")
    n = node.as_int
    if n < 1:
        raise FactorExprError(f"{op} 禁止 n<1（含负 shift / 前视）")
    return n


class _Parser:
    def __init__(self, text: str, extra_vars: frozenset[str] | None = None) -> None:
        self.s = text.strip()
        self.i = 0
        self.extra_vars = extra_vars or frozenset()

    def skip_ws(self) -> None:
        while self.i < len(self.s) and self.s[self.i].isspace():
            self.i += 1

    def parse_expr(self) -> Expr:
        self.skip_ws()
        if self.i >= len(self.s):
            raise FactorExprError("空公式")
        if self.s[self.i] in "+-" or self.s[self.i].isdigit() or self.s[self.i] == ".":
            return self._parse_number()
        m = _IDENT_RE.match(self.s, self.i)
        if not m:
            raise FactorExprError(f"无法解析: {self.s[self.i:self.i + 12]!r}")
        ident = m.group(0)
        self.i = m.end()
        self.skip_ws()
        if self.i < len(self.s) and self.s[self.i] == "(":
            return self._parse_call(ident)
        if ident not in ALL_VARS and ident not in self.extra_vars:
            raise FactorExprError(f"未知终端: {ident}")
        return Var(ident)

    def _parse_call(self, op: str) -> Op:
        self.i += 1  # (
        args: list[Expr] = []
        self.skip_ws()
        if self.i < len(self.s) and self.s[self.i] == ")":
            self.i += 1
            return _checked_op(op, ())
        while True:
            args.append(self.parse_expr())
            self.skip_ws()
            if self.i >= len(self.s):
                raise FactorExprError(f"{op}( 未闭合")
            if self.s[self.i] == ",":
                self.i += 1
                continue
            if self.s[self.i] == ")":
                self.i += 1
                break
            raise FactorExprError(f"{op}( 参数列表语法错误")
        return _checked_op(op, tuple(args))

    def _parse_number(self) -> Const:
        start = self.i
        if self.s[self.i] in "+-":
            self.i += 1
        dots = 0
        while self.i < len(self.s) and (self.s[self.i].isdigit() or self.s[self.i] == "."):
            if self.s[self.i] == ".":
                dots += 1
                if dots > 1:
                    raise FactorExprError("非法数字")
            self.i += 1
        raw = self.s[start : self.i]
        if raw in {"+", "-", ".", "+.", "-."}:
            raise FactorExprError(f"非法数字: {raw}")
        return Const(float(raw))
