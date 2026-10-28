
Option Private Module
Option Explicit

Public Const ARCRHO_VERSION As String = "4.2.4"

' The workbook sheet that carries the default project name. A workbook set up
' by an earlier version, or by ResQ itself, holds the ResQ spelling instead.
' VBA honours module-level declarations only above the first procedure, so
' these stay here rather than beside SettingsSheet.
Public Const SETTINGS_SHEET_NAME As String = "Arco Settings"
Public Const LEGACY_SETTINGS_SHEET_NAME As String = "ResQ Settings"

' User-specific config (C:\Users\...\AppData\Local\ArcRho\config.txt)
Public configDir As String
Public configPath As String
Public disable_ufLoading As Boolean
Public teamProfile As String
Public debugMode As Boolean
Public disableProgressBar As Boolean

' Internal Controls
Public disableRequest As Boolean
Public disableWaitTime As Boolean
Public skipDataProcess As Boolean
Public maxWaitTime As Single
Public errCount As Integer
Public lastRequestInfo As String

Public processedCells As New Collection
Public processedArrays As New Collection
Public cancelUpdate As Boolean
Public pendingUpdate As Boolean
Public disableWatcher As Boolean

Public triangle_tool_row As Long
Public triangle_tool_col As Long

' Counts the dataset requests formulas make and the reads GetDataset actually
' performs, for the check in excel-addin\tools\check_dataset_cache.md.
Public datasetRequestCount As Long
Public datasetFetchCount As Long
Public datasetHitCount As Long

Public Function FirstExistingPath(ParamArray paths() As Variant) As String
    Dim i As Long
    For i = LBound(paths) To UBound(paths)
        If Len(Dir$(CStr(paths(i)), vbNormal Or vbReadOnly Or vbHidden Or vbSystem Or vbDirectory)) > 0 Then
            FirstExistingPath = CStr(paths(i))
            Exit Function
        End If
    Next i
    FirstExistingPath = CStr(paths(LBound(paths)))
End Function

Public Function NormalizeDatasetName(ByVal value As String) As String
    NormalizeDatasetName = Trim$(value)
    Do While InStr(1, NormalizeDatasetName, "  ", vbBinaryCompare) > 0
        NormalizeDatasetName = Replace$(NormalizeDatasetName, "  ", " ")
    Loop
End Function

Public Function ProductRootPath() As String
    Dim addinDir As String
    addinDir = ThisWorkbook.Path

    If EndsWithText(addinDir, "\Excel Add-ins\beta") Then
        ProductRootPath = Left$(addinDir, Len(addinDir) - Len("\Excel Add-ins\beta"))
        Exit Function
    End If

    If EndsWithText(addinDir, "\Excel Add-ins") Then
        ProductRootPath = Left$(addinDir, Len(addinDir) - Len("\Excel Add-ins"))
        Exit Function
    End If

    ProductRootPath = "\\Ne7saswpn02\e\ArcRho Server"
End Function

Private Function EndsWithText(ByVal value As String, ByVal suffix As String) As Boolean
    If Len(value) < Len(suffix) Then
        EndsWithText = False
    Else
        EndsWithText = (StrComp(Right$(value, Len(suffix)), suffix, vbTextCompare) = 0)
    End If
End Function

Public Function ProductPath(ByVal relativePath As String) As String
    If Left$(relativePath, 1) = "\" Then relativePath = Mid$(relativePath, 2)
    ProductPath = ProductRootPath() & "\" & relativePath
End Function

Private Sub InitConfigPaths()
    configDir = Environ$("LOCALAPPDATA") & "\ArcRho"
    configPath = configDir & "\config.txt"
End Sub

Public Function GetDataset(funcArgs As String) As Variant
    Dim book As Workbook, values As Variant, requestKey As String
    On Error GoTo Failed
    If skipDataProcess Then Exit Function
    Set book = CallerWorkbook()
    requestKey = SnapshotRequestKey(funcArgs)
    datasetRequestCount = datasetRequestCount + 1
    If DatasetRefreshInScope(book) Then
        GetDataset = RefreshDataset(funcArgs, requestKey)
    ElseIf SnapshotRead(book, requestKey, values) Then
        datasetHitCount = datasetHitCount + 1
        GetDataset = values
    Else
        GetDataset = DatasetNotFoundText(requestKey)
        If Len(GetDataset) = 0 Then GetDataset = SNAPSHOT_REFRESH_REQUIRED
    End If
    Exit Function
Failed:
    GetDataset = "(Arco: " & Err.Description & ")"
End Function

Public Sub LoadConfig()
    Dim line As String, parts As Variant
    Dim fileVersion As String
    Dim f As Integer

    InitConfigPaths

    ' Ensure config dir
    If Dir(configDir, vbDirectory) = "" Then
        MkDir configDir
    End If

    ' -------------------------
    ' Check existing config version
    ' -------------------------
    If Dir(configPath) <> "" Then
        f = FreeFile
        Open configPath For Input As #f

        Do While Not EOF(f)
            Line Input #f, line
            line = Trim$(line)

            If InStr(line, "=") > 0 Then
                parts = Split(line, "=")
                If LCase$(Trim$(parts(0))) = "version" Then
                    fileVersion = Trim$(parts(1))
                    Exit Do
                End If
            End If
        Loop

        Close #f

        ' Version mismatch ? delete config
        If fileVersion <> ARCRHO_VERSION Then
            Kill configPath
        End If
    End If

    ' -------------------------
    ' Create config if missing
    ' -------------------------
    If Dir(configPath) = "" Then
        f = FreeFile
        Open configPath For Output As #f
        Print #f, "version = " & ARCRHO_VERSION
        Print #f, "disable_ufLoading = False"
        Print #f, "teamProfile = Default"
        Print #f, "debugMode = False"
        Print #f, "disableProgressBar = False"
        Close #f
    End If

    ' -------------------------
    ' Load config values
    ' -------------------------
    f = FreeFile
    Open configPath For Input As #f

    Do While Not EOF(f)
        Line Input #f, line
        line = Trim$(line)

        If InStr(line, "=") > 0 Then
            parts = Split(line, "=")

            Select Case LCase$(Trim$(parts(0)))
                Case "version"
                    ' ignore, already handled

                Case "disable_ufloading"
                    disable_ufLoading = CBool(Trim$(parts(1)))

                Case "teamprofile"
                    teamProfile = Trim$(parts(1))

                Case "debugmode"
                    debugMode = CBool(Trim$(parts(1)))

                Case "disableprogressbar"
                    disableProgressBar = CBool(Trim$(parts(1)))

            End Select
        End If
    Loop

    Close #f

End Sub

Public Sub UpdateConfigValue(ByVal keyName As String, ByVal newValue As String)
    Dim lines() As String, temp As String
    Dim f As Integer, i As Long

    InitConfigPaths

    ' Read all lines
    f = FreeFile()
    Open configPath For Input As #f
    lines = Split(Input$(LOF(f), f), vbCrLf)
    Close #f

    ' Modify the specific key
    For i = LBound(lines) To UBound(lines)
        temp = Trim(lines(i))
        If InStr(temp, "=") > 0 Then
            If LCase$(Trim$(Split(temp, "=")(0))) = LCase$(keyName) Then
                lines(i) = keyName & " = " & newValue
            End If
        End If
    Next i

    ' Rewrite file
    f = FreeFile()
    Open configPath For Output As #f
    For i = LBound(lines) To UBound(lines)
        Print #f, lines(i)
    Next i
    Close #f
End Sub

Public Function ReadUtf8TextFile(ByVal filePath As String) As String
    Dim stream As Object
    Set stream = CreateObject("ADODB.Stream")
    stream.Type = 2
    stream.Charset = "utf-8"
    stream.Open
    stream.LoadFromFile filePath
    ReadUtf8TextFile = stream.ReadText(-1)
    stream.Close
End Function

' The workbook's settings sheet under either spelling, or Nothing when it has neither.
Public Function SettingsSheet(ByVal book As Workbook) As Worksheet
    On Error Resume Next
    Set SettingsSheet = book.Worksheets(SETTINGS_SHEET_NAME)
    If SettingsSheet Is Nothing Then Set SettingsSheet = book.Worksheets(LEGACY_SETTINGS_SHEET_NAME)
    On Error GoTo 0
End Function

Public Function SetDefaultProject(ByVal ProjectName As String)
    Dim tmpName As String
    Dim book As Workbook
    Set book = CallerWorkbook()
    ' SetProjectName
    If ProjectName = "Default" Then
        tmpName = SettingsSheet(book).Range("B7").Value
    Else
        tmpName = ProjectName
    End If
    SetDefaultProject = Mid(tmpName, InStrRev(tmpName, "\") + 1)
End Function

Public Function JsonQuote(ByVal value As String) As String
    Dim i As Long
    Dim ch As String
    Dim code As Long
    Dim out As String

    out = """"
    For i = 1 To Len(value)
        ch = Mid$(value, i, 1)
        code = AscW(ch)
        Select Case ch
            Case """"
                out = out & "\"""
            Case "\"
                out = out & "\\"
            Case vbBack
                out = out & "\b"
            Case vbFormFeed
                out = out & "\f"
            Case vbCr
                out = out & "\r"
            Case vbLf
                out = out & "\n"
            Case vbTab
                out = out & "\t"
            Case Else
                If code >= 0 And code < 32 Then
                    out = out & "\u" & Right$("0000" & Hex$(code), 4)
                Else
                    out = out & ch
                End If
        End Select
    Next i
    JsonQuote = out & """"
End Function

Public Function DataArrayFromText(ByVal fileContent As String)
' *-------------------------------------------------------------*
' | Turn the CSV text the ArcRho Server answered with into the   |
' | array a worksheet formula returns. Every number a formula    |
' | shows is parsed here and nowhere else.                       |
' *-------------------------------------------------------------*
    Dim outputArray() As Variant
    Dim lines() As String
    Dim dateTimeString As String
    Dim data() As String
    Dim normalizedContent As String
    Dim i As Long, j As Long

    normalizedContent = Replace(fileContent, vbCrLf, vbLf)
    normalizedContent = Replace(normalizedContent, vbCr, vbLf)
    Do While Right$(normalizedContent, 1) = vbLf
        normalizedContent = Left$(normalizedContent, Len(normalizedContent) - 1)
    Loop

    If Len(normalizedContent) = 0 Then
        ReDim outputArray(0 To 0, 0 To 0)
        DataArrayFromText = outputArray
        Exit Function
    End If

    lines = Split(normalizedContent, vbLf)
    ReDim outputArray(LBound(lines) To UBound(lines), 0)

    For i = LBound(lines) To UBound(lines)
        data = Split(lines(i), ",")
        If UBound(data) > UBound(outputArray, 2) Then
            ReDim Preserve outputArray(LBound(lines) To UBound(lines), LBound(data) To UBound(data))
        End If
        For j = LBound(data) To UBound(data)

            dateTimeString = data(j)
            If InStr(dateTimeString, "+") > 0 Then
                dateTimeString = Left(dateTimeString, InStr(dateTimeString, "+") - 1)
            End If

            If IsNumeric(data(j)) Then
                outputArray(i, j) = CDbl(data(j))
            ElseIf IsDate(dateTimeString) Then
                outputArray(i, j) = CDbl(CDate(dateTimeString))
            Else
                outputArray(i, j) = data(j)
            End If
        Next j
    Next i

    DataArrayFromText = outputArray
End Function







