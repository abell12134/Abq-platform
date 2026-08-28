/** Client-side kind guard — keep in sync with backend compose_route heuristics. */
export function detectKind(
  message: string,
  focus: string,
): "market" | "single" | "portfolio" {
  const text = `${message} ${focus}`.trim();
  if (
    /列出.{0,8}组合|有哪些组合|所有组合|我的组合|列出.{0,8}自选|有哪些因子|列出.{0,6}因子|看看因子库|因子库有哪些|因子列表|检索.{0,12}(?:政策|舆情|知识)|搜索.{0,12}(?:政策|舆情|知识)|取消.{0,8}分析|入库|存进知识库/i.test(
      text,
    )
  ) {
    return "single";
  }
  if (
    /因子选股|智能选股|选票|筛票|选出.{0,8}股票|股票筛选|top\s*\d+.*股|沪深\s*300.*选|中证500.*选/i.test(
      text,
    )
  ) {
    return "single";
  }
  if (
    /大盘|市场研判|指数走势|沪深\s*300|上证指数|上证综指|创业板指|全市场|宽基/i.test(text) &&
    !/\d{6}/.test(text)
  ) {
    return "market";
  }
  const codes = text.match(/\b\d{6}\b/g) ?? [];
  if (codes.length >= 2 || /自选|组合|持仓|选组|一篮子/i.test(text)) {
    return "portfolio";
  }
  return "single";
}
