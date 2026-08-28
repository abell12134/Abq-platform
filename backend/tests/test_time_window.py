"""Time window parsing tests."""

from __future__ import annotations

import unittest

from app.orchestration.time_window import (
    DEFAULT_OHLCV_LIMIT,
    ohlcv_window_label,
    parse_ohlcv_limit,
)


class TimeWindowTests(unittest.TestCase):
    def test_default_three_months(self) -> None:
        self.assertEqual(parse_ohlcv_limit("分析这个票002487"), DEFAULT_OHLCV_LIMIT)
        self.assertEqual(DEFAULT_OHLCV_LIMIT, 63)

    def test_half_year(self) -> None:
        self.assertEqual(
            parse_ohlcv_limit("分析这个票002487 注意分析半年的行情"),
            120,
        )
        self.assertEqual(ohlcv_window_label(120), "半年")

    def test_one_year(self) -> None:
        self.assertEqual(parse_ohlcv_limit("看一年走势"), 252)

    def test_recent_n_days(self) -> None:
        self.assertEqual(parse_ohlcv_limit("最近90天行情"), 90)

    def test_focus_merged(self) -> None:
        self.assertEqual(parse_ohlcv_limit("看002487", focus="重点半年"), 120)


if __name__ == "__main__":
    unittest.main()
