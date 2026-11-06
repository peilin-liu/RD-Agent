// Shared mapping for native trace messages and script experiment results.
export function qlibDisplayMetrics(metrics = {}) {
  if (!metrics || typeof metrics !== 'object') metrics = {};
  const pick = (key) => metrics[key] === undefined ? null : metrics[key];
  const pair = (suffix) => {
    const withCost = pick(`1day.excess_return_with_cost.${suffix}`);
    const withoutCost = pick(`1day.excess_return_without_cost.${suffix}`);
    return withCost == null && withoutCost == null ? null : { 含成本: withCost, 不含成本: withoutCost };
  };
  return {
    "Rank ICIR": pick("Rank ICIR"),
    "年化超额收益": pair("annualized_return"),
    "信息比率 IR": pair("information_ratio"),
    "最大回撤": pair("max_drawdown"),
    avg_daily_turnover: pick("avg_daily_turnover"),
    total_cost: pick("total_cost"),
    avg_daily_trade_count: pick("avg_daily_trade_count"),
    total_trade_count: pick("total_trade_count"),
    avg_holding_days_per_symbol: pick("avg_holding_days_per_symbol"),
  };
}
