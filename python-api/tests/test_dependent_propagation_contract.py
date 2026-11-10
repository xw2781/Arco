from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path


_TESTS_DIR = Path(__file__).resolve().parent
_TMP_ROOT = _TESTS_DIR / "logs" / "tmp"
_SRC_ROOT = _TESTS_DIR.parent / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

import arcrho_dependent_propagation_contract as contract  # noqa: E402
from arcrho_engine_job_lease import (  # noqa: E402
    acquire_engine_job_lease,
    engine_job_lease_is_owned,
    refresh_engine_job_lease,
    release_engine_job_lease,
)


def _valid_request(**overrides):
    payload = {
        "Function": "ArcRhoRefreshDependents",
        "ContractVersion": 1,
        "RequestId": "0123456789abcdef0123456789abcdef",
        "ProjectName": "NJ_Annual_Prod_202605",
        "Path": "HPPREF\\HO+DF\\NJ\\Legacy\\HOL",
        "ChangedRoots": [
            {"dataset_name": "Paid Loss DFM Output", "dataset_type": "Ultimate Loss"}
        ],
        "UserName": "tester",
    }
    payload.update(overrides)
    return payload


class DependentPropagationRequestContractTests(unittest.TestCase):
    def test_build_returns_the_exact_normalized_payload(self) -> None:
        request = contract.build_dependent_propagation_request(
            request_id="job-1",
            project_name=" Demo Project ",
            path="HPPREF/HO+DF\\NJ",
            changed_roots=[
                {"dataset_name": " Paid ", "dataset_type": " Paid Loss "},
                {"dataset_name": "paid", "dataset_type": "paid loss"},
                {"dataset_name": "Ultimate"},
            ],
            user_name=" tester ",
        )
        self.assertEqual(
            request,
            {
                "Function": "ArcRhoRefreshDependents",
                "ContractVersion": 1,
                "RequestId": "job-1",
                "ProjectName": "Demo Project",
                "Path": "HPPREF\\HO+DF\\NJ",
                "ChangedRoots": [
                    {"dataset_name": "Paid", "dataset_type": "Paid Loss"},
                    {"dataset_name": "Ultimate", "dataset_type": ""},
                ],
                "UserName": "tester",
            },
        )

    def test_extra_fields_including_machine_paths_are_rejected(self) -> None:
        for extra_field in ("DataPath", "StatusPath", "ServerRoot", "Extra"):
            with self.subTest(extra_field=extra_field):
                payload = _valid_request(**{extra_field: r"E:\Arco Server"})
                with self.assertRaises(
                    contract.DependentPropagationContractError
                ) as raised:
                    contract.validate_dependent_propagation_request(payload)
                self.assertIn(extra_field, str(raised.exception))

    def test_missing_fields_are_rejected(self) -> None:
        for missing in contract.DEPENDENT_PROPAGATION_REQUIRED_FIELDS:
            with self.subTest(missing=missing):
                payload = _valid_request()
                del payload[missing]
                with self.assertRaises(contract.DependentPropagationContractError):
                    contract.validate_dependent_propagation_request(payload)

    def test_path_rejects_machine_local_forms(self) -> None:
        for bad_path in (
            r"E:\Arco Server\projects",
            r"\\server\share\projects",
            "//server/share",
            "..\\HOL",
            "HPPREF\\..\\HOL",
            "",
            "   ",
        ):
            with self.subTest(path=bad_path):
                with self.assertRaises(contract.DependentPropagationContractError):
                    contract.validate_reserving_class_path(bad_path)

    def test_path_normalizes_separators_and_blank_segments(self) -> None:
        self.assertEqual(
            contract.validate_reserving_class_path("HPPREF/HO+DF//NJ\\ Legacy "),
            "HPPREF\\HO+DF\\NJ\\Legacy",
        )

    def test_changed_roots_require_dataset_name_and_reject_extras(self) -> None:
        with self.assertRaises(contract.DependentPropagationContractError):
            contract.normalize_changed_roots([])
        with self.assertRaises(contract.DependentPropagationContractError):
            contract.normalize_changed_roots([{"dataset_type": "Paid"}])
        with self.assertRaises(contract.DependentPropagationContractError):
            contract.normalize_changed_roots(
                [{"dataset_name": "Paid", "csv_path": "C:/x.csv"}]
            )

    def test_merge_changed_roots_deduplicates_case_insensitively(self) -> None:
        merged = contract.merge_changed_roots(
            [{"dataset_name": "Paid", "dataset_type": "Paid Loss"}],
            [
                {"dataset_name": "PAID", "dataset_type": "PAID LOSS"},
                {"dataset_name": "Incurred", "dataset_type": ""},
            ],
        )
        self.assertEqual(
            merged,
            [
                {"dataset_name": "Paid", "dataset_type": "Paid Loss"},
                {"dataset_name": "Incurred", "dataset_type": ""},
            ],
        )

    def test_request_json_is_location_independent(self) -> None:
        request = contract.validate_dependent_propagation_request(_valid_request())
        text = json.dumps(request)
        self.assertNotIn(":\\", text.replace("\\\\", "\\").replace("HPPREF", ""))
        self.assertNotIn("E:", text)


class DependentPropagationStatusContractTests(unittest.TestCase):
    REQUEST_ID = "0123456789abcdef0123456789abcdef"

    def _progress(self):
        return {"stage": "dfm", "completed": 1, "total": 4, "label": "Paid DFM"}

    def test_status_roundtrip_with_message_and_merged_into(self) -> None:
        payload = contract.build_dependent_propagation_status(
            self.REQUEST_ID,
            "error",
            progress=self._progress(),
            message="walk failed",
            merged_into="merged-run-id",
        )
        validated = contract.validate_dependent_propagation_status(
            payload, expected_request_id=self.REQUEST_ID
        )
        self.assertEqual(validated["status"], "error")
        self.assertEqual(validated["message"], "walk failed")
        self.assertEqual(validated["merged_into"], "merged-run-id")
        self.assertEqual(validated["progress"], self._progress())

    def test_invalid_status_values_are_rejected(self) -> None:
        for status in ("done", "", None, "SUCCESS "):
            with self.subTest(status=status):
                with self.assertRaises(contract.DependentPropagationContractError):
                    contract.build_dependent_propagation_status(
                        self.REQUEST_ID, status, progress=self._progress()
                    )

    def test_status_reader_rejects_extra_fields_and_mismatched_ids(self) -> None:
        payload = contract.build_dependent_propagation_status(
            self.REQUEST_ID, "queued", progress=self._progress()
        )
        with self.assertRaises(contract.DependentPropagationContractError):
            contract.validate_dependent_propagation_status(
                {**payload, "server_root": "E:/Arco Server"}
            )
        with self.assertRaises(contract.DependentPropagationContractError):
            contract.validate_dependent_propagation_status(
                payload, expected_request_id="another-job"
            )

    def test_write_status_targets_the_canonical_statuses_folder(self) -> None:
        _TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(_TMP_ROOT)) as temp_dir:
            root = Path(temp_dir)
            written = contract.write_dependent_propagation_status(
                root,
                self.REQUEST_ID,
                "queued",
                progress=self._progress(),
            )
            self.assertEqual(
                written,
                root
                / "requests"
                / "dependent_propagation"
                / "statuses"
                / f"{self.REQUEST_ID}.json",
            )
            persisted = json.loads(written.read_text(encoding="utf-8"))
            self.assertEqual(persisted["status"], "queued")
            self.assertNotIn(str(root), json.dumps(persisted))


class ReservingClassLeaseTests(unittest.TestCase):
    def setUp(self) -> None:
        _TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=str(_TMP_ROOT))
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_lock_path_is_stable_across_case_and_separator_aliases(self) -> None:
        first = contract.dependent_propagation_lock_path(
            self.root, "Demo", "HPPREF\\HO+DF\\NJ"
        )
        second = contract.dependent_propagation_lock_path(
            self.root, "demo", "hppref/ho+df/nj"
        )
        self.assertEqual(first, second)
        self.assertTrue(first.name.endswith(".lock"))

    def test_acquire_blocks_second_owner_until_stale_takeover(self) -> None:
        first = contract.acquire_reserving_class_lease(self.root, "Demo", "A\\B")
        self.assertIsNotNone(first)
        self.assertTrue(engine_job_lease_is_owned(first))

        blocked = contract.acquire_reserving_class_lease(self.root, "Demo", "A\\B")
        self.assertIsNone(blocked)

        # A renewed lease stays fresh; an abandoned one is recoverable.
        self.assertTrue(refresh_engine_job_lease(first))
        stale_moment = time.time() - (
            contract.DEPENDENT_PROPAGATION_LEASE_STALE_SECONDS + 5
        )
        os.utime(first.path, (stale_moment, stale_moment))
        replacement = contract.acquire_reserving_class_lease(self.root, "Demo", "A\\B")
        self.assertIsNotNone(replacement)
        self.assertFalse(engine_job_lease_is_owned(first))
        self.assertFalse(refresh_engine_job_lease(first))

        release_engine_job_lease(first)
        self.assertTrue(replacement.path.exists())
        contract.release_reserving_class_lease(replacement)
        self.assertFalse(replacement.path.exists())

    def test_held_lease_context_manager_acquires_renews_and_releases(self) -> None:
        with contract.held_reserving_class_lease(
            self.root, "Demo", "A\\B", timeout_seconds=1.0, poll_seconds=0.05
        ) as lease:
            self.assertTrue(lease.path.exists())
            payload = json.loads(lease.path.read_text(encoding="utf-8"))
            self.assertEqual(payload["project_name"], "Demo")
            self.assertEqual(payload["path"], "A\\B")
        self.assertFalse(lease.path.exists())

    def test_held_lease_times_out_when_the_class_is_locked(self) -> None:
        holder = contract.acquire_reserving_class_lease(self.root, "Demo", "A\\B")
        self.assertIsNotNone(holder)
        try:
            started = time.monotonic()
            with self.assertRaises(contract.DependentPropagationLeaseUnavailable):
                with contract.held_reserving_class_lease(
                    self.root,
                    "Demo",
                    "A\\B",
                    timeout_seconds=0.2,
                    poll_seconds=0.05,
                ):
                    pass
            self.assertLess(time.monotonic() - started, 5.0)
        finally:
            contract.release_reserving_class_lease(holder)


class ReservingClassPropagationHoldTests(unittest.TestCase):
    PROJECT = "Demo"
    PATH = "A\\B"

    def setUp(self) -> None:
        _TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=str(_TMP_ROOT))
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _probe(self):
        return contract.find_reserving_class_propagation_hold(
            self.root, self.PROJECT, self.PATH
        )

    def _write_queued_request(self, request_id: str, path: str = PATH) -> Path:
        request = contract.build_dependent_propagation_request(
            request_id=request_id,
            project_name=self.PROJECT,
            path=path,
            changed_roots=[{"dataset_name": "Paid", "dataset_type": "Paid Loss"}],
            user_name="tester",
        )
        request_path = contract.dependent_propagation_request_path(
            self.root, request_id
        )
        request_path.parent.mkdir(parents=True, exist_ok=True)
        return contract.write_json_atomic(request_path, request)

    def test_an_idle_class_reports_no_hold(self) -> None:
        self.assertIsNone(self._probe())

    def test_a_fresh_lease_holds_the_class_until_its_heartbeat_goes_stale(self) -> None:
        lease = contract.acquire_reserving_class_lease(
            self.root, self.PROJECT, self.PATH
        )
        self.assertIsNotNone(lease)
        try:
            self.assertEqual(self._probe(), {"reason": "processing"})
            dead_moment = time.time() - (
                contract.DEPENDENT_PROPAGATION_STATUS_STALE_SECONDS + 5
            )
            os.utime(lease.path, (dead_moment, dead_moment))
            self.assertIsNone(self._probe())
        finally:
            contract.release_reserving_class_lease(lease)
        self.assertIsNone(self._probe())

    def test_a_queued_request_holds_the_class_until_terminal_or_abandoned(self) -> None:
        request_id = "1111111111111111aaaaaaaaaaaaaaaa"
        request_path = self._write_queued_request(request_id)
        self.assertEqual(self._probe(), {"reason": "queued"})

        contract.write_dependent_propagation_status(
            self.root,
            request_id,
            "success",
            progress={
                "stage": "complete",
                "completed": 1,
                "total": 1,
                "label": "Dependent updates complete",
            },
        )
        self.assertIsNone(self._probe())

        abandoned_id = "2222222222222222bbbbbbbbbbbbbbbb"
        abandoned_path = self._write_queued_request(abandoned_id)
        old_moment = time.time() - (
            contract.DEPENDENT_PROPAGATION_QUEUED_STALE_SECONDS + 5
        )
        os.utime(abandoned_path, (old_moment, old_moment))
        self.assertIsNone(self._probe())
        self.assertTrue(request_path.exists())

    def test_a_queued_request_for_another_class_does_not_hold_this_one(self) -> None:
        self._write_queued_request("3333333333333333cccccccccccccccc", path="Other\\Class")
        self.assertIsNone(self._probe())


class EngineHeartbeatPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        _TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=str(_TMP_ROOT))
        self.root = Path(self.temp.name)
        self.instances = self.root / "runtime" / "instances" / "arcrho_engine"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_heartbeat(self, name: str, age_seconds: float) -> Path:
        self.instances.mkdir(parents=True, exist_ok=True)
        heartbeat = self.instances / name
        heartbeat.write_text(
            json.dumps({"Server": name, "Last seen": "2026-08-06 12:00:00"}),
            encoding="utf-8",
        )
        stamp = time.time() - age_seconds
        os.utime(heartbeat, (stamp, stamp))
        return heartbeat

    def test_discovers_only_fresh_heartbeats(self) -> None:
        fresh = self._write_heartbeat("fresh.json", 5)
        self._write_heartbeat("stale.json", 61)
        found = contract.discover_fresh_engine_heartbeats(self.root)
        self.assertEqual(found, (fresh,))

    def test_require_live_engine_raises_the_user_facing_message(self) -> None:
        with self.assertRaises(contract.EngineUnavailableError) as raised:
            contract.require_live_engine(self.root)
        self.assertEqual(
            str(raised.exception), contract.ENGINE_UNAVAILABLE_MESSAGE
        )
        self._write_heartbeat("fresh.json", 1)
        self.assertTrue(contract.require_live_engine(self.root))


class SharedLeasePrimitiveTests(unittest.TestCase):
    def setUp(self) -> None:
        _TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=str(_TMP_ROOT))
        self.path = Path(self.temp.name) / "job.lock"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_payload_fields_precede_generated_ownership_fields(self) -> None:
        lease = acquire_engine_job_lease(
            self.path, stale_seconds=300, payload_fields={"request_id": "abc"}
        )
        self.assertIsNotNone(lease)
        persisted = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(
            list(persisted), ["request_id", "owner_token", "created_at"]
        )
        self.assertEqual(persisted["owner_token"], lease.owner_token)
        release_engine_job_lease(lease)

    def test_release_leaves_a_lease_whose_heartbeat_failed(self) -> None:
        lease = acquire_engine_job_lease(self.path, stale_seconds=300)
        lease.heartbeat_failed.set()
        release_engine_job_lease(lease)
        self.assertTrue(self.path.exists())


if __name__ == "__main__":
    unittest.main()
