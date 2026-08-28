from __future__ import annotations

from app.graph.models import SubgraphResult
from app.graph.store import graph_store


def _node_label(node_id: str, nodes: dict[str, str]) -> str:
    return nodes.get(node_id, node_id)


def format_subgraph_summary(result: SubgraphResult) -> str:
    if not result.nodes:
        return f"未找到节点 {result.center}，请先执行图谱 bootstrap/sync。"

    labels = {n.id: f"{n.type}:{n.label or n.id}" for n in result.nodes}
    lines = [
        f"中心 {result.center}，{result.hops} 跳，共 {len(result.nodes)} 节点 / {len(result.edges)} 边",
    ]
    for edge in result.edges[:40]:
        lines.append(
            f"- {_node_label(edge.src, labels)} --[{edge.type}]--> {_node_label(edge.dst, labels)}"
        )
    if len(result.edges) > 40:
        lines.append(f"… 另有 {len(result.edges) - 40} 条边未展示")
    return "\n".join(lines)


def query_graph_subgraph(center: str, *, hops: int = 1, max_nodes: int = 60) -> dict:
    graph_store.ensure()
    result = graph_store.subgraph(center, hops=hops, max_nodes=max_nodes)
    return {
        "status": "ok" if result.nodes else "empty",
        "center": result.center,
        "hops": result.hops,
        "node_count": len(result.nodes),
        "edge_count": len(result.edges),
        "nodes": [n.model_dump() for n in result.nodes],
        "edges": [e.model_dump() for e in result.edges],
        "summary": format_subgraph_summary(result),
    }
