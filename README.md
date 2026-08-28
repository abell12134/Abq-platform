# ABQ Lab Platform

Monorepo: LLM-orchestrated A-share / ETF analysis workbench.

## 实施进度（2026-08-27）

| 阶段 | 状态 | 说明 |
|---|---|---|
| **P0 骨架** | ✅ 完成 | FastAPI + `LlmRouter` + 前端五页 shell + Vite proxy |
| **P1 对话链路** | ✅ MVP | ReAct + SSE 流式 step + 路径 JSON 持久化 + 会话列表 + 模块化系统提示词 |
| **P2 单票分析** | ✅ MVP | `stream_single_ticket_pipeline` → 数据→三视角并行→辩论→judge |
| **P2 数据层** | ✅ | qlib 本地 + 远程补洞；`fetch_quote` 实时行情（腾讯/东财） |
| **P2 会话续聊** | ✅ MVP | 同一会话追加追问（`session_id` = path id）；点「新对话」开新路径 |
| **P2b 多模型 UI** | ✅ MVP | composer 主模型选择 ✅；牛熊辩论 ✅；续聊 judge-only ✅；**format/extract local agent** ✅；阶段 SSE `phase` ✅ |
| **P3 上下文压缩** | ✅ MVP | `CompactionEngine`；SSE `compaction`；**上下文页**双栏布局 |
| **P3 单票/选组视图** | ✅ MVP | `TicketInsightPanel` / `PortfolioInsightPanel` |
| **P4 三库** | ✅ MVP | Agent / 提示词 CRUD；工具只读；库六 Tab |
| **P4+ 组合路由** | ✅ MVP | `compose_route.py` + composer 路由提示 |
| **P5 因子/大盘/选组** | ✅ MVP | 因子库 + LLM/GP 挖掘 + 挂载；大盘/选组 pipeline |
| **P6 记忆/RAG** | ✅ R0–R2 | 归档 + embedding + 政策入库 + episodic + 库页知识 Tab |
| **R3 知识图谱** | ✅ R3.6 | CSI300 骨架、样本同步、公告/政策入图、市场层、Rollup、力导向图（见 [KNOWLEDGE_GRAPH_PLAN](docs/KNOWLEDGE_GRAPH_PLAN.md)） |
| **NL Coverage** | ✅ 12/12 | 确定性编排：`nl_plan` + `simple_action_pipeline`（见 [NL_SCENARIOS](docs/NL_SCENARIOS.md)） |
| **工程** | ✅ | GitHub CI：pytest + **ruff 阻断** + frontend build；AppShell 拆分为 Sidebar/Header/composer hook；Vite **`strictPort: 5173`** |
| **壳层质感** | ✅ | 终端风 chrome（`ABQ//Lab`、时钟、LIVE/快照）；单票 Quote 板（OHLC / as-of）；图谱 HUD 视口；选组色块热力；A 股红涨绿跌 |

**已跑通验收**：对话页发「看 600519，最近量价如何」→ 数据阶段（含补洞）→ 三视角 agent → 综合研判 → 步骤写入 `data/paths/` → 工作流可回放 → **上下文页**可看持久化 vs 模型投影。

**已知限制**：续聊默认 **judge-only**（`force_full: true` 可全量重跑）；支持 **停止分析**（`POST /api/analyze/cancel/{id}`）与 **强制删除** running 会话（`DELETE /api/paths/{id}?force=true`）；新建会话会自动取消其他进行中的分析；取数阶段工具输出仅截断（不走 extract LLM），各阶段 step **增量 SSE**；ReAct 子 agent 仍可对长工具输出走 local extract。组合路由的 `prompt_id` 仅覆盖匹配视角 agent；板块宽度 MVP 为指数 + 涨停池代理，非全市场精确涨跌家数。**不要用 Cursor Agent 沙箱代起 uvicorn**：沙箱会拦截出站 LLM（`PRIMARY_LLM_BASE_URL` / `LOCAL_LLM_BASE_URL`，默认 `118.195.177.58:8001`），会话里会出现 `Blocked by sandbox network policy`。后端请在本机终端启动。

### 三库 API（P4）

```
GET/POST        /api/agents          GET/PUT/DELETE /api/agents/{id}  (?expand=true)
GET/POST        /api/prompts         GET/PUT/DELETE /api/prompts/{id}
GET             /api/tools           只读目录（代码注册，不可 CRUD）
GET/POST/PUT/DELETE /api/portfolios      选组 CRUD + snapshot/tracks
POST           /api/factors/paper/revalidate  纸面因子批量重评
POST            /api/compose/route   规则路由：用户输入 → agent_ids / prompt_id / enable_debate
GET/POST        /api/factors         因子库 CRUD + 评测；POST /api/factors/mine/llm | /mine/gp | /synthesize
```

### 单票编排（示例）

对话发「看 600519，最近量价如何」→ `analyze_stream` 识别代码 → **LangGraph 对齐的** `stream_single_ticket_pipeline`：**数据四步（顺序）→ tech/fundamental/sentiment（并行 ReAct）→ judge（串行）**，全程 SSE 推 step。完整时序图见 [后端设计 §3.4](abq-platform-backend-design.md#34-单票链路端到端示例看-600519最近量价如何)。

## Quick start

### Backend (port 8000)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp ../.env.example ../.env   # optional: set API keys
uvicorn app.main:app --reload --port 8000
```

### Frontend (port 5173)

```bash
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173 — Vite 将 `/api` 代理到 `http://127.0.0.1:8000`（见 `frontend/vite.config.ts`）。`server.strictPort: true`：5173 被占用会直接失败，**不会**自动跳到 5174。

后端须能访问 `.env` 里的 LLM 主机。在本机终端启动 `uvicorn`，不要从受限沙箱代起。

**数据源**：`data/qib/qlib_bin.tar.gz` 首次自动解压。本地 qlib 末日若落后于当天，`fetch_ohlcv` **自动补洞**（移植 abq：`market_quotes` 腾讯/东财 → `baostock_daily` 回退）。`.env` 可关：`OHLCV_BACKFILL_ENABLED`。

## Docs

- **[设计文档](docs/DESIGN.md)** — 整合版架构、数据模型、编排、API
- **[NL 场景清单](docs/NL_SCENARIOS.md)** — 12 条对话验收话术 + 确定性编排说明
- **[RAG 方案](docs/RAG_PLAN.md)** — 会话记忆、知识库归档、本地 embedding 完整设计
- **[知识图谱方案](docs/KNOWLEDGE_GRAPH_PLAN.md)** — R3 CSI300 图谱、政策采集、Rollup、可视化
- **[使用说明](docs/USER_GUIDE.md)** — 日常操作指南（含截图）

历史分册（已并入设计文档，保留备查）：

- [Frontend design](abq-platform-frontend-design.md)
- [Backend design](abq-platform-backend-design.md)
- [Factor lab](abq-platform-factor-lab.md)
- [Tech stack](abq-platform-tech-stack.md)
