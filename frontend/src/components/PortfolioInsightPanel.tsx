import { PortfolioInsightBody } from "./PortfolioInsightBody";
import "./TicketInsightPanel.css";

interface PortfolioInsightPanelProps {
  open: boolean;
  onToggle: () => void;
}

export function PortfolioInsightPanel({ open, onToggle }: PortfolioInsightPanelProps) {
  if (!open) {
    return (
      <button type="button" className="ticketPanelTab" onClick={onToggle} title="展开组合摘要">
        选组
      </button>
    );
  }

  return (
    <aside className="ticketPanel">
      <header className="ticketPanelHd">
        <span>Book // 组合摘要</span>
        <button type="button" className="ticketPanelClose" onClick={onToggle} title="收起">
          ×
        </button>
      </header>
      <div className="ticketPanelScroll">
        <PortfolioInsightBody compact />
      </div>
    </aside>
  );
}
