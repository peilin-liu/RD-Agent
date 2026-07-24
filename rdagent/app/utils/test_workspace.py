"""Tests for rdagent.app.utils.workspace (model-artifact-ui-and-workspace-cleanup change).

Run: pytest rdagent/app/utils/test_workspace.py -v
"""
from __future__ import annotations

import os
import pickle
import shutil
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from rdagent.app.utils import workspace as ws_mod
from rdagent.app.utils.workspace import (
    ArtifactInfo,
    DeletionPlan,
    SharedWorkspace,
    collect_artifacts_for_workspace,
    collect_workspace_uuids_for_trace,
    compute_refcounts,
    execute_deletion,
    human_readable_bytes,
    plan_deletion,
)


# ---------------------------------------------------------------------------
# Fixtures pointing at the real tart-parapet run on this machine.
# These tests are skipped when the data is absent (e.g., CI on other hosts).
# ---------------------------------------------------------------------------

QUANTS_ROOT = Path("/data/projects/quants/git_ignore_folder")
TART_PARAPET_TRACE = QUANTS_ROOT / "traces" / "Finance Whole Pipeline" / "tart-parapet"
TART_PARAPET_WORKSPACE = QUANTS_ROOT / "RD-Agent_workspace" / "d5a0f6963b5a4c84bfd4835a142a38c7"
TART_PARAPET_MIN_EXPECTED_UUID_COUNT = 9  # log grep alone finds 9; pkl scan may find more

pytestmark = pytest.mark.skipif(
    not TART_PARAPET_TRACE.exists(),
    reason="tart-parapet trace data not present on this host",
)


# --------------------------- Task 1.3 --------------------------------------


def test_collect_artifacts_for_tart_parapet_workspace():
    """Spec: Workspace with successful run artifacts."""
    artifacts = collect_artifacts_for_workspace(TART_PARAPET_WORKSPACE)
    names = {a.relative_path for a in artifacts}
    # params.pkl, pred.pkl, label.pkl all live under <exp>/<rec>/artifacts/
    assert any(a.relative_path.endswith("/params.pkl") for a in artifacts), names
    assert any(a.relative_path.endswith("/pred.pkl") for a in artifacts), names
    assert any(a.relative_path.endswith("/label.pkl") for a in artifacts), names
    assert any(
        a.relative_path.endswith("/portfolio_analysis/report_normal_1day.pkl")
        for a in artifacts
    ), names
    # size_bytes matches filesystem
    for a in artifacts:
        assert a.size_bytes == a.absolute_path.stat().st_size
        assert a.absolute_path.is_file()


# --------------------------- Task 1.4 --------------------------------------


def test_collect_artifacts_for_workspace_without_mlruns(tmp_path):
    """Spec: Workspace without mlruns returns empty list, no exception."""
    ws = tmp_path / "fake_ws_no_mlruns"
    ws.mkdir()
    (ws / "factor.py").write_text("# no mlruns here")
    assert collect_artifacts_for_workspace(ws) == []


def test_collect_artifacts_aggregates_multiple_experiments(tmp_path):
    """Spec: Workspace with multiple experiments under mlruns."""
    ws = tmp_path / "multi_exp_ws"
    arts_a = ws / "mlruns" / "exp_A" / "rec_A" / "artifacts"
    arts_b = ws / "mlruns" / "exp_B" / "rec_B" / "artifacts"
    arts_a.mkdir(parents=True)
    arts_b.mkdir(parents=True)
    (arts_a / "params.pkl").write_bytes(b"a")
    (arts_b / "params.pkl").write_bytes(b"b")
    out = collect_artifacts_for_workspace(ws)
    prefixes = {a.relative_path.split("/")[0] for a in out}
    assert prefixes == {"exp_A", "exp_B"}


# --------------------------- Task 3.4 --------------------------------------


def test_collect_workspace_uuids_for_tart_parapet():
    """Spec: Trace with both pkl-embedded and log-only paths.

    The pkl scan is more thorough than log grep; the union returns at least
    the 9 UUIDs that log grep alone surfaces, and may include extras found
    only in structured pkl fields.
    """
    uuids = collect_workspace_uuids_for_trace(TART_PARAPET_TRACE)
    assert len(uuids) >= TART_PARAPET_MIN_EXPECTED_UUID_COUNT
    # pkl scan alone should have found at least 3
    pkl_only = ws_mod._scan_pkls_for_uuids(TART_PARAPET_TRACE)
    assert len(pkl_only) >= 3
    assert pkl_only.issubset(uuids)


# --------------------------- Task 3.5 --------------------------------------


def test_collect_uuids_skips_corrupted_pkl(tmp_path):
    """Spec: Trace with corrupted pkl."""
    trace = tmp_path / "mytrace"
    trace.mkdir()
    # corrupted pkl
    (trace / "broken.pkl").write_bytes(b"\x80\x05garbage")
    # log with a uuid
    (trace / "mytrace.log").write_text(
        "evolving workspace: /path/RD-Agent_workspace/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    )
    uuids = collect_workspace_uuids_for_trace(trace)
    assert "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" in uuids


def test_collect_uuids_no_logs(tmp_path):
    """Spec: Trace with no log files."""
    trace = tmp_path / "nolog"
    trace.mkdir()
    # pkl that embeds a workspace path (32 b's)
    obj = {"workspace_path": "/x/RD-Agent_workspace/" + "b" * 32}
    with (trace / "data.pkl").open("wb") as f:
        pickle.dump(obj, f)
    uuids = collect_workspace_uuids_for_trace(trace)
    assert uuids == {"b" * 32}


# --------------------------- Task 4.5 / 4.6 --------------------------------


def _setup_fake_env(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Build a fake traces_root + workspace_root + one trace referencing 3 UUIDs.

    Caller is expected to patch RD_AGENT_SETTINGS.workspace_path to ws_root.
    """
    ws_root = tmp_path / "RD-Agent_workspace"
    ws_root.mkdir()
    traces_root = tmp_path / "traces" / "Finance Whole Pipeline"
    traces_root.mkdir(parents=True)
    trace = traces_root / "tart-parapet"
    trace.mkdir()
    # create 3 workspaces
    for u in ("11111111111111111111111111111111",
              "22222222222222222222222222222222",
              "33333333333333333333333333333333"):
        (ws_root / u).mkdir()
        (ws_root / u / "factor.py").write_text("# fake")
    # pkl embedding 3 uuids
    with (trace / "data.pkl").open("wb") as f:
        pickle.dump(
            {"paths": [
                f"/x/RD-Agent_workspace/11111111111111111111111111111111",
                f"/x/RD-Agent_workspace/22222222222222222222222222222222",
                f"/x/RD-Agent_workspace/33333333333333333333333333333333",
            ]},
            f,
        )
    return traces_root, ws_root, trace


def test_plan_deletion_no_shared(tmp_path):
    """Spec: Dry-run on typical trace, no shared UUIDs."""
    traces_root, ws_root, trace = _setup_fake_env(tmp_path)
    with patch.object(ws_mod.RD_AGENT_SETTINGS, "workspace_path", ws_root):
        plan = plan_deletion(trace, keep_trace=False)
    assert len(plan.workspaces_to_delete) == 3
    assert plan.cross_trace_shared_kept == []
    assert plan.skipped_invalid_paths == []
    assert plan.trace_dir_to_delete == trace
    assert plan.total_bytes > 0


def test_plan_deletion_shared_kept(tmp_path):
    """Spec: UUID shared with another trace is kept, not deleted."""
    traces_root, ws_root, trace = _setup_fake_env(tmp_path)
    # Create another trace that references UUID "111..."
    other_trace = traces_root / "raw-elk"
    other_trace.mkdir()
    with (other_trace / "data.pkl").open("wb") as f:
        pickle.dump({"p": "/x/RD-Agent_workspace/11111111111111111111111111111111"}, f)
    with patch.object(ws_mod.RD_AGENT_SETTINGS, "workspace_path", ws_root):
        plan = plan_deletion(trace, keep_trace=False)
    # UUID "111..." should be in cross_trace_shared_kept
    kept_uuids = {s.uuid for s in plan.cross_trace_shared_kept}
    assert "11111111111111111111111111111111" in kept_uuids
    # And NOT in workspaces_to_delete
    delete_uuids = {p.name for p in plan.workspaces_to_delete}
    assert "11111111111111111111111111111111" not in delete_uuids
    # The other 2 should still be deleted
    assert len(plan.workspaces_to_delete) == 2


def test_plan_deletion_keep_trace(tmp_path):
    """Spec: keep_trace retains trace directory."""
    traces_root, ws_root, trace = _setup_fake_env(tmp_path)
    with patch.object(ws_mod.RD_AGENT_SETTINGS, "workspace_path", ws_root):
        plan = plan_deletion(trace, keep_trace=True)
    assert plan.trace_dir_to_delete is None
    assert len(plan.workspaces_to_delete) == 3


def test_plan_deletion_last_reference_still_deletes(tmp_path):
    """Spec: UUID shared but current trace is last reference → still deleted."""
    traces_root, ws_root, trace = _setup_fake_env(tmp_path)
    # raw-elk trace that referenced "111..." but raw-elk is now GONE
    # (simulate by NOT creating raw-elk). The plan should still delete "111..."
    with patch.object(ws_mod.RD_AGENT_SETTINGS, "workspace_path", ws_root):
        plan = plan_deletion(trace, keep_trace=False)
    delete_uuids = {p.name for p in plan.workspaces_to_delete}
    assert "11111111111111111111111111111111" in delete_uuids
    assert plan.cross_trace_shared_kept == []


# --------------------------- Task 5.4 / 5.5 --------------------------------


def _make_old(path: Path) -> None:
    """Set mtime to 2 hours ago."""
    two_hrs_ago = (datetime.now(timezone.utc) - timedelta(hours=2)).timestamp()
    for f in path.rglob("*"):
        if f.is_file():
            os.utime(f, (two_hrs_ago, two_hrs_ago))


def _make_recent(path: Path) -> None:
    """Set mtime to 5 minutes ago."""
    five_min_ago = (datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp()
    for f in path.rglob("*"):
        if f.is_file():
            os.utime(f, (five_min_ago, five_min_ago))


def test_execute_deletion_stale_trace(tmp_path):
    """Spec: Stale trace safe to delete."""
    traces_root, ws_root, trace = _setup_fake_env(tmp_path)
    _make_old(trace)
    with patch.object(ws_mod.RD_AGENT_SETTINGS, "workspace_path", ws_root):
        plan = plan_deletion(trace, keep_trace=False)
        result = execute_deletion(plan)
    assert result.refused is False
    assert len(result.deleted_workspaces) == 3
    assert result.trace_dir_deleted is True
    assert result.reclaimed_bytes > 0
    assert not trace.exists()
    for u in ("11111111111111111111111111111111",
              "22222222222222222222222222222222",
              "33333333333333333333333333333333"):
        assert not (ws_root / u).exists()


def test_execute_deletion_refuses_active_trace(tmp_path):
    """Spec: Recently modified trace → refused, nothing deleted."""
    traces_root, ws_root, trace = _setup_fake_env(tmp_path)
    _make_recent(trace)
    with patch.object(ws_mod.RD_AGENT_SETTINGS, "workspace_path", ws_root):
        plan = plan_deletion(trace, keep_trace=False)
        result = execute_deletion(plan)
    assert result.refused is True
    assert result.reason is not None
    assert "within the last hour" in result.reason
    assert result.deleted_workspaces == []
    assert result.trace_dir_deleted is False
    # Everything still on disk
    assert trace.exists()
    for u in ("11111111111111111111111111111111",
              "22222222222222222222222222222222",
              "33333333333333333333333333333333"):
        assert (ws_root / u).exists()


def test_execute_deletion_skips_invalid_paths(tmp_path):
    """Spec: malformed path in plan → skipped, valid ones still deleted."""
    traces_root, ws_root, trace = _setup_fake_env(tmp_path)
    _make_old(trace)
    with patch.object(ws_mod.RD_AGENT_SETTINGS, "workspace_path", ws_root):
        plan = plan_deletion(trace, keep_trace=False)
        # Inject a malformed path
        plan.workspaces_to_delete.append(ws_root / "not-a-uuid")
        result = execute_deletion(plan)
    assert ws_root / "not-a-uuid" in result.skipped_invalid_paths
    # 3 valid ones still deleted
    assert len(result.deleted_workspaces) == 3


def test_plan_deletion_on_real_tart_parapet():
    """Integration: plan_deletion on real tart-parapet produces sane plan.

    Patches RD_AGENT_SETTINGS.workspace_path to the real quants workspace root
    (the deployment under /data/projects/quants/), since the default
    Path.cwd()/git_ignore_folder/RD-Agent_workspace is only correct when the
    process was originally launched from /data/projects/quants.
    """
    real_ws_root = QUANTS_ROOT / "RD-Agent_workspace"
    with patch.object(ws_mod.RD_AGENT_SETTINGS, "workspace_path", real_ws_root):
        plan = plan_deletion(TART_PARAPET_TRACE, keep_trace=False)
        # Should propose to delete at least 9 workspaces (more if pkl scan found extras)
        assert len(plan.workspaces_to_delete) + len(plan.cross_trace_shared_kept) >= 9
        # workspaces_to_delete entries are valid UUIDs under workspace_path
        from rdagent.app.utils.workspace import _is_valid_workspace_path
        for p in plan.workspaces_to_delete:
            assert _is_valid_workspace_path(p), p
    assert plan.total_bytes > 0
    assert plan.trace_dir_to_delete == TART_PARAPET_TRACE


# --------------------------- Minor helpers --------------------------------


def test_human_readable_bytes():
    assert human_readable_bytes(18432) == "18 KB"
    assert human_readable_bytes(0) == "0 B"
    assert human_readable_bytes(50 * 1024 * 1024).endswith("MB")
