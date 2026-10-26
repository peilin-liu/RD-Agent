<template>
  <el-button :type="activeCount ? 'primary' : 'default'" :plain="!!activeCount" size="small" @click="open">
    选股器<template v-if="activeCount"> · {{ activeCount }} 项</template>
  </el-button>
  <el-dialog v-model="visible" title="条件选股" width="min(720px, calc(100vw - 32px))" append-to-body>
    <p class="screen-context">{{ market }} · {{ date || '最新数据' }} · {{ symbols.length }} 只股票</p>
    <p class="screen-help">按结束日期当天的指标筛选，所有条件需同时满足。上下限均包含边界，留空表示不限；缺失指标不满足条件。</p>
    <div class="industry-filter">
      <span>所属行业</span>
      <el-select-v2 v-model="draft.industry" :options="industries" filterable clearable placeholder="全部行业" aria-label="所属行业" />
    </div>
    <div class="ma-direction-filters">
      <label v-for="period in maScreenPeriods" :key="period">
        <span>MA{{ period }} 方向</span>
        <el-select-v2 v-model="draft.maDirections[period]" :options="directionOptions" :aria-label="`MA${period} 方向`" />
      </label>
    </div>
    <p class="screen-help">均线一阶差分 = 当日 MA − 前一交易日 MA；使用当前复权方式，历史不足时不命中。三条均线可分别设置方向。</p>
    <div class="screen-rules">
      <div v-for="(rule, index) in draft.rules" :key="index" class="screen-rule">
        <el-select-v2 v-model="rule.field" :options="fieldOptions" filterable :aria-label="`条件 ${index + 1} 指标`" />
        <el-input v-model="rule.min" placeholder="下限（不限）" :aria-label="`条件 ${index + 1} 下限`" />
        <span class="range-separator">至</span>
        <el-input v-model="rule.max" placeholder="上限（不限）" :aria-label="`条件 ${index + 1} 上限`" />
        <el-button text type="danger" :aria-label="`删除条件 ${index + 1}`" @click="draft.rules.splice(index, 1)">删除</el-button>
      </div>
    </div>
    <el-button plain @click="draft.rules.push({ field: 'pct_chg', min: '', max: '' })">＋ 添加条件</el-button>
    <p class="screen-help">百分比填百分数（例如 5 表示 5%）；成交量、成交额按行情接口原始数值输入，不使用“万 / 亿”缩写。价格使用未复权行情。</p>
    <p v-if="validationError" class="screen-error" role="alert">{{ validationError }}</p>
    <p v-else-if="loading" class="screen-help" role="status">正在加载筛选指标…</p>
    <p v-else-if="error" class="screen-error" role="alert">{{ error }} <el-button link type="primary" @click="$emit('retry')">重试</el-button></p>
    <p v-else-if="!symbols.length" class="screen-help">当前股票池暂无可用成分股，请切换股票池或刷新数据。</p>
    <p v-else-if="!ready" class="screen-help">等待行情数据加载。</p>
    <p v-else class="screen-preview" role="status">预计命中 <strong>{{ matchCount }}</strong> / {{ symbols.length }} 只股票</p>
    <template #footer>
      <div class="screen-footer">
        <el-button @click="draft = emptyScreen()">清空条件</el-button>
        <span class="footer-spacer"></span>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :disabled="!!validationError || loading || !!error || !ready" @click="apply">应用筛选</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { copyScreen, emptyScreen, maScreenPeriods, matchesScreen, screenCount, screenError, screeningFields } from "@/utils/stockScreener";
import type { StockScreen } from "@/utils/stockScreener";

const props = defineProps<{
  modelValue: StockScreen;
  symbols: { symbol: string; industry_name?: string }[];
  metrics: Record<string, Record<string, unknown>>;
  market: string;
  date: string;
  loading: boolean;
  ready: boolean;
  error: string;
}>();
const emit = defineEmits<{ (event: "update:modelValue", value: StockScreen): void; (event: "retry"): void }>();
const visible = ref(false);
const draft = ref<StockScreen>(emptyScreen());
const activeCount = computed(() => screenCount(props.modelValue));
const directionOptions = [{ label: "不限", value: "" }, { label: "向上 ↑", value: "up" }, { label: "走平 →", value: "flat" }, { label: "向下 ↓", value: "down" }];
const fieldOptions = screeningFields.map(field => ({ ...field, label: `${field.label}${field.percent ? ' (%)' : ''}` }));
const industries = computed(() => [...new Set(props.symbols.map(s => s.industry_name).filter(Boolean))]
  .sort((a, b) => a!.localeCompare(b!, "zh-CN")).map(value => ({ label: value!, value: value! })));
const validationError = computed(() => screenError(draft.value));
const matchCount = computed(() => props.symbols.filter(s => matchesScreen(s.industry_name, props.metrics[s.symbol], draft.value)).length);
function open() {
  draft.value = copyScreen(props.modelValue);
  visible.value = true;
}
function apply() {
  if (validationError.value || props.loading || props.error || !props.ready) return;
  emit("update:modelValue", copyScreen(draft.value));
  visible.value = false;
}
</script>

<style scoped>
.screen-context { margin: 0 0 12px; color: #303b51; font-weight: 600; }
.screen-help { color: #8b93a3; font-size: 12px; line-height: 1.8; margin: 12px 0; }
.industry-filter { display: flex; gap: 14px; align-items: center; margin: 20px 0 14px; }
.industry-filter > span { white-space: nowrap; }
.industry-filter :deep(.el-select-v2) { width: 240px; }
.screen-rules { max-height: 40vh; overflow-y: auto; }
.ma-direction-filters { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.ma-direction-filters label { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.screen-rule { display: grid; grid-template-columns: minmax(130px, 1.3fr) minmax(90px, 1fr) auto minmax(90px, 1fr) auto; align-items: center; gap: 8px; margin-bottom: 12px; }
.screen-rule :deep(.el-select-v2) { min-width: 0; }
.range-separator { color: #9aa1ae; }
.screen-preview { padding: 12px; background: #f0f5ff; border-radius: 6px; color: #5369bb; }
.screen-preview strong { font-size: 18px; }
.screen-error { color: #c45656; font-size: 13px; }
.screen-footer { display: flex; gap: 8px; flex-wrap: wrap; }
.screen-footer .el-button + .el-button { margin-left: 0; }
.footer-spacer { flex: 1; }
@media (max-width: 600px) {
  .screen-rule { grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr) auto; padding-bottom: 12px; border-bottom: 1px solid #eef0f4; }
  .screen-rule > :first-child { grid-column: 1 / -1; }
}
</style>
