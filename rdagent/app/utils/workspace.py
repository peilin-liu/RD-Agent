"""Workspace artifact enumeration, trace-to-workspace reverse lookup, and safe deletion.

Public API:
- collect_artifacts_for_workspace(ws_path) -> list[ArtifactInfo]
- collect_workspace_uuids_for_trace(trace_dir) -> set[str]
- plan_deletion(trace_dir, keep_trace=False) -> DeletionPlan
- execute_deletion(plan) -> DeletionResult

Safety policy:
- Deletion is dry-run by default; callers must pass execute_deletion explicitly.
- Active-trace protection: refuse to delete if any file under trace_dir was modified within the last hour. only delete 32-hex-named directories directly under RD_AGENT_SETTINGS.workspace_path.
- Reference counting: a workspace shared with other traces is kept until the current trace is its last referencer.
"""
from __future__ import annotations

import pickle
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from rdagent.core.conf import RD_AGENT_SETTINGS

# Per-file download size cap for UI artifact download buttons.
WORKSPACE_ARTIFACT_SIZE_LIMIT = 50 * 1024 * 1024

# Active-trace protection threshold.
ACTIVE_TRACE_THRESHOLD = timedelta(hours=1)

# Regex for 32-hex workspace UUID as it appears in paths.
_WORKSPACE_UUID_RE = re.compile(r"RD-Agent_workspace/([a-f0-9]{32})")
_UUID_NAME_RE = re.compile(r"^[a-f0-9]{32}$")


@dataclass
class ArtifactInfo:
    relative_path: str
    absolute_path: Path
    size_bytes: int


@dataclass
class SharedWorkspace:
    uuid: str
    refcount: int
    remaining_traces: list[str]


@dataclass
class DeletionPlan:
    workspaces_to_delete: list[Path] = field(default_factory=list)
    cross_trace_shared_kept: list[SharedWorkspace] = field(default_factory=list)
    cache_entries_to_delete: list[Path] = field(default_factory=list)
    trace_dir_to_delete: Path | None = None
    total_bytes: int = 0
    skipped_invalid_paths: list[Path] = field(default_factory=list)


@dataclass
class DeletionResult:
    deleted_workspaces: list[Path] = field(default_factory=list)
    deleted_cache_entries: list[Path] = field(default_factory=list)
    trace_dir_deleted: bool = False
    cross_trace_shared_kept: list[SharedWorkspace] = field(default_factory=list)
    skipped_invalid_paths: list[Path] = field(default_factory=list)
    refused: bool = False
    reason: str | None = None
    reclaimed_bytes: int = 0


# ----------------------------------------------------------------------------
# Artifact enumeration (capability: model-artifact-presentation)
# ----------------------------------------------------------------------------


def collect_artifacts_for_workspace(ws_path: Path) -> list[ArtifactInfo]:
    """Return all mlruns artifact files under <ws_path>/mlruns/<exp>/<rec>/artifacts/.

    Aggregates across multiple experiments/recorders. relative_path is prefixed
    with <exp>/<rec>/ so the user can tell which loop produced which file.
    Returns [] when ws_path has no mlruns/ subdirectory (not an error).
    """
    mlruns_dir = ws_path / "mlruns"
    if not mlruns_dir.exists() or not mlruns_dir.is_dir():
        return []

    out: list[ArtifactInfo] = []
    for exp_dir in sorted(p for p in mlruns_dir.iterdir() if p.is_dir() and p.name != ".trash"):
        for rec_dir in sorted(p for p in exp_dir.iterdir() if p.is_dir()):
            artifacts_dir = rec_dir / "artifacts"
            if not artifacts_dir.exists():
                continue
            for f in sorted(artifacts_dir.rglob("*")):
                if not f.is_file() or f.is_symlink():
                    continue
                rel = f.relative_to(artifacts_dir)
                out.append(
                    ArtifactInfo(
                        relative_path=f"{exp_dir.name}/{rec_dir.name}/{rel.as_posix()}",
                        absolute_path=f,
                        size_bytes=f.stat().st_size,
                    )
                )
    return out


# ----------------------------------------------------------------------------
# Trace-to-workspace reverse lookup (capability: workspace-cleanup)
# ----------------------------------------------------------------------------


def _walk_strings(obj: Any) -> Iterable[str]:
    """Yield every str value reachable from obj via __dict__ and container elements."""
    seen: set[int] = set()
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, str):
            yield cur
            continue
        oid = id(cur)
        if oid in seen:
            continue
        seen.add(oid)
        if isinstance(cur, dict):
            stack.extend(cur.keys())
            stack.extend(cur.values())
        elif isinstance(cur, (list, tuple, set, frozenset)):
            stack.extend(cur)
        elif hasattr(cur, "__dict__"):
            stack.extend(vars(cur).values())


def _scan_pkls_for_uuids(trace_dir: Path) -> set[str]:
    uuids: set[str] = set()
    for pkl in trace_dir.rglob("*.pkl"):
        try:
            with pkl.open("rb") as fh:
                obj = pickle.load(fh)
        except Exception:
            continue
        for s in _walk_strings(obj):
            uuids.update(m.group(1) for m in _WORKSPACE_UUID_RE.finditer(s))
    return uuids


def _scan_logs_for_uuids(trace_dir: Path) -> set[str]:
    uuids: set[str] = set()
    log_paths = list(trace_dir.rglob("*.log"))
    parent_log = trace_dir.parent / f"{trace_dir.name}.log"
    if parent_log.exists():
        log_paths.append(parent_log)
    for log in log_paths:
        try:
            text = log.read_text(errors="ignore")
        except Exception:
            continue
        uuids.update(m.group(1) for m in _WORKSPACE_UUID_RE.finditer(text))
    return uuids


def collect_workspace_uuids_for_trace(trace_dir: Path) -> set[str]:
    """Union of UUIDs found in trace pkls (structured) and trace logs (grep fallback)."""
    return _scan_pkls_for_uuids(trace_dir) | _scan_logs_for_uuids(trace_dir)


# ----------------------------------------------------------------------------
# Reference counting and deletion planning
# ----------------------------------------------------------------------------


def _iter_trace_dirs(traces_root: Path) -> list[Path]:
    """Yield immediate child directories of traces_root (one per trace task)."""
    if not traces_root.exists():
        return []
    return [p for p in traces_root.iterdir() if p.is_dir()]


def compute_refcounts(
    uuids: set[str], traces_root: Path, current_trace_dir: Path
) -> dict[str, tuple[int, list[str]]]:
    """For each uuid in `uuids`, return (refcount, [other_trace_names]).

    refcount counts the current trace plus every other trace under traces_root
    that references the uuid. other_trace_names excludes the current trace.
    """
    result: dict[str, tuple[int, list[str]]] = {u: (1, []) for u in uuids}
    for other in _iter_trace_dirs(traces_root):
        if other.resolve() == current_trace_dir.resolve():
            continue
        other_uuids = collect_workspace_uuids_for_trace(other)
        shared = uuids & other_uuids
        for u in shared:
            cnt, names = result[u]
            result[u] = (cnt + 1, names + [other.name])
    return result


def _collect_cache_entries(uuids: set[str]) -> list[Path]:
    """Return cache files whose filename contains any of the targeted UUIDs.

    Scans pickle_cache/, factor_implementation_source_data/,
    factor_implementation_source_data_debug/ under RD_AGENT_SETTINGS.workspace_path.parent
    (i.e., git_ignore_folder/). Class-named caches without a UUID are NOT matched.
    """
    cache_dirs = [
        RD_AGENT_SETTINGS.workspace_path.parent / "pickle_cache",
        RD_AGENT_SETTINGS.workspace_path.parent / "factor_implementation_source_data",
        RD_AGENT_SETTINGS.workspace_path.parent / "factor_implementation_source_data_debug",
    ]
    out: list[Path] = []
    for cache_dir in cache_dirs:
        if not cache_dir.exists():
            continue
        for f in cache_dir.rglob("*"):
            if f.is_file() and any(u in f.name for u in uuids):
                out.append(f)
    return out


def _dir_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for f in path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total


def plan_deletion(trace_dir: Path, keep_trace: bool = False) -> DeletionPlan:
    """Build a DeletionPlan without performing any deletion."""
    plan = DeletionPlan()
    if not trace_dir.exists():
        plan.trace_dir_to_delete = None
        return plan

    uuids = collect_workspace_uuids_for_trace(trace_dir)
    traces_root = trace_dir.parent
    refcounts = compute_refcounts(uuids, traces_root, trace_dir)

    ws_root = RD_AGENT_SETTINGS.workspace_path
    for u, (cnt, others) in refcounts.items():
        ws_path = ws_root / u
        if not ws_path.exists() or not _UUID_NAME_RE.match(u):
            plan.skipped_invalid_paths.append(ws_path)
            continue
        if cnt > 1:
            plan.cross_trace_shared_kept.append(
                SharedWorkspace(uuid=u, refcount=cnt, remaining_traces=others)
            )
            continue
        plan.workspaces_to_delete.append(ws_path)
        plan.total_bytes += _dir_size(ws_path)

    plan.cache_entries_to_delete = _collect_cache_entries(
        {ws.name for ws in plan.workspaces_to_delete}
    )
    plan.total_bytes += sum(f.stat().st_size for f in plan.cache_entries_to_delete)

    if not keep_trace:
        plan.trace_dir_to_delete = trace_dir
        plan.total_bytes += _dir_size(trace_dir)

    return plan


# ----------------------------------------------------------------------------
# Execution with safety guards
# ----------------------------------------------------------------------------


def _max_mtime(path: Path) -> datetime | None:
    """Return the most recent mtime among all files under path (recursive)."""
    latest: datetime | None = None
    for f in path.rglob("*"):
        if f.is_file():
            try:
                mt = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
            if latest is None or mt > latest:
                latest = mt
    return latest


def _is_active(path: Path, now: datetime | None = None) -> tuple[bool, Path | None, datetime | None]:
    """Return (is_active, most_recent_file, its_mtime)."""
    if now is None:
        now = datetime.now(timezone.utc)
    latest_file: Path | None = None
    latest_mt: datetime | None = None
    for f in path.rglob("*"):
        if f.is_file():
            try:
                mt = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
            if latest_mt is None or mt > latest_mt:
                latest_mt = mt
                latest_file = f
    if latest_mt is None:
        return False, None, None
    return (now - latest_mt) < ACTIVE_TRACE_THRESHOLD, latest_file, latest_mt


def _is_valid_workspace_path(path: Path) -> bool:
    """Validate path is directly under workspace_path with 32-hex final component."""
    try:
        rel = path.relative_to(RD_AGENT_SETTINGS.workspace_path)
    except ValueError:
        return False
    if len(rel.parts) != 1:
        return False
    return bool(_UUID_NAME_RE.match(rel.parts[0]))


def execute_deletion(plan: DeletionPlan) -> DeletionResult:
    """Execute a DeletionPlan with safety guards. Refuses active traces."""
    result = DeletionResult(cross_trace_shared_kept=list(plan.cross_trace_shared_kept))

    if plan.trace_dir_to_delete is not None:
        is_active, recent_file, recent_mt = _is_active(plan.trace_dir_to_delete)
        if is_active:
            result.refused = True
            result.reason = (
                f"Trace {plan.trace_dir_to_delete.name} was modified within the last hour; "
                f"refusing to delete (pipeline may still be running). "
                f"Most recent file: {recent_file} (mtime {recent_mt.isoformat() if recent_mt else 'n/a'})"
            )
            return result

    for ws in plan.workspaces_to_delete:
        if not _is_valid_workspace_path(ws):
            result.skipped_invalid_paths.append(ws)
            continue
        try:
            size = _dir_size(ws)
            shutil.rmtree(ws)
            result.deleted_workspaces.append(ws)
            result.reclaimed_bytes += size
        except OSError:
            result.skipped_invalid_paths.append(ws)

    for cache in plan.cache_entries_to_delete:
        try:
            size = cache.stat().st_size
            cache.unlink()
            result.deleted_cache_entries.append(cache)
            result.reclaimed_bytes += size
        except OSError:
            result.skipped_invalid_paths.append(cache)

    if plan.trace_dir_to_delete is not None:
        try:
            result.reclaimed_bytes += _dir_size(plan.trace_dir_to_delete)
            shutil.rmtree(plan.trace_dir_to_delete)
            result.trace_dir_deleted = True
        except OSError:
            pass

    return result


def human_readable_bytes(n: int) -> str:
    """Return a human-readable byte string like '18 KB' or '676 KB' (decimal units)."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return f"{n} {unit}" if unit == "B" else f"{n} {unit}"
        n = round(n / 1000)  # type: ignore[assignment]
    return f"{n} TB"
