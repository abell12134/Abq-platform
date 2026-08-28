# ABQ Lab 知识图谱与政策采集方案

> 版本：2026-08-27 · 状态：**R3.6 已落地**（骨架、样本同步、公告、政策 URL/列表、市场层、板块 Rollup、三元组抽取、月度维护、库页力导向图）  
> 存储：`data/graph/graph.db`（SQLite，非 Kuzu）  
> 关联：[RAG_PLAN.md](./RAG_PLAN.md) · [DESIGN.md](./DESIGN.md) · [USER_GUIDE.md](./USER_GUIDE.md)

---

## 1. 背景与目标

### 1.1 现状

ABQ Lab 已完成 P6 知识库基础能力（见 [RAG_PLAN.md](./RAG_PLAN.md)）：

| 能力 | 模块 | 状态 |
|---|---|---|
| 舆情/宽度事件归档 | `knowledge/archiver.py` → `data/knowledge/**/*.jsonl` | ✅ |
| 规则增量 diff | `get_knowledge_delta` | ✅ |
| 政策文档入库 | `knowledge/ingest.py`（PDF/MD/TXT + 对话粘贴） | ✅ |
| 语义检索 | `search_knowledge` + `memory.db` | ✅ |
| 中证300成分股 | `factors/universe.py` | ✅ |

缺口：

- 知识以**扁平事件日志 + 向量 chunk** 存在，缺少**实体—关系—实体**的结构化视图
- 政策依赖**手工上传/粘贴**，未系统化对接官网/RSS
- 库页仅有列表与检索，**无可视化探索**（图谱、时间线、板块脉络）

### 1.2 目标（R3）

在**不破坏**现有「jsonl 事实源 + SqliteStore 向量」主线的前提下：

1. 构建覆盖 **宏观 → 市场 → 政策 → 行业 → 公司** 五层的本地知识图谱
2. 首批范围：**中证300**（~300 股 + 行业 + 指数 + 政策事件）
3. **时间分层**：当年详录、去年月摘要、更早季/年主题摘要
4. **政策采集**：在现有 `ingest.py` 上扩展「官网 URL / 定时抓取」流水线
5. **可视化**：库页新增图谱探索 Tab（分阶段落地）

### 1.3 非目标

- 不用图谱替代行情/OHLCV/因子工具取数（数字仍走确定性管道）
- 不引入 PostgreSQL / Neo4j / Redis（保持单用户文件持久化）
- 不做全市场实时爬虫集群（先 CSI300 + 核心政策源）

---

## 2. 知识域全景

### 2.1 五层 × 三类信息

```
宏观层 ──货币政策/利率、汇率、大宗商品、地缘
   ↓
市场层 ──大盘行情、宽度、资金面（北向/两融/ETF）、情绪（涨停生态）
   ↓
政策监管层 ──国务院/部委规章、证监会/交易所规则、执法（问询/立案/处罚）
   ↓
行业层 ──申万/中信分类、产业政策、景气、产业链上下游
   ↓
公司层 ──经营财报、公告、舆情、股东/解禁/并购
```

### 2.2 维度清单

| 层级 | 你已提出 | 建议补充 | 入库形式 |
|---|---|---|---|
| 大盘 | 舆情、政策、行情 | 宽度、涨停数、主要指数涨跌 | jsonl 日快照 + 图谱 `MarketSnapshot` 节点 |
| 板块 | 国家政策、国际形势、舆情 | 资金净流入、龙头标的、产业链传导 | `Sector` 节点 + `sector_pulse` 归档 |
| 个股 | 公司经营状况 | 公告、解禁、分红、同业相对位置 | `Stock`/`Company` + 财报结构化字段 |
| 宏观 | （隐含在国际形势） | 降准降息、PMI、汇率 | `Macro` 节点，月频即可 |
| 监管 | 政策入库 | 问询函、减持新规、退市规则 | `Policy` 节点，关联 `AFFECTS` 边 |

**不进图谱的**：OHLCV、技术指标、因子截面数值 — 继续走 qlib/baostock + 因子库。

---

## 3. 知识图谱 Schema

### 3.1 节点类型（Entity）

| 类型 | 示例 | 关键属性 |
|---|---|---|
| `Index` | 沪深300 | `code`, `name` |
| `Sector` | 电子、白酒 | `sw_l1`, `sw_l2`, `code` |
| `Stock` | sh600519 | `symbol`, `name`, `weight_in_csi300` |
| `Company` | 贵州茅台 | `legal_name`, `listing_date` |
| `Policy` | 减持新规 | `title`, `issuer`, `effective_date`, `url`, `doc_id` |
| `Event` | 2026Q1 财报 | `type`, `date`, `impact` |
| `News` | 舆情标题 | `title`, `url`, `sentiment`, `ts` |
| `Macro` | 降准 | `indicator`, `value`, `period` |
| `Digest` | 2025-06 电子月报 | `period`, `granularity`, `summary` |

### 3.2 关系类型（Relation）

```
(Stock)-[:LISTED_AS]->(Company)
(Stock)-[:IN_INDEX {weight}]->(Index)
(Stock)-[:IN_SECTOR]->(Sector)
(Sector)-[:SUBSECTOR_OF]->(Sector)
(Policy)-[:AFFECTS {direction, strength, confidence}]->(Sector|Stock|Index)
(News)-[:MENTIONS]->(Stock|Sector)
(Event)-[:ABOUT]->(Stock)
(Stock)-[:SUPPLIES_TO|COMPETES_WITH]->(Stock)    # LLM 抽取，需 source 引用
(Macro)-[:IMPACTS]->(Sector|Index)
(Digest)-[:SUMMARIZES]->(News|Event|Policy)       # 时间 rollup 产物
```

低置信度边（`confidence < 0.7`）仅用于探索，不参与 agent 自动推理。

### 3.3 存储选型

| 层 | 路径 | 职责 |
|---|---|---|
| **事实源** | `data/knowledge/**/*.jsonl` | 审计、重放、reindex |
| **图谱** | `data/graph/graph.db`（SQLite） | 多跳查询、可视化 API |
| **向量** | `data/memory.db` | 语义检索（摘要/chunk） |

推荐 **SQLite 边表**（当前实现）：零新依赖、与单用户文件持久化一致。Kuzu/Cypher 可作为后续迁移选项。

---

## 4. 时间分层策略

| 时间窗口 | 粒度 | 存储 | 处理 |
|---|---|---|---|
| **当年（2026）** | 日/周 | 完整 headlines、指标、公告要点 | 原始 jsonl + 图谱节点 |
| **去年（2025）** | 月 | `Digest` 节点（`granularity=monthly`） | LLM 汇总当月 jsonl |
| **更早** | 季/年 | `Digest`（`granularity=quarterly/yearly`） | 按主题聚合，只保留结论 |

### 4.1 月摘要示例

```json
{
  "id": "digest_2025-06_electronics",
  "type": "monthly_digest",
  "sector": "电子",
  "period": "2025-06",
  "themes": ["AI算力景气", "消费电子复苏"],
  "key_policy_ids": ["policy_evt_xxx"],
  "avg_sentiment": 0.62,
  "summary": "6月电子板块受AI服务器拉动，政策面无重大利空…"
}
```

### 4.2 Rollup 流水线（定时任务）

```
每月 1 日 02:00
  → 读取上月 jsonl（sentiment / breadth / policy events）
  → LLM 生成 sector + market 级 Digest
  → 写入图谱 + embed 到 memory.db
  → 原始 jsonl gzip 归档到 data/knowledge/archive/
```

---

## 5. 中证300 落地范围

### 5.1 规模估算

| 项目 | 数量 | 说明 |
|---|---|---|
| 成分股 | ~300 | `fetch_universe_symbols("csi300")` 已有 |
| 申万一级行业 | ~31 | 每股 1–2 个行业标签 |
| 图谱节点 | ~5,000 | 股 + 行业 + 政策 + 事件 + 摘要 |
| 图谱边 | ~15,000 | 映射关系为主 |
| 磁盘 | < 2 GB | 含向量 + 归档 |

### 5.2 分批实施

| 阶段 | 内容 | 周期 |
|---|---|---|
| **Phase 0** | CSI300 骨架：股—行业—指数权重 | 1 周 |
| **Phase 1** | 日频 breadth + 300 股舆情批量归档 | 2 周 |
| **Phase 2** | 公告/财报结构化 + Top50 产业链边 | 1 月 |
| **Phase 3** | 政策自动采集 + 图谱可视化 | 1 月 |

舆情批量建议**夜间限速**（akshare 约 2–3 小时/轮），与热路径分析解耦。

---

## 6. 政策采集：网上能找到吗？

**可以。** 监管政策、部委规章、交易所业务规则在官网均有公开全文；当前 `ingest.py` 仅支持**本地上传与对话粘贴**，尚未实现自动抓取。建议扩展为 **三通道**：

### 6.1 三通道对比

| 通道 | 方式 | 适用场景 | 现状 |
|---|---|---|---|
| **A. 手工入库** | 库页上传 PDF/MD/TXT；对话「把这段监管条文入库」 | 研报、内部材料、扫描件 | ✅ 已实现 |
| **B. URL 入库** | 用户或管理员提交白名单官网链接 → 抓取 HTML/PDF → `ingest_text_document` | 已知政策直链 | ⬜ R3a 规划 |
| **C. 定时采集** | 订阅 RSS / 列表页增量 → 去重 → 自动入库 + 建 `Policy` 节点 | 持续更新监管库 | ⬜ R3b 规划 |

三者最终都汇入同一条流水线：`抓取正文 → split_text → manifest.json + chunks.jsonl → embed → 图谱 Policy 节点`。

### 6.2 可采集的公开数据源

| 来源 | 网址 | 内容类型 | 获取方式 | 备注 |
|---|---|---|---|---|
| 中国证监会 | https://www.csrc.gov.cn | 规章、规范性文件、答记者问 | 列表页 + 详情 HTML；部分附件 PDF | 政策核心源 |
| 上海证券交易所 | https://www.sse.com.cn | 业务规则、指引、通知 | 规则专栏列表 | 交易层面细则 |
| 深圳证券交易所 | https://www.szse.cn | 同上 | 规则列表 | 与上交所互补 |
| 国务院 | https://www.gov.cn | 国发/国办文件 | `zhengce` 频道 | 宏观政策 |
| 中国人民银行 | http://www.pbc.gov.cn | 货币政策、公告 | 新闻/政策栏目 | 利率、准备金 |
| 国家发改委 | https://www.ndrc.gov.cn | 产业政策 | 通知公告 | 行业政策 |
| 巨潮资讯 | https://www.cninfo.com.cn | 上市公司公告 | akshare `stock_notice_report` 等 | 公司级，非部委规章 |
| 东方财富 / 同花顺 | 财经门户 | 政策快讯标题 | 作发现入口，**全文以官网为准** | 仅辅助 |

**akshare 可辅助**：指数成分、公告列表、部分宏观序列；**部委规章全文**通常仍需官网 HTML/PDF 解析或配合 `langchain-community` 的 `WebBaseLoader`（限白名单域名）。

### 6.3 推荐采集架构

```
policy_sources.yaml          # 源配置：名称、列表 URL、选择器、issuer
        ↓
policy_fetcher.py            # 定时/手动：拉列表 → diff 新条目
        ↓
policy_extractor.py          # HTML→text / PDF→text（复用 ingest.extract_pdf_text）
        ↓
ingest_text_document()       # 现有切块 + embed
        ↓
graph_builder.link_policy()  # Policy 节点 + AFFECTS 边（LLM 或规则表）
```

### 6.4 `policy_sources.yaml` 示例

```yaml
sources:
  - id: csrc_rules
    name: 证监会-规范性文件
    issuer: 证监会
    list_url: https://www.csrc.gov.cn/csrc/c101953/common_list.shtml
    detail_link_selector: "a[href*='content.shtml']"
    allowed_hosts:
      - www.csrc.gov.cn
    fetch_interval_hours: 24

  - id: sse_rules
    name: 上交所-业务规则
    issuer: 上交所
    list_url: https://www.sse.com.cn/lawandrules/rules/law/
    allowed_hosts:
      - www.sse.com.cn
    fetch_interval_hours: 24
```

### 6.5 安全与合规

| 风险 | 缓解 |
|---|---|
| SSRF（任意 URL） | **仅允许 `policy_sources.yaml` 白名单 host**；用户提交 URL 也需校验 |
| 反爬 / 封 IP | 限速、If-Modified-Since、夜间跑；失败入重试队列 |
| 版式变更 | 选择器配置化；抓取失败告警，不静默丢数据 |
| 版权 | 仅个人研究本地存档；不外传、不商用再分发 |
| 幻觉关联 | `AFFECTS` 边必须带 `source_chunk_id`；低置信标灰 |

### 6.6 与现有 `ingest.py` 的衔接

现有函数无需重写，扩展点：

```python
# 规划新增 backend/app/knowledge/policy_fetcher.py
async def ingest_policy_from_url(url: str, *, title: str | None = None) -> dict:
    """校验白名单 → 下载 → 提取正文 → ingest_text_document(source='crawl')"""

async def run_policy_sync(source_id: str | None = None) -> dict:
    """定时任务：扫描 policy_sources.yaml，增量入库"""
```

API 规划：

```
POST /api/knowledge/ingest/url
     body: { "url": "https://www.csrc.gov.cn/...", "title": "可选" }

POST /api/knowledge/policy/sync
     body: { "source_id": "csrc_rules" }   # 管理员手动触发
```

---

## 7. 数据源矩阵（全库）

| 数据类型 | 免费源 | 项目现状 | 图谱用途 |
|---|---|---|---|
| CSI300 成分 | akshare `index_stock_cons_csindex` | ✅ | `IN_INDEX` 边 |
| 行情 OHLCV | baostock / qlib | ✅ | 不进图谱 |
| 新闻舆情 | akshare `stock_news_em` | ✅（常为空需降级） | `News` + `MENTIONS` |
| 大盘宽度 | 东财 API | ✅ | `MarketSnapshot` |
| 板块脉冲 | 东财 API | ✅ | `Sector` 属性更新 |
| 基本面 | akshare 巨潮 | ✅ | `Company` 属性 |
| 公告 | akshare 公告接口 | ❌ 待补 | `Event` |
| 北向/两融 | akshare | ❌ 待补 | `Macro`/`MarketSnapshot` |
| 政策全文 | 官网 + 上传 | 部分（仅上传） | `Policy` |
| 国际宏观 | akshare 宏观序列 | ❌ 可选 | `Macro` |

---

## 8. 数据挖掘与 Agent 使用

检索优先级（延续 RAG_PLAN 原则）：

1. **结构化过滤**：symbol / sector / date / type
2. **图谱扩展**：1–2 跳邻居（政策影响了哪些 CSI300 股）
3. **向量语义**：`search_knowledge` 兜底
4. **实时数字**：工具 `fetch_quote` 等

| 用户问题 | 手段 |
|---|---|
| 白酒板块近 7 天政策变化 | `get_knowledge_delta` + 图查询 `Sector←Policy` |
| 降准受益的 CSI300 标的 | `Macro -[:IMPACTS]-> Sector <-[:IN_SECTOR]- Stock` |
| 茅台 vs 五粮液舆情对比 | 两 `Stock` 节点 `News` 邻居 diff |
| 减持新规原文 | `search_knowledge(type=policy)` |

规划新工具：`query_graph(cypher|template, params)` — 封装常用模板，避免 agent 写裸 Cypher。

---

## 9. 可视化方案

**可以做，且建议分阶段**，避免一上来做全图力导向（300 股全展开易「毛球」）。

### 9.1 阶段划分

| 阶段 | 视图 | 技术 | 工作量 | 价值 |
|---|---|---|---|---|
| **V0** | 政策/事件**时间线** | 纯 CSS + 现有事件 API | 小 | 立刻可用 |
| **V1** | **板块热力** + 实体详情卡 | Recharts / 现有库页组件 | 中 | 看板块—政策—舆情脉络 |
| **V2** | **子图探索**（单股 1–2 跳） | `react-force-graph-2d` 或 `@xyflow/react` | 中 | 交互式图谱 |
| **V3** | 全库图谱 / 社区聚类 | GraphRAG 社区 + 力导向 | 大 | 研究用 |

### 9.2 推荐技术栈（与现有前端一致）

| 方案 | 说明 |
|---|---|
| **react-force-graph-2d** | 轻量，适合 Stock–Sector–Policy 子图 |
| **@xyflow/react** | 已有生态，适合固定布局的流程/层级图 |
| **Recharts** | 时间线、板块涨跌、情绪趋势 |
| **后端 API** | `GET /api/graph/subgraph?center=sh600519&hops=2` 返回 `{nodes, edges}` |

不建议为可视化单独引入 Neo4j Browser；子图由 `GET /api/graph/subgraph` 返回 JSON，前端 `GraphForceView` 渲染。

### 9.3 库页 UI 规划（Knowledge Tab 扩展）

```
库 → 知识
├── [现有] 事件归档 | 政策文档 | 语义检索
└── [已落地] 图谱探索
      ├── 中心代码 + 跳数 1|2 + 增量/强制同步
      ├── 力导向视口（角 HUD：中心、跳数、节点/边数）
      └── 高级：白名单政策 URL 入库
```

### 9.4 交互原则

- 默认展示 **≤50 节点** 子图，防止性能问题
- 节点按类型着色（Stock / Sector / Policy / News 等），边为琥珀半透明
- 点击 `Policy` 节点 → 展示 `manifest` 摘要 + `search_knowledge` 命中 chunk（规划）
- 与对话联动：分析某股时，侧边栏可嵌入「相关政策子图」缩略图（V2）

---

## 10. 模块与目录规划

```
backend/app/
├── knowledge/
│   ├── archiver.py          # 已有
│   ├── ingest.py            # 已有；R3 被 policy_fetcher 调用
│   ├── policy_fetcher.py    # 新增：URL/定时采集
│   ├── policy_sources.yaml  # 新增：源配置（或放 data/）
│   └── ...
├── graph/
│   ├── schema.py            # 节点/边类型
│   ├── store.py             # Kuzu 封装
│   ├── builder.py           # 从 jsonl / akshare 建图
│   ├── extractor.py         # LLM 三元组抽取
│   ├── summarizer.py        # 月/季 Digest
│   └── queries.py           # 预置 Cypher 模板
└── api/
    ├── knowledge.py         # 扩展 ingest/url、policy/sync
    └── graph.py             # 新增 subgraph、stats

data/
├── knowledge/               # 已有
├── graph/
│   ├── graph.db
│   └── snapshots/           # 导出的 subgraph JSON（可选缓存）
└── policy_sources.yaml      # 可选：与代码分离便于改配置

frontend/src/
├── pages/KnowledgeLibrary.tsx   # 扩展 Tab
└── components/graph/
    ├── GraphExplorer.tsx
    ├── PolicyTimeline.tsx
    └── graphTypes.ts
```

---

## 11. 开源参考

| 项目 | 借鉴点 |
|---|---|
| [Microsoft GraphRAG](https://github.com/microsoft/graphrag) | 社区检测 + 分层摘要（契合「今年详去年泛」） |
| [LightRAG](https://github.com/HKUDS/LightRAG) | 轻量图 + 向量混合检索 |
| [OpenSPG / KAG](https://github.com/OpenSPG/KAG) | 金融 KG schema 参考 |
| [Kuzu](https://github.com/kuzudb/kuzu) | 嵌入式图数据库 |
| [StockAnal_Sys](https://github.com/lc2panda/StockAnal_Sys) | A 股 agent + 舆情多源 |
| [U2INVEST](https://github.com/DasbootU9607/U2INVEST-Your-Stocks-You-To-Invest) | AkShare + RAG 流水线 |

**不整仓引入**：LlamaIndex（已有 LangChain）、Neo4j（过重）、商业 Wind/iFinD SDK。

---

## 12. 实施路线图

| 里程碑 | 交付物 | 依赖 | 状态 |
|---|---|---|---|
| **R3.0** | CSI300 骨架图谱 + `POST /api/graph/sync` 样本限速同步 | SQLite `data/graph/graph.db` | ✅ |
| **R3.1** | 公告数据源 + 图谱 Event + `fetch_announcements` | akshare | ✅ |
| **R3.2** | `policy_fetcher` + 白名单 URL 入库 + 图谱 Policy 节点 | 网络安全审查 | ✅ |
| **R3.3** | 月摘要 Rollup + Digest 节点 + `POST /api/graph/rollup` | LLM | ✅ |
| **R3.4** | 库页图谱探索（关系表 + 同步 + URL 入库） | 前端 | ✅ |
| **R3.5** | 力导向子图（react-force-graph-2d） | 前端 | ✅ |
| **R3.6** | 市场层（北向/两融/Macro/MarketSnapshot）、板块 Rollup、政策列表增量、三元组抽取、月度维护 | akshare + LLM | ✅ |

### 12.1 已实现 API

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/graph/stats` | 节点/边统计 |
| `GET` | `/api/graph/subgraph?center=sh600519&hops=1` | 子图查询 |
| `POST` | `/api/graph/bootstrap` | 仅建 CSI300 骨架（不爬舆情） |
| `POST` | `/api/graph/sync` | 样本股限速同步（见环境变量） |
| `POST` | `/api/graph/sync/market` | 北向/两融/宏观/大盘快照 |
| `POST` | `/api/graph/rollup` | 按月生成 Digest（symbol / sector / market） |
| `POST` | `/api/graph/rollup/month` | 当前月多样本股批量 Rollup |
| `POST` | `/api/graph/policy/sync` | 政策列表页增量 diff 入库 |
| `POST` | `/api/graph/maintenance` | jsonl gzip + 月 Rollup + 政策同步 |
| `POST` | `/api/graph/extract?symbol=` | 单股 LLM 产业链三元组 |
| `POST` | `/api/knowledge/ingest/url` | 白名单官网 URL 抓取入库 |
| `GET` | `/api/knowledge/policy/hosts` | 当前 URL 白名单 |

CLI：`abq-graph sync-market | policy-sync | maintenance | rotate`

Agent 工具：`query_graph`、`ingest_policy_url`、`fetch_announcements`。

**反爬策略（默认）**：

- `GRAPH_FETCH_MIN_INTERVAL_S=3`：相邻请求至少间隔 3 秒
- `GRAPH_SYNC_COOLDOWN_HOURS=6`：同一只股票 6 小时内不重复爬（`force=true` 可跳过冷却，仍遵守间隔）
- `GRAPH_SYNC_SAMPLE_SYMBOLS`：默认 5 只样本；`?symbols=sh600519,sz000858` 可指定

### 12.2 本地开发与故障排查

| 组件 | 默认地址 | 说明 |
|---|---|---|
| 后端 API | `http://127.0.0.1:8000` | `uvicorn app.main:app --port 8000` |
| 前端 | `http://127.0.0.1:5173` | `npm run dev`（`strictPort`，不会跳到 5174） |
| Vite 代理 | `/api` → `8000` | `frontend/vite.config.ts` 中 `server.proxy` |

**常见 502**：前端能打开但所有 API 报「请求失败 (502)」→ 后端未监听 8000，或 Vite 代理 `target` 与后端端口不一致。改后需重启 `npm run dev`。

**sandbox network policy**：分析步骤出现 `Blocked by sandbox network policy` / `118.195.177.58:8001` → 当前 uvicorn 在 Cursor Agent 沙箱内，出站 LLM 被拦。在本机终端重起后端。图谱同步、embedding、三元组抽取同样走该主机。

**CLI**（`pip install -e backend` 后）：

```bash
abq-graph sync-market      # 市场/宏观层
abq-graph policy-sync      # 政策列表增量
abq-graph maintenance      # 月维护（gzip + Rollup + 政策）
abq-graph rotate           # 仅 jsonl 归档
```

**数据目录**：

```
data/graph/graph.db          # 图谱（SQLite）
data/knowledge/**/*.jsonl    # 事实源（审计/重放）
data/policy_sources.yaml     # 政策 URL 白名单与定时源
```

---

## 13. 风险与验收

### 13.1 风险

| 风险 | 缓解 |
|---|---|
| akshare 限流/变更 | 多源降级 + 缓存 + 队列重试 |
| 舆情单次为空 | 历史累积，不依赖单次工具 |
| LLM 三元组幻觉 | 必填 `source_id`；低置信边标记 |
| 官网改版 | `policy_sources.yaml` 外置配置 |
| 图谱与向量不一致 | jsonl 为唯一事实源；图/向量可 reindex |

### 13.2 验收标准（R3）

1. `data/graph/graph.db` 含 300 股 + 行业 + 沪深300 指数节点
2. `GET /api/graph/subgraph?center=sh600519&hops=1` 返回政策/行业/公告/舆情邻居
3. 至少 1 份官网政策通过 `ingest/url` 或 `policy/sync` 自动入库并可 `search_knowledge` 命中
4. 库页 **知识 Tab** 可查看力导向子图、同步样本、月 Rollup
5. `POST /api/graph/sync/market` 写入北向/宏观/MarketSnapshot 节点（数据源可用时）

---

## 14. 文档索引

| 文档 | 关系 |
|---|---|
| [RAG_PLAN.md](./RAG_PLAN.md) | R0–R2 事件日志 + 向量检索；本文档为 R3 扩展 |
| [DESIGN.md](./DESIGN.md) | 平台总览 |
| [USER_GUIDE.md](./USER_GUIDE.md) | 用户侧政策入库与检索话术 |

---

*最后更新：2026-08-27*
