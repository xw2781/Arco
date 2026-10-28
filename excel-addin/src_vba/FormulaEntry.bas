Option Private Module
Option Explicit

' SheetChange is raised for edits, not workbook opening or recalculation.
' Calculate the edited formulas inside the macro, then persist outside UDFs.
Public Sub LoadEnteredFormulas(ByVal target As Range)
    Dim book As Workbook, blocks As Collection, block As Range
    Dim oldLoading As Boolean, oldCancel As XlEnableCancelKey
    Dim started As Boolean, message As String
    If DatasetRefreshRunning() Or WorkbookRefreshRunning() Then Exit Sub
    Set book = target.Worksheet.Parent
    If book Is ThisWorkbook Then Exit Sub
    If target.Worksheet.Name = SNAPSHOT_SHEET Then Exit Sub
    oldLoading = disable_ufLoading
    oldCancel = Application.EnableCancelKey
    On Error GoTo Failed
    Set blocks = FindArcRhoFormulaBlocks(target)
    If blocks.Count = 0 Then Exit Sub
    cancelUpdate = False
    disable_ufLoading = True
    Application.EnableCancelKey = xlErrorHandler
    BeginDatasetRefresh book, target.Worksheet, True, target
    started = True

    ' Probe through the ordinary UDF request builder. A saved request needs no
    ' credential or capabilities check, even on a reader's first formula edit.
    For Each block In blocks
        block.Dirty
        block.Calculate
    Next block
    If DatasetRefreshNeedsGateway() Then
        EnsureGatewayCredential
        If Not GatewayIsConfigured() Then Err.Raise 5, , "This PC is not set up to load Arco data."
        If Not GatewayServesDatasetCsv() Then Err.Raise 5, , "Ask the Arco team to update the Arco Server."
        AllowDatasetRefreshFetch
        For Each block In blocks
            If cancelUpdate Then Err.Raise 18
            block.Dirty
            block.Calculate
            If Len(DatasetRefreshError()) > 0 Then Err.Raise 5, , DatasetRefreshError()
        Next block
    End If
    If cancelUpdate Then Err.Raise 18
    If DatasetRefreshHasResults() Then
        CommitDatasetRefresh
        message = "New formula data loaded. Save the workbook to share these values."
    End If
    If DatasetRefreshSkipped().Count > 0 Then
        message = "Skipped " & DatasetRefreshSkipped().Count & " dataset(s) not found in Arco; first: " & _
            DatasetRefreshSkipped().Items()(0) & " " & message
    End If
Finish:
    If started Then EndDatasetRefresh
    disable_ufLoading = oldLoading
    Application.EnableCancelKey = oldCancel
    cancelUpdate = False
    If Len(message) > 0 Then ShowStatus "Arco [" & book.Name & "]: " & message
    Exit Sub
Failed:
    message = "Unable to load the entered formula; saved data is unchanged. " & Err.Description
    Resume Finish
End Sub
