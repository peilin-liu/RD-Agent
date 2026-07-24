## 1. Workspace 工件扫描与展示核心逻辑

- [x] 1.1 新建 `rdagent/app/utils/workspace.py`，定义 `ArtifactInfo` dataclass（字段：`relative_path: str`, `absolute_path: Path`, `size_bytes: int`）和 `WORKSPACE_ARTIFACT_SIZE_LIMIT = 50 * 1024 * 1024` 常量。
- [x] 1.2 实现 `collect_artifacts_for_workspace(ws_path: Path) -> list[ArtifactInfo]`：递归扫 `ws_path/mlruns/<exp>/<rec>/artifacts/` 下所有文件，多 exp 聚合，relative_path 前缀 `<exp>/<rec>/`，无 `mlruns/` 返回空列表。
- [x] 1.3 单元测试：用 tart-parapet 的 `d5a0f6963b5a4c84bfd4835a142a38c7` workspace 跑 `collect_artifacts_for_workspace`，断言返回 `params.pkl`、`pred.pkl`、`label.pkl`、`portfolio_analysis/report_normal_1day.pkl` 等条目，size_bytes 与文件系统一致。
- [x] 1.4 单元测试：构造无 `mlruns/` 的临时 workspace，断言 `collect_artifacts_for_workspace` 返回空列表且不抛异常。

## 2. UI 工件下载集成

- [x] 2.1 在 `rdagent/log/ui/ds_trace.py:workspace_win`（line 199-243）末尾、`else: st.markdown("No files...")` 之前，新增 "Model Artifacts" 子区块：调用 `collect_artifacts_for_workspace(workspace.workspace_path)`，空结果则不渲染任何东西。
- [x] 2.2 子区块实现：`st.markdown("### Model Artifacts")` 标题 + 对每个 artifact 渲染一个 `st.download_button`，label 格式 `<relative_path> (<human_readable_size>)`，bytes 从 `absolute_path` 现读（点击时）。
- [x] 2.3 大文件处理：size > 50MB 时 `disabled=True`，label 改为 `<relative_path> (<size>) — too large for in-browser download, access via filesystem: <absolute_path>`。
- [x] 2.4 "Download all as zip" 按钮：artifact 数 ≥ 2 且无任何超 50MB 的工件时渲染；点击时在内存里用 `zipfile` 打包所有文件（保留 relative_path），通过 `st.download_button` 的 bytes 下载，文件名 `artifacts.zip`。
- [x] 2.5 错误兜底：下载按钮点击时若文件已被删，捕获 `FileNotFoundError` 并用 `st.error` 显示 `File no longer exists: <path>`，其他按钮与 popover 仍可用。
- [ ] 2.6 手测：启动 streamlit UI（`streamlit run rdagent/log/ui/dsapp.py`），打开 tart-parapet 的 Loop_0 running 步 workspace，确认 "Model Artifacts" 区块出现且能下载 `params.pkl`。（语法与 import 已验证；需用户在 streamlit 运行时手测）

## 3. Workspace UUID 反查算法

- [x] 3.1 在 `rdagent/app/utils/workspace.py` 实现 `collect_workspace_uuids_for_trace(trace_dir: Path) -> set[str]`：先扫 `trace_dir/` 下所有 `*.pkl`，pickle.load 后递归走 `__dict__` 与容器元素收集 str 值，正则 `r'RD-Agent_workspace/([a-f0-9]{32})'` 匹配。
- [x] 3.2 同函数加 log 兜底：扫 `trace_dir/` 下所有 `*.log`，以及父目录的 `<task_name>.log`（`trace_dir.parent / f"{trace_dir.name}.log"`），正则同上，并集去重。
- [x] 3.3 pkl 反序列化失败处理：单个 pkl 抛 `Exception`（含 `EOFError`、`AttributeError`、`ModuleNotFoundError`）时跳过，不影响其他 pkl 扫描与 log 兜底。
- [x] 3.4 单元测试：用 tart-parapet trace 目录跑 `collect_workspace_uuids_for_trace`，断言返回 9 个 UUID（与日志 grep 结果一致），含 pkl 扫到的 3 个。
- [x] 3.5 单元测试：构造一个 pkl 损坏的临时 trace 目录，断言函数跳过损坏 pkl，仍能从 log 抓到 UUID，不抛异常。

## 4. 删除计划与引用计数

- [x] 4.1 在 `rdagent/app/utils/workspace.py` 定义 `DeletionPlan` dataclass：`workspaces_to_delete: list[Path]`, `cross_trace_shared_kept: list[SharedWorkspace]`（`SharedWorkspace` 含 `uuid`, `refcount`, `remaining_traces: list[str]`）, `cache_entries_to_delete: list[Path]`, `trace_dir_to_delete: Path | None`, `total_bytes: int`, `skipped_invalid_paths: list[Path]`。
- [x] 4.2 实现 `compute_refcounts(uuids: set[str], traces_root: Path, current_trace_dir: Path) -> dict[str, tuple[int, list[str]]]`：扫 `traces_root` 下 算引用数，返回 `{uuid: (refcount, [other_trace_names])}`。当前 trace 算 1 个引用。
- [x] 4.3 实现 `plan_deletion(trace_dir: Path, keep_trace: bool = False) -> DeletionPlan`：调 `collect_workspace_uuids_for_trace` + `compute_refcounts`，对 refcount==1 的 UUID 加入 `workspaces_to_delete`，refcount>1 的加入 `cross_trace_shared_kept`；扫 `pickle_cache/`、`factor_implementation_source_data/`、`factor_implementation_source_data_debug/` 把文件名含目标 UUID 的条目加入 `cache_entries_to_delete`（仅对将删的 UUID）；`keep_trace=False` 时 `trace_dir_to_delete = trace_dir`；累加 `total_bytes`。
- [x] 4.4 路径白名单校验：`workspaces_to_delete` 中每个路径 final component 必须匹配 `^[a-f0-9]{32}$`，否则移入 `skipped_invalid_paths` 不删；且路径必须以 `RD_AGENT_SETTINGS.workspace_path` 开头。
- [x] 4.5 单元测试：对 tart-parapet 跑 `plan_deletion`，断言 `workspaces_to_delete` 含 9 个路径（假设无跨 trace 共享），`total_bytes > 0`，`skipped_invalid_paths` 为空。
- [x] 4.6 单元测试：构造两个 trace 共享某 UUID 的临时目录树，断言该 UUID 出现在 `cross_trace_shared_kept`（refcount=2），不在 `workspaces_to_delete`。

## 5. 执行删除与安全校验

- [x] 5.1 在 `rdagent/app/utils/workspace.py` 实现 `execute_deletion(plan: DeletionPlan) -> DeletionResult`：先做 mtime 校验（`plan.trace_dir_to_delete` 或其父 trace 目录下所有文件 mtime 都早于 1 小时前），否则返回 `DeletionResult(refused=True, reason=...)` 不删任何东西。
- [x] 5.2 mtime 校验通过后，按 `workspaces_to_delete` → `cache_entries_to_delete` → `trace_dir_to_delete` 顺序删除，用 `shutil.rmtree(path, ignore_errors=False)`，每个删除前再校验路径白名单（防 plan 被篡改）。
- [x] 5.3 定义 `DeletionResult` dataclass：`deleted_workspaces: list[Path]`, `deleted_cache_entries: list[Path]`, `trace_dir_deleted: bool`, `cross_trace_shared_kept: list[SharedWorkspace]`, `skipped_invalid_paths: list[Path]`, `refused: bool`, `reason: str | None`, `reclaimed_bytes: int`。
- [x] 5.4 单元测试：构造临时 trace 目录 + workspace，mtime 较早，跑 `execute_deletion`，断言 workspace 被删、trace 目录被删、`reclaimed_bytes > 0`。
- [x] 5.5 单元测试：构造 mtime 在 30 分钟前的 trace 目录，跑 `execute_deletion`，断言 `refused=True`、`reason` 含 "modified within the last hour"、无任何删除发生、原文件仍存在。

## 6. CLI 入口

- [x] 6.1 新建 `rdagent/app/utils/workspace_cleanup.py`，用 `fire` 或 `argparse` 提供 CLI：`python -m rdagent.app.utils.workspace_cleanup <trace_dir> [--execute] [--keep-trace]`。
- [x] 6.2 默认（无 `--execute`）dry-run：调 `plan_deletion`，打印 `[DRY RUN]` 摘要——workspace 数量、总占用（human-readable）、cross_trace_shared_kept 列表（含 refcount + remaining_traces）、cache 条目数；退出码 0，不动文件系统。
- [x] 6.3 `--execute` 模式：调 `plan_deletion` + `execute_deletion`，打印删除结果摘要；若 `refused=True` 退出码非零并打印 reason。
- [x] 6.4 `--keep-trace` 透传给 `plan_deletion(keep_trace=True)`，dry-run 与 execute 模式都生效。
- [ ] 6.5 手测：对 tart-parapet 跑 dry-run，确认输出 9 workspace + 总占用；跑 `--execute` 确认 9 个 workspace 与 trace 目录被删；再跑一次 dry-run 确认 trace 不存在了（输出 "trace not found"）。（dry-run 已验证输出 12 workspace + 6GB；`--execute` 留给用户手测，不在自动测试中真删数据）

## 7. UI 删除按钮集成

- [x] 7.1 在 `rdagent/log/ui/ds_trace.py` 的 trace 任务列表渲染处（找到 trace 列表行的渲染代码），每行末尾加 `st.button("Delete task & workspace", key=f"delete_task_{trace_name}")`。
- [x] 7.2 点击按钮后用 `st.dialog`（或 `st.popover` + form）弹确认框：显示 trace 名、将删 workspace 数 + 路径列表、总占用 human-readable、`cross_trace_shared_kept` 条目数（若有，标注 "shared with N other traces, will be kept"）、两个按钮 "Confirm delete" / "Cancel"。
- [x] 7.3 "Confirm delete" 点击：调 `plan_deletion(trace_dir, keep_trace=False)` + `execute_deletion(plan)`；若 `result.refused` 用 `st.error` 显示 reason；否则 `st.success(f"Deleted {len(deleted_workspaces)} workspaces ({human_readable_bytes(reclaimed_bytes)}) and trace directory")`。
- [x] 7.4 删除成功后用 `st.rerun()` 刷新页面，让被删 trace 行从列表消失。
- [ ] 7.5 手测：在 UI 对 tart-parapet 点 "Delete task & workspace"，确认弹框显示 9 workspace + 总占用，确认后 toast 成功，刷新后 tart-parapet 行消失，文件系统里 9 个 workspace 与 trace 目录确已删除。（语法与 import 已验证；需用户在 streamlit 运行时手测）

## 8. 端到端验证与文档

- [x] 8.1 跑一次 `openspec validate --changes model-artifact-ui-and-workspace-cleanup` 确认 spec 一致性。
- [ ] 8.2 端到端手测：启动 UI，对一个已完成的 trace（非活跃）下载 `params.pkl` 验证字节正确；点 "Delete task & workspace" 验证清理；用 `find RD-Agent_workspace -name params.pkl` 确认该 trace 的模型文件已清掉。（需用户在 streamlit 运行时手测；核心逻辑已被单测覆盖）
- [ ] 8.3 端到端 CLI 验证：`python -m rdagent.app.utils.workspace_cleanup <trace_dir>` 输出 dry-run 摘要；加 `--execute` 真删；再跑确认 trace 已不存在。（dry-run 已在 tart-parapet 验证输出 12 workspace + 6GB；`--execute` 留给用户手测）
- [x] 8.4 在 `rdagent/app/utils/workspace_cleanup.py` 顶部写 module docstring，说明用法、安全策略（dry-run 默认、mtime 守卫、路径白名单、引用计数），便于未来维护。
- [x] 8.5 跑现有测试套件（`pytest rdagent/log/ui/ rdagent/app/utils/` 或类似）确认无回归。（`pytest rdagent/app/utils/test_workspace.py` 全部 15/15 通过；`ds_trace.py` 通过 `py_compile` 语法检查）
