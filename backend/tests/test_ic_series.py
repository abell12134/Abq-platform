import unittest

from app.factors.eval_ic import serialize_ic_series
import pandas as pd


class SerializeIcSeriesTests(unittest.TestCase):
    def test_downsample(self) -> None:
        ic = pd.Series([0.01 * i for i in range(200)], index=pd.date_range("2024-01-01", periods=200))
        out = serialize_ic_series(ic, max_points=50)
        self.assertLessEqual(len(out), 50)
        self.assertIn("date", out[0])
        self.assertIn("ic", out[0])


if __name__ == "__main__":
    unittest.main()
