import { snapshotNumber, snapshotSortFields } from "./marketSnapshot";

export type ScreeningField = { value: string; label: string; percent?: boolean; unit?: string; description?: string };
export const chipScreenFields: ScreeningField[] = [
  { value: "winner_rate", label: "获利筹码比例", percent: true, description: "当日获利筹码占比，范围 0～100%。" },
  { value: "winner_rate_position_250d", label: "获利比例250日位置", percent: true, description: "（当日获利比例 − 近250交易日最低值）÷（最高值 − 最低值）×100%。0 为区间最低、100 为最高；历史值全部相同时无有效值。" },
  { value: "winner_rate_change_5d", label: "获利比例5日变化", unit: "个百分点", description: "当日获利比例 − 5个交易日前获利比例。由40%升至60%记作 +20 个百分点；负值表示下降。" },
  { value: "winner_rate_change_20d", label: "获利比例20日变化", unit: "个百分点", description: "当日获利比例 − 20个交易日前获利比例；正值表示增加，负值表示减少。" },
  { value: "chip_concentration_70", label: "70%筹码集中度", percent: true, description: "（85%分位成本 − 15%分位成本）÷ 15%分位成本 ×100%。以成本带下沿为基准，数值越小越集中，可超过100%。" },
  { value: "chip_concentration_90", label: "90%筹码集中度", percent: true, description: "（95%分位成本 − 5%分位成本）÷ 5%分位成本 ×100%。以成本带下沿为基准，数值越小越集中，可超过100%。" },
  { value: "chip_avg_cost_bias", label: "现价相对平均成本偏离", percent: true, description: "（收盘价 ÷ 筹码平均成本 − 1）×100%。0 为成本价，+5 表示高出成本5%，−5 表示低于成本5%。" },
  { value: "chip_median_cost_bias", label: "现价相对中位成本偏离", percent: true, description: "（收盘价 ÷ 50%分位成本 − 1）×100%。正值在成本上方，负值在成本下方。" },
  { value: "chip_band_70_position", label: "现价在70%成本带位置", percent: true, description: "（收盘价 − 15%分位成本）÷（85%分位成本 − 15%分位成本）×100%。0～100 在带内，超过100在上沿之上，小于0在下沿之下；带宽为0时无有效值。" },
  { value: "chip_band_90_position", label: "现价在90%成本带位置", percent: true, description: "（收盘价 − 5%分位成本）÷（95%分位成本 − 5%分位成本）×100%。0～100 在带内，可小于0或大于100；带宽为0时无有效值。" },
];
export const chipFieldsFor = (names: string[]) => chipScreenFields.filter(field => names.includes(field.value));
export const fieldUnit = (field: ScreeningField) => field.unit || (field.percent ? "%" : "");
export const screeningFields: ScreeningField[] = snapshotSortFields.filter(field =>
  !["symbol", "name"].includes(field.value) && !chipScreenFields.some(chip => chip.value === field.value));
// Shared with the chart so every visible MA can be used in the screener.
export const maScreenPeriods = [5, 10, 20, 30, 60, 250, 500];
export const maScreenFields: ScreeningField[] = maScreenPeriods.map(period => ({
  value: `ma${period}_slope`, label: `MA${period} 斜率`,
}));
export function indicatorFieldsFor(names: string[]): ScreeningField[] {
  return [...new Set(names)].filter(value => !chipScreenFields.some(field => field.value === value)).map(value => screeningFields.find(field => field.value === value) || { value, label: value });
}
export type ScreeningRule = { field: string; min: string; max: string };
export type StockScreen = { industries: string[]; maRules: ScreeningRule[]; chipRules: ScreeningRule[]; rules: ScreeningRule[] };
export const emptyScreen = (): StockScreen => ({ industries: [], maRules: [], chipRules: [], rules: [] });
export const screenCount = (screen: StockScreen) => screen.rules.length + screen.maRules.length + (screen.chipRules || []).length + Number(!!screen.industries.length);
export const copyScreen = (screen: StockScreen): StockScreen => ({
  chipRules: (screen.chipRules || []).map(rule => ({ ...rule })),
  industries: [...screen.industries], maRules: screen.maRules.map(rule => ({ ...rule })), rules: screen.rules.map(rule => ({ ...rule })),
});

export function screenError(screen: StockScreen, fields = screeningFields, chips = chipScreenFields): string {
  for (const [label, rules, options] of [
    ["均线", screen.maRules, maScreenFields], ["指标", screen.rules, fields], ["筹码", screen.chipRules || [], chips],
  ] as const) {
    for (const [index, rule] of rules.entries()) {
      const prefix = `${label}条件 ${index + 1}`;
      if (!options.some(field => field.value === rule.field)) return `${prefix}：请选择${label}`;
      const min = rule.min.trim(), max = rule.max.trim();
      if (!min && !max) return `${prefix}：请至少填写一个边界`;
      if ((min && !Number.isFinite(Number(min))) || (max && !Number.isFinite(Number(max)))) return `${prefix}：请输入有效数字`;
      if (min && max && Number(min) > Number(max)) return `${prefix}：下限不能大于上限`;
    }
  }
  return "";
}

export function matchesScreen(industry: string | undefined, metrics: Record<string, unknown> | undefined, screen: StockScreen): boolean {
  if (screen.industries.length && !screen.industries.includes(industry || "")) return false;
  return [...screen.maRules, ...screen.rules, ...(screen.chipRules || [])].every(rule => {
    const value = snapshotNumber(metrics?.[rule.field]);
    if (value == null) return false;
    return (!rule.min.trim() || value >= Number(rule.min)) && (!rule.max.trim() || value <= Number(rule.max));
  });
}

export function screeningRuleLabel(rule: ScreeningRule): string {
  const field = [...screeningFields, ...maScreenFields, ...chipScreenFields].find(field => field.value === rule.field);
  const unit = field ? fieldUnit(field) : "";
  const label = field?.label || rule.field;
  if (rule.min.trim() && rule.max.trim()) return `${label} ${rule.min}${unit} ～ ${rule.max}${unit}`;
  return `${label} ${rule.min.trim() ? "≥" : "≤"} ${rule.min.trim() || rule.max.trim()}${unit}`;
}
