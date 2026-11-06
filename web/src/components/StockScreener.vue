<template>
  <el-button :type="activeCount ? 'primary' : 'default'" :plain="!!activeCount" size="small" @click="open">
    选股器<template v-if="activeCount"> · {{ activeCount }} 项</template>
  </el-button>
  <el-dialog v-model="visible" title="条件选股" width="min(720px, calc(100vw - 32px))" append-to-body>
    <p class="screen-context">{{ market }} · {{ date || '最新数据' }} · {{ symbols.length }} 只股票</p>
    <p class="screen-help">按结束日期当天的指标筛选，所有条件需同时满足。上下限均包含边界，留空表示不限；缺失指标不满足条件。</p>
    <div class="screen-sections">
      <section class="screen-section">
        <h3>1. 行业选择</h3>
        <p class="screen-help">可选择多个行业，匹配其中任意一个；留空表示全部行业。</p>
        <el-select-v2 v-model="draft.industries" :options="industries" multiple filterable clearable placeholder="搜索并选择行业" aria-label="所属行业（多选）" class="industry-select" />
      </section>
      <section v-for="group in ruleGroups" :key="group.key" class="screen-section">
        <h3>{{ group.title }}</h3>
        <p class="screen-help">{{ group.help }}</p>
        <div class="screen-rules">
          <div v-for="(rule, index) in draft[group.key]" :key="index" class="screen-rule">
            <el-select-v2 v-model="rule.field" :options="group.options" filterable :aria-label="`${group.name}条件 ${index + 1}`" />
            <el-input v-model="rule.min" placeholder="下限（不限）" :aria-label="`${group.name}条件 ${index + 1} 下限`" />
            <span class="range-separator">至</span>
            <el-input v-model="rule.max" placeholder="上限（不限）" :aria-label="`${group.name}条件 ${index + 1} 上限`" />
            <el-button text type="danger" :aria-label="`删除${group.name}条件 ${index + 1}`" @click="draft[group.key].splice(index, 1)">删除</el-button>
            <p v-if="group.key === 'chipRules'" class="rule-description">{{ group.options.find(field => field.value === rule.field)?.description }}</p>
          </div>
        </div>
        <el-button plain :disabled="!group.options.length" @click="addRule(group.key, group.options)">＋ 添加{{ group.name }}{{ group.key === 'chipRules' ? '条件' : '' }}</el-button>
      </section>
    </div>
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
import { copyScreen, emptyScreen, fieldUnit, maScreenFields, matchesScreen, screenCount, screenError } from "@/utils/stockScreener";
import type { ScreeningField, StockScreen } from "@/utils/stockScreener";

const props = defineProps<{
  modelValue: StockScreen;
  fields: ScreeningField[];
  chipFields: ScreeningField[];
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
const fieldOptions = computed(() => props.fields.map(field => ({ ...field, label: `${field.label}${fieldUnit(field) ? ` (${fieldUnit(field)})` : ''}` })));
const chipOptions = computed(() => props.chipFields.map(field => ({ ...field, label: `${field.label} (${fieldUnit(field)})` })));
const ruleGroups = computed(() => [
  { key: 'maRules' as const, title: '2. 均线选择', name: '均线', options: maScreenFields,
    help: '斜率 = 当日 MA − 前一交易日 MA（价格 / 交易日），使用当前复权方式。可添加多条均线，各自设置范围；正值向上，负值向下，0 为走平。' },
  { key: 'rules' as const, title: '3. 指标选择', name: '指标', options: fieldOptions.value,
    help: '可添加多个 indicator，各自设置数值范围。百分比填百分数（5 表示 5%）；其他数值与图表提示一致，不使用“万 / 亿”缩写。价格使用未复权行情。' },
  { key: 'chipRules' as const, title: '4. 筹码过滤', name: '筹码', options: chipOptions.value,
    help: '支持多项同时过滤。集中度越小越集中；偏离和位置按同一复权口径计算。成本带位置可超过100或小于0。未配置或缺失的数据不参与命中。' },
]);
function addRule(key: 'maRules' | 'rules' | 'chipRules', options: ScreeningField[]) {
  const next = options.find(option => !draft.value[key].some(rule => rule.field === option.value)) || options[0];
  if (next) draft.value[key].push({ field: next.value, min: '', max: '' });
}
const industries = computed(() => [...new Set(props.symbols.map(s => s.industry_name).filter(Boolean))]
  .sort((a, b) => a!.localeCompare(b!, "zh-CN")).map(value => ({ label: value!, value: value! })));
const validationError = computed(() => screenError(draft.value, props.fields, props.chipFields));
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
.screen-sections { max-height: 55vh; overflow-y: auto; padding-right: 8px; }
.screen-section { padding: 16px; margin-bottom: 12px; border: 1px solid #e4e9f0; border-radius: 8px; }
.screen-section h3 { margin: 0; color: #303b51; font-size: 15px; }
.screen-section .screen-help { margin: 8px 0 12px; }
.industry-select { width: 100%; }
.screen-rule { display: grid; grid-template-columns: minmax(130px, 1.3fr) minmax(90px, 1fr) auto minmax(90px, 1fr) auto; align-items: center; gap: 8px; margin-bottom: 12px; }
.screen-rule :deep(.el-select-v2) { min-width: 0; }
.rule-description { grid-column: 1 / -1; margin: 0; color: #68758a; font-size: 12px; line-height: 1.7; }
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
