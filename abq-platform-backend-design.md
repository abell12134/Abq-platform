# A股/ETF 分析平台 — 后端设计

> 与 [前端设计](abq-platform-frontend-design.md) 配套。前端定义了 `AnalysisPath`（步骤树）、`ContextSnapshot`（压缩快照）、三库（agent/prompt/factor）等数据结构，本文档定义支撑它们的后端。

## 0. 后端的本质

**一个 agent 编排引擎**。接收分析请求 → supervisor 编排子 agent → 子 agent 跑 LLM 推理 + 调工具 → 产出步骤流 → 持久化 + 压缩上下文。

这与 abq 的"预测账本"后端（L1/L2/L3 结算）是**两套东西**。abq 后端是"确定性算账"，本平台后端是"LLM 编排分析过程"。abq 的数据管道/因子/信号逻辑可作为本平台的**工具实现参考**，但代码独立。

## 1. 对前端设计的两处回填修正

设计后端时发现前端两处保守假设要修正：

| 前端原设计 | 问题 | 修正 |
|---|---|---|
| "上下文压缩前端编排逻辑，后端执行 LLM 摘要" | 压缩是 LLM 调用 + token 计数 + 步骤老化策略，全在后端 | **压缩引擎整体在后端**，前端只接收 `ContextSnapshot` 并显示压缩前后 token |
| "先按后端同步阻塞设计，后端升级流式再切" | 单票分析可能跑 20 步，同步阻塞 600s 体验崩 | **后端第一天就流式（SSE）**，逐 step 推送；前端从"占位"升级为"流式渲染步骤树" |

## 2. 分层架构

```
┌─────────────────────────────────────────────┐
│ API 层 (FastAPI)                              │
│   REST: 路径/库/选组 CRUD                     │
│   SSE : /analyze/stream 逐 step 推送          │
├─────────────────────────────────────────────┤
│ 编排层 (orchestration)                        │
│   supervisor : 路由+聚合                      │
│   agent loop : 单步 LLM推理+工具调用循环      │
│   step emitter: 产出 AnalysisStep 流          │
├─────────────────────────────────────────────┤
│ 子 agent 层 (agents)                          │
│   舆情/做空/做多 = persona+tools+prompt       │
├─────────────────────────────────────────────┤
│ 工具层 (tools)                                │
│   数据获取/清洗/指标/舆情  注册式+realm分提供方│
├─────────────────────────────────────────────┤
│ 上下文层 (context)                            │
│   token计数 + 渐进压缩 + ContextSnapshot      │
├─────────────────────────────────────────────┤
│ 持久层 (persistence)                          │
│   AnalysisPath + 三库 + 选组                  │
├─────────────────────────────────────────────┤
│ LLM 适配层 (llm)                              │
│   LlmRouter : primary API / local 小模型       │
│   providers : DeepSeek/小米/Minimax + 自部署   │
└─────────────────────────────────────────────┘
```

## 3. 编排层（核心）

### 3.1 supervisor：分析请求的入口路由

接收前端的分析请求（大盘/单票/组合 + 用户着重输入），决定调哪些子 agent、什么顺序：

```python
class AnalyzeRequest:
    kind: Literal['market', 'single', 'portfolio']
    realm: Literal['a-share', 'etf']
    target: str | None          # 单票代码 / 组合id
    focus: str | None            # 用户着重输入，如"重点看新能源资金流"
    agent_ids: list[str] | None  # 指定用哪些子agent；None=supervisor自选
    prompt_id: str | None       # 套用的提示词
```

supervisor 的路由（可用 LLM 决策，也可规则）：
- `single` → [数据获取, 清洗, 指标, 技术面agent, 基本面agent, 舆情agent, 综合研判]
- `market` → [大盘数据, 板块脉冲, 情绪agent, （按focus注入侧重agent）, 综合研判]
- `portfolio` → [组合数据, 逐票快速诊断, 综合诊断]

### 3.2 agent loop：单步推理循环

每个子 agent 内部是一个 ReAct 循环（和我讲 dsh 的 while 循环同构，但极简版）：

```python
async def run_agent(agent: SubAgent, task: str, ctx: ContextSnapshot) -> AsyncIterator[AnalysisStep]:
    messages = build_prompt(agent, task, ctx)   # 人设+任务+压缩后的历史
    while True:
        resp = await llm.complete(messages, tools=agent.tools)
        emit thought(resp.thought)               # → AnalysisStep.thought
        if not resp.tool_calls:
            yield final_step(resp.content)      # 不再调工具=完成
            return
        for call in resp.tool_calls:
            output = await tools.execute(call)  # 执行工具
            emit tool_call(call, output)        # → AnalysisStep.toolCalls
            messages.append(tool_result(output))
        # 触发上下文压缩检查（见 §5）
        ctx = maybe_compact(ctx, messages)
```

**关键**：每 emit 一个 thought/tool_call，立即通过 SSE 推前端，不等整个 agent 跑完。这是流式的来源。

### 3.3 串行 vs 并行

- **串行链路**：单票分析的标准链（获取→清洗→分析）必须串行，后者依赖前者输出。
- **可并行的 agent**：同一票的技术面/基本面/舆情三个 agent 互相独立，可并行。supervisor 标记 `parallel_group`，编排层并发跑，步骤树里显示为同层多分支。

**实现说明**：`kind=single` 且识别到股票代码时，走 **LangGraph** `graphs/single_ticket.py`：`data → views → debate? → judge`。三视角在 `views` 节点内 `asyncio` 并行；**结构化报告**写入 `PipelineReports` 并落盘 `reports.json`；牛熊辩论默认开启（`AnalyzeRequest.enable_debate`，`debate_rounds` 默认 1）。

### 3.4 单票链路端到端（示例：「看 600519，最近量价如何」）

用户在对话题发消息后，前端 `POST /api/analyze/stream`（SSE），后端 `analyze_stream` 从消息正则抽出 `600519`，创建 `AnalysisPath`，再调用 `run_single_pipeline`。每步 `append_step` 落盘并 `yield SseEvent(type=step)`；结束时 `done`。

```mermaid
sequenceDiagram
    participant UI as 前端 ChatPage
    participant API as POST /api/analyze/stream
    participant AS as analyze_stream
    participant SP as single_pipeline
    participant Data as 数据层
    participant Loop as agent_loop
    participant LLM as LlmRouter primary

    UI->>API: message + kind=single
    API->>AS: AnalyzeRequest
    AS->>AS: extract_symbol → 600519
    AS->>AS: 创建 path，写入 user step
    AS-->>UI: SSE step (user)

    AS->>SP: run_single_pipeline(600519)

    Note over SP,Data: 阶段 1：数据（无 LLM，顺序执行）
    SP->>Data: fetch_quote
    SP->>Data: fetch_ohlcv (+ qlib 补洞)
    SP->>Data: clean_data
    SP->>Data: calc_indicator
    SP-->>UI: SSE step ×4 (tool)

    Note over SP,LLM: 阶段 2：三视角（asyncio 并行）
    par tech
        SP->>Loop: run_agent(tech)
        Loop->>LLM: 技术面分析（上下文含数据摘要）
    and fundamental
        SP->>Loop: run_agent(fundamental)
        Loop->>LLM: 可能调 fetch_fundamentals
    and sentiment
        SP->>Loop: run_agent(sentiment)
        Loop->>LLM: 可能调 fetch_sentiment
    end
    SP-->>UI: SSE step（三视角交错到达）

    Note over SP,LLM: 阶段 3：多空辩论（可选，默认 1 轮）
    SP->>Loop: run_agent(bull)
  Loop->>LLM: 看多论证
    SP->>Loop: run_agent(bear)
    Loop->>LLM: 看空论证
    SP-->>UI: SSE step（bull / bear）

    Note over SP,LLM: 阶段 4：综合研判（串行）
    SP->>SP: maybe_compact_findings
    SP->>Loop: run_agent(judge)
    Loop->>LLM: 综合 tech / fund / sentiment
    SP-->>UI: SSE step (judge)

    AS-->>UI: SSE done
```

| 阶段 | 模块 | 行为 | 产出 step |
|---|---|---|---|
| 入口 | `analyze_stream.py` | 建 path / 续聊压缩 / 写 user step | `user` |
| 1 数据 | `single_pipeline._run_data_phase` | 行情 → K 线 → 清洗 → 指标（确定性，无 LLM） | `tool` ×4 |
| 2 三视角 | `node_views` | tech / fundamental / sentiment 并行 ReAct → `PipelineReports` | `assistant` |
| 3 辩论 | `node_debate`（可跳过） | bull → bear，读结构化报告 | `assistant` |
| 4 研判 | `node_judge` | 读 reports + debate_history | `assistant` |

**结构化报告**：`app/models/pipeline.py` `PipelineReports`（tech/fundamental/sentiment/bull/bear/judge 各 `AgentReport`）；持久化 `data/paths/{id}/reports.json`；runtime user turn 含「结构化报告」段。

**请求参数**：`enable_debate: bool = true`，`debate_rounds: int = 1`。

**代码索引**：`app/orchestration/graphs/single_ticket.py` · `pipeline_phases.py` · `single_pipeline.py`（graph 流式包装）。

## 4. 工具层（数据重写为工具形式）

**决策**：数据获取完全重写，不碰 abq 代码。abq 的数据逻辑只当参考看。所有数据能力以工具形式存在。

工具是 LLM 可调用的确定性函数。每个工具有 schema（供 LLM）+ 实现：

```python
@tool(realm='a-share')
async def fetch_ohlcv(symbol: str, start: str, end: str) -> DataFrame:
    """获取A股日K"""
    # 实现自写：调 baostock / akshare（参考 abq data_pipeline 的调用方式，但不 import）
```

工具注册表按 realm 分——`fetch_ohlcv` 在 a-share 走 baostock，在 etf 走 ETF 接口。这是多市场落地的关键 seam。

### 数据工具清单（核心）
| 工具 | 职责 | realm 分提供方 |
|---|---|---|
| fetch_ohlcv | 日K数据 | a-share: baostock; etf: ETF接口 |
| fetch_quote | 实时行情 | 同上分 |
| clean_data | 数据清洗（去停牌/前复权/对齐） | realm 无关，参数不同 |
| calc_indicator | 技术指标（MACD/RSI/...） | realm 无关 |
| fetch_sentiment | 舆情数据 | 多源（东财/财联社），参考 abq |
| fetch_fundamentals | 基本面数据 | a-share: 财报; etf: 成份/规模 |

## 5. 上下文压缩引擎（后端实现前端设计的 ContextSnapshot）

前端定义了 `ContextSnapshot`，后端负责生成它：

```python
class CompactionEngine:
    THRESHOLD_RATIO = 0.6   # 累积 token 达模型上限 60% 触发

    def maybe_compact(self, ctx, messages) -> ContextSnapshot:
        tokens = count_tokens(messages)
        if tokens < model_limit * self.THRESHOLD_RATIO:
            return ctx                    # 未触发，原样返回
        # 触发：按步骤老化
        return self.compact(messages)

    def compact(self, messages) -> ContextSnapshot:
        # 1. 较早步骤 → LLM 摘要成一句话，丢弃原始 output
        # 2. 聚合关键发现 keyFindings（始终完整携带）
        # 3. 最新 N 步保留完整
        # 4. 返回压缩快照（持久层仍存全量）
```

**持久与压缩分离**：`tools.execute()` 的原始 output **先进持久层**（全量），再决定喂给 LLM 时压缩。压缩只影响"模型看到的"，不影响"记录的"。

## 6. 子 agent 执行模型

```python
class SubAgent:
    id: str
    name: str
    persona: str               # 人设 prompt（引用提示词库）
    tools: list[str]           # 可用工具 id
    parallel_group: str | None # 并行分组
    model_tier: Literal['primary', 'local'] = 'primary'
    # primary = 云端大模型 API；local = 本地/自部署小模型
    # 未指定时：研判类 agent 默认 primary；抽取/格式化类默认 local（见 §8.3）
```

舆情/做空/做多都是 `SubAgent` 实例，差异只在 persona + tools + **model_tier**。库管理 = CRUD 这些实例。

## 7. 持久层（纯文件存储，无数据库）

**决策**：不用数据库，全部用 JSON/YAML 文件。单用户场景，文件存储足够且更透明可 diff。

### 7.1 目录布局

```
data/
├── paths/
│   ├── _index.json                    # 路径索引（id→标题/kind/realm/状态/创建时间），列表查询走它
│   ├── {pathId}/
│   │   ├── meta.json                  # AnalysisPath 元数据（不含 steps）
│   │   ├── steps/
│   │   │   ├── 01-fetch.json          # 每步单独文件，按序号命名
│   │   │   ├── 02-clean.json
│   │   │   └── ...
│   │   ├── outputs/
│   │   │   ├── {toolCallId}.parquet   # 大输出（DataFrame）单独 blob，steps 里只存 ref
│   │   │   └── ...
│   │   └── context/
│   │       └── snapshot-{n}.json      # 每次压缩的快照（可选，给历史回放）
├── agents/
│   └── {agentId}.yaml                 # 子agent（人设+工具集+prompt）
├── prompts/
│   └── {promptId}.yaml                # 提示词库
├── factors/                           # 因子库（方案见 abq-platform-factor-lab.md）
│   ├── catalog/                       # 种子因子，一文件一条
│   ├── discovered.yaml                # llm / gp / synth，带状态机
│   ├── _index.json
│   └── runs/{runId}/                  # 挖掘任务漏斗与进度
├── llm/
│   ├── providers.yaml                 # 已注册的 provider 端点（密钥走环境变量）
│   └── routing.yaml                   # 默认主模型 / 本地模型 + 角色→tier 映射
└── portfolios/
    ├── _index.json
    └── {portfolioId}/
        ├── meta.json
        └── track-records.json         # 涨跌记录
```

### 7.2 设计原则

| 问题 | 处理 |
|---|---|
| **大 output** | toolCall.output 超阈值（如 1KB）写到 `outputs/{toolCallId}.parquet`，step 文件里只存 `{outputRef}`。小 output 直接内联 JSON |
| **并发写** | agent loop 异步，但**同一条 path 的 step 写入串行**（step 序号递增是天然串行点）；不同 path 各自目录，天然隔离 |
| **原子写** | 一律写临时文件再 `os.replace` rename，绝不在原文件上直接写——崩溃不损坏已有数据 |
| **查询** | 列表/过滤走 `_index.json` 索引文件（每次写 path 时更新索引）；详细回放才扫 `steps/` 目录 |
| **索引一致性** | index 先于实际文件写会有悬空引用——回放时校验 step 文件存在，缺失则标 `partial` |
| **可读可 diff** | YAML 给人读（agent/prompt/factor），JSON 给程序（path steps）。路径回放可直接 cat 看 |

### 7.3 为什么不担心查询性能
单用户、路径量级是百到千条、每条几十步。全量扫描 `_index.json`（百 KB 级）毫秒级。文件存储的真正价值是**透明**——出问题直接打开文件看，不用 SQL client。

## 8. 多模型接入（主模型 API + 本地小模型）

**决策**：系统级编排与复杂研判走**云端大模型 API**；agent 库里偏抽取、格式化、摘要的小任务走**本地小模型**（OpenAI 兼容端点）。两层共用同一 `LlmProvider` 接口，用 `model_tier` 路由，不把「换模型」做成另一套编排引擎。

### 8.1 两类接入

| 类型 | 用途 | 示例 provider | 协议 |
|---|---|---|---|
| **primary（主模型）** | supervisor 路由、综合研判、多 agent 辩论收口、用户对话跟进 | DeepSeek、**小米（MiMo 等）**、**Minimax**、OpenAI 兼容商用 API | 各厂商 REST；统一包成 `LlmProvider` |
| **local（本地小模型）** | 数据抽取、字段对齐、短摘要、压缩摘要、轻量分类 | 自部署 **Nemotron / Qwen 小参** 等 | **OpenAI Chat Completions 兼容** `/v1/chat/completions` |

本地端点示例（配置里写 base_url + model id，**密钥只放环境变量**）：

```bash
# .env — 不要写进仓库
LOCAL_LLM_BASE_URL=http://118.195.177.58:8001/v1
LOCAL_LLM_API_KEY=<your-token>
LOCAL_LLM_MODEL=nemotron-3.5-lightning:30b-a3b-mlx-bf16
```

等价请求形态：

```bash
curl "$LOCAL_LLM_BASE_URL/chat/completions" \
  -H "Authorization: Bearer $LOCAL_LLM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"nemotron-3.5-lightning:30b-a3b-mlx-bf16","messages":[{"role":"user","content":"..."}]}'
```

商用主模型同理：`XIAOMI_API_KEY`、`MINIMAX_API_KEY` 等走 env；`providers.yaml` 只存 base_url、default_model、timeout。

### 8.2 配置与注册

`data/llm/providers.yaml`（无密钥）：

```yaml
providers:
  deepseek:
    tier: primary
    base_url: https://api.deepseek.com/v1
    default_model: deepseek-chat
  xiaomi:
    tier: primary
    base_url: https://api.xiaomimimo.com/v1   # 以厂商文档为准
    default_model: mimo-v2-flash
  minimax:
    tier: primary
    base_url: https://api.minimax.chat/v1
    default_model: abab6.5s-chat
  local-nemotron:
    tier: local
    base_url: ${LOCAL_LLM_BASE_URL}
    default_model: ${LOCAL_LLM_MODEL}
    api_key_env: LOCAL_LLM_API_KEY
```

`data/llm/routing.yaml`：

```yaml
defaults:
  primary_provider: deepseek      # 用户可在设置里改默认主模型
  local_provider: local-nemotron

# 非 agent 库的内置调用方
roles:
  supervisor: primary
  judge: primary
  compaction: local               # 压缩摘要用小模型即可
  user_chat: primary              # 对话页跟用户聊的主链路

# agent 库条目可覆盖；此处是种子默认值
agent_defaults:
  tech: primary
  fundamental: primary
  sentiment: primary
  bull: primary
  bear: primary
  extract: local                    # 数据抽取 / 结构化
  format: local                     # 表格→字段、JSON 修复
```

### 8.3 谁用哪个 tier

| 调用方 | tier | 原因 |
|---|---|---|
| supervisor（路由、委派、对用户回复） | **primary** | 需要强推理与长上下文规划 |
| tech / fundamental / sentiment / judge / bull / bear | **primary** | 研判质量优先 |
| **数据抽取**（公告段落→结构化字段、工具输出→摘要句） | **local** | 模板化、短输出、高 QPS、可离线 |
| **格式化 / 修复**（JSON 补全、列名对齐） | **local** | 小模型足够，省钱省延迟 |
| **compaction 摘要** | **local** | 输入是已有步骤，任务是压缩，不需最强模型 |
| 用户可在 composer 选的「主模型」 | **primary** | 只影响 primary tier 的 provider 选择，不绑架 local |

原则：**主链路质量用大单模型；可替换、可重试、输出短的环节用小模型**。若本地不可用，fallback 到 primary（可配置 `local_fallback: primary | fail`）。

### 8.4 适配层实现

```python
class ModelTier(str, Enum):
    PRIMARY = "primary"
    LOCAL = "local"

class LlmProvider(Protocol):
    tier: ModelTier
    async def complete(self, messages, tools=None, *, model: str | None = None) -> Response: ...
    async def stream(self, messages, tools=None, *, model: str | None = None) -> AsyncIterator[Chunk]: ...

class LlmRouter:
    """按 tier + agent.model_tier + routing.yaml 解析具体 provider。"""

    def resolve(
        self,
        *,
        agent: SubAgent | None = None,
        role: str | None = None,          # supervisor / compaction / ...
        override_primary: str | None = None,  # 用户 composer 里选的主模型
    ) -> LlmProvider: ...

    async def health(self) -> dict[str, bool]:
        """primary / local 是否可达，供顶栏「LLM 就绪」。"""
```

`run_agent` 与 `CompactionEngine` 统一走 router：

```python
provider = llm_router.resolve(agent=agent)          # 子 agent：看 agent.model_tier
provider = llm_router.resolve(role="compaction")  # 压缩
provider = llm_router.resolve(role="supervisor", override_primary=req.primary_model)
resp = await provider.complete(messages, tools=agent.tools)
```

每个 `AnalysisStep` 记录实际使用的 `{tier, provider, model}`，工作流页可回放「这步是小模型做的」。

### 8.5 与工具层的关系

- **取数 / 清洗 / 算指标**：仍是确定性工具，不调 LLM。
- **工具返回后的「抽取」**：若需要 LLM（例如从长公告抽三元组），走 `agent.extract` 或内联 `role=extract` → **local**。
- 不要让小模型承担带工具的 ReAct 长链；local tier 默认 **不开 tools** 或只允许 1 个只读格式化工具，避免弱模型胡调 `fetch_ohlcv`。

### 8.6 API 与前端联动

```
GET  /api/llm/providers          # 已配置 provider 列表（无密钥）
GET  /api/llm/health             # { primary: ok, local: ok }
PUT  /api/settings/llm           # 改默认 primary_provider、local 端点（写 routing.yaml）
```

`AnalyzeRequest` 增加可选字段：

```python
class AnalyzeRequest:
    ...
    primary_model: str | None = None   # 如 "xiaomi:mimo-v2-flash"；只影响 primary tier
```

SSE `step` 事件增加 `llm: { tier, provider, model }` 供工作流页展示。

## 9. API 设计

### REST（CRUD）
```
GET    /api/paths                路径列表
GET    /api/paths/{id}           单条路径全量（steps + snapshots + reports）
DELETE /api/paths/{id}           ?force=true 可中断 running 会话

GET    /api/agents               Agent 列表
POST   /api/agents
GET    /api/agents/{id}          ?expand=true 含解析后 persona/instructions
PUT    /api/agents/{id}
DELETE /api/agents/{id}          内置种子不可删

GET    /api/prompts              提示词列表
POST   /api/prompts
GET    /api/prompts/{id}
PUT    /api/prompts/{id}
DELETE /api/prompts/{id}         内置种子不可删；被 agent 引用时拒绝

GET    /api/tools                工具只读目录（langchain_tools + TOOL_GUIDANCE）

GET    /api/portfolios           选组（P5）
POST   /api/portfolios/{id}/track
```

### SSE（分析流式）
```
POST   /api/analyze/stream
  body: AnalyzeRequest
  response: text/event-stream
    data: {type:"step", step: AnalysisStep}
    data: {type:"compaction", snapshot: ContextSnapshot}
    data: {type:"done", pathId: "..."}
```

每个 `AnalysisStep`（含 thought/toolCall）实时推送，前端流式渲染步骤树。压缩事件单独推送，前端显示"已压缩 N→M tokens"。

## 10. 多市场

`realm` 贯穿：AnalyseRequest.realm → 工具按 realm 选提供方 → AnalysisPath 存 realm。A股/ETF 的差异封装在**数据工具提供方**和**指标计算**里，编排层/supervisor/子agent 不感知市场细节。

## 11. 技术栈（已拍板）

> 完整选型理由、目录结构、依赖清单见 [技术选型](abq-platform-tech-stack.md)。

- **Python 3.12 + FastAPI**：数据分析生态（pandas/numpy/baostock/akshare）无可替代；异步+SSE 原生支持
- **LangGraph**：单票编排引擎（`app/orchestration/graphs/single_ticket.py`；SSE 走 `stream_single_ticket_pipeline`）
- **纯文件存储**：JSON/YAML，无数据库（见 §7）
- **子agent 结构化人设**：persona + instructions + variables，对齐提示词库
- **流式第一天**：SSE（`sse-starlette`），逐 step 推送
- **LLM**：`openai` SDK + `LlmRouter`（primary API / local OpenAI 兼容端点）

### 已拍板的决策记录
| 决策 | 选择 |
|---|---|
| 数据获取 | 完全重写为工具形式，不碰 abq 代码 |
| 编排引擎 | LangGraph `StateGraph`（`stream_single_ticket_pipeline` 增量 SSE；`get_single_ticket_graph()` 批量） |
| 流式 | 第一天就要（SSE） |
| 子agent人设 | 结构化（persona+instructions+variables） |
| 多模型 | primary（商用 API：DeepSeek/小米/Minimax）+ local（OpenAI 兼容自部署）；`LlmRouter` 按 tier 路由 |
| 持久化 | 纯 JSON/YAML 文件，无数据库 |

## 12. 实施分期（与前端对齐）

| 阶段 | 状态 | 后端 | 前端联动 |
|---|---|---|---|
| P0 | ✅ | FastAPI 骨架 + LLM 适配 seam + **LlmRouter（primary/local 两路）** | shell + 顶栏模型状态 |
| P1 | ✅ MVP | agent loop + step emitter + 持久化（文件 JSON） | 路径记录 + SSE 步骤卡片 + 会话列表 |
| P2 | ✅ MVP | 单票 pipeline + 工具层（clean/calc/akshare）+ 三视角并行 + judge 收口 | 步骤树展示 agent 中文名 |
| P2b | ✅ MVP | **local tier**：extract（长工具输出摘要）+ format（JSON 合同修复） | composer 主模型选择；工作流 tier 列 |
| P3 | ✅ MVP | `CompactionEngine` + `data/paths/{id}/context/snapshot-*.json` + SSE `compaction` | `ContextPage` 指标卡 + 双栏；`CompactionBanner` + 单票摘要面板 |
| P4 | ✅ MVP | 三库 CRUD（`library_store` + `api/prompts` / `api/agents` / `api/tools`） | 侧栏「库」四 Tab + 编辑弹窗 |
| P4+ | ✅ MVP | 组合路由 `compose_route` + 续聊 `focus` meta + `resolve_view_agent_ids` | composer 路由提示 + 工作流并行泳道 |
| P5a/b | ✅ MVP | **因子库**：FactorExpr + 22 种子 + `/api/factors` + 评测 | 库页第四 Tab |
| P5c | ✅ MVP | **LLM 挖掘**：提议 → 解析 IR → 同一套准入；`runs/{id}` 进度 | 库页挖掘面板 + 闸门详情 |
| P5d | ✅ MVP | **GP 轨 A**：gplearn 大盘择时；`mine/gp?track=market` | 库页 GP 轨 A |
| P5e | ✅ MVP | **GP 轨 B**：截面树 GP + 日度 Rank IC；`mine/gp?track=cs` | 库页 GP 轨 B |
| P5g | ✅ MVP | 单票 `attach_factors` + 因子 ReAct 工具 + `reports.factor_summary` | 单票摘要面板因子区块 |
| P5f | ✅ MVP | `synth.py` equal/ic/ic_ir + Gate 5 纸面 | 库页因子合成 |
| P5 大盘 | ✅ MVP | `kind=market` → `graphs/market.py` | composer 自动识别大盘意图 |
| P5 选组 | ⬜ | 组合跟踪 | 选组 pipeline |
| P6 | ⬜ | ETF realm 工具提供方 | ETF 支持 |

### 已落地模块（代码索引）

| 模块 | 路径 | 备注 |
|---|---|---|
| SSE 分析流 | `app/api/analyze.py` → `app/orchestration/analyze_stream.py` | 新建会话取消孤儿 run；`touch_activity` 防误标 stale |
| ReAct 循环 | `app/orchestration/agent_loop.py` | LangChain `ChatOpenAI` + `bind_tools`；长工具输出经 `compact_tool_output`（ReAct 路径） |
| 单票编排 | `app/orchestration/graphs/single_ticket.py` | LangGraph 对齐；`_stream_phase_update` 各阶段增量 SSE |
| 取数加速 | `app/orchestration/tool_output.py` | pipeline 数据工具仅 truncate，不走 extract LLM |
| 系统提示词 | `app/prompts/` + `data/agents/` + `data/prompts/` | identity/safety 组装 + YAML 种子 |
| 三库持久化 | `app/persistence/library_store.py` | Agent/Prompt CRUD；校验禁词、变量、工具引用 |
| 三库 API | `app/api/agents.py`, `prompts.py`, `tools.py` | `GET/POST/PUT/DELETE`；内置 id 保护 |
| 组合路由 | `app/orchestration/compose_route.py`, `app/api/compose.py` | 规则路由 → `agent_ids` / `prompt_id` / `enable_debate` |
| 因子库 | `app/factors/` + `app/api/factors.py` | FactorExpr、评测、LLM/GP 挖掘（`mine_gp.py` / `mine_gp_cs.py`）、`attach.py`、`agent_tools.py` |
| 因子挂载 | `app/factors/attach.py`, `graphs/single_ticket.py` | 数据阶段后写 `factor_summary` |
| 因子 agent 工具 | `app/tools/langchain_tools.py` | `list_factors` / `compute_factor` / `factor_analysis` |
| OHLCV | `app/data/ohlcv.py` | qlib 本地 + 远程补洞 |
| 远程行情 | `app/data/market_quotes.py` | 移植 abq `quotes.py`（腾讯/东财） |
| baostock 补洞 | `app/data/baostock_daily.py` | 移植 abq `fetch_baostock` |
| qlib 本地 | `app/data/qlib_store.py` | factor 还原人民币价 |
| 基本面/舆情 | `app/data/fundamentals.py`, `sentiment.py` | akshare |
| 指标工具 | `app/data/bar_processing.py` | `clean_data` / `calc_indicator` |
| 工具注册 | `app/tools/registry.py` | OpenAI function schema |
| 路径持久化 | `app/persistence/paths.py` | `data/paths/{id}/steps/*.json` |
| 上下文压缩 | `app/context/compaction.py`, `tokens.py` | 阈值 3500 token / ≥6 步；local LLM + 规则回退 |
| 压缩快照 | `data/paths/{id}/context/snapshot-*.json` | `GET /api/paths/{id}` 返回 `snapshots` |
| LLM 路由 | `app/llm/router.py`, `langchain_client.py`, `chat.py` | LangChain `ChatOpenAI`；`.env` primary/local |

**P4+ 已落地**：规则组合路由（`POST /api/compose/route`）、续聊 `focus` 写入 path meta、工作流三视角/辩论并行泳道。`prompt_id` 路由结果已注入对应视角 agent 的提示词加载。

**P5 已落地**：因子库（P5a/b）+ LLM 挖掘（P5c）+ GP 双轨（P5d 大盘 / P5e 截面）+ 合成与纸面（P5f）+ 单票挂载与 agent 因子工具（P5g）。
