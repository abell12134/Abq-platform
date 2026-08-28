import "./MemoryHintBanner.css";

interface MemoryHintBannerProps {
  hints: string[];
  summary?: string | null;
  loading?: boolean;
}

export function MemoryHintBanner({ hints, summary, loading }: MemoryHintBannerProps) {
  if (!loading && hints.length === 0) return null;
  return (
    <div className="memoryHintBanner" role="status">
      <div className="memoryHintTitle">
        {loading ? "检索历史记忆…" : summary ?? `命中 ${hints.length} 条历史记忆`}
      </div>
      {!loading ? (
        <ul className="memoryHintList">
          {hints.map((hint) => (
            <li key={hint}>{hint}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
