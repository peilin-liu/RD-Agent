"""CLI for workspace cleanup (capability: workspace-cleanup).

Usage:
    python -m rdagent.app.utils.workspace_cleanup <trace_dir> [--execute] [--keep-trace]

Default (no --execute): dry-run. Prints a [DRY RUN] summary of what would be
deleted and exits without touching the filesystem.

--execute: actually run plan_deletion + execute_deletion.

--keep-trace: keep the trace directory itself, only delete the associated
workspace directories and cache entries.

Safety:
- Active-trace protection: refuses to delete a trace whose files were modified
  within the last hour (pipeline may still be running).
- Path whitelist: only 32-hex-named directories directly under
  RD_AGENT_SETTINGS.workspace_path can be deleted.
- Reference counting: a workspace shared with other traces is kept until the
  current trace is its last referencer.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rdagent.app.utils.workspace import (
    DeletionPlan,
    execute_deletion,
    human_readable_bytes,
    plan_deletion,
)
from rdagent.log import rdagent_logger as logger


def _print_plan(plan: DeletionPlan, prefix: str = "[DRY RUN]") -> None:
    print(f"{prefix} - Workspace Cleanup Summary")
    print(f"  Workspaces to delete: {len(plan.workspaces_to_delete)}")
    for p in plan.workspaces_to_delete:
        print(f"    - {p}")
    print(f"  Cross-trace shared (kept): {len(plan.cross_trace_shared_kept)}")
    for s in plan.cross_trace_shared_kept:
        print(f"    - {s.uuid} (refcount={s.refcount}, also in: {', '.join(s.remaining_traces)})")
    print(f"  Cache entries to delete: {len(plan.cache_entries_to_delete)}")
    print(f"  Skipped invalid paths: {len(plan.skipped_invalid_paths)}")
    for p in plan.skipped_invalid_paths:
        print(f"    - {p}")
    print(f"  Trace dir to delete: {plan.trace_dir_to_delete}")
    print(f"  Total bytes to reclaim: {human_readable_bytes(plan.total_bytes)}")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m rdagent.app.utils.workspace_cleanup",
        description="Safely delete a trace task and its associated workspaces/cache.",
    )
    parser.add_argument("trace_dir", type=Path, help="Path to the trace directory to clean up.")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually perform deletion. Without this flag, only a dry-run summary is printed.",
    )
    parser.add_argument(
        "--keep-trace",
        action="store_true",
        help="Keep the trace directory itself; only delete associated workspaces and cache.",
    )
    args = parser.parse_args()

    trace_dir: Path = args.trace_dir
    if not trace_dir.exists():
        logger.error(f"Trace directory not found: {trace_dir}")
        return 2

    plan = plan_deletion(trace_dir, keep_trace=args.keep_trace)

    if not args.execute:
        _print_plan(plan, prefix="[DRY RUN]")
        print()
        print("Run with --execute to actually delete.")
        return 0

    _print_plan(plan, prefix="[EXECUTE]")
    result = execute_deletion(plan)
    print()
    print(f"[RESULT] - Deletion Result")
    print(f"  Refused: {result.refused}")
    if result.refused:
        print(f"  Reason: {result.reason}")
        return 1
    print(f"  Deleted workspaces: {len(result.deleted_workspaces)}")
    print(f"  Deleted cache entries: {len(result.deleted_cache_entries)}")
    print(f"  Trace dir deleted: {result.trace_dir_deleted}")
    print(f"  Cross-trace shared kept: {len(result.cross_trace_shared_kept)}")
    print(f"  Skipped invalid paths: {len(result.skipped_invalid_paths)}")
    print(f"  Reclaimed bytes: {human_readable_bytes(result.reclaimed_bytes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
