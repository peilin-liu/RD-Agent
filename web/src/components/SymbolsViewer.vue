<template>
  <div class="symbols-viewer">
    <!-- Market snapshot view -->
    <MarketSnapshot
      v-if="viewMode === 'market'"
      ref="marketSnapRef"
      :region="props.region"
      :latestDate="latestTradingDate"
      @select-symbol="onSnapshotSelectSymbol"
      @back="onMarketBack"
    />

    <!-- Single-symbol K-line view -->
    <div v-else class="split-layout">
      <aside class="symbol-sidebar" aria-label="指数成分股">
        <div class="sidebar-heading">
          <h2><label for="market-select">指数 / 股票池</label></h2>
          <span class="region-badge">{{ props.region.toUpperCase() }}</span>
        </div>
        <el-select-v2
          id="market-select"
          v-model="selectedMarket"
          :options="marketOptions"
          :loading="marketsLoading"
          filterable
          placeholder="选择指数"
          class="market-select"
          @change="onMarketChange"
        />
        <el-input v-model="symbolSearch" placeholder="搜索代码或名称" clearable class="symbol-search" aria-label="搜索成分股" />
        <div class="symbol-sort">
          <el-select-v2
            v-model="symbolSort"
            :options="symbolSortOptions"
            :loading="metricsLoading"
            class="symbol-sort-select"
            aria-label="成分股排序指标"
            placeholder="排序指标"
            @change="onSymbolSortChange"
          />
          <el-button class="sort-direction" :aria-label="sortOrder === 'asc' ? '当前升序，切换为降序' : '当前降序，切换为升序'" @click="toggleSortOrder">
            {{ sortOrder === 'asc' ? '升序 ↑' : '降序 ↓' }}
          </el-button>
        </div>
        <div class="list-summary">
          <span>{{ marketLabel(selectedMarket) }}</span>
          <span>{{ filteredSymbols.length }} / {{ constituents.length }} 只</span>
        </div>
        <div v-if="showSortValue" class="metric-caption">
          <span>{{ metricsDate || latestTradingDate }}</span>
          <span>{{ sortField.label }}</span>
        </div>
        <div v-if="symbolsError" class="sidebar-error" role="alert">
          {{ symbolsError }}
          <el-button link type="primary" @click="retrySymbols">重试</el-button>
        </div>
        <div v-if="metricsError" class="sidebar-error" role="alert">
          {{ metricsError }}
          <el-button link type="primary" @click="loadMetrics()">重试</el-button>
        </div>
        <div class="symbol-list" v-loading="symbolsLoading">
          <el-auto-resizer v-if="filteredSymbols.length">
            <template #default="{ height, width }">
              <el-table-v2
                v-if="height > 0 && width > 0"
                ref="symbolTableRef"
                :data="filteredSymbols"
                :columns="symbolColumns(width)"
                :width="width"
                :height="height"
                :header-height="0"
                :row-height="62"
                row-key="symbol"
                :row-class="symbolRowClass"
                :row-event-handlers="{ onClick: onSymbolRowClick }"
                fixed
              />
            </template>
          </el-auto-resizer>
          <div v-else-if="!symbolsLoading && !symbolsError" class="list-empty">
            {{ symbolSearch ? '没有匹配的股票' : '该股票池暂无可用成分股' }}
          </div>
        </div>
        <div class="sidebar-footer">点击股票，在右侧查看 K 线</div>
      </aside>

      <section class="chart-pane" aria-label="股票 K 线">
        <div class="chart-heading">
          <div class="stock-title">
            <h2>{{ selectedInfo?.name || selectedSymbol || '选择一只股票' }}</h2>
            <span v-if="selectedSymbol" class="stock-code">{{ selectedSymbol }}</span>
            <p class="stock-meta">
              {{ selectedInfo?.industry_name || '日 K 线' }}
              <span v-if="latestTradingDate"> · 数据截至 {{ latestTradingDate }}</span>
              <span> · {{ adjustmentLabel }}<template v-if="adjustment === 'qfq' && adjustmentAnchorDate">（基准 {{ adjustmentAnchorDate }}）</template></span>
            </p>
          </div>
          <el-button tag="a" :href="marketHref" plain @click.left.exact.prevent="switchToMarket" size="small">市场行情表</el-button>
        </div>
        <div class="controls-row">
          <span class="control-label">日期范围</span>
          <el-date-picker v-model="startDate" type="date" placeholder="开始日期" value-format="YYYY-MM-DD" @change="onDateChange" class="date-picker" />
          <span class="date-separator">至</span>
          <el-date-picker v-model="endDate" type="date" placeholder="结束日期" value-format="YYYY-MM-DD" @change="onDateChange" class="date-picker" />
          <el-select-v2 v-model="adjustment" :options="adjustmentOptions" class="adjustment-select" aria-label="价格复权方式" @change="onAdjustmentChange" />
          <el-button type="primary" @click="fetchData" :loading="dataLoading" :disabled="!selectedSymbol" size="small">刷新</el-button>
        </div>
        <div v-if="errorMsg" class="chart-error" role="alert">{{ errorMsg }}</div>
        <p v-if="selectedSymbol && !symbolsLoading && !selectedInMarket" class="outside-market">当前股票不在所选股票池中，可从左侧选择成分股。</p>
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

    <div class="chart-stage" v-loading="dataLoading">
      <div ref="chartDom" class="chart-container" v-show="rawData.length"></div>
      <div v-if="!rawData.length && !dataLoading" class="chart-empty">
        <strong>{{ selectedSymbol ? '暂无行情数据' : '从左侧选择股票' }}</strong>
        <span>{{ selectedSymbol ? '可调整日期范围，或选择其他股票。' : '选择指数后，点击成分股即可查看 K 线。' }}</span>
      </div>
    </div>

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
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick, h } from "vue";
import { getSymbols, getOHLCV, getDataRange, getMarkets, getInstruments, getMarketSnapshot } from "@/utils/api";
import { snapshotSortFields, snapshotNumber, formatSnapshotNumber } from "@/utils/marketSnapshot";
import type { PriceAdjustment } from "@/utils/api";
import * as echarts from "echarts";
import MarketSnapshot from "./MarketSnapshot.vue";

const props = defineProps<{ region: string }>();

// View mode: 'single' (K-line) or 'market' (snapshot table). Lives in the URL
// query (?view=market|single) so a refresh keeps the view and the URL is
// shareable. Default 'market' (the data-explorer landing view).
import { useRoute, useRouter } from "vue-router";
const route = useRoute();
const router = useRouter();
const VIEW_Q = "view";
const initialView = (route.query[VIEW_Q] as "single" | "market") || "market";
const viewMode = ref<"single" | "market">(
  initialView === "single" ? "single" : "market"
);
const marketSnapRef = ref<any>(null);
// Latest trading day, passed to MarketSnapshot so it defaults the date picker.
const latestTradingDate = ref<string>("");
function switchToMarket() {
  chartRequest++;
  dataLoading.value = false;
  viewMode.value = "market";
  // MarketSnapshot fetches on mount; if already mounted (toggling), refetch.
  nextTick(() => marketSnapRef.value?.fetchData?.());
}
function onSnapshotSelectSymbol(sym: string) {
  selectedSymbol.value = sym;
  viewMode.value = "single";
}
async function onMarketBack(market: string) {
  if (selectedMarket.value !== market) {
    selectedMarket.value = market;
    await loadConstituents(true);
  }
  viewMode.value = "single";
}

type SymbolInfo = { symbol: string; name: string; listing_date?: string; industry_name?: string };
const symbols = ref<SymbolInfo[]>([]);
const constituents = ref<SymbolInfo[]>([]);
const symbolsLoading = ref(false);
const symbolsError = ref("");
const markets = ref<string[]>([]);
const marketsLoading = ref(false);
const selectedMarket = ref<string>((route.query.market as string) || "csi300");
const symbolSearch = ref("");
const symbolTableRef = ref<any>(null);
type SnapshotRow = Awaited<ReturnType<typeof getMarketSnapshot>>["data"][number];
const metricsBySymbol = ref<Record<string, SnapshotRow>>({});
const metricsLoading = ref(false);
const metricsLoaded = ref(false);
const metricsError = ref("");
const metricsDate = ref("");
const hasPredictions = ref(false);
const symbolSort = ref(snapshotSortFields.some(field => field.value === route.query.list_sort)
  ? String(route.query.list_sort) : "symbol");
function defaultSortOrder(key: string): "asc" | "desc" {
  return ["symbol", "name", "pred_rank"].includes(key) ? "asc" : "desc";
}
const sortOrder = ref<"asc" | "desc">(route.query.list_order === "asc" || route.query.list_order === "desc"
  ? route.query.list_order : defaultSortOrder(symbolSort.value));
const symbolSortOptions = computed(() => snapshotSortFields.filter(field =>
  field.value !== "pred_rank" || hasPredictions.value || symbolSort.value === "pred_rank"));
const sortField = computed(() => snapshotSortFields.find(field => field.value === symbolSort.value) || snapshotSortFields[0]);
const showSortValue = computed(() => !["symbol", "name"].includes(symbolSort.value));
function sortValue(symbol: string, key = symbolSort.value): number | null {
  const row = metricsBySymbol.value[symbol];
  return snapshotNumber(row?.[key as keyof SnapshotRow]);
}
function sortValueText(symbol: string): string {
  if (metricsLoading.value && !metricsLoaded.value) return "…";
  const value = sortValue(symbol);
  if (value == null) return "-";
  if (symbolSort.value === "pred_rank") return String(value);
  if (sortField.value.percent) return `${symbolSort.value === "pct_chg" && value > 0 ? "+" : ""}${value.toFixed(2)}%`;
  return formatSnapshotNumber(value);
}
function onSymbolSortChange() { sortOrder.value = defaultSortOrder(symbolSort.value); }
function toggleSortOrder() { sortOrder.value = sortOrder.value === "asc" ? "desc" : "asc"; }
let constituentsRequest = 0;
let chartRequest = 0;
const MARKET_LABELS: Record<string, string> = {
  all: "全部股票", csi300: "沪深300", csi500: "中证500", csi1000: "中证1000",
  csi2000: "中证2000", sse50: "上证50", csi_dividend: "中证红利", csi_soe: "中证国企",
  csi_soe_dividend: "国企红利", csi800_consumer: "中证800消费", csi800_healthcare: "中证800医药",
  main_board: "主板", bj_board: "北交所", chinext: "创业板", chinext_board: "创业板",
  star_board: "科创板", custom_6in1: "自定义 6 合 1",
};
function marketLabel(market: string) { return MARKET_LABELS[market] || market; }
const marketOptions = computed(() => markets.value.map(m => ({
  label: `${marketLabel(m)}${MARKET_LABELS[m] ? ` · ${m}` : ""}`, value: m,
})));
const filteredSymbols = computed(() => {
  const query = symbolSearch.value.trim().toLowerCase();
  const rows = constituents.value.filter(s => !query || `${s.symbol} ${s.name || ""}`.toLowerCase().includes(query));
  const direction = sortOrder.value === "asc" ? 1 : -1;
  return rows.sort((a, b) => {
    const tie = a.symbol.localeCompare(b.symbol);
    if (symbolSort.value === "symbol") return tie * direction;
    if (symbolSort.value === "name") return (a.name || "").localeCompare(b.name || "", "zh-CN") * direction || tie;
    const av = sortValue(a.symbol), bv = sortValue(b.symbol);
    // Missing values stay at the end in either direction; equal values use code.
    if (av == null && bv == null) return tie;
    if (av == null) return 1;
    if (bv == null) return -1;
    return (av - bv) * direction || tie;
  });
});
// Selected symbol lives in URL (?symbol=000538.SZ) so refresh keeps it and
// deep links work. Auto-loads on mount if present.
const selectedSymbol = ref<string>((route.query.symbol as string) || "");
const selectedInfo = computed(() => constituents.value.find(s => s.symbol === selectedSymbol.value)
  || symbols.value.find(s => s.symbol === selectedSymbol.value));
const selectedInMarket = computed(() => constituents.value.some(s => s.symbol === selectedSymbol.value));
function isAdjustment(value: unknown): value is PriceAdjustment {
  return value === "none" || value === "qfq" || value === "hfq";
}
let adjustmentChosen = isAdjustment(route.query.adjustment);
const adjustment = ref<PriceAdjustment>(isAdjustment(route.query.adjustment) ? route.query.adjustment : "qfq");
const adjustmentAnchorDate = ref("");
const adjustmentOptions = [
  { label: "前复权", value: "qfq" },
  { label: "后复权", value: "hfq" },
  { label: "不复权", value: "none" },
];
const adjustmentLabel = computed(() => adjustmentOptions.find(option => option.value === adjustment.value)?.label);
const marketHref = computed(() => router.resolve({
  path: route.path,
  query: {
    ...route.query, panel: "4", view: "market", market: selectedMarket.value,
    symbol: selectedSymbol.value || undefined, adjustment: adjustment.value,
  },
}).href);
watch([viewMode, selectedMarket, selectedSymbol, adjustment, symbolSort, sortOrder], ([view, market, symbol, priceMode, listSort, listOrder]) => {
  router.replace({ query: {
    ...route.query, [VIEW_Q]: view, market, symbol: symbol || undefined, adjustment: priceMode,
    list_sort: listSort === "symbol" && listOrder === "asc" ? undefined : listSort,
    list_order: listSort === "symbol" && listOrder === "asc" ? undefined : listOrder,
  } });
});
function symbolColumns(width: number) {
  return [{
    key: "symbol", dataKey: "symbol", title: "股票", width,
    cellRenderer: ({ rowData }: { rowData: SymbolInfo }) => {
      const value = sortValue(rowData.symbol);
      return h("div", { class: "symbol-item" }, [
        h("div", { class: "symbol-identity" }, [
          h("span", { class: "symbol-name", title: rowData.name || rowData.symbol }, rowData.name || rowData.symbol),
          h("span", { class: "symbol-code" }, rowData.symbol),
        ]),
        showSortValue.value ? h("span", {
          class: ["symbol-metric", symbolSort.value === "pct_chg" && value != null ? (value > 0 ? "metric-up" : value < 0 ? "metric-down" : "") : ""],
          title: `${sortField.value.label}: ${value ?? "-"} · ${metricsDate.value || latestTradingDate.value}`,
        }, sortValueText(rowData.symbol)) : null,
      ]);
    },
  }];
}
function symbolRowClass({ rowData }: { rowData: SymbolInfo }) {
  return rowData.symbol === selectedSymbol.value ? "symbol-row selected" : "symbol-row";
}
function onSymbolRowClick({ rowData }: { rowData: SymbolInfo }) {
  if (rowData.symbol === selectedSymbol.value) return;
  selectedSymbol.value = rowData.symbol;
  fetchData();
}
const startDate = ref<string | null>(new Date(Date.now() - 365 * 24 * 3600 * 1000).toISOString().slice(0, 10));
const endDate = ref<string | null>(new Date().toISOString().slice(0, 10));
const dataLoading = ref(false);
const errorMsg = ref("");

const CORE_FIELDS = ["open", "high", "low", "close"];
// Lower-panel fields enabled by default on first load (case-insensitive):
// pe / pb / pe_ttm / pb_ttm.
const DEFAULT_LOWER_FIELDS = ["pe", "pb", "pe_ttm", "pb_ttm"];
function isDefaultField(f: string): boolean {
  return DEFAULT_LOWER_FIELDS.includes(String(f).toLowerCase());
}
const maPeriods = [5, 10, 20, 30, 60, 250, 500];
const enabledMA = ref<Set<number>>(new Set(maPeriods));
// Fixed color per MA period so the tag and the overlay line share the same
// color, making it easy to tell MA types apart on the chart.
const MA_COLORS: Record<number, string> = {
  5: "#ee6666",
  10: "#fac858",
  20: "#5470c6",
  30: "#91cc75",
  60: "#73c0de",
  250: "#9a60b4",
  500: "#fc8452",
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
// Applied once per region: defaults enabled for the first data load, then
// user toggles take over.
const defaultsApplied = ref(false);

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

onMounted(async () => {
  loadSymbols();
  await Promise.all([loadLatestDate(), loadMarkets()]);
  await loadConstituents(true);
});
async function loadLatestDate() {
  try {
    const res: any = await getDataRange();
    const region = res?.regions?.[props.region] || res?.[props.region];
    latestTradingDate.value = region?.end || res?.end || "";
    if (!adjustmentChosen && isAdjustment(region?.price_adjustment)) {
      adjustment.value = region.price_adjustment;
    }
  } catch (e) { /* non-fatal */ }
}
let chartResizeObserver: ResizeObserver | undefined;
watch(chartDom, (element, previous) => {
  previous?.removeEventListener("wheel", onChartWheel);
  chartResizeObserver?.disconnect();
  chartInstance?.dispose();
  chartInstance = null;
  if (element) {
    element.addEventListener("wheel", onChartWheel, { passive: false });
    chartResizeObserver = new ResizeObserver(resizeChart);
    chartResizeObserver.observe(element);
    renderChart();
  }
}, { flush: "post" });
watch(viewMode, async (view) => {
  if (view === "single") {
    await nextTick();
    if (!metricsLoaded.value && !metricsLoading.value) loadMetrics();
    if (!selectedSymbol.value && constituents.value.length) selectedSymbol.value = constituents.value[0].symbol;
    fetchData();
  }
});
// AutoResizer starts at zero dimensions. Wait for the sized table to mount
// before scrolling, otherwise virtual rows and the DOM scroll offset diverge.
watch([symbolTableRef, filteredSymbols, selectedSymbol], async ([table, , symbol], [previousTable, , previousSymbol]) => {
  await nextTick();
  if (!table || table !== symbolTableRef.value) return;
  const index = filteredSymbols.value.findIndex(s => s.symbol === selectedSymbol.value);
  if (table !== previousTable || symbol !== previousSymbol) {
    if (index >= 0) table.scrollToRow(index, "auto");
  } else {
    // Sort/filter changes show the beginning of the ordered list, without
    // changing the stock whose K-line is currently open.
    table.scrollToTop(0);
  }
}, { flush: "post" });
onBeforeUnmount(() => {
  constituentsRequest++;
  chartRequest++;
  chartResizeObserver?.disconnect();
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

watch(() => props.region, async () => {
  chartRequest++;
  constituentsRequest++;
  selectedSymbol.value = "";
  constituents.value = [];
  rawData.value = [];
  rawDataFull.value = [];
  userStart.value = "";
  ohlcvFields.value = [];
  indicatorFields.value = [];
  enabledIndicators.value = new Set();
  pitFactorFields.value = [];
  pitOverlayFields.value = [];
  enabledPit.value = new Set();
  defaultsApplied.value = false;
  if (chartInstance) { chartInstance.dispose(); chartInstance = null; }
  loadSymbols();
  await Promise.all([loadLatestDate(), loadMarkets()]);
  await loadConstituents();
});

async function loadSymbols() {
  try {
    const res = await getSymbols(props.region);
    symbols.value = Array.isArray(res) ? res : [];
  } catch { symbols.value = []; }
}

function apiError(response: unknown, fallback: string) {
  const value = response as { error?: string; data?: { error?: string } } | undefined;
  return new Error(value?.error || value?.data?.error || fallback);
}

async function loadMarkets() {
  marketsLoading.value = true;
  symbolsError.value = "";
  try {
    const res = await getMarkets(props.region);
    if (!Array.isArray(res?.markets)) throw apiError(res, "无法加载指数列表");
    markets.value = res.markets;
    if (!markets.value.includes(selectedMarket.value)) selectedMarket.value = markets.value[0] || "all";
  } catch (error: any) {
    markets.value = [];
    symbolsError.value = error?.message || "无法加载指数列表";
  } finally { marketsLoading.value = false; }
}

async function loadConstituents(preserveSelection = false) {
  const request = ++constituentsRequest;
  chartRequest++;
  dataLoading.value = false;
  symbolsLoading.value = true;
  symbolsError.value = "";
  constituents.value = [];
  symbolSearch.value = "";
  metricsBySymbol.value = {};
  metricsLoading.value = false;
  metricsLoaded.value = false;
  metricsError.value = "";
  metricsDate.value = "";
  hasPredictions.value = false;
  if (!preserveSelection) {
    rawData.value = [];
    rawDataFull.value = [];
    chartInstance?.clear();
  }
  try {
    const res = await getInstruments(props.region, selectedMarket.value);
    if (request !== constituentsRequest) return;
    if (!Array.isArray(res?.instruments)) throw apiError(res, "无法加载成分股");
    constituents.value = res.instruments;
    if ((!preserveSelection && !selectedInMarket.value) || !selectedSymbol.value) {
      selectedSymbol.value = constituents.value[0]?.symbol || "";
    }
    if (viewMode.value === "single") {
      fetchData();
      loadMetrics(request);
    }
  } catch (error: any) {
    if (request !== constituentsRequest) return;
    symbolsError.value = error?.message || "无法加载成分股";
  } finally {
    if (request === constituentsRequest) symbolsLoading.value = false;
  }
}

async function loadMetrics(request = constituentsRequest) {
  if (request !== constituentsRequest || metricsLoading.value || metricsLoaded.value || !constituents.value.length) return;
  metricsLoading.value = true;
  metricsError.value = "";
  try {
    const response = await getMarketSnapshot(props.region, selectedMarket.value);
    if (request !== constituentsRequest) return;
    if (!Array.isArray(response?.data)) throw apiError(response, "无法加载排序指标");
    metricsBySymbol.value = Object.fromEntries(response.data.map(row => [row.symbol, row]));
    metricsDate.value = response.date;
    hasPredictions.value = !!response.predictions;
    metricsLoaded.value = true;
  } catch (error: any) {
    if (request === constituentsRequest) metricsError.value = error?.message || "无法加载排序指标";
  } finally {
    if (request === constituentsRequest) metricsLoading.value = false;
  }
}

function onMarketChange() { loadConstituents(); }
async function retrySymbols() {
  await loadMarkets();
  if (!symbolsError.value) await loadConstituents(true);
}

function onDateChange() { if (selectedSymbol.value) fetchData(); }
function onAdjustmentChange() {
  adjustmentChosen = true;
  if (selectedSymbol.value) fetchData();
}

async function fetchData() {
  const request = ++chartRequest;
  rawData.value = [];
  rawDataFull.value = [];
  adjustmentAnchorDate.value = "";
  chartInstance?.clear();
  errorMsg.value = "";
  if (!selectedSymbol.value) return;
  dataLoading.value = true;
  try {
    const start = startDate.value || "2024-01-01";
    const end = endDate.value || "2024-12-31";
    userStart.value = start;
    // Lookback buffer so long MAs (MA500) have enough history to form. Fetch
    // ~1.6x the longest MA period in calendar days before the user's start.
    const maxMA = Math.max(...maPeriods);
    const lookbackDays = Math.ceil(maxMA * 1.6);
    const fetchStart = new Date(start);
    fetchStart.setDate(fetchStart.getDate() - lookbackDays);
    const fetchStartStr = fetchStart.toISOString().slice(0, 10);
    // Send empty fields -> backend uses ohlcv_fields + tech_fields from ~/.rd-agent/config.json.
    // PIT factors are opt-in (slow P() operator): pass enabled PIT keys via pitFields.
    const pitKeys = Array.from(enabledPit.value);
    const res = await getOHLCV(props.region, [selectedSymbol.value], [], fetchStartStr, end, adjustment.value, pitKeys);
    if (request !== chartRequest) return;
    if (!Array.isArray(res?.data)) throw apiError(res, "无法加载行情数据");
    if (!res.data.length) return;
    if (!Array.isArray(res.columns)) throw new Error("行情数据格式无效");
    adjustmentAnchorDate.value = res.adjustment_anchors?.[selectedSymbol.value]?.date || "";
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
    // First load of a region: enable valuation defaults (pe/pb/pe_ttm/pb_ttm)
    // in the lower panel; afterwards preserve the user's toggles.
    if (!defaultsApplied.value) {
      defaultsApplied.value = true;
      const ind = new Set<string>();
      indicatorFields.value.forEach((f) => { if (isDefaultField(f)) ind.add(f); });
      enabledIndicators.value = ind;
      const pitSel = new Set<string>();
      pitFactorFields.value.forEach((f) => { if (isDefaultField(f) && !ind.has(f)) pitSel.add(f); });
      enabledPit.value = pitSel;
      // PIT factors are opt-in per request; refetch once so their columns exist.
      const pitMissing = Array.from(pitSel).some((k) => !(res.columns || []).includes(k));
      if (pitMissing) {
        await fetchData();
        return;
      }
    }
    await nextTick();
    if (request !== chartRequest) return;
    renderChart();
  } catch (e: any) {
    if (request === chartRequest) errorMsg.value = e?.message || String(e);
  } finally {
    if (request === chartRequest) dataLoading.value = false;
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
  chartInstance.resize();

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

  // MA uses the full lookback data (rawDataFull) so long periods (MA500) have
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
.symbols-viewer { padding: 4px 20px 20px; }
.split-layout { display: grid; grid-template-columns: 200px minmax(0, 1fr); gap: 12px; align-items: stretch; }
.symbol-sidebar, .chart-pane { background: #fff; border: 1px solid #e5e9f0; border-radius: 12px; color: #303133; min-width: 0; }
.symbol-sidebar { display: flex; flex-direction: column; min-height: 0; overflow: hidden; position: relative; }
.sidebar-heading { display: flex; justify-content: space-between; align-items: center; padding: 18px 12px 14px; }
.sidebar-heading h2, .stock-title h2 { margin: 0; font-size: 17px; font-weight: 600; line-height: 1.5; }
.region-badge { background: #f0f4ff; color: #5369bb; padding: 3px 7px; border-radius: 5px; font-size: 11px; font-weight: 600; }
.control-label { color: #7b8495; font-size: 12px; white-space: nowrap; }
.market-select, .symbol-search { width: calc(100% - 24px) !important; margin: 0 12px 12px; }
.symbol-sort { display: grid; grid-template-columns: minmax(0, 1fr) 52px; gap: 6px; margin: 0 12px 12px; }
.symbol-sort-select { width: 100%; min-width: 0; }
.symbol-sort .sort-direction { width: 52px; padding: 4px 5px; font-size: 12px; }
.metric-caption { display: flex; justify-content: space-between; gap: 6px; padding: 7px 12px; border-bottom: 1px solid #eef0f4; color: #8b93a3; font-size: 11px; }
.metric-caption span:last-child { color: #535d70; }
.list-summary { display: flex; justify-content: space-between; gap: 6px; padding: 0 12px 10px; color: #8b93a3; font-size: 12px; border-bottom: 1px solid #eef0f4; }
.list-summary span:first-child { color: #535d70; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.list-summary span:last-child { flex-shrink: 0; }
.symbol-list { flex: 1; min-height: 0; position: relative; }
/* Let the chart determine the grid height, independently of virtual-table measurements. */
.symbol-list :deep(.el-auto-resizer) { position: absolute; inset: 0; }
.symbol-list :deep(.el-table-v2__row.symbol-row) { cursor: pointer; border-bottom: 1px solid #f1f3f7; }
.symbol-list :deep(.el-table-v2__row.selected) { background: #edf3ff; box-shadow: inset 3px 0 #5470c6; }
.symbol-list :deep(.el-table-v2__row:hover) { background: #f4f7fc; }
.symbol-list :deep(.el-table-v2__row.selected:hover) { background: #edf3ff; }
.symbol-list :deep(.symbol-item) { display: flex; align-items: center; justify-content: space-between; gap: 8px; width: 100%; padding: 0 3px; min-width: 0; box-sizing: border-box; }
.symbol-list :deep(.symbol-identity) { display: flex; flex-direction: column; gap: 5px; min-width: 0; flex: 1; }
.symbol-list :deep(.symbol-name) { color: #303b51; font-size: 14px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.symbol-list :deep(.symbol-code) { color: #8b93a3; font-size: 12px; font-variant-numeric: tabular-nums; }
.symbol-list :deep(.symbol-metric) { flex-shrink: 0; max-width: 76px; color: #535d70; font-size: 12px; font-variant-numeric: tabular-nums; text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.symbol-list :deep(.metric-up) { color: #ef232a; }
.symbol-list :deep(.metric-down) { color: #14b143; }
.symbol-list :deep(.selected .symbol-name) { color: #3e5db3; }
.sidebar-footer { padding: 12px; border-top: 1px solid #eef0f4; font-size: 11px; color: #9aa1ae; }
.sidebar-error { padding: 10px 16px; color: #c45656; font-size: 12px; line-height: 1.6; background: #fff5f5; }
.list-empty { padding: 40px 16px; text-align: center; color: #9aa1ae; font-size: 13px; }
.chart-pane { padding: 20px; }
.chart-heading { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 12px; }
.stock-title { display: flex; gap: 4px 12px; align-items: baseline; flex-wrap: wrap; min-width: 0; }
.stock-title h2 { font-size: 22px; color: #263147; }
.stock-code { color: #828c9e; font-size: 13px; font-variant-numeric: tabular-nums; }
.stock-meta { font-size: 12px; color: #9aa1ae; margin: 0; }
.controls-row { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; padding: 12px 0; margin-bottom: 14px; border-top: 1px solid #eef0f4; border-bottom: 1px solid #eef0f4; }
.controls-row :deep(.date-picker.el-input) { width: 154px !important; flex-grow: 0; }
.adjustment-select { width: 110px; }
.date-separator { color: #a0a7b3; font-size: 12px; }
.chart-error { padding: 10px 12px; background: #fff2f0; border-radius: 6px; color: #c45656; font-size: 13px; margin-bottom: 12px; }
.outside-market { color: #909399; font-size: 12px; margin: 0 0 10px; }
.chart-stage { min-height: 480px; position: relative; }
.chart-empty { min-height: 480px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; color: #a0a7b3; font-size: 13px; }
.chart-empty strong { font-size: 17px; color: #737d90; font-weight: 500; }
.indicator-tags { margin-bottom: 8px; display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.indicator-tags.lower-tags { margin-top: 6px; margin-bottom: 0; }
.ind-tag { cursor: pointer; user-select: none; }
.row-label { font-size: 12px; color: #909399; margin-right: 4px; }
.row-empty { font-size: 12px; color: #c0c4cc; }
.chart-container { width: 100%; height: clamp(480px, 62vh, 700px); }
@media (max-width: 1100px) {
  .split-layout { grid-template-columns: 180px minmax(0, 1fr); gap: 10px; }
  .chart-pane { padding: 16px; }
  .symbols-viewer { padding: 4px 12px 16px; }
}
@media (max-width: 700px) {
  .split-layout { grid-template-columns: minmax(0, 1fr); }
  .symbol-sidebar { position: static; height: 400px; }
  .chart-heading { align-items: flex-start; }
  .stock-title { gap: 5px 10px; }
  .stock-title h2 { font-size: 19px; }
  .stock-meta { flex-basis: 100%; }
  .controls-row { gap: 8px; }
  .controls-row > .control-label { width: 100%; }
  .controls-row :deep(.date-picker.el-input) { width: 140px !important; }
}
</style>
