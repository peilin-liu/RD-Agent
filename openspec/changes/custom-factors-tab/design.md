## Context

RD-Agent 的 qlib 场景（fin_factor / fin_model / fin_quant）在 loop 中会弹 feature interaction 面板，让用户从 Alpha158 池池里挑因子注入 configured features。面板在 `web/src/views/PlaygroundPage.vue:410` 的 `feature-table` 区，源数据是前端常量 `ALPHA158`（`web/src/constants/qlib.js`）。

注入链路（已存在，本次不改）：
```
featureRows (UI configured features)
  → submitUserInteraction 提交 features: {name: expression}
  → 后端 user_response_q 回 rdagent 主进程
  → exp.base_features 填充
  → model_runner.py:83 注入 conf_baseline_factors_model.yaml 的 feature 字段
  → qrun 训练
```

本次在面板里加 Custom tab，让用户维护一份 `~/.rd-agent/factors.json`，自定义因子与 Alpha158 并列展示、共用同一条注入链路。

约束：
- 自定义因子**只读**——用户手编辑文件，UI 不提供增删改写回。
- 文件路径固定 `~/.rd-agent/factors.json`（跨场景共享，不分 scenario）。
- 不能破坏现有 Alpha158 tab 的行为与 CSS。

## Goals / Non-Goals

**Goals:**
- 在 feature-pool 区顶部加 tab，切 Alpha158 / Custom 两个源。
- Custom tab 从 `~/.rd-agent/factors.json` 拉因子，渲染成可点击标签，点击走原 `addFeatureFromPool` 注入。
- 懒加载：只在首次切到 Custom 时拉一次（避免每 loop 重拉）。
- 文档：把 qlib 全部可用算子 + 字段 + 表达式语法 + 示例落到 `docs/custom_factors.md`，用户有据可查。

**Non-Goals:**
- 不做 UI 增删改写回文件（用户手维护，简单优先）。
- 不做按 scenario 区分自定义因子文件（一份通用）。
- 不动 Alpha158 常量本身。
- 不动后端 `base_features` 注入链路（已通）。
- 不做自定义因子表达式的前端实时校验（仍由后端 `validate_qlib_features` 兜底）。

## Decisions

### D1. 文件位置 `~/.rd-agent/factors.json`，后端只读

**选择**：路径 `Path.home() / ".rd-agent" / "factors.json"`，后端 `GET /custom_factors` 只读返回。

**理由**：
- 与 `~/.rd-agent/` 这类用户级配置目录习惯一致（qlib 自身数据在 `~/.qlib/`）。
- 只读避免并发写冲突与权限问题。
- 缺失返回，不阻断 Alpha158 流程。

**备选**（已否）：
- 项目根 `custom_factors.json`：跨项目隔离差，多 trace 共用易污染。
- 上传目录 `base_factors.json`：那个是给 qrun 直接吃的注入文件，与 UI 展示源混用易错。

### D2. tab 切换不重置 configured features

**选择**：`featurePoolTab` 只决定 `availableFeatureTags` 的源，已加入 `featureRows` 的因子不动。两个 tab 的因子可混在 configured features 里。

**理由**：用户可能同时用 Alpha158 的几个因子 + 自定义的几个，切换 tab 不应丢失已选。

**备选**（已否）：切 tab 清空 configured features——破坏跨源组合用例。

### D3. 懒加载 + 缓存

**选择**：`customFactorsLoaded` 标志，首次切到 Custom 才调 `getCustomFactors()`，之后用缓存。刷新页面重新加载。

**理由**：loop 交互面板可能多次弹出，每次重拉浪费；用户改文件后刷新页面即可重拉。

### D4. 文档落在 `docs/custom_factors.md`

**选择**：独立用户向文档，含 factors.json 格式、qlib 字段表、全部算子分类表（滚动/双序列/逐元素逻辑）+ 签名含义、语法要点、示例、验证排错、参考来源。

**理由**：算子来自 qlib 库（`qlib.data.ops`），RD-Agent 无内置算子文档；用户写表达式时需要一站式参考，避免反复查 qlib 源码。算子列表通过 `python -c "import qlib.data.ops as ops; ..."` 抓取真实注册类 + `inspect.signature` + `inspect.getdoc`，非凭记忆。

## Risks / Trade-offs

- qlib 升级后算子可能增减——文档会过时。缓解：文档末尾列出 `python -c "import qlib.data.ops"` 查询命令，用户可自行核对。
- 自定义因子与 Alpha158 同名时，`availableFeatureTags` 的 used-set 过滤会让同名因子只显示一次（来自当前 tab），但 configured features 里可能重复——用户自行避免同名。
- `~/.rd-agent/` 目录需用户自建（示例文件已随本次改动写入，首次部署有内容可看）。

## Migration Plan

1. 后端加 `/custom_factors` 端点（本次已完成，编译通过）。
2. 前端加 API + state + tab UI + CSS（本次已完成）。
3. 写示例 `~/.rd-agent/factors.json`（本次已写入 5 个示例因子）。
4. 写 `docs/custom_factors.md`（本次已完成）。
5. 重启 `rdagent server_ui` + 重构前端，跑 `fin_model` 验证 Custom tab 能拉到因子、点击注入、提交后 qrun 用上自定义因子。
