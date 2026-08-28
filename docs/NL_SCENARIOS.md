# 自然语言场景清单（NL Coverage）

> **验收标准**：下列话术应能通过对话完成，无需先去库页/选组页点按钮。  
> **成功指标**：本表 12 条核心场景全部 ✅（截至 2026-08-26）。  
> **自动化**：`backend/tests/test_nl_plan.py`、`backend/tests/test_screener.py`、`backend/tests/test_compose_route.py`、`backend/tests/test_analyze_stream.py`

## 核心场景

| # | 用户话术 | 期望 intent / 链路 | 状态 |
|---|----------|---------------------|------|
| 1 | 看 600519，最近量价如何 | `kind=single` 单票 pipeline | ✅ |
| 2 | 今天市场怎么样 | `kind=market` 大盘 pipeline | ✅ |
| 3 | 用 LLM 帮我挖 2 个动量因子 | `intent=factor_mine` → `run_factor_mine_pipeline` | ✅ |
| 4 | 用因子从沪深300选出 20 只股票 | `intent=factor_screen` → `run_factor_screen` | ✅ |
| 5 | 从沪深300选出 20 只，放进默认自选并诊断 | `intent=composite_screen`：screen → apply → diagnose | ✅ |
| 6 | 帮我诊断一下默认自选 | `kind=portfolio` | ✅ |
| 7 | 上次怎么看茅台 | `memory_intent` + prefetch | ✅ |
| 8 | 把这段监管条文入库 + 粘贴正文 | `intent=ingest_policy` → `run_ingest_policy_pipeline` | ✅ |
| 9 | 取消当前分析 | `intent=cancel_analysis` → `run_cancel_analysis_pipeline` | ✅ |
| 10 | 列出我的自选组合 | `intent=list_portfolios` | ✅ |
| 11 | 有哪些动量因子 / 列出因子 | `intent=list_factors`（可带主题） | ✅ |
| 12 | 检索政策：减持新规 | `intent=search_knowledge` → `run_search_knowledge_pipeline` | ✅ |

## 确定性 NL 架构（编排层直跑，不经 supervisor）

> `nl_plan.py` 使用 **正则 + 规则** 解析白名单话术，不是 planner agent。  
> **配不上时**走 supervisor / 单票·大盘·选组 pipeline，见 [DESIGN.md §4.1.2](./DESIGN.md#412-nl-规划为何用正则正则配不上怎么办)。

| 模块 | 职责 |
|------|------|
| `nl_plan.py` | 正则检测 + `parse_*_plan()` / `detect_simple_intent()` |
| `simple_action_pipeline.py` | 零 LLM pipeline，yield `PhaseMarker` + `AnalysisStep` |
| `analyze_stream.py` | `simple_intent` 分支优先于 kind dispatch |
| `compose_route.py` | 返回 `intent` + `plan`，`agent_ids: []` |

**已确定性覆盖的 intent**：`list_portfolios`、`list_factors`、`factor_mine`、`factor_screen`、`composite_screen`（screen 步）、`ingest_policy`、`search_knowledge`、`cancel_analysis`。

**仍走 supervisor / ReAct pipeline 的**：单票三视角、大盘、选组诊断、复合任务中含 LLM 研判的步骤。

## 复合任务解析规则

检测到「因子选股」**且**含「导入/放进/写入」或「诊断」时，走编排层 `run_composite_screen_plan`，不经过 supervisor 逐步调工具。

- universe：含「中证500」→ csi500，否则 csi300
- top_n：`选出 N 只` / `top N`
- portfolio_id：默认 `default`；「默认自选」同义
- mode：含「替换/覆盖」→ replace，否则 merge

## 对话内可见结果

| 场景 | UI 表现 |
|------|---------|
| 选股 | `ScreenActionCard`（Top N 表 + 导入选组 + 发起组合诊断） |
| 导入组合 | 气泡「已导入选组」 |
| 组合诊断 | 后续 portfolio pipeline 步骤卡 + 右侧组合摘要 |
| 因子挖掘 | 顶部 **FactorMineBanner** 漏斗进度 |
| 政策入库 | 步骤卡 `ingest_policy_text` + doc_id / 切块数 |
| 知识检索 | 步骤卡 `search_knowledge` + Markdown 命中表 |
| 取消分析 | 步骤卡 `cancel_analysis`；亦可点 composer **停止** |
| 工具失败 | `StepCard` 显示 `suggested_action` 建议下一步话术 |
