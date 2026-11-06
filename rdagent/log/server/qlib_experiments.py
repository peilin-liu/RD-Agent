"""Read-only discovery of train outputs and their explicitly referenced artifacts."""

from __future__ import annotations

import hashlib
import math
import os
import threading
from collections import deque
from pathlib import Path
from urllib.parse import unquote, urlparse

import pandas as pd
import yaml

from rdagent.log.server.qlib_progress import ProgressReader
from rdagent.log.ui.qlib_metrics import portfolio_metrics, return_chart_content

CONFIG_NAMES = ("rolling_workflow_config.yaml", "workflow_config.yaml")
LOG_NAMES = ("rolling.log", "qrun.log")


def train_data_directory() -> Path:
    from rdagent.core.region_config import _load_config
    from rdagent.log.ui.conf import UI_SETTING

    configured = os.environ.get("UI_TRAIN_DATA_DIR") or _load_config().get("train_data_dir")
    value = configured if configured is not None else UI_SETTING.train_data_dir
    if not isinstance(value, str) or not value.strip():
        raise ValueError("train_data_dir must be a non-empty directory path")
    return Path(value).expanduser().resolve()


def json_safe(value):
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return str(value)


def local_path(uri: str, relative_to: Path) -> Path:
    parsed = urlparse(str(uri))
    if parsed.scheme not in {"", "file"} or parsed.netloc not in {"", "localhost"}:
        raise ValueError("Only explicitly referenced local file URIs are supported")
    path = Path(unquote(parsed.path)).expanduser()
    return (path if path.is_absolute() else relative_to / path).resolve()


def within(root: Path, *parts: str) -> Path:
    result = root.joinpath(*parts).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError("Path escapes its registered source")
    return result


def read_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        result = yaml.safe_load(stream)
    if not isinstance(result, dict):
        raise ValueError(f"Expected a mapping in {path.name}")
    return result


def nested(mapping: dict, *keys):
    value = mapping
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def metric_points(path: Path):
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            # An unfinished trailing write must not become a metric sample.
            if not line.endswith("\n"):
                continue
            parts = line.split()
            if len(parts) not in {2, 3, 5}:
                continue
            try:
                stamp, value = int(parts[0]), float(parts[1])
                step = int(parts[2]) if len(parts) == 3 else 0
                yield {"step": step, "timestamp": stamp, "value": value if math.isfinite(value) else None}
            except ValueError:
                continue


def read_metrics(run_dir: Path) -> dict:
    result = {}
    folder = run_dir / "metrics"
    if not folder.is_dir():
        return result
    for file in folder.rglob("*"):
        if not file.is_file() or file.is_symlink() or not file.resolve().is_relative_to(folder.resolve()):
            continue
        try:
            latest = max(
                metric_points(file),
                key=lambda p: (p["step"], p["timestamp"], p["value"] if p["value"] is not None else float("-inf")),
            )
            result[file.relative_to(folder).as_posix()] = latest["value"]
        except (ValueError, OSError):
            continue
    return result


def artifact_roots(run_dir: Path, meta: dict) -> list[Path]:
    roots = []
    if meta.get("artifact_uri"):
        roots.append(local_path(meta["artifact_uri"], run_dir))
    default = (run_dir / "artifacts").resolve()
    if default not in roots:
        roots.append(default)
    return roots


def artifact_file(roots: list[Path], name: str) -> Path | None:
    for root in roots:
        candidate = within(root, name)
        if candidate.is_file():
            return candidate
    return None


class ExperimentReader:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.progress = ProgressReader()
        self._report_cache = {}
        self._lock = threading.RLock()

    def sources(self, extra_dirs=()) -> dict[str, Path]:
        candidates = [self.root]
        if self.root.is_dir():
            candidates.extend(p for p in sorted(self.root.iterdir()) if p.is_dir() and not p.is_symlink())
        # Only explicitly registered task output locations may be outside the discovery root.
        candidates.extend(Path(p).resolve() for p in extra_dirs if p)
        result = {}
        for folder in candidates:
            if folder.name.startswith("."):
                continue
            if any((folder / name).is_file() for name in (*CONFIG_NAMES, *LOG_NAMES)):
                key = hashlib.sha256(str(folder).encode()).hexdigest()[:24]
                result[key] = folder
        return result

    def resolve(self, source_id: str, extra_dirs=()) -> Path:
        source = self.sources(extra_dirs).get(source_id)
        if source is None:
            raise FileNotFoundError("Training output directory not found")
        return source

    @staticmethod
    def log_file(folder: Path) -> Path | None:
        existing = [folder / name for name in LOG_NAMES if (folder / name).is_file()]
        return max(existing, key=lambda p: p.stat().st_mtime_ns) if existing else None

    def summary(self, source_id: str, folder: Path) -> tuple[dict, dict]:
        errors = []
        log = self.log_file(folder)
        config_name = "workflow_config.yaml" if log and log.name == "qrun.log" else "rolling_workflow_config.yaml"
        config_path = folder / config_name
        if not config_path.exists():
            config_path = next((folder / n for n in CONFIG_NAMES if (folder / n).exists()), config_path)
        try:
            config = read_yaml(config_path)
        except (ValueError, OSError, yaml.YAMLError) as exc:
            config = {}
            errors.append(f"Configuration: {exc}")
        progress = (
            self.progress.read(log)
            if log
            else {
                "stage": "unknown",
                "completed_windows": 0,
                "total_windows": None,
                "active_windows": [],
                "terminal": None,
                "terminal_state": "missing",
                "errors": [],
                "recorders": {},
                "main_candidates": {},
            }
        )
        errors.extend(progress.get("errors", []))
        terminal = progress.get("terminal")
        uri = nested(config, "qlib_init", "exp_manager", "kwargs", "uri")
        state, run_id, exp_id, run_dir, roots = "pending", None, None, None, []
        metadata, name, expected_name = {}, folder.name, None
        if terminal and terminal.get("run_id"):
            run_id = terminal["run_id"]
            exp_id = terminal.get("experiment_id") or progress["recorders"].get(run_id)
            names = [name for name, ids in progress.get("main_candidates", {}).items() if run_id in ids]
            if len(names) == 1:
                expected_name = names[0]
        elif progress.get("terminal_state") not in {"invalid", "conflict"}:
            mains = progress.get("main_candidates", {})
            candidates = [(n, rid) for n, ids in mains.items() for rid in ids]
            if len(candidates) == 1:
                name, run_id = candidates[0]
                expected_name = name
                exp_id = progress["recorders"].get(run_id)
            elif len(candidates) > 1:
                state = "ambiguous"
                errors.append("Multiple main runs in this output; no run was selected")
        else:
            state = "error"
        if run_id and exp_id and uri:
            try:
                store = local_path(uri, folder)
                run_dir = within(store, str(exp_id), run_id)
                metadata = read_yaml(run_dir / "meta.yaml")
                exp_meta = read_yaml(within(store, str(exp_id), "meta.yaml"))
                if str(metadata.get("run_id", metadata.get("run_uuid"))) != run_id:
                    raise ValueError("Run metadata disagrees with the reported run_id")
                if str(metadata.get("experiment_id")) != str(exp_id):
                    raise ValueError("Run metadata disagrees with experiment_id")
                if expected_name is not None and exp_meta.get("name") != expected_name:
                    raise ValueError("Experiment name disagrees with the completion record")
                name = str(exp_meta.get("name", name))
                roots = artifact_roots(run_dir, metadata)
                state = "partial"
            except (OSError, ValueError, yaml.YAMLError) as exc:
                errors.append(f"Result association: {exc}")
                run_dir, roots, state = None, [], "missing"
        elif terminal or run_id:
            state = "missing" if state != "ambiguous" else state
            errors.append("A complete result URI and exact experiment/run identity are not available yet")
        report = artifact_file(roots, "portfolio_analysis/report_normal_1day.pkl")
        visible_files = [config_path]
        for relative_name in (
            "portfolio_analysis/report_normal_1day.pkl",
            "portfolio_analysis/positions_normal_1day.pkl",
            "portfolio_analysis/indicators_normal_1day.pkl",
            "rolling_manifest.yaml",
            "resolved_config.yaml",
        ):
            file = artifact_file(roots, relative_name)
            if file:
                visible_files.append(file)
        artifact_revision = [(str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in visible_files if p.is_file()]
        metric_revision = (
            sorted(
                (str(p.relative_to(run_dir)), p.stat().st_mtime_ns, p.stat().st_size)
                for p in (run_dir / "metrics").rglob("*")
                if p.is_file()
            )
            if run_dir
            else []
        )
        revision = hashlib.sha256(
            repr((uri, run_id, exp_id, artifact_revision, metric_revision, terminal)).encode()
        ).hexdigest()
        execution = {"success": "succeeded", "failed": "failed", "interrupted": "interrupted"}.get(
            terminal.get("status") if terminal else None, "unknown"
        )
        public = {
            "id": source_id,
            "name": name,
            "output_dir": str(folder),
            "source_uri": uri,
            "experiment_id": str(exp_id) if exp_id is not None else None,
            "run_id": run_id,
            "management_mode": "external",
            "execution_state": execution,
            "result_state": state,
            "progress": {key: value for key, value in progress.items() if key not in {"recorders", "main_candidates"}},
            "terminal": terminal,
            "errors": errors,
            "result_revision": revision,
            "market": config.get("market"),
            "benchmark": config.get("benchmark"),
        }
        context = {
            "folder": folder,
            "config": config,
            "log": log,
            "run_dir": run_dir,
            "roots": roots,
            "metadata": metadata,
            "progress": progress,
            "report": report,
        }
        return public, context

    def list(self, extra_dirs=()) -> list[dict]:
        result = []
        for key, folder in self.sources(extra_dirs).items():
            try:
                public, _ = self.summary(key, folder)
                result.append(public)
            except (OSError, ValueError, yaml.YAMLError) as exc:
                result.append(
                    {
                        "id": key,
                        "name": folder.name,
                        "output_dir": str(folder),
                        "execution_state": "unknown",
                        "result_state": "error",
                        "errors": [str(exc)],
                        "progress": {"stage": "unknown"},
                    }
                )
        return result

    def _portfolio(self, report_path: Path, roots: list[Path]) -> tuple[dict, dict, list[str]]:
        optional_files = [
            artifact_file(roots, f"portfolio_analysis/{name}")
            for name in ("indicators_normal_1day.pkl", "positions_normal_1day.pkl")
        ]
        signature = (
            str(report_path),
            report_path.stat().st_mtime_ns,
            report_path.stat().st_size,
            *((str(p), p.stat().st_mtime_ns, p.stat().st_size) if p else None for p in optional_files),
        )
        with self._lock:
            cached = self._report_cache.get(signature)
            if cached is not None:
                return cached
        warnings = []
        report = pd.read_pickle(report_path)
        if not isinstance(report, pd.DataFrame) or report.empty:
            raise ValueError("Backtest report is not a non-empty dataframe")
        metrics = portfolio_metrics(report=report)
        for name, argument in [
            ("indicators_normal_1day.pkl", "indicators"),
            ("positions_normal_1day.pkl", "positions"),
        ]:
            file = artifact_file(roots, f"portfolio_analysis/{name}")
            if file:
                try:
                    metrics.update(portfolio_metrics(**{argument: pd.read_pickle(file)}))
                except Exception as exc:
                    warnings.append(f"Optional {name}: {exc}")
        chart = return_chart_content(report, include_plotlyjs="/api/qlib-script/plotly.js")
        value = (metrics, chart, warnings)
        with self._lock:
            if len(self._report_cache) >= 8:
                self._report_cache.pop(next(iter(self._report_cache)))
            self._report_cache[signature] = value
        return value

    def detail(self, source_id: str, extra_dirs=()) -> dict:
        folder = self.resolve(source_id, extra_dirs)
        result, context = self.summary(source_id, folder)
        metrics, chart, windows = {}, None, []
        run_dir, roots = context["run_dir"], context["roots"]
        if run_dir:
            metrics = read_metrics(run_dir)
            has_core_metrics = bool(metrics)
            if context["report"]:
                try:
                    derived, chart, warnings = self._portfolio(context["report"], roots)
                    metrics.update(derived)
                    result["errors"].extend(warnings)
                    result["result_state"] = "ready" if has_core_metrics else "partial"
                except Exception as exc:
                    result["errors"].append(f"Backtest report: {exc}")
            manifest = artifact_file(roots, "rolling_manifest.yaml")
            if manifest:
                try:
                    data = read_yaml(manifest)
                    entries = data.get("windows") or []
                    if not isinstance(entries, list):
                        raise ValueError("Window manifest windows must be a list")
                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue
                        rid = entry.get("prediction_run_id") or entry.get("run_id")
                        exp = context["progress"]["recorders"].get(rid)
                        windows.append(
                            {
                                "key": entry.get("key"),
                                "run_id": entry.get("run_id"),
                                "prediction_run_id": rid,
                                "experiment_id": exp,
                                "segments": entry.get("segments"),
                                "active": entry.get("key") == data.get("active_window"),
                                "source": "manifest",
                                "run_dir": entry.get("run_dir"),
                            }
                        )
                except (ValueError, OSError, yaml.YAMLError) as exc:
                    result["errors"].append(f"Window manifest: {exc}")
        config = context["config"]
        resolved = artifact_file(roots, "resolved_config.yaml")
        if resolved:
            try:
                config = read_yaml(resolved)
            except (OSError, ValueError, yaml.YAMLError) as exc:
                result["errors"].append(f"Resolved configuration: {exc}")
        result.update(
            metrics=metrics,
            windows=windows,
            artifacts=self.artifacts(source_id, extra_dirs),
            view={
                "sourceType": "qlib-script",
                "name": result["name"],
                "executionState": result["execution_state"],
                "feedbackCharts": chart,
                "feedbackConfig": {
                    "config": "```yaml\n"
                    + yaml.safe_dump(json_safe(config), allow_unicode=True, sort_keys=False)
                    + "```"
                },
                "rawMetrics": metrics,
                "researchHypothesis": None,
                "feedbackHypothesis": None,
            },
        )
        return json_safe(result)

    def artifacts(self, source_id: str, extra_dirs=()) -> list[dict]:
        folder = self.resolve(source_id, extra_dirs)
        _, context = self.summary(source_id, folder)
        files = {}
        for root in context["roots"]:
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root):
                    relative = path.relative_to(root).as_posix()
                    size = path.stat().st_size
                    files.setdefault(
                        relative,
                        {
                            "relative_path": relative,
                            "size_bytes": size,
                            "size_human": f"{size / 1024:.1f} KB",
                            "absolute_path": str(path),
                        },
                    )
        return list(files.values())

    def download(self, source_id: str, name: str, extra_dirs=()) -> Path:
        folder = self.resolve(source_id, extra_dirs)
        if name in (*CONFIG_NAMES, *LOG_NAMES) and (folder / name).is_file():
            return within(folder, name)
        _, context = self.summary(source_id, folder)
        path = artifact_file(context["roots"], name)
        if path is None:
            raise FileNotFoundError("Artifact no longer exists")
        return path

    def history(self, source_id: str, run_id: str, extra_dirs=()) -> dict:
        folder = self.resolve(source_id, extra_dirs)
        _, context = self.summary(source_id, folder)
        exp = context["progress"]["recorders"].get(run_id)
        if not exp or not context["run_dir"]:
            return {"series": {}}
        store = context["run_dir"].parent.parent
        metrics = within(store, exp, run_id, "metrics")
        series = {}
        if metrics.is_dir():
            for file in metrics.rglob("*"):
                if file.is_file() and not file.is_symlink() and file.resolve().is_relative_to(metrics.resolve()):
                    series[file.relative_to(metrics).as_posix()] = list(deque(metric_points(file), maxlen=5000))
        return json_safe({"run_id": run_id, "series": series})


_readers: dict[Path, ExperimentReader] = {}
_readers_lock = threading.Lock()


def get_reader() -> ExperimentReader:
    root = train_data_directory()
    with _readers_lock:
        if root not in _readers:
            if len(_readers) >= 4:
                _readers.pop(next(iter(_readers)))
            _readers[root] = ExperimentReader(root)
        return _readers[root]
