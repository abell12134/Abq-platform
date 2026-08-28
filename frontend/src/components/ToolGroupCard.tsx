import { useState } from "react";
import type { AnalysisStep } from "../types/analysis";
import { agentLabel } from "../lib/agentLabels";

function dataGroupPreview(steps: AnalysisStep[], symbol?: string): string {
  const quoteStep = steps.find((s) => s.agent === "fetch_quote");
  if (quoteStep?.result) {
    try {
      const data = JSON.parse(quoteStep.result) as {
        price?: number;
        pct_change?: number;
        name?: string;
        symbol?: string;
      };
      if (data.price != null) {
        const sym = symbol ?? data.symbol ?? "";
        const pct =
          data.pct_change != null
            ? ` ${data.pct_change > 0 ? "+" : ""}${data.pct_change}%`
            : "";
        return `${data.name ?? sym} · ${data.price}${pct}`;
      }
    } catch {
      /* ignore */
    }
  }
  const labels = steps.map((s) => agentLabel(s.agent)).join(" · ");
  return symbol ? `${symbol} · ${labels}` : labels;
}

export function ToolGroupCard({
  steps,
  symbol,
  defaultCollapsed = true,
}: {
  steps: AnalysisStep[];
  symbol?: string;
  defaultCollapsed?: boolean;
}) {
  const [open, setOpen] = useState(!defaultCollapsed);
  const headline = dataGroupPreview(steps, symbol);

  return (
    <div className="col">
      <div className={`pcard pcard-tool-group ${open ? "pcard-open" : "pcard-collapsed"}`}>
        <button
          type="button"
          className="phd stepToggle"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
        >
          <span className="stepChevron" aria-hidden>
            {open ? "▾" : "▸"}
          </span>
          <span className="kind">data</span>
          <span className="pid">数据阶段</span>
          <span className="stepPreview">{headline}</span>
        </button>
        {open ? (
          <div className="toolGroupBody">
            {steps.map((step) => (
              <div className="toolGroupRow" key={step.id}>
                <span className="toolGroupLabel">{agentLabel(step.agent)}</span>
                <span className="toolGroupMeta">
                  {step.tool_calls[0]?.output_ref ?? "完成"}
                </span>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}
