from __future__ import annotations

import asyncio
import sys

from app.memory.indexer import reindex_all
from app.memory.store import memory_store


def memory_main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "reindex"
    if cmd == "reindex":
        scope = sys.argv[2] if len(sys.argv) > 2 else "all"
        result = asyncio.run(reindex_all(scope=scope))
        print(result)
        return
    if cmd == "count":
        memory_store.ensure()
        print({"total_items": memory_store.count()})
        return
    print("Usage: abq-memory [reindex [all|paths]|count]")


def graph_main() -> None:
    cmd = sys.argv[2] if len(sys.argv) > 2 else "help"
    if cmd == "sync-market":
        from app.graph.sync import sync_market_layer

        print(asyncio.run(sync_market_layer()))
        return
    if cmd == "policy-sync":
        from app.knowledge.policy_sync import sync_policy_sources

        print(asyncio.run(sync_policy_sources()))
        return
    if cmd == "maintenance":
        from app.graph.maintenance import run_scheduled_maintenance

        print(asyncio.run(run_scheduled_maintenance()))
        return
    if cmd == "rotate":
        from app.graph.maintenance import rotate_jsonl_archives

        print(rotate_jsonl_archives())
        return
    if cmd == "csi300-month":
        from app.graph.batch_sync import sync_csi300_month

        period = sys.argv[3] if len(sys.argv) > 3 else None
        force = "--force" in sys.argv
        print(asyncio.run(sync_csi300_month(period=period, force=force)))
        return
    print(
        "Usage: abq-graph <sync-market|policy-sync|maintenance|rotate|csi300-month> [--force]\n"
        "  sync-market     — 北向/两融/宏观/大盘快照\n"
        "  policy-sync     — 证监会等政策列表增量入库\n"
        "  maintenance     — 归档+jsonl rotate+月rollup+政策同步\n"
        "  rotate          — 仅 jsonl 按月 gzip 归档\n"
        "  csi300-month    — CSI300 全成分同步 + 板块/大盘月 Rollup（可选 YYYY-MM）"
    )
