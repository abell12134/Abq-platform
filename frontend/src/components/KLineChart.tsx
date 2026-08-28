import "./KLineChart.css";

export interface OhlcvBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export function KLineChart({
  bars,
  windowLabel,
}: {
  bars: OhlcvBar[];
  windowLabel?: string;
}) {
  if (!bars.length) return null;

  const w = 360;
  const priceH = 168;
  const volH = 44;
  const h = priceH + volH;
  const padX = 8;
  const padTop = 8;
  const padBottom = 6;

  const lows = bars.map((b) => b.low);
  const highs = bars.map((b) => b.high);
  const minPrice = Math.min(...lows);
  const maxPrice = Math.max(...highs);
  const priceSpan = maxPrice - minPrice || 1;

  const volumes = bars.map((b) => b.volume ?? 0);
  const maxVol = Math.max(...volumes, 1);

  const slot = (w - padX * 2) / bars.length;
  const bodyW = Math.max(2, slot * 0.55);

  const priceY = (value: number) =>
    padTop + (1 - (value - minPrice) / priceSpan) * (priceH - padTop - padBottom);

  const volY = (value: number) => priceH + volH - padBottom - (value / maxVol) * (volH - padBottom - 4);

  const firstDate = bars[0]?.date ?? "";
  const lastDate = bars[bars.length - 1]?.date ?? "";

  return (
    <div className="klineChart">
      <div className="klineChartHd">
        <span>K 线{windowLabel ? ` · ${windowLabel}` : ""}</span>
        <span>
          {firstDate} → {lastDate}
        </span>
      </div>
      <svg className="klineChartSvg" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
        {bars.map((bar, i) => {
          const cx = padX + slot * i + slot / 2;
          const up = bar.close >= bar.open;
          const color = up ? "var(--kline-up)" : "var(--kline-down)";
          const bodyTop = priceY(Math.max(bar.open, bar.close));
          const bodyBottom = priceY(Math.min(bar.open, bar.close));
          const bodyHeight = Math.max(1.2, bodyBottom - bodyTop);
          const vol = bar.volume ?? 0;
          const volTop = volY(vol);

          return (
            <g key={`${bar.date}-${i}`}>
              <line
                className="klineWick"
                x1={cx}
                x2={cx}
                y1={priceY(bar.high)}
                y2={priceY(bar.low)}
                stroke={color}
              />
              <rect
                className="klineBody"
                x={cx - bodyW / 2}
                y={bodyTop}
                width={bodyW}
                height={bodyHeight}
                fill={color}
              />
              {vol > 0 ? (
                <rect
                  className="klineVol"
                  x={cx - bodyW / 2}
                  y={volTop}
                  width={bodyW}
                  height={priceH + volH - padBottom - volTop}
                  fill={color}
                  opacity={0.35}
                />
              ) : null}
            </g>
          );
        })}
        <line
          className="klineSplit"
          x1={padX}
          x2={w - padX}
          y1={priceH}
          y2={priceH}
        />
      </svg>
      <div className="klineChartAxis">
        <span>{maxPrice.toFixed(2)}</span>
        <span>{minPrice.toFixed(2)}</span>
      </div>
    </div>
  );
}
