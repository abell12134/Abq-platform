export const DEFAULT_OHLCV_LIMIT = 63;

const LIMIT_PRESETS: Array<{ pattern: RegExp; limit: number; label: string }> = [
  { pattern: /半年|6\s*个?月|六个月/, limit: 120, label: "半年" },
  { pattern: /(?:一|1)\s*年|12\s*个?月|十二个月/, limit: 252, label: "1年" },
  { pattern: /3\s*个?月|三个月|一季(?:度)?/, limit: 63, label: "3个月" },
  { pattern: /1\s*个?月|一个月/, limit: 22, label: "1个月" },
];

const N_DAYS_RE = /(?:最近|近|过去)?\s*(\d{1,3})\s*(?:个?交易日?|日|天)/i;

export function parseOhlcvLimit(message = "", focus: string | null = null): number {
  const text = `${message} ${focus ?? ""}`.trim();
  if (!text) return DEFAULT_OHLCV_LIMIT;

  for (const preset of LIMIT_PRESETS) {
    if (preset.pattern.test(text)) return preset.limit;
  }

  const match = text.match(N_DAYS_RE);
  if (match) return Math.max(5, Math.min(400, Number(match[1])));

  return DEFAULT_OHLCV_LIMIT;
}

export function ohlcvWindowLabel(limit: number): string {
  const hit = LIMIT_PRESETS.find((preset) => preset.limit === limit);
  return hit?.label ?? `${limit}日`;
}
