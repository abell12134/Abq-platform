# ABQ Platform Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e .
uvicorn app.main:app --reload --port 8000
```

- Health: http://127.0.0.1:8000/api/health
- OpenAPI: http://127.0.0.1:8000/docs

前端开发时 Vite 将 `/api` 代理到 `http://127.0.0.1:8000`（见 `frontend/vite.config.ts`）。

## CLI

```bash
abq-memory reindex [all|paths]   # 重建 memory 向量索引
abq-memory count

abq-graph sync-market             # 北向/两融/宏观/大盘快照
abq-graph policy-sync             # 政策列表增量入库
abq-graph maintenance             # jsonl gzip + 月 Rollup + 政策同步
abq-graph rotate                  # 仅 jsonl 按月归档
```

## 图谱 API（R3）

| 方法 | 路径 |
|---|---|
| `GET` | `/api/graph/stats` |
| `GET` | `/api/graph/subgraph?center=sh600519&hops=1` |
| `POST` | `/api/graph/bootstrap` |
| `POST` | `/api/graph/sync` |
| `POST` | `/api/graph/sync/market` |
| `POST` | `/api/graph/rollup` |
| `POST` | `/api/graph/policy/sync` |
| `POST` | `/api/graph/maintenance` |

详见 [docs/KNOWLEDGE_GRAPH_PLAN.md](../docs/KNOWLEDGE_GRAPH_PLAN.md)。
