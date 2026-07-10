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
      <el-date-picker v-model="dateRange" type="daterange" range-separator="~" start-placeholder="Start" end-placeholder="End" value-format="YYYY-MM-DD" @change="onDateChange" style="margin-left:12px" />
      <el-checkbox v-model="adjust" @change="onAdjustChange" style="margin-left:12px">Adjusted prices</el-checkbox>
      <el-button type="primary" @click="fetchData" :loading="dataLoading" style="margin-left:12px">Load</el-button>
      <span v-if="errorMsg" class="error-msg">{{ errorMsg }}</span>
    </div>
    <div class="indicator-tags" v-if="allFields.length">
      <el-tag v-for="f in allFields" :key="f" :type="enabledFields.has(f) ? '' : 'info'" :effect="enabledFields.has(f) ? 'dark' : 'plain'" @click="toggleField(f)" class="ind-tag">{{ f }}</el-tag>
    </div>
    <div ref="chartDom" class="chart-container" v-loading="dataLoading"></div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from "vue";
import { getSymbols, getOHLCV } from "@/utils/api";
import * as echarts from "echarts";

const props = defineProps<{ region: string }>();

const symbols = ref<Array<{ symbol: string; name: string; listing_date?: string }>>([]);
const symbolOptions = computed(() =>
  symbols.value.map(s => ({ label: `${s.symbol}  ${s.name}`, value: s.symbol }))
);
const symbolsLoading = ref(false);
const selectedSymbol = ref("");
const dateRange = ref<[string, string] | null>([
  new Date(Date.now() - 365 * 24 * 3600 * 1000).toISOString().slice(0, 10),
  new Date().toISOString().slice(0, 10),
]);
const dataLoading = ref(false);
const errorMsg = ref("");
const adjust = ref(false);
const allFields = ref<string[]>([]);
const enabledFields = ref<Set<string>>(new Set());
const rawData = ref<Record<string, any>[]>([]);
const chartDom = ref<HTMLElement | null>(null);
let chartInstance: echarts.ECharts | null = null;

onMounted(() => { loadSymbols(); });

watch(() => props.region, () => {
  selectedSymbol.value = "";
  rawData.value = [];
  allFields.value = [];
  enabledFields.value = new Set();
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
    const start = dateRange.value?.[0] || "2024-01-01";
    const end = dateRange.value?.[1] || "2024-12-31";
    const res = await getOHLCV(props.region, [selectedSymbol.value], [], start, end, adjust.value);
    if (!res.columns || !res.data) { errorMsg.value = "Invalid response from server"; return; }
    const rows = res.data.map((row: any[]) => Object.fromEntries(res.columns.map((c: string, i: number) => [c, row[i]])));
    const normalized = rows.map((r: Record<string, any>) => {
      const nr: Record<string, any> = {};
      for (const k of Object.keys(r)) nr[k.startsWith("$") ? k.slice(1) : k] = r[k];
      return nr;
    });
    rawData.value = normalized;
    if (normalized.length) {
      const keys = new Set<string>();
      normalized.forEach((r) => Object.keys(r).forEach((k) => keys.add(k)));
      keys.delete("date");
      keys.delete("instrument");
      allFields.value = Array.from(keys).sort();
      // Default: enable only price-like fields
      const defaultFields = ["open", "high", "low", "close", "adjclose"];
      enabledFields.value = new Set(defaultFields.filter(f => keys.has(f)));
    }
    await nextTick();
    renderChart();
  } catch (e: any) {
    errorMsg.value = e?.message || String(e);
  } finally {
    dataLoading.value = false;
  }
}

function toggleField(f: string) {
  const s = new Set(enabledFields.value);
  if (s.has(f)) s.delete(f); else s.add(f);
  enabledFields.value = s;
  renderChart();
}

function renderChart() {
  if (!chartDom.value || !rawData.value.length) return;
  if (!chartInstance) chartInstance = echarts.init(chartDom.value);
  const dates = rawData.value.map((r) => r.date);
  const activeFields = allFields.value.filter((f) => enabledFields.value.has(f));
  chartInstance.setOption({
    title: { text: selectedSymbol.value },
    tooltip: { trigger: "axis" },
    legend: { data: activeFields, top: 30, type: "scroll" },
    grid: { top: 80, left: 70, right: 40, bottom: 40 },
    xAxis: { type: "category", data: dates },
    yAxis: { type: "value" },
    dataZoom: [{ type: "inside" }, { type: "slider", bottom: 0 }],
    series: activeFields.map((f) => ({ name: f, type: "line", data: rawData.value.map((r) => r[f]), symbol: "none" })) as echarts.SeriesOption[],
  }, true);
}
</script>

<style scoped lang="scss">
.symbols-viewer { padding: 16px 20px; }
.controls-row { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
.error-msg { color: #f56c6c; font-size: 13px; margin-left: 12px; }
.indicator-tags { margin-bottom: 8px; display: flex; flex-wrap: wrap; gap: 6px; max-height: 120px; overflow-y: auto; }
.ind-tag { cursor: pointer; user-select: none; }
.chart-container { width: 100%; height: 480px; border: 1px solid #ebeef5; border-radius: 6px; margin-top: 8px; }
</style>
