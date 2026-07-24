## ADDED Requirements

### Requirement: Trace-to-workspace UUID reverse lookup
The system SHALL provide a function `collect_workspace_uuids_for_trace(trace_dir: Path) -> set[str]` that returns the set of 32-hex workspace UUIDs referenced by a given trace directory. The lookup SHALL combine two sources: (a) structured scan of all `*.pkl` files under `trace_dir/` by recursively walking each pickled object's `__dict__` and container elements, collecting string values matching `r'RD-Agent_workspace/([a-f0-9]{32})'`; (b) text grep of all `*.log` files under `trace_dir/` AND its parent directory's `<task_name>.log` file, matching the same regex. The two sources SHALL be unioned and deduplicated.

#### Scenario: Trace with both pkl-embedded and log-only paths
- **WHEN** `trace_dir` is `traces/Finance Whole Pipeline/tart-parapet/`, where pkls contain 3 unique workspace UUIDs and the `<task>.log` mentions 9 unique workspace UUIDs (with the 3 pkl ones as a subset)
- **THEN** `collect_workspace_uuids_for_trace` SHALL return a set of exactly 9 UUIDs.

#### Scenario: Trace with corrupted pkl
- **WHEN** one `*.pkl` under `trace_dir/` cannot be unpickled (e.g., class definition missing or file truncated)
- **THEN** the function SHALL skip that pkl, continue scanning the rest, and the result SHALL still include UUIDs found in other pkls and in logs. The function SHALL NOT raise.

#### Scenario: Trace with no log files
- **WHEN** `trace_dir/` contains only `*.pkl` files and no `*.log` files anywhere (including parent)
- **THEN** the function SHALL return only UUIDs found in pkls (source (a)); absence of logs SHALL NOT be an error.

### Requirement: Deletion plan preview (dry-run)
The system SHALL provide a `plan_deletion(trace_dir: Path, keep_trace: bool = False) -> DeletionPlan` that returns a structured plan WITHOUT performing any deletion. The plan SHALL include: list of workspace absolute paths to delete (each under `RD_AGENT_SETTINGS.workspace_path`), list of cache entries to delete (under `pickle_cache/`, `factor_implementation_source_data/`, `factor_implementation_source_data_debug/` whose filename contains a targeted UUID), total bytes to reclaim, and `cross_trace_shared_kept` (UUIDs referenced by other traces that will NOT be deleted, with their refcount and remaining referencing trace names).

#### Scenario: Dry-run on typical trace
- **WHEN** `plan_deletion` is called on `trace_dir = traces/Finance Whole Pipeline/tart-parapet/` with `keep_trace=False`
- **THEN** the returned plan SHALL list 9 workspace paths to delete and an empty `cross_trace_shared_kept` (assuming no other trace references the same UUIDs), and total bytes reflecting workspace + trace + cache sizes.

#### Scenario: Dry-run with shared workspace kept
- **WHEN** `plan_deletion` is called on a trace that references UUID `abc...` which is also referenced by trace `raw-elk`
- **THEN** the plan SHALL list `abc...`'s workspace in `cross_trace_shared_kept` with `refcount=2` and `remaining_traces=["raw-elk"]`, NOT in the to-delete list, and the to-delete list SHALL include only UUIDs where this trace is the sole referencer.

#### Scenario: keep_trace retains trace directory
- **WHEN** `plan_deletion` is called with `keep_trace=True`
- **THEN** the plan SHALL exclude `trace_dir` itself from deletion targets but still include all workspace paths (those whose last reference is the current trace) and cache entries; total bytes reflects only workspace + cache sizes.

### Requirement: Active-trace protection
The system SHALL refuse to execute a deletion plan whose `trace_dir` has been modified within the last 1 hour. Modification time SHALL be the maximum mtime across all files under `trace_dir/` (recursive). When refused, the system SHALL return an error message naming the trace and the most-recently-modified file's path and mtime, and SHALL NOT delete anything.

#### Scenario: Recently modified trace
- **WHEN** `trace_dir/` or any file under it has mtime within the last 3600 seconds and the user calls `execute_deletion`
- **THEN** the system SHALL return an error like "Trace <name> was modified <X> minutes ago; refusing to delete (pipeline may still be running). Most recent file: <path>", and no filesystem mutation SHALL occur.

#### Scenario: Stale trace safe to delete
- **WHEN** every file under `trace_dir/` has mtime older than 3600 seconds
- **THEN** `execute_deletion` SHALL proceed to delete the planned workspace paths and (if `keep_trace=False`) the trace directory.

### Requirement: Path whitelist enforcement
The system SHALL delete only paths matching `^[a-f0-9]{32}$` directly under `RD_AGENT_SETTINGS.workspace_path`. Any path in the deletion plan that does not match this pattern (even if produced by `collect_workspace_uuids_for_trace`) SHALL be skipped and recorded in `skipped_invalid_paths`. The system SHALL NOT delete paths outside `RD_AGENT_SETTINGS.workspace_path`.

#### Scenario: Valid UUID workspace path
- **WHEN** the deletion plan includes `RD-Agent_workspace/d5a0f6963b5a4c84bfd4835a142a38c7/`
- **THEN** `execute_deletion` SHALL delete that directory recursively (the directory name `d5a0f6963b5a4c84bfd4835a142a38c7` matches the 32-hex pattern).

#### Scenario: Malformed path in plan
- **WHEN** the deletion plan includes a path whose final component is not 32 hex chars (e.g., due to a regex bug or log noise like `RD-Agent_workspace/some_dir/`)
- **THEN** `execute_deletion` SHALL skip it, record it in `skipped_invalid_paths`, and continue deleting the valid paths.

### Requirement: Cross-trace sharing with reference counting
Before executing, the system SHALL scan all other trace directories under the same traces root and compute their referenced UUIDs (using the same `collect_workspace_uuids_for_trace` lookup). For each UUID in the current plan, the system SHALL compute a reference count = number of trace directories (including the current one) that reference it. The system SHALL delete a shared workspace ONLY when the current deletion removes its LAST remaining reference (i.e., the current trace is the only referencer); otherwise the workspace SHALL NOT be deleted and SHALL be recorded in `cross_trace_shared_kept` with its reference count and the list of remaining referencing traces.

The system SHALL NOT maintain a persistent reference counter file; counts SHALL be computed on-demand by scanning all trace directories at deletion time, so that trace directories added/removed between plan and execute are reflected.

#### Scenario: UUID shared with another trace (not last reference)
- **WHEN** workspace UUID `abc...` is referenced by both `traces/Finance Whole Pipeline/tart-parapet/` and `traces/Finance Whole Pipeline/raw-elk/`, and the user deletes tart-parapet
- **THEN** the system SHALL NOT delete workspace `abc...`, SHALL include it in `cross_trace_shared_kept` with `refcount=2` and `remaining_traces=["raw-elk"]`, and SHALL delete only tart-parapet's trace directory (if `keep_trace=False`) plus any UUIDs where tart-parapet is the sole referencer.

#### Scenario: UUID shared but current trace is last reference
- **WHEN** workspace UUID `abc...` was historically referenced by tart-parapet and raw-elk, but raw-elk has already been deleted earlier, so tart-parapet is now the only remaining trace referencing `abc...` (refcount computed at deletion time = 1)
- **THEN** the system SHALL delete workspace `abc...` along with the tart-parapet trace directory, because the current deletion removes its last reference.

#### Scenario: No shared UUIDs
- **WHEN** no UUID in the plan is referenced by any other trace directory (all refcounts = 1, current only)
- **THEN** all planned workspace paths SHALL be deleted normally, and `cross_trace_shared_kept` SHALL be empty.

### Requirement: CLI entrypoint
The system SHALL expose `python -m rdagent.app.utils.workspace_cleanup <trace_dir>` as a CLI. Default invocation (no `--execute`) SHALL print the dry-run plan and exit without modifying the filesystem. `--execute` SHALL run `execute_deletion`. `--keep-trace` SHALL set `keep_trace=True`. The CLI SHALL accept a relative or absolute `trace_dir` path.

#### Scenario: Default dry-run
- **WHEN** the user runs `python -m rdagent.app.utils.workspace_cleanup traces/Finance Whole Pipeline/tart-parapet`
- **THEN** the CLI SHALL print "[DRY RUN]" prefixed summary listing 9 workspace paths, total bytes, cross-trace-shared UUIDs (if any), and exit code 0, without deleting anything.

#### Scenario: Execute flag
- **WHEN** the user runs the CLI with `--execute` on a stale trace with no shared UUIDs
- **THEN** the CLI SHALL delete the 9 workspace directories and the trace directory, then print a summary of deleted paths and reclaimed bytes.

#### Scenario: Refused due to active trace
- **WHEN** the user runs with `--execute` on a trace modified within the last hour
- **THEN** the CLI SHALL print the active-trace error message and exit with non-zero code, without deleting anything.

### Requirement: UI delete button on trace task row
The Trace page SHALL render a "Delete task & workspace" button on each trace task row. Clicking it SHALL open a confirmation dialog showing: the trace name, the count and list of workspace paths to be deleted, total bytes to reclaim, count of cross-trace-shared UUIDs (if any, with a warning that those will be skipped), and two buttons "Confirm delete" / "Cancel".

#### Scenario: Confirm delete in UI
- **WHEN** the user clicks "Delete task & workspace" for tart-parapet, sees 9 workspace paths + total size in the dialog, and clicks "Confirm delete"
- **THEN** the UI SHALL call `execute_deletion` with the plan, then show a success toast "Deleted 9 workspaces (<X> MB) and trace directory", and the trace task row SHALL disappear from the list on next page render.

#### Scenario: Cancel in UI
- **WHEN** the user clicks "Delete task & workspace" then "Cancel"
- **THEN** no deletion SHALL occur and the dialog SHALL close.

#### Scenario: Active trace refused in UI
- **WHEN** the user clicks "Delete task & workspace" for a trace modified within the last hour and confirms
- **THEN** the UI SHALL show an error toast with the active-trace message and NOT delete anything.

### Requirement: Cache cleanup scoped by UUID
The system SHALL scan `pickle_cache/`, `factor_implementation_source_data/`, `factor_implementation_source_data_debug/` for files or directories whose name contains a targeted workspace UUID, and include them in the deletion plan. Entries whose names do not contain a targeted UUID SHALL NOT be deleted.

#### Scenario: Cache file named after UUID
- **WHEN** `pickle_cache/` contains a file `d5a0f6963b5a4c84bfd4835a142a38c7.cache` and that UUID is in the plan
- **THEN** the plan SHALL include that cache file for deletion.

#### Scenario: Class-named cache not deleted
- **WHEN** `pickle_cache/` contains `rdagent.scenarios.qlib.developer.factor_runner.QlibFactorRunner.develop/` (no UUID in name)
- **THEN** that entry SHALL NOT be in the deletion plan, even if it conceptually relates to the deleted trace (the system cannot safely attribute it).
