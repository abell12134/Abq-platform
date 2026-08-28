import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  fetchKnowledgeEvents,
  fetchPolicyDocuments,
  reindexMemory,
  searchMemory,
  uploadPolicyDocument,
} from "../api/knowledge";
import { QueryErrorBanner } from "../components/QueryErrorBanner";
import { GraphExplorer } from "../components/GraphExplorer";
import "./KnowledgeLibrary.css";
import "./LibraryPage.css";

type KnTab = "archive" | "graph" | "search";

export function KnowledgeLibrary() {
  const [tab, setTab] = useState<KnTab>("graph");
  const [symbol, setSymbol] = useState("sh600519");
  const [eventType, setEventType] = useState<"sentiment" | "announcement" | "breadth">(
    "sentiment",
  );
  const [searchQ, setSearchQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [searchResult, setSearchResult] = useState<Awaited<ReturnType<typeof searchMemory>> | null>(
    null,
  );
  const queryClient = useQueryClient();

  const eventsQuery = useQuery({
    queryKey: ["knowledge-events", eventType, symbol],
    queryFn: () => fetchKnowledgeEvents(eventType, symbol || undefined),
    enabled: tab === "archive" && (eventType === "breadth" || Boolean(symbol)),
  });

  const policyQuery = useQuery({
    queryKey: ["knowledge-policy"],
    queryFn: fetchPolicyDocuments,
    enabled: tab === "archive",
  });

  const reindexMut = useMutation({
    mutationFn: () => reindexMemory("all"),
    onError: (e: Error) => setError(e.message),
  });

  const uploadMut = useMutation({
    mutationFn: (file: File) => uploadPolicyDocument(file, { symbol: symbol || undefined }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["knowledge-policy"] });
      setError(null);
    },
    onError: (e: Error) => setError(e.message),
  });

  async function handleSearch() {
    if (!searchQ.trim()) return;
    try {
      const res = await searchMemory(searchQ, {
        namespace: "knowledge",
        symbol: symbol || undefined,
        type: "policy",
      });
      setSearchResult(res);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "检索失败");
    }
  }

  return (
    <section className="knLib">
      <div className="knTopBar">
        <div className="knTabs">
          {(
            [
              ["graph", "图谱"],
              ["archive", "归档"],
              ["search", "检索"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              className={tab === id ? "knTab knTabActive" : "knTab"}
              onClick={() => setTab(id)}
            >
              {label}
            </button>
          ))}
        </div>
        <label className="knSymbolField">
          代码
          <input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="sh600519"
          />
        </label>
      </div>

      {error ? <div className="libErr">{error}</div> : null}

      {tab === "graph" ? (
        <GraphExplorer symbol={symbol} onSymbolChange={setSymbol} onError={setError} />
      ) : null}

      {tab === "archive" ? (
        <div className="knArchiveGrid">
          <div className="knPanel">
            <h3>事件归档</h3>
            <div className="knRow">
              <label>
                类型
                <select
                  value={eventType}
                  onChange={(e) =>
                    setEventType(e.target.value as "sentiment" | "announcement" | "breadth")
                  }
                >
                  <option value="sentiment">舆情</option>
                  <option value="announcement">公告</option>
                  <option value="breadth">大盘宽度</option>
                </select>
              </label>
            </div>
            <QueryErrorBanner
              isError={eventsQuery.isError}
              error={eventsQuery.error}
              label="事件加载失败"
            />
            <ul className="knList">
              {(eventsQuery.data ?? []).slice(0, 20).map((ev) => (
                <li key={ev.id}>
                  <time>{ev.ts.slice(0, 16).replace("T", " ")}</time>
                  <span>{ev.summary}</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="knPanel">
            <h3>政策文档</h3>
            <label className="knFile">
              上传 PDF / MD / TXT
              <input
                type="file"
                accept=".pdf,.md,.txt,.markdown"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) uploadMut.mutate(f);
                  e.target.value = "";
                }}
              />
            </label>
            {uploadMut.isPending ? <p className="sub">入库中…</p> : null}
            <QueryErrorBanner
              isError={policyQuery.isError}
              error={policyQuery.error}
              label="政策列表加载失败"
            />
            <ul className="knList">
              {(policyQuery.data ?? []).slice(0, 15).map((doc) => (
                <li key={doc.id}>
                  <strong>{doc.title}</strong>
                  <span className="sub">
                    {doc.chunk_count} 块 · {doc.uploaded_at.slice(0, 10)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      ) : null}

      {tab === "search" ? (
        <div className="knPanel knSearch">
          <h3>语义检索</h3>
          <div className="knSearchRow">
            <input
              value={searchQ}
              onChange={(e) => setSearchQ(e.target.value)}
              placeholder="检索政策、舆情摘要…"
              onKeyDown={(e) => {
                if (e.key === "Enter") void handleSearch();
              }}
            />
            <button type="button" className="libPrimaryBtn" onClick={() => void handleSearch()}>
              检索
            </button>
          </div>
          {searchResult ? <p className="sub">{searchResult.summary}</p> : null}
          <ul className="knList">
            {(searchResult?.hits ?? []).map((h, i) => (
              <li key={`${h.path_id ?? i}`}>
                <span>{h.judge_one_liner ?? h.text}</span>
                {h.score != null ? <em>{h.score.toFixed(3)}</em> : null}
              </li>
            ))}
          </ul>
          <p className="sub knSearchFoot">
            <button
              type="button"
              className="knTextBtn"
              disabled={reindexMut.isPending}
              onClick={() => reindexMut.mutate()}
            >
              {reindexMut.isPending ? "重建索引中…" : "重建向量索引"}
            </button>
          </p>
        </div>
      ) : null}
    </section>
  );
}
