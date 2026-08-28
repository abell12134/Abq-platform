import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import type { GraphEdge, GraphNode } from "../api/graph";

const TYPE_COLORS: Record<string, string> = {
  Stock: "#e8913a",
  Company: "#d4a574",
  Sector: "#4eae86",
  News: "#7eb6ff",
  Policy: "#c4b5f0",
  Event: "#d0a441",
  Digest: "#fb923c",
  Index: "#8a94a8",
  Macro: "#a78bfa",
};

interface GraphForceViewProps {
  center: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  hops?: number;
  width?: number;
  height?: number;
}

export function GraphForceView({
  center,
  nodes,
  edges,
  hops = 1,
  width,
  height = 400,
}: GraphForceViewProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<{ zoomToFit: (ms?: number, padding?: number) => void } | null>(null);
  const [size, setSize] = useState({ w: width ?? 640, h: height });

  const graphData = useMemo(() => {
    const idSet = new Set(nodes.map((n) => n.id));
    const centerId = center.includes(":") ? center : `stock:${center.toLowerCase()}`;
    return {
      nodes: nodes.map((n) => ({
        id: n.id,
        name: n.label || n.id,
        type: n.type,
        val: n.id === centerId || n.props?.symbol === center ? 3.4 : 1.6,
      })),
      links: edges
        .filter((e) => idSet.has(e.src) && idSet.has(e.dst))
        .map((e) => ({
          source: e.src,
          target: e.dst,
          type: e.type,
        })),
    };
  }, [nodes, edges, center]);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const apply = () => {
      const w = width ?? Math.max(320, el.clientWidth);
      setSize({ w, h: height });
    };
    apply();
    const ro = new ResizeObserver(apply);
    ro.observe(el);
    return () => ro.disconnect();
  }, [width, height]);

  useEffect(() => {
    const t = window.setTimeout(() => graphRef.current?.zoomToFit(400, 48), 320);
    return () => window.clearTimeout(t);
  }, [graphData]);

  if (graphData.nodes.length === 0) {
    return <p className="sub">无力导向图数据</p>;
  }

  return (
    <div className="knForceStage" ref={wrapRef}>
      <div className="knForceHud knForceHudTL">
        <span className="hudLabel">Subgraph</span>
        <strong>{center}</strong>
      </div>
      <div className="knForceHud knForceHudTR">
        <span className="hudLabel"> hops {hops}</span>
        <strong>
          {nodes.length}N · {edges.length}E
        </strong>
      </div>
      <ForceGraph2D
        ref={graphRef as never}
        width={size.w}
        height={size.h}
        backgroundColor="#05060a"
        graphData={graphData}
        nodeLabel={(n) => `${(n as { type?: string }).type}: ${(n as { name?: string }).name}`}
        linkDirectionalArrowLength={3.2}
        linkDirectionalArrowRelPos={1}
        linkDirectionalParticles={1}
        linkDirectionalParticleWidth={1.4}
        linkDirectionalParticleSpeed={0.003}
        linkColor={() => "rgba(232, 145, 58, 0.28)"}
        nodeCanvasObject={(node, ctx, globalScale) => {
          const n = node as { id?: string; name?: string; type?: string; x?: number; y?: number };
          const label = (n.name || n.id || "").slice(0, 16);
          const fontSize = 11 / globalScale;
          const r = Math.sqrt(Math.max(1, (node as { val?: number }).val ?? 1)) * 4.2;
          const color = TYPE_COLORS[n.type || ""] || "#cbd5e1";
          const x = n.x ?? 0;
          const y = n.y ?? 0;
          ctx.save();
          ctx.shadowColor = color;
          ctx.shadowBlur = 14 / globalScale;
          ctx.beginPath();
          ctx.arc(x, y, r, 0, 2 * Math.PI, false);
          ctx.fillStyle = color;
          ctx.fill();
          ctx.restore();
          ctx.beginPath();
          ctx.arc(x, y, r * 0.38, 0, 2 * Math.PI, false);
          ctx.fillStyle = "rgba(255,255,255,0.82)";
          ctx.fill();
          ctx.font = `${fontSize}px "IBM Plex Sans", sans-serif`;
          ctx.fillStyle = "#d7dee8";
          ctx.fillText(label, x + r + 3, y + fontSize * 0.32);
        }}
      />
    </div>
  );
}
