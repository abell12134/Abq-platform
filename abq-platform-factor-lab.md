# A股/ETF 分析平台 — 因子库与因子挖掘方案

> 配套：[后端](abq-platform-backend-design.md) · [前端](abq-platform-frontend-design.md)。  
> 参考实现：**不 import**。思想来自本仓库的 abq `quant/factor_lab`、Abq-Trading 的 `llm_factor_miner` / 五道准入、Vibe-Trading 的 Alpha Zoo 算子契约。  
> 状态：P5a–g 已落地（解释器 + 种子 + LLM/GP 双轨挖掘 + **合成/纸面** + 单票挂载 + agent 因子工具）。**对话内触发挖掘**仍待做。

## 0. 要解决什么

dd 的「库」已含 Agent / 提示词 / 工具 / **因子** 四 Tab；因子运行时见 `app/factors/` + `data/factors/`（种子目录 + `discovered.yaml` + 挖掘 runs）。**P5f 合成 + 纸面跟踪**仍待做。对照历史缺口：

| 已有资产 | 缺什么 |
|---|---|
| **abq `factor_lab`**：LLM 提议 Qlib 表达式 + 五道准入 + YAML 状态机 | 在 dd 里没有运行时；表达式绑死 Qlib |
| **Abq-Trading**：经典因子 Python 实现 + `eval` 跑 LLM 公式 + IC 合成 | `eval` 不安全；无遗传规划；绑 MySQL |
| **Vibe-Trading Alpha Zoo**：462 预构建截面 Alpha + 算子层禁前视 | 没有自动发明公式；体量大、许可分散，不适合整库搬进 dd |
| **dd 自己**（2026-08 现状） | 单票 OHLCV / 指标 / LLM 编排 + FactorExpr IR + 五道准入 + LLM/GP 双轨挖掘 + 单票挂载 + agent 因子工具 | P5f 合成、纸面跟踪、大盘/选组 pipeline、对话内触发挖掘 |

目标：**一个因子库 + 三条发明路径 + 同一套准入**。LLM 挖掘沿用 abq 的 RD-Agent 循环；新增遗传规划 / 符号回归，用**大盘数据**当终端变量，自动发明可读公式。

三条路径的产出必须长得一样，才能进同一库、过同一闸门、被同一分析工具调用。

```
  种子目录          LLM 挖掘              GP / 符号回归
  (手写/移植)       (有经济逻辑)           (机器发明公式)
       │                 │                      │
       └────────────┬────┴──────────────────────┘
                    ▼
              FactorExpr IR
              （白名单算子树，禁 eval）
                    ▼
              同一评测 + 五道准入
                    ▼
         data/factors/  （状态机 YAML）
                    ▼
     分析工具 / 库 UI / 合成 score
```

## 1. 已拍板的决策

| # | 决策 | 选择 | 不选 |
|---|---|---|---|
| D1 | 存储 | 继续文件 YAML，对齐 dd 无数据库 | 不接 Abq-Trading MySQL |
| D2 | 因子表示 | **自有 `FactorExpr` IR**（算子树） | 不 `eval` pandas；不把 Qlib 表达式当运行时 |
| D3 | 预构建规模 | **种子 20–40 个**（动量/反转/波动/量价/大盘相对） | 不整库导入 VT 462 |
| D4 | LLM 挖掘 | 移植 abq 循环：提议 → 解析成 IR → 评测 → 反馈再提 | 不沿用 Abq-Trading 的 `eval(formula)` |
| D5 | 自动发明 | **双轨 GP**：大盘择时用 gplearn；截面选股用面板适应度（DEAP 或自研小引擎） | 不用 vanilla gplearn 直接优化 Rank IC（它看不到「按日分组」） |
| D6 | 大盘怎么进公式 | 大盘字段作为 **broadcast 终端**（当日全市场同一个值）+ 一条独立的择时轨道 | 不只做指数择时、也不只用个股 OHLCV |
| D7 | 过拟合 | LLM / GP / 手写 **同一五道准入**；GP 额外加复杂度惩罚与 walk-forward | 无 AI 免检 |
| D8 | 与分析链路 | 因子是**确定性工具**，不进 system prompt；agent 只拿摘要统计 | 不把因子面板塞进 LLM 上下文 |

## 2. 因子是什么（契约）

### 2.1 记录

```yaml
id: gp_mkt_vol_ratio_001          # ^[a-z][a-z0-9_]+$
name: 量能比相对大盘
kind: factor
origin: gp | llm | catalog | synth
status: candidate                 # 见 §5 状态机
theme: [volume, market]
universe: csi300 | csi500 | market
formula: div(ts_mean(volume,5), ts_mean(mkt_volume,5))
expr:                             # FactorExpr 树（源）
  op: div
  args:
    - {op: ts_mean, args: [{var: volume}, {n: 5}]}
    - {op: ts_mean, args: [{var: mkt_volume}, {n: 5}]}
hypothesis: ""                    # GP 可空；LLM/晋升 live 必须非空
forward_days: 5
metrics: {}                       # 最近一次评测
reject_reason: ""
created_at: ...
updated_at: ...
```

`formula` 是给人看的打印串；**计算只认 `expr` 树**。LLM 输出字符串时，解析器必须先编成树，编失败则丢弃。

### 2.2 面板形状

与 abq / VT 一致：

- 每个字段一张宽表：`index=date`，`columns=symbol`
- 截面因子 `compute(panel) → DataFrame` 同形状
- 择时因子 `universe: market`：输出是 **一条 Series**（按日），不是截面

### 2.3 算子白名单（禁前视）

移植 VT `base.py` 的精神，不搬 462 个文件。

| 类 | 算子 | 约束 |
|---|---|---|
| 算术 | `add sub mul div abs log sign sqrt` | `div` 分母 +ε；`log` 只吃正数否则 NaN |
| 时序 | `delay ts_mean ts_std ts_max ts_min ts_rank delta ts_corr ts_sum` | 窗口 `n≥1`；**禁止负 shift** |
| 截面 | `rank zscore` | 仅 `universe ≠ market` |
| 终端 | `open high low close volume amount` | 个股 |
| 大盘终端 | `mkt_close mkt_open mkt_high mkt_low mkt_volume mkt_amount mkt_advance mkt_decline mkt_limit_up` | 按日 broadcast 到所有列 |

没有 `Ref(x, -n)`，没有任意 Python。解释器是 100 行左右的树遍历，不是 `eval`。

**大盘 terminal 的意义**：GP/LLM 可以发明「相对大盘」公式，例如：

- `div(close, mkt_close)` — 个股相对指数强弱  
- `sub(ts_std(close,20), ts_std(mkt_close,20))` — 特异波动  
- `div(ts_mean(volume,5), ts_mean(mkt_volume,5))` — 量能是否独立于市场  

这就是「根据大盘数据自动发明公式」，同时仍然是**选股因子**。

## 3. 三条发明路径

### 3.1 种子目录（catalog）

手写或从经典文献移植，IR 静态入库，`origin: catalog`，`status` 直接 `passed_auto`（仍跑一遍 Gate 1–3 记 metrics，不豁免样本外）。

建议种子（第一批，不是 462）：

- 动量 / 反转：`mom_5/20/60`，`rev_5`
- 波动 / 振幅：`vol_20`，`high_low_range_20`，`intraday_range`
- 量价：`vol_ratio_5_20`，`amihud_10`，`pv_corr_20`（abq 里进过 paper_tracking）
- 位置：`close_to_high_20`，`ma_bias_20`
- 大盘相对：`excess_mom_20 = sub(mom_20, mkt_mom_20)` 等 4–6 个

来源对照：abq `SEED_FACTORS` + Abq-Trading `_CLASSIC_FACTORS`。公式改写成 `FactorExpr`，不拷贝 Qlib 字符串当运行时。

VT 的 alpha101 / gtja191 **按需**再移植（一条公式一个 PR），不作为 P5 范围。

### 3.2 LLM 挖掘（沿用 abq，收紧执行）

循环与 `quant/factor_lab/run_iteration.py` 同构：

1. 把已有 `formula + metrics + reject_reason` 喂给 LLM  
2. LLM 产出 `{name, category, hypothesis, formula}`（**可打印串**，不是 pandas）  
3. 解析器 → `FactorExpr`；解析失败 / 用了未知算子 → 丢弃  
4. 在截面面板上计算 → 五道准入  
5. 本轮漏斗写成 feedback，进入下一轮  

相对 abq 的改动：

- 算子表换成 §2.3，不再要求 Qlib `Ref/Mean/$close`  
- 必须写 `hypothesis`（Gate 4）；讲不清逻辑的高 IC 直接拒  
- 用现有 `LlmRouter` primary；温度 0.3–0.7；JSON only  
- **禁止** Abq-Trading 那种 `eval(formula, {"__builtins__": {}}, pandas_env)`  

工具：`POST /api/factors/mine/llm`，后台任务，SSE 或轮询 task（dd 目前无 task_manager，P5 用文件 `data/factors/runs/{id}/progress.json` + 可选 SSE `type:factor_mine`）。

### 3.3 GP / 符号回归（新增）

目标：在**不算经济逻辑**的情况下搜索算子树，输出可读公式。GP 的 `hypothesis` 允许空，但 **不能进 `live`**，除非事后由 LLM 或人补逻辑并通过 Gate 4。

#### 为什么不能「只用 gplearn 做选股」

gplearn 的适应度是 `metric(y, y_pred)`，样本互相独立。截面 Rank IC 必须 **按日分组再平均**。把 (date, stock) 拉平后算 Spearman 会混日，统计上是错的。这是硬约束，不是优化细节。

因此拆成两轨：

| 轨 | 样本 | 适应度 | 搜索引擎 | 产出 `universe` |
|---|---|---|---|---|
| **A 大盘择时** | 每个交易日一行 | 公式值 vs 指数未来 N 日收益的 Spearman（可加方向胜率） | **gplearn `SymbolicRegressor`** | `market` |
| **B 截面选股** | 日 × 股票面板 | 日度 Rank IC 均值 / ICIR − λ·复杂度 | **DEAP 或自研树 GP**（`evaluate(tree, panel)`） | `csi300` 等 |

两轨的**树节点集合相同**（§2.3），打印格式相同，入库相同。gplearn 的程序树在跑完后 **转译成 `FactorExpr`**，不要把 gplearn 的 Python 可执行对象存盘。

#### 轨 A：根据大盘数据发明择时公式（你点名的能力）

特征（按日，全是大盘，没有个股）：

- 指数 OHLCV（默认沪深 300，可切上证）  
- 市场宽度：上涨家数、下跌家数、涨停家数（有数据才启用）  
- 已算好的短窗：`ret_1/5/20`、`vol_20`、`ma_bias`、`amount_z`  

gplearn 配置（MVP）：

- `function_set`: add, sub, mul, div, abs, log, sqrt, max, min（再注册 2–3 个无状态变换）  
- `parsimony_coefficient`: 偏短公式  
- `max_depth`: 4–5  
- `metric`: 自定义 Spearman（此时样本=日期，合法）  
- 种群 / 代：小（例如 pop=200, gen=30），单用户本机可跑完  

产出例：`div(ts_std(mkt_volume,20), abs(mkt_close - ts_mean(mkt_close,20)))`  
用途：大盘分析链路的择时分数；**不直接当选股因子**。

过拟合特别狠（一条时间序列）。轨 A **强制**：

- 时间 walk-forward（至少 3 折，中间 gap 等于 `forward_days`）  
- 复杂度上限（节点数 ≤ 12）  
- 与「昨日收益」相关 >0.8 视为作弊，丢弃  

#### 轨 B：截面 GP + 大盘 broadcast

这是把大盘用进**选股**的正路：个股字段 + 大盘字段（同行广播）组成终端，适应度是截面 IC。

实现要点：

- 个体 = `FactorExpr` 树  
- `evaluate`：解释器在面板上算出因子 → Gate 1 的 IC 统计 → 适应度 = `|ic_mean| / (1 + λ * n_nodes)`，OOS 折差过大则罚  
- 变异/交叉只在白名单算子上  
- 与种子 / 已发现因子 `|corr| > 0.7` 的个体适应度归零（搜索期就去重）  

若 P5 时间紧：轨 B 可先做成 **「原语库 + gplearn 只做四则组合」**：先用算子算出 ~40 个原语列（含大盘相对），gplearn 只组合这些列。适应度仍必须自写（按日 IC），这意味着 **不能把 gplearn.fit 当黑盒**，要用 DEAP 包一层，或自己写进化循环、只用 gplearn 的树表示。方案选择：**自研/DEAP 为主，gplearn 负责轨 A 与树的打印习惯**。

#### GP 跑完之后

1. 打印公式 → 解析回 IR（往返必须恒等）  
2. 进 `candidate`，走完整五道准入（不是只看训练适应度）  
3. Gate 4：GP 因子停在 `passed_auto`，等 LLM 补 `hypothesis` 或人工写逻辑才可 `paper_tracking`

## 4. 评测核（三条路径共用）

纯函数，对标 abq `factor_math` + VT `factor_analysis_core`：

| 输出 | 定义 |
|---|---|
| 日度 Rank IC | 截面 Spearman；当日有效股票 <5 或缺失率 >30% 丢弃该日 |
| `ic_mean` / `ic_std` / ICIR / 正 IC 占比 | 有效日上的汇总 |
| 分层净值 | 默认 5 组，多空价差只作展示，不替代 IC 闸门 |
| 择时轨 | 公式 Series vs 指数远期收益的 Spearman（不是 Rank IC） |

预处理：截面 MAD 3 倍 winsorize；**不** `fillna(0)`。标签：未来 N 日收益，默认 N=5，与 abq 一致。

## 5. 五道准入与状态机

直接采用 abq `run_iteration.py` / `factor_lib.py`，阈值可配置，默认：

| 关 | 规则 | 失败去向 |
|---|---|---|
| 1 初筛 | 选股：`\|RankIC\|≥0.02` 且 `\|ICIR\|≥0.25`；择时：`\|IC\|≥0.05`（更严，样本少） | `rejected` |
| 2 去重 | 与库内非 retired 最大 \|相关\| < 0.7 | `rejected`（记 `corr_with`） |
| 3 样本外 | 时间 70/30；OOS 与 IS **同号** 且 \|OOS IC\|≥0.01；择时必须 walk-forward 折平均同号 | `rejected` |
| 4 逻辑 | catalog/LLM：`hypothesis` ≥ 8 字；GP：可暂空，最多到 `passed_auto` | GP 停在 `passed_auto` |
| 5 纸面 | 对合成组合有增量 IC 才 `paper_tracking`；15 日无改进 `frozen`；30 日失效 `retired` | 见状态 |

状态机（与 abq YAML 一致，便于以后把旧 `factors.yaml` 迁过来）：

```
candidate → rejected
          → passed_auto → paper_tracking → live
                       ↘ frozen → (可解冻回 paper_tracking)
          → retired
```

`live` 才允许进分析工具默认集与多因子合成。

**红线**：LLM / GP 与手写同一套阈值。禁止「模型提出的先用着」。

## 6. 合成

移植 Abq-Trading `factor_synthesis` 的三种方法，输入改为「`status in {paper_tracking, live}` 的面板」：

- `equal` / `ic` / `ic_ir`  
- 合成结果本身是一条 `origin: synth` 因子，再走 Gate 1–3  

不在 P5 做回归加权（容易过拟合，且要截面回归基础设施）。

## 7. 数据层（P5 与大盘共用）

因子挖掘需要 **截面面板**，不是单票 `limit=30` 的工具输出。

| 数据 | 来源（dd 已有/待建） | 用途 |
|---|---|---|
| 个股日 K | 现有 qlib + 补洞，扩成宽表 | 截面因子 |
| 指数日 K | 新增 `fetch_index_ohlcv`（沪深300 / 上证） | 大盘终端、择时轨 |
| 市场宽度 | 新增（涨跌家数 / 涨停家数；东财或本地统计） | 大盘终端；缺则降级，不阻塞轨 B |
| 股票池 | 配置：`csi300` 默认；可 `csi500` | 控制计算量 |

面板构建是确定性模块 `app/factors/panel.py`，**不是 LLM 工具**。挖掘任务内部调用；分析时 `compute_factor` 工具可对当前 path 的标的子集计算。

单用户约束：CSI300 × 5 年 × 6 字段可以进内存；全 A 先不做。

## 8. 存储与 API

### 8.1 目录（替换后端设计里单文件 `factors.yaml`）

```
data/factors/
├── catalog/                      # 种子，一因子一 YAML（可 diff）
│   ├── mom_20.yaml
│   └── ...
├── discovered.yaml               # llm / gp / synth（状态机会变，集中一个文件）
├── _index.json                   # id → origin/status/ic_mean 供列表
└── runs/
    └── {runId}/
        ├── meta.json             # llm | gp_market | gp_cs
        ├── progress.json
        ├── candidates.jsonl      # 每一代/每一轮
        └── report.md             # 漏斗摘要
```

种子与 discovered 分开：种子不进「退休」流转；discovered 才走状态机。去重时种子仍参与相关计算（与 abq `SEED_FACTORS` 相同角色）。

### 8.2 API

```
GET    /api/factors                         列表（status/origin/theme）
GET    /api/factors/{id}                    含 formula、metrics、hypothesis
POST   /api/factors                         手写登记（body 必须是合法 FactorExpr）
PUT    /api/factors/{id}                    改 hypothesis / status（人工 Gate 4/5）
DELETE /api/factors/{id}                    非 catalog

POST   /api/factors/eval                    对指定 id 或临时 expr 跑 IC
POST   /api/factors/synthesize              equal | ic | ic_ir

POST   /api/factors/mine/llm                {universe, rounds, k}
POST   /api/factors/mine/gp                 {track: market|cs, generations, ...}
GET    /api/factors/runs/{runId}            进度 + 漏斗
```

分析工具（给 agent，**P5g 已落地** — `app/tools/langchain_tools.py` + `app/factors/agent_tools.py`）：

- `list_factors(status?, theme?, limit?)` — 目录摘要（默认 `live` / `paper_tracking` / `passed_auto`）
- `compute_factor(factor_id, symbol)` — 最新值 + 截面分位（择时因子返回大盘序列最新值）
- `factor_analysis(factor_id)` — 已存 IC / 闸门评测 JSON

已绑定 agent：`tech`、`fundamental`、`judge`（judge 含 `factor_analysis`）。库页「工具」Tab 只读展示上述工具与 guidance。

### 8.3 前端

库页第四 Tab **因子**（P4 的 Agent/提示词/工具保留）：

- 筛选：origin / status / theme  
- 详情：公式、假设、IC 曲线（eval 产物）、闸门原因  
- 操作：跑准入、LLM 挖掘、**GP 发明**（轨 A 大盘择时 / 轨 B 截面选股）、合成  
- 挖掘中：进度条读 `runs/{id}/progress.json`  

不单独做 VT 式 Alpha Zoo 产品页。dd 仍是分析工作台，因子是库资产。

## 9. 和现有编排的衔接

| 场景 | 用法 |
|---|---|
| 单票 | 数据阶段后 `attach_factors`（`passed_auto/live` 截面摘要 → `reports.factor_summary`）；右栏 **单票摘要** 展示因子列表；agent 可 `list_factors` / `compute_factor` 深挖 |
| 大盘 | 择时轨 `universe:market` 的 live 公式值在 **market pipeline** 数据阶段自动挂载；`kind=market` 走指数链路 |
| 对话挖掘 | agent 工具 `start_factor_mine_llm` / `start_factor_mine_gp` + `get_factor_mine_status`（tech / supervisor 已绑定） |

因子计算失败不得阻断主分析：缺数据则 step 标 warning，分析继续。

## 10. 实施分期（把原 P5 拆开）

| 阶段 | 内容 | 依赖 |
|---|---|---|
| **P5a 库内核** | `FactorExpr` 解释器 + 评测核 + YAML 存储 + REST 列表/详情/手写登记 + 库 Tab | 现有 qlib 面板化 |
| **P5b 种子 + 准入** | 20–40 catalog + Gate 1–3 + 人工改 status | P5a |
| **P5c LLM 挖掘** | 提议循环 + 解析器 + 反馈；`mine/llm` | P5b + LlmRouter |
| **P5d 大盘数据 + GP 轨 A** | ✅ gplearn 择时、转译 IR、walk-forward 记录；`mine/gp` | P5b |
| **P5e GP 轨 B** | ✅ MVP | 截面树 GP + 日度 Rank IC 适应度 + 大盘 broadcast 原语；`mine/gp` track=cs | P5d |
| **P5f 合成 + 纸面** | ✅ MVP | equal/ic/ic_ir + Gate 5 增量 IC → paper_tracking；重评 15 日冻结 / 30 日退役 | P5b |
| **P5g 挂分析** | ✅ MVP | 自动挂载 + 摘要面板 + agent 工具 `list_factors` / `compute_factor` / `factor_analysis` | P5b |

建议落地顺序：**P5a → P5b → P5d → P5c → P5e → P5g → P5f**。  
P5g（挂载 + 面板 + agent 工具）已先于 P5f 落地，便于单票分析立刻引用因子库。

## 11. 风险与非目标

**风险**

- 遗传规划极易拟合噪声。没有 Gate 3 / walk-forward 就不要展示「发明成功」。  
- 大盘宽度数据源不稳定：终端做成可选，缺字段时公式里用到则该候选无效。  
- gplearn 多年维护弱：锁版本；树转 IR 单测必须覆盖。  
- LLM 公式幻觉：解析失败是正常漏斗，不是 bug。  

**P5 明确不做**

- 全市场（全 A）挖掘  
- 把 VT 462 因子当种子  
- 实盘下单 / 与 abq L1 结算打通  
- 基本面 PIT 全套（可后续加 `fund:` 终端，对齐 VT）  
- 遗传规划结果自动 `live`

## 12. 代码落点（实施时）

```
backend/app/factors/
  ir.py            # FactorExpr 解析 / 打印 / 校验
  ops.py           # 白名单算子（禁前视）
  eval_ic.py       # Rank IC / 择时 IC / 分层
  gates.py         # 五道准入
  panel.py         # 个股宽表 + 大盘 broadcast
  store.py         # catalog + discovered.yaml
  mine_llm.py      # 提议循环
  mine_gp.py       # 轨 A gplearn 大盘择时
  mine_gp_cs.py    # 轨 B 截面树 GP（自研进化 + 日度 Rank IC）
  attach.py        # 单票自动挂载 factor_summary
  agent_tools.py   # list_factors / compute_factor / factor_analysis
  synth.py         # 等权 / IC / ICIR 合成 + Gate 5
  paper.py         # 纸面冻结 / 退役规则
backend/app/api/factors.py
frontend: LibraryPage 增加 factors tab + 挖掘面板
```

依赖：`gplearn`（轨 A 大盘择时）。轨 B 为自研树 GP，**未引入 DEAP**。不要为了 GP 引入 Julia/PySR。
