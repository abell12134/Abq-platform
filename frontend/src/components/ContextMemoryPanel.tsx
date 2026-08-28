import { useQuery } from "@tanstack/react-query";
import { fetchMemoryPreview } from "../api/memory";
import { useUiStore } from "../stores/ui";
import "../pages/pages.css";

export function ContextMemoryPanel() {
  const meta = useUiStore((s) => s.analysisMeta);
  const memoryHints = useUiStore((s) => s.memoryHints);
  const lastMessage = useUiStore((s) => s.messages).filter((m) => m.kind === "user").at(-1)?.text ?? "";

  const { data: preview } = useQuery({
    queryKey: ["memory-preview-ctx", meta.target, meta.kind, lastMessage.slice(0, 80)],
    queryFn: () =>
      fetchMemoryPreview({
        message: lastMessage || "历史研判",
        kind: meta.kind ?? "single",
        symbol: meta.target,
        focus: meta.focus,
      }),
    enabled: Boolean(meta.target || lastMessage.length > 4),
  });

  const hints = memoryHints.length > 0 ? memoryHints : preview?.hints ?? [];

  if (!hints.length) {
    return (
      <section className="ctxBlock ctxBlockFlush">
        <h2>跨会话记忆</h2>
        <p className="ctxMutedLine">暂无预取记忆。问「上次怎么看」或续聊时会自动检索。</p>
      </section>
    );
  }

  return (
    <section className="ctxBlock ctxBlockFlush">
      <div className="ctxBlockHd">
        <h2>跨会话记忆</h2>
        <span className="ctxMutedLine">{preview?.summary ?? `${hints.length} 条`}</span>
      </div>
      <ul className="ctxMemoryList">
        {hints.map((hint) => (
          <li key={hint}>{hint}</li>
        ))}
      </ul>
    </section>
  );
}
