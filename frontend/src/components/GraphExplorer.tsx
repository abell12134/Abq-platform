import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  fetchGraphStats,
  fetchGraphSubgraph,
  ingestPolicyUrl,
  syncGraphIncremental,
} from "../api/graph";
import { QueryErrorBanner } from "../components/QueryErrorBanner";
import { GraphForceView } from "./GraphForceView";

interface GraphExplorerProps {
  symbol: string;
  onSymbolChange: (symbol: string) => void;
  onError: (message: string | null) => void;
}

export function GraphExplorer({ symbol, onSymbolChange, onError }: GraphExplorerProps) {
  const [hops, setHops] = useState(1);
  const [info, setInfo] = useState<string | null>(null);
  const [policyUrl, setPolicyUrl] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const queryClient = useQueryClient();

  const statsQuery = useQuery({
    queryKey: ["graph-stats"],
    queryFn: fetchGraphStats,
  });

  const subgraphQuery = useQuery({
    queryKey: ["graph-subgraph", symbol, hops],
    queryFn: () => fetchGraphSubgraph(symbol, hops),
    enabled: Boolean(symbol),
  });

  const updateMut = useMutation({
    mutationFn: (force: boolean) => syncGraphIncremental(symbol, { force }),
    onSuccess: (data) => {
      setInfo(data.summary || "增量更新完成");
      onError(null);
      void queryClient.invalidateQueries({ queryKey: ["graph-stats"] });
      void queryClient.invalidateQueries({ queryKey: ["graph-subgraph"] });
      void queryClient.invalidateQueries({ queryKey: ["knowledge-events"] });
      void queryClient.invalidateQueries({ queryKey: ["knowledge-policy"] });
    },
    onError: (e: Error) => onError(e.message),
  });

  const policyUrlMut = useMutation({
    mutationFn: () =>
      ingestPolicyUrl({
        url: policyUrl.trim(),
        symbol: symbol || undefined,
      }),
    onSuccess: () => {
      onError(null);
      setInfo("政策 URL 已入库");
      setPolicyUrl("");
      void queryClient.invalidateQueries({ queryKey: ["knowledge-policy"] });
      void queryClient.invalidateQueries({ queryKey: ["graph-subgraph"] });
    },
    onError: (e: Error) => onError(e.message),
  });

  const nodes = subgraphQuery.data?.nodes ?? [];
  const edges = subgraphQuery.data?.edges ?? [];

  return (
    <div className="knPanel knGraph">
      <div className="knGraphHead">
        <div>
          <p className="hudLabel">Knowledge graph</p>
          <h3>知识图谱</h3>
        </div>
        {statsQuery.data ? (
          <span className="sub knGraphStats">
            {statsQuery.data.node_count} 节点 · {statsQuery.data.edge_count} 边
          </span>
        ) : null}
      </div>

      <p className="sub knGraphHint">
        默认增量模式：6 小时内不重复爬取；归档与月摘要在无新数据时自动跳过。
      </p>

      {info ? <p className="sub knGraphInfo">{info}</p> : null}

      <div className="knRow knGraphToolbar">
        <label>
          股票代码
          <input
            value={symbol}
            onChange={(e) => onSymbolChange(e.target.value)}
            placeholder="sh600519"
          />
        </label>
        <label>
          关系跳数
          <select value={hops} onChange={(e) => setHops(Number(e.target.value))}>
            <option value={1}>1 跳</option>
            <option value={2}>2 跳</option>
          </select>
        </label>
        <button
          type="button"
          className="libPrimaryBtn knPrimaryAction"
          disabled={updateMut.isPending || !symbol.trim()}
          onClick={() => updateMut.mutate(false)}
        >
          {updateMut.isPending ? "更新中…" : "增量更新"}
        </button>
        <button
          type="button"
          className="knTextBtn"
          onClick={() => setShowAdvanced((v) => !v)}
        >
          {showAdvanced ? "收起高级" : "高级选项"}
        </button>
      </div>

      <QueryErrorBanner
        isError={subgraphQuery.isError}
        error={subgraphQuery.error}
        label="子图加载失败"
      />

      {nodes.length > 0 ? (
        <GraphForceView center={symbol} nodes={nodes} edges={edges} hops={hops} />
      ) : (
        <p className="sub knGraphEmpty">
          {subgraphQuery.isLoading ? "加载子图…" : "暂无关系，点击「增量更新」拉取数据。"}
        </p>
      )}

      {showAdvanced ? (
        <div className="knGraphAdvanced">
          <button
            type="button"
            className="libPrimaryBtn"
            disabled={updateMut.isPending || !symbol.trim()}
            onClick={() => updateMut.mutate(true)}
          >
            强制全量刷新
          </button>
          <div className="knRow">
            <label className="knGrow">
              政策 URL（白名单）
              <input
                value={policyUrl}
                onChange={(e) => setPolicyUrl(e.target.value)}
                placeholder="https://www.csrc.gov.cn/..."
              />
            </label>
            <button
              type="button"
              className="libPrimaryBtn"
              disabled={policyUrlMut.isPending || !policyUrl.trim()}
              onClick={() => policyUrlMut.mutate()}
            >
              抓取入库
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
