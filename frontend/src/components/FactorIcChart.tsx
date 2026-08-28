import "./FactorIcChart.css";

export interface IcPoint {
  date: string;
  ic: number;
}

export function FactorIcChart({ series }: { series: IcPoint[] }) {
  if (!series.length) {
    return null;
  }

  const values = series.map((p) => p.ic);
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 0);
  const span = max - min || 0.01;
  const w = 280;
  const h = 72;
  const pad = 4;

  const points = series.map((p, i) => {
    const x = pad + (i / Math.max(1, series.length - 1)) * (w - pad * 2);
    const y = pad + (1 - (p.ic - min) / span) * (h - pad * 2);
    return `${x},${y}`;
  });

  const zeroY = pad + (1 - (0 - min) / span) * (h - pad * 2);
  const area = `${pad},${zeroY} ${points.join(" ")} ${w - pad},${zeroY}`;

  return (
    <div className="icChart">
      <div className="icChartHd">
        <span>IC 时序</span>
        <span>
          {series[0]?.date} → {series[series.length - 1]?.date}
        </span>
      </div>
      <svg className="icChartSvg" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
        <line className="icChartZero" x1={pad} x2={w - pad} y1={zeroY} y2={zeroY} />
        <polygon className="icChartArea" points={area} />
        <polyline className="icChartLine" points={points.join(" ")} />
      </svg>
    </div>
  );
}
