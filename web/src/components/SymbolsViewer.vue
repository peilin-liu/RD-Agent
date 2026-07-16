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
        :type="enabledMA.has(p) ? '' : 'info'"
        :effect="enabledMA.has(p) ? 'dark' : 'plain'"
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
const maPeriods = [5, 10, 20, 30, 60];
const enabledMA = ref<Set<number>>(new Set([5, 10, 20]));

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

const rawData = ref<Record<string, any>[]>([]);
const chartDom = ref<HTMLElement | null>(null);
let chartInstance: echarts.ECharts | null = null;

onMounted(() => { loadSymbols(); window.addEventListener("resize", resizeChart); });
onBeforeUnmount(() => { window.removeEventListener("resize", resizeChart); if (chartInstance) { chartInstance.dispose(); chartInstance = null; } });

function resizeChart() { if (chartInstance) chartInstance.resize(); }

watch(() => props.region, () => {
  selectedSymbol.value = "";
  rawData.value = [];
  ohlcvFields.value = [];
  indicatorFields.value = [];
  enabledIndicators.value = new Set();
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
    // Send empty fields -> backend uses ohlcv_fields + tech_fields from ~/.rd-agent/config.json
    const res = await getOHLCV(props.region, [selectedSymbol.value], [], start, end, adjust.value);
    if (!res.columns || !res.data) { errorMsg.value = "Invalid response from server"; return; }
    const rows = res.data.map((row: any[]) => Object.fromEntries(res.columns.map((c: string, i: number) => [c, row[i]])));
    const normalized = rows.map((r: Record<string, any>) => {
      const nr: Record<string, any> = {};
      for (const k of Object.keys(r)) nr[k.startsWith("$") ? k.slice(1) : k] = r[k];
      return nr;
    });
    rawData.value = normalized;
    const strip = (arr: any[]) => (arr || []).map((s: string) => s.startsWith("$") ? s.slice(1) : s);
    const ohlcv = strip(res.ohlcv_fields || []);
    const tech = strip(res.tech_fields || []);
    // ohlcv_fields order convention: [open, high, low, close, ...extras]
    ohlcvFields.value = ohlcv;
    indicatorFields.value = tech;
    const ind = new Set<string>();
    if (tech.includes("volume")) ind.add("volume");
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
  const maList = maPeriods.filter((p) => enabledMA.value.has(p));

  const legendData: string[] = [];
  const series: echarts.SeriesOption[] = [];

  if (hasOHLC) {
    series.push({
      name: "K", type: "candlestick", data: candleData, xAxisIndex: 0, yAxisIndex: 0,
      itemStyle: { color: "#ef232a", color0: "#14b143", borderColor: "#ef232a", borderColor0: "#14b143" },
    } as any);
  } else {
    series.push({ name: "close", type: "line", data: closes, xAxisIndex: 0, yAxisIndex: 0, symbol: "none" } as any);
    legendData.push("close");
  }

  maList.forEach((p) => {
    legendData.push(`MA${p}`);
    series.push({
      name: `MA${p}`, type: "line", data: calcMA(closes, p), xAxisIndex: 0, yAxisIndex: 0,
      symbol: "none", lineStyle: { width: 1 },
    } as any);
  });

  indicators.forEach((f, idx) => {
    legendData.push(f);
    const isVolume = /volume|amount|count|share/i.test(f);
    const col = indColor(f);
    const data = rawData.value.map((r, i) => {
      const v = r[f];
      if (isVolume) {
        return { value: v, itemStyle: { color: upDown[i] ? "#ef232a" : "#14b143" } };
      }
      return v;
    });
    series.push({
      name: f, type: isVolume ? "bar" : "line", data,
      xAxisIndex: 1, yAxisIndex: 1 + idx, symbol: "none",
      lineStyle: { width: 1, color: col },
      itemStyle: { color: col },
      barWidth: "60%",
    } as any);
  });

  const yAxis: any[] = [
    { gridIndex: 0, scale: true, splitLine: { lineStyle: { color: "#eee" } } },
    // Always keep a lower-panel axis so grid[1] never collapses when no indicator is selected.
    { gridIndex: 1, scale: true, splitNumber: 2, splitLine: { show: false } },
  ];
  // Additional lower axes for extra indicators (idx 0 reuses the always-present axis above).
  indicators.forEach((_, idx) => {
    if (idx > 0) yAxis.push({ gridIndex: 1, scale: true, splitNumber: 2, splitLine: { show: false } });
  });

  chartInstance.setOption({
    title: { text: selectedSymbol.value, left: 10, top: 6 },
    tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
    legend: { data: legendData, top: 30, type: "scroll" },
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    grid: [
      { left: 70, right: 50, top: 70, height: "52%" },
      { left: 70, right: 50, top: "70%", height: "20%" },
    ],
    xAxis: [
      { type: "category", data: dates, gridIndex: 0, scale: true, boundaryGap: true, axisLabel: { show: false } },
      { type: "category", data: dates, gridIndex: 1, scale: true, boundaryGap: true },
    ],
    yAxis,
    dataZoom: [
      {
        type: "inside", xAxisIndex: [0, 1],
        zoomOnMouseWheel: "ctrl",
        moveOnMouseWheel: true,
        moveOnMouseMove: true,
      },
      { type: "slider", xAxisIndex: [0, 1], bottom: 5, height: 18 },
    ],
    series,
  }, true);
}
</script>

<style scoped lang="scss">
.symbols-viewer { padding: 16px 20px; }
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
