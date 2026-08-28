# A股/ETF 分析平台 — 前端设计

> **备查稿。** 现行信息架构与视觉语言以 [docs/DESIGN.md](docs/DESIGN.md) §6 为准（2026-08-27：`ABQ//Lab` 终端 chrome、Quote 板、图谱 HUD）。下文布局草图可能落后于实现。

## 0. 定位

这是一个**独立的 A股/ETF 分析平台**的前端设计。不是 abq 的壳子——abq 是领域知识和分析逻辑的参考来源之一，但本平台**完全独立重写**，自己拥有状态、路径记录、上下文管理。

平台本质：**用 LLM 编排分析过程**——大盘/单票/组合分析由若干 LLM 驱动的子 agent 协作完成，过程被完整记录、可回放，长链路自动压缩上下文。

## 1. 你要的能力（逐条对齐）

| 你的需求 | 平台对应 | 备注 |
|---|---|---|
| 页面入口参考 dsh | 输入框→编排→工具执行流可视化 | 见 §3.1 |
| 记录分析路径 | 每次分析=一条带步骤树+工具记录的路径，持久化 | 见 §4 |
| 上下文压缩技术 | LLM 上下文 compaction + 全路径持久化，两者都要 | 见 §5 |
| 大盘分析（独立页面，可按输入着重分析） | 大盘研判视图 + 可注入侧重 | 见 §6.1 |
| 单票分析（获取→清洗→分析） | 单票分析链 + 工具链 | 见 §6.2 |
| 子 agent（舆情/做空/做多等） | LLM 驱动角色库，可组合 | 见 §6.3 |
| 提示词库（可选+自定义） | 提示词库管理 | 见 §6.4 |
| 选组（多票组合跟踪+涨跌记录） | 组合跟踪视图 | 见 §6.5 |
| 多模型接入 | 主模型 API + 本地小模型分层 | 见 §9 |

## 2. 架构原则（借鉴 dsh 到什么程度）

借鉴 dsh 的**交互范式和过程呈现思想**，不照搬它的 Cordis 容器内核（你是单用户演进，不是让陌生人写插件）：

**借鉴**：
- **过程即记录**：dsh 的核心是"把模型输出文本变成可记录、可中断、可回放的行动链"。本平台同样——每次分析是一条事件流，不是一次问答。
- **会话+工具调用树**：dsh 的 ui-conversation + ui-tool 范式，本平台直接采用。
- **能力注册**：子 agent / 提示词 / 工具都是可注册可组合的库项（dsh 的能力 seam 思想，简化版）。

**不借鉴**：
- Cordis 插件容器 + patch 配置层（单用户演进用不上）
- slot 声明合并 + type-chain（过度工程）
- 双下行 WebSocket（编排可以是流式或轮询，单通道即可）

## 3. 整体布局

> 2026-08-24 更正：默认入口不是「数据台 + 右侧步骤树」。打开就是对话（对齐 dsh），工作流与上下文压缩各自成页。大盘/单票/选组是对话里触发的分析种类，不是顶栏一级导航。
>
> 2026-08-24 补充：壳层借鉴 [Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) 的**全局侧栏 + 空态引导**，不借它的多产品导航（Runtime / Reports / Alpha Zoo 等）。我们仍是分析工作台，不是量化 SaaS 全家桶。

### 3.1 壳层（全局侧栏，借鉴 Vibe-Trading）

```
┌────────────┬──────────────────────────────────────────────────┐
│ ABQ Lab    │  贵州茅台怎么看 · 单票 · A股          LLM 就绪    │
│            ├──────────────────────────────────────────────────┤
│ ◉ 对话     │                                                  │
│   单票     │   【空态】大标题 + 一句价值主张 + Start CTA         │
│   工作流   │   三张能力卡（编排 / 插件挂载 / 流式过程）           │
│   上下文   │   快捷 chip + 可展开「按场景浏览示例」              │
│ 库         │                                                  │
│            │                                                  │
│ Sessions + │   【有消息】对话流 + 工具/agent 插件卡片            │
│ · 茅台 ●   │                                                  │
│ · 大盘 ◌   │   ▌输入框（全页共用，浮底居中，像 dsh）            │
│ · 组合A ●  │                                                  │
└────────────┴──────────────────────────────────────────────────┘
```

**从 Vibe-Trading 借什么**：

| VT 做法 | 我们怎么用 | 不借什么 |
|---|---|---|
| 左侧**持久**导航 + Sessions | 对话 / 工作流 / 上下文 / **库**放侧栏；会话列表 + 全宽「新对话」按钮 | Runtime、Reports、Portfolio 等产品线导航 |
| 空态 Hero +「Start Research」CTA | 新用户第一眼知道「用自然语言发起分析」 | 营销首页与 Agent 页拆成两个产品 |
| 底部三张能力卡 | 解释：LLM 编排、agent库挂载、流式工具卡 | 照搬橙色 SaaS 视觉 |
| Welcome 分类示例（chip + 可展开） | 按「单票 / 大盘 / 选组 / 多 agent」分 tab 给 prompt | 它的 8 类 crypto/quant 目录 |
| Session 状态点（● 完成 / ◌ 进行中） | 侧栏一眼看出哪条 path 还在跑 | 侧栏折叠态下的完整 rename/delete（可后做） |

**仍对齐 dsh 的部分**：打开默认是对话；工作流、上下文是**整页切换**而不是右栏挂件；输入框三页共用、浮在底部。

### 3.2 五页分工

| 页 | 主区 | 何时用 |
|---|---|---|
| **对话**（默认） | 空态 Hero 或对话流 + 底输入框；步骤卡默认折叠 | 打开产品、提问、跟进 |
| **单票** | 当前 path 的行情头、指标网格、三视角结论、综合研判 | 单票分析完成后快速读结论（不替代对话流） |
| **工作流** | 选中 path 的色块时间线 + 事件账本 | 回看编排过程，不聊天 |
| **上下文** | 持久化 vs 模型投影 token 对比 + 压缩事件 + 关键发现 | 看模型实际吃到什么（见 §3.3） |
| **库** | Agent / 提示词 / 工具（只读）/ 因子 四 Tab + 编辑弹窗 | 维护可复用资产（P4 + P5） |

一次对话会落成一条 `AnalysisPath`。工具调用以卡片插在消息流中，不另开右栏。数据阶段多工具调用在对话页合并为一张「取数」卡片（`ToolGroupCard`）。

大盘 / 选组仍是分析 `kind`（见 §6），从对话里发起（「看大盘，侧重新能源」）。**单票**既是 `kind:'single'` 的分析类型，也提供独立的**结论汇总页**（侧栏「单票」），与对话并列导航但不替代对话发起分析。

### 3.3 上下文页（P3 落地，2026-08-25 布局优化）

对齐 §5「记录的全量 ≠ 模型看到的」：**不**展示调试参数列表，而是持久化层 vs 模型投影的对比仪表。

**信息架构（自上而下）**：

1. **页头** — path 步数、是否已压缩注入、标的代码（pill）。
2. **指标行（4 卡）** — 持久化全量 token、模型可见 token、压缩率、关键发现条数；每卡带迷你色条。
3. **双栏主体（宽屏）** — **左栏**：快照摘要 + `outputRef` 芯片、压缩事件（local）、Runtime user turn（`<details>` 折叠）；**右栏**：关键发现多列卡片网格 + 持久化 token 构成图例。
4. **关键发现** — 每 agent **一条**；可展开卡片，预览两行截断。

页面 `max-width: 1280px` 居中；&lt;1100px 指标 2×2、主体单栏。

**视图模型**：`frontend/src/lib/contextView.ts` 的 `buildContextView()` 从 `workflowSteps` + `contextSnapshots` + `analysisMeta` 计算各段 token 与 `runtimePreview`。

**对话页联动**：SSE `compaction` + `phase` 更新 store；`CompactionBanner`；编排等待时显示阶段 label（如「拉取行情与指标」）。

### 3.4 对话流展示（P2/P3）

| 规则 | 实现 |
|---|---|
| 每 agent 只展示最后一条有效 assistant | `chatDisplaySteps.ts` → `buildChatThread()` |
| 数据工具合并 | `fetch_quote` / `fetch_ohlcv` / `clean_data` / `calc_indicator` → `ToolGroupCard` |
| 步骤默认折叠 | `stepDefaultCollapsed`；展开后 `MarkdownBody` 渲染 |
| 跳过空响应与中间「调用工具」占位 | 后端 `agent_loop` 过滤 + 空响应重试 |

## 4. 分析路径记录（核心数据结构）

每次分析（无论大盘/单票/组合）都是一条 **AnalysisPath**：

```ts
interface AnalysisPath {
  id: string
  title: string                // 自动生成或用户命名
  kind: 'market' | 'single' | 'portfolio'
  realm: 'a-share' | 'etf'     // 市场抽象，扩展用
  target?: string              // single: 股票代码; portfolio: 组合id
  created: string
  steps: AnalysisStep[]
  contextSnapshot: ContextSnapshot  // 见 §5，当前压缩后的上下文
  status: 'running' | 'done' | 'error'
}

interface AnalysisStep {
  id: string
  agent: string                // 哪个子 agent 产出（supervisor/舆情/做空/...）
  thought: string              // LLM 的推理（思考）
  toolCalls: ToolCall[]        // 该步骤的工具调用
  result: string               // 该步结论
  tokensIn: number             // 用于 §5 compaction 决策
  llm?: { tier: 'primary' | 'local'; provider: string; model: string }  // 见 §9
  ts: string
}

interface ToolCall {
  id: string
  tool: string                 // fetch_data / clean_data / calc_indicator / ...
  args: Record<string, unknown>
  output: unknown              // 原始输出（持久化，见 §5）
  outputSummary?: string       // 压缩后的摘要（供后续 LLM 用）
  status: 'ok' | 'error'
}
```

**这是整个平台的脊柱**。UI 的右侧详情栏就是渲染这棵树。持久化它=回放能力；压缩它的 `steps`/`toolCalls.output`=LLM 上下文管理。

## 5. 上下文管理（你说的"两者都要"）

### 5.1 全路径持久化（给人看/回放）
- 每条 AnalysisPath 的全部 steps + toolCalls.output（含原始数据）**完整存盘**。
- 回放 = 重新渲染这棵树，不重新执行。
- 可检索、可对比（把两条单票分析并排看差异）。

### 5.2 LLM 上下文压缩（给模型看，防 context 爆）
长分析链（如单票分析跑了 20 步）会把历史全塞进 prompt，必须压缩。这是 dsh/claude code 那类 harness 的核心技术：

```ts
interface ContextSnapshot {
  // 原始 steps 太长，压缩成摘要喂给下一步 LLM
  summary: string              // 历史步骤的结构化摘要
  keyFindings: Finding[]       // 关键发现（带来源 stepId）
  carriedOutputs: string[]    // 仍需携带的工具输出 ref（其余已摘要化）
  totalRawTokens: number       // 压缩前
  totalCompressedTokens: number // 压缩后
}
```

压缩策略（**整个引擎在后端**，前端只接收 `ContextSnapshot` 并显示压缩前后 token）：
1. **阈值触发**：当待送 LLM 的累积 token 超过阈值（如 model 的 60%），触发压缩。
2. **按步骤老化**：较早的步骤 → 只保留 `outputSummary`（一句话摘要），丢弃 `output` 原始数据（但持久化层仍存全量）。
3. **关键发现提携**：把分散在各步骤的结论聚合成 `keyFindings`，始终完整携带。
4. **渐进压缩**：不是一次全压，而是按重要性梯度——最新的完整、中等的摘要、最老的只留结论。

**关键设计**：持久化层和 LLM 上下文层**分离**。持久化永远存全量（给人回放），LLM 上下文是持久化层的一个有损投影（给模型用）。这正是 dsh "模型可见即已记录"的反向——"记录的全量 ≠ 模型看到的"。

**后端触发条件（MVP）**：`CompactionEngine.should_compact()` — 历史步数 ≥ 6 且估算 token ≥ 3500；续聊入口（`analyze_stream`）与 judge 前 `maybe_compact_findings` 均会调用。未达阈值时 judge 直接吃各 agent 最新 findings（上下文页显示「未压缩，findings 直喂」）。超阈值优先 local LLM 摘要（`data/prompts/compaction-instructions.yaml`），失败回退规则摘要。

## 6. 五大功能视图

### 6.1 大盘分析
- **研判视图**：市场整体指标（可借鉴 abq 的 sector_pulse 行业脉冲逻辑）+ 涨跌分布 + 资金/情绪。
- **可按输入着重**：用户输入"重点看新能源板块资金流"→ supervisor 注入这个侧重 → 子 agent 针对性跑 → 步骤树显示侧重分析。
- 分析结果落到一条 `kind:'market'` 的 AnalysisPath。

### 6.2 单票分析

用户输入股票代码 → 触发标准链路。端到端时序见后端 [§3.4 单票链路端到端](abq-platform-backend-design.md#34-单票链路端到端示例看-600519最近量价如何)。

```
数据获取(fetch_quote/ohlcv) → 清洗(clean_data) → 指标(calc_indicator)
  → 技术面 ∥ 基本面 ∥ 舆情（asyncio 并行）
  → 综合研判(judge)
```

- 数据阶段为**确定性工具**（无 LLM）；三视角与 judge 各走一轮 `agent_loop` ReAct。
- `kind=single` 且有代码时走 `single_pipeline`，**不经 LLM supervisor**（规则 pipeline，非 LangGraph）。
- 每个环节是工具调用或子 agent；前端对话页将数据四步合并为一张「取数」卡片。
- 结果落到 `kind:'single'` 的 AnalysisPath，`target`=股票代码；侧栏「单票」页汇总展示结论。
- **市场抽象**：`realm` 字段区分 A股/ETF，单票分析组件按 realm 渲染不同指标（A股看涨停板/T+1，ETF 看折溢价/成份股）。

### 6.3 子 agent 库（LLM 驱动角色）
```ts
interface SubAgent {
  id: string
  name: string                 // 舆情agent / 做空agent / 做多agent
  persona: string              // 人设 prompt
  tools: string[]              // 可用工具集
  promptTemplate: string       // 提示词模板（引用提示词库）
  modelTier: 'primary' | 'local'  // 默认 primary；抽取/格式化类用 local
  status: 'draft' | 'active'   // 可组合即可用
}
```
- 每个 agent 是 **人设 + 工具集 + 提示词** 的组合，LLM 驱动，结果不固定。
- 可被 supervisor 编排进任何分析链路（单票/大盘）。
- 库管理：CRUD + 试跑 + 挂到分析链路。

### 6.4 提示词库
```ts
interface PromptEntry {
  id: string
  name: string
  category: 'analysis' | 'agent-persona' | 'extraction' | 'summary'
  template: string             // 含变量占位 {{symbol}} {{date}}
  variables: string[]
  isCustom: boolean
}
```
- 分析时可选现成 prompt 套用，也可自定义。
- 子 agent 的人设就是引用一条 prompt。
- 与单票/大盘分析的"着重输入"配合——用户的着重输入填进模板变量。

### 6.5 选组跟踪
```ts
interface Portfolio {
  id: string
  name: string
  realm: 'a-share' | 'etf'
  members: PortfolioMember[]   // 多只票
  // 持续跟踪的涨跌记录
  trackRecords: TrackRecord[]   // 每日/触发式记录
}
interface PortfolioMember {
  symbol: string
  addedAt: string
  note?: string
}
```
- 多票组成一组，持续跟踪涨跌。
- 可对组合整体触发一条 `kind:'portfolio'` 的 AnalysisPath（组合诊断）。
- 涨跌记录时间线视图。

## 7. 三库统一（你说的"开放构建因子/agent/提示词库"）

子 agent / 提示词 / （后续）因子 都是**可复用的库资产**，统一抽象：

```ts
interface LibraryEntry {
  id: string
  kind: 'agent' | 'prompt' | 'factor'
  name: string
  status: 'draft' | 'active' | 'deprecated'
  meta: Record<string, unknown>   // 各 kind 特有字段
  validate: () => ValidationResult // 各库自己的检验
}
```
库管理 UI = 通用列表 + 按 kind 的 keyed 详情视图（**P4 已落地** Agent + Prompt CRUD；工具只读；**因子库见 P5 / [因子方案](abq-platform-factor-lab.md)**）。「根据用户输入自动组合」= 规则路由器选 `prompt_id` + `agent_id`（**P4+ 已落地**：composer 防抖提示 + 分析请求携带 `agent_ids`）。

因子 Tab 不是 VT 式独立 Alpha Zoo 产品页：列表（origin / status / theme）+ 公式与 IC + 挖掘任务（LLM / GP）+ 合成。因子是库资产，挂在分析工具上。

## 9. 多模型（主模型 API + 本地小模型）

与后端 [§8](abq-platform-backend-design.md#8-多模型接入主模型-api--本地小模型) 对齐：**编排与研判用大单模型，抽取与小任务用本地小模型**。

### 9.1 两层模型

| tier | 用户感知 | 典型 provider | 用于 |
|---|---|---|---|
| **primary** | composer 里可选的「主模型」 | DeepSeek、小米、Minimax 等 API | supervisor、tech/fund/sentiment/judge、用户对话 |
| **local** | 设置里配置，composer 显示「本地 ✓」 | 自部署 OpenAI 兼容端点（如 Nemotron） | 数据抽取、格式化、压缩摘要 |

用户只在对话 composer **显式选 primary**（例如 `小米 · mimo-v2-flash`）。local 由平台按 agent 的 `modelTier` 自动路由，避免每步都让用户选。

### 9.2 UI 落点

| 位置 | 展示 |
|---|---|
| **顶栏** | `主模型: Minimax · 就绪` · `本地: nemotron ✓`（`/api/llm/health`） |
| **composer** | 主模型下拉（仅 primary 列表）；旁注「子任务走本地小模型」 |
| **agent库** | 每条 agent 卡片 badge：`primary` / `local` |
| **工作流** | 事件账本每步可选列 `tier · model`（如 `local · nemotron`） |
| **上下文** | 压缩事件注明「由 local 模型摘要」 |

### 9.3 设置（P2b）

轻量设置页或侧栏抽屉：`providers.yaml` 的可编辑视图——主模型默认 provider、local base_url / model id（**密钥只填环境变量，前端不落盘**）。

## 10. 技术栈

> 完整选型理由、目录结构、依赖清单见 [技术选型](abq-platform-tech-stack.md)。

**结论（已推荐）**：

- React 18 + Vite + TypeScript
- 路由：react-router
- 状态：zustand（UI 态）+ TanStack Query（服务端数据）
- 样式：CSS variables token 系统，深色专业数据界面（参考 dsh 视觉：深色/卡片/左导航）。不引大型 UI 库。
- **编排通信：SSE 流式**（第一天就要，与后端一致）。用 `@microsoft/fetch-event-source` POST `/api/analyze/stream`，逐 step 渲染——原生 `EventSource` 不支持 POST body。
- 持久化：**后端文件存储**（JSON/YAML），前端不存数据，只从后端 REST 读路径列表/详情。
- 自建轻量 primitives：**流式步骤树渲染器**、工具调用卡片、涨跌时间线、上下文压缩可视化（显示压缩前后 token）。

## 11. 实施分期

| 阶段 | 状态 | 前端 | 后端联动 |
|---|---|---|---|
| **P0 骨架** | ✅ | shell（左路径列表+主区+右详情）+ 三栏布局 + token 主题 + 路由 | FastAPI 骨架 + LLM seam |
| **P1 路径记录 + 流式** | ✅ MVP | `useAnalyzeStream` + `StepCard` + `SessionList` + 工作流 `WorkflowLedger` | SSE step emitter + 文件持久化 |
| **P2 单票分析** | ✅ MVP | `StepCard` agent 中文名 + 工作流回放 | `single_pipeline` + 数据补洞 + 三视角并行 |
| **P2b 多模型** | ✅ MVP | composer 主模型选择 + 顶栏 health + 工作流 tier 列 | LlmRouter + local extract/compaction |
| **P3 上下文压缩** | ✅ MVP | `ContextPage` 四指标卡 + 双栏布局；`CompactionBanner` | `CompactionEngine` + `snapshot-*.json` + SSE `compaction` |
| **P3 单票视图** | ✅ MVP | 对话页 `TicketInsightPanel`（~420–560px 可收起） | `GET /api/paths/{id}` reports |
| **P3 对话展示** | ✅ MVP | `chatDisplaySteps` / `ToolGroupCard` / 编排 phase label | 增量 SSE + 防双会话 |
| **P4 三库** | ✅ MVP | `LibraryPage` 四 Tab（Agent / 提示词 / 工具 / 因子）+ 编辑弹窗 | 三库 REST CRUD |
| **P4+** | ✅ MVP | composer 路由提示 + `focus` 续聊恢复 + 工作流并行泳道 | `POST /api/compose/route` |
| **P5 因子** | ✅ a–g（除 f） | 库页：筛选 / 评测 / LLM 挖掘 / GP 双轨 / 单票摘要因子区块 | `/api/factors` + `mine/*` + agent 因子工具 |
| **P5 大盘/选组** | ⬜ | 大盘研判视图 + 组合跟踪 + 涨跌时间线 | 大盘/组合数据工具 + 选组跟踪 |
| **P6 多市场** | ⬜ | realm 渲染分流（A股/ETF 不同指标） | ETF realm 工具提供方 |

### 已落地模块（代码索引）

| 模块 | 路径 |
|---|---|
| 对话页 + composer | `frontend/src/pages/ChatPage.tsx`, `components/ChatComposer.tsx` |
| 单票摘要面板 | `frontend/src/components/TicketInsightPanel.tsx`, `TicketInsightBody.tsx`, `lib/ticketSummary.ts`（含 **因子截面** 解析 `factor_summary`） |
| 上下文页 | `frontend/src/pages/ContextPage.tsx`, `lib/contextView.ts` |
| 三库管理 | `frontend/src/pages/LibraryPage.tsx`, `FactorLibrary.tsx`, `api/library.ts` |
| SSE hook | `frontend/src/hooks/useAnalyzeStream.ts` |
| 步骤卡片 / 工作流 | `frontend/src/components/StepCard.tsx`, `ToolGroupCard.tsx`, `pages/WorkflowPage.tsx`, `lib/workflowPhases.ts` |
| 对话线程过滤 | `frontend/src/lib/chatDisplaySteps.ts` |
| Markdown 正文 | `frontend/src/components/MarkdownBody.tsx` |
| agent 中文名 | `frontend/src/lib/agentLabels.ts` |
| 会话列表 | `frontend/src/components/SessionList.tsx`（全宽「新对话」） |
| UI 状态（含 snapshots） | `frontend/src/stores/ui.ts` |

**P4+ 已落地**：composer 路由提示（`routeHint`）、续聊 `focus` 持久化与恢复、工作流并行泳道（`workflowPhases.ts` + `WorkflowPage`）。

**P5g 已落地**：单票摘要右栏「因子截面」卡片；库页 GP 发明支持轨 A（大盘择时）/ 轨 B（截面选股）。

## 12. 待你确认的设计选择

1. **路径列表放左还是右**：dsh 是左导航+右主区，我放成"左路径列表+右详情"。可调。
2. **市场切换**：顶栏全局切换，还是每条分析独立指定 realm？我倾向每条独立（realm 在 AnalysisPath 里），顶栏只是默认值。
