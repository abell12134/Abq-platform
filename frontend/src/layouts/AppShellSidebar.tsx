import type { PageId } from "../types/analysis";
import { SessionList } from "../components/SessionList";
import "./AppShellSidebar.css";

const NAV: { id: PageId; label: string; icon: string }[] = [
  { id: "chat", label: "对话", icon: "◉" },
  { id: "portfolio", label: "选组", icon: "◎" },
  { id: "workflow", label: "工作流", icon: "≡" },
  { id: "context", label: "上下文", icon: "◫" },
  { id: "agent-lib", label: "库", icon: "▣" },
];

interface AppShellSidebarProps {
  page: PageId;
  onNavigate: (page: PageId) => void;
}

export function AppShellSidebar({ page, onNavigate }: AppShellSidebarProps) {
  return (
    <aside className="shell">
      <div className="brand">
        <i>//</i>
        <div className="brandText">
          <strong>
            ABQ<span className="brandSlash">//</span>Lab
          </strong>
          <span className="brandSub">A股分析工作台</span>
        </div>
      </div>
      <nav className="nav">
        {NAV.map((item) => (
          <button
            key={item.id}
            type="button"
            className={page === item.id ? "active" : ""}
            onClick={() => onNavigate(item.id)}
          >
            <span>{item.icon}</span>
            {item.label}
          </button>
        ))}
      </nav>
      <SessionList />
      <div className="shellFt" title="ABQ Lab">
        <span>ABQ// v0.1</span>
        <span>编排引擎</span>
      </div>
    </aside>
  );
}
