from __future__ import annotations

import argparse
import faulthandler
import os
import sys
import threading
import time
import traceback
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
SRC = ROOT / "src"
TESTS = ROOT / "tests"

sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))


def _documents_debug_dir() -> Path:
    return Path.home() / "Documents" / "Arco" / "debug"


def _short(value: Any, limit: int = 220) -> str:
    text = repr(value)
    return text if len(text) <= limit else f"{text[:limit]}..."


def _shape(value: Any) -> str:
    if isinstance(value, dict):
        return f"dict(keys={list(value.keys())})"
    if isinstance(value, list):
        if value and all(isinstance(row, list) for row in value):
            cols = max((len(row) for row in value), default=0)
            return f"matrix(rows={len(value)}, cols={cols})"
        return f"list(len={len(value)})"
    return type(value).__name__


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()

    log_dir = _documents_debug_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"python_api_test_trace_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    with log_path.open("w", encoding="utf-8", buffering=1) as log_file:

        def log(message: str) -> None:
            elapsed = time.perf_counter() - start
            log_file.write(f"{elapsed:9.3f}s {message}\n")
            log_file.flush()

        def timeout_dump() -> None:
            log(f"TIMEOUT after {args.timeout}s; dumping all thread stacks")
            faulthandler.dump_traceback(file=log_file, all_threads=True)
            log_file.flush()
            os._exit(124)

        start = time.perf_counter()
        timer = threading.Timer(args.timeout, timeout_dump)
        timer.daemon = True
        timer.start()

        log(f"TRACE START pid={os.getpid()} cwd={Path.cwd()}")
        log(f"log_path={log_path}")
        log(f"python={sys.executable}")

        try:
            import arcrho_api.dfm as dfm_module
            import arcrho_api.io as io_module
            import arcrho_api.project as project_module
        except Exception:
            log("IMPORT arcrho_api failed")
            log(traceback.format_exc())
            return 2

        def trace_call(owner: Any, name: str, label: str | None = None) -> None:
            original = getattr(owner, name)
            call_label = label or f"{owner}.{name}"

            def wrapper(*call_args: Any, **kwargs: Any) -> Any:
                details = ""
                if name == "write_json_atomic" and call_args:
                    details = f" path={call_args[0]}"
                    if len(call_args) > 1:
                        details += f" data={_shape(call_args[1])}"
                elif name == "format_json_for_save":
                    indent = call_args[1] if len(call_args) > 1 else kwargs.get("indent", "")
                    if indent != "":
                        return original(*call_args, **kwargs)
                    details = f" data={_shape(call_args[0]) if call_args else ''}"
                elif call_args:
                    first = call_args[0]
                    details = f" self={type(first).__name__}"
                    path = getattr(first, "file_path", None)
                    if path is not None:
                        details += f" file={path}"
                log(f"ENTER {call_label}{details}")
                try:
                    result = original(*call_args, **kwargs)
                except Exception as exc:
                    log(f"RAISE {call_label}: {type(exc).__name__}: {_short(exc)}")
                    raise
                log(f"EXIT  {call_label}")
                return result

            setattr(owner, name, wrapper)

        trace_call(dfm_module.DfmMethod, "save", "DfmMethod.save")
        trace_call(dfm_module.DfmMethod, "_trim_saved_triangle_arrays", "DfmMethod._trim_saved_triangle_arrays")
        trace_call(dfm_module, "write_json_atomic", "dfm.write_json_atomic")
        trace_call(project_module, "write_json_atomic", "project.write_json_atomic")
        trace_call(io_module, "format_json_for_save", "io.format_json_for_save")

        project_class = getattr(project_module, "Project", None) or getattr(project_module, "ArcRhoProject", None)
        if project_class is not None and hasattr(project_class, "rebuild_dfm_index"):
            trace_call(project_class, "rebuild_dfm_index", f"{project_class.__name__}.rebuild_dfm_index")

        original_run = unittest.TestCase.run

        def traced_test_run(self: unittest.TestCase, result: unittest.result.TestResult | None = None) -> Any:
            test_id = self.id()
            log(f"TEST START {test_id}")
            test_start = time.perf_counter()
            try:
                return original_run(self, result)
            finally:
                log(f"TEST END   {test_id} elapsed={time.perf_counter() - test_start:.3f}s")

        unittest.TestCase.run = traced_test_run

        log("loading tests.test_arcrho_api")
        suite = unittest.defaultTestLoader.loadTestsFromName("test_arcrho_api")
        log(f"loaded tests count={suite.countTestCases()}")
        result = unittest.TextTestRunner(stream=log_file, verbosity=2).run(suite)
        timer.cancel()
        log(
            "TRACE END "
            f"run={result.testsRun} failures={len(result.failures)} errors={len(result.errors)} "
            f"skipped={len(result.skipped)}"
        )
        return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
