/** Display names for agents and tools in the UI */
export const AGENT_LABELS: Record<string, string> = {
  supervisor: "编排",
  tech: "技术面",
  fundamental: "基本面",
  sentiment: "舆情",
  market: "大盘研判",
  portfolio: "组合诊断",
  judge: "综合研判",
  bull: "看多",
  bear: "看空",
  fetch_ohlcv: "取数",
  fetch_quote: "实时价",
  clean_data: "清洗",
  calc_indicator: "指标",
  fetch_fundamentals: "基本面数据",
  fetch_sentiment: "舆情数据",
  fetch_market_breadth: "市场宽度",
  fetch_sector_pulse: "板块脉冲",
  fetch_portfolio_quotes: "组合行情",
  start_factor_mine_llm: "LLM挖掘",
  start_factor_mine_gp: "GP挖掘",
  get_factor_mine_status: "挖掘进度",
  run_factor_screen: "因子选股",
  apply_screen_to_portfolio: "导入选组",
  list_portfolios: "组合列表",
  update_portfolio: "更新组合",
  cancel_analysis: "取消分析",
  ingest_policy_text: "政策入库",
  search_knowledge: "知识检索",
};

export function agentLabel(id: string): string {
  return AGENT_LABELS[id] ?? id;
}
