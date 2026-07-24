## Context

RD-Agent 是 spec-driven 的 R&D agent，quant 场景下每个 loop 在 `RD_AGENT_SETTINGS.workspace_path / uuid.uuid4().hex` 路径生成工作区（`rdagent/core/experiment.py:167`），因子 workspace 产出 `factor.py` / `result.h5` / `daily_pv.h5`，实验 workspace 产出 `qrun` 跑出来的 `mlruns/<exp>/<rec>/artifacts/*.pkl`。当前现状：

- `workspace.file_dict` 只存 `.py`/`.md` 字符串源码（`experiment.py:164`），模型工件是二进制 pkl，不进 `file_dict`，所以 UI 的 `workspace_win`（`ds_trace.py:199`）展示不出来。
- `RD-Agent_workspace/` 已实测累积 538 个 uuid 目录（单次 whole pipeline 多 loop 即可产生数十 GB），无清理入口，用户既删不掉也无法判断哪些可删。
- Trace 任务（如 `Finance Whole Pipeline/tart-parapet`）能反向关联到 workspace：trace pkl 结构化字段抓到 3 个 uuid，trace `.log` 文本 grep 补到 9 个，并集完整覆盖该任务真实占用的所有 workspace 目录。这是新清理方案的数据基础。

约束：
- UI 用 streamlit，已有 `st.download_button` / `st.popover` 组件可直接复用。
- 清理是破坏性操作，必须 dry-run + 显式确认 + 防 trace 活跃时被误删。
- 不能破坏现有 trace pkl 与 workspace 目录结构（向后兼容）。

## Goals / Non-Goals

**Goals:**
- 让用户在 UI Trace 页 Files popover 内一键下载与该 workspace 关联的 mlruns 模型工件（`params.pkl` / `pred.pkl` / `label.pkl` 等）。
- 让用户能从 UI 直接删一个 trace 任务及其全部关联 workspace + 孤儿缓存，无需手工 `find` + `rm`。
- 提供与 UI 等价的 CLI（`python -m rdagent.app.utils.workspace_cleanup`），便于脚本化 / cron。
- 反查算法稳健：结构化扫 pkl 优先，log grep 兜底，并集去重。
- 清理操作默认 dry-run，`--execute` 才真删；UI 删除前二次确认。

**Non-Goals:**
- 不做 mlruns 工件的在线推理 / 模型注册（那是 qlib MLflow tracker 的事，超出 RD-Agent 范畴）。
- 不做按时间/大小自动 GC 的定时任务（用户按需触发即可，避免后台进程误删活跃 workspace）。
- 不修改 `workspace.file_dict` 数据结构（保持向后兼容，工件展示走独立扫描路径）。
- 不动 trace pkl 的序列化格式（只读不写）。
- 不做跨 trace 的 workspace 归属冲突仲裁（一个 workspace 只信其首次被扫到的 trace；实测未发现跨任务共享 workspace 的情况，因每次 loop 都新分配 uuid）。

## Decisions

### D1. 模型工件展示位置：在 `workspace_win` Files popover 内追加 "Model Artifacts" 子区

**选择**：在现有 Files popover（`ds_trace.py:199-243`）末尾追加一个 "Model Artifacts" 子区块，仅当该 workspace 路径下存在 `mlruns/*/artifacts/` 时渲染。

**理由**：
- 用户已在 Files popover 找代码，工件放同处上下文连贯。
- `workspace_win` 已有 `workspace.workspace_path`，无需新参数。
- 不破坏现有 `.py`/`.md` 展示逻辑。

**备选**：独立 "Artifacts" 页 → 多一次跳转，且 workspace 与工件分离展示，用户难对应。已否。

### D2. 工件展示形态：路径树 + 逐文件 `st.download_button`

**选择**：扫描 `workspace_path/mlruns/<exp>/<rec>/artifacts/`，展平成 `(relative_path, abs_path, size)` 列表，每个文件一个下载按钮，文件名带 size 标注（如 `params.pkl (18 KB)`）。`portfolio_analysis/`、`sig_analysis/` 子目录的 pkl 也展平展示。

**理由**：
- streamlit `st.download_button` 需 bytes，pkl 文件体积小（实测最大 9MB `indicators_normal_1day_obj.pkl`），内存可接受。
- 展平比嵌套树简单，UI 渲染快。
- 路径前缀保留（`portfolio_analysis/report_normal_1day.pkl`）让用户知道文件归属。

**备选**：打包成 zip 一次下载 → 多数情况用户只想拿 `params.pkl`，强制打包反而重。已否。但提供 "Download all as zip" 二级按钮作为可选项。

### D3. Workspace 反查算法：pkl 结构化扫描 + log grep 兜底，并集去重

**选择**：实现 `collect_workspace_uuids_for_trace(trace_dir: Path) -> set[str]`：

```
1. pkl 扫描：递归遍历 trace_dir 下所有 *.pkl
   - pickle.load 每个 pkl
   - 递归走对象 __dict__ / 容器元素，收集所有 str 值
   - 正则匹配 r'RD-Agent_workspace/([a-f0-9]{32})'
2. log grep 兜底：扫 trace_dir 下所有 *.log（包括父目录的 <task>.log）
   - re.findall(r'RD-Agent_workspace/([a-f0-9]{32})', text)
3. 并集去重
```

**理由**：
- pkl 结构化优先：能抓到嵌套对象（如 `Experiment.workspace_path`）。
- log 兜底：覆盖 pkl 未保存中间状态的情况（如 `evolving workspace: File Factor[...]: /path` 这类 INFO 日志）。
- 实测 tart-parapet：pkl 抓 3 + log 抓 9 → 并集 9，完整覆盖。
- 不引入 qlib MLflow API（避免依赖 qlib 运行时）。

**备选**：只扫 pkl → 漏 6 个因子 workspace（pkl 里没存它们的路径）。已否。
**备选**：只 grep log → 受日志格式变化影响大。已否。

### D4. 清理入口：UI 在 trace 任务列表行 + CLI `python -m rdagent.app.utils.workspace_cleanup <trace_dir>`

**选择**：
- UI：Trace 页任务列表每行末尾加 "Delete task & workspace" 按钮，点击 → 弹窗显示将删的 workspace 路径列表 + 总占用 + trace 目录本身 → 二次确认 → 执行。
- CLI：`python -m rdagent.app.utils.workspace_cleanup <trace_dir> [--execute] [--keep-trace]`，默认 dry-run 输出摘要，`--execute` 真删，`--keep-trace` 只删 workspace 保留 trace 目录。

**理由**：
- UI 按 trace 任务为单位最符合用户心智（"删这个任务" = "删它的一切"）。
- CLI 与 UI 共用同一 `collect_workspace_uuids_for_trace` + `delete_workspaces` 实现，单一真源。
- `--keep-trace` 给"只想回收磁盘但保留 trace 日志"的场景留口子。

**备选**：UI 独立 "Workspace Cleanup" 页 → 用户要回去对照 trace 名判断哪些可删，心智负担大。已否，并入 trace 列表行。

### D5. 安全校验：活跃 trace 保护 + dry-run 默认 + 路径白名单 + 引用计数

**选择**：
- 删除前校验 trace 目录 mtime：若 1 小时内被修改过（说明 pipeline 还在跑），拒绝删除并提示。
- 默认 dry-run，输出 `[DRY RUN]` 前缀摘要；`--execute` 才真删。
- workspace 路径白名单：只删 `RD_AGENT_SETTINGS.workspace_path` 下的 uuid 形态目录（正则 `^[a-f0-9]{32}$`），避免误删非 workspace 子目录。
- 缓存清理（`pickle_cache/`、`factor_implementation_source_data[_debug]/`）：只删文件名包含该 trace 的 workspace uuid 的缓存条目，不删整个目录。
- **跨 trace 共享用引用计数**：删除前扫所有 trace 目录，对每个 UUID 计算引用数（多少 trace 引用它）。当前 trace 是某 UUID 的**最后一个引用者**时才删该 workspace，否则保留并记录在 `cross_trace_shared_kept`（含 refcount + 剩余 trace 名）。引用计数**不持久化**，每次删除时即时计算，保证 trace 增减都被反映。

**理由**：
- mtime 校验防 pipeline 运行中被删（OOM 也算异常终止，但 mtime 不会太近）。
- 路径白名单是兜底防线，即使 uuid 反查算法出 bug 也不会越界删。
- 缓存按 uuid 精准清理，不波及其他 trace 的缓存。
- 引用计数解决"共享 workspace 何时该删"——简单共享不删会让 workspace 永远清不掉（用户删 raw-elk 后 tart-parapet 引的 workspace 成了孤儿）。即时计算而非持久化计数器，避免计数漂移（trace 目录直接被用户手工 rm 时计数器不会更新）。

### D6. 共享逻辑的代码组织：新增 `rdagent/app/utils/workspace.py` 作为单一真源

**选择**：新增 `rdagent/app/utils/workspace.py`，包含：
- `collect_workspace_uuids_for_trace(trace_dir: Path) -> set[str]`
- `collect_artifacts_for_workspace(ws_path: Path) -> list[ArtifactInfo]`
- `plan_deletion(trace_dir: Path, keep_trace: bool) -> DeletionPlan`（含 `cross_trace_shared_kept` 与即时引用计数结果）
- `execute_deletion(plan: DeletionPlan) -> DeletionResult`（按引用计数决策删/保留）

UI（`ds_trace.py`）与 CLI（`rdagent/app/utils/workspace_cleanup.py`）都调它。

**理由**：
- 单一真源，UI 与 CLI 行为一致。
- 与 `rdagent/app/utils/` 现有 `info.py` / `ws.py` / `ape.py` 风格一致。

## Risks / Trade-offs

- **pkl 反序列化失败** → 某个 pkl 损坏或类找不到时跳过，记入 `unparseable_pkls` 列表，dry-run 摘要里展示，不阻塞清理。log grep 兜底覆盖。
- **log grep 漏抓** → 若未来 log 格式变化（uuid 不再出现在 log 里），反查不完整。缓解：同时维护 pkl 扫描为主路径；dry-run 摘要展示"已找到 N 个 workspace"，用户可肉眼核对数量是否合理。
- **跨 trace 共享 workspace** → 实测未发现（每 loop 新分配 uuid），但理论上若未来代码复用 workspace，反查会让一个 workspace 同时被多 trace 引用。**缓解（引用计数）**：删除时即时计算每个 UUID 的引用数，仅当当前 trace 是最后引用者时才删该 workspace，否则保留并记 `cross_trace_shared_kept`。这避免简单共享"永不删"导致的孤儿 workspace 累积。引用数不持久化，每次删除即时扫所有 trace 计算，保证 trace 目录手工增减都被反映。
- **streamlit 大 pkl 下载占内存** → `indicators_normal_1day_obj.pkl` 实测 9MB，可接受；若未来 qlib 产出更大工件，改为 chunk 流式下载或 zip 打包。
- **UI 误删活跃 trace** → mtime 校验 + 二次确认 + dry-run 默认三重防线。最坏情况用户点错，dry-run 摘要会让他看到将删什么。
- **缓存清理误伤** → `pickle_cache/` 文件名不含 workspace uuid 的情况（如 `QlibFactorRunner.develop/` 这类按类名命名的缓存），无法精准关联，这类缓存**不删**，仅删文件名包含 uuid 的条目。trade-off：留下少量孤儿缓存，换安全性。

## Migration Plan

- 纯新增能力，无数据迁移。旧 trace / 旧 workspace 立即可用新 UI 与 CLI。
- 部署：`git pull` + 重启 streamlit UI 即可。CLI 直接 `python -m rdagent.app.utils.workspace_cleanup`。
- 回滚：删除新增文件，恢复 `ds_trace.py` 的 `workspace_win` 即可。无数据库 / 配置变更。

## Open Questions

- Q1: workspace 工件下载是否需要权限控制？当前 RD-Agent UI 是单用户本地 streamlit，默认无鉴权。假设本地信任，不引入鉴权。若未来多用户部署需补。
- Q2: 是否需要在 Summary 页加"磁盘占用概览"看板（按 trace 汇总 workspace 总大小）？这超出当前两个 capability 范围，留作后续 change。
- Q3: 删除 trace 后是否要留"墓碑"记录（已删的 trace 名 + 删除时间）便于追溯？当前设计不写墓碑，删除即彻底。若需审计，后续 change 加 `deletion_log.jsonl`。
