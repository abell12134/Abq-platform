"""NL plan and composite intent tests."""

from __future__ import annotations

import unittest

from app.orchestration.compose_route import route_compose
from app.orchestration.nl_plan import parse_nl_plan


class NlPlanTests(unittest.TestCase):
    def test_screen_only_is_not_composite(self) -> None:
        self.assertIsNone(parse_nl_plan("用因子从沪深300选出20只股票"))

    def test_screen_only_plan(self) -> None:
        from app.orchestration.nl_plan import parse_factor_screen_plan

        plan = parse_factor_screen_plan("用因子从沪深300选出20只股票")
        assert plan is not None
        self.assertEqual(plan["intent"], "factor_screen")
        self.assertEqual(plan["steps"], ["screen"])
        self.assertEqual(plan["universe"], "csi300")
        self.assertEqual(plan["top_n"], 20)

    def test_route_compose_factor_screen(self) -> None:
        out = route_compose("用因子从沪深300选出20只股票", kind="single")
        self.assertEqual(out.get("intent"), "factor_screen")
        self.assertIn("plan", out)
        self.assertEqual(out["plan"]["steps"], ["screen"])

    def test_screen_apply_diagnose(self) -> None:
        msg = "从沪深300用因子选出20只，放进默认自选并诊断"
        plan = parse_nl_plan(msg)
        assert plan is not None
        self.assertEqual(plan["intent"], "composite_screen")
        self.assertEqual(plan["universe"], "csi300")
        self.assertEqual(plan["top_n"], 20)
        self.assertEqual(plan["portfolio_id"], "default")
        self.assertEqual(plan["steps"], ["screen", "apply", "diagnose"])

    def test_csi500_replace(self) -> None:
        plan = parse_nl_plan("中证500选出10只替换进默认自选")
        assert plan is not None
        self.assertEqual(plan["universe"], "csi500")
        self.assertEqual(plan["top_n"], 10)
        self.assertEqual(plan["mode"], "replace")
        self.assertEqual(plan["steps"], ["screen", "apply"])

    def test_route_compose_composite(self) -> None:
        out = route_compose("从沪深300选出20只股票放进默认自选并诊断")
        self.assertEqual(out.get("intent"), "composite_screen")
        self.assertIn("plan", out)

    def test_detect_list_portfolios_intent(self) -> None:
        from app.orchestration.nl_plan import detect_simple_intent

        self.assertEqual(
            detect_simple_intent("列出我的自选组合"), {"intent": "list_portfolios"}
        )
        self.assertEqual(detect_simple_intent("我有哪些组合"), {"intent": "list_portfolios"})
        self.assertIsNone(detect_simple_intent("诊断默认自选"))
        self.assertIsNone(detect_simple_intent("看 600519"))

    def test_detect_list_factors_intent(self) -> None:
        from app.orchestration.nl_plan import detect_simple_intent

        out = detect_simple_intent("有哪些动量因子")
        self.assertEqual(out, {"intent": "list_factors", "theme": "动量"})
        out2 = detect_simple_intent("列出因子")
        self.assertEqual(out2, {"intent": "list_factors", "theme": None})
        self.assertIsNone(detect_simple_intent("用因子从沪深300选出20只"))

    def test_route_compose_list_portfolios(self) -> None:
        out = route_compose("列出我的自选组合")
        self.assertEqual(out.get("intent"), "list_portfolios")
        self.assertEqual(out["kind"], "single")
        self.assertIsNone(out["target"])

    def test_route_compose_list_factors(self) -> None:
        out = route_compose("有哪些动量因子")
        self.assertEqual(out.get("intent"), "list_factors")
        self.assertEqual(out.get("theme"), "动量")
        self.assertEqual(out["kind"], "single")

    def test_detect_factor_mine_intent(self) -> None:
        from app.orchestration.nl_plan import detect_simple_intent, parse_factor_mine_plan

        out = detect_simple_intent("用 LLM 帮我挖 2 个动量因子")
        self.assertEqual(out["intent"], "factor_mine")
        self.assertEqual(out["mode"], "llm")
        self.assertEqual(out["k"], 2)
        self.assertEqual(out["theme_hint"], "动量")

        gp = parse_factor_mine_plan("用 GP 发明一个大盘择时因子")
        assert gp is not None
        self.assertEqual(gp["mode"], "gp")
        self.assertEqual(gp["track"], "market")

    def test_route_compose_factor_mine(self) -> None:
        out = route_compose("用 LLM 帮我挖 2 个动量因子")
        self.assertEqual(out.get("intent"), "factor_mine")
        self.assertEqual(out["agent_ids"], [])
        self.assertEqual(out["plan"]["k"], 2)

    def test_detect_ingest_policy_intent(self) -> None:
        from app.orchestration.nl_plan import detect_simple_intent, parse_ingest_policy_plan

        msg = (
            "把这段监管条文入库：\n"
            "标题：信息披露监管要求\n"
            "内容：\n"
            "第一条 上市公司应及时披露重大事项。\n"
            "第二条 减持需提前公告。"
        )
        plan = parse_ingest_policy_plan(msg)
        assert plan is not None
        self.assertEqual(plan["intent"], "ingest_policy")
        self.assertEqual(plan["title"], "信息披露监管要求")
        self.assertIn("第一条", plan["content"])
        self.assertEqual(detect_simple_intent(msg)["intent"], "ingest_policy")

    def test_detect_cancel_analysis_intent(self) -> None:
        from app.orchestration.nl_plan import detect_simple_intent

        self.assertEqual(detect_simple_intent("取消当前分析"), {"intent": "cancel_analysis"})
        self.assertIsNone(detect_simple_intent("取消选股"))

    def test_route_compose_ingest_policy(self) -> None:
        out = route_compose("把这段监管条文入库：\n内容：\n" + "监管要求正文。" * 3)
        self.assertEqual(out.get("intent"), "ingest_policy")
        self.assertEqual(out["agent_ids"], [])

    def test_route_compose_cancel_analysis(self) -> None:
        out = route_compose("取消当前分析")
        self.assertEqual(out.get("intent"), "cancel_analysis")
        self.assertEqual(out["agent_ids"], [])

    def test_detect_search_knowledge_intent(self) -> None:
        from app.orchestration.nl_plan import detect_simple_intent, parse_search_knowledge_plan

        msg = "检索政策：减持新规"
        plan = parse_search_knowledge_plan(msg)
        assert plan is not None
        self.assertEqual(plan["intent"], "search_knowledge")
        self.assertEqual(plan["query"], "减持新规")
        self.assertEqual(plan["knowledge_type"], "policy")
        self.assertEqual(detect_simple_intent(msg)["intent"], "search_knowledge")

    def test_route_compose_search_knowledge(self) -> None:
        out = route_compose("检索政策：减持新规")
        self.assertEqual(out.get("intent"), "search_knowledge")
        self.assertEqual(out["agent_ids"], [])
        self.assertEqual(out["plan"]["query"], "减持新规")

    async def test_search_knowledge_pipeline_empty(self) -> None:
        from app.orchestration.simple_action_pipeline import run_search_knowledge_pipeline

        items = [
            item
            async for item in run_search_knowledge_pipeline(
                {"intent": "search_knowledge", "query": "", "knowledge_type": "policy"}
            )
        ]
        self.assertEqual(items[-1].agent, "search_knowledge")
        self.assertIn("需要检索关键词", items[-1].result)


class ListPortfoliosPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_yields_portfolio_list_step(self) -> None:
        from app.orchestration.simple_action_pipeline import run_list_portfolios_pipeline

        items = [item async for item in run_list_portfolios_pipeline()]
        step = items[-1]
        self.assertEqual(step.role, "assistant")
        self.assertEqual(step.agent, "list_portfolios")
        self.assertIn("我的自选组合", step.result)

    async def test_yields_factor_list_step(self) -> None:
        from app.orchestration.simple_action_pipeline import run_list_factors_pipeline

        items = [item async for item in run_list_factors_pipeline(theme="动量")]
        step = items[-1]
        self.assertEqual(step.role, "assistant")
        self.assertEqual(step.agent, "list_factors")
        self.assertIn("因子", step.result)

    async def test_yields_factor_mine_tool_step(self) -> None:
        from unittest.mock import AsyncMock, patch

        from app.orchestration.simple_action_pipeline import run_factor_mine_pipeline

        mock_result = {
            "status": "running",
            "run_id": "test-run-abc",
            "kind": "llm",
            "message": "LLM 因子挖掘已启动",
        }
        with patch(
            "app.orchestration.simple_action_pipeline.schedule_llm_mine",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            items = [
                item
                async for item in run_factor_mine_pipeline(
                    {
                        "intent": "factor_mine",
                        "mode": "llm",
                        "k": 2,
                        "rounds": 2,
                        "theme_hint": "动量",
                        "universe": "csi300",
                        "use_synthetic": True,
                    }
                )
            ]
        tool_step = next(s for s in items if getattr(s, "role", None) == "tool")
        self.assertEqual(tool_step.agent, "start_factor_mine_llm")
        self.assertIn("test-run-abc", tool_step.result)
        summary = items[-1]
        self.assertEqual(summary.role, "assistant")
        self.assertIn("因子挖掘已启动", summary.result)

    async def test_ingest_policy_pipeline_ok(self) -> None:
        import tempfile
        from pathlib import Path

        from app.config import settings
        from app.orchestration.simple_action_pipeline import run_ingest_policy_pipeline

        with tempfile.TemporaryDirectory() as tmp:
            orig = settings.data_dir
            settings.data_dir = Path(tmp)
            settings.embedding_enabled = False
            try:
                items = [
                    item
                    async for item in run_ingest_policy_pipeline(
                        {
                            "intent": "ingest_policy",
                            "title": "测试政策",
                            "content": "第一条 监管要求\n第二条 信息披露义务说明。",
                            "symbol": None,
                            "theme": "监管",
                        }
                    )
                ]
            finally:
                settings.data_dir = orig
                settings.embedding_enabled = True

        tool_step = next(s for s in items if getattr(s, "role", None) == "tool")
        self.assertEqual(tool_step.agent, "ingest_policy_text")
        self.assertIn("doc_", tool_step.result)
        self.assertIn("政策文档已入库", items[-1].result)

    async def test_cancel_analysis_pipeline_idle(self) -> None:
        from unittest.mock import patch

        from app.orchestration.simple_action_pipeline import run_cancel_analysis_pipeline

        with patch(
            "app.orchestration.simple_action_pipeline.analysis_registry.active_ids",
            return_value=[],
        ):
            items = [item async for item in run_cancel_analysis_pipeline(path_id="current-path")]
        self.assertEqual(items[-1].agent, "cancel_analysis")
        self.assertIn("无进行中", items[-1].result)


if __name__ == "__main__":
    unittest.main()
