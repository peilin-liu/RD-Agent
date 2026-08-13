<template>
  <div class="market-snapshot">
    <div class="ms-controls">
      <span class="ms-label">市场</span>
      <el-select-v2
        v-model="selectedMarket"
        :options="marketOptions"
        style="width: 200px"
        @change="onMarketChange"
      />
      <span class="ms-label" style="margin-left: 12px">日期</span>
      <el-date-picker
        v-model="selectedDate"
        type="date"
        placeholder="最新交易日"
        value-format="YYYY-MM-DD"
        :clearable="false"
        style="width: 150px; margin-left: 4px"
        @change="fetchData"
      />
      <span class="ms-label" style="margin-left: 12px">行业</span>
      <el-select-v2
        v-model="selectedIndustry"
        :options="industryOptions"
        filterable
        clearable
        placeholder="全部行业"
        style="width: 220px; margin-left: 4px"
      />
      <el-input
        v-model="searchText"
        placeholder="搜 symbol/name"
        clearable
        style="width: 180px; margin-left: 12px"
      />
      <el-select-v2
        v-if="predictions"
        v-model="sortChoice"
        :options="sortOptions"
        style="width: 150px; margin-left: 12px"
        @change="onSortChoice"
      />
      <el-button type="primary" @click="fetchData" :loading="loading" style="margin-left: 12px">刷新</el-button>
      <el-button type="primary" plain @click="emit('back')" size="small">← 返回单股</el-button>
      <span v-if="errorMsg" class="ms-error">{{ errorMsg }}</span>
    </div>

    <div class="ms-stats" v-if="!loading && rows.length">
      <span class="ms-label">{{ filterred.length }} / {{ rows.length }} 只</span>
      <span class="ms-label">上涨 <span style="color: #ef232a">{{ upCount }}</span></span>
      <span class="ms-label">下跌 <span style="color: #14b143">{{ downCount }}</span></span>
      <span class="ms-label" v-if="predictions">预测 {{ predictions.market }} · {{ predictions.date }} · 已关联 {{ predictions.joined }}/{{ predictions.total }} 只</span>
    </div>

    <el-table-v2
      v-loading="loading"
      :data="displayRows"
      :columns="columns"
      :width="tableWidth"
      :height="560"
      :row-height="40"
      :sort-by="sortByState"
      :row-event-handlers="{ onClick: onRowClick }"
      fixed
      @column-sort="onColumnSort"
      class="ms-table"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, nextTick, h } from "vue";
import { getMarkets, getMarketSnapshot } from "@/utils/api";

const props = defineProps<{ region: string; latestDate?: string }>();
const emit = defineEmits<{
  (e: "selectSymbol", sym: string): void;
  (e: "back"): void;
}>();

const markets = ref<string[]>([]);
const selectedMarket = ref<string>("csi300");
const selectedDate = ref<string>("");
const selectedIndustry = ref<string>("");
const searchText = ref<string>("");
const lastMarket = ref<string>("");
const rows = ref<any[]>([]);
const loading = ref(false);
const errorMsg = ref("");
const tableWidth = ref(1100);
// Prediction join metadata: { market, date, total, joined } or null.
const predictions = ref<any>(null);

const marketOptions = computed(() =>
  markets.value.map(m => ({ label: m, value: m }))
);

// Industry filter shows industry_name (中文), table column shows industry_code.
const industryOptions = computed(() => {
  const seen = new Set<string>();
  const out: { label: string; value: string }[] = [];
  for (const r of rows.value) {
    if (r.industry_name && !seen.has(r.industry_name)) {
      seen.add(r.industry_name);
      out.push({ label: `${r.industry_name} (${r.industry_code})`, value: r.industry_name });
    }
  }
  out.sort((a, b) => a.label.localeCompare(b.label, "zh"));
  return out;
});

const filterred = computed(() => {
  const kw = searchText.value.trim().toLowerCase();
  const ind = selectedIndustry.value;
  return rows.value.filter(r => {
    if (ind && r.industry_name !== ind) return false;
    if (kw) {
      const s = (r.symbol + " " + (r.name || "")).toLowerCase();
      if (!s.includes(kw)) return false;
    }
    return true;
  });
});

const upCount = computed(() => filterred.value.filter(r => r.pct_chg != null && r.pct_chg > 0).length);
const downCount = computed(() => filterred.value.filter(r => r.pct_chg != null && r.pct_chg < 0).length);

const fmt = (v: any, digits = 2) => {
  if (v == null) return "-";
  const n = Number(v);
  if (isNaN(n)) return "-";
  if (Math.abs(n) >= 1e8) return (n / 1e8).toFixed(2) + "亿";
  if (Math.abs(n) >= 1e4) return (n / 1e4).toFixed(2) + "万";
  return n.toFixed(digits);
};
const fmtPct = (v: any) => {
  if (v == null) return "-";
  const n = Number(v);
  if (isNaN(n)) return "-";
  const cls = n > 0 ? "ms-up" : n < 0 ? "ms-down" : "";
  return h("span", { class: cls }, `${n > 0 ? "+" : ""}${n.toFixed(2)}%`);
};
const fmtRank = (v: any) => {
  if (v == null) return "-";
  const n = Number(v);
  if (isNaN(n)) return "-";
  return String(n);
};

// el-table-v2 native sort state: { key, order }. Clicking a sortable column
// header fires @column-sort with { key, order }. We bind :sort-by to this ref.
const sortByState = ref<{ key: string; order: "asc" | "desc" }>({ key: "turnover", order: "desc" });
// Sort-choice dropdown (shown when predictions are joined). Values mirror the
// sortable column keys; order per choice: score sorts descending, rank ascending.
const sortChoice = ref<string>("turnover");
const SORT_CHOICES: Record<string, { key: string; order: "asc" | "desc" }> = {
  pred_rank: { key: "pred_rank", order: "asc" },
  pct_chg: { key: "pct_chg", order: "desc" },
  turnover: { key: "turnover", order: "desc" },
};
const sortOptions = computed(() => [
  { label: "按排名", value: "pred_rank" },
  { label: "按涨跌幅", value: "pct_chg" },
  { label: "按换手率", value: "turnover" },
]);
function onSortChoice(v: string) {
  const s = SORT_CHOICES[v] || SORT_CHOICES.turnover;
  sortByState.value = { ...s };
}
function onColumnSort({ key, order }: { key: string; order: "asc" | "desc" }) {
  sortByState.value = { key, order };
  if (key in SORT_CHOICES) sortChoice.value = key;
}

const sortedRows = computed(() => {
  const { key, order } = sortByState.value;
  const dir = order === "asc" ? 1 : -1;
  const arr = [...filterred.value];
  arr.sort((a, b) => {
    const va = a[key], vb = b[key];
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    return (Number(va) - Number(vb)) * dir;
  });
  return arr;
});

// Override filterred binding with sorted version
const displayRows = sortedRows;

const columns = computed<any[]>(() => [
  { key: "symbol", title: "Symbol", width: 110, dataKey: "symbol", sortable: true, cellRenderer: ({ cellData }: any) => cellData },
  { key: "name", title: "名称", width: 110, dataKey: "name" },
  ...(predictions.value ? [
    { key: "pred_rank", title: "排名", width: 90, dataKey: "pred_rank", sortable: true, cellRenderer: ({ cellData }: any) => fmtRank(cellData) },
  ] : []),
  { key: "industry_code", title: "行业", width: 70, dataKey: "industry_code" },
  { key: "pct_chg", title: "涨跌幅", width: 100, dataKey: "pct_chg",
    sortable: true, cellRenderer: ({ cellData }: any) => fmtPct(cellData) },
  { key: "close", title: "收盘", width: 80, dataKey: "close", sortable: true, cellRenderer: ({ cellData }: any) => fmt(cellData) },
  { key: "open", title: "开盘", width: 80, dataKey: "open", cellRenderer: ({ cellData }: any) => fmt(cellData) },
  { key: "high", title: "最高", width: 80, dataKey: "high", cellRenderer: ({ cellData }: any) => fmt(cellData) },
  { key: "low", title: "最低", width: 80, dataKey: "low", cellRenderer: ({ cellData }: any) => fmt(cellData) },
  { key: "turnover", title: "换手率%", width: 100, dataKey: "turnover",
    sortable: true, cellRenderer: ({ cellData }: any) => fmt(cellData) },
  { key: "volume", title: "成交量(万)", width: 110, dataKey: "volume", sortable: true, cellRenderer: ({ cellData }: any) => fmt(cellData) },
  { key: "amount", title: "成交额", width: 100, dataKey: "amount", sortable: true, cellRenderer: ({ cellData }: any) => fmt(cellData) },
  { key: "PE", title: "PE", width: 80, dataKey: "PE", sortable: true, cellRenderer: ({ cellData }: any) => fmt(cellData) },
  { key: "PB", title: "PB", width: 80, dataKey: "PB", sortable: true, cellRenderer: ({ cellData }: any) => fmt(cellData) },
  { key: "DV_RATIO", title: "股息率%", width: 90, dataKey: "DV_RATIO", sortable: true, cellRenderer: ({ cellData }: any) => fmt(cellData) },
  { key: "DV_TTM", title: "TTM股息率%", width: 100, dataKey: "DV_TTM", sortable: true, cellRenderer: ({ cellData }: any) => fmt(cellData) },
]);

// Open the single-symbol K-line in a NEW browser tab so the market snapshot
// stays open in the current tab. URL carries panel/view/symbol so the new tab
// auto-loads that symbol.
function onRowClick({ rowData }: any) {
  if (!rowData || !rowData.symbol) return;
  const url = `/#/?panel=4&view=single&symbol=${encodeURIComponent(rowData.symbol)}`;
  window.open(url, "_blank");
}

async function loadMarkets() {
  try {
    const res = await getMarkets(props.region);
    markets.value = Array.isArray(res.markets) ? res.markets : [];
    if (markets.value.length && !markets.value.includes(selectedMarket.value)) {
      selectedMarket.value = markets.value[0];
    }
  } catch (e: any) {
    errorMsg.value = "Failed to load markets: " + (e?.message || e);
  }
}

async function fetchData() {
  loading.value = true;
  errorMsg.value = "";
  try {
    const res = await getMarketSnapshot(props.region, selectedMarket.value, selectedDate.value || undefined);
    rows.value = Array.isArray(res.data) ? res.data : [];
    predictions.value = (res as any).predictions || null;
    if (res.date) selectedDate.value = res.date;
    // Default sort on market switch: by prediction rank when a score file is
    // joined for the selected market, otherwise by turnover. Manual sorts
    // survive date changes / refresh within the same market.
    if (selectedMarket.value !== lastMarket.value) {
      lastMarket.value = selectedMarket.value;
      sortChoice.value = predictions.value ? "pred_rank" : "turnover";
      onSortChoice(sortChoice.value);
    }
  } catch (e: any) {
    errorMsg.value = "Failed to load snapshot: " + (e?.message || e);
    rows.value = [];
    predictions.value = null;
  } finally {
    loading.value = false;
  }
}

function onMarketChange() { fetchData(); }

function resizeTable() {
  const el = document.querySelector(".market-snapshot");
  tableWidth.value = el ? el.clientWidth : 1100;
}

onMounted(async () => {
  if (props.latestDate) selectedDate.value = props.latestDate;
  await loadMarkets();
  await fetchData();
  await nextTick();
  resizeTable();
  window.addEventListener("resize", resizeTable);
});

onBeforeUnmount(() => {
  window.removeEventListener("resize", resizeTable);
});

defineExpose({ fetchData });
</script>

<style scoped lang="scss">
.market-snapshot { padding: 4px 0; }
.ms-controls { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; margin-bottom: 10px; }
.ms-label { font-size: 12px; color: #909399; }
.ms-error { color: #f56c6c; font-size: 13px; margin-left: 12px; }
.ms-stats { display: flex; gap: 16px; margin-bottom: 8px; }
.ms-table { border: 1px solid #ebeef5; border-radius: 6px; }
:deep(.el-table-v2__row) { cursor: pointer; }
:deep(.el-table-v2__row:hover) { background: #f5f7fa; }
:deep(.ms-up) { color: #ef232a; }
:deep(.ms-down) { color: #14b143; }
</style>
