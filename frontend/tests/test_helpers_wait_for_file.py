from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


FRONTEND_ROOT = Path(__file__).resolve().parents[1]
if str(FRONTEND_ROOT) not in sys.path:
    sys.path.insert(0, str(FRONTEND_ROOT))

from app_server import helpers


class NetworkPathDetectionTests(unittest.TestCase):
    def test_unc_pathis_network_path(self) -> None:
        self.assertTrue(helpers.is_network_path(r"\\server\Arco Server\requests\request.json"))

    def test_mapped_remote_driveis_network_path(self) -> None:
        with (
            patch.object(helpers.os, "name", "nt"),
            patch.object(helpers.os.path, "splitdrive", return_value=("E:", r"\Arco Server\requests\request.json")),
            patch.object(helpers, "_windows_drive_type", return_value=helpers._WINDOWS_DRIVE_REMOTE),
        ):
            self.assertTrue(helpers.is_network_path(r"E:\Arco Server\requests\request.json"))

    def test_local_windows_drive_is_not_network_path(self) -> None:
        with (
            patch.object(helpers.os, "name", "nt"),
            patch.object(helpers.os.path, "splitdrive", return_value=("C:", r"\ArcRho\request.json")),
            patch.object(helpers, "_windows_drive_type", return_value=3),
        ):
            self.assertFalse(helpers.is_network_path(r"C:\ArcRho\request.json"))


class NetworkWaitTests(unittest.TestCase):
    def test_network_path_polls_without_starting_watchdog(self) -> None:
        with (
            patch.object(helpers, "is_network_path", return_value=True),
            patch.object(helpers, "_bust_network_lookup_cache", return_value=True) as poke,
            patch.object(helpers.os.path, "exists", side_effect=(False, True)),
            patch.object(helpers, "Observer") as observer,
            patch.object(helpers.time, "sleep") as sleep,
        ):
            result = helpers.wait_for_file(r"E:\Arco Server\projects\example.csv", timeout_sec=1.0, settle_ms=0)

        self.assertTrue(result)
        observer.assert_not_called()
        sleep.assert_not_called()
        poke.assert_called_once_with(r"E:\Arco Server\projects")

    def test_network_path_stops_at_the_requested_timeout(self) -> None:
        with (
            patch.object(helpers, "is_network_path", return_value=True),
            patch.object(helpers, "_bust_network_lookup_cache", return_value=True),
            patch.object(helpers.os.path, "exists", return_value=False),
            patch.object(helpers, "Observer") as observer,
            patch.object(helpers.time, "monotonic", side_effect=(0.0, 0.0, 1.01)),
            patch.object(helpers.time, "sleep") as sleep,
        ):
            result = helpers.wait_for_file(r"E:\Arco Server\projects\example.csv", timeout_sec=1.0, settle_ms=0)

        self.assertFalse(result)
        observer.assert_not_called()
        sleep.assert_not_called()

    def test_failed_lookup_cache_probe_disables_later_probes_but_keeps_polling(self) -> None:
        with (
            patch.object(helpers, "is_network_path", return_value=True),
            patch.object(helpers, "_bust_network_lookup_cache", return_value=False) as poke,
            patch.object(helpers.os.path, "exists", side_effect=(False, False, True)),
            patch.object(helpers.time, "sleep"),
        ):
            result = helpers.wait_for_file(r"E:\Arco Server\projects\example.csv", timeout_sec=5.0, settle_ms=0)

        self.assertTrue(result)
        poke.assert_called_once()

    def test_local_path_poll_fallback_never_probes_the_directory(self) -> None:
        with (
            patch.object(helpers, "is_network_path", return_value=False),
            patch.object(helpers, "Observer", None),
            patch.object(helpers, "FileSystemEventHandler", None),
            patch.object(helpers, "_bust_network_lookup_cache") as poke,
            patch.object(helpers.os.path, "exists", side_effect=(False, True)),
            patch.object(helpers.time, "sleep"),
        ):
            result = helpers.wait_for_file(r"C:\ArcRho\example.csv", timeout_sec=1.0, settle_ms=0)

        self.assertTrue(result)
        poke.assert_not_called()

    def test_poll_interval_backs_off_from_fast_to_capped(self) -> None:
        with (
            patch.object(helpers, "is_network_path", return_value=True),
            patch.object(helpers, "_bust_network_lookup_cache", return_value=True),
            patch.object(helpers.os.path, "exists", side_effect=(False, False, False, False, True)),
            patch.object(helpers.time, "sleep") as sleep,
        ):
            result = helpers.wait_for_file(r"E:\Arco Server\projects\example.csv", timeout_sec=30.0, settle_ms=0)

        self.assertTrue(result)
        intervals = [call.args[0] for call in sleep.call_args_list]
        self.assertEqual(len(intervals), 3)
        self.assertAlmostEqual(intervals[0], helpers._WAIT_POLL_INITIAL_SEC)
        self.assertTrue(all(intervals[i] <= intervals[i + 1] for i in range(len(intervals) - 1)))
        self.assertTrue(all(interval <= helpers._WAIT_POLL_MAX_SEC for interval in intervals))


class LookupCacheProbeTests(unittest.TestCase):
    def test_probe_writes_and_removes_a_unique_temp_file(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            self.assertTrue(helpers._bust_network_lookup_cache(folder))
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_probe_reports_failure_for_an_unwritable_directory(self) -> None:
        missing = str(Path(__file__).resolve().parent / "does-not-exist-probe-target")
        self.assertFalse(helpers._bust_network_lookup_cache(missing))


if __name__ == "__main__":
    unittest.main()
