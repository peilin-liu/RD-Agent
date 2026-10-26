import { snapshotNumber, snapshotSortFields } from "./marketSnapshot";

export const screeningFields = snapshotSortFields.filter(field =>
  !["symbol", "name", "winner_rate", "winner_rate_position_250d"].includes(field.value));

export type ScreeningRule = { field: string; min: string; max: string };
export const maScreenPeriods = [5, 20, 60] as const;
export type MADirection = "" | "up" | "flat" | "down";
export type StockScreen = { industry: string; rules: ScreeningRule[]; maDirections: Record<5 | 20 | 60, MADirection> };
export const emptyScreen = (): StockScreen => ({ industry: "", rules: [], maDirections: { 5: "", 20: "", 60: "" } });
export const maDirectionLabels = { up: "向上", flat: "走平", down: "向下" };
export const screenCount = (screen: StockScreen) => screen.rules.length + Number(!!screen.industry)
  + Object.values(screen.maDirections).filter(Boolean).length;
export const copyScreen = (screen: StockScreen): StockScreen => ({
  industry: screen.industry || "", rules: screen.rules.map(rule => ({ ...rule })), maDirections: { ...screen.maDirections },
});

export function screenError(screen: StockScreen): string {
  for (const [index, rule] of screen.rules.entries()) {
    if (!screeningFields.some(field => field.value === rule.field)) return `条件 ${index + 1}：请选择指标`;
    const min = rule.min.trim(), max = rule.max.trim();
    if (!min && !max) return `条件 ${index + 1}：请至少填写一个边界`;
    if ((min && !Number.isFinite(Number(min))) || (max && !Number.isFinite(Number(max)))) {
      return `条件 ${index + 1}：请输入有效数字`;
    }
    if (min && max && Number(min) > Number(max)) return `条件 ${index + 1}：下限不能大于上限`;
  }
  return "";
}

export function matchesScreen(
  industry: string | undefined,
  metrics: Record<string, unknown> | undefined,
  screen: StockScreen,
): boolean {
  if (screen.industry && industry !== screen.industry) return false;
  for (const period of maScreenPeriods) {
    const direction = screen.maDirections[period];
    if (!direction) continue;
    const slope = snapshotNumber(metrics?.[`ma${period}_slope`]);
    if (slope == null) return false;
    const actual = Math.abs(slope) < 1e-8 ? "flat" : slope > 0 ? "up" : "down";
    if (actual !== direction) return false;
  }
  return screen.rules.every(rule => {
    const value = snapshotNumber(metrics?.[rule.field]);
    if (value == null) return false;
    return (!rule.min.trim() || value >= Number(rule.min)) && (!rule.max.trim() || value <= Number(rule.max));
  });
}

export function screeningRuleLabel(rule: ScreeningRule): string {
  const field = screeningFields.find(field => field.value === rule.field);
  const unit = field?.percent ? "%" : "";
  const label = field?.label || rule.field;
  if (rule.min.trim() && rule.max.trim()) return `${label} ${rule.min}${unit} ～ ${rule.max}${unit}`;
  return `${label} ${rule.min.trim() ? "≥" : "≤"} ${rule.min.trim() || rule.max.trim()}${unit}`;
}
