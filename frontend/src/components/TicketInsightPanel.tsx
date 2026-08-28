import { TicketInsightBody } from "./TicketInsightBody";
import "./TicketInsightPanel.css";

interface TicketInsightPanelProps {
  open: boolean;
  onToggle: () => void;
}

export function TicketInsightPanel({ open, onToggle }: TicketInsightPanelProps) {
  if (!open) {
    return (
      <button type="button" className="ticketPanelTab" onClick={onToggle} title="展开单票摘要">
        单票
      </button>
    );
  }

  return (
    <aside className="ticketPanel">
      <header className="ticketPanelHd">
        <span>Quote // 单票摘要</span>
        <button type="button" className="ticketPanelClose" onClick={onToggle} title="收起">
          ×
        </button>
      </header>
      <div className="ticketPanelScroll">
        <TicketInsightBody compact />
      </div>
    </aside>
  );
}
