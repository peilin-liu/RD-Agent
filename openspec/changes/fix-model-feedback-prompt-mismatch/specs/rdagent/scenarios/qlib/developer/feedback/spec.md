## Context

RD-Agent 的 quant 场景下，每个 loop 通过 `QlibModelExperiment2Feedback.generate_feedback`（`rdagent/scenarios/qlib/developer/feedback.py:121`）把 model 实验结果喂给 LLM 生成 feedback，LLM 返回 JSON 含 `Decision` 字段决定是否替换 SOTA。

## Requirements

### Requirement: `fin_model` 单独跑时 feedback decision 能正常反映 LLM 评估
当用户运行 `fin_model`（scenario = `QlibModelScenario`，非 `QlibQuantScenario`）时，`QlibModelExperiment2Feedback` 必须用 `model_feedback_generation` prompt（问 `Decision`），读取代码读 `Decision`。两者字段必须一致，使 LLM 认可时 `HypothesisFeedback.decision = True`，hypothesis 成为 SOTA。

#### Scenario: fin_model 的非首轮 loop 被认可

- **GIVEN** 一个跑 `fin_model` 的 trace，Loop_0 已成 SOTA，Loop_1 跑出新模型且 LLM 评估认可
- **WHEN** `QlibModelExperiment2Feedback.generate_feedback` 被调用
- **THEN**
  - LLM 收到的 system prompt 来自 `model_feedback_generation`（包含 `"Decision": <true or false>` 字段说明）
  - LLM 返回 JSON 含 `"Decision": true`
  - `HypothesisFeedback.decision == True`
  - 该 hypothesis 成为新 SOTA

### Requirement: fin_quant 行为不变
`fin_quant`（scenario = `QlibQuantScenario`）继续走原 if 分支逻辑：用 `model_feedback_generation` prompt + `get_scenario_all_desc(action="model")` 取模型部分描述。

#### Scenario: fin_quant 的 feedback 字段一致

- **GIVEN** 一个跑 `fin_quant` 的 trace
- **WHEN** `QlibModelExperiment2Feedback.generate_feedback` 被调用
- **THEN**
  - system prompt 来自 `model_feedback_generation`
  - scenario 描述通过 `get_scenario_all_desc(action="model")` 取
  - 读取代码读 `Decision` 字段

### Requirement: `QlibModelScenario.get_scenario_all_desc` 不被传 `action` 参数
`QlibModelScenario.get_scenario_all_desc` 签名只收 `task` / `filtered_tag` / `simple_background`，不收 `action`。`QlibModelExperiment2Feedback` 在 else 分支调它时**不得**传 `action`，否则 TypeError。

#### Scenario: 调用 QlibModelScenario 的 desc 不传 action

- **GIVEN** scenario 为 `QlibModelScenario`
- **WHEN** 取 scenario 描述
- **THEN** 调用 `self.scen.get_scenario_all_desc()`（无 `action` 参数），不抛 TypeError
