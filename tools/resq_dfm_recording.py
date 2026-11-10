"""Record every COM read the ResQ import makes of one DFM, for replay in tests.

The import's ``resq_migration.dfm.export_dfm`` is run against a live ResQ DFM
through a proxy that answers each read from ResQ and writes down what ResQ
said: a property's value, a parameterised getter's answer for the exact
arguments, a nested object, or the error ResQ raised. The recording, together
with the ultimates ResQ's own output vector holds, goes to a gzip JSON fixture
that ``python-api/tests/resq_com_replay.py`` replays, so a test runs the real
import code on ResQ's real answers without ResQ.

Server PC only (ResQ COM), run outside the sandbox::

    py -3.10 tools/resq_dfm_recording.py [--class MP+PIP] [--method "F 25 - Incurred DFM Bootstrap"] [--out PATH]

Read only: the proxy refuses every attribute write and the tool never saves.
Early binding throughout (late binding returns wrong values for some ResQ
properties).
"""
from __future__ import annotations

import argparse
import datetime
import gzip
import json
import sys
from pathlib import Path

from win32com.client import gencache

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python-api" / "src"))
sys.path.insert(0, str(REPO / "python-api" / "migration"))
sys.path.insert(0, str(REPO / "python-api" / "tests"))

from resq_com_replay import call_key, encode_value  # noqa: E402
from resq_migration import dfm as migration_dfm  # noqa: E402

PROJECT = "NJ_Annual_Prod_202605_Fake"
BASE = r"PRNJ - PA\PA\All States\Direct Group"
CONFIG = r"E:/Arco Server/config/config.json"
DEFAULT_OUT = REPO / "python-api" / "tests" / "fixtures" / "resq_dfm_mp_pip_f25.json.gz"


class _Recorder:
    """Stands in for one COM object and records each read under its path."""

    def __init__(self, target, path: str, reads: dict) -> None:
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_path", path)
        object.__setattr__(self, "_reads", reads)

    def __setattr__(self, name, value):
        raise RuntimeError(f"refusing to write {self._path}.{name} while recording")

    def _wrap(self, key: str, produce):
        try:
            value = produce()
        except Exception as exc:
            self._reads[key] = {"err": type(exc).__name__, "msg": str(exc)[:200]}
            raise
        if hasattr(value, "_oleobj_"):
            self._reads[key] = {"obj": 1}
            return _Recorder(value, key, self._reads)
        if callable(value):
            self._reads[key] = {"fn": 1}
            return _RecordedMethod(value, key, self._reads)
        self._reads[key] = encode_value(value)
        return value

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return self._wrap(f"{self._path}.{name}", lambda: getattr(self._target, name))


class _RecordedMethod:
    def __init__(self, method, path: str, reads: dict) -> None:
        self._method = method
        self._path = path
        self._reads = reads

    def __call__(self, *args, **kwargs):
        key = call_key(self._path, args, kwargs)
        owner = _Recorder(None, self._path, self._reads)
        return owner._wrap(key, lambda: self._method(*args, **kwargs))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--class", dest="rc", default="MP+PIP")
    parser.add_argument("--method", default="F 25 - Incurred DFM Bootstrap")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    cfg = json.load(open(CONFIG))["resq"]
    app = gencache.EnsureDispatch("ResQ3Automation.ResQApplication")
    app.ConnectByName(cfg["connection_name"], cfg["user_name"], cfg["password"])
    try:
        project = app.Projects().Item(PROJECT)
        if str(project.Name) != PROJECT:
            raise RuntimeError("refusing to run outside the fake project")
        rc_path = BASE + "\\" + args.rc
        dfm = project.ReservingClasses().Item(rc_path).DFMMethods().Item(args.method)
        output = dfm.OutputVector
        ultimates = [float(output.ValuesByIndex(k)) for k in range(1, int(output.Count) + 1)]
        tails = []
        for row in range(1, int(dfm.RatioAverageCount) + 1):
            average = dfm.CustomAverages(row)
            tails.append({"row": row, "name": str(dfm.AverageFormula(row)),
                          "average_type": int(average.AverageType), "tail_factor": float(average.TailFactor)})

        reads: dict = {}
        payload = migration_dfm.export_dfm(_Recorder(dfm, "dfm", reads), rc_path, REPO, strict=True)
    finally:
        app.Disconnect()

    fixture = {
        "source": f"{PROJECT} / {rc_path} / {args.method}, recorded over ResQ COM (read only)",
        "captured_on": datetime.date.today().isoformat(),
        "reserving_class": rc_path,
        "method": args.method,
        "resq_output_ultimates": ultimates,
        "resq_average_rows": tails,
        "reads": reads,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.out, "wt", encoding="utf-8") as handle:
        json.dump(fixture, handle, separators=(",", ":"))
    formulas = payload["ratios_tab"]["average_formulas"]
    print(json.dumps({
        "reads": len(reads),
        "out": str(args.out),
        "rows_with_a_tail": [(label, row[-1]) for label, row in zip(formulas["label"], formulas["values"])
                             if row and row[-1] not in (None, 1, 1.0)],
        "resq_ultimates": ultimates,
        "arco_ultimates": payload["results_tab"].get("ultimate_vector"),
    }, indent=1, default=str))


if __name__ == "__main__":
    main()
