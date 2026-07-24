## Why

单独跑 `fin_model`（Finance Model Implementation）时，每个 loop 的 `HypothesisFeedback.decision` **永远是 False**，无论 LLM 实际评估是否认可。用户因此始终拿不到被接受的 SOTA 模型，"训练出一个能用模型" 这一最基本目标无法达成。

根因在 `rdagent/scenarios/qlib/developer/feedback.py:138-145`：`QlibModelExperiment2Feedback.generate_feedback` 按 scenario 类型分支选 prompt：

```python
if isinstance(self.scen, QlibQuantScenario):
    sys_prompt = model_feedback_generation   # system prompt 期望 LLM 返回 "Decision"
else:
    sys_prompt = factor_feedback_generation  # system prompt 期望 LLM 返回 "Replace Best Result"
```

但下面读取代码始终是 `response_json_hypothesis.get("Decision", "false")`（feedback.py:185）。

字段名不一致：

| 命令 | Scenario | 分支 | LLM 被问字段 | 代码读字段 | 结果 |
|------|----------|------|-------------|-----------|------|
| `fin_quant` | `QlibQuantScenario` | if | `Decision` | `Decision` | ✓ 正常 |
| `fin_model` | `QlibModelScenario` | else | `Replace Best Result` | `Decision` | ✗ 永远 False |

实测 tempered-dictionary trace 3 个 loop，LLM 在 `debug_llm/*.pkl` 的原始响应**全部返回 `"Replace Best Result": "yes"`**（想换 SOTA），但代码因找不到 `Decision` 键命中默认 `"false"` → `convert2bool("false") = False`，所有 loop 全部 reject。

`fin_quant`（全流程）走 if 分支，字段一致，正常工作——这就是为什么该 regression 一直没被发现：官方主推 quant 全流程，`fin_model` 单独路径成漏网之鱼。

### 这是上游 regression，非本地引入

- 该分支逻辑由官方 commit `6e42d523 "feat: add RD-Agent-Quant scenario"`（2025-05-29, Yuante Li）引入。
- 重构前（`6e42d523~1`）`QlibModelExperiment2Feedback` 始终用 `model_feedback_generation` prompt + 读 `Decision`，**一致、正常**。
- `git blame` 确认 line 138 的分支判断与 line 185 的 `get("Decision")` 都源自 `6e42d523`，重构时漏改了 else 分支的读取字段。
- `git status` 显示本地 conf.py 仅改了 train/valid/test 日期段，与该 bug 无关。

## What Changes

- `QlibModelExperiment2Feedback.generate_feedback` 始终使用 `model_feedback_generation` system prompt（即问 LLM `Decision`），删掉错误的 factor prompt else 分支。if/else 现在只决定 scenario 描述如何取：`QlibQuantScenario` 传 `action="model"`（取模型部分描述），其他（如 `QlibModelScenario`）调 `get_scenario_all_desc()`（无 `action` 参数，因 `QlibModelScenario.get_scenario_all_desc` 签名不收 `action`）。
- 删除我此前临时加的字段兼容 workaround（`get("Decision") or get("Replace Best Result")`），恢复原生 `get("Decision", "false")`。字段两端干净一致，不留 hack。

## Impact

- **修改代码**：`rdagent/scenarios/qlib/developer/feedback.py`（约 10 行改动）。
- **依赖**：无新增。
- **行为变化**：`fin_model` 的 loop feedback `decision` 现在能正常反映 LLM 评估（认可时为 True，被接受的 hypothesis 成为 SOTA）。`fin_quant` 行为不变（原就走 if 分支）。
- **兼容性**：`QlibModelScenario` 与 `QlibQuantScenario` 都直接继承 `Scenario`，互无父子关系；改动不引入新依赖、不改 trace 格式、不改 workspace 结构。
- **BREAKING**：无。`fin_model` 此前实际不可用（永远 reject），修复后变可用，不算 breaking。
