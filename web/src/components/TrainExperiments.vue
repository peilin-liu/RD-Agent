<template>
  <div class="train-experiments">
    <div class="toolbar">
      <h1>Training Experiments</h1>
      <el-button @click="poll(true)" :loading="loading">刷新</el-button>
      <el-button type="primary" @click="showCreate = !showCreate">{{ showCreate ? '收起参数' : '新建训练' }}</el-button>
      <span class="source-path">{{ dataDir }}</span>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div v-if="showCreate" class="create-panel">
      <p>固定调用 train 入口。只启用需要覆盖的参数，其他值由训练配置决定。</p>
      <details v-for="group in groups" :key="group.title" :open="group.title === '实验与数据'">
        <summary>{{ group.title }}</summary>
        <div class="parameter-grid">
          <label v-for="field in group.fields" :key="field.name" class="parameter">
            <input type="checkbox" v-model="common[field.name].enabled" />
            <span>{{ field.label || field.name }}</span>
            <select v-if="field.boolean" v-model="common[field.name].value" :disabled="!common[field.name].enabled">
              <option value="true">开启</option><option value="false">关闭</option>
            </select>
            <input v-else v-model="common[field.name].value" :disabled="!common[field.name].enabled" placeholder="沿用训练配置" />
          </label>
        </div>
      </details>
      <details>
        <summary>其他脚本参数</summary>
        <p>所有脚本选项均可填写；开关填写实际选项名，例如 no-lock-thread-rand。</p>
        <div v-for="(row, index) in advanced" :key="index" class="advanced-row">
          <input v-model="row.name" placeholder="参数名，例如 num-boost-round" />
          <select v-model="row.kind"><option value="value">带值参数</option><option value="flag">开关</option></select>
          <input v-if="row.kind === 'value'" v-model="row.value" placeholder="参数值，可为空字符串" />
          <el-button @click="advanced.splice(index, 1)">删除</el-button>
        </div>
        <el-button @click="advanced.push({ name: '', value: '', kind: 'value' })">添加参数</el-button>
      </details>
      <div class="form-actions">
        <el-button @click="preview" :loading="submitting">预览参数</el-button>
        <el-button type="primary" @click="start" :loading="submitting">开始训练</el-button>
      </div>
      <pre v-if="previewData" class="preview">{{ JSON.stringify(previewData.argv, null, 2) }}</pre>
      <p>rolling-exp-name 按填写值传递；训练侧重跑同名实验可能替换原有结果。</p>
    </div>

    <div v-if="tasks.length" class="task-list">
      <div v-for="task in tasks.slice(0, 8)" :key="task.id" class="task-row">
        <span>{{ task.created_at }} · {{ task.state }}</span>
        <span>{{ task.output_dir || '等待训练生成输出目录' }}</span>
        <el-button v-if="['pending', 'running', 'stopping'].includes(task.state)" size="small" @click="stop(task.id)">停止</el-button>
        <details v-if="task.error"><summary>调用错误</summary><pre>{{ task.error }}</pre></details>
      </div>
    </div>

    <div class="selector">
      <el-select v-model="selected" @change="selectExperiment" filterable placeholder="选择训练实验" style="width: min(700px, 100%)">
        <el-option v-for="item in experiments" :key="item.id" :value="item.id" :label="`${item.name} · ${item.execution_state}`" />
      </el-select>
      <span v-if="!experiments.length && !loading">尚未发现实验，请检查 train_data_dir。</span>
    </div>
    <template v-if="current">
      <div class="progress-panel">
        <strong>阶段：{{ stageLabel(current.progress?.stage) }}</strong>
        <span>调用：{{ current.execution_state }}</span>
        <span v-if="current.progress?.total_windows != null">窗口训练：{{ current.progress.completed_windows }}/{{ current.progress.total_windows }}</span>
        <span v-else>已完成窗口：{{ current.progress?.completed_windows || 0 }}</span>
        <span v-if="current.progress?.backtest">回测：{{ current.progress.backtest.completed }}/{{ current.progress.backtest.total }}</span>
        <span>最后观测：{{ current.progress?.observed_at || '未知' }}</span>
        <span v-if="current.progress?.log_updated_at">日志更新：{{ current.progress.log_updated_at }}</span>
        <span v-if="current.progress?.recovering">正在重放日志…</span>
        <span v-if="current.terminal">退出码：{{ current.terminal.exit_code }}<template v-if="current.terminal.failed_stage"> · 失败阶段：{{ current.terminal.failed_stage }}</template></span>
        <span v-if="current.progress?.latest_training_output">最近训练输出：{{ current.progress.latest_training_output }}</span>
      </div>
      <el-alert v-for="message in warnings" :key="message" :title="message" type="warning" :closable="false" />
      <details class="log-panel" open>
        <summary>原始训练日志 <a :href="detail?.log_download_url">下载</a></summary>
        <pre>{{ logText || '等待日志输出…' }}</pre>
      </details>
      <p v-if="detailLoading">正在加载实验结果…</p>
      <template v-if="detail">
        <ResultPage :currentData="resultData" :traceName="detail.name" scenarioName="Qlib Training"
          :externalMode="true" :externalArtifacts="detail.artifacts || []" :logDownloadUrl="detail.log_download_url" />
        <Feedback :currentData="detail.view" :updateEnd="true" :resultsOnly="true" />
        <div class="windows" v-if="detail.windows?.length">
          <h2>滚动窗口</h2>
          <el-table :data="detail.windows" @row-click="loadHistory" style="width: 100%">
            <el-table-column prop="key" label="窗口" width="130" />
            <el-table-column label="训练区间"><template #default="scope">{{ segment(scope.row, 'train') }}</template></el-table-column>
            <el-table-column label="验证区间"><template #default="scope">{{ segment(scope.row, 'valid') }}</template></el-table-column>
            <el-table-column label="测试区间"><template #default="scope">{{ segment(scope.row, 'test') }}</template></el-table-column>
            <el-table-column prop="run_id" label="Run ID" />
          </el-table>
          <p>选择窗口查看已有训练指标。</p>
          <el-select v-if="historyKeys.length" v-model="historyMetric"><el-option v-for="key in historyKeys" :key="key" :label="key" :value="key" /></el-select>
          <LineChart v-if="historyKeys.length" :data="historyData" :chartName="historyMetric" color="blue" />
          <p v-else-if="historyRequested">该窗口没有可读取的训练历史，模型文件仍可从 Model files 查看。</p>
        </div>
      </template>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { createTrainTask, getTrainExperiment, getTrainExperiments, getTrainHistory, getTrainLog, getTrainTasks, previewTrainTask, stopTrainTask } from '../utils/api';
import { qlibDisplayMetrics } from '../utils/qlibMetrics';
import ResultPage from '../views/ResultPage.vue';
import Feedback from './feedback.vue';
import LineChart from './lineChartOne.vue';

const fields = (names) => names.split(' ').map(name => ({ name }));
const groups = [
  { title: '实验与数据', fields: fields('rolling-exp-name config symbols benchmark data-root factor-files factor-dir out-dir label-expr') },
  { title: '数据区间', fields: fields('train-start train-end valid-start valid-end fit-start fit-end test-start test-end') },
  { title: 'LightGBM', fields: fields('learning-rate max-depth num-leaves min-data-in-leaf lambda-l1 lambda-l2 colsample-bytree subsample num-threads num-boost-round early-stopping-metric early-stopping-rounds') },
  { title: '滚动训练', fields: [...fields('rolling-step rolling-train-step rolling-horizon parallel'), { name: 'lock-thread-rand', boolean: true }, { name: 'rolling-warm-start', boolean: true }] },
  { title: '策略与信号', fields: [...fields('topk hold-thresh n-drop rank-exit-threshold max-n-drop tilt-low pe-penalty pe-high-threshold new-stock-min-sessions new-stock-observation-sessions new-stock-penalty st-penalty open-cost close-cost min-cost'), { name: 'equal-weight-target', boolean: true }] },
];
const common = reactive(Object.fromEntries(groups.flatMap(g => g.fields).map(f => [f.name, { enabled: false, value: f.boolean ? 'true' : '' }])));
const advanced = ref([]);
const showCreate = ref(false);
const submitting = ref(false);
const previewData = ref(null);
const experiments = ref([]);
const tasks = ref([]);
const selected = ref('');
const detail = ref(null);
const detailLoading = ref(false);
const error = ref('');
const loading = ref(false);
const dataDir = ref('');
const logText = ref('');
const history = ref({});
const historyMetric = ref('');
const historyRequested = ref(false);
const route = useRoute();
const router = useRouter();
let timer, disposed = false, polling = false, selectionVersion = 0;
let logOffset = 0, logGeneration = '';

const current = computed(() => experiments.value.find(row => row.id === selected.value));
const warnings = computed(() => [...new Set([...(current.value?.errors || []), ...(detail.value?.errors || [])])]);
const resultData = computed(() => detail.value?.view ? [{ ...detail.value.view,
  executionState: current.value?.execution_state || detail.value.execution_state,
  feedbackMetric: qlibDisplayMetrics(detail.value.metrics) }] : []);
const historyKeys = computed(() => Object.keys(history.value));
const historyData = computed(() => (history.value[historyMetric.value] || []).map(p => ({ name: String(p.step), value: p.value })));
const segment = (row, key) => (row.segments?.[key] || []).join(' ~ ');
const stageLabel = (stage) => ({ unknown: '未确认', loading: '数据准备', training: '窗口训练', merging: '预测集成', backtesting: '回测', result_written: '结果已生成', completed: '完成', failed: '失败', interrupted: '中断' }[stage] || stage || '未确认');

function overrides() {
  const rows = [];
  for (const group of groups) for (const field of group.fields) {
    const item = common[field.name];
    if (!item.enabled) continue;
    rows.push(field.boolean ? { name: item.value === 'false' ? `no-${field.name}` : field.name, kind: 'flag' }
      : { name: field.name, kind: 'value', value: item.value });
  }
  return [...rows, ...advanced.value.map(row => ({ ...row }))];
}

async function preview() {
  submitting.value = true;
  try { previewData.value = await previewTrainTask(overrides()); error.value = ''; }
  catch (e) { error.value = e.message; }
  finally { submitting.value = false; }
}

async function start() {
  submitting.value = true;
  try { await createTrainTask(overrides()); error.value = ''; showCreate.value = false; await poll(true); }
  catch (e) { error.value = e.message; }
  finally { submitting.value = false; }
}

async function stop(id) {
  try { await stopTrainTask(id); await poll(); }
  catch (e) { error.value = e.message; }
}

async function loadDetail(force = false) {
  const id = selected.value, version = selectionVersion;
  if (!id || !force && detail.value?.id === id && detail.value.result_revision === current.value?.result_revision) return;
  detailLoading.value = true;
  try {
    const data = await getTrainExperiment(id);
    if (!disposed && version === selectionVersion && id === selected.value) detail.value = data;
  } finally { if (!disposed && version === selectionVersion) detailLoading.value = false; }
}

async function readLog() {
  const id = selected.value, version = selectionVersion;
  if (!id) return;
  try {
    const data = await getTrainLog(id, logOffset, logGeneration);
    if (disposed || version !== selectionVersion) return;
    logText.value = ((data.reset ? '' : logText.value) + data.text).slice(-40000);
    logOffset = data.offset; logGeneration = data.generation;
  } catch (e) {
    if (!disposed && version === selectionVersion && !logText.value) logText.value = e.message;
  }
}

async function selectExperiment() {
  selectionVersion += 1;
  detail.value = null; logText.value = ''; logOffset = 0; logGeneration = '';
  history.value = {}; historyRequested.value = false;
  router.replace({ query: { ...route.query, train_experiment: selected.value } });
  try { await loadDetail(true); await readLog(); }
  catch (e) { if (!disposed) error.value = e.message; }
}

async function loadHistory(window) {
  const version = selectionVersion;
  try {
    const data = await getTrainHistory(selected.value, window.prediction_run_id || window.run_id);
    if (!disposed && version === selectionVersion) {
      history.value = data.series || {}; historyMetric.value = Object.keys(history.value)[0] || ''; historyRequested.value = true;
    }
  } catch (e) { error.value = e.message; }
}

async function poll(force = false) {
  clearTimeout(timer);
  if (polling || disposed) return;
  polling = true; loading.value = true;
  try {
    const [data, taskData] = await Promise.all([getTrainExperiments(), getTrainTasks()]);
    if (disposed) return;
    experiments.value = data.experiments || []; tasks.value = taskData.tasks || []; dataDir.value = data.train_data_dir;
    error.value = '';
    if (!selected.value || !experiments.value.some(row => row.id === selected.value)) {
      selected.value = experiments.value.find(row => row.id === route.query.train_experiment)?.id || experiments.value[0]?.id || '';
      if (selected.value) await selectExperiment();
    } else { await loadDetail(force); await readLog(); }
  } catch (e) { if (!disposed) error.value = e.message; }
  finally {
    polling = false;
    if (!disposed) { loading.value = false; timer = setTimeout(() => poll(), 2500); }
  }
}

onMounted(() => poll());
onUnmounted(() => { disposed = true; selectionVersion += 1; clearTimeout(timer); });
</script>

<style scoped>
.train-experiments { padding: 1.2em; width: 100%; box-sizing: border-box; }
.toolbar, .selector, .progress-panel, .form-actions, .task-row { display: flex; gap: 1em; align-items: center; flex-wrap: wrap; margin: 1em 0; }
h1 { margin-right: auto; font-size: 1.5em; } h2 { font-size: 1.3em; margin: 1em 0; }
.source-path { color: #666; font-size: .9em; }
.create-panel, .progress-panel, .log-panel, .task-list { background: var(--bg-white, white); border: 1px solid #dce2ef; border-radius: 10px; padding: 1em; margin: 1em 0; }
.parameter-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: .6em 1.5em; margin: 1em 0; }
.parameter { display: flex; gap: .5em; align-items: center; } .parameter span { width: 11em; overflow-wrap: anywhere; }
.parameter input:not([type=checkbox]), .parameter select { flex: 1; min-width: 0; }
input, select { padding: .4em; border: 1px solid #cbd5e1; border-radius: 4px; }
input:disabled, select:disabled { background: #f4f5f7; }
.advanced-row { display: flex; gap: .5em; margin: .6em 0; flex-wrap: wrap; }
details { margin: .6em 0; } summary { cursor: pointer; font-weight: 600; } p { margin: .6em 0; color: #666; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font: 12px/1.6 monospace; }
.log-panel pre { max-height: 320px; overflow: auto; background: #f6f8fb; padding: .8em; }
.preview { max-height: 250px; overflow: auto; }
.task-row { border-bottom: 1px solid #eee; padding-bottom: .5em; }
.progress-panel span { font-size: .9em; } .windows { margin: 1.5em 0; }
</style>
