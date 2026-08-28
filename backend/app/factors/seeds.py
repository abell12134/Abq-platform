"""Catalog seed formulas. Written to data/factors/catalog on ensure()."""

from __future__ import annotations

from app.factors.ir import expr_to_dict, parse_formula

SEEDS: list[dict] = [
    {
        "id": "mom_5",
        "name": "5日动量",
        "theme": ["momentum"],
        "universe": "csi300",
        "formula": "sub(div(close, delay(close, 5)), 1)",
        "hypothesis": "过去5日涨幅高的股票短期动量延续，预期未来收益偏高。",
    },
    {
        "id": "mom_20",
        "name": "20日动量",
        "theme": ["momentum"],
        "universe": "csi300",
        "formula": "sub(div(close, delay(close, 20)), 1)",
        "hypothesis": "过去20日相对强弱衡量中期动量，强者恒强。",
    },
    {
        "id": "mom_60",
        "name": "60日动量",
        "theme": ["momentum"],
        "universe": "csi300",
        "formula": "sub(div(close, delay(close, 60)), 1)",
        "hypothesis": "一季动量捕捉更长趋势，换手相对较低。",
    },
    {
        "id": "rev_5",
        "name": "5日反转",
        "theme": ["reversal"],
        "universe": "csi300",
        "formula": "sub(div(delay(close, 5), close), 1)",
        "hypothesis": "近5日大涨后容易回吐，短期反转。",
    },
    {
        "id": "vol_5",
        "name": "5日波动率",
        "theme": ["volatility"],
        "universe": "csi300",
        "formula": "ts_std(sub(div(close, delay(close, 1)), 1), 5)",
        "hypothesis": "短期波动高的股票风险补偿或博彩偏好，方向需实证。",
    },
    {
        "id": "vol_20",
        "name": "20日波动率",
        "theme": ["volatility"],
        "universe": "csi300",
        "formula": "ts_std(sub(div(close, delay(close, 1)), 1), 20)",
        "hypothesis": "已实现波动衡量风险；低波异象预期低波动后续收益更高。",
    },
    {
        "id": "high_low_range_20",
        "name": "20日振幅",
        "theme": ["volatility"],
        "universe": "csi300",
        "formula": "div(sub(ts_max(high, 20), ts_min(low, 20)), ts_mean(close, 20))",
        "hypothesis": "高低点振幅大意味着分歧或投机性强。",
    },
    {
        "id": "intraday_range",
        "name": "日内振幅",
        "theme": ["volatility", "microstructure"],
        "universe": "csi300",
        "formula": "div(sub(high, low), close)",
        "hypothesis": "当日高低价差相对收盘价衡量盘中波动。",
    },
    {
        "id": "vol_ratio_5_20",
        "name": "量比5/20",
        "theme": ["volume"],
        "universe": "csi300",
        "formula": "div(ts_mean(volume, 5), ts_mean(volume, 20))",
        "hypothesis": "近5日成交量相对20日均量放大，资金关注度上升。",
    },
    {
        "id": "amount_ratio_5_20",
        "name": "额比5/20",
        "theme": ["volume"],
        "universe": "csi300",
        "formula": "div(ts_mean(amount, 5), ts_mean(amount, 20))",
        "hypothesis": "成交额比成交量更能反映资金力度。",
    },
    {
        "id": "amihud_10",
        "name": "Amihud非流动性10日",
        "theme": ["liquidity"],
        "universe": "csi300",
        "formula": "ts_mean(div(abs(sub(div(close, delay(close, 1)), 1)), add(amount, 1)), 10)",
        "hypothesis": "单位成交额对应的价格冲击越大，非流动性溢价越高。",
    },
    {
        "id": "pv_corr_20",
        "name": "量价相关20日",
        "theme": ["volume", "momentum"],
        "universe": "csi300",
        "formula": "ts_corr(close, volume, 20)",
        "hypothesis": "价量正相关表示趋势受资金确认，动量更易延续。",
    },
    {
        "id": "close_to_high_20",
        "name": "收盘相对20日高点",
        "theme": ["momentum"],
        "universe": "csi300",
        "formula": "sub(div(close, ts_max(high, 20)), 1)",
        "hypothesis": "接近20日高点表示强势；远离则走弱。",
    },
    {
        "id": "close_to_low_20",
        "name": "收盘相对20日低点",
        "theme": ["reversal"],
        "universe": "csi300",
        "formula": "sub(div(close, ts_min(low, 20)), 1)",
        "hypothesis": "远离20日低点越多越强；贴近日低可能超卖。",
    },
    {
        "id": "ma_bias_5",
        "name": "5日均线偏离",
        "theme": ["momentum"],
        "universe": "csi300",
        "formula": "sub(div(close, ts_mean(close, 5)), 1)",
        "hypothesis": "价格高于短均线表示短线强势。",
    },
    {
        "id": "ma_bias_20",
        "name": "20日均线偏离",
        "theme": ["momentum"],
        "universe": "csi300",
        "formula": "sub(div(close, ts_mean(close, 20)), 1)",
        "hypothesis": "价格相对20日均线的位置衡量趋势偏离。",
    },
    {
        "id": "rel_close",
        "name": "相对大盘价格",
        "theme": ["market", "momentum"],
        "universe": "csi300",
        "formula": "div(close, mkt_close)",
        "hypothesis": "个股价格相对指数的水平，衡量相对强弱的慢变量。",
    },
    {
        "id": "excess_mom_20",
        "name": "超额动量20日",
        "theme": ["market", "momentum"],
        "universe": "csi300",
        "formula": "sub(sub(div(close, delay(close, 20)), 1), sub(div(mkt_close, delay(mkt_close, 20)), 1))",
        "hypothesis": "剔除市场本身动量后的个股超额动量。",
    },
    {
        "id": "rel_volume_5",
        "name": "量能相对大盘5日",
        "theme": ["market", "volume"],
        "universe": "csi300",
        "formula": "div(ts_mean(volume, 5), ts_mean(mkt_volume, 5))",
        "hypothesis": "个股成交量是否独立于市场放量。",
    },
    {
        "id": "idio_vol_20",
        "name": "特异波动20日",
        "theme": ["market", "volatility"],
        "universe": "csi300",
        "formula": "sub(ts_std(sub(div(close, delay(close, 1)), 1), 20), ts_std(sub(div(mkt_close, delay(mkt_close, 1)), 1), 20))",
        "hypothesis": "个股波动减去市场波动，衡量特异风险。",
    },
    {
        "id": "timing_mom_20",
        "name": "大盘20日动量（择时）",
        "theme": ["market", "momentum"],
        "universe": "market",
        "formula": "sub(div(mkt_close, delay(mkt_close, 20)), 1)",
        "hypothesis": "指数自身中期动量，用于大盘择时而非选股。",
    },
    {
        "id": "timing_vol_20",
        "name": "大盘20日波动（择时）",
        "theme": ["market", "volatility"],
        "universe": "market",
        "formula": "ts_std(sub(div(mkt_close, delay(mkt_close, 1)), 1), 20)",
        "hypothesis": "市场已实现波动升高时风险偏好下降，用于择时。",
    },
]


def seed_payloads() -> list[dict]:
    out = []
    for raw in SEEDS:
        expr = parse_formula(raw["formula"])
        out.append(
            {
                **raw,
                "formula": raw["formula"],
                "expr": expr_to_dict(expr),
                "origin": "catalog",
                "status": "passed_auto",
                "forward_days": 5,
                "builtin": True,
            }
        )
    return out
