export const snapshotSortFields = [
  { value: "symbol", label: "股票代码" },
  { value: "name", label: "股票名称" },
  { value: "pct_chg", label: "涨跌幅", percent: true },
  { value: "turnover", label: "换手率", percent: true },
  { value: "winner_rate", label: "获利筹码比例", percent: true },
  { value: "winner_rate_position_250d", label: "获利筹码250日位置", percent: true },
  { value: "volume", label: "成交量" },
  { value: "amount", label: "成交额" },
  { value: "close", label: "收盘价" },
  { value: "open", label: "开盘价" },
  { value: "high", label: "最高价" },
  { value: "low", label: "最低价" },
  { value: "pe", label: "PE" },
  { value: "pb", label: "PB" },
  { value: "dv_ratio", label: "股息率", percent: true },
  { value: "dv_ttm", label: "TTM 股息率", percent: true },
  { value: "pred_rank", label: "预测排名" },
];

export function snapshotNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function formatSnapshotNumber(value: unknown, digits = 2): string {
  const n = snapshotNumber(value);
  if (n == null) return "-";
  if (Math.abs(n) >= 1e8) return (n / 1e8).toFixed(2) + "亿";
  if (Math.abs(n) >= 1e4) return (n / 1e4).toFixed(2) + "万";
  return n.toFixed(digits);
}
