import logging
import os
import random
import threading
import traceback
from collections import defaultdict
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from multiprocessing import Process, Queue
from pathlib import Path
from queue import Empty

import pandas as pd
import randomname
import typer
from flask import Flask, jsonify, request, send_file, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

from rdagent.log.storage import FileStorage
from rdagent.log.ui.conf import UI_SETTING
from rdagent.log.ui.storage import WebStorage

app = Flask(__name__, static_folder=str(Path(UI_SETTING.static_path).resolve()))
CORS(app)
app.config["UI_SERVER_PORT"] = 19899

_YELLOW = "\033[33m"
_RESET = "\033[0m"


class _YellowWarningFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        if record.levelno == logging.WARNING:
            record.levelname = f"{_YELLOW}{record.levelname}{_RESET}"
        return super().format(record)


def _configure_app_logger() -> None:
    formatter = _YellowWarningFormatter(
        fmt="[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    for handler in app.logger.handlers:
        handler.setFormatter(formatter)


_configure_app_logger()


_TARGETS_WITHOUT_USER_INTERACTION = {"general_model", "fin_factor_report"}


class RDAgentTask:
    def __init__(
        self,
        target_name: str,
        kwargs: dict,
        stdout_path: str,
        log_trace_path: str,
        scenario: str,
        trace_name: str,
        ui_server_port: int | None = None,
        create_process: bool = True,
    ) -> None:
        self.target_name = target_name
        self.kwargs = kwargs
        self.stdout_path = stdout_path
        self.log_trace_path = log_trace_path
        self.scenario = scenario
        self.trace_name = trace_name
        self.ui_server_port = ui_server_port
        self.process: Process | None = None

        # Two IPC queues for user interaction.
        # - `user_request_q`: rdagent subprocess -> server (dicts to render on frontend)
        # - `user_response_q`: server -> rdagent subprocess (user input dicts)
        # NOTE: Use multiprocessing.Queue because rdagent is started as a separate process.
        self.user_request_q: Queue = Queue(maxsize=1024)
        self.user_response_q: Queue = Queue(maxsize=1024)

        if create_process:
            self.process = Process(
                target=self._run,
                name=f"rdagent:{self.scenario}:{self.trace_name}",
            )
        self.messages: list[dict] = []
        self.pointers: defaultdict[str, int] = defaultdict(int)

    def start(self) -> None:
        if self.process is not None:
            self.process.start()

    def is_alive(self) -> bool:
        return self.process is not None and self.process.is_alive()

    def get_end_code(self) -> int:
        if self.process is None or self.process.exitcode is None:
            return 0
        return self.process.exitcode

    def stop(self) -> None:
        if self.process is not None and self.process.is_alive():
            self.process.terminate()
            self.process.join()

        # Best-effort cleanup for IPC queues.
        for q in (self.user_request_q, self.user_response_q):
            try:
                q.cancel_join_thread()
            except Exception:
                pass
            try:
                q.close()
            except Exception:
                pass

    def _run(self) -> None:
        from rdagent.log.conf import LOG_SETTINGS

        LOG_SETTINGS.set_ui_server_port(self.ui_server_port)

        from rdagent.log import rdagent_logger

        rdagent_logger.refresh_storages_from_settings()
        rdagent_logger.set_storages_path(self.log_trace_path)
        Path(self.stdout_path).parent.mkdir(parents=True, exist_ok=True)
        with open(self.stdout_path, "w") as log_file:
            with redirect_stdout(log_file), redirect_stderr(log_file):
                rdagent_logger.rebind_console_to_current_streams()
                try:
                    # Only interactive targets should receive IPC queues.
                    if self.target_name not in _TARGETS_WITHOUT_USER_INTERACTION:
                        self.kwargs.setdefault(
                            "user_interaction_queues",
                            (self.user_request_q, self.user_response_q),
                        )

                    if self.target_name == "data_science":
                        from rdagent.app.data_science.loop import main as data_science

                        data_science(**self.kwargs)
                    elif self.target_name == "general_model":
                        from rdagent.app.general_model.general_model import (
                            extract_models_and_implement as general_model,
                        )

                        general_model(**self.kwargs)
                    elif self.target_name == "fin_factor":
                        from rdagent.app.qlib_rd_loop.factor import main as fin_factor

                        fin_factor(**self.kwargs)
                    elif self.target_name == "fin_factor_report":
                        from rdagent.app.qlib_rd_loop.factor_from_report import (
                            main as fin_factor_report,
                        )

                        fin_factor_report(**self.kwargs)
                    elif self.target_name == "fin_model":
                        from rdagent.app.qlib_rd_loop.model import main as fin_model

                        fin_model(**self.kwargs)
                    elif self.target_name == "fin_quant":
                        from rdagent.app.qlib_rd_loop.quant import main as fin_quant

                        fin_quant(**self.kwargs)
                    else:
                        raise ValueError(f"Unknown target: {self.target_name}")
                except Exception:
                    traceback.print_exc()


rdagent_processes: dict[str, RDAgentTask] = {}
log_folder_path = Path(UI_SETTING.trace_folder).absolute()


def _drain_user_requests_into_messages(task: RDAgentTask) -> None:
    """Move a single pending user-interaction request into `task.messages`.

    Assumption: each rdagent process only has one active request at a time.
    """

    try:
        req = task.user_request_q.get_nowait()
    except Empty:
        return
    except Exception:
        return

    # Standardize the message shape for the frontend.
    # The agent can send either a full message dict, or a raw content dict.
    if isinstance(req, dict) and {"tag", "timestamp", "content"}.issubset(req.keys()):
        msg = req
    else:
        msg = {
            "tag": "user_interaction.request",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "content": req,
        }
    task.messages.append(msg)


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(app.static_folder, "favicon.ico", mimetype="image/vnd.microsoft.icon")


def _normalize_static_request_path(fn: str) -> str:
    # Strip a leading static_path prefix from the request path (supports both
    # relative ("./git_ignore_folder/static/...") and absolute paths).
    prefix = UI_SETTING.static_path
    # Normalize to a posix-style relative segment for prefix matching
    rel_prefix = prefix.lstrip("./").lstrip("/")
    if rel_prefix and fn.startswith(f"{rel_prefix}/"):
        return fn[len(rel_prefix) + 1 :]
    return fn


def _get_or_create_task(trace_id: str) -> RDAgentTask:
    task = rdagent_processes.get(trace_id)
    if task is None:
        task = RDAgentTask(
            target_name="",
            kwargs={},
            stdout_path="",
            log_trace_path=trace_id,
            scenario="",
            trace_name="",
            ui_server_port=None,
            create_process=False,
        )
        rdagent_processes[trace_id] = task
    return task


def _resolve_stdout_path(trace_id: str) -> Path | None:
    normalized_trace_id = str(trace_id or "").strip()
    if not normalized_trace_id:
        return None

    task = rdagent_processes.get(str(log_folder_path / normalized_trace_id))
    if task is None or not task.stdout_path:
        return None

    stdout_path = Path(task.stdout_path).resolve()

    try:
        if os.path.commonpath([str(stdout_path), str(log_folder_path)]) != str(log_folder_path):
            return None
    except ValueError:
        return None

    return stdout_path


def read_trace(log_path: Path, id: str = "") -> None:
    fs = FileStorage(log_path)
    ws = WebStorage(port=1, path=log_path)
    task = _get_or_create_task(id)
    task.messages = []
    last_timestamp = None
    for msg in fs.iter_msg():
        data = ws._obj_to_json(obj=msg.content, tag=msg.tag, id=id, timestamp=msg.timestamp.isoformat())
        if data:
            if isinstance(data, list):
                for d in data:
                    task.messages.append(d["msg"])
                    last_timestamp = msg.timestamp
            else:
                task.messages.append(data["msg"])
                last_timestamp = msg.timestamp

    now = datetime.now(timezone.utc)
    if last_timestamp and (now - last_timestamp).total_seconds() > 1800:
        task.messages.append(
            {
                "tag": "END",
                "timestamp": now.isoformat(),
                "content": {"error_msg": "Trace session has ended.", "end_code": 0},
            }
        )


def _collect_existing_trace_ids(trace_root: Path) -> list[str]:
    """Return trace ids that should be visible in the UI history panel."""

    if not trace_root.exists():
        return []

    trace_ids: list[str] = []
    for trace_dir in sorted(trace_root.glob("*/*"), key=lambda p: str(p)):
        if not trace_dir.is_dir():
            continue
        if "uploads" in trace_dir.relative_to(trace_root).parts:
            continue
        if not any(trace_dir.rglob("*.pkl")):
            continue

        trace_ids.append(trace_dir.relative_to(trace_root).as_posix())

    return trace_ids


def _load_existing_traces(trace_root: Path) -> None:
    """Load persisted traces into memory so the UI survives a server restart."""

    for trace_id in _collect_existing_trace_ids(trace_root):
        trace_dir = trace_root / trace_id

        try:
            read_trace(trace_dir, id=str(trace_dir))
        except Exception:
            app.logger.exception("Failed to load trace from %s", trace_dir)


@app.route("/trace", methods=["POST"])
def update_trace():
    data = request.get_json()
    trace_id = data.get("id")
    return_all = data.get("all")
    reset = data.get("reset")
    msg_num = random.randint(1, 10)
    app.logger.info(data)
    log_folder_path = Path(UI_SETTING.trace_folder).absolute()
    if not trace_id:
        return jsonify({"error": "Trace ID is required"}), 400
    trace_id = str(log_folder_path / trace_id)

    task = _get_or_create_task(trace_id)

    # Make sure any pending user-interaction requests are visible to the frontend.
    _drain_user_requests_into_messages(task)

    if task.process is not None and not task.is_alive():
        if not task.messages or task.messages[-1].get("tag") != "END":
            task.messages.append(
                {
                    "tag": "END",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "content": {
                        "error_msg": "RD-Agent process has completed.",
                        "end_code": task.get_end_code(),
                    },
                }
            )
            app.logger.warning(f"Process for {trace_id} has ended.")

    user_ip = request.remote_addr

    if reset:
        task.pointers[user_ip] = 0

    start_pointer = task.pointers[user_ip]
    end_pointer = start_pointer + msg_num
    if end_pointer > len(task.messages) or return_all:
        end_pointer = len(task.messages)

    returned_msgs = task.messages[start_pointer:end_pointer]
    task.pointers[user_ip] = end_pointer
    if returned_msgs:
        app.logger.info([msg["tag"] for msg in returned_msgs])
    return jsonify(returned_msgs), 200


@app.route("/stdout", methods=["GET"])
def download_stdout_file():
    trace_id = request.args.get("id", "")
    stdout_path = _resolve_stdout_path(trace_id)

    if stdout_path is None:
        return jsonify({"error": "Trace ID is required or invalid"}), 400
    if not stdout_path.exists() or not stdout_path.is_file():
        return jsonify({"error": "Stdout file not found"}), 404

    return send_file(
        stdout_path,
        as_attachment=True,
        download_name=stdout_path.name,
        mimetype="text/plain",
    )


@app.route("/traces", methods=["GET"])
def list_traces():
    """Return trace ids that are available for history browsing."""

    trace_ids = _collect_existing_trace_ids(log_folder_path)
    return jsonify(trace_ids), 200


@app.route("/upload", methods=["POST"])
def upload_file():
    # 获取请求体中的字段
    global rdagent_processes
    scenario = request.form.get("scenario")
    files = request.files.getlist("files")
    competition = request.form.get("competition")
    loop_n = request.form.get("loops")
    all_duration = request.form.get("all_duration")
    region = request.form.get("region")
    market = request.form.get("market")

    # scenario = "Data Science Loop"
    if scenario == "Data Science":
        competition = competition[10:]  # Eg. MLE-Bench:aerial-cactus-competition
        trace_name = f"{competition}-{randomname.get_name()}"
    else:
        trace_name = randomname.get_name()
    trace_files_path = log_folder_path / "uploads" / scenario / trace_name

    log_trace_path = (log_folder_path / scenario / trace_name).absolute()
    stdout_path = log_folder_path / scenario / f"{trace_name}.log"
    if not stdout_path.exists():
        stdout_path.parent.mkdir(parents=True, exist_ok=True)

    # save files
    for file in files:
        if file:
            p = (log_folder_path / "uploads" / scenario / trace_name).resolve()
            sanitized_filename = secure_filename(file.filename)  # Sanitize filename
            target_path = (p / sanitized_filename).resolve()  # Normalize target path
            # Ensure target_path is within the allowed base directory
            if os.path.commonpath([str(target_path), str(p)]) == str(p) and target_path.is_file() == False:
                if not p.exists():
                    p.mkdir(parents=True, exist_ok=True)
                file.save(target_path)
            else:
                return jsonify({"error": "Invalid file path"}), 400

    target_name = None
    kwargs = {}
    loop_n_val = int(loop_n) if loop_n else None
    all_duration_val = f"{all_duration}h" if all_duration else None

    if scenario == "Finance Data Building":
        target_name = "fin_factor"
        kwargs = {
            "loop_n": loop_n_val,
            "all_duration": all_duration_val,
            "base_features_path": str(trace_files_path),
            "region": region,
            "market": market,
        }
    if scenario == "Finance Model Implementation":
        target_name = "fin_model"
        kwargs = {
            "loop_n": loop_n_val,
            "all_duration": all_duration_val,
            "base_features_path": str(trace_files_path),
            "region": region,
            "market": market,
        }
    if scenario == "Finance Whole Pipeline":
        target_name = "fin_quant"
        kwargs = {
            "loop_n": loop_n_val,
            "all_duration": all_duration_val,
            "base_features_path": str(trace_files_path),
            "region": region,
            "market": market,
        }
    if scenario == "Finance Data Building (Reports)":
        target_name = "fin_factor_report"
        kwargs = {"report_folder": str(trace_files_path), "all_duration": all_duration_val}
    if scenario == "General Model Implementation":
        if len(files) == 0:  # files is one link
            rfp = request.form.get("files")[0]
        else:  # one file is uploaded
            rfp = str(trace_files_path / files[0].filename)
        target_name = "general_model"
        kwargs = {"report_file_path": rfp}
    if scenario == "Data Science":
        target_name = "data_science"
        kwargs = {"competition": competition, "loop_n": loop_n_val, "timeout": all_duration_val}

    if target_name is None:
        return jsonify({"error": "Unknown scenario"}), 400

    app.logger.info(f"Started process for {log_trace_path} with target: {target_name}, kwargs: {kwargs}")
    if market:
        app.logger.warning(f"[upload] scenario={scenario} region={region} market={market}")
    else:
        app.logger.warning(f"[upload] scenario={scenario} region={region} market=(not set, will use region default)")
    task = RDAgentTask(
        target_name=target_name,
        kwargs=kwargs,
        stdout_path=str(stdout_path),
        log_trace_path=str(log_trace_path),
        scenario=scenario,
        trace_name=trace_name,
        ui_server_port=app.config["UI_SERVER_PORT"],
    )
    task.start()
    app.logger.warning(f"Task {log_trace_path} started.")
    rdagent_processes[str(log_trace_path)] = task
    return (
        jsonify(
            {
                "id": f"{scenario}/{trace_name}",
            }
        ),
        200,
    )


@app.route("/receive", methods=["POST"])
def receive_msgs():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data received"}), 400
    except Exception as e:
        return jsonify({"error": "Internal Server Error"}), 500

    if isinstance(data, list):
        for d in data:
            task = _get_or_create_task(d["id"])
            task.messages.append(d["msg"])
    else:
        task = _get_or_create_task(data["id"])
        task.messages.append(data["msg"])

    return jsonify({"status": "success"}), 200


@app.route("/user_interaction/submit", methods=["POST"])
def submit_user_interaction_response():
    """Frontend submits a user response; server forwards it to the rdagent subprocess via IPC queue."""
    data = request.get_json(silent=True) or {}
    trace_id = data.get("id")
    payload = data.get("payload")

    if not trace_id:
        return jsonify({"error": "Trace ID is required"}), 400
    if payload is None:
        return jsonify({"error": "Missing 'payload'"}), 400

    trace_id = str(log_folder_path / trace_id)
    task = _get_or_create_task(trace_id)

    try:
        task.user_response_q.put(payload, block=False)
    except Exception as e:
        return jsonify({"error": f"Failed to enqueue user response: {e}"}), 500

    return jsonify({"status": "success"}), 200


@app.route("/control", methods=["POST"])
def control_process():
    global rdagent_processes
    data = request.get_json()
    app.logger.info(data)
    if not data or "id" not in data or "action" not in data:
        return jsonify({"error": "Missing 'id' or 'action' in request"}), 400

    id = str(log_folder_path / data["id"])
    action = data["action"]

    if action != "stop":
        return jsonify({"error": "Only 'stop' action is supported"}), 400

    if id not in rdagent_processes or rdagent_processes[id] is None:
        return jsonify({"error": "No running process for given id"}), 400

    task = rdagent_processes[id]

    if task.process is None:
        return jsonify({"error": "No running process for given id"}), 400

    try:
        if task.is_alive():
            task.stop()

        if not task.messages or task.messages[-1].get("tag") != "END":
            task.messages.append(
                {
                    "tag": "END",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "content": {"error_msg": "RD-Agent process was stopped by user.", "end_code": -1},
                }
            )
            app.logger.warning(f"Process for {id} has been stopped.")
        return jsonify({"status": "stopped"}), 200
    except Exception as e:
        return jsonify({"error": f"Failed to {action} process, {e}"}), 500


@app.route("/test", methods=["GET"])
def test():
    # return 'Hello, World!'
    msgs = {k: [i["tag"] for i in task.messages] for k, task in rdagent_processes.items()}
    pointers = {k: dict(task.pointers) for k, task in rdagent_processes.items()}
    return jsonify({"msgs": msgs, "pointers": pointers}), 200


# ---------- Qlib Data Provider (init once per region, reused) ----------

_qlib_registry: dict[str, "QlibDataProvider"] = {}
_qlib_failed_regions: dict[str, str] = {}
_qlib_lock = threading.Lock()


class QlibDataProvider:
    def __init__(self, region: str):
        from rdagent.core.region_config import get_region_config

        ri = get_region_config(region)
        self.region = region
        self.provider_uri = ri.qlib_data_path
        self.symbols_path = ri.symbols_path
        self.ohlcv_fields = ri.ohlcv_fields if ri.ohlcv_fields else ["$open", "$close", "$high", "$low"]
        self.tech_fields = ri.tech_fields if ri.tech_fields else ["$volume"]
        self._symbols: list[dict] = []
        self._verify_data_dir()
        self._init_qlib()
        self._load_symbols()

    def _verify_data_dir(self) -> None:
        p = Path(self.provider_uri)
        if not p.exists():
            raise ValueError(f"Data directory not found: {self.provider_uri}")
        if not (p / "calendars" / "day.txt").exists():
            raise ValueError(f"Calendar not found: {p / 'calendars' / 'day.txt'}")

    @property
    def data_range(self) -> tuple[str, str]:
        """Return (first_date, last_date) from calendars/day.txt."""
        cal = Path(self.provider_uri) / "calendars" / "day.txt"
        if not cal.exists():
            return ("", "")
        with open(cal, encoding="utf-8") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        if not lines:
            return ("", "")
        return (lines[0], lines[-1])

    def _init_qlib(self) -> None:
        import qlib
        from qlib.data import D

        qlib.init(
            provider_uri={"day": self.provider_uri},
            expression_cache=None,
        )
        self.D = D

    def _load_symbols(self) -> None:
        p = Path(self.symbols_path)
        if p.is_file():
            csv_path = p
        elif p.is_dir():
            csv_path = None
            for pat in [f"{self.region}_symbols.csv", f"{self.region}_benchmarks.csv"]:
                candidate = p / pat
                if candidate.exists():
                    csv_path = candidate
                    break
            if csv_path is None:
                for f in p.glob(f"{self.region}_*.csv"):
                    csv_path = f
                    break
        else:
            csv_path = None
        if csv_path is not None:
            self._symbols = pd.read_csv(csv_path).to_dict(orient="records")
        else:
            self._symbols = []

    def _parse_date(self, s: str) -> str:
        return pd.Timestamp(s).strftime("%Y-%m-%d")

    def query(
        self,
        instruments: list[str],
        fields: list[str],
        start: str,
        end: str,
        freq: str = "day",
    ) -> pd.DataFrame:
        df: pd.DataFrame = self.D.features(
            instruments,
            fields,
            start_time=start,
            end_time=end,
            freq=freq,
        )
        if df.empty:
            return df
        df = df.swaplevel().sort_index()
        df.index.names = ["date", "instrument"]
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.map("_".join)
        return df


def _get_provider(region: str) -> QlibDataProvider | None:
    if region in _qlib_failed_regions:
        return None
    with _qlib_lock:
        if region not in _qlib_registry:
            try:
                _qlib_registry[region] = QlibDataProvider(region)
            except Exception as e:
                _qlib_failed_regions[region] = str(e)
                raise
        return _qlib_registry[region]


@app.route("/api/qlib/reload/<region>", methods=["POST"])
def reload_qlib_region(region: str):
    """Manually re-run qlib.init + reload symbols for a region.

    Qlib data on disk may be updated daily; this endpoint drops the cached
    provider and rebuilds it so subsequent queries see the latest data.
    """
    with _qlib_lock:
        _qlib_registry.pop(region, None)
        prev_err = _qlib_failed_regions.pop(region, None)
        try:
            _qlib_registry[region] = QlibDataProvider(region)
        except Exception as e:
            _qlib_failed_regions[region] = str(e)
            import traceback as tb
            return jsonify({
                "status": "error",
                "region": region,
                "error": str(e),
                "trace": tb.format_exc(),
                "previous_error": prev_err,
            }), 500
    provider = _qlib_registry[region]
    start, end = provider.data_range
    app.logger.info(f"Region {region} reloaded (qlib init + symbols cached)")
    return jsonify({
        "status": "success",
        "region": region,
        "data_range": {"start": start, "end": end},
        "symbols_count": len(provider._symbols),
    }), 200


@app.route("/api/symbols/<region>", methods=["GET"])
def get_symbols(region: str):
    """Return cached symbols list for a region (loaded at startup)."""
    provider = _get_provider(region)
    if provider is None:
        err = _qlib_failed_regions.get(region, "unknown error")
        return jsonify({"error": f"Region '{region}' failed to load: {err}"}), 503
    return jsonify(provider._symbols)


@app.route("/api/ohlcv/<region>", methods=["POST"])
def get_ohlcv(region: str):
    """
    Query OHLCV data for a list of instruments over a time range.
    Body: { "instruments": ["000001.SZ"], "start": "2024-01-01", "end": "2024-12-31", "fields": ["$open","$close"] }
    If fields is empty, all configured fields (ohlcv_fields + tech_fields) are queried
    and the response includes ohlcv_fields/tech_fields classification for the frontend.
    """
    data = request.get_json(silent=True) or {}
    instruments = data.get("instruments", [])
    start = data.get("start", "2024-01-01")
    end = data.get("end", "2024-12-31")
    fields = data.get("fields", [])

    if not instruments:
        return jsonify({"error": "Missing instruments"}), 400

    try:
        provider = _get_provider(region)
        if provider is None:
            err = _qlib_failed_regions.get(region, "unknown error")
            return jsonify({"error": f"Region '{region}' failed to load: {err}"}), 503
        if not fields:
            fields = provider.ohlcv_fields + provider.tech_fields
        adjust = bool(data.get("adjust", False))

        df = provider.query(instruments, fields, start, end)
        if df.empty:
            return jsonify({"data": []})
        df = df.reset_index()
        # Drop suspended days: close NaN or volume == 0.
        # Resolve close column by position (4th ohlcv field) so expression
        # fields like "$close/$factor" work; volume by name match in tech_fields.
        close_field = provider.ohlcv_fields[3] if len(provider.ohlcv_fields) >= 4 else "$close"
        if close_field in df.columns:
            df = df[df[close_field].notna()]
        vol_field = next((f for f in provider.tech_fields if "volume" in f), None)
        if vol_field and vol_field in df.columns:
            df = df[df[vol_field].fillna(0) > 0]
        if df.empty:
            return jsonify({"data": []})
        df = df.reset_index(drop=True)
        # Ensure date column is plain string for JSON serialization
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        # Adjusted prices: if requested, replace raw OHLC with adjusted values
        if adjust and "$adjclose" in df.columns and "$close" in df.columns:
            adj_ratio = df["$adjclose"] / df["$close"]
            for raw_field in ["$open", "$high", "$low"]:
                if raw_field in df.columns:
                    df[raw_field] = df[raw_field] * adj_ratio
            df["$close"] = df["$adjclose"]
        # Manually convert NaN to None so jsonify produces valid JSON (null)
        def _clean(v):
            try:
                if pd.isna(v):
                    return None
            except (TypeError, ValueError):
                pass
            return v
        result = {
            "columns": df.columns.tolist(),
            "data": [[_clean(v) for v in row] for row in df.values.tolist()],
            "ohlcv_fields": provider.ohlcv_fields,
            "tech_fields": provider.tech_fields,
        }
        return jsonify(result)
    except Exception as e:
        import traceback as tb

        return jsonify({"error": str(e), "trace": tb.format_exc()}), 500


# ---------- End Qlib Data Provider ----------


@app.route("/api/regions", methods=["GET"])
def get_regions():
    """Return available regions and the current default region."""
    from rdagent.core.region_config import get_available_regions, get_default_region

    return jsonify({
        "regions": get_available_regions(),
        "default_region": get_default_region(),
    }), 200


@app.route("/api/markets", methods=["GET"])
def get_markets():
    """Return cached market list for a region (scanned from instruments dir at startup)."""
    from rdagent.core.region_config import get_cached_markets

    region = request.args.get("region")
    if not region:
        return jsonify({"error": "region query param required"}), 400
    return jsonify({"region": region, "markets": get_cached_markets(region)}), 200


@app.route("/api/region", methods=["POST"])
def set_region():
    """Set the default region (persists to ~/rd-agent/config.json)."""
    data = request.get_json(silent=True) or {}
    region = data.get("region")
    if not region:
        return jsonify({"error": "Missing 'region'"}), 400
    from rdagent.core.region_config import set_default_region

    set_default_region(region)
    return jsonify({"status": "success", "region": region}), 200


@app.route("/api/scenario_info", methods=["GET"])
def get_scenario_info():
    """Return the configured Qlib data split for each scenario.

    Reads from the QLIB_FACTOR_ / QLIB_MODEL_ / QLIB_QUANT_ env-driven settings so the
    frontend can display the real data source instead of a hardcoded description.
    """
    try:
        from rdagent.app.qlib_rd_loop.conf import (  # type: ignore
            FACTOR_PROP_SETTING,
            MODEL_PROP_SETTING,
            QUANT_PROP_SETTING,
        )

        def _split(s):
            return {
                "train_start": s.train_start,
                "train_end": s.train_end,
                "valid_start": s.valid_start,
                "valid_end": s.valid_end,
                "test_start": s.test_start,
                "test_end": s.test_end,
            }

        return jsonify({
            "factor": _split(FACTOR_PROP_SETTING),
            "model": _split(MODEL_PROP_SETTING),
            "quant": _split(QUANT_PROP_SETTING),
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/data_range", methods=["GET"])
def get_data_range():
    """Return the actual data coverage (first/last date) for each available region,
    read from <qlib_data_path>/calendars/day.txt."""
    from rdagent.core.region_config import get_available_regions

    out = {}
    for region in get_available_regions():
        provider = _get_provider(region)
        if provider is None:
            out[region] = {"start": "", "end": "", "error": _qlib_failed_regions.get(region, "unknown")}
        else:
            start, end = provider.data_range
            out[region] = {"start": start, "end": end}
    return jsonify({"regions": out}), 200


@app.route("/", methods=["GET"])
def index():
    # return 'Hello, World!'
    # return {k: [i["tag"] for i in v] for k, v in msgs_for_frontend.items()}
    return send_from_directory(app.static_folder, "index.html")


@app.route("/<path:fn>", methods=["GET"])
def server_static_files(fn):
    return send_from_directory(app.static_folder, _normalize_static_request_path(fn))


def main(port: int = 19899):
    app.config["UI_SERVER_PORT"] = port
    _load_existing_traces(log_folder_path)
    # Preload all regions at startup
    from rdagent.core.region_config import get_available_regions, scan_all_regions

    markets_cache = scan_all_regions()
    for r, markets in markets_cache.items():
        app.logger.info(f"Region {r} markets scanned: {len(markets)} markets cached")
    for r in get_available_regions():
        try:
            _get_provider(r)
            app.logger.info(f"Region {r} loaded (qlib init + symbols cached)")
        except Exception as e:
            app.logger.warning(f"Region {r} load failed: {e}")
    app.run(debug=False, host="0.0.0.0", port=port)


if __name__ == "__main__":
    typer.run(main)
