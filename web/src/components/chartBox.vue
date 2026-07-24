<template>
  <div class="chart-box">
    <div
      class="chart-item"
      v-for="(item, index) in keyList"
      :key="item"
    >
      <div
        class="zoom"
        v-if="hasData(item)"
        @click="zoom(colors[index], metricData[item], item)"
      ></div>
      <lineChart
        v-if="hasData(item)"
        :color="colors[index]"
        :data="metricData[item]"
        :chartName="metricLabels[item] || item"
        :smallSize="true"
      ></lineChart>
      <div v-else class="chart-empty">
        <div class="chart-empty-title">{{ metricLabels[item] || item }}</div>
        <div class="chart-empty-body">数据缺失<br/>（任务可能命中缓存未真训练）</div>
      </div>
    </div>
    <div class="dialog-box" v-if="showDialog">
      <div class="dialog-content gradient-border">
        <div class="close" @click="close"></div>
        <lineChart
          :color="dialogColor"
          :data="dialogData"
          :chartName="dialogName"
          :smallSize="false"
        ></lineChart>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, defineProps, watch, ref } from "vue";
import lineChart from "../components/lineChartOne.vue";

const props = defineProps({
  metricData: Object,
});
const metricData = ref(props.metricData);
const colors = ["red", "blue", "orange", "green", "purple", "teal", "brown", "pink", "olive", "navy"];
// Human-readable labels for the displayed metric keys. Falls back to the raw
// key for anything not listed here (e.g. legacy Alpha158-only runs).
const metricLabels = {
  "Rank ICIR": "日频 Rank ICIR",
  "年化收益": "年化收益（含/不含成本）",
  "信息比率 IR": "信息比率 IR（含/不含成本）",
  "最大回撤": "最大回撤（含/不含成本）",
  avg_daily_turnover: "平均日换手率",
  total_cost: "交易总成本",
  avg_daily_trade_count: "平均日交易次数",
  total_trade_count: "总交易次数",
  avg_holding_days_per_symbol: "平均每标的持有天数",
};
const keyList = ref([]);
const showDialog = ref(false);

// A metric has data when the value is either a finite number, or an object
// whose at least one entry is a finite number (the with/without cost case).
// null / undefined / empty object => no data (render a placeholder).
const hasData = (key) => {
  const v = metricData.value && metricData.value[key];
  if (v == null) return false;
  if (typeof v === "number") return Number.isFinite(v);
  if (typeof v === "object") {
    return Object.values(v).some((x) => typeof x === "number" && Number.isFinite(x));
  }
  return false;
};

const updateData = () => {
  keyList.value = Object.keys(metricData.value || {});
};
const dialogColor = ref("");
const dialogData = ref(null);
const dialogName = ref("");
const zoom = (color, data, name) => {
  dialogColor.value = color;
  dialogData.value = data;
  showDialog.value = true;
  dialogName.value = name;
};
const close = () => {
  showDialog.value = false;
  dialogColor.value = "";
  dialogData.value = null;
  dialogName.value = "";
};

watch(
  () => props.metricData,
  (newValue, oldValue) => {
    metricData.value = newValue;
    updateData();
  },
  {
    deep: true,
    immediate: true,
  }
);

onMounted(() => {
  updateData();
});
</script>

<style scoped lang="scss">
.chart-box {
  display: flex;
  flex-wrap: wrap;
  gap: 1.8em;
  margin-bottom: 1.8em;
  .chart-item {
    // Fixed 4-per-row layout: each chart takes 25% of the row, minus the
    // gap. Avoids the previous "100/n %" which squeezed 9 charts into one
    // tiny row.
    flex: 0 0 calc(25% - 1.35em);
    max-width: 500px;
    min-width: 0;
    background-color: var(--bg-white);
    border-radius: 35.5px;
    position: relative;
    box-shadow: 1px 1px 2px 0px rgba(255, 255, 255, 0.3) inset,
      -1px -1px 2px 0px rgba(221, 221, 221, 0.5) inset,
      -10px 10px 20px 0px rgba(221, 221, 221, 0.2),
      10px -10px 20px 0px rgba(221, 221, 221, 0.2),
      -10px -10px 20px 0px rgba(255, 255, 255, 0.9),
      10px 10px 25px 0px rgba(221, 221, 221, 0.9);
    .zoom {
      position: absolute;
      right: 1.125em;
      top: 0.8em;
      width: 1.125em;
      height: 1.125em;
      background: url(@/assets/playground-images/zoom.svg) no-repeat;
      background-size: contain;
      cursor: pointer;
      z-index: 1;
      &:hover {
        opacity: 0.5;
      }
    }
    .chart-empty {
      width: 100%;
      height: 200px;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 0.6em;
      color: #9ca3af;
      font-size: 0.85em;
      text-align: center;
      line-height: 1.5;
      .chart-empty-title {
        font-weight: 600;
        color: #6b7280;
        font-size: 0.95em;
      }
      .chart-empty-body {
        font-style: italic;
      }
    }
  }
  .dialog-box {
    width: 100vw;
    height: 100vh;
    position: fixed;
    left: 0;
    top: 0;
    background: rgba(255, 255, 255, 0.29);
    backdrop-filter: blur(4.599999904632568px);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 100;
    .dialog-content {
      width: 60%;
      height: 60%;
      position: relative;
      background-color: var(--bg-white);
      border-radius: 30px;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 1em;
      .close {
        position: absolute;
        right: 1.125em;
        top: 0.8em;
        width: 1.125em;
        height: 1.125em;
        background: url(@/assets/playground-images/zoom.svg) no-repeat;
        background-size: contain;
        cursor: pointer;
        transform: rotate(45deg);
        -webkit-transform: rotate(45deg);
        &:hover {
          opacity: 0.5;
        }
      }
    }
  }
}
</style>
