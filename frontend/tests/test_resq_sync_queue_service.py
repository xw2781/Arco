"""The hosted ResQ sync-queue publish writes the macro's request on the configured workspace."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

FRONTEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = FRONTEND_ROOT.parent
SERVER_COMPONENTS_SRC = REPOSITORY_ROOT / "server-components" / "src"
PYTHON_API_SRC = REPOSITORY_ROOT / "python-api" / "src"
for path in (FRONTEND_ROOT, SERVER_COMPONENTS_SRC, PYTHON_API_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from arcrho_api import resq_sync_queue as queue  # noqa: E402
from arcrho_workspace_mutation_contract import WORKSPACE_MUTATION_KINDS  # noqa: E402

from app_server.services import resq_sync_queue_service, user_identity_service  # noqa: E402

REQUEST_ID = "0123456789abcdef0123456789abcdef"


class ResqSyncQueueServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(dir=str(FRONTEND_ROOT))
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        patcher = patch.object(
            resq_sync_queue_service.config,
            "load_workspace_paths",
            return_value={"workspace_root": str(self.root), "paths": {}},
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_mutation_is_registered_with_the_arguments_the_service_takes(self) -> None:
        spec = WORKSPACE_MUTATION_KINDS[queue.PUBLISH_MUTATION_KIND]
        self.assertEqual(spec.module, "resq_sync_queue_service")
        self.assertEqual(spec.function, "publish_resq_sync_request")
        self.assertEqual(spec.required, ("project_name", "reserving_class", "request_id", "phase"))
        self.assertEqual(spec.optional, ("selected_rows",))

    def test_publishes_the_request_for_the_acting_user_under_the_configured_root(self) -> None:
        with user_identity_service.acting_identity("jdoe", "Jane Doe"):
            response = resq_sync_queue_service.publish_resq_sync_request(
                "Demo", r"Auto\PP", REQUEST_ID, "Export"
            )

        self.assertEqual(response, {"ok": True, "request_id": REQUEST_ID, "phase": "export", "resumed": False})
        request_path, _ = queue.request_paths(self.root, REQUEST_ID)
        published = json.loads(request_path.read_text(encoding="utf-8"))
        self.assertEqual(published["Function"], queue.REQUEST_FUNCTION)
        self.assertEqual((published["ProjectName"], published["Path"], published["Phase"]), ("Demo", r"Auto\PP", "export"))
        self.assertEqual(published["UserName"], "jdoe")
        self.assertNotIn(queue.SELECTION_FIELD, published)

    def test_an_apply_carries_the_reviewed_rows_with_their_signatures(self) -> None:
        rows = [{"id": "paid-loss", "name": "Paid Loss", "signature": {"key": "paid-loss"}}]

        resq_sync_queue_service.publish_resq_sync_request("Demo", r"Auto\PP", REQUEST_ID, "apply", rows)

        request_path, _ = queue.request_paths(self.root, REQUEST_ID)
        published = json.loads(request_path.read_text(encoding="utf-8"))
        self.assertEqual(
            published[queue.SELECTION_FIELD],
            [{"Id": "paid-loss", "Signature": {"key": "paid-loss"}, "Name": "Paid Loss"}],
        )

    def test_a_request_id_already_in_the_queue_is_returned_untouched(self) -> None:
        resq_sync_queue_service.publish_resq_sync_request("Demo", r"Auto\PP", REQUEST_ID, "preview")
        request_path, status_path = queue.request_paths(self.root, REQUEST_ID)
        first = request_path.read_bytes()

        repeated = resq_sync_queue_service.publish_resq_sync_request("Demo", r"Auto\PP", REQUEST_ID, "preview")

        self.assertTrue(repeated["resumed"])
        self.assertEqual(request_path.read_bytes(), first)

        request_path.unlink()
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text("{}", encoding="utf-8")
        claimed = resq_sync_queue_service.publish_resq_sync_request("Demo", r"Auto\PP", REQUEST_ID, "preview")
        self.assertTrue(claimed["resumed"])
        self.assertFalse(request_path.exists())

    def test_refuses_a_bad_phase_selection_or_request_id(self) -> None:
        for args in (
            ("Demo", r"Auto\PP", REQUEST_ID, "rollback"),
            ("Demo", r"Auto\PP", REQUEST_ID, "export", [{"id": "x", "signature": {}}]),
            ("Demo", r"Auto\PP", "../escape", "preview"),
            ("Demo", r"C:\Arco Server\projects\Demo", REQUEST_ID, "preview"),
        ):
            with self.subTest(args=args):
                with self.assertRaises(HTTPException) as refused:
                    resq_sync_queue_service.publish_resq_sync_request(*args)
                self.assertEqual(refused.exception.status_code, 400)
        self.assertFalse((self.root / queue.REQUEST_RELATIVE_DIR).exists())


if __name__ == "__main__":
    unittest.main()
