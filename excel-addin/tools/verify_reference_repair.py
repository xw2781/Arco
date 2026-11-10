"""Test reference repair in private Excel with synthetic add-ins and workbooks.

Run with py -3.10 -B excel-addin/tools/verify_reference_repair.py.
No live add-in, project data, user workbook or configuration is changed.
"""

from __future__ import annotations

import os
import re
import tempfile
import time
from pathlib import Path

from verify_built_addin import compile_project, replace_procedure
from verify_workbook_snapshots import SOURCE, TEST_ROOT, check, excel_session, runtime


def run(excel, name, *args):
    return excel.Run(f"'ArcRhoSnapshotSmoke.xlsm'!ReferenceRepairSmokeHelpers.{name}", *args)


def parser_checks(excel):
    target = r"E:\Arco Server\Excel Add-ins\Arco.xlam"
    qualified = f"'{target}'!ArcoVec"
    examples = [
        ('=ArcRho.xlam!ArcRhoVec($A$2,C6)', f'={qualified}($A$2,C6)'),
        (r"='C:\Program Files (x86)\Willis Towers Watson\ResQ\Addins\ResQ.xlam'!ResQTri(A1,B1)",
         f"='{target}'!ArcoTri(A1,B1)"),
        (r"='C:\Program Files\Willis Towers Watson\ResQ\Addins\ResQ.xlam'!ResQVec(A1,B1)",
         f'={qualified}(A1,B1)'),
        (r"='\\Ne7saswpn02\E\Arco Server\Excel Add-ins\ArcRho.xlam'!ArcoVec(A1,B1)",
         f'={qualified}(A1,B1)'),
        ('=SUM(ARCRHO_BETA.xlam!ArcRhoVec(A1,B1))+ResQVec(A2,B2)',
         f'=SUM({qualified}(A1,B1))+{qualified}(A2,B2)'),
        ('=IF(A1="ResQVec(""text"")",ADASVec(A1,B1),0)',
         f'=IF(A1="ResQVec(""text"")",{qualified}(A1,B1),0)'),
        ('=ResQVecExtra(1)+MyArcRhoVec(2)+ResQUnknown(3)',
         '=ResQVecExtra(1)+MyArcRhoVec(2)+ResQUnknown(3)'),
        ("='Other.xlam'!ArcRhoVec(1)+Other.xlam!ResQVec(2)",
         "='Other.xlam'!ArcRhoVec(1)+Other.xlam!ResQVec(2)"),
        ("='ArcRhoVec(1)'!A1+Table1[[#Headers],[ResQVec(1)]]",
         "='ArcRhoVec(1)'!A1+Table1[[#Headers],[ResQVec(1)]]"),
        ('=@_xlfn._xludf.ArcRhoVec(A1,B1)', f'=@{qualified}(A1,B1)'),
        ("='C:\\O''Brien\\[ArcRho.xlam]'!arcRHOVec (A1,B1)", f'={qualified} (A1,B1)'),
        ('=[ArcRho.xlam]!ArcRhoVec(A1,B1)', f'={qualified}(A1,B1)'),
    ]
    for before, after in examples:
        actual = run(excel, "Rewrite", before, target, True, True)
        check(actual == after, f"rewrite {before}")
        check(run(excel, "Rewrite", after, target, True, True) == after, "repair is idempotent")
    check(run(excel, "Rewrite", '=ArcRho.xlam!ArcRhoVec(1)', target, False, True)
          == '=ArcRho.xlam!ArcoVec(1)', "rename-only retains the existing qualifier")
    check(run(excel, "Rewrite", '=ArcRho.xlam!ArcRhoVec(1)', target, True, False)
          == f"='{target}'!ArcRhoVec(1)", "path-only preserves the function name")
    check(run(excel, "Rewrite", '=ArcRho.xlam!ArcRhoVec(1)', '', True, True)
          == '=ArcoVec(1)', "unqualified Arco formulas can be produced")
    source = (SOURCE / "ArcRhoFunctions.bas").read_text(encoding="cp1252")
    names = re.findall(r"^(?:Public )?Function (Arco\w+)\(", source, re.M)
    for name in names:
        for prefix in ("ResQ", "ArcRho", "ADAS", "Arco"):
            check(run(excel, "MapFunction", prefix + name[4:]) == name,
                  f"{prefix + name[4:]} maps to the current public function")
        resq_name = "ResQ" + name[4:]
        expected = f"='{target}'!{resq_name}(A1)"
        check(run(excel, "RewriteForResQ", f"={name}(A1)", target) == expected,
              f"{name} converts to {resq_name}")
    old32 = r"='C:\Program Files (x86)\Willis Towers Watson\ResQ\Addins\ResQ.xlam'!ResQVec(A1)"
    new64 = r"C:\Program Files\Willis Towers Watson\ResQ\Addins\ResQ.xlam"
    check(run(excel, "RewriteForResQ", old32, new64) == f"='{new64}'!ResQVec(A1)",
          "32-bit ResQ references retarget to 64-bit ResQ")
    check(run(excel, "RewriteForResQ", '=IF(TRUE,"ArcoVec(A1)",ArcoVec(A1))', new64)
          == f'=IF(TRUE,"ArcoVec(A1)",\'{new64}\'!ResQVec(A1))', "ResQ conversion preserves quoted text")


def fake_addin(excel, path, prefix):
    book = excel.Workbooks.Add()
    component = book.VBProject.VBComponents.Add(1)
    component.Name = "SyntheticFunctions"
    component.CodeModule.AddFromString(
        f"Public Function {prefix}Vec(ParamArray args()) As Variant\r\n"
        f"    {prefix}Vec = Array(10, 20)\r\nEnd Function\r\n"
        f"Public Function {prefix}VecCell(ParamArray args()) As Variant\r\n"
        f"    {prefix}VecCell = 7\r\nEnd Function\r\n"
    )
    book.IsAddin = True
    book.SaveAs(str(path), 55)
    # Saving an ordinary workbook as XLAM creates the file but leaves the
    # open workbook's identity unchanged until it is reopened.
    book.Close(False)
    book = excel.Workbooks.Open(str(path), 0, False)
    return book


def workbook_checks(excel, directory):
    old = fake_addin(excel, directory / "ResQ.xlam", "ResQ")
    target = directory / "Arco.xlam"
    new = fake_addin(excel, target, "Arco")
    excel.Calculation = -4135
    report = excel.Workbooks.Add()
    sheet = report.Worksheets(1)
    sheet.Name = "Report"
    hidden = report.Worksheets.Add(After=sheet)
    hidden.Name = "Hidden"
    hidden.Visible = 0
    other = excel.Workbooks.Add()
    other.Worksheets(1).Range("A1").Formula = "=ResQ.xlam!ResQVecCell(1)"
    sheet.Range("A1").Formula2 = "=ResQ.xlam!ResQVecCell(1)"
    sheet.Range("B1:C1").FormulaArray = "=ResQ.xlam!ResQVec(1)"
    sheet.Range("B3").Formula2 = "=ResQ.xlam!ResQVec(1)"
    sheet.Range("A5").Value2 = "ResQVec(1)"
    sheet.Range("A6").Formula2 = '=IF(TRUE,"ResQVec(1)",0)'
    sheet.Range("A8").Formula2 = "=NamedResult+1"
    sheet.Range("A9").Formula2 = "=Hidden!A2+1"
    hidden.Range("A1").Formula2 = "=ResQ.xlam!ResQVecCell(1)"
    hidden.Range("A2").Formula2 = "=Report!A8+1"
    report.Names.Add(Name="NamedResult", RefersTo="=ResQ.xlam!ResQVecCell(1)")
    sheet.Names.Add(Name="Report!LocalResult", RefersTo="=ResQ.xlam!ResQVecCell(1)")
    old.Close(False)
    untouched = other.Worksheets(1).Range("A1").Formula2
    report.Activate()
    before = sheet.Range("A1").Formula2
    count = run(excel, "ScanRepair", report.Name, str(target))
    check(count == 6 and sheet.Range("A1").Formula2 == before,
          "scan finds scalar, array, spill, hidden-sheet and both scoped names without writes")
    excel.EnableEvents = True
    prior_state = (excel.EnableEvents, excel.Calculation, excel.DisplayAlerts)
    check(run(excel, "ApplyRepair", report.Name) == count, "all discovered repairs apply")
    state = (excel.EnableEvents, excel.Calculation, excel.DisplayAlerts)
    check(state == prior_state, f"repair restores calculation, events and alerts: {prior_state} -> {state}")
    excel.EnableEvents = False
    excel.DisplayAlerts = False
    check(sheet.Range("A1").Value2 == 7 and sheet.Range("A9").Value2 == 10,
          "repaired functions and cross-sheet dependent formulas recalculate in manual mode")
    check(sheet.Range("B1:C1").HasArray and sheet.Range("B1:C1").Value2 == ((10.0, 20.0),),
          "legacy arrays retain their rectangle and values")
    check(sheet.Range("B3").HasSpill and sheet.Range("C3").Value2 == 20,
          "dynamic arrays still spill")
    check(sheet.Range("A5").Value2 == "ResQVec(1)" and sheet.Range("A6").Value2 == "ResQVec(1)",
          "text cells and formula string literals are preserved")
    check(other.Worksheets(1).Range("A1").Formula2 == untouched, "another open workbook is unchanged")
    remaining = run(excel, "ScanRepair", report.Name, str(target))
    check(remaining == 0, "a repaired workbook needs no second repair: " + run(excel, "RepairStatuses"))
    check(run(excel, "ScanRepair", report.Name, str(directory / "another" / "Arco.xlam")) == -1
          and "already loaded" in run(excel, "ScanError"), "conflicting loaded paths give actionable feedback")
    report.SaveAs(str(directory / "repaired.xlsx"), 51)
    report.Close(False)
    new.Close(False)
    report = excel.Workbooks.Open(str(directory / "repaired.xlsx"), 0, False)
    links = report.LinkSources(1)
    check(links and all(Path(link) == target for link in links), "saved workbook links point only to the chosen add-in")
    report.Close(False)
    other.Close(False)


def blocked_checks(excel, directory):
    report = excel.Workbooks.Add()
    sheet = report.Worksheets(1)
    sheet.Range("A1").Formula2 = "=ArcRhoVec(1)"
    sheet.Protect("test")
    found = run(excel, "ScanRepair", report.Name, str(directory / "Arco.xlam"))
    status = run(excel, "RepairStatuses")
    check(run(excel, "ApplyRepair", report.Name) == 0 and "unprotect" in status,
          f"protected formulas are reported without changes ({found}): {status}; {sheet.Range('A1').Formula2}")
    sheet.Unprotect("test")
    sheet.Cells.Clear()
    sheet.Range("B1:C1").FormulaArray = '=IF(TRUE,ArcRhoVec(1),"' + 'x' * 170 + '")'
    original = sheet.Range("B1").FormulaArray
    run(excel, "ScanRepair", report.Name, str(directory / "Arco.xlam"))
    check(run(excel, "ApplyRepair", report.Name) == 0 and sheet.Range("B1").FormulaArray == original
          and "255-character" in run(excel, "RepairStatuses"), "long legacy arrays remain intact and report the Excel limit")
    report.Activate()
    check(run(excel, "ShowRepairForm") == "Arco Excel add-in|True", "Arco is the default target and Update is ready immediately")
    check(run(excel, "FormFits"), "all simplified form controls fit inside the client area")
    controls = run(excel, "FormControls").split("|")
    check(not set(controls) & {"cmdPreview", "cmdClose", "cmdLoaded", "lstChanges", "txtBefore", "txtAfter", "txtPath", "cmdBrowse"},
          "the form has no preview, Close button, developer shortcut or editable path")
    check(run(excel, "FormTarget", 0).startswith("Arco Excel add-in|E:\\Arco Server"), "Arco target uses the mapped release path")
    allowed = os.environ["COMPUTERNAME"].upper() == "NE7SASWPN02"
    check(run(excel, "HostAllowsResQ") == allowed and run(excel, "FormResQEnabled") == allowed,
          "ResQ option availability follows the actual computer name")
    if not allowed:
        check("Only available on NE7SASWPN02" == run(excel, "FormResQHint")
              and run(excel, "FormTarget", 1).startswith("Arco Excel add-in|"),
              "unavailable ResQ is muted, explained and cannot be selected")
        before = sheet.Range("B1").FormulaArray
        denied = run(excel, "UpdateReferences", report.Name, str(directory / "ResQ.xlam"), "ResQ")
        check("only available on NE7SASWPN02" in denied and sheet.Range("B1").FormulaArray == before,
              "the update routine also rejects direct ResQ conversion on a client")
    run(excel, "CloseRepairForm")
    check(run(excel, "ShowRepairForm") == "Arco Excel add-in|True", "opening the form again always defaults to Arco")
    run(excel, "CloseRepairForm")
    report.Close(False)


def progress_checks(excel, directory, runtime_book):
    # Observe the real progress form at repaint, and click its real Cancel
    # control at a chosen phase. The production scan/update paths stay intact.
    module = runtime_book.VBProject.VBComponents("ufProgressBar").CodeModule
    code = module.Lines(1, module.CountOfLines)
    module.DeleteLines(1, module.CountOfLines)
    module.AddFromString(code.replace("Me.Repaint", "Me.Repaint\r\n    ObserveReferenceProgress Me"))
    compile_project(excel, runtime_book)
    book = excel.Workbooks.Add()
    book.Worksheets.Add()
    sheets = [book.Worksheets(index) for index in (1, 2)]
    for index, sheet in enumerate(sheets):
        sheet.Name = f"Large{index + 1}"
        sheet.Range("A1:BH1000").Formula = "=ROW()+COLUMN()"
        sheet.Range("BJ1:CC1000").FormulaArray = "=ArcRhoVec(1)"
        sheet.Range("A1002").Formula = "=ArcRhoVecCell(1)"
    target_path = directory / "Arco.xlam"
    run(excel, "StartProgressCheck", "Finding add-in formulas", 0)
    result = run(excel, "UpdateReferences", book.Name, str(target_path), "Arco")
    check(result == "Update cancelled; no references were changed."
          and all("ArcRhoVec" in sheet.Range("BJ1").FormulaArray for sheet in sheets),
          "Cancel during batched discovery leaves all formulas unchanged: " + result)
    check(run(excel, "RepairIdle"), "cancellation closes progress and clears its shared cancellation flag")

    run(excel, "StartProgressCheck")
    started = time.monotonic()
    result = run(excel, "UpdateReferences", book.Name, str(target_path), "Arco")
    elapsed = time.monotonic() - started
    print(f"INFO reference repair scanned 160,002 formula cells in {elapsed:.2f}s", flush=True)
    check(result.startswith("4 updated; 0 not updated"), "large workbook updates all four formula ranges: " + result)
    check(all("ArcoVec" in sheet.Range("BJ1").FormulaArray and sheet.Range("BJ1:CC1000").HasArray for sheet in sheets),
          "large legacy arrays update once and retain their original rectangles")
    log = run(excel, "ReadProgressLog")
    rows = [row.split("|") for row in log.splitlines()]
    percentages = [float(row[-1].strip("%")) for row in rows]
    check("Sheet 1 of 2: Large1" in log and "Sheet 2 of 2: Large2" in log
          and "cells checked" in log and "Updating add-in references" in log
          and percentages == sorted(percentages) and percentages[-1] == 100,
          "progress shows each sheet, cell counts and update phase with increasing percentages")
    check(run(excel, "RepairIdle"), "completion unloads the progress form")
    book.Close(False)

    book = excel.Workbooks.Add()
    sheet = book.Worksheets(1)
    sheet.Range("A1:A200").Formula = "=ArcRhoVecCell(1)"
    run(excel, "StartProgressCheck", "Updating add-in references", 75)
    result = run(excel, "UpdateReferences", book.Name, str(target_path), "Arco")
    check(result.startswith("Update cancelled. 64 updated; 136 not updated.")
          and "ArcoVecCell" in sheet.Range("A64").Formula
          and "ArcRhoVecCell" in sheet.Range("A65").Formula,
          "Cancel during updates stops at the next batch and reports partial changes: " + result)
    check(run(excel, "RepairIdle"), "partial cancellation also restores idle state")
    book.Close(False)


def form_update_checks(excel, directory, runtime_book):
    # Substitute only deployment locations with synthetic add-ins, then run
    # the production form's selection, button and update handler.
    module = runtime_book.VBProject.VBComponents("ReferenceRepair").CodeModule
    replace_procedure(module, "CanUseResQ", "Public Function CanUseResQ() As Boolean\r\n    CanUseResQ = True\r\nEnd Function")
    # Simulate the sole ResQ host in this isolated runtime; the production
    # host gate was tested above against this workstation's actual identity.
    book = excel.Workbooks.Add()
    run(excel, "ShowRepairForm")
    check(run(excel, "FormResQEnabled") and r"C:\Program Files\Willis Towers Watson\ResQ\Addins\ResQ.xlam" in run(excel, "FormTarget", 1),
          "on the ResQ host the dropdown selects the 64-bit installation")
    run(excel, "CloseRepairForm")
    book.Close(False)
    replace_procedure(module, "ReferenceTargetPath", "\r\n".join((
        "Public Function ReferenceTargetPath(ByVal targetIndex As Long) As String",
        f'    If targetIndex = 1 Then ReferenceTargetPath = "{directory / "ResQ.xlam"}" Else ReferenceTargetPath = "{directory / "Arco.xlam"}"',
        "End Function",
    )))
    book = excel.Workbooks.Add()
    sheet = book.Worksheets(1)
    sheet.Range("A1").Formula = "=ArcRhoVecCell(1)"
    run(excel, "StartProgressCheck")
    run(excel, "ShowRepairForm")
    check(run(excel, "FormApply", 0).startswith("1 updated; 0 not updated"), "Update converts to Arco directly without preview")
    run(excel, "CloseRepairForm")
    run(excel, "ShowRepairForm")
    check(run(excel, "FormApply", 1).startswith("1 updated; 0 not updated")
          and "ResQVecCell" in sheet.Range("A1").Formula, "ResQ dropdown choice updates path and function together")
    run(excel, "CloseRepairForm")
    form = runtime_book.VBProject.VBComponents("ufAddinReferences").CodeModule
    form.AddFromString("Private Sub UserForm_Activate()\r\n    DriveRepairDialog Me\r\nEnd Sub")
    check(run(excel, "RunRepairDialog").startswith("1 updated; 0 not updated")
          and "ArcoVecCell" in sheet.Range("A1").Formula,
          "the real modal dialog hides for progress and reopens with its result")
    book.Close(False)


def main():
    created_root = not TEST_ROOT.exists()
    TEST_ROOT.mkdir(exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="excel-references-", dir=TEST_ROOT) as scratch:
            with excel_session() as excel:
                book = runtime(excel, Path(scratch))
                for name in ("ReferenceFormulaRepair.bas", "ReferenceEdit.cls", "ReferenceRepair.bas", "ufAddinReferences.frm"):
                    book.VBProject.VBComponents.Import(str(SOURCE / name))
                book.VBProject.VBComponents.Import(str(Path(__file__).with_name("reference_repair_smoke_helpers.bas")))
                compile_project(excel, book)
                parser_checks(excel)
                workbook_checks(excel, Path(scratch))
                blocked_checks(excel, Path(scratch))
                progress_checks(excel, Path(scratch), book)
                form_update_checks(excel, Path(scratch), book)
    finally:
        if created_root and TEST_ROOT.exists() and not any(TEST_ROOT.iterdir()):
            TEST_ROOT.rmdir()
    print("Reference repair COM checks passed.", flush=True)


if __name__ == "__main__":
    main()
