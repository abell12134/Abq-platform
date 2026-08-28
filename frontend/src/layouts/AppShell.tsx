import { ChatComposer } from "../components/ChatComposer";
import { FactorMineBanner } from "../components/FactorMineBanner";
import { PortfolioInsightPanel } from "../components/PortfolioInsightPanel";
import { TicketInsightPanel } from "../components/TicketInsightPanel";
import { useAppShellComposer } from "../hooks/useAppShellComposer";
import { AgentLibPage } from "../pages/AgentLibPage";
import { ChatPage } from "../pages/ChatPage";
import { ContextPage } from "../pages/ContextPage";
import { PortfolioPage } from "../pages/PortfolioPage";
import { WorkflowPage } from "../pages/WorkflowPage";
import { useUiStore } from "../stores/ui";
import { AppShellHeader } from "./AppShellHeader";
import { AppShellSidebar } from "./AppShellSidebar";
import "./AppShell.css";

export function AppShell() {
  const page = useUiStore((s) => s.page);
  const setPage = useUiStore((s) => s.setPage);
  const sessionTitle = useUiStore((s) => s.sessionTitle);
  const workflowSteps = useUiStore((s) => s.workflowSteps);
  const ticketPanelOpen = useUiStore((s) => s.ticketPanelOpen);
  const setTicketPanelOpen = useUiStore((s) => s.setTicketPanelOpen);
  const portfolioPanelOpen = useUiStore((s) => s.portfolioPanelOpen);
  const setPortfolioPanelOpen = useUiStore((s) => s.setPortfolioPanelOpen);
  const analysisMeta = useUiStore((s) => s.analysisMeta);
  const activePortfolioId = useUiStore((s) => s.activePortfolioId);
  const setActivePortfolioId = useUiStore((s) => s.setActivePortfolioId);

  const { composerProps, llmHealthError, primary, local } = useAppShellComposer();

  const showTicketPanel =
    page === "chat" &&
    analysisMeta.kind === "single" &&
    workflowSteps.some((s) => s.role === "tool" && s.agent === "fetch_quote");

  const showPortfolioPanel =
    page === "chat" &&
    analysisMeta.kind === "portfolio" &&
    workflowSteps.some((s) => s.role === "tool" && s.agent === "fetch_portfolio_quotes");

  const showInsightPanel = showTicketPanel || showPortfolioPanel;
  const insightPanelOpen = showTicketPanel
    ? ticketPanelOpen
    : showPortfolioPanel
      ? portfolioPanelOpen
      : false;

  function toggleInsightPanel() {
    if (showTicketPanel) setTicketPanelOpen(!ticketPanelOpen);
    if (showPortfolioPanel) setPortfolioPanelOpen(!portfolioPanelOpen);
  }

  return (
    <div className="app">
      <AppShellSidebar page={page} onNavigate={setPage} />

      <div className="main">
        <AppShellHeader
          sessionTitle={sessionTitle}
          kind={analysisMeta.kind}
          target={analysisMeta.target}
          focus={analysisMeta.focus}
          showInsightPanel={showInsightPanel}
          insightPanelOpen={insightPanelOpen}
          onToggleInsightPanel={toggleInsightPanel}
          primaryLabel={llmHealthError ? "不可用" : (primary?.label ?? "…")}
          localLabel={llmHealthError ? "不可用" : (local?.model?.split(":")[0] ?? "…")}
          llmOk={Boolean(primary?.ok)}
          localOk={Boolean(local?.ok)}
          llmHealthError={llmHealthError}
        />

        <div className="stage">
          <section className={`page ${page === "chat" ? "show" : ""}`}>
            <div
              className={[
                "chatLayout",
                showInsightPanel ? "hasPanel" : "",
                showInsightPanel && insightPanelOpen ? "panelOpen" : "",
              ]
                .filter(Boolean)
                .join(" ")}
            >
              <div className="chatColumn">
                <ChatPage />
                <FactorMineBanner />
                <ChatComposer {...composerProps} />
              </div>
              {showTicketPanel ? (
                <TicketInsightPanel
                  open={ticketPanelOpen}
                  onToggle={() => setTicketPanelOpen(!ticketPanelOpen)}
                />
              ) : null}
              {showPortfolioPanel ? (
                <PortfolioInsightPanel
                  open={portfolioPanelOpen}
                  onToggle={() => setPortfolioPanelOpen(!portfolioPanelOpen)}
                />
              ) : null}
            </div>
          </section>
          <section className={`page dockedPage ${page === "portfolio" ? "show" : ""}`}>
            <PortfolioPage
              portfolioId={activePortfolioId}
              onPortfolioIdChange={setActivePortfolioId}
            />
          </section>
          <section className={`page dockedPage ${page === "workflow" ? "show" : ""}`}>
            <WorkflowPage />
          </section>
          <section className={`page dockedPage ${page === "context" ? "show" : ""}`}>
            <ContextPage />
          </section>
          <section className={`page dockedPage ${page === "agent-lib" ? "show" : ""}`}>
            <AgentLibPage />
          </section>

          {page !== "chat" && page !== "agent-lib" ? (
            <div className="dock dockGlobal">
              <ChatComposer {...composerProps} />
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
