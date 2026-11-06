"""Read training progress from existing files; never write to the training directory."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_RECORDER = re.compile(r"Recorder ([0-9a-f]{32}) starts running under Experiment (\d+)")
_MAIN = re.compile(r"集成结果已写入实验 `([^`]+)` \(recorder ([0-9a-f]{32})\)")
_START = re.compile(r"训练窗口 (\d+)/(\d+)")
_DONE = re.compile(r"窗口 (\d+)/(\d+) 训练完成 \(run_id=([0-9a-f]{32})\)")
_TOTAL = re.compile(r"(?:滚动窗口共\s*(\d+)\s*个|预计\s*(\d+)\s*个窗口)")
_BACKTEST = re.compile(r"backtest loop:\s*\d+%.*?\|\s*(\d+)/(\d+)")
_TIME = re.compile(r"\((\d{4}-\d\d-\d\d \d\d:\d\d:\d\d[,\.]\d+)\)")
_PREFIX = "QRUN_RESULT "


def _strict_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def parse_terminal(line: str) -> dict:
    """Normalize the producer's stage field and the earlier failed_stage draft."""

    def reject_constant(value: str) -> None:
        raise ValueError(f"Invalid JSON constant: {value}")

    raw = json.loads(line[len(_PREFIX) :], object_pairs_hook=_strict_object, parse_constant=reject_constant)
    if not isinstance(raw, dict) or not {"status", "exit_code", "run_id"}.issubset(raw):
        raise ValueError("QRUN_RESULT must contain status, exit_code and run_id")
    status, code, rid = raw["status"], raw["exit_code"], raw["run_id"]
    if not isinstance(status, str) or status not in {"success", "failed", "interrupted"} or type(code) is not int:
        raise ValueError("Invalid terminal status or exit_code")
    if (status == "success") != (code == 0):
        raise ValueError("Terminal status disagrees with exit_code")
    if rid is not None and (not isinstance(rid, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", rid)):
        raise ValueError("Invalid run_id")
    if "stage" in raw:
        stage = raw["stage"]
        if not isinstance(stage, str) or not stage.strip():
            raise ValueError("stage must be a non-empty string")
    elif "failed_stage" in raw:
        stage = raw["failed_stage"]
        if status == "success" and stage is not None:
            raise ValueError("Successful terminal has failed_stage")
        if status != "success" and (not isinstance(stage, str) or not stage.strip()):
            raise ValueError("Failure requires a stage")
    else:
        raise ValueError("Terminal requires stage (or legacy failed_stage)")
    exp = raw.get("experiment_id")
    if exp is not None and (
        not isinstance(exp, (str, int)) or isinstance(exp, bool) or not re.fullmatch(r"[a-zA-Z0-9_-]+", str(exp))
    ):
        raise ValueError("Invalid experiment_id")
    return {
        **raw,
        "stage": stage,
        "failed_stage": stage if status != "success" else None,
        "experiment_id": str(exp) if exp is not None else None,
    }


@dataclass
class _LogState:
    identity: tuple[int, int]
    offset: int = 0
    pending: bytes = b""
    prefix: bytes = b""
    checkpoint: bytes = b""
    stage: str = "unknown"
    total: int | None = None
    completed: dict[str, int] = field(default_factory=dict)
    active: dict[int, str | None] = field(default_factory=dict)
    pid_windows: dict[str, int] = field(default_factory=dict)
    recorders: dict[str, str] = field(default_factory=dict)
    mains: dict[str, set[str]] = field(default_factory=dict)
    terminal: dict | None = None
    terminal_state: str = "missing"
    terminal_errors: list[str] = field(default_factory=list)
    observed_at: str | None = None
    latest_output: str | None = None
    backtest: dict | None = None


class ProgressReader:
    """Bounded incremental reads with disposable, process-local cursors."""

    def __init__(self, batch_bytes: int = 4 * 1024 * 1024) -> None:
        self.batch_bytes = batch_bytes
        self._states: dict[Path, _LogState] = {}
        self._lock = threading.RLock()

    def clear(self) -> None:
        with self._lock:
            self._states.clear()

    def read(self, path: Path) -> dict:
        with self._lock:
            return self._read(path)

    def _read(self, path: Path) -> dict:
        path = path.resolve()
        try:
            with path.open("rb") as stream:
                stat = path.stat()
                identity = (stat.st_dev, stat.st_ino)
                old = self._states.get(path)
                reset = old is None or old.identity != identity or stat.st_size < old.offset
                if old is not None and not reset:
                    reset = stream.read(len(old.prefix)) != old.prefix
                    stream.seek(max(0, old.offset - len(old.checkpoint)))
                    reset = reset or stream.read(len(old.checkpoint)) != old.checkpoint
                state = _LogState(identity) if reset else old
                assert state is not None
                if path not in self._states and len(self._states) >= 256:
                    self._states.pop(next(iter(self._states)))
                self._states[path] = state
                stream.seek(state.offset)
                chunk = stream.read(self.batch_bytes)
                state.offset += len(chunk)
                data = state.pending + chunk
                start = 0
                for match in re.finditer(rb"\r\n|\r|\n", data):
                    record = data[start : match.start()]
                    # A terminal is committed only after its final newline.
                    if record.startswith(_PREFIX.encode()) and match.group() == b"\r":
                        break
                    self._line(state, record.decode("utf-8", errors="replace"))
                    start = match.end()
                state.pending = data[start:]
                if len(state.pending) > 1024 * 1024:
                    state.pending = state.pending[-1024 * 1024 :]
                    self._error(state, "An overlong log record was truncated")
                stream.seek(0)
                state.prefix = stream.read(min(state.offset, 256))
                stream.seek(max(0, state.offset - 128))
                state.checkpoint = stream.read(min(state.offset, 128))
                return self._snapshot(state, stat)
        except (OSError, ValueError) as exc:
            return {
                "stage": "unknown",
                "completed_windows": 0,
                "total_windows": None,
                "active_windows": [],
                "terminal": None,
                "terminal_state": "missing",
                "errors": [str(exc)],
                "recorders": {},
                "main_candidates": {},
                "recovering": False,
            }

    @staticmethod
    def _error(state: _LogState, message: str) -> None:
        if message not in state.terminal_errors and len(state.terminal_errors) < 20:
            state.terminal_errors.append(message)

    def _line(self, state: _LogState, line: str) -> None:
        if line.startswith(_PREFIX):
            try:
                terminal = parse_terminal(line)
                if state.terminal is not None and state.terminal != terminal:
                    state.terminal_state = "conflict"
                    self._error(state, "Conflicting QRUN_RESULT records in the same log generation")
                elif state.terminal_state not in {"invalid", "conflict"}:
                    state.terminal = terminal
                    state.terminal_state = "valid"
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                state.terminal_state = "invalid"
                self._error(state, f"Invalid QRUN_RESULT: {exc}")
            return
        stamp = _TIME.search(line)
        if stamp:
            state.observed_at = stamp.group(1)
        pid = re.match(r"^\[(\d+):", line)
        start = _START.search(line)
        if start:
            index, total = map(int, start.groups())
            state.total, state.stage = total, "training"
            state.active[index] = None
            if pid:
                state.pid_windows[pid.group(1)] = index
        total_match = _TOTAL.search(line)
        if total_match:
            state.total = int(next(group for group in total_match.groups() if group is not None))
        recorder = _RECORDER.search(line)
        if recorder:
            rid, exp = recorder.groups()
            state.recorders[rid] = exp
            if pid and pid.group(1) in state.pid_windows:
                index = state.pid_windows[pid.group(1)]
                if index in state.active:
                    state.active[index] = rid
        done = _DONE.search(line)
        if done:
            index, total, rid = done.groups()
            state.total = int(total)
            state.completed[rid] = int(index)
            state.active.pop(int(index), None)
            state.stage = "merging" if len(state.completed) == state.total else "training"
        main = _MAIN.search(line)
        if main:
            name, rid = main.groups()
            state.mains.setdefault(name, set()).add(rid)
            state.stage = "result_written"
        backtest = _BACKTEST.search(line)
        if backtest:
            count, total = map(int, backtest.groups())
            state.backtest = {"completed": count, "total": total}
            state.stage = "backtesting"
        if "构建 handler 缓存" in line or "Loading data Done" in line:
            state.stage = "loading"
        if re.match(r"^\[\d+\]\s", line) or "Early stopping" in line:
            state.latest_output = line[:1000]

    @staticmethod
    def _snapshot(state: _LogState, stat: Any) -> dict:
        terminal = state.terminal if state.terminal_state == "valid" else None
        stage = state.stage
        if terminal:
            stage = "completed" if terminal["status"] == "success" else terminal["status"]
        return copy.deepcopy(
            {
                "stage": stage,
                "completed_windows": len(state.completed),
                "total_windows": state.total,
                "active_windows": [{"index": i, "run_id": rid} for i, rid in sorted(state.active.items())],
                "completed_run_ids": list(state.completed),
                "latest_training_output": state.latest_output,
                "backtest": state.backtest,
                "observed_at": state.observed_at,
                "log_updated_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                "terminal": terminal,
                "terminal_state": state.terminal_state,
                "errors": state.terminal_errors,
                "recorders": state.recorders,
                "main_candidates": {k: sorted(v) for k, v in state.mains.items()},
                "recovering": state.offset < stat.st_size,
                "offset": state.offset,
                "generation": hashlib.sha256(repr(state.identity).encode() + state.prefix).hexdigest()[:16],
            }
        )
