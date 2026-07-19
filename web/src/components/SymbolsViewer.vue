<template>
  <div class="symbols-viewer">
    <div class="controls-row">
      <el-select-v2
        v-model="selectedSymbol"
        :options="symbolOptions"
        filterable
        placeholder="Search symbol..."
        :loading="symbolsLoading"
        @change="onSymbolChange"
        style="width:240px"
      />
      <el-date-picker v-model="startDate" type="date" placeholder="Start" value-format="YYYY-MM-DD" @change="onDateChange" style="margin-left:12px;width:150px" />
      <span style="margin:0 6px">~</span>
      <el-date-picker v-model="endDate" type="date" placeholder="End" value-format="YYYY-MM-DD" @change="onDateChange" style="width:150px" />
      <el-checkbox v-model="adjust" @change="onAdjustChange" style="margin-left:12px">Adjusted prices</el-checkbox>
      <span class="hint">ohlcv + tech fields from ~/.rd-agent/config.json</span>
      <el-button type="primary" @click="fetchData" :loading="dataLoading" style="margin-left:12px">Load</el-button>
      <span v-if="errorMsg" class="error-msg">{{ errorMsg }}</span>
    </div>

    <div class="indicator-tags" v-if="rawData.length">
      <span class="row-label">MA</span>
      <el-tag
        v-for="p in maPeriods" :key="p"
        :color="enabledMA.has(p) ? maColor(p) : undefined"
        :effect="enabledMA.has(p) ? 'dark' : 'plain'"
        :style="enabledMA.has(p) ? `color:#fff;border-color:transparent` : `color:${maColor(p)}`"
        @click="toggleMA(p)"
        class="ind-tag"
      >MA{{ p }}</el-tag>
    </div>

    <div ref="chartDom" class="chart-container" v-loading="dataLoading"></div>

    <div class="indicator-tags lower-tags" v-if="rawData.length">
      <span class="row-label">Indicator</span>
      <el-tag
        v-for="f in indicatorFields" :key="f"
        :color="enabledIndicators.has(f) ? indColor(f) : undefined"
        :effect="enabledIndicators.has(f) ? 'dark' : 'plain'"
        :style="enabledIndicators.has(f) ? 'color:#fff;border-color:transparent' : ''"
        @click="toggleIndicator(f)"
        class="ind-tag"
      >{{ f }}</el-tag>
      <span v-if="!indicatorFields.length" class="row-empty">no indicator fields</span>
    </div>

    <div class="indicator-tags lower-tags" v-if="rawData.length && pitFactorFields.length">
      <span class="row-label">PIT</span>
      <el-tag
        v-for="f in pitFactorFields" :key="`pit_${f}`"
        :color="enabledPit.has(f) ? pitColor(f) : undefined"
        :effect="enabledPit.has(f) ? 'dark' : 'plain'"
        :style="enabledPit.has(f) ? 'color:#fff;border-color:transparent' : ''"
        @click="togglePit(f)"
        class="ind-tag"
      >{{ f }}{{ pitOverlayFields.includes(f) ? ' ⓘ' : '' }}</el-tag>
      <span class="row-empty">ⓘ = overlay on K-line; others in indicator panel</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from "vue";
import { getSymbols, getOHLCV } from "@/utils/api";
import * as echarts from "echarts";

const props = defineProps<{ region: string }>();

const symbols = ref<Array<{ symbol: string; name: string; listing_date?: string }>>([]);
const symbolOptions = computed(() =>
  symbols.value.map(s => ({ label: `${s.symbol}  ${s.name}`, value: s.symbol }))
);
const symbolsLoading = ref(false);
const selectedSymbol = ref("");
const startDate = ref<string | null>(new Date(Date.now() - 365 * 24 * 3600 * 1000).toISOString().slice(0, 10));
const endDate = ref<string | null>(new Date().toISOString().slice(0, 10));
const dataLoading = ref(false);
const errorMsg = ref("");
const adjust = ref(false);

const CORE_FIELDS = ["open", "high", "low", "close"];
const maPeriods = [5, 10, 20, 30, 60, 250];
const enabledMA = ref<Set<number>>(new Set([5, 10, 20]));
// Fixed color per MA period so the tag and the overlay line share the same
// color, making it easy to tell MA types apart on the chart.
const MA_COLORS: Record<number, string> = {
  5: "#ee6666",
  10: "#fac858",
  20: "#5470c6",
  30: "#91cc75",
  60: "#73c0de",
  250: "#9a60b4",
};
function maColor(p: number): string {
  return MA_COLORS[p] || "#999";
}

// Stable color per indicator field (by index in indicatorFields) so tag and line match.
const IND_PALETTE = [
  "#5470c6", "#91cc75", "#fac858", "#ee6666", "#73c0de",
  "#3ba272", "#fc8452", "#9a60b4", "#ea7ccc", "#5ab1ef",
  "#d87c7c", "#8d98b3", "#e5cf0d", "#97b552", "#95706d",
];
function indColor(f: string): string {
  const i = indicatorFields.value.indexOf(f);
  return IND_PALETTE[(i < 0 ? 0 : i) % IND_PALETTE.length];
}

const ohlcvFields = ref<string[]>([]);
const indicatorFields = ref<string[]>([]);
const enabledIndicators = ref<Set<string>>(new Set());
const pitFactorFields = ref<string[]>([]);
const pitOverlayFields = ref<string[]>([]);
const enabledPit = ref<Set<string>>(new Set());

// PIT palette (distinct from tech indicator palette). Color by index in
// pitFactorFields so tag and line match.
const PIT_PALETTE = [
  "#ee6666", "#73c0de", "#3ba272", "#fc8452", "#9a60b4",
  "#ea7ccc", "#5ab1ef", "#d87c7c", "#e5cf0d", "#97b552",
  "#95706d", "#c4ccd3", "#f5994e", "#7f9eb2", "#bda29a",
];
function pitColor(f: string): string {
  const i = pitFactorFields.value.indexOf(f);
  return PIT_PALETTE[(i < 0 ? 0 : i) % PIT_PALETTE.length];
}

const rawData = ref<Record<string, any>[]>([]);
// Full fetched data including a lookback buffer before the user's start date,
// so long moving averages (e.g. MA250) can be computed. `rawData` is the
// displayed slice (date >= userStart); `rawDataFull` is used only for MA calc.
const rawDataFull = ref<Record<string, any>[]>([]);
const userStart = ref<string>("");
const chartDom = ref<HTMLElement | null>(null);
let chartInstance: echarts.ECharts | null = null;

onMounted(() => {
  loadSymbols();
  window.addEventListener("resize", resizeChart);
  chartDom.value?.addEventListener("wheel", onChartWheel, { passive: false });
});
onBeforeUnmount(() => {
  window.removeEventListener("resize", resizeChart);
  chartDom.value?.removeEventListener("wheel", onChartWheel);
  if (chartInstance) { chartInstance.dispose(); chartInstance = null; }
});

function resizeChart() { if (chartInstance) chartInstance.resize(); }

function fmtNum(v: any): string {
  if (v == null || v === "") return "-";
  const n = Number(v);
  if (isNaN(n)) return String(v);
  return Math.abs(n) >= 1000 ? n.toLocaleString() : n.toFixed(2);
}

// Pinch (trackpad ctrl+wheel) zooms the chart; plain wheel scrolls the page.
function onChartWheel(e: WheelEvent) {
  if (!chartInstance || !e.ctrlKey) return;
  e.preventDefault();
  const opt = chartInstance.getOption() as any;
  const dz = opt?.dataZoom?.[0];
  let start = typeof dz?.start === "number" ? dz.start : 0;
  let end = typeof dz?.end === "number" ? dz.end : 100;
  const range = Math.max(0.5, end - start);
  const factor = e.deltaY > 0 ? 1.2 : 1 / 1.2;
  const center = (start + end) / 2;
  let newRange = Math.min(100, Math.max(0.5, range * factor));
  let ns = center - newRange / 2;
  let ne = center + newRange / 2;
  if (ns < 0) { ns = 0; ne = newRange; }
  if (ne > 100) { ne = 100; ns = 100 - newRange; }
  chartInstance.dispatchAction({ type: "dataZoom", start: ns, end: ne });
}

watch(() => props.region, () => {
  selectedSymbol.value = "";
  rawData.value = [];
  rawDataFull.value = [];
  userStart.value = "";
  ohlcvFields.value = [];
  indicatorFields.value = [];
  enabledIndicators.value = new Set();
  pitFactorFields.value = [];
  pitOverlayFields.value = [];
  enabledPit.value = new Set();
  if (chartInstance) { chartInstance.dispose(); chartInstance = null; }
  loadSymbols();
});

async function loadSymbols() {
  symbolsLoading.value = true;
  errorMsg.value = "";
  try {
    const res = await getSymbols(props.region);
    if (Array.isArray(res)) {
      symbols.value = res;
    } else {
      symbols.value = [];
      errorMsg.value = "Failed to load symbols: " + ((res as any)?.error || "invalid response");
    }
  } catch (e: any) {
    symbols.value = [];
    errorMsg.value = "Failed to load symbols: " + (e?.message || e);
  } finally {
    symbolsLoading.value = false;
  }
}

function onSymbolChange() { fetchData(); }
function onDateChange() { if (selectedSymbol.value) fetchData(); }
function onAdjustChange() { if (selectedSymbol.value) fetchData(); }

async function fetchData() {
  if (!selectedSymbol.value) return;
  errorMsg.value = "";
  dataLoading.value = true;
  try {
    const start = startDate.value || "2024-01-01";
    const end = endDate.value || "2024-12-31";
    userStart.value = start;
    // Lookback buffer so long MAs (MA250) have enough history to form. Fetch
    // ~1.6x the longest MA period in calendar days before the user's start.
    const maxMA = Math.max(...maPeriods);
    const lookbackDays = Math.ceil(maxMA * 1.6);
    const fetchStart = new Date(start);
    fetchStart.setDate(fetchStart.getDate() - lookbackDays);
    const fetchStartStr = fetchStart.toISOString().slice(0, 10);
    // Send empty fields -> backend uses ohlcv_fields + tech_fields from ~/.rd-agent/config.json.
    // PIT factors are opt-in (slow P() operator): pass enabled PIT keys via pitFields.
    const pitKeys = Array.from(enabledPit.value);
    const res = await getOHLCV(props.region, [selectedSymbol.value], [], fetchStartStr, end, adjust.value, pitKeys);
    if (!res.columns || !res.data) { errorMsg.value = "Invalid response from server"; return; }
    const rows = res.data.map((row: any[]) => Object.fromEntries(res.columns.map((c: string, i: number) => [c, row[i]])));
    const normalized = rows.map((r: Record<string, any>) => {
      const nr: Record<string, any> = {};
      for (const k of Object.keys(r)) nr[k.startsWith("$") ? k.slice(1) : k] = r[k];
      return nr;
    });
    rawDataFull.value = normalized;
    // Displayed slice: only dates within the user's selected [start, end] window.
    rawData.value = normalized.filter((r) => r.date >= start && r.date <= end);
    const strip = (arr: any[]) => (arr || []).map((s: string) => s.startsWith("$") ? s.slice(1) : s);
    const ohlcv = strip(res.ohlcv_fields || []);
    const tech = strip(res.tech_fields || []);
    const pit = strip(res.pit_factors || []);
    const pitOv = strip(res.pit_overlay_fields || []);
    // ohlcv_fields order convention: [open, high, low, close, ...extras]
    ohlcvFields.value = ohlcv;
    indicatorFields.value = tech;
    pitFactorFields.value = pit;
    pitOverlayFields.value = pitOv;
    const ind = new Set<string>();
    enabledIndicators.value = ind;
    await nextTick();
    renderChart();
  } catch (e: any) {
    errorMsg.value = e?.message || String(e);
  } finally {
    dataLoading.value = false;
  }
}

function toggleMA(p: number) {
  const s = new Set(enabledMA.value);
  if (s.has(p)) s.delete(p); else s.add(p);
  enabledMA.value = s;
  renderChart();
}
function toggleIndicator(f: string) {
  const s = new Set(enabledIndicators.value);
  if (s.has(f)) s.delete(f); else s.add(f);
  enabledIndicators.value = s;
  renderChart();
}
function togglePit(f: string) {
  const s = new Set(enabledPit.value);
  if (s.has(f)) s.delete(f); else s.add(f);
  enabledPit.value = s;
  // PIT data is not loaded by default; refetch with the newly enabled PIT keys.
  fetchData();
}

function calcMA(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  for (let i = period - 1; i < values.length; i++) {
    let s = 0;
    for (let j = i - period + 1; j <= i; j++) s += values[j];
    out[i] = +(s / period).toFixed(4);
  }
  return out;
}

function renderChart() {
  if (!chartDom.value || !rawData.value.length) return;
  if (!chartInstance) chartInstance = echarts.init(chartDom.value);

  const dates = rawData.value.map((r) => r.date);
  // Map OHLC by position from ohlcv_fields (supports expressions like $open/$factor)
  const ohlcv = ohlcvFields.value;
  const openK = ohlcv[0], highK = ohlcv[1], lowK = ohlcv[2], closeK = ohlcv[3];
  const hasOHLC = ohlcv.length >= 4;
  const candleData = rawData.value.map((r) => [r[openK], r[closeK], r[lowK], r[highK]]);
  const upDown = rawData.value.map((r) => Number(r[closeK]) >= Number(r[openK]));
  const closes = rawData.value.map((r) => Number(r[closeK]));

  const indicators = indicatorFields.value.filter((f) => enabledIndicators.value.has(f));
  const overlayPit = pitFactorFields.value.filter((f) => enabledPit.value.has(f) && pitOverlayFields.value.includes(f));
  const lowerPit = pitFactorFields.value.filter((f) => enabledPit.value.has(f) && !pitOverlayFields.value.includes(f));
  const maList = maPeriods.filter((p) => enabledMA.value.has(p));

  // MA uses the full lookback data (rawDataFull) so long periods (MA250) have
  // enough history, then slices to the displayed window. `rawData` is a
  // date-filtered contiguous tail of rawDataFull, so offset aligns them.
  const fullCloses = rawDataFull.value.map((r) => Number(r[closeK]));
  const offset = Math.max(0, rawDataFull.value.findIndex((r) => r.date >= userStart.value));

  // yAxis index plan:
  //   0                          -> grid0 price (left)
  //   1 .. overlayPit.length     -> grid0 right (overlay, one per factor with offset)
  //   overlayAxes+1              -> grid1 base (always present)
  //   overlayAxes+2 ..           -> grid1 extras for indicators + lowerPit
  const overlayAxes = overlayPit.length;
  const lowerAll = [...indicators, ...lowerPit];

  const legendData: string[] = [];
  const series: echarts.SeriesOption[] = [];

  if (hasOHLC) {
    series.push({
      name: "K", type: "candlestick", data: candleData, xAxisIndex: 0, yAxisIndex: 0,
      dimensions: ["open", "close", "low", "high"],
      itemStyle: { color: "#ef232a", color0: "#14b143", borderColor: "#ef232a", borderColor0: "#14b143" },
    } as any);
  } else {
    series.push({ name: "close", type: "line", data: closes, xAxisIndex: 0, yAxisIndex: 0, symbol: "none" } as any);
    legendData.push("close");
  }

  // MA overlays on K-line (price axis). Line color matches the MA tag color.
  maList.forEach((p) => {
    legendData.push(`MA${p}`);
    const col = maColor(p);
    const fullMA = calcMA(fullCloses, p).slice(offset);
    series.push({
      name: `MA${p}`, type: "line", data: fullMA, xAxisIndex: 0, yAxisIndex: 0,
      symbol: "none", lineStyle: { width: 1.5, color: col },
      itemStyle: { color: col },
    } as any);
  });

  // PIT overlay on K-line (right-side secondary axes, e.g. PE_MA60/PB_MA60).
  overlayPit.forEach((f, i) => {
    legendData.push(f);
    const col = pitColor(f);
    series.push({
      name: f, type: "line", data: rawData.value.map((r) => r[f]),
      xAxisIndex: 0, yAxisIndex: 1 + i, symbol: "none",
      lineStyle: { width: 1.5, color: col },
      itemStyle: { color: col },
    } as any);
  });

  // Lower-panel series: tech indicators + non-overlay PIT factors.
  lowerAll.forEach((f, idx) => {
    legendData.push(f);
    const isVolume = /volume|amount|count|share/i.test(f);
    const isPit = lowerPit.includes(f);
    const col = isPit ? pitColor(f) : indColor(f);
    const data = rawData.value.map((r, i) => {
      const v = r[f];
      if (isVolume) {
        return { value: v, itemStyle: { color: upDown[i] ? "#ef232a" : "#14b143" } };
      }
      return v;
    });
    series.push({
      name: f, type: isVolume ? "bar" : "line", data,
      xAxisIndex: 1, yAxisIndex: overlayAxes + 1 + idx, symbol: "none",
      lineStyle: { width: 1, color: col },
      itemStyle: { color: col },
      barWidth: "60%",
    } as any);
  });

  const yAxis: any[] = [
    { gridIndex: 0, scale: true, splitLine: { lineStyle: { color: "#eee" } } },
  ];
  // Overlay axes on grid0 (right side, stacked with offset so labels don't overlap).
  overlayPit.forEach((f, i) => {
    yAxis.push({
      gridIndex: 0, position: "right", offset: i * 50, scale: true,
      name: f, nameTextStyle: { color: pitColor(f), fontSize: 10 },
      axisLabel: { color: pitColor(f), fontSize: 10 },
      splitLine: { show: false },
    });
  });
  // Always keep a lower-panel axis so grid[1] never collapses when nothing is selected.
  yAxis.push({ gridIndex: 1, scale: true, splitNumber: 2, splitLine: { show: false } });
  // Additional lower axes for extra indicators/PIT (idx 0 reuses the base above).
  lowerAll.forEach((_, idx) => {
    if (idx > 0) yAxis.push({ gridIndex: 1, scale: true, splitNumber: 2, splitLine: { show: false } });
  });

  // Widen right margin when overlay axes are present so their labels fit.
  const gridRight = 50 + overlayAxes * 30;

  chartInstance.setOption({
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "cross" },
      formatter: (params: any) => {
        if (!Array.isArray(params) || !params.length) return "";
        const idx = params[0].dataIndex;
        const row = rawData.value[idx];
        if (!row) return "";
        const ohlcv = ohlcvFields.value;
        const lines: string[] = [params[0].axisValueLabel || params[0].name];
        if (ohlcv.length >= 4) {
          lines.push(`open: ${fmtNum(row[ohlcv[0]])}`);
          lines.push(`high: ${fmtNum(row[ohlcv[1]])}`);
          lines.push(`low: ${fmtNum(row[ohlcv[2]])}`);
          lines.push(`close: ${fmtNum(row[ohlcv[3]])}`);
        }
        lowerAll.forEach((f) => {
          lines.push(`${f}: ${fmtNum(row[f])}`);
        });
        overlayPit.forEach((f) => {
          lines.push(`${f}: ${fmtNum(row[f])}`);
        });
        return lines.join("<br/>");
      },
    },
    // Legend hidden: the lower indicator/MA/PIT tag rows already show
    // selection state + color, so the top legend is redundant. Re-enable
    // with `show: true` (and `top: 8, type: "scroll"`) if click-to-hide a
    // single series is needed.
    legend: { show: false, data: legendData },
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    grid: [
      { left: 70, right: gridRight, top: 36, height: "56%" },
      { left: 70, right: 50, top: "72%", height: "20%" },
    ],
    xAxis: [
      { type: "category", data: dates, gridIndex: 0, scale: true, boundaryGap: true, axisLabel: { show: false } },
      { type: "category", data: dates, gridIndex: 1, scale: true, boundaryGap: true },
    ],
    yAxis,
    dataZoom: [
      {
        type: "inside", xAxisIndex: [0, 1],
        // Disable wheel handling here so plain wheel scrolls the page;
        // pinch (ctrl+wheel) zoom is handled by onChartWheel. Drag still pans.
        zoomOnMouseWheel: false,
        moveOnMouseWheel: false,
        moveOnMouseMove: true,
      },
      { type: "slider", xAxisIndex: [0, 1], bottom: 5, height: 18 },
    ],
    series,
  }, true);
}
</script>

<style scoped lang="scss">
.symbols-viewer { padding: 4px 20px 16px; }
.controls-row { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
.error-msg { color: #f56c6c; font-size: 13px; margin-left: 12px; }
.hint { font-size: 12px; color: #909399; margin-left: 12px; }
.indicator-tags { margin-bottom: 8px; display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.indicator-tags.lower-tags { margin-top: 6px; margin-bottom: 0; }
.ind-tag { cursor: pointer; user-select: none; }
.row-label { font-size: 12px; color: #909399; margin-right: 4px; }
.row-empty { font-size: 12px; color: #c0c4cc; }
.chart-container { width: 100%; height: 640px; border: 1px solid #ebeef5; border-radius: 6px; margin-top: 8px; }
</style>
