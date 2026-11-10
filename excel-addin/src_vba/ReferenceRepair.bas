Attribute VB_Name = "ReferenceRepair"
Option Private Module
Option Explicit

Public Const REFERENCE_ADDIN_FILE As String = "Arco.xlam"
Public Const DEFAULT_REFERENCE_PATH As String = "E:\Arco Server\Excel Add-ins\" & REFERENCE_ADDIN_FILE
Public Const RESQ_REFERENCE_PATH As String = "C:\Program Files\Willis Towers Watson\ResQ\Addins\ResQ.xlam"
Public Const RESQ_COMPUTER As String = "NE7SASWPN02"
Private repairing As Boolean

Public Function CanUseResQ() As Boolean
    CanUseResQ = StrComp(Environ$("COMPUTERNAME"), RESQ_COMPUTER, vbTextCompare) = 0
End Function

Public Function ReferenceTargetPath(ByVal targetIndex As Long) As String
    If targetIndex = 1 Then
        ReferenceTargetPath = RESQ_REFERENCE_PATH
    Else
        ReferenceTargetPath = DEFAULT_REFERENCE_PATH
    End If
End Function

Private Sub AddReferenceEdit(ByVal edits As Collection, ByVal target As Object, _
                             ByVal location As String, ByVal text As String, ByVal isName As Boolean, _
                             ByVal isArray As Boolean, ByVal protected As Boolean, _
                             ByVal targetPath As String, ByVal fixPath As Boolean, ByVal rename As Boolean, _
                             ByVal targetLoaded As Boolean, ByVal functionPrefix As String)
    Dim changed As String, entry As ReferenceEdit
    changed = RepairReferenceFormula(text, targetPath, fixPath, rename, targetLoaded, functionPrefix)
    If changed = text Then Exit Sub
    Set entry = New ReferenceEdit
    Set entry.Target = target
    entry.Location = location
    entry.After = changed
    entry.IsName = isName
    entry.IsArray = isArray
    entry.Status = "Ready"
    If protected Then entry.Status = "Not updated: unprotect this sheet or workbook first."
    If isArray And Len(changed) > 255 Then entry.Status = "Not updated: legacy array formula exceeds Excel's 255-character editing limit."
    edits.Add entry
End Sub

Public Function FindReferenceEdits(ByVal book As Workbook, ByVal targetPath As String, _
                                   ByVal fixPath As Boolean, ByVal rename As Boolean, _
                                   Optional ByVal showProgress As Boolean = False, _
                                   Optional ByVal functionPrefix As String = "Arco") As Collection
    Dim edits As New Collection, ws As Worksheet, blocks As Collection, block As Range
    Dim name As name, text As String, isArray As Boolean
    Dim sheetIndex As Long, sheetCount As Long, itemIndex As Long, body As String
    Dim loaded As Workbook
    If book Is Nothing Then Err.Raise 5, , "Open the workbook you want to repair."
    If book Is ThisWorkbook Or book.IsAddin Then Err.Raise 5, , "Select a report workbook first."
    ' Excel stores a loaded add-in by filename, expanding it on save/close.
    ' Use that spelling only when it resolves to the exact requested file.
    If fixPath And Len(targetPath) > 0 Then
        On Error Resume Next
        Set loaded = Application.Workbooks(Mid$(targetPath, InStrRev(targetPath, "\") + 1))
        On Error GoTo 0
        If Not loaded Is Nothing Then
            If StrComp(loaded.FullName, targetPath, vbTextCompare) <> 0 Then
                Err.Raise 5, , loaded.Name & " is already loaded from " & loaded.FullName & _
                    ". Load it from the selected target location first."
            End If
            targetPath = loaded.Name
        End If
    End If
    sheetCount = book.Worksheets.Count
    For Each ws In book.Worksheets
        sheetIndex = sheetIndex + 1
        If ws.Name <> SNAPSHOT_SHEET Then
            body = "Sheet " & sheetIndex & " of " & sheetCount & ": " & ws.Name
            RefreshProgress showProgress, "Finding add-in formulas ...", body, "Reading formula cells ...", _
                            (sheetIndex - 1) / sheetCount * 70
            If cancelUpdate Then Exit For
            Set blocks = FindArcRhoFormulaBlocks(ws.UsedRange, showProgress, _
                (sheetIndex - 1) / sheetCount * 70, 50 / sheetCount, True, body)
            If cancelUpdate Then Exit For
            itemIndex = 0
            For Each block In blocks
                isArray = block.HasArray
                If isArray Then text = CStr(block.FormulaArray) Else text = CStr(block.Formula2)
                AddReferenceEdit edits, block, ws.Name & "!" & block.Address, text, False, isArray, _
                                 ws.ProtectContents, targetPath, fixPath, rename, Not loaded Is Nothing, functionPrefix
                itemIndex = itemIndex + 1
                If itemIndex Mod 64 = 0 Or itemIndex = blocks.Count Then
                    RefreshProgress showProgress, "Checking add-in references ...", body, _
                        itemIndex & " / " & blocks.Count & " formula range(s); " & edits.Count & " change(s) found", _
                        ((sheetIndex - 1) * 70 + 50 + itemIndex / blocks.Count * 20) / sheetCount
                    If cancelUpdate Then Exit For
                End If
            Next block
        End If
        If cancelUpdate Then Exit For
    Next ws
    ' Workbook.Names includes worksheet-scoped names as well.
    itemIndex = 0
    For Each name In book.Names
        If cancelUpdate Then Exit For
        AddReferenceEdit edits, name, "Name: " & name.Name, name.RefersTo, True, False, _
                         book.ProtectStructure, targetPath, fixPath, rename, Not loaded Is Nothing, functionPrefix
        itemIndex = itemIndex + 1
        If itemIndex Mod 64 = 0 Or itemIndex = book.Names.Count Then
            RefreshProgress showProgress, "Checking defined names ...", book.Name, _
                itemIndex & " / " & book.Names.Count & " names checked", 70 + itemIndex / book.Names.Count * 5
        End If
    Next name
    Set FindReferenceEdits = edits
End Function

Public Function ApplyReferenceEdits(ByVal book As Workbook, ByVal edits As Collection, _
                                    Optional ByVal showProgress As Boolean = False) As Long
    Dim entry As ReferenceEdit, oldCalc As XlCalculation, oldEvents As Boolean
    Dim oldAlerts As Boolean, oldScreen As Boolean, oldSkip As Boolean, oldLoading As Boolean
    Dim oldCancel As XlEnableCancelKey, failure As String, itemIndex As Long
    If WorkbookRefreshRunning() Or DatasetRefreshRunning() Then Err.Raise 5, , "Wait for the current refresh to finish."
    If book.ReadOnly Then Err.Raise 5, , "The workbook is read-only. Save an editable copy first."
    oldCalc = Application.Calculation
    oldEvents = Application.EnableEvents
    oldAlerts = Application.DisplayAlerts
    oldScreen = Application.ScreenUpdating
    oldCancel = Application.EnableCancelKey
    oldSkip = skipDataProcess
    oldLoading = disable_ufLoading
    On Error GoTo Failed
    Application.EnableEvents = False
    Application.DisplayAlerts = False
    Application.ScreenUpdating = False
    Application.EnableCancelKey = xlErrorHandler
    Application.Calculation = xlCalculationManual
    skipDataProcess = True
    disable_ufLoading = True
    For Each entry In edits
        If itemIndex Mod 64 = 0 Then
            RefreshProgress showProgress, "Updating add-in references ...", entry.Location, _
                itemIndex & " / " & edits.Count & " checked; " & ApplyReferenceEdits & " updated", 75 + itemIndex / edits.Count * 20
        End If
        If cancelUpdate Then Exit For
        If entry.Apply Then ApplyReferenceEdits = ApplyReferenceEdits + 1
        itemIndex = itemIndex + 1
    Next entry
    skipDataProcess = oldSkip
    If ApplyReferenceEdits > 0 Then
        RefreshProgress showProgress, "Recalculating workbook formulas ...", book.Name, ApplyReferenceEdits & " updated", 95
        RecalculateWorkbookFormulas book
    End If
Finish:
    skipDataProcess = oldSkip
    disable_ufLoading = oldLoading
    Application.Calculation = oldCalc
    Application.EnableCancelKey = oldCancel
    Application.ScreenUpdating = oldScreen
    Application.DisplayAlerts = oldAlerts
    Application.EnableEvents = oldEvents
    If Len(failure) > 0 Then Err.Raise 5, , failure
    Exit Function
Failed:
    failure = Err.Description
    Resume Finish
End Function

' The form runs this after hiding its modal dialog, so the existing modeless
' progress form can repaint and its Cancel button stays available.
Public Function UpdateWorkbookReferences(ByVal book As Workbook, ByVal targetPath As String, _
                                         Optional ByVal functionPrefix As String = "Arco") As String
    Dim edits As Collection, entry As ReferenceEdit, updated As Long, details As String
    Dim oldCancel As XlEnableCancelKey, oldStatus As Variant
    If repairing Or WorkbookRefreshRunning() Or DatasetRefreshRunning() Then Err.Raise 5, , "Wait for the current update to finish."
    If book.ReadOnly Then Err.Raise 5, , "The workbook is read-only. Save an editable copy first."
    If functionPrefix = "ResQ" And Not CanUseResQ() Then
        Err.Raise 5, , "ResQ conversion is only available on " & RESQ_COMPUTER & "."
    End If
    If Len(Dir$(targetPath, vbNormal Or vbReadOnly Or vbHidden Or vbSystem)) = 0 Then
        Err.Raise 5, , "The selected add-in was not found on this PC: " & targetPath
    End If
    oldCancel = Application.EnableCancelKey
    oldStatus = Application.StatusBar
    On Error GoTo Failed
    repairing = True
    cancelUpdate = False
    Application.EnableCancelKey = xlErrorHandler
    Show_ufProgressBar
    ufProgressBar.Caption = "Updating Add-in References"
    Set edits = FindReferenceEdits(book, targetPath, True, True, True, functionPrefix)
    If cancelUpdate Then
        UpdateWorkbookReferences = "Update cancelled; no references were changed."
        GoTo Finish
    End If
    updated = ApplyReferenceEdits(book, edits, True)
    If cancelUpdate Then
        UpdateWorkbookReferences = "Update cancelled. " & updated & " updated; " & edits.Count - updated & " not updated."
    ElseIf edits.Count = 0 Then
        UpdateWorkbookReferences = "No references need updating."
    Else
        UpdateWorkbookReferences = updated & " updated; " & edits.Count - updated & " not updated."
    End If
    If updated > 0 Then UpdateWorkbookReferences = UpdateWorkbookReferences & " Save the workbook to keep the changes."
    If functionPrefix = "ResQ" Then UpdateWorkbookReferences = UpdateWorkbookReferences & vbCrLf & _
        "Open the workbook on " & RESQ_COMPUTER & " to calculate the ResQ formulas."
    For Each entry In edits
        If entry.Status <> "Updated" And entry.Status <> "Ready" Then details = details & vbCrLf & entry.Location & ": " & entry.Status
    Next entry
    UpdateWorkbookReferences = UpdateWorkbookReferences & details
    If Not cancelUpdate Then RefreshProgress True, "Update complete", book.Name, updated & " updated", 100
Finish:
    Unload ufProgressBar
    Application.EnableCancelKey = oldCancel
    Application.StatusBar = oldStatus
    cancelUpdate = False
    repairing = False
    Exit Function
Failed:
    UpdateWorkbookReferences = "Unable to finish updating references: " & Err.Description
    Resume Finish
End Function
