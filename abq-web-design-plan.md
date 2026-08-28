# abq Web 前端设计方案

## 0. 本文档状态

已用源码核查校准关键事实（见下方"已核查"）。3 个并行调查 agent 的部分结果已直接读源码补齐。

**已核查的关键事实：**
- `POST /api/supervisor/ask` 是**同步阻塞 POST**，单次返回 `{reply, tool_trace, meta}`，**非流式**（agent_api/ 无 SSE/WebSocket/StreamingResponse）。LangGraph 在后端跑完一次性返回。前端需处理 30–600s 长等待。
- factor_lab 有持久化 registry：`quant/factor_lab/factors.yaml`（load_lib/save_lib）。"因子库"= 包装现有 YAML，非新建存储。
- 无 realm/market 抽象：A 股逻辑（涨跌停/ST/limit_up）硬编码在 ~15 个文件（core/events.py、settle/track、prediction/emit 等）。ETF 落地工作量在**后端结算层**而非 UI——UI 只需预留 realm 字段。

---

## 1. 你真正要什么（重新框定）

你说的是"参考 dsh 画个页面"，但你的四个补充回答把任务升级了：

1. **插件化架构内核** —— 不是为了好看，是为了"后续开放构建因子库 / agent 库 / 提示词库，根据用户输入自动组合"。即 UI 要能**容纳未来会出现、现在还没定义的能力**。
2. **可对接 dsh** —— 后续可能把 abq 接到 dsh 里跑。所以 abq 前端**不能假设自己永远独立**，它的能力要能被重新封装。
3. **多市场** —— A 股只是第一个，后续 ETF。领域模型不能把"股票/涨停板/T+1"写死成 UI 骨架。
4. **推倒重做现有 agent-ui**，暂不做 TUI。

这三条合起来，决定了设计的核心矛盾：**既要满足当前 abq 的具体领域（预测账本/结算/信任），又要保留 dsh 式的可扩展性**。处理不好就会两端不靠——既没 dsh 的通用，又比直接写多了一堆抽象负担。

我的判断：**借鉴 dsh 的分层思想，但不照搬 Cordis 容器**。理由在 §2。

---

## 2. 架构决策：借鉴到什么程度

dsh 的复杂性来自它的定位——**通用 harness，要让第三方插件扩展**，所以它需要：Cordis 插件容器、slot 声明系统、双下行 WebSocket、patch 配置层。

abq 不是通用 harness，它是**单用户、领域专用、后端已定型**的控制台。它的"扩展"是**你自己演进**（加因子库、加 ETF、加 agent），不是让陌生人写插件。所以：

| dsh 的能力 | abq 是否需要 | 取舍 |
|---|---|---|
| Cordis 插件容器 + patch 配置 | **不需要** | 单用户演进不需要 patch 层；用普通模块注册即可 |
| slot 声明系统（声明=渲染授权） | **借鉴简化版** | 用"命名区域 + 注册表"实现可扩展的 UI 区位，但不做声明合并/type-chain 那套 |
| 双下行 WebSocket 流式 | **需要简化版** | Supervisor 编排要流式（30–600s），但要单通道、按需，不做 mux |
| 万物皆插件（循环也是插件） | **不需要** | abq 的"循环"是后端 LangGraph，前端不重造 |
| loopback 安全 fence | **借鉴** | abq 已有 IP 白名单 + Bearer，前端只做调用方 |

**核心借鉴**：dsh 的 **"能力 seam"（接口/提供方/消费方三元组）思想** + **"布局即注册"的 UI 组装方式** + **"会话/工具调用流"的呈现范式**。不借它的容器内核。

---

## 3. API 契约（待 agent 校准）

基于已读文档（QUANT_AGENT_ARCHITECTURE.md §6, USAGE.md）的端点清单：

| 方法 路径 | 用途 | 前端消费方 |
|---|---|---|
| GET /api/health | caliber / Peak LLM / 鉴权 | 系统状态 |
| GET /api/system/status | 数据日、口径版本 | 顶栏 AsOf |
| GET /api/predictions | L1/L2 全量 + release_gate | 今日放行 / 账本 |
| GET /api/strategies | L3 策略注册表 | 策略信任 |
| GET /api/calibration | 分桶校准 / Wilson | 成绩校准 |
| GET /api/research/* | factor_lab 同步 + 晋升门 | 研究旁路 |
| GET /api/recommend/blend | 混权推荐 | 今日放行排序 |
| POST /api/supervisor/ask | Supervisor 编排（流式 30–600s） | 会话栏 |
| POST /api/admin/recompute | 口径重算（dry_run 优先） | 结算台 |

**待校准**：每个端点的请求/响应字段名（claim_type/status/strategy_state 的实际枚举值）、supervisor/ask 是否 SSE 流式、research/* 的子路径。

---

## 4. 信息架构（页面 ↔ 模式）

现有 7 页是**数据浏览模式**。你要的 dsh 风格增加了**会话编排模式**和**库管理模式**。合成三模式布局：

### 4.1 主布局（借鉴 dsh：左导航 + 主工作区 + 右侧会话/工具轨）

```
┌──────────────────────────────────────────────────────────────┐
│ TopBar: AsOf · caliber · LLM 状态 · 鉴权 · 市场切换(A股/ETF▾) │
├────────┬───────────────────────────────┬─────────────────────┤
│        │                               │                     │
│ SideNav│      主工作区                  │  会话/工具轨         │
│ (注册式)│  (随路由切换的视图)            │  (Supervisor流)      │
│        │                               │                     │
│ ·今日  │                               │  ┌─ 对话流 ─┐       │
│ ·账本  │                               │  │ user msg │       │
│ ·结算  │                               │  │ step┐    │       │
│ ·校准  │                               │  │ tool├──┐ │       │
│ ·策略  │                               │  │     │  │ │       │
│ ·研究  │                               │  │     ←──┘ │       │
│ ·库 ▾  │                               │  │ asst msg │       │
│  因子  │                               │  └─────────┘       │
│  agent │                               │                     │
│  prompt│                               │  ▌输入框            │
│ ·系统  │                               │                     │
└────────┴───────────────────────────────┴─────────────────────┘
```

### 4.2 三种工作模式（顶栏切换，共享同一 shell）

| 模式 | 主区内容 | 会话轨 | 对应 dsh |
|---|---|---|---|
| **工作台**(默认) | 今日放行/账本/结算等数据视图，随左导航切 | 附着当前预测的 Supervisor 会话 | layout + conversation |
| **会话** | 整宽对话流 + 工具调用树，无数据表格 | (主区即会话) | ui-trajectory + ui-tool |
| **库** | 因子库/agent库/提示词库管理 | 库项编辑器 | (dsh 无直接对应，这是 abq 独有扩展点) |

**关键**：左导航项、顶栏市场切换、会话轨的输入快捷芯片——都是**注册式**的，不是写死的。这满足"后续开放构建各种库"。

---

## 5. 领域模型（前端 TS 类型，待 agent 校准字段名）

```ts
// 市场——抽象第一层，A股/ETF 都实现 AssetRealm
interface AssetRealm {
  code: 'a-share' | 'etf'  // 后续扩展
  label: string
  // 各 realm 的结算规则、涨停限制、T+N 不同
}

// 预测账本条目（L1/L2 共用，claim_type 区分）
interface Prediction {
  pred_id: string
  realm: AssetRealm['code']
  object: string          // 股票代码 / 组合ID
  claim_type: 'direction' | 'interval' | 'target'
  claim: unknown          // 结构随 claim_type
  deadline: string
  benchmark?: string
  settlement_caliber: string
  status: 'pending' | 'resolved' | 'expired' | 'shadow'
  release_gate: 'released' | 'hold' | 'quarantine' | 'observe'
  scorecard?: Scorecard   // resolved 才有
  source: { model: string; confidence?: number }  // LGBM 等；LLM 不在此
}

interface Strategy {       // L3 状态机
  sid: string; state: 'champion'|'challenger'|'paused'|'shadow'; trust_weight: number; ... }
```

**设计约束**（来自 PRODUCT.md，UI 必须强制）：
- 纸面 vs 实盘视觉分离（双时间线，禁止混读）
- 无成绩单/n<30 不得进主推荐区（released gate 强制）
- LLM 数字与账本冲突时以账本为准（Supervisor 回复带可追溯锚点）
- 不出现"必涨/稳赚"措辞

---

## 6. 可扩展性内核（借鉴 dsh 的简化方案）

这是你要的"插件化架构内核"。不做 Cordis，做**三层注册表**：

### 6.1 能力注册表（UI 侧）
```ts
// 一个全局 registry，模块启动时注册
const nav = createNavRegistry()        // 左导航项 → 路由 → 视图组件
const realm = createRealmRegistry()    // 市场实现（A股先注册，ETF 后注册）
const convoChip = createChipRegistry() // 会话轨输入快捷芯片
const toolView = createToolViewRegistry() // 工具调用的 keyed 视图（对应 dsh ui-tool）
```
每个注册表就是 `Map<id, entry>` + `register()` + `useEntries()` hook。**不做 slot 声明合并、不做 type-chain**——单用户演进用不上，徒增复杂度。

### 6.2 三库（因子/agent/提示词）的统一抽象
你要的"根据用户输入自动组合"，本质是：**用户输入 → 路由 → 选库项 → 组装成 prompt/工具集 → 调 Supervisor**。统一成一个 `LibraryEntry` 契约：

```ts
interface LibraryEntry {
  id: string
  kind: 'factor' | 'agent' | 'prompt'
  name: string
  status: 'draft'|'proposed'|'evaluated'|'promoted'|'paused'  // 复用 champion/challenger 状态机
  meta: Record<string, unknown>  // 各 kind 特有字段
  validate: () => Promise<ValidationResult>  // 复用各库的检验门
}
```
这样库管理 UI 可以是一个通用 CRUD + 按 kind 的 keyed 详情视图（正是 dsh 的 chain-kind slot 思想，但用更简单的 keyed 路由实现）。

### 6.3 接入 dsh 的预留路径
abq 接 dsh 的方式（后续）：把 abq 的每个能力（取数、emit、track、Supervisor）包装成 **dsh 的能力 seam 提供方**注册到 `ctx.*`。所以现在 abq 前端的**能力调用统一走 `api.*` 客户端抽象层**（不直接 fetch），将来这个客户端可以换成 dsh 的 `ctx.connection`。这是唯一需要现在就遵守的前端纪律。

---

## 7. 技术栈

- React 18 + Vite + TypeScript（沿用，已成熟）
- 路由：react-router（沿用）
- 状态：现有 zustand store 演进，**领域数据用 react-query/SWR 缓存**（现状每次 mount fetch，要改成带缓存+失效的）
- 样式：现有 lab-ledger.css → 重构为 **CSS variables token 系统**（design tokens：色板/间距/字号），深色专业数据界面。不引入 Tailwind/大型 UI 库（单用户、数据密集、自包含）
- 会话：Supervisor 是**同步阻塞 POST（非流式）**，单次返回 `{reply, tool_trace, meta}`，耗时 30–600s。前端做：①提交即显示"编排中"状态 + 可取消（AbortController）②用占位/骨架而非流式 token ③`tool_trace` 渲染为工具调用树（整批，非流式追加）。**不**引入 SSE/WebSocket。
- 组件：自建轻量 primitives（表格、印章/badge、分桶条、Wilson CI 图）——这些是 abq 特有，外部库没有

---

## 8. 实施分期

**P0 — 骨架重写**（先有可用的 dsh 风格壳）
1. 新 agent-ui 目录结构：app/（shell）+ features/（页面）+ shared/（api/store/ui）+ registry/（§6）
2. 三栏 shell + 顶栏市场切换 + 注册式导航
3. design tokens + 深色主题
4. api 抽象层 + react-query 缓存

**P1 — 工作台模式**（搬现有 7 页到新壳，用真实 API）
- 今日放行 / 账本 / 结算 / 校准 / 策略 / 研究旁路 / 系统
- 每页暴露为 nav 注册项

**P2 — 会话模式**
- Supervisor 会话轨（流式）+ 工具调用树（keyed 视图注册）
- 预测附着 → 会话上下文

**P3 — 库模式（2026-08-25 落地）**
- ✅ Agent / 提示词 CRUD（`LibraryPage` + `library_store`）
- ✅ 工具只读目录（代码注册，UI 展示 description + guidance）
- ✅ 因子库（`data/factors/` + `FactorLibrary` Tab；评测 / LLM 挖掘 / GP 双轨）
- ✅ 「根据用户输入自动组合」规则路由器（`POST /api/compose/route` → composer 提示 + `agent_ids` / `prompt_id`）

**P4 — 多市场 + dsh 对接预留**
- AssetRealm 抽象落地，注册 ETF realm
- api 客户端层为 dsh connection 留 seam

---

## 9. 待 agent 校准的开放问题

1. supervisor/ask 是否流式？若是，是 SSE 还是 WebSocket？（决定 §7 和 P2）
2. research/* 的确切子路径与晋升门字段？（决定库管理 P3）
3. factor_lab 是否有持久化的因子 registry 文件（factors.yaml）？（决定"因子库"是 UI 包装现有文件还是新建存储）
4. A 股相关逻辑在代码里有多硬？（决定 ETF realm 的 P4 工作量）
5. 是否已有任何 registry/decorator 模式？（决定 §6 能否复用既有抽象）
