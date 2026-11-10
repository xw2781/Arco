from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path


_TESTS_DIR = Path(__file__).resolve().parent
_TMP_ROOT = _TESTS_DIR / "logs" / "tmp"
_MIGRATION_ROOT = _TESTS_DIR.parent / "migration"
if str(_MIGRATION_ROOT) not in sys.path:
    sys.path.insert(0, str(_MIGRATION_ROOT))

from resq_migration import engine  # noqa: E402


class ResqEngineRequestQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        _TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=str(_TMP_ROOT))
        self.root = Path(self.tmp.name) / "Arco Server"
        self.requests_dir = self.root / "requests"
        self.instances_dir = (
            self.root / "runtime" / "instances" / "arcrho_engine"
        )
        self.target = (
            self.root
            / "projects"
            / "Demo"
            / "data"
            / "Auto_%5C_PP"
            / "datasets"
            / "Paid Loss@12@12@cum@dev.csv"
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_heartbeat(self, name: str = "worker.json") -> Path:
        self.instances_dir.mkdir(parents=True, exist_ok=True)
        heartbeat = self.instances_dir / name
        heartbeat.write_text(
            json.dumps({"Server": name, "Last seen": "2026-07-24 12:00:00"}),
            encoding="utf-8",
        )
        return heartbeat

    def test_discovers_only_fresh_engine_heartbeats(self) -> None:
        fresh = self._write_heartbeat("fresh.json")
        stale = self._write_heartbeat("stale.json")
        now = time.time()
        os.utime(fresh, (now - 5, now - 5))
        os.utime(stale, (now - 61, now - 61))

        found = engine.discover_fresh_engine_heartbeats(
            self.root,
            max_age_sec=60,
            now=now,
        )

        self.assertEqual(found, (fresh,))

    def test_missing_fresh_worker_raises_engine_unavailable(self) -> None:
        with self.assertRaises(engine.EngineUnavailableError):
            engine.require_engine_workers(self.root)
        self.assertFalse(self.requests_dir.exists())

    def test_jobs_use_unique_staging_outputs_and_complete_request_payload(self) -> None:
        first = engine.create_engine_request_job(
            project_name="Demo",
            rc_path=r"Auto\PP",
            dataset_type="Paid Loss",
            data_path=self.target,
            origin_length=12,
            development_length=12,
            is_vector=False,
            server_root=self.root,
            user_name="tester",
        )
        second = engine.create_engine_request_job(
            project_name="Demo",
            rc_path=r"Auto\PP",
            dataset_type="Paid Loss",
            data_path=self.target,
            origin_length=12,
            development_length=12,
            is_vector=False,
            server_root=self.root,
            user_name="tester",
        )

        self.assertNotEqual(first.request_id, second.request_id)
        self.assertNotEqual(first.output_path, second.output_path)
        self.assertEqual(first.target_path, self.target.resolve())
        self.assertNotEqual(first.payload["DataPath"], str(first.target_path))
        self.assertEqual(first.payload["DataPath"], str(first.output_path))
        self.assertEqual(first.payload["StatusPath"], str(first.status_path))
        self.assertEqual(first.payload["RequestId"], first.request_id)
        self.assertEqual(first.payload["Function"], "ArcRhoTri")
        self.assertFalse(first.payload["Transposed"])
        self.assertEqual(first.payload["UserName"], "tester")

    def test_publish_is_atomic_and_targets_staging_output(self) -> None:
        self._write_heartbeat()
        job = engine.create_engine_request_job(
            project_name="Demo",
            rc_path=r"Auto\PP",
            dataset_type="Generated Premium",
            data_path=self.target,
            origin_length=6,
            development_length=6,
            is_vector=True,
            server_root=self.root,
            user_name="tester",
        )

        published = engine.publish_engine_request(job)
        payload = json.loads(published.read_text(encoding="utf-8"))

        self.assertTrue(published.is_file())
        self.assertFalse(job.request_temp_path.exists())
        self.assertEqual(payload["Function"], "ArcRhoVec")
        self.assertEqual(payload["DataPath"], str(job.output_path))
        self.assertFalse(self.target.exists())
        engine.cleanup_engine_request_job(job)

    def test_wait_and_finalize_replace_canonical_only_after_completion(self) -> None:
        job = engine.create_engine_request_job(
            project_name="Demo",
            rc_path=r"Auto\PP",
            dataset_type="Paid Loss",
            data_path=self.target,
            origin_length=12,
            development_length=12,
            is_vector=False,
            server_root=self.root,
        )
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.target.write_text("old\n", encoding="utf-8")

        def complete_request() -> None:
            time.sleep(0.05)
            job.output_path.parent.mkdir(parents=True, exist_ok=True)
            worker_temp = job.output_path.with_suffix(".worker.tmp")
            worker_temp.write_text("new\n", encoding="utf-8")
            os.replace(worker_temp, job.output_path)

        worker = threading.Thread(target=complete_request)
        polls = []
        worker.start()
        try:
            engine.wait_for_engine_request(
                job,
                timeout_sec=1,
                poll_interval_sec=0.01,
                on_poll=lambda: polls.append(time.monotonic()),
            )
            self.assertEqual(self.target.read_text(encoding="utf-8"), "old\n")
            finalized = engine.finalize_engine_request(job)
        finally:
            worker.join(timeout=1)

        self.assertEqual(finalized, self.target.resolve())
        self.assertEqual(self.target.read_text(encoding="utf-8"), "new\n")
        self.assertFalse(job.output_path.exists())
        self.assertGreater(len(polls), 0)

    def test_status_aware_worker_requires_success_before_accepting_output(self) -> None:
        job = engine.create_engine_request_job(
            project_name="Demo",
            rc_path=r"Auto\PP",
            dataset_type="Paid Loss",
            data_path=self.target,
            origin_length=12,
            development_length=12,
            is_vector=False,
            server_root=self.root,
        )
        job.output_path.parent.mkdir(parents=True, exist_ok=True)
        job.status_path.write_text(
            json.dumps({"request_id": job.request_id, "status": "processing"}),
            encoding="utf-8",
        )
        job.output_path.write_text("not-final-yet\n", encoding="utf-8")

        def finish_status() -> None:
            time.sleep(0.05)
            temp_status = job.status_path.with_suffix(".tmp")
            temp_status.write_text(
                json.dumps({"request_id": job.request_id, "status": "success"}),
                encoding="utf-8",
            )
            os.replace(temp_status, job.status_path)

        worker = threading.Thread(target=finish_status)
        worker.start()
        started = time.monotonic()
        try:
            completed = engine.wait_for_engine_request(
                job,
                timeout_sec=1,
                poll_interval_sec=0.01,
            )
        finally:
            worker.join(timeout=1)

        self.assertEqual(completed, job.output_path)
        self.assertGreaterEqual(time.monotonic() - started, 0.04)
        engine.cleanup_engine_request_job(job)

    def test_status_aware_worker_error_is_not_finalized(self) -> None:
        job = engine.create_engine_request_job(
            project_name="Demo",
            rc_path=r"Auto\PP",
            dataset_type="Paid Loss",
            data_path=self.target,
            origin_length=12,
            development_length=12,
            is_vector=False,
            server_root=self.root,
        )
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.target.write_text("keep\n", encoding="utf-8")
        job.output_path.parent.mkdir(parents=True, exist_ok=True)
        job.output_path.write_text("(error)\n", encoding="utf-8")
        job.status_path.write_text(
            json.dumps({
                "request_id": job.request_id,
                "status": "error",
                "message": "configuration failed",
            }),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(engine.EngineGenerationError, "configuration failed"):
            engine.wait_for_engine_request(
                job,
                timeout_sec=1,
                poll_interval_sec=0.01,
            )

        self.assertEqual(self.target.read_text(encoding="utf-8"), "keep\n")
        engine.cleanup_engine_request_job(job)

    def test_legacy_worker_recognizable_error_csv_is_not_finalized(self) -> None:
        job = engine.create_engine_request_job(
            project_name="Demo",
            rc_path=r"Auto\PP",
            dataset_type="Paid Loss",
            data_path=self.target,
            origin_length=12,
            development_length=12,
            is_vector=False,
            server_root=self.root,
        )
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.target.write_text("keep\n", encoding="utf-8")
        job.output_path.parent.mkdir(parents=True, exist_ok=True)
        job.output_path.write_text(
            '"(data processing configuration error: missing rules)"\n',
            encoding="utf-8",
        )

        with self.assertRaisesRegex(engine.EngineGenerationError, "missing rules"):
            engine.wait_for_engine_request(
                job,
                timeout_sec=1,
                poll_interval_sec=0.01,
            )

        self.assertEqual(self.target.read_text(encoding="utf-8"), "keep\n")
        engine.cleanup_engine_request_job(job)

    def test_generate_engine_csv_uses_worker_request_end_to_end(self) -> None:
        self._write_heartbeat()
        stop = threading.Event()
        observed_payload: dict = {}

        def worker() -> None:
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not stop.is_set():
                requests = tuple(self.requests_dir.glob("*.json"))
                if requests:
                    request_path = requests[0]
                    observed_payload.update(
                        json.loads(request_path.read_text(encoding="utf-8"))
                    )
                    request_path.unlink()
                    output = Path(observed_payload["DataPath"])
                    output.parent.mkdir(parents=True, exist_ok=True)
                    worker_temp = output.with_suffix(".worker.tmp")
                    worker_temp.write_text("1,2\n3,4\n", encoding="utf-8")
                    os.replace(worker_temp, output)
                    return
                time.sleep(0.01)

        worker_thread = threading.Thread(target=worker)
        worker_thread.start()
        try:
            engine.generate_engine_csv(
                project_name="Demo",
                rc_path=r"Auto\PP",
                dataset_type="Paid Loss",
                data_path=self.target,
                origin_length=12,
                development_length=12,
                is_vector=False,
                server_root=self.root,
                timeout_sec=1,
                poll_interval_sec=0.01,
            )
        finally:
            stop.set()
            worker_thread.join(timeout=1)

        self.assertEqual(self.target.read_text(encoding="utf-8"), "1,2\n3,4\n")
        self.assertEqual(observed_payload["ProjectName"], "Demo")
        self.assertEqual(observed_payload["Path"], r"Auto\PP")
        self.assertNotEqual(observed_payload["DataPath"], str(self.target))
        self.assertEqual(tuple(self.requests_dir.glob("*.tmp")), ())

    def test_timeout_cleanup_preserves_existing_canonical_cache(self) -> None:
        self._write_heartbeat()
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.target.write_text("keep\n", encoding="utf-8")

        with self.assertRaises(engine.EngineGenerationError):
            engine.generate_engine_csv(
                project_name="Demo",
                rc_path=r"Auto\PP",
                dataset_type="Paid Loss",
                data_path=self.target,
                origin_length=12,
                development_length=12,
                is_vector=False,
                server_root=self.root,
                timeout_sec=0.05,
                poll_interval_sec=0.01,
            )

        self.assertEqual(self.target.read_text(encoding="utf-8"), "keep\n")
        self.assertEqual(tuple(self.requests_dir.glob("*.json")), ())


if __name__ == "__main__":
    unittest.main()
