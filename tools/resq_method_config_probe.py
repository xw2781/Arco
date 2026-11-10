"""Probe how ResQ creates and reconfigures DFM, BF and Result Selection methods.

Creates throwaway methods (and the dataset types their outputs need) named
``ZZ Probe ...`` in one reserving class of the fake project, exercises every
call the ResQ export relies on to create a missing method or bring an existing
one in line with ArcRho, re-reads each result through a fresh connection, and
deletes everything it created. Nothing that already exists in the class is
changed. Server PC only (ResQ COM), with a Python that has pywin32::

    py -3.10 tools/resq_method_config_probe.py
    py -3.10 tools/resq_method_config_probe.py --only C D      # groups D, B, R, L need C's objects
    py -3.10 tools/resq_method_config_probe.py --json temp/method_probe.json
    py -3.10 tools/resq_method_config_probe.py --gui-setup     # objects for the GUI Load Settings check
    py -3.10 tools/resq_method_config_probe.py --gui-compare   # compare after the GUI check
    py -3.10 tools/resq_method_config_probe.py --cleanup       # delete every ZZ Probe object

The findings are recorded in python-api/docs/resq_reserving_class_export.md,
"Creating and reconfiguring methods"; the case ids printed here (C1, D3, ...)
are the ones that section cites.

Early binding throughout, and every plain property put goes through IDispatch
so a refused set raises ResQ's own error text instead of pywin32 quietly
creating a Python attribute. ``PROJECT`` must never name a production project.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback

import pythoncom
import pywintypes
from win32com.client import gencache

PROJECT = "NJ_Annual_Prod_202605_Fake"
RC_PATH = r"PRNJ - PA\PA\All States\Direct Group\COL"
PREFIX = "ZZ Probe "
CONFIG = r"E:/Arco Server/config/config.json"
STATE_FILE = os.path.join("temp", "resq_method_config_probe_gui.json")

TRI_ANNUAL = "Gross Loss--Incurred"          # stored O12/D12
TRI_ANNUAL_2 = "Gross Loss--Paid"            # ResQ spells it with a trailing space
TRI_QUARTERLY = "Claim Counts--CWP"          # C 12 runs on it at O3/D3
QUARTERLY_CATEGORY = "C Claim Count"         # the category of TRI_QUARTERLY (case C2)
SHARED_VECTOR_TYPE = "F 00 - Ultimate Net Loss"   # non-unique, not calculated, origin vector
CATEGORY = "D Gross Loss"
PRIOR_1 = "D 82 - Prior Qtr Selected"
PRIOR_2 = "D 91 - Current Qtr Indicated"
LATEST_VECTOR = "D 92 - Current Qtr Selected"

METHOD_DFM, METHOD_BF, METHOD_RS = 1, 2, 4
PRIOR_ULTIMATES = 0

OBSERVED: dict[str, object] = {}


# ----- COM helpers ----------------------------------------------------------------

def key(name) -> str:
    return " ".join(str(name or "").split()).casefold()


def err_text(exc):
    if isinstance(exc, pywintypes.com_error):
        args = exc.args
        return str(args[2][2]) if len(args) > 2 and args[2] and len(args[2]) > 2 else str(args)
    return f"{type(exc).__name__}: {exc}"


def record(case, entry):
    OBSERVED.setdefault(case, []).append(entry)


def put(case, obj, name, value):
    """Property put through Invoke; prints and records whether ResQ accepted it."""
    shown = getattr(value, "Name", value) if not isinstance(value, (int, float, str, bool)) else value
    try:
        dispid = obj._oleobj_.GetIDsOfNames(name)
        obj._oleobj_.Invoke(dispid, 0, pythoncom.DISPATCH_PROPERTYPUT, 0, value)
        print(f"  put {name}={shown!r}: ok")
        record(case, {"put": name, "value": str(shown), "accepted": True})
        return True
    except Exception as exc:  # noqa: BLE001
        text = err_text(exc)
        print(f"  put {name}={shown!r}: REFUSED {text}")
        record(case, {"put": name, "value": str(shown), "accepted": False, "error": text})
        return False


def call(case, label, fn):
    """Invoke an action and report whether ResQ accepted it; returns (ok, result)."""
    try:
        result = fn()
        print(f"  {label}: ok")
        record(case, {"call": label, "accepted": True})
        return True, result
    except Exception as exc:  # noqa: BLE001
        text = err_text(exc)
        print(f"  {label}: REFUSED {text}")
        record(case, {"call": label, "accepted": False, "error": text})
        return False, None


def safe(fn, default=None):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        return default if default is not None else f"<error: {err_text(exc)}>"


def section(title):
    print("\n" + "=" * 8, title)


def find(collection, name):
    wanted = key(name)
    for i in range(1, collection.Count + 1):
        item = collection.Item(i)
        if key(item.Name) == wanted:
            return item
    return None


# ----- snapshots --------------------------------------------------------------------

def dfm_rows(dfm):
    rows = []
    for i in range(1, int(dfm.RatioAverageCount) + 1):
        a = dfm.CustomAverages(i)
        t = int(a.AverageType)
        rows.append({
            "row": i,
            "label": str(dfm.AverageFormula(i)),
            "name": str(a.Name),
            "type": t,
            "weight": int(a.WeightType),
            "periods": int(a.PeriodsIncluded),
            "exclude_hilo": bool(a.ExcludeHighLow),
            "exclude_hilo2": int(a.ExcludeHighLow2),
            "formula": str(a.Formula or "") if t == 6 else "",
            "tail": round(float(a.TailFactor), 9),
        })
    return rows


def dfm_snapshot(dfm):
    cols = int(dfm.DevelopmentCount(1))
    origins = int(dfm.OriginCount)
    s = {
        "name": str(dfm.Name),
        "output": str(dfm.OutputVector.Name),
        "output_type": str(dfm.OutputVector.DatasetType.Name),
        "input": safe(lambda: str(dfm.InputTriangle.Name)),
        "lengths": [int(dfm.OriginLength), int(dfm.DevelopmentLength)],
        "origins": origins,
        "columns": cols,
        "ratio_decimals": safe(lambda: int(dfm.RatioDecimalPlaces)),
        "method_decimals": safe(lambda: int(dfm.MethodDecimalPlaces)),
        "rows": dfm_rows(dfm),
        "selected": [safe(lambda d=d: int(dfm.SelectedRatios(d))) for d in range(1, cols + 1)],
        "excluded": [[o, d, int(dfm.ExcludedRatios(o, d))]
                     for o in range(1, origins + 1)
                     for d in range(1, int(dfm.DevelopmentCount(o)))
                     if int(dfm.ExcludedRatios(o, d)) == 1],
        "user_ratios": [],
        "curve_user_cols": safe(lambda: int(dfm.CurveUserValueColCount)),
        "curve_user_values": [],
        "selected_estimates": [safe(lambda i=i: int(dfm.SelectedEstimates(i))) for i in range(1, cols)],
        "selected_tail_factor": safe(lambda: int(dfm.SelectedTailFactor)),
        "future_periods": safe(lambda: int(dfm.FutureDevelopmentPeriods)),
        "fitting_method": safe(lambda: int(dfm.FittingMethod)),
        "included_ratios": [safe(lambda i=i: bool(dfm.IncludedRatios(i))) for i in range(1, cols)],
        "notes": safe(lambda: str(dfm.Notes or "")),
    }
    for row in s["rows"]:
        if row["type"] == 5:
            for d in range(1, cols):
                v = safe(lambda d=d, r=row["row"]: float(dfm.UserRatios(d, r)), 0.0)
                if isinstance(v, float) and v:
                    s["user_ratios"].append([row["row"], d, round(v, 6)])
    user_cols = s["curve_user_cols"] if isinstance(s["curve_user_cols"], int) else 0
    for col in range(6, 6 + user_cols):
        s["curve_user_values"].append([round(float(safe(lambda i=i, c=col: dfm.CurveValues(c, i), 0.0)), 6)
                                       for i in range(0, 4)])
    return s


def bf_snapshot(bf):
    count = int(bf.PriorVectorCount)
    priors = []
    for k in range(1, count + 1):
        pr = bf.PriorRatioObj(k)
        priors.append({
            "vector": safe(lambda: str(pr.Vector.Name)),
            "type": safe(lambda: int(pr.PriorType)),
            "weights": [round(float(safe(lambda o=o: pr.RatioWeights(o), 0.0)), 6) for o in range(1, int(bf.OriginCount) + 1)],
        })
    return {
        "name": str(bf.Name),
        "output": str(bf.OutputVector.Name),
        "output_type": str(bf.OutputVector.DatasetType.Name),
        "origin_length": int(bf.OriginLength),
        "latest": safe(lambda: str(bf.Latest.Name)),
        "latest_type": safe(lambda: int(bf.LatestType)),
        "pct_developed": safe(lambda: str(bf.PercentageDeveloped.Name)),
        "pct_developed_type": safe(lambda: int(bf.PercentageDevelopedType)),
        "legacy_prior": safe(lambda: str(bf.Prior.Name) if bf.Prior is not None else None, "None"),
        "legacy_prior_type": safe(lambda: int(bf.PriorType)),
        "has_prior": safe(lambda: bool(bf.HasPrior)),
        "weight_selection": safe(lambda: int(bf.PriorRatioWeightSelection)),
        "priors": priors,
    }


def rs_snapshot(rs):
    count = int(rs.DatasetCount)
    origins = int(rs.OriginCount)
    return {
        "name": str(rs.Name),
        "output": str(rs.OutputVector.Name),
        "output_type": str(rs.OutputVector.DatasetType.Name),
        "origin_length": int(rs.OriginLength),
        "datasets": [str(rs.Dataset(i).Name) for i in range(1, count + 1)],
        "sort_index": [safe(lambda i=i: int(rs.CustomSortIndex(i))) for i in range(1, count + 1)],
        "weights": [[round(float(safe(lambda i=i, o=o: rs.Weights(i, o), 0.0)), 6) for o in range(1, origins + 1)]
                    for i in range(1, count + 1)],
    }


def diff(before, after, label):
    changed = {k: {"before": before.get(k), "after": after.get(k)}
               for k in sorted(set(before) | set(after)) if before.get(k) != after.get(k)}
    print(f"  -- {label}: {', '.join(changed) if changed else 'nothing changed'}")
    for k, v in changed.items():
        b, a = json.dumps(v["before"], default=str), json.dumps(v["after"], default=str)
        print(f"     {k}: {b[:160]}  ->  {a[:160]}")
    return changed


# ----- the probe --------------------------------------------------------------------

class Probe:
    def __init__(self, app):
        self.app = app
        self.bind()

    def bind(self):
        self.project = self.app.Projects().Item(PROJECT)
        self.rc = self.project.ReservingClasses().Item(RC_PATH)

    def reconnect(self):
        """A fresh connection, so every read comes from the database."""
        try:
            self.rc.UnloadChildren()
        except Exception:  # noqa: BLE001
            pass
        self.app.Disconnect()
        cfg = json.load(open(CONFIG))["resq"]
        self.app.ConnectByName(cfg["connection_name"], cfg["user_name"], cfg["password"])
        self.bind()

    # -- lookups -------------------------------------------------------------------

    def triangle(self, name):
        return find(self.rc.Triangles(), name)

    def vector(self, name):
        return find(self.rc.Vectors(), name)

    def dfm(self, name):
        return find(self.rc.DFMMethods(), name)

    def bf(self, name):
        return find(self.rc.BFMethods(), name)

    def rs(self, name):
        return find(self.rc.ResultSelections(), name)

    def dataset_type(self, name):
        return find(self.project.DatasetTypes(), name)

    def new_type(self, case, name, decimals=0, category=CATEGORY, aggregated=False):
        """A unique origin-vector dataset type made through DatasetTypes().Add().

        ``Add()`` defaults to ``Aggregated = True``; every method output type in
        the class is ``False``, and an aggregated output type can make the save
        of a method in a roll-up class fail (case C2).
        """
        dt = self.project.DatasetTypes().Add()
        defaults = {
            "Name": safe(lambda: str(dt.Name)), "Unique": safe(lambda: bool(dt.Unique)),
            "Aggregated": safe(lambda: bool(dt.Aggregated)), "DataFormat": safe(lambda: int(dt.DataFormat)),
            "DecimalPlaces": safe(lambda: int(dt.DecimalPlaces)), "Calculated": safe(lambda: bool(dt.Calculated)),
            "IncludeInResultSelection": safe(lambda: bool(dt.IncludeInResultSelection)),
            "Category": safe(lambda: dt.Category.Name if dt.Category is not None else None, "None"),
        }
        print(f"  new type defaults: {defaults}")
        record(case, {"new_type_defaults": defaults})
        put(case, dt, "Name", name)
        put(case, dt, "Category", self.project.Categories().Item(category))
        put(case, dt, "DataFormat", 1)
        put(case, dt, "DecimalPlaces", decimals)
        put(case, dt, "Unique", True)
        put(case, dt, "Aggregated", aggregated)
        call(case, f"DatasetType {name!r}.Save", dt.Save)
        return dt

    def add_method(self, case, kind, name, type_name=None, new_type=False, category=CATEGORY):
        ok, m = call(case, f"AddMethod({kind}) for {name!r}", lambda: self.rc.AddMethod(kind))
        if not ok:
            return None
        defaults = {"Name": safe(lambda: str(m.Name)), "OriginLength": safe(lambda: int(m.OriginLength)),
                    "Output": safe(lambda: str(m.OutputVector.Name)),
                    "OutputType": safe(lambda: str(m.OutputVector.DatasetType.Name) if m.OutputVector.DatasetType else None, "None")}
        if kind == METHOD_DFM:
            defaults.update({"DevelopmentLength": safe(lambda: int(m.DevelopmentLength)),
                             "RatioAverageCount": safe(lambda: int(m.RatioAverageCount)),
                             "InputTriangle": safe(lambda: m.InputTriangle.Name if m.InputTriangle is not None else None, "None")})
        if kind == METHOD_RS:
            defaults["DatasetCount"] = safe(lambda: int(m.DatasetCount))
        if kind == METHOD_BF:
            defaults["PriorVectorCount"] = safe(lambda: int(m.PriorVectorCount))
        print(f"  defaults after AddMethod: {defaults}")
        record(case, {"add_method_defaults": defaults})
        put(case, m, "Name", name)
        put(case, m.OutputVector, "Name", name)
        dt = self.new_type(case, type_name or name, category=category) if new_type else self.dataset_type(type_name or SHARED_VECTOR_TYPE)
        put(case, m.OutputVector, "DatasetType", dt)
        return m

    # ===== group C: creating methods ===========================================

    def c0_survey(self):
        counts = {"dfm": self.rc.DFMMethods().Count, "bf": self.rc.BFMethods().Count,
                  "rs": self.rc.ResultSelections().Count, "triangles": self.rc.Triangles().Count,
                  "vectors": self.rc.Vectors().Count, "types": self.project.DatasetTypes().Count}
        left = [str(v.Name) for v in (self.rc.Vectors().Item(i) for i in range(1, self.rc.Vectors().Count + 1))
                if str(v.Name).startswith(PREFIX)]
        counts["class_aggregated"] = safe(lambda: bool(self.rc.Aggregated))
        counts["class_calculated"] = safe(lambda: bool(self.rc.Calculated))
        print(f"  counts {counts}; ZZ Probe vectors already present: {left}")
        OBSERVED["survey"] = {"counts": counts, "leftover": left}
        missing = find(self.project.Categories(), "ZZ no such category")
        print(f"  a category lookup that misses returns {missing!r}")
        record("C0", {"missing_category_lookup": repr(missing)})
        item_missing = safe(lambda: repr(self.project.Categories().Item("ZZ no such category")))
        print(f"  Categories().Item(<missing>) -> {item_missing}")
        record("C0", {"categories_item_missing": item_missing})

    def c1_create_dfm(self):
        """C1 — AddMethod(1) onto a dataset type that already exists: name, output, input, lengths, Save."""
        self.new_type("C1", PREFIX + "DFM A")
        self.reconnect()
        m = self.add_method("C1", METHOD_DFM, PREFIX + "DFM A", type_name=PREFIX + "DFM A")
        call("C1", "Save before InputTriangle is set", m.Save)
        put("C1", m, "InputTriangle", self.triangle(TRI_ANNUAL))
        put("C1", m, "OriginLength", 12)
        put("C1", m, "DevelopmentLength", 12)
        call("C1", "Save", m.Save)
        print(f"  rows of a new DFM: {[r['label'] for r in dfm_rows(m)]}")
        record("C1", {"new_dfm_rows": dfm_rows(m)})

    def c2_create_dfm_new_type(self):
        """C2 — a DFM whose output type is made in the same pass; and the saves ResQ refuses."""
        m = self.add_method("C2", METHOD_DFM, PREFIX + "DFM B", new_type=True, category=QUARTERLY_CATEGORY)
        put("C2", m, "InputTriangle", self.triangle(TRI_QUARTERLY))
        put("C2", m, "OriginLength", 12)
        put("C2", m, "DevelopmentLength", 12)
        call("C2", "Save", m.Save)
        # Refusals, each on its own throwaway method; a refused save persists nothing.
        dup = self.add_method("C2", METHOD_DFM, PREFIX + "DFM B dup", type_name=PREFIX + "DFM B")
        put("C2", dup, "InputTriangle", self.triangle(TRI_QUARTERLY))
        call("C2", "Save a second DFM onto DFM B's unique type", dup.Save)
        shared = self.add_method("C2", METHOD_DFM, PREFIX + "DFM shared", type_name=SHARED_VECTOR_TYPE)
        put("C2", shared, "InputTriangle", self.triangle(TRI_ANNUAL))
        call("C2", f"Save a DFM onto the shared non-unique type {SHARED_VECTOR_TYPE!r}", shared.Save)
        agg = self.add_method("C2", METHOD_DFM, PREFIX + "DFM agg", type_name=None, new_type=False)
        put("C2", agg.OutputVector, "DatasetType",
            self.new_type("C2", PREFIX + "DFM agg", category=QUARTERLY_CATEGORY, aggregated=True))
        put("C2", agg, "InputTriangle", self.triangle(TRI_QUARTERLY))
        call("C2", "Save a DFM whose new output type keeps Add()'s Aggregated=True", agg.Save)
        cat = self.add_method("C2", METHOD_DFM, PREFIX + "DFM cat", new_type=True, category=CATEGORY)
        put("C2", cat, "InputTriangle", self.triangle(TRI_QUARTERLY))
        call("C2", f"Save a DFM whose output type category {CATEGORY!r} differs from its input's", cat.Save)
        self.reconnect()

    def c3_create_bf(self):
        """C3 — AddMethod(2): latest triangle, % developed from the new DFM, one prior."""
        m = self.add_method("C3", METHOD_BF, PREFIX + "BF", new_type=True)
        put("C3", m, "OriginLength", 12)
        put("C3", m, "LatestType", 0)
        put("C3", m, "Latest", self.triangle(TRI_ANNUAL))
        put("C3", m, "PercentageDevelopedType", 2)
        print(f"  PercentageDevelopedType after the type put: {safe(lambda: int(m.PercentageDevelopedType))}")
        put("C3", m, "PercentageDeveloped", self.vector(PREFIX + "DFM A"))
        print(f"  PercentageDevelopedType after the dataset put: {safe(lambda: int(m.PercentageDevelopedType))}")
        put("C3", m, "PercentageDevelopedType", 2)
        print(f"  PercentageDevelopedType after the type is put again: {safe(lambda: int(m.PercentageDevelopedType))}")
        call("C3", "AddPriorVector(prior 1, ultimates)", lambda: m.AddPriorVector(self.vector(PRIOR_1), PRIOR_ULTIMATES))
        print(f"  PriorVectorCount after one AddPriorVector: {safe(lambda: int(m.PriorVectorCount))}")
        call("C3", "Save", m.Save)

    def c4_create_rs(self):
        """C4 — AddMethod(4): load a triangle, the new DFM and the new BF."""
        m = self.add_method("C4", METHOD_RS, PREFIX + "RS", new_type=True)
        for name in (TRI_ANNUAL, PREFIX + "DFM A", PREFIX + "BF"):
            ds = self.triangle(name) or self.vector(name)
            call("C4", f"AddDataset({name!r})", lambda ds=ds: m.AddDataset(ds))
        print(f"  datasets before Save: {[str(m.Dataset(i).Name) for i in range(1, int(m.DatasetCount) + 1)]}")
        call("C4", "Save", m.Save)

    def v1_verify_created(self):
        """V1 — everything C1-C4 made, read back through a fresh connection."""
        self.reconnect()
        out = {}
        for label, getter, snap in (("DFM A", self.dfm, dfm_snapshot), ("DFM B", self.dfm, dfm_snapshot),
                                    ("DFM B dup", self.dfm, dfm_snapshot),
                                    ("BF", self.bf, bf_snapshot), ("RS", self.rs, rs_snapshot)):
            m = getter(PREFIX + label)
            out[label] = snap(m) if m is not None else None
            brief = {k: v for k, v in (out[label] or {}).items() if k not in ("rows", "excluded", "included_ratios", "selected_estimates", "selected", "weights")}
            print(f"  {label}: {json.dumps(brief, default=str)[:600] if m is not None else 'NOT FOUND'}")
        dt = self.dataset_type(PREFIX + "DFM B")
        if dt is not None:
            out["type DFM B"] = {"Unique": bool(dt.Unique), "DataFormat": int(dt.DataFormat),
                                 "DecimalPlaces": int(dt.DecimalPlaces), "Category": str(dt.Category.Name)}
            print(f"  type DFM B: {out['type DFM B']}")
        OBSERVED["V1"] = out

    # ===== group D: reconfiguring a DFM ========================================

    def _dress(self, case, m):
        """Give a DFM a selection, an exclusion, a User Entry value, a curve column and a note."""
        rows = dfm_rows(m)
        user_row = next((r["row"] for r in rows if r["type"] == 5), None)
        call(case, "SetSelectedRatios(dev 1 -> row 2)", lambda: m.SetSelectedRatios(1, 2))
        call(case, "SetSelectedRatios(dev 2 -> row 5)", lambda: m.SetSelectedRatios(2, 5))
        call(case, "SetExcludedRatios(1, 1, 1)", lambda: m.SetExcludedRatios(1, 1, 1))
        if user_row:
            call(case, f"SetUserRatios(dev 3, row {user_row}, 1.2345)", lambda: m.SetUserRatios(3, user_row, 1.2345))
            call(case, f"SetSelectedRatios(dev 3 -> row {user_row})", lambda: m.SetSelectedRatios(3, user_row))
        put(case, m, "CurveUserValueColCount", 1)
        call(case, "SetCurveValues(6, 1, 1.05)", lambda: m.SetCurveValues(6, 1, 1.05))
        put(case, m, "FutureDevelopmentPeriods", 3)
        put(case, m, "Notes", "ZZ probe note")
        call(case, "Save", m.Save)

    def d1_input_triangle(self):
        """D1 — change a saved DFM's input triangle."""
        m = self.dfm(PREFIX + "DFM A")
        self._dress("D1", m)
        before = dfm_snapshot(m)
        put("D1", m, "InputTriangle", self.triangle(TRI_ANNUAL_2))
        mid = dfm_snapshot(m)
        diff(before, mid, "in memory after InputTriangle put")
        call("D1", "Save", m.Save)
        self.reconnect()
        after = dfm_snapshot(self.dfm(PREFIX + "DFM A"))
        OBSERVED["D1 diff"] = diff(before, after, "after Save, fresh connection")

    def d2_lengths(self):
        """D2 — origin and development length, both directions, on a quarterly triangle."""
        m = self.dfm(PREFIX + "DFM B")
        self._dress("D2", m)
        s0 = dfm_snapshot(m)
        print(f"  start O{s0['lengths'][0]}/D{s0['lengths'][1]}")
        lengths = lambda: f"now O{int(m.OriginLength)}/D{int(m.DevelopmentLength)}"
        put("D2", m, "OriginLength", 3); print(f"    {lengths()}")      # D12 does not divide O3
        put("D2", m, "DevelopmentLength", 3); print(f"    {lengths()}")
        put("D2", m, "OriginLength", 3); print(f"    {lengths()}")
        call("D2", "Save at O3/D3", m.Save)
        self.reconnect()
        m = self.dfm(PREFIX + "DFM B")
        s1 = dfm_snapshot(m)
        OBSERVED["D2 down"] = diff(s0, s1, "O12/D12 -> O3/D3, fresh connection")
        lengths = lambda: f"now O{int(m.OriginLength)}/D{int(m.DevelopmentLength)}"
        put("D2", m, "DevelopmentLength", 12); print(f"    {lengths()}")    # D12 does not divide O3
        put("D2", m, "OriginLength", 12); print(f"    {lengths()}")
        put("D2", m, "DevelopmentLength", 12); print(f"    {lengths()}")
        call("D2", "Save at O12/D12", m.Save)
        put("D2", m, "DevelopmentLength", 6)
        call("D2", "Save at O12/D6", m.Save)
        put("D2", m, "DevelopmentLength", 12)
        call("D2", "Save back at O12/D12", m.Save)
        self.reconnect()
        s2 = dfm_snapshot(self.dfm(PREFIX + "DFM B"))
        OBSERVED["D2 up"] = diff(s1, s2, "O3/D3 -> O12/D12, fresh connection")

    def d3_row_count(self):
        """D3 — grow and shrink RatioAverageCount."""
        m = self.dfm(PREFIX + "DFM A")
        call("D3", "SetSelectedRatios(dev 4 -> row 13)", lambda: m.SetSelectedRatios(4, 13))
        call("D3", "Save", m.Save)
        s0 = dfm_snapshot(m)
        put("D3", m, "RatioAverageCount", 15)
        rows = dfm_rows(m)
        print(f"  rows after growing to 15: {[(r['row'], r['label'], r['type'], r['weight'], r['periods']) for r in rows[-4:]]}")
        call("D3", "Save at 15 rows", m.Save)
        self.reconnect()
        m = self.dfm(PREFIX + "DFM A")
        s1 = dfm_snapshot(m)
        OBSERVED["D3 grow"] = diff(s0, s1, "13 -> 15 rows, fresh connection")
        put("D3", m, "RatioAverageCount", 11)
        call("D3", "Save at 11 rows", m.Save)
        self.reconnect()
        m = self.dfm(PREFIX + "DFM A")
        s2 = dfm_snapshot(m)
        OBSERVED["D3 shrink"] = diff(s1, s2, "15 -> 11 rows, fresh connection")
        put("D3", m, "RatioAverageCount", 13)
        rows = dfm_rows(m)
        print(f"  rows 12-13 after growing back to 13: {[(r['row'], r['label'], r['type']) for r in rows[11:]]}")
        call("D3", "Save at 13 rows", m.Save)

    ROW_SPECS = [
        # row, label, AverageType, WeightType, PeriodsIncluded, ExcludeHighLow2, Formula
        (1, "simple all", 0, 0, 0, 0, None),
        (2, "volume all", 0, 1, 0, 0, None),
        (3, "simple 5", 0, 0, 5, 0, None),
        (4, "volume 3 ex hi/lo", 0, 1, 3, 1, None),
        (5, "simple 6 ex hi/lo x2", 0, 0, 6, 2, None),
        (6, "user entry", 5, 0, 0, 0, None),
        (7, "calculated", 6, 0, 0, 0, "(Average(3)+Average(4))/2"),
        (8, "benchmark", 9, 0, 0, 0, None),
    ]

    def d4_row_fields(self):
        """D4 — write every CustomAverages field per row kind; what the name reads back as."""
        m = self.dfm(PREFIX + "DFM A")
        result = []
        for row, label, t, w, p, ex, formula in self.ROW_SPECS:
            a = m.CustomAverages(row)
            print(f"  row {row} ({label}) before: {m.AverageFormula(row)!r}")
            put("D4", a, "AverageType", t)
            put("D4", a, "WeightType", w)
            put("D4", a, "PeriodsIncluded", p)
            put("D4", a, "ExcludeHighLow", ex > 0)
            put("D4", a, "ExcludeHighLow2", ex)
            if formula is not None:
                put("D4", a, "Formula", formula)
            after_fields = str(m.AverageFormula(row))
            call("D4", f"row {row} ResetName", a.ResetName)
            after_reset = str(m.AverageFormula(row))
            value = safe(lambda: round(float(m.AverageRatioValues(1, row)), 6))
            print(f"    name after fields {after_fields!r}, after ResetName {after_reset!r}, dev 1 value {value}")
            result.append({"row": row, "kind": label, "after_fields": after_fields, "after_reset": after_reset, "dev1": value})
        a = m.CustomAverages(3)
        put("D4", a, "Name", "ZZ custom label")
        renamed = str(m.AverageFormula(3))
        print(f"  row 3 after Name='ZZ custom label': {renamed!r}")
        result.append({"row": 3, "kind": "explicit Name", "after_fields": renamed})
        call("D4", "row 3 ResetName after an explicit Name", a.ResetName)
        reset = str(m.AverageFormula(3))
        print(f"  row 3 after ResetName: {reset!r}")
        result.append({"row": 3, "kind": "ResetName after explicit Name", "after_fields": reset})
        a = m.CustomAverages(7)
        put("D4", a, "Name", "Benchmark")
        put("D4", a, "Formula", "(Average(1)+Average(2))/2")
        put("D4", a, "PeriodsIncluded", 4)
        kept = str(m.AverageFormula(7))
        print(f"  row 7 after Name='Benchmark' then Formula and PeriodsIncluded puts: {kept!r}")
        result.append({"row": 7, "kind": "explicit Name, then field puts", "after_fields": kept})
        call("D4", "Save", m.Save)
        self.reconnect()
        m = self.dfm(PREFIX + "DFM A")
        rows = dfm_rows(m)
        for r in rows[:8]:
            print(f"  fresh: {r}")
        OBSERVED["D4"] = {"writes": result, "fresh_rows": rows}

    # ===== group B: reconfiguring a BF =========================================

    def b1_bf(self):
        """B1 — latest as triangle and vector, % developed type, several priors and weights."""
        m = self.bf(PREFIX + "BF")
        s0 = bf_snapshot(m)
        put("B1", m, "LatestType", 1)
        put("B1", m, "Latest", self.vector(LATEST_VECTOR))
        put("B1", m, "PercentageDevelopedType", 3)
        put("B1", m, "PercentageDeveloped", self.vector(PREFIX + "DFM B"))
        call("B1", "AddPriorVector(prior 2, ultimates)", lambda: m.AddPriorVector(self.vector(PRIOR_2), PRIOR_ULTIMATES))
        print(f"  PriorVectorCount: {safe(lambda: int(m.PriorVectorCount))}")
        put("B1", m, "PriorRatioWeightSelection", 1)
        origins = int(m.OriginCount)
        for k, weight in ((1, 0.25), (2, 0.75)):
            pr = m.PriorRatioObj(k)
            ok, _ = call("B1", f"PriorRatioObj({k}).SetRatioWeights(o, {weight})",
                         lambda pr=pr, weight=weight: [pr.SetRatioWeights(o, weight) for o in range(1, origins + 1)])
            if not ok:
                ok, _ = call("B1", f"PriorRatioObj({k}).RatioWeights put by Invoke", lambda pr=pr, weight=weight: [
                    pr._oleobj_.Invoke(pr._oleobj_.GetIDsOfNames("RatioWeights"), 0, pythoncom.DISPATCH_PROPERTYPUT, 0, o, weight)
                    for o in range(1, origins + 1)])
        call("B1", "Save", m.Save)
        self.reconnect()
        m = self.bf(PREFIX + "BF")
        s1 = bf_snapshot(m)
        OBSERVED["B1 reconfigure"] = diff(s0, s1, "latest vector, pd type 3, two priors, fresh connection")
        call("B1", "RemovePriorVector(1)", lambda: m.RemovePriorVector(1))
        put("B1", m, "LatestType", 0)
        put("B1", m, "Latest", self.triangle(TRI_ANNUAL))
        put("B1", m, "PercentageDevelopedType", 2)
        put("B1", m, "PercentageDeveloped", self.vector(PREFIX + "DFM A"))
        call("B1", "Save", m.Save)
        self.reconnect()
        m = self.bf(PREFIX + "BF")
        s2 = bf_snapshot(m)
        OBSERVED["B1 remove"] = diff(s1, s2, "RemovePriorVector(1) and latest back to a triangle, fresh connection")
        put("B1", m, "Prior", self.vector(PRIOR_1))
        put("B1", m, "PriorType", PRIOR_ULTIMATES)
        s3 = bf_snapshot(m)
        OBSERVED["B1 legacy prior"] = diff(s2, s3, "legacy Prior put with one collection prior, in memory")
        call("B1", "Save", m.Save)
        self.reconnect()
        OBSERVED["B1 legacy prior saved"] = diff(s2, bf_snapshot(self.bf(PREFIX + "BF")), "legacy Prior put, fresh connection")

    # ===== group R: reconfiguring a Result Selection ===========================

    def r1_rs(self):
        """R1 — weights, RemoveDataset, re-adding, and the dataset order."""
        m = self.rs(PREFIX + "RS")
        origins = int(m.OriginCount)
        for i, w in ((1, 0.2), (2, 0.3), (3, 0.5)):
            call("R1", f"SetWeights({i}, o, {w})", lambda i=i, w=w: [m.SetWeights(i, o, w) for o in range(1, origins + 1)])
        call("R1", "Save", m.Save)
        self.reconnect()
        m = self.rs(PREFIX + "RS")
        s0 = rs_snapshot(m)
        print(f"  start: {s0['datasets']} weights {[w[0] for w in s0['weights']]} sort {s0['sort_index']}")
        call("R1", "RemoveDataset(DFM A output)", lambda: m.RemoveDataset(self.vector(PREFIX + "DFM A")))
        s1 = rs_snapshot(m)
        diff(s0, s1, "after RemoveDataset, in memory")
        call("R1", "Save", m.Save)
        self.reconnect()
        m = self.rs(PREFIX + "RS")
        s2 = rs_snapshot(m)
        OBSERVED["R1 remove"] = diff(s0, s2, "RemoveDataset, fresh connection")
        call("R1", "AddDataset(DFM A output) again", lambda: m.AddDataset(self.vector(PREFIX + "DFM A")))
        call("R1", "Save", m.Save)
        self.reconnect()
        m = self.rs(PREFIX + "RS")
        s3 = rs_snapshot(m)
        OBSERVED["R1 re-add"] = diff(s2, s3, "re-added, fresh connection")
        count = int(m.DatasetCount)
        call("R1", f"SetCustomSortIndex({count}, 1)", lambda: m.SetCustomSortIndex(count, 1))
        call("R1", "Save", m.Save)
        self.reconnect()
        OBSERVED["R1 sort"] = diff(s3, rs_snapshot(self.rs(PREFIX + "RS")), "SetCustomSortIndex(last, 1), fresh connection")
        call("R1", "RemoveDataset by index (expected to fail: it takes the dataset)", lambda: m.RemoveDataset(1))

    # ===== group L: LoadMethod ==================================================

    def l1_load_method(self):
        """L1 — DFM.LoadMethod(other): what is copied and what is kept."""
        source = self.dfm(PREFIX + "DFM A")
        target = self.add_method("L1", METHOD_DFM, PREFIX + "DFM C", new_type=True, category=QUARTERLY_CATEGORY)
        put("L1", target, "InputTriangle", self.triangle(TRI_QUARTERLY))
        put("L1", target, "OriginLength", 3)
        put("L1", target, "DevelopmentLength", 3)
        put("L1", target, "Notes", "ZZ target note")
        call("L1", "Save", target.Save)
        put("L1", source, "RatioDecimalPlaces", 3)
        call("L1", "Save the source with 3 ratio decimals", source.Save)
        src = dfm_snapshot(source)
        before = dfm_snapshot(target)
        call("L1", "target.LoadMethod(DFM A)", lambda: target.LoadMethod(source))
        mid = dfm_snapshot(target)
        diff(before, mid, "target after LoadMethod, in memory")
        call("L1", "Save", target.Save)
        self.reconnect()
        after = dfm_snapshot(self.dfm(PREFIX + "DFM C"))
        OBSERVED["L1 changed"] = diff(before, after, "target after LoadMethod, fresh connection")
        OBSERVED["L1 still differs from source"] = diff(src, after, "source vs target after LoadMethod")

    # ===== GUI "Load Settings From Another Method" =============================

    def gui_setup(self):
        """A source DFM with non-default rows and a plain target, for the GUI check."""
        src = self.add_method("G", METHOD_DFM, PREFIX + "GUI Source", new_type=True)
        put("G", src, "InputTriangle", self.triangle(TRI_ANNUAL))
        put("G", src, "OriginLength", 12)
        put("G", src, "DevelopmentLength", 12)
        call("G", "Save", src.Save)
        put("G", src, "RatioAverageCount", 11)
        a = src.CustomAverages(2)
        put("G", a, "WeightType", 1); put("G", a, "PeriodsIncluded", 4); a.ResetName()
        a = src.CustomAverages(7)
        put("G", a, "AverageType", 6); put("G", a, "Formula", "(Average(1)+Average(2))/2"); put("G", a, "Name", "ZZ calc")
        call("G", "Save", src.Save)
        self._dress("G", src)
        tgt = self.add_method("G", METHOD_DFM, PREFIX + "GUI Target", new_type=True)
        put("G", tgt, "InputTriangle", self.triangle(TRI_ANNUAL_2))
        put("G", tgt, "OriginLength", 12)
        put("G", tgt, "DevelopmentLength", 12)
        put("G", tgt, "Notes", "ZZ target note")
        call("G", "Save", tgt.Save)
        self.reconnect()
        state = {"source": dfm_snapshot(self.dfm(PREFIX + "GUI Source")),
                 "target_before": dfm_snapshot(self.dfm(PREFIX + "GUI Target"))}
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, default=str)
        print(f"  snapshots written to {STATE_FILE}")

    def gui_compare(self):
        with open(STATE_FILE, encoding="utf-8") as handle:
            state = json.load(handle)
        after = dfm_snapshot(self.dfm(PREFIX + "GUI Target"))
        OBSERVED["GUI changed"] = diff(state["target_before"], after, "GUI target: before vs after Load Settings")
        OBSERVED["GUI still differs from source"] = diff(state["source"], after, "GUI source vs target after Load Settings")

    # ===== cleanup ==============================================================

    def delete_probe_objects(self):
        self.reconnect()
        deleted = []
        for getter in (self.rc.ResultSelections, self.rc.BFMethods, self.rc.DFMMethods):
            coll = getter()
            for item in [coll.Item(i) for i in range(1, coll.Count + 1)]:
                if str(item.Name).startswith(PREFIX):
                    name = str(item.Name)
                    ok, _ = call("cleanup", f"delete method {name!r}", item.Delete)
                    if ok:
                        deleted.append(name)
        self.reconnect()
        coll = self.rc.Vectors()
        for item in [coll.Item(i) for i in range(1, coll.Count + 1)]:
            if str(item.Name).startswith(PREFIX):
                call("cleanup", f"delete leftover vector {item.Name!r}", item.Delete)
        self.reconnect()
        types = self.project.DatasetTypes()
        for item in [types.Item(i) for i in range(1, types.Count + 1)]:
            if str(item.Name).startswith(PREFIX):
                call("cleanup", f"delete dataset type {item.Name!r}", item.Delete)
        self.reconnect()
        left = {
            "dfm": self.rc.DFMMethods().Count, "bf": self.rc.BFMethods().Count, "rs": self.rc.ResultSelections().Count,
            "triangles": self.rc.Triangles().Count, "vectors": self.rc.Vectors().Count,
            "types": self.project.DatasetTypes().Count,
            "zz_left": [str(v.Name) for coll in (self.rc.Vectors(), self.project.DatasetTypes())
                        for v in (coll.Item(i) for i in range(1, coll.Count + 1)) if str(v.Name).startswith(PREFIX)],
        }
        print(f"  left: {left}")
        OBSERVED["cleanup"] = {"deleted": deleted, "left": left}


CASES = [
    ("C", "C0 survey", "c0_survey"),
    ("C", "C1 create a DFM on an existing shared type", "c1_create_dfm"),
    ("C", "C2 create a DFM on a new dataset type", "c2_create_dfm_new_type"),
    ("C", "C3 create a BF", "c3_create_bf"),
    ("C", "C4 create a Result Selection", "c4_create_rs"),
    ("C", "V1 read the created methods back", "v1_verify_created"),
    ("D", "D1 change the input triangle", "d1_input_triangle"),
    ("D", "D2 change origin and development length", "d2_lengths"),
    ("D", "D3 grow and shrink the average rows", "d3_row_count"),
    ("D", "D4 each average row field", "d4_row_fields"),
    ("B", "B1 BF latest, % developed and priors", "b1_bf"),
    ("R", "R1 Result Selection datasets and weights", "r1_rs"),
    ("L", "L1 LoadMethod", "l1_load_method"),
]


def connect():
    cfg = json.load(open(CONFIG))["resq"]
    app = gencache.EnsureDispatch("ResQ3Automation.ResQApplication")
    app.ConnectByName(cfg["connection_name"], cfg["user_name"], cfg["password"])
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", nargs="+", metavar="GROUP", help="run only these groups (C D B R L) or case ids (C1 D3)")
    parser.add_argument("--keep", action="store_true", help="leave the probe objects in ResQ")
    parser.add_argument("--json", metavar="PATH", help="write the observations to this file")
    parser.add_argument("--gui-setup", action="store_true", help="create the GUI Load Settings source and target only")
    parser.add_argument("--gui-compare", action="store_true", help="compare the GUI target with its source")
    parser.add_argument("--cleanup", action="store_true", help="only delete every ZZ Probe object")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    wanted = {value.upper() for value in (args.only or [])}
    app = connect()
    probe = None
    try:
        probe = Probe(app)
        if args.gui_setup:
            section("GUI setup"); probe.gui_setup()
        elif args.gui_compare:
            section("GUI compare"); probe.gui_compare()
        elif not args.cleanup:
            for group, title, attr in CASES:
                case_id = title.split()[0]
                if wanted and group not in wanted and case_id not in wanted and case_id != "C0":
                    continue
                section(title)
                try:
                    getattr(probe, attr)()
                except Exception:  # noqa: BLE001
                    traceback.print_exc()
                    record(case_id, {"crashed": traceback.format_exc(limit=2)})
        if args.cleanup or not (args.keep or args.gui_setup or args.gui_compare):
            section("cleanup")
            try:
                probe.delete_probe_objects()
            except Exception:  # noqa: BLE001
                traceback.print_exc()
    finally:
        if probe is not None:
            try:
                probe.rc.UnloadChildren()
            except Exception:  # noqa: BLE001
                pass
        app.Disconnect()
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(OBSERVED, handle, indent=2, default=str)
        print(f"\nobservations written to {args.json}")


if __name__ == "__main__":
    main()
