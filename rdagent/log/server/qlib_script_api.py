"""HTTP adapters for fixed-entrypoint training and existing result components."""

import codecs
import hashlib
from functools import wraps
from pathlib import Path
from urllib.parse import urlencode

from flask import Blueprint, Response, jsonify, request, send_file

from rdagent.log.server.qlib_experiments import (
    get_reader,
    json_safe,
    train_data_directory,
)
from rdagent.log.server.qlib_tasks import TaskManager, log_identity
from rdagent.log.ui.conf import UI_SETTING

api = Blueprint("qlib_script", __name__, url_prefix="/api/qlib-script")
_managers = {}


def manager() -> TaskManager:
    root = train_data_directory()
    store = Path(UI_SETTING.trace_folder).resolve() / ".qlib-script-tasks"
    key = (root, store)
    if key not in _managers:
        _managers[key] = TaskManager(store, root)
    return _managers[key]


def endpoint(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except FileNotFoundError as exc:
            return jsonify(error=str(exc)), 404
        except (ValueError, TypeError) as exc:
            return jsonify(error=str(exc)), 400
        except RuntimeError as exc:
            return jsonify(error=str(exc)), 409
        except OSError as exc:
            return jsonify(error=str(exc)), 500

    return guarded


def annotate(result):
    tasks = manager().list()
    for task in tasks:
        if task.get("output_dir") and Path(task["output_dir"]).resolve() == Path(result["output_dir"]).resolve():
            active = task.get("state") in {"pending", "running", "stopping"}
            if not task.get("output_observed") or (
                not active
                and (not task.get("log_identity") or task["log_identity"] != log_identity(result["output_dir"]))
            ):
                continue
            result["management_mode"], result["task_id"] = "managed", task["id"]
            result["process_state"] = task["state"]
            result["task_error"] = task.get("error")
            terminal = result.get("terminal")
            if terminal and task.get("exit_code") is not None and terminal["exit_code"] != task["exit_code"]:
                result["exit_conflict"] = True
                result["errors"].append(f"Exit-code conflict: log={terminal['exit_code']}, process={task['exit_code']}")
                result["execution_state"] = "failed"
            elif not terminal:
                invalid = result.get("progress", {}).get("terminal_state") in {"invalid", "conflict"}
                result["execution_state"] = "unknown" if invalid and task["state"] == "succeeded" else task["state"]
            if result.get("view"):
                result["view"]["executionState"] = result["execution_state"]
            break
    return result


def downloads(result):
    for item in result.get("artifacts", []):
        item["download_url"] = f"/api/qlib-script/experiments/{result['id']}/artifact?" + urlencode(
            {"path": item["relative_path"]}
        )
    result["log_download_url"] = f"/api/qlib-script/experiments/{result['id']}/log/download"
    return result


@api.route("/experiments", methods=["GET"])
@api.route("/discover", methods=["POST"])
@endpoint
def experiments():
    reader = get_reader()
    rows = [annotate(row) for row in reader.list(manager().output_dirs())]
    return jsonify(json_safe({"train_data_dir": str(reader.root), "exists": reader.root.is_dir(), "experiments": rows}))


@api.route("/experiments/<source_id>", methods=["GET"])
@api.route("/experiments/<source_id>/refresh", methods=["POST"])
@endpoint
def detail(source_id):
    return jsonify(json_safe(downloads(annotate(get_reader().detail(source_id, manager().output_dirs())))))


@api.route("/experiments/<source_id>/progress", methods=["GET"])
@endpoint
def progress(source_id):
    reader = get_reader()
    folder = reader.resolve(source_id, manager().output_dirs())
    result, _ = reader.summary(source_id, folder)
    return jsonify(json_safe(annotate(result)))


@api.route("/experiments/<source_id>/artifacts", methods=["GET"])
@endpoint
def artifacts(source_id):
    rows = get_reader().artifacts(source_id, manager().output_dirs())
    return jsonify(downloads({"id": source_id, "artifacts": rows}))


@api.route("/experiments/<source_id>/artifact", methods=["GET"])
@endpoint
def download(source_id):
    path = get_reader().download(source_id, request.args.get("path", ""), manager().output_dirs())
    return send_file(path, as_attachment=True, download_name=path.name)


@api.route("/experiments/<source_id>/log/download", methods=["GET"])
@endpoint
def download_log(source_id):
    reader = get_reader()
    log = reader.log_file(reader.resolve(source_id, manager().output_dirs()))
    if log is None:
        raise FileNotFoundError("Training log not found")
    return send_file(log, as_attachment=True, download_name=log.name)


@api.route("/experiments/<source_id>/logs", methods=["GET"])
@endpoint
def logs(source_id):
    reader = get_reader()
    log = reader.log_file(reader.resolve(source_id, manager().output_dirs()))
    if log is None:
        raise FileNotFoundError("Training log not found")
    offset, limit = int(request.args.get("offset", 0)), int(request.args.get("limit", 65536))
    if offset < 0 or not 1 <= limit <= 262144:
        raise ValueError("Invalid log offset or limit")
    with log.open("rb") as stream:
        stat = log.stat()
        prefix = stream.read(256)
        generation = hashlib.sha256(f"{stat.st_dev}:{stat.st_ino}".encode() + prefix).hexdigest()[:24]
        previous = request.args.get("generation")
        reset = offset > stat.st_size or bool(previous and previous != generation)
        if reset:
            offset = 0
        stream.seek(offset)
        data = stream.read(limit)
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        text = decoder.decode(data, final=False)
        pending, _ = decoder.getstate()
        next_offset = offset + len(data) - len(pending)
    return jsonify(text=text, offset=next_offset, generation=generation, reset=reset, eof=next_offset >= stat.st_size)


@api.route("/experiments/<source_id>/history", methods=["GET"])
@endpoint
def history(source_id):
    return jsonify(get_reader().history(source_id, request.args.get("run_id", ""), manager().output_dirs()))


@api.route("/tasks", methods=["GET", "POST"])
@endpoint
def tasks():
    if request.method == "POST":
        return jsonify(manager().create(request.get_json())), 201
    return jsonify(tasks=manager().list())


@api.route("/tasks/preview", methods=["POST"])
@endpoint
def preview():
    return jsonify(manager().preview(request.get_json()))


@api.route("/tasks/<task_id>", methods=["GET"])
@endpoint
def task(task_id):
    return jsonify(manager().get(task_id))


@api.route("/tasks/<task_id>/stop", methods=["POST"])
@endpoint
def stop(task_id):
    return jsonify(manager().stop(task_id))


@api.route("/plotly.js", methods=["GET"])
def plotly_script():
    from plotly.offline import get_plotlyjs

    response = Response(get_plotlyjs(), mimetype="application/javascript")
    response.cache_control.public = True
    response.cache_control.max_age = 86400
    return response
