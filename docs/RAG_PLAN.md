# ABQ Lab 记忆与 RAG 方案

> 版本：2026-08-27 · 状态：**R0–R2 已落地**；R3 图谱扩展见 [KNOWLEDGE_GRAPH_PLAN.md](./KNOWLEDGE_GRAPH_PLAN.md)  
> 关联：[DESIGN.md](./DESIGN.md) · [USER_GUIDE.md](./USER_GUIDE.md) · [KNOWLEDGE_GRAPH_PLAN.md](./KNOWLEDGE_GRAPH_PLAN.md)（R3 图谱扩展）

---

## 1. 背景与目标

### 1.1 现状

ABQ Lab 已具备：

- **过程全量落盘**：`data/paths/{id}/steps/*.json`、reports、ContextSnapshot
- **同会话压缩**：`CompactionEngine`（默认阈值 **128k token**，`CONTEXT_COMPACT_THRESHOLD_TOKENS`）+ judge-only 续聊
- **工具实时取数**：行情、舆情、大盘宽度、因子等经 `langchain_tools` 当次拉取
- **文件持久化**：JSON/YAML，无数据库

缺口：

| 场景 | 现状 | 痛点 |
|---|---|---|
| 跨会话追问 | 仅能按时间浏览 SessionList | 「两周前对 600519 的风险判断是什么？」无法语义检索 |
| 舆情/大盘增量 | 工具当次返回，分析结束即蒸发 | 无法回答「近 7 天舆情主题是否转向」 |
| 政策/研报 | 无入库流水线 | 无法做监管文件语义检索 |
| 长会话内 | Compaction 已覆盖 | 无需额外向量库 |

### 1.2 目标

在不破坏「**过程全量落盘 ≠ 模型全量可见**」原则的前提下，新增两层能力：

1. **会话记忆（Episodic）**：跨 path 检索历史研判摘要
2. **领域知识库（Semantic KB）**：舆情、大盘快照、政策文档的归档与增量分析

### 1.3 非目标

- 不用 RAG 替代行情/因子/OHLCV 工具取数（数字必须来自确定性工具）
- 不把 `data/paths/*.json` 当语料塞进 Document Loader（破坏回放与 schema）
- 不引入 PostgreSQL / Redis（保持单用户文件持久化主线）
- 不在分析 SSE 热路径同步调用 embedding（避免与 local chat 抢 GPU）

---

## 2. 设计原则

| 原则 | 说明 |
|---|---|
| **结构化优先** | 能按 `symbol/kind/date` 过滤的，先走 metadata，再走向量 |
| **摘要入库** | 只 embed judge 结论、新闻标题、政策 chunk，不 embed 全量 step |
| **异步归档** | 分析结束后后台 queue 写入 jsonl + 可选向量索引 |
| **双轨分库** | 会话记忆与领域知识 namespace 分离，工具分开暴露 |
| **可降级** | `EMBEDDING_ENABLED=false` 时 R0 结构化检索仍可用 |
| **可审计** | 检索结果必须带 `path_id` / `source` / `ts`，可回跳原文 |

---

## 3. 总体架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│ 热路径（分析 SSE，无 embedding）                                          │
│  User → analyze_stream → compose_route → pipeline → tools → agents      │
│                              ↓                                          │
│                        path_store（steps + reports + snapshot）          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    分析结束 / 工具返回（异步，不阻塞 SSE）
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 温路径（归档 + 可选 embedding）                                         │
│  knowledge_archiver → data/knowledge/**/*.jsonl（事件日志，主事实源）    │
│  embed_queue        → Ollama qwen3-embedding:8b @1024d                  │
│                     → data/memory.db（SqliteStore 向量 + KV）            │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                              agent 按需检索
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 冷路径（外部文档入库，R2）                                               │
│  PDF/HTML/Markdown → langchain-community Loader → Splitter → embed      │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.1 与现有层次关系

```
┌─────────────────────────────────────────────────────────────┐
│ 前端 (React)                                                 │
├─────────────────────────────────────────────────────────────┤
│ API 层 — 新增 /api/knowledge/*、/api/memory/search           │
├─────────────────────────────────────────────────────────────┤
│ 编排层 — supervisor 可路由到记忆/知识工具                     │
├─────────────────────────────────────────────────────────────┤
│ 工具层 — search_prior_analysis / search_knowledge /          │
│          get_knowledge_delta                                 │
├─────────────────────────────────────────────────────────────┤
│ 上下文层 — CompactionEngine（同会话）+ MemoryStore（跨会话）  │
├─────────────────────────────────────────────────────────────┤
│ 持久层 — paths（不变）+ knowledge（jsonl）+ memory.db（新增） │
├─────────────────────────────────────────────────────────────┤
│ LLM 层 — LlmRouter（chat）+ EmbeddingClient（旁路）          │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. 三层存储分工

| 层 | 路径 | 内容 | Loader | Embedding |
|---|---|---|---|---|
| **过程层** | `data/paths/{id}/` | steps、reports、snapshot、meta | ❌ 直读 JSON | ❌ |
| **事件层** | `data/knowledge/` | 舆情/宽度/政策抓取记录（jsonl） | ❌ 自写 append | ⚠️ 仅标题+摘要 |
| **记忆层** | `data/memory.db` | 可检索摘要、政策 chunk、episodic | ❌ SqliteStore API | ✅ |

### 4.1 目录结构

```
data/
├── paths/                          # 不变
│   ├── _index.json
│   └── {path_id}/
│       ├── meta.json               # 扩展 judge 摘要字段
│       ├── steps/
│       ├── reports.json
│       └── snapshot.json
├── knowledge/                      # 新增：事件日志（主事实源）
│   ├── by_symbol/
│   │   └── sh600519/
│   │       ├── sentiment.jsonl
│   │       └── analysis_refs.jsonl
│   ├── by_theme/
│   │   └── 新能源/
│   │       └── sector_pulse.jsonl
│   ├── market/
│   │   └── breadth.jsonl
│   └── policy/
│       ├── manifest.json           # 文档清单
│       └── chunks.jsonl            # 切块元数据（正文在 memory.db）
├── agents/                         # 不变
├── prompts/                        # 不变
├── factors/                        # 不变
├── portfolios/                     # 不变
└── memory.db                       # 新增：SqliteStore（KV + 向量）
```

### 4.2 事件日志记录格式

```json
{
  "id": "evt_a1b2c3",
  "ts": "2026-08-26T02:15:00Z",
  "type": "sentiment",
  "symbol": "sh600519",
  "source": "akshare",
  "path_id": "abc123def456",
  "payload_hash": "sha256:…",
  "headlines": [
    {"title": "…", "time": "2026-08-26 10:00", "url": "…"}
  ],
  "summary": "共 8 条，最新关注业绩与渠道价"
}
```

```json
{
  "id": "evt_mkt001",
  "ts": "2026-08-26T02:15:00Z",
  "type": "breadth",
  "source": "akshare",
  "path_id": "abc123def456",
  "metrics": {
    "advance": 3200,
    "decline": 1800,
    "unchanged": 120,
    "advance_ratio": 0.62,
    "limit_up_count": 45
  },
  "summary": "上涨家数 3200，宽度偏强，涨停 45 家"
}
```

### 4.3 Path Meta 扩展

`AnalysisPathIndexEntry` / `meta.json` 新增字段（R0）：

```json
{
  "id": "abc123def456",
  "kind": "single",
  "target": "sh600519",
  "symbols": ["sh600519"],
  "judge_stance": "observe",
  "judge_one_liner": "缩量回调至均线附近，观望为主",
  "data_as_of": "2026-08-25",
  "tags": ["量价", "白酒"]
}
```

---

## 5. LangChain Loader / Parser 策略

参考 [LangChain 入门指南](https://langchain.cadn.net.cn/python/docs/how_to/index.html)。

### 5.1 不使用 Loader 的场景

| 数据 | 读写方式 | 原因 |
|---|---|---|
| `path_store` steps/reports | `json.load` + Pydantic | 强 schema、可回放、可 diff |
| agents / prompts / factors | `yaml.safe_load` + `LibraryStore` | 已有校验与 CRUD |
| portfolios | `portfolio_store` | 结构化业务对象 |

### 5.2 使用 Loader 的场景（R2）

| 来源 | Loader | Splitter | 用途 |
|---|---|---|---|
| 政策 PDF | `PyPDFLoader` | `RecursiveCharacterTextSplitter` | 监管文件库 |
| 财经网页 | `WebBaseLoader` 或自研抓取 | 按段落 | 研报归档 |
| 本地 Markdown | `DirectoryLoader` + `UnstructuredMarkdownLoader` | 按标题 | 研究笔记 |

流水线：

```
Loader → Document(page_content, metadata)
      → Splitter(chunk_size=512, overlap=64)
      → metadata 补全 {symbol, theme, source, published_at}
      → embed → SqliteStore namespace ("knowledge", "policy")
```

### 5.3 Output Parser

现有 `format` / `extract` local agent 已承担 JSON 修复与长输出摘要。RAG 阶段**不强制**引入 LangChain Output Parser；若后续因子路由、记忆抽取需固定 schema，可在 `app/memory/extractors.py` 局部使用 `PydanticOutputParser`。

---

## 6. Embedding 模型方案

### 6.1 选型：`qwen3-embedding:8b`（本地 Ollama）

| 维度 | 评估 |
|---|---|
| 检索质量 | 开源 embedding 第一梯队（MTEB Multilingual ~70.58） |
| 中文/A 股 | 100+ 语言，新闻标题、政策表述表现好 |
| 上下文 | 32k，政策段落不必过碎 |
| 单用户规模 | 万级 chunk 绰绰有余 |
| 资源 | 量化约 6–8GB；与 local chat 可能抢 GPU |

**结论：能力完全够用，甚至过剩。** 工程上通过 **降维 + 异步** 控制成本。

### 6.2 推荐运行配置

```bash
ollama pull qwen3-embedding:8b
ollama pull qwen3-reranker:0.6b   # 可选，top-k 重排
```

| 参数 | 推荐值 | 说明 |
|---|---|---|
| `EMBEDDING_MODEL` | `qwen3-embedding:8b` | Ollama 模型名 |
| `EMBEDDING_DIMENSIONS` | `1024` | MRL 截断，索引体积约为 4096 的 1/4 |
| `EMBEDDING_BATCH_SIZE` | `16` | 后台批量 embed |
| `RERANKER_MODEL` | `qwen3-reranker:0.6b` | 可选；对 top-20 重排至 top-5 |

资源紧张时的降级顺序：

1. 保持 8B，仅后台 embed，分析时不并发
2. 维度降至 `512`
3. 换 `qwen3-embedding:4b` 或 `0.6b`

### 6.3 接入方式

与 `LlmRouter`（primary/local chat）**旁路**，新增 `EmbeddingClient`：

```python
# app/llm/embedding_client.py（规划）
from langchain_community.embeddings import OllamaEmbeddings

class EmbeddingClient:
    def __init__(self, base_url: str, model: str, dimensions: int): ...

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_query(self, text: str) -> list[float]: ...
```

SqliteStore 索引配置：

```python
from langgraph.store.sqlite import AsyncSqliteStore

index = {
    "dims": 1024,
    "embed": embedding_client,  # LangChain Embeddings 兼容
    "fields": ["text"],
}
```

### 6.4 什么文本需要 Embedding

| 类型 | 来源 | 是否 embed | 典型长度 |
|---|---|---|---|
| judge 研判摘要 | reports / meta | ✅ | 200–500 字 |
| ContextSnapshot.summary | snapshot.json | ✅ | 100–300 字 |
| 舆情标题+摘要 | sentiment jsonl | ✅ | 50–100 字/条 |
| 大盘宽度一句话 | breadth jsonl | ✅ | ~80 字 |
| 政策 chunk | PDF splitter | ✅ | ~512 token |
| 原始 OHLCV / 因子矩阵 | 工具输出 | ❌ | — |
| 完整 agent step 正文 | steps/*.json | ❌ | — |

---

## 7. 两条 RAG 线

### 7.1 A 线：会话历史检索（Episodic Memory）

**回答的问题：**

- 「上次对这只票的研判立场是什么？」
- 「近一个月大盘研判和今天宽度是否一致？」
- 「组合诊断里成员强弱是否反转？」

**数据流：**

```
分析结束
  → 解析 judge report（stance / one_liner / symbols）
  → 写入 path meta（结构化，R0 即可检索）
  → 异步 MemStore.put(("paths", symbol), path_id, record, index=True)
```

**检索策略（混合）：**

```
1. metadata 过滤：symbol + kind + date_range
2. 向量相似：query ↔ judge_one_liner（R1）
3. 可选 rerank：top-20 → qwen3-reranker → top-5
```

**与 CompactionEngine 关系：**

| 机制 | 范围 | 作用 |
|---|---|---|
| `CompactionEngine` | 同 path 内 | 压缩 steps → ContextSnapshot |
| Episodic Memory | 跨 path | 检索历史研判摘要 |

二者互补，不互相替代。

**Namespace 设计：**

```
("paths", "{symbol}")     # 单票历史研判
("paths", "market")       # 大盘研判
("paths", "portfolio")    # 组合诊断
```

### 7.2 B 线：领域知识库（Semantic KB）

**回答的问题：**

- 「这只票近 7 天舆情主题是否从业绩转向监管？」
- 「上次宽度上涨家数 3200，今天多少？变化说明什么？」
- 「同主题政策一周内是否重复出现？」

**B1 — 事件日志 + 规则增量（R0，无 embedding）**

工具返回后 `knowledge_archiver.append()`：

- `fetch_sentiment` → `by_symbol/{sym}/sentiment.jsonl`
- `fetch_market_breadth` → `market/breadth.jsonl`
- `fetch_sector_pulse` → `by_theme/{theme}/sector_pulse.jsonl`

`get_knowledge_delta(symbol, type, since=7d)`：

- 对比两次快照：新标题、消失主题、情绪词变化
- 输出结构化 diff + 一句话摘要（可走 local 小模型）

**B2 — 语义检索（R1）**

归档时 embed 标题/摘要 → SqliteStore：

```
namespace: ("knowledge", "sentiment", "{symbol}")
namespace: ("knowledge", "breadth", "market")
namespace: ("knowledge", "policy")
```

**B3 — 政策文档流水线（R2）**

```
用户上传 PDF / 指定 URL
  → Loader + Splitter
  → manifest.json 登记
  → embed chunks → memory.db
  → search_knowledge(query, filters={type: policy})
```

> **R3 扩展（已落地）**：官网定时采集、URL 白名单入库、政策节点入图谱、月 Rollup，见 [KNOWLEDGE_GRAPH_PLAN.md](./KNOWLEDGE_GRAPH_PLAN.md)。

---

## 8. 开源组件引入清单

### 8.1 引入

```toml
# backend/pyproject.toml 规划新增
"langmem>=0.1",
"langgraph-checkpoint-sqlite>=2.0",
"langchain-community>=0.3",
"langchain-text-splitters>=0.3",
```

| 组件 | 用途 | 说明 |
|---|---|---|
| [LangMem](https://github.com/langchain-ai/langmem) | episodic 抽取、memory tools | 与 LangGraph 同源；R2 接入 |
| [LangGraph SqliteStore](https://github.com/langchain-ai/langgraph/tree/main/libs/checkpoint-sqlite) | 单文件 KV + 向量 | 替代 Postgres / Chroma |
| langchain-community | PDF/HTML Loader | 仅外部文档 |
| langchain-text-splitters | 文档切块 | 配合 Loader |

### 8.2 不引入

| 组件 | 原因 |
|---|---|
| Mem0 | 与 LangMem + SqliteStore 能力重叠 |
| Chroma | 与 SqliteStore 向量功能重复 |
| PostgreSQL / Redis | 违背单用户文件持久化主线 |
| LlamaIndex | 已有 LangChain，避免双栈 |
| 整仓 FundAI / StockAnal_Sys | 架构差异大，只借鉴模式 |

### 8.3 参考源码（只读片段）

| 项目 | 借鉴点 |
|---|---|
| [U2INVEST](https://github.com/DasbootU9607/U2INVEST-Your-Stocks-You-To-Invest) | AkShare + Chroma RAG 流水线、`vector_store.py` |
| [FundAI](https://github.com/light-misty/FundAI) | FastAPI + SSE + 多 agent 事件模型 |
| [StockAnal_Sys](https://github.com/lc2panda/StockAnal_Sys) | A 股 agent 划分、舆情多源降级 |
| [LangGraph-Finance-Agent](https://github.com/NachiketaAnand/LangGraph-Finance-Agent) | `rag.py` 最小文档入库范例 |
| [LangMem episodic guide](https://langchain-ai.github.io/langmem/guides/extract_episodic_memories/) | Episode schema + 后台抽取 |

---

## 9. 模块设计

### 9.1 新增后端模块

```
backend/app/
├── knowledge/
│   ├── __init__.py
│   ├── archiver.py          # jsonl append；payload_hash 去重
│   ├── delta.py             # get_knowledge_delta 规则 diff
│   ├── ingest.py            # R2: Loader + Splitter 流水线
│   └── models.py            # KnowledgeEvent, DeltaResult
├── memory/
│   ├── __init__.py
│   ├── store.py             # SqliteStore 封装；namespace 常量
│   ├── embed_queue.py       # 异步批量 embed（asyncio.Queue）
│   ├── extractors.py        # 从 judge report / snapshot 抽摘要
│   └── search.py            # 混合检索：metadata + vector + rerank
├── llm/
│   └── embedding_client.py  # Ollama qwen3-embedding 封装
└── api/
    ├── knowledge.py         # GET /api/knowledge/delta, /search
    └── memory.py            # GET /api/memory/search, POST /reindex
```

### 9.2 工具注册（`langchain_tools.py`）

| 工具名 | 阶段 | 说明 |
|---|---|---|
| `search_prior_analysis` | R0 | symbol/kind/date 结构化检索历史 path 摘要 |
| `get_knowledge_delta` | R0 | 舆情/宽度 jsonl 规则增量 diff |
| `search_knowledge` | R1 | 向量 + metadata 混合检索知识库 |
| `ingest_policy_document` | R2 | 上传/URL 政策文档入库 |

工具返回格式（统一）：

```json
{
  "status": "ok",
  "hits": [
    {
      "text": "…",
      "score": 0.87,
      "source": "path",
      "path_id": "abc123",
      "ts": "2026-08-20T…",
      "metadata": {}
    }
  ],
  "summary": "检索到 3 条相关记录"
}
```

### 9.3 编排挂载点

| 文件 | 改动 |
|---|---|
| `analyze_stream.py` | 分析 `done` 后 `asyncio.create_task(archive_and_index(path_id))` |
| `graphs/single_ticket.py` | data 阶段 sentiment 返回后 archiver |
| `graphs/market.py` | breadth 返回后 archiver |
| `agent_loop.py` | sentiment/market agent 可 bind `search_knowledge` |
| `compose_route.py` | 意图含「上次/对比/近一周」时提示 supervisor 优先记忆工具 |

### 9.4 Agent 使用约束

- **supervisor / judge**：可调用 `search_prior_analysis`、`get_knowledge_delta`
- **sentiment / market agent**：可调用 `search_knowledge`（舆情/政策）
- **data 阶段工具**：只写归档，不读向量库（避免循环）
- 检索结果注入 prompt 时必须带 **来源标注**，judge 输出需区分「本次工具数据」与「历史记忆」

---

## 10. API 设计

### 10.1 REST

```
GET  /api/paths/search
     ?symbol=sh600519&kind=single&since=2026-08-01&limit=10
     → 结构化历史研判列表（R0）

GET  /api/knowledge/delta
     ?symbol=sh600519&type=sentiment&since_days=7
     → 规则增量 diff（R0）

GET  /api/knowledge/events
     ?symbol=sh600519&type=sentiment&limit=50
     → jsonl 事件只读（调试/前端）

GET  /api/memory/search
     ?q=茅台渠道价&namespace=knowledge&symbol=sh600519&limit=5
     → 向量检索（R1）

POST /api/memory/reindex
     body: { "scope": "paths" | "knowledge" | "all" }
     → 全量重建向量索引（运维）

GET  /api/llm/health
     → 扩展 embedding: { ok, model, dimensions }（R1）

POST /api/knowledge/ingest          # R2
     multipart: file=policy.pdf, metadata={...}
```

### 10.2 配置项（`.env`）

```bash
# Embedding（R1）
EMBEDDING_ENABLED=true
EMBEDDING_BASE_URL=http://127.0.0.1:11434
EMBEDDING_MODEL=qwen3-embedding:8b
EMBEDDING_DIMENSIONS=1024
EMBEDDING_BATCH_SIZE=16

# Reranker（可选）
RERANKER_ENABLED=false
RERANKER_MODEL=qwen3-reranker:0.6b

# Memory store
MEMORY_DB_PATH=data/memory.db

# Knowledge archiver
KNOWLEDGE_ARCHIVE_ENABLED=true
KNOWLEDGE_DEDUP_BY_HASH=true
```

---

## 11. 分阶段实施

### R0 — 结构化记忆（1–2 周，无 embedding）

**目标**：跨会话「找得到」、舆情/宽度「留得住」、增量「算得出」。

| 任务 | 交付物 |
|---|---|
| Path meta 扩展 | `judge_stance`, `judge_one_liner`, `symbols`, `data_as_of` |
| judge 结束写 meta | `extractors.py` 解析 reports.json |
| `knowledge_archiver` | sentiment / breadth jsonl append + hash 去重 |
| `get_knowledge_delta` | 规则 diff 工具 + API |
| `search_prior_analysis` | metadata 检索工具 + `GET /api/paths/search` |
| 单测 | archiver、delta、path search |

**验收：**

1. 单票分析结束后 `data/knowledge/by_symbol/sh600519/sentiment.jsonl` 有新行
2. `GET /api/paths/search?symbol=sh600519` 返回按时间排序的历史摘要
3. `get_knowledge_delta(since=7d)` 能列出新增标题
4. `EMBEDDING_ENABLED=false` 时全流程正常

### R1 — 向量检索（2–3 周）

**目标**：语义相似检索、跨主题关联。

| 任务 | 交付物 |
|---|---|
| `EmbeddingClient` | Ollama qwen3-embedding @1024d |
| `memory/store.py` | SqliteStore 封装 + namespace |
| `embed_queue` | 分析结束后异步 bulk embed |
| `memory/search.py` | metadata 过滤 + vector + 可选 rerank |
| `search_knowledge` 工具 | agent 可调用 |
| health 扩展 | `/api/llm/health` 含 embedding |
| CLI | `abq-api memory reindex` |
| 单测 | embed mock、search 混合逻辑 |

**验收：**

1. `search_knowledge("茅台渠道价")` 返回相关舆情摘要且带 `ts/source`
2. `search_prior_analysis("缩量回调观望")` 语义命中历史 judge 摘要
3. 分析 SSE 延迟不受 embedding 影响（embed 在 done 之后）
4. `memory.db` 可删除后 `reindex` 重建

### R2 — 政策库与 Episodic（2026-08-26 已落地）

| 任务 | 状态 |
|---|---|
| `knowledge/ingest.py` PDF/MD/TXT 切块入库 | ✅ |
| `POST /api/knowledge/ingest` | ✅ |
| `ingest_policy_text` / `search_episodes` 工具 | ✅ |
| Episodic 抽取（local LLM + 规则回退） | ✅ |
| Agent 挂载记忆工具 | ✅ |
| 库页「知识库」Tab | ✅ |
| `abq-memory reindex` CLI | ✅ |

### R2 — LangMem（暂缓）

改用轻量 `memory/episodic.py`，不引入 LangMem 依赖。


---

## 12. 检索流程详图

### 12.1 search_prior_analysis

```
输入: { query?, symbol, kind?, since?, limit=5 }

Step 1  metadata 过滤
        paths._index + meta.json
        WHERE symbol IN symbols AND kind = kind AND updated >= since

Step 2  (R1) 向量检索
        MemStore.search(("paths", symbol), query, limit=20)

Step 3  (R1, 可选) rerank
        qwen3-reranker: top-20 → top-5

Step 4  合并去重，按 score + recency 排序

输出: hits[{ path_id, judge_one_liner, stance, ts, score }]
```

### 12.2 get_knowledge_delta

```
输入: { symbol, type, since_days=7 }

Step 1  读取 jsonl，过滤 ts >= since

Step 2  若记录 < 2：返回「数据不足」

Step 3  规则 diff
        - 新标题集合 minus 旧标题集合
        - 关键词频变化（业绩/监管/回购…）
        - 数值型（breadth advance_ratio 变化）

Step 4  (可选) local 小模型生成一句话摘要

输出: { new_items, removed_items, metric_changes, summary }
```

### 12.3 search_knowledge

```
输入: { query, symbol?, type?, since?, limit=5 }

Step 1  确定 namespace
        ("knowledge", type, symbol?) 或 ("knowledge", "policy")

Step 2  metadata 预过滤（symbol, ts）

Step 3  MemStore.search(namespace, query, limit=20)

Step 4  rerank → top-5

Step 5  每条 hit 附 jsonl 原始事件 id（可审计）

输出: hits[{ text, score, source, event_id, ts }]
```

---

## 13. 运维与风险

### 13.1 运维

| 操作 | 命令/方式 |
|---|---|
| 查看事件日志 | 直接读 `data/knowledge/**/*.jsonl` |
| 重建向量索引 | `POST /api/memory/reindex` |
| 关闭 embedding | `EMBEDDING_ENABLED=false`（回退 R0） |
| 备份 | 复制 `data/knowledge/` + `data/memory.db` |
| 磁盘估算 | 1 万条 × 1024 维 ≈ 40MB（向量）+ jsonl 文本 |

### 13.2 风险与缓解

| 风险 | 缓解 |
|---|---|
| embedding 与 chat 抢 GPU | 仅 done 后异步 embed；可配 `EMBED_CONCURRENCY=1` |
| 舆情重复入库 | `payload_hash` 去重 |
| 检索幻觉 | 工具返回必须带 source；judge prompt 区分历史 vs 本次 |
| jsonl 无限增长 | 按月 rotate（`sentiment.2026-08.jsonl`）；R2 再加 compaction |
| SqliteStore 损坏 | 可从 jsonl + path meta 全量 reindex |
| 8B embedding 过重 | 降维 512 或换 4B/0.6B |

### 13.3 隐私与安全

- 单用户本地部署，数据不出机
- 若未来多用户：namespace 加 `user_id`；memory.db 按用户分文件
- 政策 PDF 入库前扫描路径，禁止任意 URL SSRF（R2 白名单域名）

---

## 14. 前端规划（R2 可选）

| 页面 | 功能 |
|---|---|
| 上下文页 | 增加「跨会话记忆命中」展示（本次分析调用了哪些历史摘要） |
| 对话页 | composer 提示「将检索历史研判」 |
| 库页 · 知识 Tab | 事件日志浏览、政策文档上传、**图谱探索**、reindex 按钮 |

R0/R1 可仅后端 + agent 工具验证，不强制前端。

---

## 15. 测试策略

```
tests/
├── test_knowledge_archiver.py    # append、dedup、rotate
├── test_knowledge_delta.py       # sentiment/breadth diff
├── test_path_search.py           # metadata 检索
├── test_memory_store.py          # SqliteStore put/search（mock embed）
├── test_memory_search.py         # 混合检索 + rerank mock
└── test_embed_queue.py           # 异步队列不阻塞
```

集成验收脚本（手动）：

```bash
# 1. 跑一次单票分析
# 2. 检查 jsonl
cat data/knowledge/by_symbol/sh600519/sentiment.jsonl | tail -1
# 3. 结构化检索
curl "http://127.0.0.1:8000/api/paths/search?symbol=sh600519"
# 4. (R1) 向量检索
curl "http://127.0.0.1:8000/api/memory/search?q=渠道价&symbol=sh600519"
# 5. (R3) 图谱子图
curl "http://127.0.0.1:8000/api/graph/subgraph?center=sh600519&hops=1"
```

---

## 16. 里程碑与文档更新

| 阶段 | README 进度行 | DESIGN.md |
|---|---|---|
| R0 | P6a 结构化记忆 + 知识归档 | § 持久层扩展 knowledge |
| R1 | P6b 本地 embedding + 向量检索 | § MemoryStore |
| R2 | P6c 政策库 + LangMem | § 政策入库 |
| R3 | 知识图谱 + 政策定时采集 | 见 [KNOWLEDGE_GRAPH_PLAN.md](./KNOWLEDGE_GRAPH_PLAN.md) |

---

## 17. 决策摘要

| 问题 | 决策 |
|---|---|
| 文件持久化用 Loader 吗？ | **应用状态不用**；仅外部 PDF/HTML/Markdown 用 Loader |
| 需要 embedding 吗？ | **R0 不需要**；R1 起用本地 `qwen3-embedding:8b` @1024d |
| 8B 够吗？ | **够，且过剩**；注意异步与降维 |
| 向量库选型？ | **SqliteStore**（`data/memory.db`），不引入 Chroma/Postgres |
| 开源引入？ | **LangMem + langgraph-checkpoint-sqlite + langchain-community** |
| 两条 RAG 线？ | **A 会话记忆（paths）+ B 领域知识（knowledge）**，分 namespace、分工具 |
| 先做啥？ | **R0**：path meta + jsonl 归档 + 结构化检索 + delta |

---

## 附录 A：Namespace 一览

| Namespace | 用途 | 典型 key |
|---|---|---|
| `("paths", "{symbol}")` | 单票历史研判 | `path_id` |
| `("paths", "market")` | 大盘研判 | `path_id` |
| `("paths", "portfolio")` | 组合诊断 | `path_id` |
| `("knowledge", "sentiment", "{symbol}")` | 舆情摘要 | `event_id` |
| `("knowledge", "breadth", "market")` | 大盘宽度 | `event_id` |
| `("knowledge", "policy")` | 政策 chunk | `chunk_id` |

## 附录 B：依赖版本（规划）

```toml
[project]
dependencies = [
  # 现有依赖不变 …
  "langmem>=0.1",
  "langgraph-checkpoint-sqlite>=2.0",
  "langchain-community>=0.3",
  "langchain-text-splitters>=0.3",
]
```

## 附录 C：参考链接

- [LangChain 入门指南（中文）](https://langchain.cadn.net.cn/python/docs/how_to/index.html)
- [Qwen3-Embedding-8B](https://huggingface.co/Qwen/Qwen3-Embedding-8B)
- [LangMem GitHub](https://github.com/langchain-ai/langmem)
- [LangGraph SqliteStore](https://github.com/langchain-ai/langgraph/tree/main/libs/checkpoint-sqlite)
