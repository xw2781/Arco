Option Private Module
Option Explicit

Private Const DATASET_NOT_FOUND_TEXT As String = "(dataset not found)"
Private refreshBook As Workbook
Private refreshSheet As Worksheet
Private refreshResults As Object
Private refreshFailure As String
Private refreshSkipped As Object
Private committing As Boolean
Private refreshTarget As Range
Private missingOnly As Boolean
Private fetchAllowed As Boolean
Private needsGateway As Boolean

Public Sub BeginDatasetRefresh(ByVal book As Workbook, Optional ByVal sheet As Worksheet, _
                               Optional ByVal onlyMissing As Boolean = False, Optional ByVal target As Range)
    If Not refreshBook Is Nothing Then Err.Raise 5, , "An Arco refresh is already running."
    SnapshotPrepare book
    Set refreshBook = book
    Set refreshSheet = sheet
    Set refreshTarget = target
    Set refreshResults = CreateObject("Scripting.Dictionary")
    refreshFailure = ""
    Set refreshSkipped = CreateObject("Scripting.Dictionary")
    committing = False
    missingOnly = onlyMissing
    fetchAllowed = Not onlyMissing
    needsGateway = False
    datasetRequestCount = 0
    datasetFetchCount = 0
    datasetHitCount = 0
End Sub

Public Sub EndDatasetRefresh()
    Set refreshBook = Nothing
    Set refreshSheet = Nothing
    Set refreshResults = Nothing
    Set refreshTarget = Nothing
    committing = False
End Sub

Public Function DatasetRefreshNeedsGateway() As Boolean
    DatasetRefreshNeedsGateway = needsGateway
End Function

Public Sub AllowDatasetRefreshFetch()
    fetchAllowed = True
End Sub

Public Function DatasetRefreshHasResults() As Boolean
    If Not refreshResults Is Nothing Then DatasetRefreshHasResults = (refreshResults.Count > 0)
End Function

Public Function DatasetRefreshError() As String
    DatasetRefreshError = refreshFailure
End Function

Public Function DatasetRefreshSkipped() As Object
    Set DatasetRefreshSkipped = refreshSkipped
End Function

' Outside a refresh, a cell whose dataset the last refresh did not find keeps
' saying so instead of asking for another refresh.
Public Function DatasetNotFoundText(ByVal requestKey As String) As String
    If notFoundKeys.Exists(requestKey) Then DatasetNotFoundText = DATASET_NOT_FOUND_TEXT
End Function

Private Function notFoundKeys() As Object
    Static keys As Object
    If keys Is Nothing Then Set keys = CreateObject("Scripting.Dictionary")
    Set notFoundKeys = keys
End Function

Public Function DatasetRefreshRunning() As Boolean
    DatasetRefreshRunning = Not refreshBook Is Nothing
End Function

Public Function DatasetRefreshOwnsWorkbook(ByVal book As Workbook) As Boolean
    If refreshBook Is Nothing Then Exit Function
    DatasetRefreshOwnsWorkbook = (book Is refreshBook)
End Function

Public Function DatasetRefreshInScope(ByVal book As Workbook) As Boolean
    Dim caller As Object
    If refreshBook Is Nothing Then Exit Function
    If committing Then Exit Function
    If Not book Is refreshBook Then Exit Function
    If refreshSheet Is Nothing And refreshTarget Is Nothing Then
        DatasetRefreshInScope = True
        Exit Function
    End If
    On Error Resume Next
    Set caller = Application.Caller
    On Error GoTo 0
    If Not refreshSheet Is Nothing Then
        If TypeOf caller Is Excel.Range Then
            If Not caller.Worksheet Is refreshSheet Then Exit Function
        End If
    End If
    If Not refreshTarget Is Nothing Then
        If Not TypeOf caller Is Excel.Range Then Exit Function
        If Application.Intersect(caller, refreshTarget) Is Nothing Then Exit Function
    End If
    DatasetRefreshInScope = True
End Function

Public Function RefreshDataset(ByVal funcArgs As String, ByVal requestKey As String) As Variant
    Dim values As Variant, csvText As String, message As String, unavailable As Boolean
    On Error GoTo Failed
    If refreshResults.Exists(requestKey) Then
        datasetHitCount = datasetHitCount + 1
        RefreshDataset = refreshResults(requestKey)
        Exit Function
    End If
    If missingOnly Then
        If SnapshotRead(refreshBook, requestKey, values) Then
            datasetHitCount = datasetHitCount + 1
            RefreshDataset = values
            Exit Function
        End If
    End If
    If Not fetchAllowed Then
        needsGateway = True
        RefreshDataset = "(Arco: loading this formula's data...)"
        Exit Function
    End If
    If cancelUpdate Then
        RefreshDataset = "(Arco refresh cancelled.)"
        Exit Function
    End If
    If Len(refreshFailure) > 0 Then
        RefreshDataset = "(" & refreshFailure & ")"
        Exit Function
    End If
    If refreshSkipped.Exists(requestKey) Then
        RefreshDataset = DATASET_NOT_FOUND_TEXT
        Exit Function
    End If
    datasetFetchCount = datasetFetchCount + 1
    If GatewayDatasetCsv(funcArgs, csvText, message, unavailable) Then
        values = DataArrayFromText(csvText)
        If IsArray(values) Then
            refreshResults(requestKey) = values
            If notFoundKeys.Exists(requestKey) Then notFoundKeys.Remove requestKey
            RefreshDataset = values
            Exit Function
        End If
        message = "Arco Server answered without a data array."
    End If
    ' A dataset Arco has no data for fails only its own formulas; the rest refresh.
    If unavailable Then
        refreshSkipped(requestKey) = message
        notFoundKeys(requestKey) = True
        RefreshDataset = DATASET_NOT_FOUND_TEXT
        Exit Function
    End If
    refreshFailure = message
    RefreshDataset = "(" & message & ")"
    Exit Function
Failed:
    refreshFailure = "Arco refresh failed: " & Err.Description
    RefreshDataset = "(" & refreshFailure & ")"
End Function

Public Sub CommitDatasetRefresh(Optional ByVal replaceAll As Boolean = False)
    Dim number As Long, description As String
    If refreshBook Is Nothing Then Err.Raise 5, , "No Arco refresh is running."
    If cancelUpdate Or Len(refreshFailure) > 0 Then Err.Raise 5, , "The Arco refresh did not finish."
    On Error GoTo Failed
    committing = True
    SnapshotCommit refreshBook, refreshResults, replaceAll
    committing = False
    Exit Sub
Failed:
    number = Err.Number: description = Err.Description
    committing = False
    Err.Raise number, "CommitDatasetRefresh", description
End Sub
