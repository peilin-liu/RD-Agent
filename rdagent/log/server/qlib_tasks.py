"""A fixed train entrypoint with task records in RD-Agent's existing trace storage.

The producer owns its logs. This supervisor drains output but does not create a
second training log or write control files into train_data_dir.
"""

from __future__ import annotations

import fcntl
import json
import math
import os
import re
import selectors
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

TRAIN_SCRIPT = Path(__file__).resolve().parents[3].parent / "qlib/tools/qrun/train_run.py"


def log_identity(folder: str | Path | None) -> list | None:
    if not folder:
        return None
    try:
        logs = [Path(folder) / name for name in ("rolling.log", "qrun.log") if (Path(folder) / name).is_file()]
        if not logs:
            return None
        log = max(logs, key=lambda p: p.stat().st_mtime_ns)
        stat = log.stat()
        return [str(log.resolve()), stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_size]
    except OSError:
        return None


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, ensure_ascii=False, allow_nan=False)
        stream.flush()
    temporary.replace(path)


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def process_identity(pid: int) -> str | None:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] == "Z":
            return None
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        return f"{boot}:{fields[19]}"
    except (OSError, IndexError):
        return None


def build_arguments(overrides: list, data_dir: Path) -> tuple[list[str], dict]:
    if not isinstance(overrides, list) or len(overrides) > 300:
        raise ValueError("overrides must be a list of at most 300 parameter rows")
    arguments, values = [], {}
    for row in overrides:
        if not isinstance(row, dict) or set(row) - {"name", "value", "kind", "enabled"}:
            raise ValueError("Each parameter row contains name, value, kind and enabled only")
        if type(row.get("enabled", True)) is not bool:
            raise ValueError("Parameter enabled must be boolean")
        if not row.get("enabled", True):
            continue
        name = str(row.get("name", "")).removeprefix("--")
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", name):
            raise ValueError("Invalid parameter name; enter an option, not a command")
        kind = row.get("kind", "value")
        if kind == "flag":
            arguments.append(f"--{name}")
            values[name] = True
        elif kind == "value":
            value = row.get("value")
            if type(value) not in {str, int, float} or isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"{name} requires a string or finite number; use flag for a switch")
            arguments.append(f"--{name}={value}")
            values[name] = str(value)
        else:
            raise ValueError("Parameter kind must be value or flag")
    if "out-dir" not in values:
        arguments.insert(0, f"--out-dir={data_dir}")
        values["out-dir"] = str(data_dir)
    return arguments, values


class TaskManager:
    def __init__(self, store: Path, data_dir: Path) -> None:
        self.store, self.data_dir = store.resolve(), data_dir.resolve()
        self._children = []

    def preview(self, body: dict) -> dict:
        if not isinstance(body, dict) or set(body) - {"overrides"}:
            raise ValueError("Only parameter overrides are accepted; the train entrypoint is fixed")
        args, values = build_arguments(body.get("overrides", []), self.data_dir)
        root = Path(str(values["out-dir"])).expanduser()
        if not root.is_absolute():
            root = TRAIN_SCRIPT.parents[2] / root
        output = None
        name = values.get("rolling-exp-name")
        if isinstance(name, str) and name:
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("rolling-exp-name must be relative to out-dir")
            output = str((root / relative).resolve())
        return {
            "argv": [sys.executable, str(TRAIN_SCRIPT), *args],
            "output_dir": output,
            "overrides": body.get("overrides", []),
            "entrypoint": str(TRAIN_SCRIPT),
        }

    def _folder(self, task_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", task_id):
            raise ValueError("Invalid task ID")
        folder = self.store / task_id
        if not (folder / "request.json").is_file():
            raise FileNotFoundError("Task not found")
        return folder

    def get(self, task_id: str) -> dict:
        folder = self._folder(task_id)
        request, runtime = _read(folder / "request.json"), _read(folder / "runtime.json")
        result = {**request, **runtime}
        if result.get("state") in {"pending", "running", "stopping"}:
            pid, identity = result.get("worker_pid"), result.get("worker_identity")
            if pid and identity and process_identity(pid) != identity:
                result["state"] = "interrupted"
            elif not pid and time.time() - result.get("created_timestamp", time.time()) > 60:
                result["state"] = "interrupted"
        return result

    def list(self) -> list[dict]:
        self._children = [p for p in self._children if p.poll() is None]
        if not self.store.is_dir():
            return []
        return sorted(
            [
                self.get(p.name)
                for p in self.store.iterdir()
                if re.fullmatch(r"[a-f0-9]{32}", p.name) and (p / "request.json").is_file()
            ],
            key=lambda row: row.get("created_timestamp", 0),
            reverse=True,
        )

    def output_dirs(self) -> list[str]:
        return [row["output_dir"] for row in self.list() if row.get("output_dir")]

    def create(self, body: dict) -> dict:
        preview = self.preview(body)
        if not TRAIN_SCRIPT.is_file():
            raise ValueError(f"The fixed train entrypoint is not installed: {TRAIN_SCRIPT}")
        self.store.mkdir(parents=True, exist_ok=True)
        with (self.store / ".launch.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if any(row.get("state") in {"pending", "running", "stopping"} for row in self.list()):
                raise RuntimeError("A training task is already running")
            task_id = uuid.uuid4().hex
            folder = self.store / task_id
            request = {
                **preview,
                "id": task_id,
                "created_timestamp": time.time(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            _write(folder / "request.json", request)
            _write(folder / "runtime.json", {"state": "pending"})
            try:
                worker = subprocess.Popen(
                    [sys.executable, "-m", __name__, str(folder)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                    cwd=str(Path(__file__).resolve().parents[3]),
                )
                self._children.append(worker)
            except OSError as exc:
                _write(folder / "runtime.json", {"state": "failed", "exit_code": None, "error": str(exc)})
                raise
        return self.get(task_id)

    def stop(self, task_id: str) -> dict:
        task = self.get(task_id)
        if task.get("state") not in {"pending", "running", "stopping"}:
            raise ValueError("Task is not running or its process identity cannot be verified")
        (self._folder(task_id) / "cancel").touch()
        return {"id": task_id, "state": "stopping"}


def supervise(folder: Path) -> None:
    request = _read(folder / "request.json")
    runtime = {
        "state": "running",
        "worker_pid": os.getpid(),
        "worker_identity": process_identity(os.getpid()),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "output_dir": request.get("output_dir"),
    }
    _write(folder / "runtime.json", runtime)
    child = None
    tail, partial, stopping = b"", b"", None
    try:
        child = subprocess.Popen(
            request["argv"],
            cwd=str(TRAIN_SCRIPT.parents[2]),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            bufsize=0,
        )
        runtime.update(child_pid=child.pid, child_identity=process_identity(child.pid), child_pgid=child.pid)
        _write(folder / "runtime.json", runtime)
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            while child.poll() is None or selector.get_map():
                if (folder / "cancel").exists() and stopping is None:
                    stopping = time.monotonic()
                    runtime["state"] = "stopping"
                    _write(folder / "runtime.json", runtime)
                    try:
                        os.killpg(child.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                if stopping is not None and time.monotonic() - stopping > 10:
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                for key, _ in selector.select(timeout=0.25):
                    data = os.read(key.fd, 65536)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    # Retain only a bounded failure diagnostic, not another training log.
                    tail = (tail + data)[-16384:]
                    records = (partial + data).split(b"\n")
                    partial = records.pop()[-16384:]
                    for raw in records:
                        line = raw.decode("utf-8", errors="replace")
                        match = re.search(r"\[info\]\s*输出目录:\s*(.+)", line)
                        if match:
                            runtime["output_dir"] = str(Path(match.group(1).strip()).expanduser().resolve())
                            runtime["output_observed"] = True
                            _write(folder / "runtime.json", runtime)
        code = child.wait()
        runtime.update(
            state="cancelled" if stopping is not None else "succeeded" if code == 0 else "failed",
            exit_code=code,
            ended_at=datetime.now(timezone.utc).isoformat(),
        )
        if code:
            runtime["error"] = tail.decode("utf-8", errors="replace")
    except Exception as exc:
        runtime.update(state="failed", error=str(exc), exit_code=child.poll() if child else None)
        if child and child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGTERM)
                child.wait(timeout=10)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
    finally:
        if runtime.get("output_observed"):
            runtime["log_identity"] = log_identity(runtime.get("output_dir"))
        _write(folder / "runtime.json", runtime)


if __name__ == "__main__":
    supervise(Path(sys.argv[1]).resolve())
