from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException


FRONTEND_ROOT = Path(__file__).resolve().parents[1]
if str(FRONTEND_ROOT) not in sys.path:
    sys.path.insert(0, str(FRONTEND_ROOT))

from app_server import config
from app_server.services import dataset_instance_index_service
from arcrho_api.dataset_index_contract import (
    canonicalize_index_row,
    scan_folder_signature,
)


def _folder_paths_for(rc_dir: Path) -> dict[str, str]:
    return {
        "data": str(rc_dir),
        "datasets": str(rc_dir / config.DATASET_CACHE_DIR),
        "methods": str(rc_dir / config.METHOD_DATA_DIR),
        "sidecars": str(rc_dir / config.DATASET_SIDECAR_DIR),
    }


class DatasetInstanceIndexMetadataTests(unittest.TestCase):
    def test_delete_resolution_overlaps_method_payload_reads(self) -> None:
        with tempfile.TemporaryDirectory(dir=str(FRONTEND_ROOT)) as temp_dir:
            data_root = Path(temp_dir)
            folder_paths = _folder_paths_for(data_root)
            for directory in folder_paths.values():
                Path(directory).mkdir(exist_ok=True)
            for index in range(8):
                Path(folder_paths["methods"], f"DFM@Method {index}.json").write_text("{}", encoding="utf-8")

            active = 0
            max_active = 0
            activity_lock = threading.Lock()

            def slow_metadata_read(path: str):
                nonlocal active, max_active
                with activity_lock:
                    active += 1
                    max_active = max(max_active, active)
                time.sleep(0.02)
                with activity_lock:
                    active -= 1
                return {"details_tab": {"output_dataset": "Paid Ultimate"}}

            with mock.patch.object(
                dataset_instance_index_service,
                "_safe_read_json",
                side_effect=slow_metadata_read,
            ):
                targets, matched = dataset_instance_index_service._cached_delete_targets(
                    folder_paths,
                    {"paid ultimate"},
                    read_sidecar_payloads=False,
                )

        self.assertEqual(len(targets), 8)
        self.assertEqual(matched, {"paid ultimate"})
        self.assertGreater(max_active, 1)

    def test_canonical_row_keeps_scalar_period_lengths(self) -> None:
        logical = canonicalize_index_row(
            {
                "name": "Paid Loss",
                "dataset_type": "Paid Loss",
                "origin_length": 12,
                "development_length": 36,
            }
        )

        self.assertEqual(logical["name"], "Paid Loss")
        self.assertEqual(logical["origin_length"], 12)
        self.assertEqual(logical["development_length"], 36)

    def _rebuild_patches(self, write_side_effect: OSError):
        folder_paths = {
            "data": r"E:\Arco Server\projects\Example\data\Paid",
            "datasets": r"E:\Arco Server\projects\Example\data\Paid\datasets",
            "methods": r"E:\Arco Server\projects\Example\data\Paid\methods",
            "sidecars": r"E:\Arco Server\projects\Example\data\Paid\sidecars",
        }
        payload = {
            "ok": True,
            "version": dataset_instance_index_service.INDEX_VERSION,
            "exists": True,
            "project_name": "Example",
            "reserving_class": "Paid",
            "folder_signature": "sha256:" + ("0" * 64),
            "files": [
                {
                    "name": "Paid Loss",
                    "dataset_type": "Paid Loss",
                    "method_type": "None",
                    "status": 0,
                    "last_modified": "",
                    "last_modified_timestamp": 0.0,
                    "created": "",
                    "created_timestamp": 0.0,
                    "user": "",
                },
            ],
        }
        return (
            mock.patch.object(dataset_instance_index_service, "_folder_paths", return_value=folder_paths),
            mock.patch.object(dataset_instance_index_service.os.path, "isdir", return_value=True),
            mock.patch.object(
                dataset_instance_index_service,
                "index_update_lock",
                return_value=threading.Lock(),
            ),
            mock.patch.object(
                dataset_instance_index_service,
                "build_dataset_index_payload",
                return_value=payload,
            ),
            mock.patch.object(dataset_instance_index_service, "index_rebuild_reason"),
            mock.patch.object(
                dataset_instance_index_service,
                "_write_index_file",
                side_effect=write_side_effect,
            ),
        )

    def test_get_index_returns_scanned_rows_when_index_write_fails(self) -> None:
        write_error = OSError(53, "The network path was not found")
        patches = self._rebuild_patches(write_error)

        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5] as write,
        ):
            result = dataset_instance_index_service.get_index("Example", "Paid", refresh=True)

        self.assertTrue(result["ok"])
        self.assertEqual([item["name"] for item in result["files"]], ["Paid Loss"])
        self.assertFalse(result["index_persisted"])
        self.assertEqual(result["folder_paths"], {
            "data": r"E:\Arco Server\projects\Example\data\Paid",
            "datasets": r"E:\Arco Server\projects\Example\data\Paid\datasets",
            "methods": r"E:\Arco Server\projects\Example\data\Paid\methods",
            "sidecars": r"E:\Arco Server\projects\Example\data\Paid\sidecars",
        })
        self.assertIn("Dataset table loaded from the dataset folder", result["index_warning"])
        self.assertIn("The network path was not found", result["index_warning"])
        written_payload = write.call_args.args[1]
        self.assertNotIn("index_persisted", written_payload)
        self.assertNotIn("index_warning", written_payload)

    def test_direct_rebuild_remains_strict_when_index_write_fails(self) -> None:
        write_error = OSError(53, "The network path was not found")
        patches = self._rebuild_patches(write_error)

        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
        ):
            with self.assertRaises(HTTPException) as raised:
                dataset_instance_index_service.rebuild_index("Example", "Paid")

        self.assertEqual(raised.exception.status_code, 500)
        self.assertIn("Failed to write dataset instance index", raised.exception.detail)

    def test_permission_failure_can_fall_back_only_for_read_path(self) -> None:
        write_error = PermissionError(13, "Access is denied")
        patches = self._rebuild_patches(write_error)

        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
        ):
            result = dataset_instance_index_service.get_index("Example", "Paid", refresh=True)

        self.assertFalse(result["index_persisted"])
        self.assertIn("Access is denied", result["index_warning"])

    def test_index_read_failure_does_not_trigger_a_folder_rebuild(self) -> None:
        read_error = HTTPException(500, "Failed to read dataset instance index: network unavailable")
        with (
            mock.patch.object(
                dataset_instance_index_service,
                "_folder_paths",
                return_value={
                    "data": "",
                    "datasets": "datasets",
                    "methods": "methods",
                    "sidecars": "sidecars",
                },
            ),
            mock.patch.object(
                dataset_instance_index_service,
                "_read_index_file",
                side_effect=read_error,
            ),
            mock.patch.object(
                dataset_instance_index_service,
                "rebuild_index",
                side_effect=AssertionError("an index read failure must not trigger a folder scan"),
            ) as rebuild,
        ):
            with self.assertRaises(HTTPException) as raised:
                dataset_instance_index_service.get_index("Example", "Paid")

        self.assertEqual(raised.exception.status_code, 500)
        rebuild.assert_not_called()

    def test_non_utf8_index_is_treated_as_invalid_and_rebuilt(self) -> None:
        with tempfile.TemporaryDirectory(dir=str(FRONTEND_ROOT)) as temp_dir:
            data_dir = Path(temp_dir)
            index_path = data_dir / "index.json"
            index_path.write_bytes(b"\xff\xfe\x00")
            folder_paths = {
                "data": str(data_dir),
                "datasets": str(data_dir / "datasets"),
                "methods": str(data_dir / "methods"),
                "sidecars": str(data_dir / "sidecars"),
            }
            rebuilt = {
                "ok": True,
                "project_name": "Example",
                "reserving_class": "Paid",
                "files": [],
            }
            with (
                mock.patch.object(
                    dataset_instance_index_service,
                    "_folder_paths",
                    return_value=folder_paths,
                ),
                mock.patch.object(
                    dataset_instance_index_service,
                    "rebuild_index",
                    return_value=rebuilt,
                ) as rebuild,
            ):
                result = dataset_instance_index_service.get_index("Example", "Paid")

        self.assertEqual(result, rebuilt)
        rebuild.assert_called_once()

    def test_current_index_reports_persisted_without_changing_saved_payload(self) -> None:
        with tempfile.TemporaryDirectory(dir=str(FRONTEND_ROOT)) as temp_dir:
            data_root = Path(temp_dir)
            (data_root / "datasets").mkdir()
            (data_root / "methods").mkdir()
            sidecar_dir = data_root / "sidecars"
            sidecar_dir.mkdir()
            (sidecar_dir / "Paid Loss.json").write_text(
                '{"dataset_name": "Paid Loss"}',
                encoding="utf-8",
            )

            saved_payload = {
                "ok": True,
                "version": dataset_instance_index_service.INDEX_VERSION,
                "exists": True,
                "project_name": "Example",
                "reserving_class": "Paid",
                # The signature must describe the folder as it is on disk, or the
                # read treats the index as stale and rebuilds it.
                "folder_signature": scan_folder_signature(data_root).signature,
                "files": [
                    {
                        "name": "Paid Loss",
                        "dataset_type": "Paid Loss",
                        "method_type": "None",
                        "status": 0,
                        "last_modified": "",
                        "last_modified_timestamp": 0.0,
                        "created": "",
                        "created_timestamp": 0.0,
                        "user": "",
                    },
                ],
            }
            folder_paths = {
                "data": str(data_root),
                "datasets": str(data_root / "datasets"),
                "methods": str(data_root / "methods"),
                "sidecars": str(sidecar_dir),
            }

            with (
                mock.patch.object(
                    dataset_instance_index_service,
                    "_folder_paths",
                    return_value=folder_paths,
                ),
                mock.patch.object(
                    dataset_instance_index_service,
                    "_read_index_file",
                    return_value=saved_payload,
                ),
                mock.patch.object(
                    dataset_instance_index_service,
                    "rebuild_index",
                    side_effect=AssertionError("a matching signature must not rebuild"),
                ),
            ):
                result = dataset_instance_index_service.get_index("Example", "Paid")

            self.assertTrue(result["index_persisted"])
            self.assertEqual(result["index_warning"], "")
            # The cheap path must say so, so a fast reload is distinguishable
            # from a slow one in the caller's own report.
            self.assertEqual(result["index_rebuild_reason"], "")
            self.assertFalse(result["index_rebuilt"])
            self.assertEqual(result["folder_paths"]["data"], str(data_root))
            self.assertNotIn("folder_paths", saved_payload)
            self.assertNotIn("index_persisted", saved_payload)
            self.assertNotIn("index_warning", saved_payload)
            self.assertNotIn("index_rebuild_reason", saved_payload)
            self.assertNotIn("index_rebuilt", saved_payload)
            self.assertNotIn("index_elapsed_ms", saved_payload)

    def test_a_changed_folder_makes_a_saved_index_stale(self) -> None:
        with tempfile.TemporaryDirectory(dir=str(FRONTEND_ROOT)) as temp_dir:
            data_root = Path(temp_dir)
            (data_root / "datasets").mkdir()
            (data_root / "methods").mkdir()
            sidecar_dir = data_root / "sidecars"
            sidecar_dir.mkdir()
            (sidecar_dir / "Paid Loss.json").write_text(
                '{"dataset_name": "Paid Loss"}',
                encoding="utf-8",
            )
            stale_signature = scan_folder_signature(data_root).signature

            (sidecar_dir / "Reported Loss.json").write_text(
                '{"dataset_name": "Reported Loss"}',
                encoding="utf-8",
            )

            saved_payload = {
                "ok": True,
                "version": dataset_instance_index_service.INDEX_VERSION,
                "exists": True,
                "project_name": "Example",
                "reserving_class": "Paid",
                "folder_signature": stale_signature,
                "files": [
                    {
                        "name": "Paid Loss",
                        "dataset_type": "Paid Loss",
                        "method_type": "None",
                        "status": 0,
                        "last_modified": "",
                        "last_modified_timestamp": 0.0,
                        "created": "",
                        "created_timestamp": 0.0,
                        "user": "",
                    },
                ],
            }
            folder_paths = {
                "data": str(data_root),
                "datasets": str(data_root / "datasets"),
                "methods": str(data_root / "methods"),
                "sidecars": str(sidecar_dir),
            }

            with (
                mock.patch.object(
                    dataset_instance_index_service,
                    "_folder_paths",
                    return_value=folder_paths,
                ),
                mock.patch.object(
                    dataset_instance_index_service,
                    "_read_index_file",
                    return_value=saved_payload,
                ),
            ):
                result = dataset_instance_index_service.get_index("Example", "Paid")

            self.assertEqual(
                [row["name"] for row in result["files"]],
                ["Paid Loss", "Reported Loss"],
            )
            # Naming the failed check is what turns an unexplained slow reload
            # into something diagnosable from the operator's own report.
            self.assertEqual(result["index_rebuild_reason"], "folder-signature-changed")
            self.assertTrue(result["index_rebuilt"])
            self.assertGreaterEqual(result["index_elapsed_ms"], 0)
            self.assertNotIn(
                "index_rebuild_reason",
                json.loads((data_root / "index.json").read_text(encoding="utf-8")),
            )

    def test_a_missing_index_reports_why_it_was_rebuilt(self) -> None:
        with tempfile.TemporaryDirectory(dir=str(FRONTEND_ROOT)) as temp_dir:
            data_root = Path(temp_dir)
            (data_root / "datasets").mkdir()
            (data_root / "methods").mkdir()
            sidecar_dir = data_root / "sidecars"
            sidecar_dir.mkdir()
            (sidecar_dir / "Paid Loss.json").write_text(
                '{"dataset_name": "Paid Loss"}',
                encoding="utf-8",
            )
            folder_paths = {
                "data": str(data_root),
                "datasets": str(data_root / "datasets"),
                "methods": str(data_root / "methods"),
                "sidecars": str(sidecar_dir),
            }

            with (
                mock.patch.object(
                    dataset_instance_index_service,
                    "_folder_paths",
                    return_value=folder_paths,
                ),
                mock.patch.object(
                    dataset_instance_index_service,
                    "_canonical_identity",
                    return_value=("Example", "Paid"),
                ),
            ):
                first = dataset_instance_index_service.get_index("Example", "Paid")
                second = dataset_instance_index_service.get_index("Example", "Paid")
                forced = dataset_instance_index_service.get_index(
                    "Example",
                    "Paid",
                    refresh=True,
                )

            self.assertEqual(first["index_rebuild_reason"], "index-missing")
            # The rebuild it just paid for makes the next read the cheap one.
            self.assertEqual(second["index_rebuild_reason"], "")
            self.assertFalse(second["index_rebuilt"])
            self.assertEqual(forced["index_rebuild_reason"], "refresh-requested")

    def test_index_response_reports_the_on_disk_signature(self) -> None:
        # The Project Instance staleness watch baselines on this field, so it
        # must match the format the /datasets/cached/index-signature poll
        # reports for the same file: "<mtime_ms>:<size>", mtime first so the
        # client can compare write recency.
        with tempfile.TemporaryDirectory(dir=str(FRONTEND_ROOT)) as temp_dir:
            rc_dir = Path(temp_dir)
            folder_paths = _folder_paths_for(rc_dir)
            index_path = rc_dir / dataset_instance_index_service.INDEX_FILE_NAME
            index_path.write_text('{"files": []}', encoding="utf-8")

            response = dataset_instance_index_service._index_response(
                {"project_name": "Example", "reserving_class": "Paid", "files": []},
                persisted=True,
                folder_paths=folder_paths,
            )

            stat = index_path.stat()
            self.assertEqual(
                response["index_signature"],
                f"{round(stat.st_mtime * 1000.0, 3)}:{int(stat.st_size)}",
            )
            self.assertEqual(
                response["index_signature"],
                dataset_instance_index_service._index_signature_of(str(index_path)),
            )

    def test_index_response_signature_is_missing_without_a_file(self) -> None:
        with tempfile.TemporaryDirectory(dir=str(FRONTEND_ROOT)) as temp_dir:
            folder_paths = _folder_paths_for(Path(temp_dir))

            response = dataset_instance_index_service._index_response(
                {"project_name": "Example", "reserving_class": "Paid", "files": []},
                persisted=False,
                warning="not written",
                folder_paths=folder_paths,
            )

            self.assertEqual(response["index_signature"], "missing")


if __name__ == "__main__":
    unittest.main()
