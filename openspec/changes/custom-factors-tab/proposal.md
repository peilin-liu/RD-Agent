## Why

`fin_model` / `fin_quant` loop 跑到 feature interaction 时弹出选因子面板，原来只有 **Base features (Alpha158)** 一栏，展示 `web/src/constants/qlib.js` 里硬编码的 158 个 qlib 因子。用户想在 Alpha158 基础上加自定义因子（如自写的动量、量价关系、跨周期统计），没有 UI 入口，只能手改上传目录的 `base_factors.json` 或改前端常量。

需要一个 tab 切换，让用户在 Alpha158 之外维护一份自定义因子清单（只读、手工维护），在 loop 交互面板里与 Alpha158 并列展示、点击注入。

## What Changes

- **后端新增 `GET /custom_factors` 端点**（`rdagent/log/server/app.py`）：读 `~/.rd-agent/factors.json`，返回 `{name: expression}` 字典。文件不存在返回 `{}`；非 JSON 对象返回 400。
- **前端 API** `web/src/utils/api.js` + `api.d.ts`：新增 `getCustomFactors()` 调用该端点。
- **前端 UI** `web/src/views/PlaygroundPage.vue`：
  - feature-pool 区顶部加两个 tab：**Alpha158** / **Custom**。
  - 新增 state：`customFactors` / `customFactorsLoaded` / `customFactorsError` / `featurePoolTab`。
  - `availableFeatureTags` computed 按 tab 选源（ALPHA158 或 customFactors）。
  - 切到 Custom 时懒加载 `getCustomFactors()`；空态/错误态有提示文案。
  - 自定义因子点击注入走原 `addFeatureFromPool` 路径，与 Alpha158 同链路（`base_features` → `conf_baseline_factors_model.yaml` → qrun）。
  - CSS：新增 `.feature-pool-tabs` / `.feature-pool-tab` / `.feature-pool-empty`。
- **示例文件** `~/.rd-agent/factors.json`：写入 5 个示例因子（动量/量比/均线交叉/高低相关/收盘距 vwap）。
- **用户文档** `docs/custom_factors.md`：记录 factors.json 格式、qlib 字段、全部支持的算子（滚动统计/双序列滚动/逐元素与逻辑）+ 签名与含义、表达式语法要点、示例因子、验证排错。

## Impact

- **新增/修改代码**：后端约 25 行（新端点）、前端约 60 行（state + computed + template + CSS）、文档 1 篇。
- **依赖**：无新增（`json` / `Path` 后端已有；前端用已有 `request`）。
- **数据**：`~/.rd-agent/factors.json` 为用户手维护文件，缺失不影响 Alpha158 tab，Custom tab 显示空态。
- **兼容性**：纯新增能力，不破坏现有 Alpha158 流程。`feature-pool-block` 由 `v-if="availableFeatureTags.length"` 改为始终显示（让 tab 可见），原"全部已加完"的隐藏行为改成空态文案提示，体验一致。
- **BREAKING**：无。
