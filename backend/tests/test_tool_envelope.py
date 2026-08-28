"""Tool envelope normalization tests."""

from __future__ import annotations

import unittest

from app.tools.envelope import tool_err, tool_ok, wrap_tool_result


class EnvelopeTests(unittest.TestCase):
    def test_tool_ok_shape(self) -> None:
        out = tool_ok({"a": 1}, summary="ok", next_hints=["x"])
        self.assertTrue(out["ok"])
        self.assertEqual(out["summary"], "ok")
        self.assertEqual(out["data"], {"a": 1})
        self.assertEqual(out["next_hints"], ["x"])

    def test_tool_err_with_suggested_action(self) -> None:
        out = tool_err("nope", suggested_action="retry")
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "nope")
        self.assertEqual(out["suggested_action"], "retry")

    def test_wrap_passes_through_envelope(self) -> None:
        src = {"ok": True, "summary": "done", "data": {"x": 1}}
        out = wrap_tool_result(src)
        self.assertEqual(out, src)

    def test_wrap_legacy_status_error(self) -> None:
        out = wrap_tool_result({"status": "error", "error": "boom"})
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "boom")

    def test_wrap_plain_dict_becomes_data(self) -> None:
        out = wrap_tool_result({"portfolios": []})
        self.assertTrue(out["ok"])
        self.assertEqual(out["data"], {"portfolios": []})

    def test_wrap_non_dict(self) -> None:
        out = wrap_tool_result([1, 2, 3])
        self.assertTrue(out["ok"])
        self.assertEqual(out["data"], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
