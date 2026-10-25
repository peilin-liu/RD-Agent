export type ChipLayer = {
  key: string;
  label: string;
  color: string;
  fields: string[];
  band?: [string, string];
  rate?: boolean;
};

export const chipLayers: ChipLayer[] = [
  { key: "weight_avg", label: "筹码平均成本", color: "#00897b", fields: ["weight_avg"] },
  { key: "band_70", label: "70% 成本带", color: "#00897b", fields: ["cost_15pct", "cost_85pct"], band: ["cost_15pct", "cost_85pct"] },
  { key: "winner_rate", label: "获利筹码比例", color: "#2a9d8f", fields: ["winner_rate"], rate: true },
  { key: "cost_50pct", label: "成本中位数", color: "#8d6e63", fields: ["cost_50pct"] },
  { key: "band_90", label: "90% 成本带", color: "#5470c6", fields: ["cost_5pct", "cost_95pct"], band: ["cost_5pct", "cost_95pct"] },
  { key: "cost_5pct", label: "5% 成本", color: "#64b5f6", fields: ["cost_5pct"] },
  { key: "cost_15pct", label: "15% 成本", color: "#4db6ac", fields: ["cost_15pct"] },
  { key: "cost_85pct", label: "85% 成本", color: "#26a69a", fields: ["cost_85pct"] },
  { key: "cost_95pct", label: "95% 成本", color: "#7986cb", fields: ["cost_95pct"] },
  { key: "his_low", label: "历史最低", color: "#90a4ae", fields: ["his_low"] },
  { key: "his_high", label: "历史最高", color: "#607d8b", fields: ["his_high"] },
];

export function chipNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
