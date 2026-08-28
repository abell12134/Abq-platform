from __future__ import annotations

import unittest

from app.models.analysis import AnalyzeRequest
from app.orchestration.compose_route import route_compose
from app.orchestration.pipeline_phases import resolve_view_agent_ids
from app.prompts.loader import prompt_id_for_agent


class ComposeRouteTests(unittest.TestCase):
    def test_sentiment_keywords(self) -> None:
        out = route_compose("600519 最近舆情怎么样")
        self.assertIn("sentiment", out["agent_ids"])
        self.assertEqual(out["prompt_id"], "sentiment-instructions")

    def test_tech_keywords(self) -> None:
        out = route_compose("看量价背离和均线支撑", focus="重点技术面")
        self.assertEqual(out["agent_ids"][0], "tech")

    def test_resolve_view_agent_ids_filters_invalid(self) -> None:
        req = AnalyzeRequest(message="x", agent_ids=["tech", "nope", "fundamental"])
        self.assertEqual(resolve_view_agent_ids(req), ("tech", "fundamental"))

    def test_prompt_id_routes_to_matching_agent(self) -> None:
        req = AnalyzeRequest(message="x", prompt_id="fundamental-instructions")
        self.assertEqual(prompt_id_for_agent("fundamental", req), "fundamental-instructions")
        self.assertIsNone(prompt_id_for_agent("tech", req))


if __name__ == "__main__":
    unittest.main()
