## Context

RD-Agent 是 spec-driven 的 quant R&D agent。`fin_model` 与 `fin_quant` pipeline 都通过 `QlibModelExperiment2Feedback.generate_feedback`（`rdagent/scenarios/qlib/developer/feedback.py:121`）为每个 loop 生成 model hypothesis feedback，LLM 返回 JSON 的 `Decision` 字段决定是否替换 SOTA。

## Tasks

### 1. 修复 prompt/读取字段不一致

- [ ] 改 `rdagent/scenarios/qlib/developer/feedback.py:138-145`：始终用 `model_feedback_generation` system prompt，if/else 只决定 scenario desc 取法（`QlibQuantScenario` 传 `action="model"`，其他无 `action`）。
- [ ] 回退 line 185 的字段兼容 workaround，恢复原生 `convert2bool(response_json_hypothesis.get("Decision", "false"))`。
- [ ] `python -c "import py_compile; py_compile.compile('rdagent/scenarios/qlib/developer/feedback.py', doraise=True)"` 编译校验通过。

### 2. 验证

- [ ] 重启 rdagent 服务重载 Python 代码。
- [ ] 新跑一个 `fin_model` trace（至少 2 个 loop），从 `git_ignore_folder/traces/Finance Model Implementation/<trace>/Loop_*/feedback/feedback/*.pkl` 加载 `HypothesisFeedback`，确认 `decision` 能为 True（LLM 认可时）。
- [ ] 新跑一个 `fin_quant` trace 的一个 loop，确认行为不变（仍走 if 分支，decision 字段一致）。
- [ ] 进 Result 页核对被接受的 SOTA hypothesis 对应的 loop 与模型工件。

### 3. 文档记录

- [x] 在 `openspec/changes/fix-model-feedback-prompt-mismatch/` 下写 proposal.md / design.md / tasks.md / spec.md 记录根因、决策、验证步骤。
- [ ] 确认 `QlibModelScenario.get_scenario_all_desc` 不收 `action` 这一约束已写入 design.md D2 与 spec.md。
