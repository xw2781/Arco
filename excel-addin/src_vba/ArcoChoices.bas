Attribute VB_Name = "ArcoChoices"
Option Private Module
Option Explicit

' The project names, reserving classes, and dataset types the add-in's pickers
' offer: Insert Function, Select Datasets, Load Reserving Classes, and the
' default-project dropdown on the settings sheet. One Arco Server request
' answers all three for a project, and the answer is kept for the Excel
' session, so a picker opened again fills at once. Refresh asks again.

Private projectNames As Variant   ' 1-based String array, or Empty until read
Private projectFolders As Variant ' each project's folder in the Arco project tree, beside projectNames
Private latestProject As String  ' the server's latest project, for a new workbook's default
Private projectLists As Object    ' project name -> Dictionary of Classes and DatasetTypes

' Read the lists for projectName, or only the project names when it is "".
' Reuses this session's answer unless refresh is True. False with a reason
' when the server could not answer.
Public Function LoadChoices(ByVal projectName As String, ByRef outMessage As String, _
                            Optional ByVal refresh As Boolean = False) As Boolean
    Dim reply As Object, entry As Object

    If projectLists Is Nothing Then
        Set projectLists = CreateObject("Scripting.Dictionary")
        projectLists.CompareMode = vbTextCompare
    End If
    projectName = Trim$(projectName)
    If Not refresh And Not IsEmpty(projectNames) Then
        If Len(projectName) = 0 Or projectLists.Exists(projectName) Then
            LoadChoices = True
            Exit Function
        End If
    End If

    If Not GatewayFormulaChoices(projectName, reply, outMessage) Then Exit Function
    projectNames = StringArray(reply("projects"))
    projectFolders = StringArray(reply("project_folders"))
    latestProject = CStr(reply("latest_project"))
    If Len(projectName) > 0 Then
        Set entry = CreateObject("Scripting.Dictionary")
        entry("Classes") = StringArray(reply("reserving_classes"))
        entry("DatasetTypes") = TableArray(reply("dataset_types"))
        Set projectLists(projectName) = entry
    End If
    LoadChoices = True
End Function

Public Function ChoiceProjectNames() As Variant
    ChoiceProjectNames = projectNames
End Function

Public Function ChoiceProjectFolders() As Variant
    ChoiceProjectFolders = projectFolders
End Function

' The project's reserving classes that hold data, or Empty.
Public Function ChoiceReservingClasses(ByVal projectName As String) As Variant
    If HasProject(projectName) Then ChoiceReservingClasses = projectLists(Trim$(projectName))("Classes")
End Function

' The project's dataset types with a header row (Name, Data Format, Category),
' 1-based in both dimensions, or Empty.
Public Function ChoiceDatasetTypes(ByVal projectName As String) As Variant
    If HasProject(projectName) Then ChoiceDatasetTypes = projectLists(Trim$(projectName))("DatasetTypes")
End Function

' The names of the project's dataset types in one Data Format, or Empty.
Public Function ChoiceDatasetNames(ByVal projectName As String, ByVal dataFormat As String) As Variant
    Dim table As Variant, names() As String, r As Long, n As Long
    table = ChoiceDatasetTypes(projectName)
    If IsEmpty(table) Then Exit Function
    ReDim names(1 To UBound(table, 1))
    For r = 2 To UBound(table, 1)
        If StrComp(table(r, 2), dataFormat, vbTextCompare) = 0 Then
            n = n + 1
            names(n) = table(r, 1)
        End If
    Next r
    If n = 0 Then Exit Function
    ReDim Preserve names(1 To n)
    ChoiceDatasetNames = names
End Function

' The project a workbook's formulas use when they name none: the settings
' sheet's Default Project Name, without any folder in front of it.
Public Function WorkbookDefaultProject(ByVal book As Workbook) As String
    Dim ws As Worksheet, projectValue As String
    If book Is Nothing Then Exit Function
    Set ws = SettingsSheet(book)
    If ws Is Nothing Then Exit Function
    projectValue = Trim$(CStr(ws.Range("B7").Value))
    WorkbookDefaultProject = Mid$(projectValue, InStrRev(projectValue, "\") + 1)
End Function

' List the Arco Server's projects on the settings sheet with ArcoProjectNames
' in A11, clearing column A from there down to make room, and offer that list
' as the Default Project Name cell's dropdown. A blank Default Project Name
' becomes the latest project. Asks the server again, so Connect and Login also
' refreshes the project list.
Public Sub OfferProjectDropdown(ByVal ws As Worksheet)
    Dim message As String

    If Not LoadChoices("", message, True) Then
        Application.StatusBar = "Arco: the project list could not be read. " & message
        Exit Sub
    End If
    If IsEmpty(ChoiceProjectNames()) Then Exit Sub

    ws.Range("A11:A" & ws.Rows.Count).ClearContents
    ws.Range("A11").Formula2 = "=ArcoProjectNames()"

    If Len(Trim$(CStr(ws.Range("B7").Value))) = 0 Then ws.Range("B7").Value = latestProject
    With ws.Range("B7").Validation
        .Delete
        .Add Type:=xlValidateList, AlertStyle:=xlValidAlertInformation, _
             Formula1:="=$A$11#"
        .InCellDropdown = True
        .ErrorTitle = "Arco"
        .ErrorMessage = "That project is not on the Arco Server's project list."
    End With
End Sub

Public Sub WarnNoDefaultProject(ByVal featureName As String)
    Dim msg As String

    msg = "Please connect and log in, then select a default project before using " & featureName & "."
    On Error Resume Next
    ufAlert.ShowMessage msg, "Arco"
    If Err.Number <> 0 Then
        Err.Clear
        MsgBox msg, vbExclamation, "Arco"
    End If
    On Error GoTo 0
End Sub

Private Function HasProject(ByVal projectName As String) As Boolean
    If projectLists Is Nothing Then Exit Function
    HasProject = projectLists.Exists(Trim$(projectName))
End Function

Private Function StringArray(ByVal items As Collection) As Variant
    Dim out() As String, i As Long
    If items.Count = 0 Then Exit Function
    ReDim out(1 To items.Count)
    For i = 1 To items.Count
        out(i) = CStr(items(i))
    Next i
    StringArray = out
End Function

Private Function TableArray(ByVal table As Object) As Variant
    Dim columns As Collection, rows As Collection, out() As String
    Dim r As Long, c As Long
    Set columns = table("columns")
    Set rows = table("rows")
    If rows.Count = 0 Then Exit Function
    ReDim out(1 To rows.Count + 1, 1 To columns.Count)
    For c = 1 To columns.Count
        out(1, c) = CStr(columns(c))
    Next c
    For r = 1 To rows.Count
        For c = 1 To columns.Count
            out(r + 1, c) = CStr(rows(r)(c))
        Next c
    Next r
    TableArray = out
End Function
