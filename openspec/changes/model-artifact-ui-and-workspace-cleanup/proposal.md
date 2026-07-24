## Why

RD-Agent 跑 factor/model pipeline 后产出的模型工件（`mlruns/<exp>/<rec>/artifacts/params.pkl`、`pred.pkl`、`label.pkl` 等）目前被 qlib MLflow 写到 `RD-Agent_workspace/<uuid>/mlruns/` 子目录下，**不在 `workspace.file_dict` 里**（`file_dict` 只存 `.py`/`.md` 源码字符串，见 `rdagent/core/experiment.py:164`）。因此 UI 的 Trace 页 Files popover（`rdagent/log/ui/ds_trace.py:199` `workspace_win`）只能展示和下载代码，**无法看到或下载模型工件**。用户即使 pipeline 完整跑通，也无法从 UI 拿到训练好的模型，必须手工 `find ... -name params.pkl`。

同时，每次 loop 都会在 `RD-Agent_workspace/` 下生成新的 `<uuid>` 工作区目录（因子 workspace + 含 mlruns 的实验 workspace），叠加 `pickle_cache/`、`factor_implementation_source_data/` 等缓存目录。这些目录目前**无清理命令、UI 无清理入口**，磁盘占用持续增长（实测单次 whole pipeline 多 loop 即可产生数 GB），用户无法删除也无法复用，影响长期可用性。

## What Changes

- **新增模型工件扫描与展示**：在 `workspace_win` 的 Files popover 中，若该 workspace 关联的实验 workspace 存在 `mlruns/<exp>/<rec>/artifacts/` 目录，列出其中的工件文件（`params.pkl`/`pred.pkl`/`label.pkl`/`portfolio_analysis/`/`sig_analysis/` 等），并支持逐个下载。
- **新增 trace 锚定的 workspace 清理 CLI**：以 trace 任务为锚点反向关联 workspace——扫 trace 目录下所有 `.pkl`（结构化 `workspace_path` 字段）与 `.log`（兜底 grep `RD-Agent_workspace/<32hex>`）取并集，得到该 trace 生成的全部 workspace uuid 列表。CLI `python -m rdagent.app.utils.workspace_cleanup <trace_path>` 默认 dry-run，列出将删的 workspace 路径 + 总占用，加 `--execute` 才真正删除；删除 trace 目录的同时联动删除关联 workspace，并清理 `pickle_cache/`、`factor_implementation_source_data[_debug]/` 中仅被该 trace 引用的条目。入口**：在 Trace 页的任务列表行加 "Delete task & workspace" 按钮（与 trace 任务一一对应），删除前弹窗显示将清理的 workspace 路径列表 + 总磁盘占用 + 关联 trace 文件，二次确认后执行；删除走与 CLI 相同的 uuid 反查 + 安全校验。
- **BREAKING**：无。所有清理操作默认 dry-run + 显式确认；UI 展示新增为附加面板，不改动现有 Files popover 对 `.py`/`.md` 的展示逻辑。

## Capabilities

### New Capabilities
- `model-artifact-presentation`: 在 UI 中扫描、展示、下载与 workspace 关联的 qlib MLflow 模型工件（`params.pkl` 等）。
- `workspace-cleanup`: 提供 CLI 与 UI 入口，以 trace 任务为锚点反查并删除其生成的全部 workspace 与相关缓存，支持 dry-run、二次确认、批量删除。

### Modified Capabilities
<!-- 无既有 specs，首次变更 -->

## Impact

- **新增/修改代码**：
  - `rdagent/log/ui/ds_trace.py` — `workspace_win` 内增加 mlruns 工件扫描与下载按钮（修改 ~50 行）
  - `rdagent/log/ui/ds_summary.py` 或新建 `rdagent/log/ui/ds_cleanup.py` — 工作区清理 UI 面板（新增 ~150 行）
  - 新增 `rdagent/app/utils/workspace_cleanup.py` — CLI 入口与清理逻辑（新增 ~200 行）
  - `rdagent/core/experiment.py` 或 `rdagent/scenarios/qlib/experiment/workspace.py` — 增加从 experiment workspace 反查 mlruns 路径的辅助方法（新增 ~30 行）
- **依赖**：可能用到 `streamlit` 已有的 `st.download_button`；CLI 无新外部依赖（仅标准库 + 已有 `RD_AGENT_SETTINGS`）。
- **数据/磁盘**清理操作不可逆，需严格 dry-run + 确认；不能误删活跃 trace 引用的工作区。
- **兼容性**：纯新增能力，不破坏现有 trace 格式与 workspace 结构。
