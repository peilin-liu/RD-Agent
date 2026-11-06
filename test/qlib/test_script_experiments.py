"""File-protocol, result integration and process tests without real training."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

import pandas as pd
import yaml

from rdagent.log.server.qlib_experiments import ExperimentReader, read_metrics
from rdagent.log.server.qlib_progress import ProgressReader, parse_terminal
from rdagent.log.server.qlib_tasks import (
    TaskManager,
    build_arguments,
    log_identity,
    process_identity,
)

RID = "a" * 32
WINDOW = "b" * 32


def terminal(status="success", **extra):
    record = {
        "status": status,
        "stage": "complete" if status == "success" else "analyze",
        "exit_code": 0 if status == "success" else 1,
        "run_id": RID,
        "experiment_id": "101",
    }
    return "QRUN_RESULT " + json.dumps({**record, **extra}, ensure_ascii=False) + "\n"


class FilesTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "outputs"
        self.output = self.root / "example"
        self.output.mkdir(parents=True)
        self.store = self.base / "mlruns"
        self.run = self.store / "101" / RID
        self.artifacts = self.run / "artifacts"
        self.artifacts.mkdir(parents=True)
        self.dump(self.store / "101/meta.yaml", {"name": "example", "experiment_id": "101"})
        self.dump(
            self.run / "meta.yaml",
            {"run_id": RID, "experiment_id": "101", "status": 3, "artifact_uri": self.artifacts.as_uri()},
        )
        self.dump(
            self.output / "rolling_workflow_config.yaml",
            {
                "qlib_init": {"exp_manager": {"kwargs": {"uri": self.store.as_uri()}}},
                "market": "csi300",
                "benchmark": "000300.sh",
            },
        )
        (self.run / "metrics").mkdir()
        (self.run / "metrics/IC").write_text("1000 0.1 0\n")
        report = pd.DataFrame(
            {
                "return": [0.01, -0.02, 0.03],
                "cost": [0.001] * 3,
                "bench": [0.002, -0.001, 0.004],
                "turnover": [0.1, 0.2, 0.3],
                "total_cost": [10, 20, 30],
            },
            index=pd.date_range("2026-01-01", periods=3, name="datetime"),
        )
        (self.artifacts / "portfolio_analysis").mkdir()
        report.to_pickle(self.artifacts / "portfolio_analysis/report_normal_1day.pkl")
        self.log = self.output / "rolling.log"
        self.log.write_text(f"Recorder {RID} starts running under Experiment 101\n")
        self.reader = ExperimentReader(self.root)
        self.source_id = next(iter(self.reader.sources()))

    @staticmethod
    def dump(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data))

    def append(self, text):
        with self.log.open("a") as stream:
            stream.write(text)


class ProgressTests(FilesTestCase):
    def test_actual_terminal_fields_and_legacy_draft(self):
        actual = parse_terminal(terminal("failed", error="分析失败", extra_field=1))
        self.assertEqual(actual["failed_stage"], "analyze")
        interrupted = parse_terminal(terminal("interrupted", exit_code=130))
        self.assertEqual(interrupted["status"], "interrupted")
        legacy = parse_terminal('QRUN_RESULT {"status":"success","failed_stage":null,"exit_code":0,"run_id":null}')
        self.assertIsNone(legacy["failed_stage"])

    def test_invalid_and_inconsistent_json_does_not_report_success(self):
        for record in [
            terminal(exit_code=True),
            terminal(exit_code=1),
            terminal(stage=None),
            terminal(status=[]),
            'QRUN_RESULT {"status":"success"}\n',
            'QRUN_RESULT {"status":"success","status":"failed"}\n',
        ]:
            with self.subTest(record=record), self.assertRaises(ValueError):
                parse_terminal(record)

    def test_reverse_window_labels_do_not_count_as_completion(self):
        self.append("滚动窗口共 9 个:\n训练窗口 9/9\n")
        reader = ProgressReader()
        first = reader.read(self.log)
        self.assertEqual((first["completed_windows"], first["total_windows"]), (0, 9))
        self.append(f"窗口 9/9 训练完成 (run_id={WINDOW})\n" * 2)
        self.assertEqual(reader.read(self.log)["completed_windows"], 1)
        self.assertEqual(ProgressReader().read(self.log)["completed_windows"], 1)

    def test_half_utf8_and_terminal_wait_for_final_newline(self):
        encoded = terminal(error="中文").encode()
        split = encoded.index("中文".encode()) + 1
        with self.log.open("ab") as stream:
            stream.write(encoded[:split])
        reader = ProgressReader()
        self.assertEqual(reader.read(self.log)["terminal_state"], "missing")
        with self.log.open("ab") as stream:
            stream.write(encoded[split:-1])
        self.assertEqual(reader.read(self.log)["terminal_state"], "missing")
        with self.log.open("ab") as stream:
            stream.write(b"\n")
        self.assertEqual(reader.read(self.log)["terminal"]["error"], "中文")

    def test_duplicate_terminal_is_idempotent_and_conflict_is_visible(self):
        self.append(terminal() * 2)
        reader = ProgressReader()
        self.assertEqual(reader.read(self.log)["terminal_state"], "valid")
        self.append(terminal("failed"))
        result = reader.read(self.log)
        self.assertEqual(result["terminal_state"], "conflict")
        self.assertIsNone(result["terminal"])

    def test_rewrite_larger_than_old_file_resets_progress(self):
        self.append(terminal())
        reader = ProgressReader()
        self.assertEqual(reader.read(self.log)["terminal_state"], "valid")
        self.log.write_text("new invocation\n" * 100 + "训练窗口 2/3\n")
        result = reader.read(self.log)
        self.assertEqual(result["terminal_state"], "missing")
        self.assertEqual((result["completed_windows"], result["total_windows"]), (0, 3))

    def test_carriage_return_backtest_is_stage_progress_only(self):
        self.append("backtest loop: 50%|abc| 5/10 [time]\rbacktest loop: 100%|abc| 10/10 [time]\r")
        result = ProgressReader().read(self.log)
        self.assertEqual(result["backtest"], {"completed": 10, "total": 10})
        self.assertEqual(result["stage"], "backtesting")
        self.assertIsNone(result["terminal"])

    def test_parallel_windows_do_not_assign_unattributed_iterations(self):
        self.append("[1:MainThread] 训练窗口 2/2\n[2:MainThread] 训练窗口 1/2\n[20] valid rank: 0.1\n")
        result = ProgressReader().read(self.log)
        self.assertEqual(len(result["active_windows"]), 2)
        self.assertTrue(all(row["run_id"] is None for row in result["active_windows"]))

    def test_bounded_batches_replay_to_same_terminal(self):
        self.append(terminal())
        reader = ProgressReader(batch_bytes=17)
        for _ in range(100):
            result = reader.read(self.log)
            if not result["recovering"]:
                break
        self.assertEqual(result["terminal"]["run_id"], RID)


class ResultTests(FilesTestCase):
    def test_shallow_discovery_does_not_include_history_or_grandchildren(self):
        nested = self.output / "nested"
        nested.mkdir()
        (nested / "rolling.log").write_text(terminal())
        self.assertEqual(list(self.reader.sources().values()), [self.output])

    def test_legacy_result_and_read_only_recovery(self):
        self.append(f"集成结果已写入实验 `example` (recorder {RID})\n")
        before = {p: p.stat().st_mtime_ns for p in self.base.rglob("*") if p.is_file()}
        result = self.reader.detail(self.source_id)
        restarted = ExperimentReader(self.root).detail(self.source_id)
        self.assertEqual(result["result_state"], "ready")
        self.assertEqual(result["name"], "example")
        self.assertEqual(restarted["run_id"], RID)
        self.assertEqual(result["execution_state"], "unknown")
        self.assertIsNone(result["view"]["researchHypothesis"])
        self.assertEqual(before, {p: p.stat().st_mtime_ns for p in self.base.rglob("*") if p.is_file()})

    def test_failed_analysis_keeps_readable_backtest(self):
        self.append(terminal("failed"))
        result = self.reader.detail(self.source_id)
        self.assertEqual((result["execution_state"], result["result_state"]), ("failed", "ready"))
        self.assertEqual(result["metrics"]["IC"], 0.1)

    def test_failure_before_run_does_not_pick_an_existing_run(self):
        self.append(terminal("failed", run_id=None, experiment_id=None, stage="config"))
        result = self.reader.detail(self.source_id)
        self.assertIsNone(result["run_id"])
        self.assertEqual(result["metrics"], {})
        self.assertEqual(result["execution_state"], "failed")

    def test_terminal_identity_never_falls_back_to_legacy_latest(self):
        self.append(f"集成结果已写入实验 `example` (recorder {RID})\n" + terminal(run_id="c" * 32))
        result = self.reader.detail(self.source_id)
        self.assertEqual(result["run_id"], "c" * 32)
        self.assertEqual(result["result_state"], "missing")

    def test_window_recorder_is_not_the_main_run(self):
        self.log.write_text(f"Recorder {WINDOW} starts running under Experiment 102\n")
        result = self.reader.detail(self.source_id)
        self.assertIsNone(result["run_id"])

    def test_ambiguous_completion_does_not_choose_last(self):
        self.append(
            f"集成结果已写入实验 `example` (recorder {RID})\n集成结果已写入实验 `example` (recorder {WINDOW})\n"
        )
        self.assertEqual(self.reader.detail(self.source_id)["result_state"], "ambiguous")

    def test_metrics_match_highest_step_not_last_line_and_nonfinite_is_null(self):
        (self.run / "metrics/IC").write_text("1000 0.5 9\n2000 0.1 1\n")
        (self.run / "metrics/nan").write_text("1000 nan 0\n")
        self.assertEqual(read_metrics(self.run), {"IC": 0.5, "nan": None})

    def test_partially_written_nested_configuration_is_recoverable(self):
        self.dump(self.output / "rolling_workflow_config.yaml", {"qlib_init": {"exp_manager": None}})
        self.append(terminal())
        self.assertEqual(self.reader.detail(self.source_id)["result_state"], "missing")
        self.dump(
            self.output / "rolling_workflow_config.yaml",
            {"qlib_init": {"exp_manager": {"kwargs": {"uri": self.store.as_uri()}}}},
        )
        self.assertEqual(self.reader.detail(self.source_id)["result_state"], "ready")

    def test_experiment_metadata_must_match_the_explicit_completion_name(self):
        self.append(f"集成结果已写入实验 `example` (recorder {RID})\n")
        self.dump(self.store / "101/meta.yaml", {"name": "another-experiment", "experiment_id": "101"})
        self.assertEqual(self.reader.detail(self.source_id)["result_state"], "missing")

    def test_revision_changes_when_an_older_metric_is_updated(self):
        self.append(terminal())
        before = self.reader.detail(self.source_id)["result_revision"]
        (self.run / "metrics/IC").write_text("1000 0.4 1\n")
        self.assertNotEqual(before, self.reader.detail(self.source_id)["result_revision"])

    def test_later_optional_artifact_invalidates_result_and_report_caches(self):
        self.append(terminal())
        first = self.reader.detail(self.source_id)
        self.assertNotIn("total_trade_count", first["metrics"])
        pd.DataFrame({"count": [1, 2]}).to_pickle(self.artifacts / "portfolio_analysis/indicators_normal_1day.pkl")
        second = self.reader.detail(self.source_id)
        self.assertNotEqual(first["result_revision"], second["result_revision"])
        self.assertEqual(second["metrics"]["total_trade_count"], 3)

    def test_optional_bad_pickle_does_not_hide_core_result(self):
        (self.artifacts / "portfolio_analysis/positions_normal_1day.pkl").write_text("not a pickle")
        self.append(terminal())
        result = self.reader.detail(self.source_id)
        self.assertEqual(result["result_state"], "ready")
        self.assertTrue(any("positions" in message for message in result["errors"]))

    def test_missing_core_metrics_keeps_report_visible_but_partial(self):
        (self.run / "metrics/IC").unlink()
        self.append(terminal())
        result = self.reader.detail(self.source_id)
        self.assertEqual(result["result_state"], "partial")
        self.assertIsNotNone(result["view"]["feedbackCharts"])

    def test_artifact_uri_and_snapshot_files_survive_missing_original_window(self):
        moved = self.base / "artifact-location"
        self.artifacts.rename(moved)
        self.dump(self.run / "meta.yaml", {"run_id": RID, "experiment_id": "101", "artifact_uri": moved.as_uri()})
        self.dump(
            moved / "rolling_manifest.yaml",
            {
                "active_window": "2026-01-01",
                "windows": [{"key": "2026-01-01", "run_id": WINDOW, "run_dir": "artifacts/windows/2026-01-01"}],
            },
        )
        snapshot = moved / "windows/2026-01-01/artifacts/params.pkl"
        snapshot.parent.mkdir(parents=True)
        snapshot.write_bytes(b"model, never loaded")
        self.append(terminal())
        result = self.reader.detail(self.source_id)
        self.assertEqual(result["result_state"], "ready")
        self.assertEqual(len(result["windows"]), 1)
        self.assertTrue(any(a["relative_path"].endswith("params.pkl") for a in result["artifacts"]))

    def test_declared_artifact_uri_takes_precedence_over_old_default_files(self):
        declared = self.base / "declared-artifacts"
        (declared / "portfolio_analysis").mkdir(parents=True)
        report = pd.read_pickle(self.artifacts / "portfolio_analysis/report_normal_1day.pkl")
        report["turnover"] = 0.9
        report.to_pickle(declared / "portfolio_analysis/report_normal_1day.pkl")
        self.dump(self.run / "meta.yaml", {"run_id": RID, "experiment_id": "101", "artifact_uri": declared.as_uri()})
        self.append(terminal())
        self.assertAlmostEqual(self.reader.detail(self.source_id)["metrics"]["avg_daily_turnover"], 0.9)

    def test_download_blocks_traversal_and_symlink_escape(self):
        self.append(terminal())
        secret = self.base / "outside"
        secret.write_text("private")
        (self.artifacts / "escape").symlink_to(secret)
        for name in ["../../outside", str(secret), "escape"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.reader.download(self.source_id, name)


class ArgumentsTests(unittest.TestCase):
    def test_fixed_entry_and_argument_values_are_not_shell_code(self):
        root = Path("/tmp/training")
        expression = "Ref(Mean($open, 3), -12)/Ref($open, -1) - 1"
        rows = [
            {"name": "label-expr", "value": expression},
            {"name": "no-lock-thread-rand", "kind": "flag"},
            {"name": "new-supported-option", "value": "--literal"},
            {"name": "future_option", "value": ""},
            {"name": "num-leaves", "value": 0},
            {"name": "ignored", "value": "x", "enabled": False},
        ]
        argv, _ = build_arguments(rows, root)
        self.assertIn("--label-expr=" + expression, argv)
        self.assertIn("--new-supported-option=--literal", argv)
        self.assertIn("--future_option=", argv)
        self.assertIn("--num-leaves=0", argv)
        self.assertIn("--no-lock-thread-rand", argv)
        self.assertNotIn("--ignored=x", argv)
        self.assertFalse(any("num-threads" in value for value in argv))

    def test_preview_rejects_command_override_and_preserves_explicit_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = TaskManager(Path(directory) / "tasks", Path(directory) / "default")
            with self.assertRaises(ValueError):
                manager.preview({"command": "python other.py", "overrides": []})
            result = manager.preview(
                {
                    "overrides": [
                        {"name": "out-dir", "value": directory},
                        {"name": "rolling-exp-name", "value": "chosen"},
                    ]
                }
            )
            self.assertEqual(result["output_dir"], str(Path(directory) / "chosen"))
            self.assertTrue(any(arg == "--rolling-exp-name=chosen" for arg in result["argv"]))


class ApiTests(FilesTestCase):
    def setUp(self):
        super().setUp()
        from rdagent.log.server import app as server
        from rdagent.log.server import qlib_experiments, qlib_script_api

        self.client = server.app.test_client()
        for module in (qlib_experiments, qlib_script_api):
            patcher = patch.object(module, "train_data_directory", return_value=self.root)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(server.UI_SETTING, "trace_folder", str(self.base / "traces"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_http_recovery_and_download_safety(self):
        self.append(terminal())
        rows = self.client.get("/api/qlib-script/experiments").get_json()["experiments"]
        source = rows[0]["id"]
        response = self.client.get(f"/api/qlib-script/experiments/{source}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["execution_state"], "succeeded")
        self.assertEqual(response.get_json()["management_mode"], "external")
        self.assertEqual(self.client.post(f"/api/qlib-script/tasks/{source}/stop").status_code, 400)
        self.assertEqual(
            self.client.get(f"/api/qlib-script/experiments/{source}/artifact?path=../../outside").status_code, 400
        )
        self.assertEqual(self.client.get("/api/qlib-script/experiments/not-registered").status_code, 404)

    def test_log_cursor_reads_appends_and_resets_after_replacement(self):
        url = f"/api/qlib-script/experiments/{self.source_id}/logs"
        first = self.client.get(url).get_json()
        self.append("new line\n")
        second = self.client.get(
            url, query_string={"offset": first["offset"], "generation": first["generation"]}
        ).get_json()
        self.assertIn("new line", second["text"])
        self.log.write_text("replacement\n")
        third = self.client.get(
            url, query_string={"offset": second["offset"], "generation": second["generation"]}
        ).get_json()
        self.assertTrue(third["reset"])
        self.assertEqual(third["text"], "replacement\n")

    def test_task_create_does_not_accept_an_alternative_entrypoint(self):
        response = self.client.post("/api/qlib-script/tasks/preview", json={"command": "arbitrary", "overrides": []})
        self.assertEqual(response.status_code, 400)

    def test_reused_directory_does_not_inherit_old_task_ownership_or_exit_code(self):
        from rdagent.log.server import qlib_script_api

        self.append(terminal())
        task = {
            "id": "d" * 32,
            "output_dir": str(self.output),
            "output_observed": True,
            "log_identity": log_identity(self.output),
            "state": "succeeded",
            "exit_code": 0,
        }
        with patch.object(qlib_script_api.TaskManager, "list", return_value=[task]):
            result = self.client.get(f"/api/qlib-script/experiments/{self.source_id}").get_json()
            self.assertEqual(result["management_mode"], "managed")
            self.log.write_text(terminal("failed"))
            result = self.client.get(f"/api/qlib-script/experiments/{self.source_id}").get_json()
            self.assertEqual(result["management_mode"], "external")
            self.assertEqual(result["execution_state"], "failed")
            self.assertNotIn("exit_conflict", result)

    def test_managed_exit_conflict_and_invalid_terminal_are_visible(self):
        from rdagent.log.server import qlib_script_api

        self.append(terminal())
        task = {
            "id": "d" * 32,
            "output_dir": str(self.output),
            "output_observed": True,
            "log_identity": log_identity(self.output),
            "state": "failed",
            "exit_code": 2,
        }
        with patch.object(qlib_script_api.TaskManager, "list", return_value=[task]):
            result = self.client.get(f"/api/qlib-script/experiments/{self.source_id}").get_json()
            self.assertTrue(result["exit_conflict"])
            self.assertEqual(result["execution_state"], "failed")
            self.log.write_text("QRUN_RESULT invalid\n")
            task.update(log_identity=log_identity(self.output), state="succeeded", exit_code=0)
            result = self.client.get(f"/api/qlib-script/experiments/{self.source_id}").get_json()
            self.assertEqual(result["execution_state"], "unknown")
            self.assertTrue(result["errors"])


class SupervisorTests(unittest.TestCase):
    def test_created_call_continues_writing_without_the_original_manager(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            script = base / "tools/qrun/train_run.py"
            script.parent.mkdir(parents=True)
            script.write_text(
                "import json,sys,time\nfrom pathlib import Path\n"
                "args=dict(arg[2:].split('=',1) for arg in sys.argv[1:])\n"
                "out=Path(args['out-dir'])/args['rolling-exp-name']\n"
                "out.mkdir(parents=True,exist_ok=True)\n"
                "log=out/'rolling.log'\n"
                "log.write_text('训练窗口 9/9\\n')\n"
                "print('[info] 输出目录: '+str(out),flush=True)\n"
                "time.sleep(0.5)\n"
                f"payload={{'status':'failed','stage':'analyze','exit_code':3,'run_id':{RID!r},'experiment_id':'101'}}\n"
                "with log.open('a') as stream:\n"
                f" stream.write('窗口 9/9 训练完成 (run_id={WINDOW})\\n')\n"
                " stream.write('QRUN_RESULT '+json.dumps(payload)+'\\n')\n"
                "print('fixture failure diagnostic',flush=True)\n"
                "sys.exit(3)\n"
            )
            with patch("rdagent.log.server.qlib_tasks.TRAIN_SCRIPT", script):
                manager = TaskManager(base / "tasks", base / "outputs")
                task = manager.create({"overrides": [{"name": "rolling-exp-name", "value": "example"}]})
                worker = manager._children[0]
            try:
                restarted = TaskManager(base / "tasks", base / "outputs")
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    result = restarted.get(task["id"])
                    if result["state"] not in {"pending", "running"}:
                        break
                    time.sleep(0.05)
                worker.wait(timeout=5)
                self.assertEqual((result["state"], result["exit_code"]), ("failed", 3))
                self.assertIn("fixture failure diagnostic", result["error"])
                self.assertEqual(result["log_identity"], log_identity(result["output_dir"]))
                recovered = ExperimentReader(base / "outputs").list()[0]
                self.assertEqual(recovered["execution_state"], "failed")
                self.assertEqual(recovered["progress"]["completed_windows"], 1)
                self.assertEqual(recovered["terminal"]["stage"], "analyze")
                self.assertEqual([p.name for p in Path(result["output_dir"]).iterdir()], ["rolling.log"])
                self.assertEqual(len(restarted.list()), 1)
            finally:
                if worker.poll() is None:
                    restarted.stop(task["id"])
                    worker.wait(timeout=15)

    def test_detached_worker_survives_manager_recreation_and_stops_children(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task_id = "d" * 32
            folder = base / task_id
            folder.mkdir()
            pid_file = base / "grandchild.pid"
            script = base / "fixture.py"
            script.write_text(
                "import subprocess,sys,time\n"
                "from pathlib import Path\n"
                'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"])\n'
                f"Path({str(pid_file)!r}).write_text(str(child.pid))\n"
                'print("fixture started",flush=True)\n'
                "time.sleep(60)\n"
            )
            (folder / "request.json").write_text(
                json.dumps(
                    {
                        "id": task_id,
                        "argv": [sys.executable, str(script)],
                        "created_timestamp": time.time(),
                        "output_dir": str(base / "source"),
                    }
                )
            )
            (folder / "runtime.json").write_text('{"state":"pending"}')
            worker = subprocess.Popen(
                [sys.executable, "-m", "rdagent.log.server.qlib_tasks", str(folder)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            try:
                deadline = time.monotonic() + 12
                while not pid_file.exists() and time.monotonic() < deadline:
                    if worker.poll() is not None:
                        self.fail(worker.stderr.read().decode())
                    time.sleep(0.05)
                self.assertTrue(pid_file.exists())
                restarted = TaskManager(base, base / "outputs")
                self.assertEqual(restarted.get(task_id)["state"], "running")
                restarted.stop(task_id)
                self.assertEqual(worker.wait(timeout=15), 0)
                self.assertEqual(TaskManager(base, base / "outputs").get(task_id)["state"], "cancelled")
                self.assertIsNone(process_identity(int(pid_file.read_text())))
            finally:
                if worker.poll() is None:
                    worker.terminate()
                    worker.wait(timeout=5)
                worker.stderr.close()


class WebRestartTests(FilesTestCase):
    def test_web_exit_does_not_stop_train_and_fresh_service_recovers_without_tasks(self):
        entry = self.base / "entry/tools/qrun/train_run.py"
        entry.parent.mkdir(parents=True)
        release = self.base / "release"
        entry.write_text(
            "import time\nfrom pathlib import Path\n"
            f"log=Path({str(self.log)!r})\n"
            "log.write_text('训练窗口 9/9\\n')\n"
            f"print('[info] 输出目录: '+{str(self.output)!r},flush=True)\n"
            f"while not Path({str(release)!r}).exists(): time.sleep(0.02)\n"
            f"with log.open('a') as stream: stream.write({f'窗口 9/9 训练完成 (run_id={WINDOW})' + chr(10) + terminal('failed', exit_code=3)!r})\n"
            "raise SystemExit(3)\n"
        )
        processes = []

        def start_web(label):
            ready = self.base / f"{label}.port"
            trace = self.base / label
            code = (
                "from pathlib import Path\n"
                "from werkzeug.serving import make_server\n"
                "from rdagent.log.server import app as server, qlib_tasks\n"
                f"qlib_tasks.TRAIN_SCRIPT=Path({str(entry)!r})\n"
                f"server.UI_SETTING.trace_folder={str(trace)!r}\n"
                "web=make_server('127.0.0.1',0,server.app,threaded=True)\n"
                f"Path({str(ready)!r}).write_text(str(web.server_port))\n"
                "web.serve_forever()\n"
            )
            process = subprocess.Popen(
                [sys.executable, "-c", code],
                env={**os.environ, "UI_TRAIN_DATA_DIR": str(self.root)},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            processes.append(process)
            deadline = time.monotonic() + 15
            while not ready.exists() and time.monotonic() < deadline:
                self.assertIsNone(process.poll(), "Fixture Web service exited during startup")
                time.sleep(0.05)
            self.assertTrue(ready.exists())
            return process, f"http://127.0.0.1:{ready.read_text()}/api/qlib-script", trace

        def fetch(url, body=None):
            request = Request(
                url,
                data=json.dumps(body).encode() if body is not None else None,
                headers={"Content-Type": "application/json"},
            )
            with urlopen(request, timeout=10) as response:
                return json.load(response)

        try:
            web, url, trace = start_web("original-web")
            task = fetch(url + "/tasks", {"overrides": [{"name": "rolling-exp-name", "value": "example"}]})
            manager = TaskManager(trace / ".qlib-script-tasks", self.root)
            deadline = time.monotonic() + 10
            while not manager.get(task["id"]).get("output_observed") and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(manager.get(task["id"]).get("output_observed"))
            web.terminate()
            web.wait(timeout=5)
            self.assertEqual(manager.get(task["id"])["state"], "running")
            release.touch()
            deadline = time.monotonic() + 10
            while manager.get(task["id"])["state"] == "running" and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertEqual(manager.get(task["id"])["exit_code"], 3)
            _, fresh_url, _ = start_web("fresh-web-without-task-records")
            self.assertEqual(fetch(fresh_url + "/tasks")["tasks"], [])
            result = fetch(fresh_url + "/experiments/" + self.source_id)
            self.assertEqual(result["management_mode"], "external")
            self.assertEqual((result["execution_state"], result["result_state"]), ("failed", "ready"))
            self.assertEqual(result["progress"]["completed_windows"], 1)
            self.assertEqual(result["terminal"]["exit_code"], 3)
        finally:
            release.touch()
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
