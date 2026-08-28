import { useUiStore } from "../stores/ui";
import { TicketInsightBody } from "../components/TicketInsightBody";
import "./pages.css";

export function SingleTicketPage() {
  return (
    <div className="pad ticketPage">
      <TicketInsightBody />
    </div>
  );
}

export function CompactionBanner() {
  const snapshots = useUiStore((s) => s.contextSnapshots);
  const latest = snapshots[snapshots.length - 1];
  if (!latest) return null;

  const ratio =
    latest.total_raw_tokens > 0
      ? Math.round((1 - latest.total_compressed_tokens / latest.total_raw_tokens) * 100)
      : 0;

  return (
    <div className="col">
      <div className="compactionBanner">
        <span className="kind">compact</span>
        <span>
          上下文已压缩 {latest.total_raw_tokens.toLocaleString()} →{" "}
          {latest.total_compressed_tokens.toLocaleString()} tokens
          {ratio > 0 ? `（约省 ${ratio}%）` : ""}
        </span>
      </div>
    </div>
  );
}
