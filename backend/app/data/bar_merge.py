from __future__ import annotations


def merge_klines(hist: list[dict], recent: list[dict]) -> list[dict]:
    """历史 + 近期合并，重叠日期以 recent（远端）为准。移植自 abq quant/webapp/quotes.py"""
    if not hist:
        return recent
    if not recent:
        return hist
    cut = recent[0]["date"]
    base = [k for k in hist if k["date"] < cut]
    seen = {k["date"] for k in base}
    for k in recent:
        if k["date"] in seen:
            base = [x for x in base if x["date"] != k["date"]]
        base.append(k)
        seen.add(k["date"])
    return sorted(base, key=lambda x: x["date"])
