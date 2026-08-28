# A股/ETF 分析平台 — 技术选型

> 与 [前端设计](abq-platform-frontend-design.md)、[后端设计](abq-platform-backend-design.md) 配套。本文档回答：**用什么栈、为什么、不选什么、仓库怎么拆**。

## 0. 选型前提（约束）

| 约束 | 对选型的影响 |
|---|---|
| 单用户、本地/内网部署 | 不上 K8s、不上多租户、P0 不做鉴权复杂度 |
| LLM 编排 + A股取数 | 后端必须 Python；前端重流式 UI |
| 过程可回放、文件可 diff | 持久化用 JSON/YAML，不用 DB |
| 主模型 API + 本地小模型 | 统一 OpenAI 兼容 client + Router |
| 对话优先、工作流/上下文分页 | 前端是 SPA，不是 SSR 站点 |

---

## 1. 总览（推荐方案）

```
abq-platform/
├── backend/          # Python 3.12 + FastAPI
├── frontend/         # React 18 + Vite + TypeScript
├── data/             # 运行时数据（paths/agents/llm/…，gitignore 大文件）
├── mockup/           # 静态原型（已有）
└── docs/             # 设计文档（或放仓库根目录 *.md）
```

| 层 | 选型 | 版本建议 |
|---|---|---|
| 后端运行时 | **Python 3.12** | uv 或 venv 管理依赖 |
| API 框架 | **FastAPI** | 异步 + SSE + Pydantic 天然契合 |
| 编排 | **LangGraph** `StateGraph`（单票主图）+ **LangChain** 模型/工具/消息（子 agent ReAct） |
| 模型 | `langchain_openai.ChatOpenAI` + `LlmRouter`（primary/local） |
| 工具 | `langchain_core.tools.@tool` → `registry.execute_tool` / `bind_tools` |
| LLM 客户端 | **httpx** + OpenAI SDK（`base_url` 可指本地） | 一套协议接 primary/local |
| 取数/算指标 | **pandas** + **akshare** / **baostock** | 工具层同步包一层 `asyncio.to_thread` |
| 持久化 | **JSON + YAML 文件** | `aiofiles` 写盘，原子 rename |
| 前端框架 | **React 18 + Vite 6 + TypeScript 5** | 无 SSR 需求，Vite 够快 |
| 路由 | **react-router 7** | 五页：对话 / 工作流 / 上下文 / 库 |
| 服务端状态 | **TanStack Query v5** | paths、agents、health 缓存与重试 |
| 客户端 UI 态 | **zustand** | 当前 session、挂载插件、SSE 缓冲 |
| 流式 | **SSE** | `@microsoft/fetch-event-source`（支持 POST body） |
| 样式 | **CSS Variables + 少量 CSS Modules** | 不引 Ant Design / MUI / Tailwind |

**开发联调**：Vite `server.proxy` → `http://127.0.0.1:8000`；生产由 FastAPI `StaticFiles` 挂 `frontend/dist` 或 nginx 反代。

---

## 2. 后端选型（详）

### 2.1 为什么 Python + FastAPI

| 候选 | 结论 |
|---|---|
| **Python + FastAPI** ✅ | pandas/akshare 生态、你们已有 abq Python 经验、SSE/async 成熟 |
| Node (Nest/Hono) | 取数与指标要在 Python 里再跑一层，多进程割裂 |
| Go/Rust | 编排与 LLM SDK 生态弱，迭代慢 |

FastAPI 负责：REST CRUD、SSE 推送、`LlmRouter`、文件读写。业务逻辑按设计文档分层，**不要**把 LangGraph 节点和 HTTP 路由写进同一个文件。

### 2.2 编排：LangGraph（单票已迁入）

| 阶段 | 做法 | 状态 |
|---|---|---|
| **P1** | `run_agent()` ReAct + SSE | ✅ |
| **P2** | `single_pipeline` 规则链 + asyncio 并行 | ✅（已替换） |
| **P2b** | **LangGraph** `StateGraph`：data → views → debate → judge | ✅ |
| **P4+** | 组合路由、续聊 focus、工作流并行泳道 | ✅ |

单票图：`app/orchestration/graphs/single_ticket.py`。提示词仍在 `data/agents/*.yaml` + `data/prompts/*.yaml`。

### 2.3 LLM 层（LangChain ChatOpenAI）

```text
LlmRouter
  ├── ChatOpenAI (tier=primary)  → DeepSeek / 小米 / Minimax
  └── ChatOpenAI (tier=local)    → Nemotron @ :8001/v1
```

- 实现：`app/llm/langchain_client.py` + `LlmChat` 薄封装（兼容 compaction/format/extract）。
- Token 计数：`tiktoken`（近似）或 provider 返回的 `usage`。
- **不引入** LiteLLM 作为 P0 硬依赖——provider 就 4～5 个，自己包一层更可控；后期 provider 爆炸再加。

### 2.4 工具层（LangChain @tool）

- 定义：`app/tools/langchain_tools.py`（`@tool` 装饰器）。行情/基本面/舆情 + **因子工具** `list_factors` / `compute_factor` / `factor_analysis`（实现见 `app/factors/agent_tools.py`）。
- 注册：`registry.py` 提供 `openai_tool_schemas` / `execute_tool`（`tool.ainvoke`）。
- 子 agent：`agent_loop` 使用 `bind_tools` + `AIMessage` / `ToolMessage`。
- 重 CPU/IO 的 pandas 调用：`await asyncio.to_thread(...)`，避免阻塞 event loop。
- 工具返回大表：长输出走 local **extract** 摘要（`tool_output.compact_tool_output`）。

### 2.5 持久化：文件，不用数据库

| 候选 | 结论 |
|---|---|
| **JSON/YAML 文件** ✅ | 单用户、可 cat/diff、与设计一致 |
| SQLite | 查询稍方便，但 steps 仍是大 JSON，收益不大 |
| Postgres | 过度 |

写盘约定：`*.tmp` → `os.replace`；同 path 串行写；`_index.json` 与 meta 同事务更新。

### 2.6 流式：SSE，不用 WebSocket

| 候选 | 结论 |
|---|---|
| **SSE** ✅ | 服务端→客户端单向 step 流足够；浏览器 `EventSource` / fetch-event-source |
| WebSocket | 双向优势用不上，重连与代理更麻烦 |
| 同步 POST | 单票 20 步会卡 600s，已否决 |

事件类型固定：`step` | `compaction` | `error` | `done`（与前端设计一致）。

### 2.7 后端目录结构（建议）

```text
backend/
├── app/
│   ├── main.py              # FastAPI app、CORS、挂静态资源
│   ├── api/
│   │   ├── paths.py
│   │   ├── analyze.py       # POST /analyze/stream (SSE)
│   │   ├── agents.py
│   │   ├── llm.py           # health / providers
│   │   └── portfolios.py
│   ├── orchestration/
│   │   ├── supervisor.py
│   │   ├── agent_loop.py
│   │   └── graphs/          # LangGraph（P2）
│   ├── agents/              # SubAgent 加载、prompt 组装
│   ├── tools/               # fetch_ohlcv, clean_data, ...
│   ├── context/             # CompactionEngine, token count
│   ├── llm/                 # LlmRouter, providers
│   └── persistence/         # paths, atomic write, index
├── pyproject.toml
└── tests/
```

### 2.8 后端关键依赖（`pyproject.toml` 草案）

```toml
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
  "sse-starlette>=2.0",
  "pydantic-settings>=2.0",
  "pyyaml>=6.0",
  "aiofiles>=24.0",
  "httpx>=0.28",
  "openai>=1.0",
  "tiktoken>=0.8",
  "pandas>=2.2",
  "akshare>=1.14",
  "langgraph>=0.2",      # P2 再真正用
  "langchain-core>=0.3", # LangGraph 同伴，minimal use
]
```

---

## 3. 前端选型（详）

### 3.1 为什么 React + Vite，而不是 Next.js

| 候选 | 结论 |
|---|---|
| **React + Vite SPA** ✅ | 单用户工具、无 SEO、部署=静态文件；与 mockup 迁移直接 |
| Next.js | SSR/RSC 无收益，反而多一层部署 |
| Vue / Svelte | 可行，但 dsh 与现有 mockup 思路更接近 React 生态 |

### 3.2 状态怎么拆

```text
zustand（短命、高频）
  ├── 当前 page（chat | workflow | ctx | agent-lib）
  ├── 当前 sessionId / 挂载的 plugin chips
  └── SSE 流缓冲（正在追加的 step）

TanStack Query（服务端数据）
  ├── GET /api/paths, /api/paths/:id
  ├── GET /api/agents, /api/prompts, /api/tools
  ├── GET /api/llm/health
  └── mutation：三库 CRUD、删除会话、取消分析
```

**不要**把完整 AnalysisPath 只放 zustand——刷新丢失；SSE 追加时 `queryClient.setQueryData` 合并进缓存。

### 3.3 SSE 客户端

原生 `EventSource` **不能 POST body**。分析请求要带 `AnalyzeRequest` JSON，因此用：

- **`@microsoft/fetch-event-source`**：`fetch` + SSE 解析，支持 POST、自定义 header、abort。

```ts
// 伪代码
await fetchEventSource("/api/analyze/stream", {
  method: "POST",
  body: JSON.stringify(req),
  onmessage(ev) { /* step | compaction | done */ },
});
```

### 3.4 样式：Design Tokens，不引组件库

mockup 已是深色 + 橙色 accent + 高密度。落地方式：

- `src/styles/tokens.css` — CSS variables（`--bg`, `--accent`, …）
- 页面级 `*.module.css` — 布局与组件
- **不引** Ant Design / shadcn 全套——对话流、工作流色块、token 仪表都是**领域组件**，通用库反而要大量覆盖样式

可选：仅引入 **@radix-ui/react-dropdown-menu** 等无样式原语（composer 下拉），不强制。

### 3.5 路由

```text
/                 → 对话（默认）
/ticket           → 单票汇总（当前 path）
/workflow         → 工作流（需 session/path 上下文）
/context          → 上下文（token 对比仪表）
/agent-lib        → 库（Agent / 提示词 / 工具）
```

侧栏 Sessions 切换不走路由参数也行（zustand `sessionId`），但五页用 react-router 便于深链 `#/workflow`。

### 3.6 前端目录结构（建议）

```text
frontend/
├── src/
│   ├── app/
│   │   ├── App.tsx
│   │   └── router.tsx
│   ├── layouts/
│   │   └── AppShell.tsx       # 全局侧栏 + 顶栏 + composer dock
│   ├── pages/
│   │   ├── ChatPage.tsx
│   │   ├── SingleTicketPage.tsx
│   │   ├── WorkflowPage.tsx
│   │   ├── ContextPage.tsx
│   │   └── AgentLibPage.tsx
│   ├── components/
│   │   ├── composer/
│   │   ├── chat/              # 消息、plugin 卡片
│   │   ├── workflow/          # 时间线、账本
│   │   ├── StepCard.tsx, ToolGroupCard.tsx, MarkdownBody.tsx
│   ├── lib/
│   │   ├── contextView.ts     # 上下文页视图模型
│   │   ├── chatDisplaySteps.ts
│   │   └── ticketSummary.ts
│   ├── hooks/
│   │   ├── useAnalyzeStream.ts
│   │   └── useLlmHealth.ts
│   ├── stores/
│   │   └── ui.ts              # zustand
│   ├── api/
│   │   └── client.ts          # fetch + query keys
│   ├── types/                 # AnalysisPath, AnalysisStep, ...
│   └── styles/
│       └── tokens.css
├── index.html
├── vite.config.ts
└── package.json
```

### 3.7 前端关键依赖（`package.json` 草案）

```json
{
  "dependencies": {
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "react-router": "^7.0.0",
    "@tanstack/react-query": "^5.60.0",
    "zustand": "^5.0.0",
    "@microsoft/fetch-event-source": "^2.0.4"
  },
  "devDependencies": {
    "typescript": "^5.6.0",
    "vite": "^6.0.0",
    "@vitejs/plugin-react": "^4.3.0"
  }
}
```

---

## 4. 明确不选（避免过度工程）

| 不选 | 原因 |
|---|---|
| 微服务 / gRPC | 单进程 FastAPI 足够 |
| Redis / 消息队列 | 无多实例、无排队削峰需求 |
| Docker 强制 | 本地 `uvicorn` + `vite` 即可；部署时再容器化 |
| Cordis / 插件容器（dsh 全套） | 单用户演进，用注册表 + YAML 即可 |
| Tauri / Electron 桌面壳 | P0 浏览器；以后要离线再议 |
| GraphQL | REST + SSE 已覆盖 |
| 完整 LangChain 工具链 | 工具自己注册，少一层抽象 |

---

## 5. 与 abq 旧 Web 方案的关系

[abq-web-design-plan.md](abq-web-design-plan.md) 面向 **abq 预测账本 + 同步 POST supervisor**。本平台是**独立重写**：

| 旧 abq Web | 本平台 |
|---|---|
| 同步 `POST /supervisor/ask` | **SSE** `/api/analyze/stream` |
| 7 页数据台 | 对话优先五页（+ 单票汇总） |
| 接 abq 后端 | **新 backend**，abq 仅作工具实现参考 |

两套不合并代码；若以后要对接 dsh，导出的是 **AnalysisPath 事件流 + LibraryEntry**，不是 abq 的 L1/L2 账本 API。

---

## 6. 落地清单与进度

> **进度（2026-08-25）**：P0–P4+ ✅ MVP · **P5a–g（除 f）✅ MVP**（因子库 + LLM/GP 双轨挖掘 + 单票挂载 + agent 因子工具）

**后端**
1. ✅ FastAPI + health + SSE `/api/analyze/stream`（增量 phase/step；孤儿 run 取消）
2. ✅ LangGraph `single_ticket` + LangChain tools/chat
3. ✅ `ohlcv.py`（qlib + 远程补洞）+ `clean_data` / `calc_indicator`
4. ✅ akshare 基本面/舆情；路径 JSON 持久化
5. ✅ `CompactionEngine` + context snapshot + SSE `compaction`
6. ✅ `library_store` + `/api/agents` `/api/prompts` `/api/tools`
7. ✅ 因子库 `app/factors/` + `/api/factors`（P5a/b）+ `mine_llm.py`（P5c）+ `mine_gp.py` / `mine_gp_cs.py`（P5d/e）+ `attach.py` / `agent_tools.py`（P5g）
8. ✅ 组合路由 `compose_route.py` + `POST /api/compose/route`（P4+）

**前端**
1. ✅ 五页 shell + `useAnalyzeStream` + `StepCard` / `WorkflowLedger`
2. ✅ `SessionList` 全宽新对话 + `TicketInsightPanel`
3. ✅ `ContextPage` 四指标卡 + 双栏布局
4. ✅ `LibraryPage` 四 Tab（含因子）

验收：单票分析全链路 → 工作流回放 → 上下文页投影 → 库页可编辑 agent/提示词/因子 → 单票摘要展示因子截面 → composer 路由提示。

**下一步**：因子合成与纸面跟踪（P5f）、对话内触发挖掘、大盘/选组 pipeline、ETF realm（P6）。

---

## 7. 待你拍板的两项（其余已推荐）

| # | 问题 | 推荐 | 备选 |
|---|---|---|---|
| 1 | 仓库形态 | **monorepo** `backend/` + `frontend/` | 两个 git 仓（没必要） |
| 2 | 包管理 | 后端 **uv**，前端 **pnpm** | pip + npm 也行 |

其余按本文档默认执行即可。
