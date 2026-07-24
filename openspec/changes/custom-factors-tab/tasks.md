## Context

RD-Agent qlib 场景的 feature interaction 面板原只有 Alpha158 一栏。本次加 Custom tab，从 `~/.rd-agent/factors.json` 读自定义因子。

## Tasks

### 1. 后端

- [x] `rdagent/log/server/app.py`：新增 `GET /custom_factors` 端点，读 `~/.rd-agent/factors.json`，返回 `{name: expression}`。文件缺失返回 `{}`，非对象返回 400。
- [x] `python -c "import py_compile; py_compile.compile('rdagent/log/server/app.py', doraise=True)"` 通过。

### 2. 前端

- [x] `web/src/utils/api.js`：新增 `getCustomFactors()`。
- [x] `web/src/utils/api.d.ts`：补 `getCustomFactors` 类型声明。
- [x] `web/src/views/PlaygroundPage.vue`：import `getCustomFactors`；新增 state `customFactors`/`customFactorsLoaded`/`customFactorsError`/`featurePoolTab`；`availableFeatureTags` 按 tab 选源；新增 `loadCustomFactors` + `onFeaturePoolTabChange`；template 加 tab UI + 空态/错误态；CSS 加 `.feature-pool-tabs`/`.feature-pool-tab`/`.feature-pool-empty`。
- [ ] 重构前端后跑 `fin_model`，验证 Custom tab 拉到因子、点击注入、提交后 qrun 用上自定义因子。

### 3. 示例 + 文档

- [x] `~/.rd-agent/factors.json`：写入 5 个示例因子（动量/量比/均线交叉/高低相关/收盘距 vwap）。
- [x] `docs/custom_factors.md`：factors.json 格式、qlib 字段、全部算子分类表 + 签名含义、表达式语法、示例、验证排错、参考来源。
- [x] `openspec/changes/custom-factors-tab/`：proposal.md + design.md + tasks.md 记录变更。

## Verification

- [ ] 重启 `rdagent server_ui`，`curl http://localhost:<port>/custom_factors` 返回 5 个因子。
- [ ] 前端 `fin_model` loop 弹 feature interaction 面板，顶部有 Alpha158 / Custom 两个 tab。
- [ ] 切 Custom 看到示例因子标签，点击加入 configured features。
- [ ] 提交后 trace log 出现 `Loaded base features ... N features loaded`（N 含自定义因子）。
- [ ] mlruns `params/feature_names` 含自定义因子名。
