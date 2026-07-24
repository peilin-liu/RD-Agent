## Context

`QlibModelExperiment2Feedback`（`rdagent/scenarios/qlib/developer/feedback.py:121`）是 fin_model / fin_quant pipeline 生成 model hypothesis feedback 的类。它做两件事：

1. 构造 system + user prompt 喂给 LLM，让 LLM 返回 JSON（含 observations / hypothesis_evaluation / new_hypothesis / reasoning / decision 字段）。
2. 从 JSON 读 `Decision` 字段（line 185：`convert2bool(response_json_hypothesis.get("Decision", "false"))`），作为 `HypothesisFeedback.decision`，决定是否替换 SOTA。

两个 system prompt 模板（`rdagent/scenarios/qlib/prompts.yaml`）问 LLM 的字段名不同：
- `model_feedback_generation`（line 245-252）→ `"Decision": <true or false>`
- `factor_feedback_generation`（line 170-208）→ `"Replace Best Result": "yes or no"`

因此**该类只有配 `model_feedback_generation` prompt 才字段对得上**。

两个 scenario 类的继承结构（无父子关系）：

```
Scenario (core)
├── QlibFactorScenario       (factor_experiment.py)  → fin_factor
├── QlibModelScenario        (model_experiment.py)   → fin_model
└── QlibQuantScenario        (quant_experiment.py)    → fin_quant
```

`QlibQuantScenario.get_scenario_all_desc` 收 `action` 参数（可传 `action="model"` 取模型部分描述）；`QlibModelScenario.get_scenario_all_desc` 不收 `action`（已经是 model-only，没有分部可挑）。

约束：
- `QlibModelScenario` 不继承 `QlibQuantScenario`，`isinstance` 检查对它返回 False。
- 不能给 `QlibModelScenario.get_scenario_all_desc` 传 `action="model"`（会 TypeError）。

## Goals / Non-Goals

**Goals:**
- 让 `fin_model` 单独跑时 feedback `decision` 能正常反映 LLM 评估。
- 字段两端（prompt 问什么 / 代码读什么）干净一致，不留字段兼容 workaround。

**Non-Goals:**
- 不重构 scenario 类继承关系。
- 不改 prompt 模板内容（`Decision` vs `Replace Best Result` 保留各自原貌，因 model 与 factor pipeline 各自有对应读取代码）。
- 不动 `QlibFactorExperiment2Feedback`（line 117 读 `Replace Best Result`，与 factor prompt 一致，本来就对）。

## Decisions

### D1. 始终用 `model_feedback_generation` prompt，不按 scenario 分支

**选择**：

```python
if isinstance(self.scen, QlibQuantScenario):
    scenario_desc = self.scen.get_scenario_all_desc(action="model")
else:
    scenario_desc = self.scen.get_scenario_all_desc()
sys_prompt = T("scenarios.qlib.prompts:model_feedback_generation.system").r(
    scenario=scenario_desc
)
```

**理由**：
- 这是 `QlibModelExperiment2Feedback`，本就是为 model 实验生成 feedback，逻辑上就该用 model prompt。
- 读代码固定读 `Decision`，prompt 必须固定问 `Decision`，字段才能对上。
- `fin_model` 用 factor prompt 是 quant 重构时误配，非有意。

**备选**（已否）：
- 保留分支 + 改读取代码兼容两个字段（`get("Decision") or get("Replace Best Result")`）：能修但留 workaround，掩盖 prompt/读取不对齐的根因，未来再改 prompt 容易再踩。
- 让 `QlibModelScenario` 继承 `QlibQuantScenario`：改继承链影响面太大，远超本次修复目标。

### D2. if/else 只决定 scenario desc 的 `action` 参数

**选择**：保留 if/else 但语义改成"按 scenario 类型选 desc 取法"：`QlibQuantScenario` 传 `action="model"`（取模型部分），其他调 `get_scenario_all_desc()`。

**理由**：
- `QlibQuantScenario` 全流程含 factor + model + trade，需 `action="model"` 截取模型相关描述喂给 LLM。
- `QlibModelScenario` 已经是 model-only，`get_scenario_all_desc` 签名不收 `action`，传了会 TypeError，故走无参版本。
- 这样两种 scenario 都能拿到合适的 model 相关描述，且都不踩签名限制。

### D3. 回退字段兼容 workaround

**选择**：恢复原生 `decision=convert2bool(response_json_hypothesis.get("Decision", "false"))`。

**理由**：D1 已让 prompt 和读取字段一致（都 `Decision`），不再需要 fallback。留 fallback 反而让人误以为 LLM 会返回两种字段名，掩盖根因。

## Risks / Trade-offs

- `fin_model` 行为变化最明显：此前所有 loop 永远 reject，修复后 LLM 认可时 decision=True，hypothesis 成为 SOTA。这是修复目标，不算 regression。
- 历史跑出的 trace（如 tempered-dictionary）已存 feedback pkl 的 `decision=False` 不会自动改——这些是历史快照，按当前跑新 trace 验证即可。
- 若未来再加新 scenario 给 `QlibModelExperiment2Feedback`，需要确保它的 `get_scenario_all_desc` 也能无 `action` 调用，或在该处再加分支。这是低概率，记在此处供后续维护者参考。

## Migration Plan

1. 改 `feedback.py:138-145` 与 line 185（本次已完成）。
2. `python -c "import py_compile; py_compile.compile('rdagent/scenarios/qlib/developer/feedback.py', doraise=True)"` 编译校验通过。
3. 重启 `rdagent` 服务重载 Python 代码。
4. 新跑一个 `fin_model` trace，验证 loop feedback 的 `decision` 能变 True（LLM 认可时）。
5. 进 Result 页核对 SOTA 标记与对应 loop 的模型工件。
