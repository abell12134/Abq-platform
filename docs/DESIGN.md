# ABQ Lab 平台设计文档

> 版本：2026-08-27 · 状态：P5 MVP + P6/R3 + 壳层质感已落地  
> 使用说明见 [USER_GUIDE.md](./USER_GUIDE.md)

---

## 1. 产品定位

**ABQ Lab** 是一个独立的 A 股 / ETF 分析工作台。核心不是「问答」，而是 **用 LLM 编排分析过程**——大盘、单票、组合三类分析由多个子 agent 协作完成，全过程被记录、可回放，长链路自动压缩上下文。

与 abq「预测账本」后端（L1/L2/L3 确定性结算）是两套东西：本平台后端是 **LLM 编排引擎**；abq 的数据管道 / 因子 / 信号逻辑仅作工具实现参考，代码独立。

### 1.1 能力矩阵

| 用户需求 | 平台对应 | 实现状态 |
|---|---|---|
| 自然语言发起分析 | 对话页 + composer | ✅ |
| 记录分析路径 | `AnalysisPath` 步骤树持久化 | ✅ |
| 上下文压缩 | 后端 `CompactionEngine` + 上下文页可视化 | ✅ |
| 大盘研判 | `kind=market` pipeline | ✅ |
| 单票分析 | `kind=single` LangGraph pipeline | ✅ |
| 选组跟踪 / 诊断 | `kind=portfolio` pipeline + 选组页 | ✅ MVP |
| 子 agent 库 | Agent / 提示词 / 工具 三库 | ✅ |
| 因子库与挖掘 | FactorExpr + LLM/GP 双轨 + 五道准入 | ✅ |
| 多模型 | primary API + local 小模型分层 | ✅ |
| 会话记忆 / 知识库 RAG | path 索引 + knowledge 归档 + embedding + 政策库 | ✅ P6 |
| 知识图谱（CSI300） | `graph.db` + 样本同步 + 政策/公告入图 + Rollup | ✅ R3 |
| 工作台质感 | 终端 chrome + Quote 板 + 图谱 HUD | ✅ |
| ETF realm | realm 分流 | ⬜ P6 |

---

## 2. 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│ 前端 (React + Vite + TypeScript)                             │
│  对话 / 选组 / 工作流 / 上下文 / 库  ←→  SSE + REST           │
├─────────────────────────────────────────────────────────────┤
│ API 层 (FastAPI)                                             │
│  REST: 路径 / 三库 / 选组 / 因子 CRUD                         │
│  SSE : POST /api/analyze/stream 逐 step 推送                 │
├─────────────────────────────────────────────────────────────┤
│ 编排层 (orchestration)                                       │
│  compose_route → single | market | portfolio pipeline        │
│  agent_loop : ReAct 推理 + 工具调用                          │
│  LangGraph : single_ticket 主图（data→views→debate→judge）   │
├─────────────────────────────────────────────────────────────┤
│ 子 agent 层 (data/agents/*.yaml + data/prompts/*.yaml)       │
│  tech / fundamental / sentiment / market / portfolio / judge │
├─────────────────────────────────────────────────────────────┤
│ 工具层 (langchain_tools.py)                                  │
│  行情 / 清洗 / 指标 / 舆情 / 板块宽度 / 因子 / 挖掘           │
├─────────────────────────────────────────────────────────────┤
│ 上下文层 (context/)                                          │
│  token 计数 + 渐进压缩 → ContextSnapshot                     │
├─────────────────────────────────────────────────────────────┤
│ 持久层 (persistence/)                                      │
│  paths / agents / prompts / factors / portfolios (JSON/YAML) │
│  knowledge/*.jsonl + memory.db + graph/graph.db（P6 + R3）   │
├─────────────────────────────────────────────────────────────┤
│ LLM 适配层 (llm/)                                            │
│  LlmRouter : primary (DeepSeek/小米/Minimax) + local         │
└─────────────────────────────────────────────────────────────┘
```

### 2.1 技术选型摘要

| 层 | 选型 |
|---|---|
| 后端 | Python ≥3.12 + FastAPI + LangGraph + LangChain |
| 前端 | React 19 + Vite 8 + TypeScript 5/6 |
| 状态 | zustand（UI）+ TanStack Query（服务端） |
| 流式 | SSE（`@microsoft/fetch-event-source`） |
| 持久化 | JSON/YAML 文件，无数据库 |
| 取数 | qlib 本地 + 腾讯/东财实时 + baostock 补洞 |
| 样式 | CSS Variables（`frontend/src/styles/tokens.css`），不引大型 UI 库；IBM Plex Sans / Mono |

---

## 3. 核心数据模型

### 3.1 分析请求 `AnalyzeRequest`

```python
class AnalyzeRequest:
    kind: Literal["market", "single", "portfolio"]
    realm: Literal["a-share", "etf"]
    target: str | None          # 单票代码 / 组合 id
    focus: str | None           # 用户侧重，如「重点看新能源」
    agent_ids: list[str] | None
    prompt_id: str | None
    enable_debate: bool         # 牛熊辩论，默认 True
    message: str                # 用户自然语言输入
    session_id: str | None      # 续聊 = 已有 path id
```

### 3.2 分析路径 `AnalysisPath`

每次分析（无论种类）落成一条路径：

```ts
interface AnalysisPath {
  id: string
  kind: "single" | "market" | "portfolio"
  realm: "a-share" | "etf"
  target?: string
  title: string
  status: "running" | "done" | "error" | "cancelled"
  steps: AnalysisStep[]        // 全量落盘
  snapshots: ContextSnapshot[] // 压缩快照
  reports?: PipelineReports    // 结构化 agent 输出
}
```

**原则**：持久化全量 steps ≠ 模型可见上下文。压缩后生成 `ContextSnapshot`，供续聊与 judge 使用。

### 3.3 步骤 `AnalysisStep`

```ts
interface AnalysisStep {
  id: string
  role: "user" | "assistant" | "tool"
  agent?: string               // tech / judge / fetch_quote …
  thought?: string
  result?: string
  toolCalls?: ToolCall[]
  tier?: "primary" | "local"
}
```

SSE 事件类型：`step` · `token` · `phase` · `compaction` · `done` · `error`

### 3.4 组合 `PortfolioRecord`

```yaml
id: default
name: 默认自选
realm: a-share
members:
  - symbol: "600519"
    note: ""
  - symbol: "600363"
  - symbol: "300750"
```

扩展：`PortfolioSnapshot`（实时等权汇总）、`TrackRecord`（每日快照时间线）。

### 3.5 因子 `FactorRecord`

```yaml
id: mom_20
name: 20日动量
origin: catalog | llm | gp | synth
status: candidate | passed_auto | live | rejected | …
expr: { op: sub, args: [...] }   # FactorExpr IR，禁 eval
formula: sub(div(close, delay(close, 20)), 1)
metrics: { ic_mean, icir, … }
```

---

## 4. 编排设计

### 4.1 路由 `compose_route`

规则路由（`POST /api/compose/route`），从用户输入推断 kind 与 intent：

| 信号 | kind / intent | 执行方式 |
|---|---|---|
| 含 6 位代码、单票关键词 | `single` | tech / fundamental / sentiment pipeline |
| 大盘 / 指数 / 情绪 | `market` | market pipeline |
| 自选 / 组合 / 多代码 | `portfolio` | portfolio pipeline |
| 列出组合 / 因子 / 挖掘 / 选股 / 入库 / 检索 / 取消 | `single` + `intent=*` | **确定性** `simple_action_pipeline`（`agent_ids: []`） |
| 复合选股 + 导入/诊断 | `composite_screen` | `run_composite_screen_plan` |
| 记忆关键词（上次/对比/近一周） | 任意 kind | `memory_intent` 预取，仍走原 pipeline |

前端 `lib/detectKind.ts` 与 composer 路由提示对齐；用户可覆盖 `agent_ids` / `prompt_id`。

### 4.1.1 确定性 NL（`detect_simple_intent`）

实现：`nl_plan.py` 解析 → `analyze_stream` 优先分支 → `simple_action_pipeline.py`。

| intent | pipeline |
|---|---|
| `list_portfolios` | `run_list_portfolios_pipeline` |
| `list_factors` | `run_list_factors_pipeline` |
| `factor_mine` | `run_factor_mine_pipeline` → `FactorMineBanner` |
| `factor_screen` | `run_composite_screen_plan`（仅 screen 步） |
| `ingest_policy` | `run_ingest_policy_pipeline` |
| `search_knowledge` | `run_search_knowledge_pipeline` |
| `cancel_analysis` | `run_cancel_analysis_pipeline` |

完整话术见 [NL_SCENARIOS.md](./NL_SCENARIOS.md)。

### 4.1.2 NL 规划：为何用正则？正则配不上怎么办？

**是的**，`nl_plan.py` 对 NL Coverage 清单里的「控制台动作」走 **正则 + 规则解析**，不是单独再挂一个 planner agent。这是刻意设计：

| 层级 | 机制 | 适用 |
|------|------|------|
| L1 快路径 | `detect_simple_intent()` 正则 | 列出组合/因子、挖掘、选股、入库、检索、取消等 **白名单话术** |
| L2 结构化 | `parse_nl_plan` / `parse_factor_screen_plan` | 复合选股（screen→apply→diagnose） |
| L3 慢路径 | **supervisor** `run_agent`（ReAct + 工具） | 其余自然语言：多步推理、模糊意图、需工具链组合 |

**正则配不上时**：`detect_simple_intent` 返回 `None` → `analyze_stream` 继续走 L2/L3，**不会报错**。例如「帮我想想茅台和五粮液谁更强」会进单票/组合 pipeline 或 supervisor，由模型自己调工具。

**为何不全部用 agent 规划？**

- NL Coverage 验收要的是 **一句话、零额外点击、结果可复现**；正则路径无 LLM 延迟、可单测、无幻觉路由。
- 全 agent 规划会增加延迟与成本，且「列出我的组合」类指令不需要推理。

**后续可选**：在 L1/L2 都未命中时，增加轻量 **NL planner agent**（只输出 `intent + plan` JSON），再交给确定性 pipeline 执行——与当前 supervisor 并存，而非替换快路径。

### 4.2 单票 pipeline (`kind=single`)

```
用户消息 → extract_symbol
  → data 阶段（串行）：fetch_quote → fetch_ohlcv → clean_data → calc_indicator
  → factors 阶段：attach_factors_for_symbol → factor_summary
  → views 阶段（并行）：tech / fundamental / sentiment (ReAct)
  → debate?（可选）：bull / bear
  → judge（串行）：综合研判
```

实现：`app/orchestration/graphs/single_ticket.py`  
结构化报告写入 `PipelineReports` → `data/paths/{id}/reports.json`

### 4.3 大盘 pipeline (`kind=market`)

```
指数行情 + 板块宽度(fetch_market_breadth) + 板块脉冲(fetch_sector_pulse)
  → 择时因子挂载
  → market / sentiment agent（并行）
  → judge
```

实现：`app/orchestration/graphs/market.py`  
`focus` 注入 `theme_hint` 用于板块匹配。

### 4.4 选组 pipeline (`kind=portfolio`)

```
组合成员批量行情(fetch_portfolio_quotes) + 轻量指标
  → 成员因子截面（前 4 只）
  → portfolio agent（组合诊断）
  → judge（配置与风险研判）
```

实现：`app/orchestration/graphs/portfolio.py`  
成员来源：消息中多代码 **或** `portfolio_store` 默认自选。

### 4.5 Agent 循环

每个子 agent 内部是 ReAct 循环：

1. `build_prompt(agent, task, ctx)` — 人设 + 压缩历史 + findings
2. `llm.complete(messages, tools=agent.tools)`
3. 有 tool_calls → 执行工具 → emit step → 检查压缩
4. 无 tool_calls → emit 最终结论 → return

**流式**：每 emit 一个 thought/tool_call，立即 SSE 推送，不等 agent 跑完。

### 4.6 因子挖掘（对话触发）

用户说「用 LLM 挖 2 个动量因子」→ 编排层 **确定性** `run_factor_mine_pipeline`：

- 调用 `schedule_llm_mine` / `schedule_gp_mine`
- 产出 tool step（`start_factor_mine_*` + `run_id` JSON）
- 前端 `FactorMineBanner` 轮询漏斗，不占对话主线程

supervisor 仍保留同名工具，供复杂多步任务 fallback。

---

## 5. 上下文压缩

| 参数 | 值 |
|---|---|
| 触发阈值 | 默认 **128k token**（`CONTEXT_COMPACT_THRESHOLD_TOKENS`）；且 ≥4 步 |
| 压缩模型 | local tier（Nemotron 等） |
| 落盘 | `data/paths/{id}/context/snapshot-*.json` |
| 续聊策略 | 默认 judge-only；`force_full: true` 可全量重跑 |

压缩内容：旧步骤摘要 + 关键 findings + outputRef 列表；全量 steps 仍保留供工作流回放。

---

## 6. 前端信息架构

### 6.1 页面分工

| 页 | 职责 |
|---|---|
| **对话**（默认） | 空态 Hero / 对话流 + 底输入框；步骤卡默认折叠 |
| **选组** | 等权组合概览、成员表、涨跌时间线、成员编辑 |
| **工作流** | 色块时间线 + 事件账本，按阶段分组 |
| **上下文** | 持久化 vs 模型投影 token 对比 + 压缩事件 |
| **库** | Agent / 提示词 / 工具 / 因子 / 选股 / 知识库 六 Tab |

**布局组件**（`frontend/src/layouts/`）：

- `AppShell.tsx` — 页面切换与 insight 面板编排
- `AppShellSidebar.tsx` — 导航 + 会话列表
- `AppShellHeader.tsx` — 标题、kind 标签、LIVE/快照、上海时钟、LLM 状态
- `useAppShellComposer.ts` — 路由预览、发送、composer 状态
- `ChatComposer.tsx` — 输入框与模型选择（样式见 `ChatComposer.css`）

品牌写法 **`ABQ//Lab`**（侧栏图标 `//`、顶栏 `ABQ//`）是终端风分隔符，参考 GMT 类盯盘终端的 `Brand//` 句式，不是代码注释、也不是路径。

大盘 / 单票 / 选组是分析 **kind**，从对话发起；选组另有独立跟踪页。

### 6.2 视觉语言（2026-08-27）

聊天编排仍是主轴，不做成可拖拽 mosaic 看板，也不做 3D 舞台。偷的是语言：

| 来源 | 落到 ABQ 的部分 |
|---|---|
| 盯盘终端（密度 / chrome） | 顶栏时钟与 LIVE/快照、等宽行情数字、as-of、A 股红涨绿跌、选组成员色块 |
| 电影 HUD（材质） | 近黑底、暗角与颗粒、`.hudLabel` 字距、图谱视口角标、节点余晖 |

**已落地表面**：

- `tokens.css`：IBM Plex、`--up` / `--down`、HUD 工具类、环境光
- 单票 / 组合摘要：Quote 板（Open/High/Low/Prev/Vol、状态、as-of）；涨跌格热力
- 知识图谱：400px 力导向视口 + 角 HUD（中心代码、跳数、N/E）
- 选组页：成员色块热力；涨跌色与行情板对齐（红涨绿跌）
- 对话空态：`ABQ//` kicker + 命令行示例
- Vite：`server.port = 5173` 且 `strictPort: true`

### 6.3 对话展示规则

- 每 agent 只展示最后一条有效 assistant（`chatDisplaySteps.ts`）
- 数据工具合并为 `ToolGroupCard`（取数 / 清洗 / 指标）
- 挖掘工具步骤过滤到 `FactorMineBanner`
- 编排阶段显示 `phase` label（如「拉取行情与指标」）

### 6.4 选组页 MVP

- `GET /api/portfolios/{id}/snapshot` — 实时等权汇总
- `GET/POST /api/portfolios/{id}/tracks` — 历史快照
- `PUT /api/portfolios/{id}` — 成员编辑
- 多组合 CRUD（侧栏列表 + 新建 / 删除）
- 「发起组合诊断」→ 对话流 `kind=portfolio`
- 会话列表显示 kind 标签（单票 / 大盘 / 选组）
- 对话侧栏 `PortfolioInsightPanel`；成员色块热力

**未做**：自定义权重（仍等权）。

---

## 7. 因子库设计

### 7.1 三条发明路径

```
种子目录 (22+)     LLM 挖掘 (RD-Agent)     GP 双轨 (gplearn/DEAP)
      │                    │                        │
      └────────────────────┴────────────────────────┘
                           ▼
                    FactorExpr IR（白名单算子树）
                           ▼
                    五道准入评测
                           ▼
                    data/factors/*.yaml
                           ▼
              分析挂载 / agent 工具 / 库 UI
```

### 7.2 五道准入

1. 初筛（IC / 覆盖率）
2. 去重（与库内因子相关度）
3. 样本外
4. 经济逻辑（LLM / 人工）
5. 纸面跟踪（Gate 5）

### 7.3 与分析链路的关系

因子是 **确定性工具**，不进 system prompt 大段面板。agent 通过 `list_factors` / `compute_factor` / `factor_analysis` 拿摘要统计；单票数据阶段自动 `attach_factors` 写 `reports.factor_summary`。

---

## 8. API 一览

```
# 分析
POST   /api/analyze/stream          SSE 流式分析
POST   /api/analyze/cancel/{id}     停止分析
GET    /api/paths                   会话列表
GET    /api/paths/{id}              路径详情 + snapshots + reports
DELETE /api/paths/{id}?force=true   删除（可强制删 running）

# 路由
POST   /api/compose/route           规则路由

# 三库
GET/POST/PUT/DELETE  /api/agents
GET/POST/PUT/DELETE  /api/prompts
GET                  /api/tools      只读

# 选组
GET/POST/PUT       /api/portfolios
GET                /api/portfolios/{id}/snapshot
GET/POST           /api/portfolios/{id}/tracks

# 因子
GET/POST           /api/factors
POST               /api/factors/mine/llm
POST               /api/factors/mine/gp
POST               /api/factors/synthesize
GET                /api/factors/runs/{id}
```

---

## 9. 目录结构

```
dd/
├── backend/
│   └── app/
│       ├── api/              # FastAPI 路由
│       ├── orchestration/    # pipeline + agent_loop + compose_route
│       │   └── graphs/       # single_ticket / market / portfolio
│       ├── agents/           # agent 规格
│       ├── tools/            # langchain_tools
│       ├── factors/          # 因子库运行时
│       ├── data/             # 取数 / 指标 / 板块脉冲
│       ├── context/          # 压缩引擎
│       ├── persistence/      # 文件存储
│       └── llm/              # LlmRouter
├── frontend/
│   └── src/
│       ├── pages/            # Chat / Portfolio / Workflow / Context / Library
│       ├── components/       # StepCard / FactorMineBanner / …
│       ├── layouts/          # AppShell / Sidebar / Header
│       ├── hooks/            # useAnalyzeStream / useAppShellComposer
│       ├── styles/           # tokens.css（色板、HUD、颗粒）
│       └── stores/           # ui.ts (zustand)
├── data/
│   ├── agents/               # agent YAML 种子
│   ├── prompts/              # 提示词 YAML
│   ├── factors/              # 因子库
│   ├── portfolios/           # 选组配置
│   └── paths/                # 分析路径（运行时）
└── docs/
    ├── DESIGN.md             # 本文档
    ├── USER_GUIDE.md         # 使用说明
    └── images/               # 截图
```

---

## 10. 实施进度（2026-08-27）

| 阶段 | 状态 | 说明 |
|---|---|---|
| P0 骨架 | ✅ | FastAPI + 前端 shell + Vite proxy |
| P1 对话链路 | ✅ | ReAct + SSE + 路径持久化 |
| P2 单票分析 | ✅ | LangGraph data→views→debate→judge |
| P2b 多模型 | ✅ | primary/local 分层 + extract |
| P3 上下文压缩 | ✅ | CompactionEngine + 上下文页 |
| P4 三库 | ✅ | Agent/提示词/工具 CRUD |
| P4+ 组合路由 | ✅ | compose_route + 工作流并行泳道 |
| P5 因子库 | ✅ | FactorExpr + LLM/GP 挖掘 + 挂载 |
| P5 大盘 | ✅ | 指数 + 板块宽度/脉冲 + 择时因子 |
| P5 选组 | ✅ MVP | pipeline + 选组跟踪页 |
| P5.1 选组 | ✅ | 多组合 CRUD + `PortfolioInsightPanel` 侧栏 |
| P5.2 大盘 | ✅ | 真实宽度（涨跌家数）+ data 阶段择时因子挂载 |
| P5.2 因子 | ✅ | `POST /api/factors/paper/revalidate` + IC 曲线 |
| P6 记忆/RAG | ✅ | 归档 + embedding + 政策入库 + episodic |
| R3 知识图谱 | ✅ | CSI300 骨架 + 样本同步 + 公告/政策入图 + Rollup + 库页力导向图 |
| **NL Coverage** | ✅ | 12 条核心话术确定性编排（见 `NL_SCENARIOS.md`） |
| **CI** | ✅ | pytest + ruff（阻断）+ frontend build |
| **壳层质感** | ✅ | 终端 chrome + Quote 板 + 图谱 HUD + 选组热力；Vite `strictPort` |

### P6+ NL 与工程（2026-08-27）

**NL 确定性编排**
- `nl_plan.py`：screen / composite / mine / list / ingest / search / cancel
- `simple_action_pipeline.py`：零 LLM 直跑；工具信封 `suggested_action`（`tools/envelope.py`）
- 前端 `QueryErrorBanner`、`StepCard` 失败提示

**工程**
- `.github/workflows/ci.yml`：`ruff check app` 阻断合并
- AppShell 拆分为 Sidebar / Header / composer hook；composer 样式迁入 `ChatComposer.css`
- Vite `strictPort: true`（只绑 5173）；壳层质感见 §6.2

### 已知限制

- 续聊默认 judge-only
- 涨跌家数来自指数行情字段汇总，非逐股精确统计
- 组合页不支持自定义权重（仍等权）
- 本地 qlib 末日可能落后，自动 baostock 补洞（约一周时滞可能影响因子 as_of）
- Cursor Agent 沙箱代起的 uvicorn **不能**访问远端 LLM；后端须在本机终端启动

---

## 11. 历史文档索引

本文档整合了以下原始设计稿，详细章节可查阅原文件：

| 文档 | 内容 |
|---|---|
| `abq-platform-backend-design.md` | 后端分层、编排时序图、API 细节 |
| `abq-platform-frontend-design.md` | 前端布局、数据结构、展示规则（备查；现行视觉见本文 §6） |
| `abq-platform-factor-lab.md` | 因子 IR、准入闸门、挖掘方案 |
| `abq-platform-tech-stack.md` | 技术选型理由、依赖清单 |
| `abq-platform-system-prompts.md` | 系统提示词分段策略 |
| `abq-web-design-plan.md` | 早期 Web 方案（已被本文取代） |
| `docs/NL_SCENARIOS.md` | 12 条 NL 验收话术与确定性编排 |
| `docs/RAG_PLAN.md` | P6 会话记忆与知识库 RAG 完整方案 |
| `docs/KNOWLEDGE_GRAPH_PLAN.md` | R3 知识图谱、政策采集、可视化方案 |
