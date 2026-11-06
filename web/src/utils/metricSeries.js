// ResultPage passes each metric as [{ name, value, desc }, ...].
// A value may be a number or named series such as 含成本 / 不含成本.
export function metricSeriesHasData(series) {
  return Array.isArray(series) && series.some(point => {
    const value = point?.value;
    if (typeof value === 'number') return Number.isFinite(value);
    return value != null && typeof value === 'object' && !Array.isArray(value)
      && Object.values(value).some(item => typeof item === 'number' && Number.isFinite(item));
  });
}
