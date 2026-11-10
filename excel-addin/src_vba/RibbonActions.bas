Private mAlertCloseTime As Date

Public Sub CopyActiveRangeAddress()
    Dim selectedRange As Range
    Dim selectedWorkbook As Workbook
    Dim clipboard As MSForms.DataObject
    Dim externalAddress As String

    On Error GoTo ErrorHandler

    If TypeName(Application.Selection) <> "Range" Then
        ufAlert.ShowMessage "Select a worksheet range before copying its address.", "Arco"
        Exit Sub
    End If

    Set selectedRange = Application.Selection
    Set selectedWorkbook = selectedRange.Worksheet.Parent

    If Len(selectedWorkbook.Path) = 0 Then
        ufAlert.ShowMessage "Save the workbook before copying a full range address.", "Arco"
        Exit Sub
    End If

    externalAddress = "='" & Replace$( _
        selectedWorkbook.Path & Application.PathSeparator & _
        "[" & selectedWorkbook.Name & "]" & selectedRange.Worksheet.Name, _
        "'", "''") & "'!" & selectedRange.Address( _
            RowAbsolute:=True, _
            ColumnAbsolute:=True, _
            ReferenceStyle:=xlA1)

    Set clipboard = New MSForms.DataObject
    clipboard.SetText externalAddress
    clipboard.PutInClipboard

    ufAlert.ShowTimedMessage _
        "Active range address copied to the clipboard.", _
        "Arco", _
        2
    Exit Sub

ErrorHandler:
    ufAlert.ShowMessage "The active range address could not be copied: " & Err.Description, "Arco"
End Sub

Public Sub ScheduleTimedAlertClose(ByVal delaySeconds As Long)
    CancelTimedAlertClose

    mAlertCloseTime = Now + TimeSerial(0, 0, delaySeconds)
    Application.OnTime _
        EarliestTime:=mAlertCloseTime, _
        Procedure:=TimedAlertCloseProcedureName
End Sub

Public Sub CancelTimedAlertClose()
    If mAlertCloseTime = 0 Then Exit Sub

    On Error Resume Next
    Application.OnTime _
        EarliestTime:=mAlertCloseTime, _
        Procedure:=TimedAlertCloseProcedureName, _
        Schedule:=False
    On Error GoTo 0

    mAlertCloseTime = 0
End Sub

Public Sub CloseTimedAlert()
    mAlertCloseTime = 0
    Unload ufAlert
End Sub

Private Function TimedAlertCloseProcedureName() As String
    TimedAlertCloseProcedureName = "'" & Replace$(ThisWorkbook.Name, "'", "''") & "'!CloseTimedAlert"
End Function

Sub CalculateWorkbook()
    RefreshWorkbookSnapshots False, Not disableProgressBar
End Sub

Sub CalculateWorkbookWithUI()
    RefreshWorkbookSnapshots False, True
End Sub

Sub CalculateSheet()
    RefreshWorkbookSnapshots True, Not disableProgressBar
End Sub

Sub CalculateWorkbookNoUI()
    RefreshWorkbookSnapshots False, False
End Sub

Function KeyExists(coll As Collection, key As String) As Boolean
    Dim item As Variant
    On Error Resume Next
    item = coll(key)
    KeyExists = (Err.Number = 0)
    On Error GoTo 0
End Function

Function SheetExists(sheetName As String) As Boolean
    Dim ws As Worksheet
    On Error Resume Next
        Set ws = ActiveWorkbook.Sheets(sheetName)
    On Error GoTo 0
    If ws Is Nothing Then
        SheetExists = False
    Else
        SheetExists = True
    End If
End Function

Public Sub SetupConnection2()
    Dim sheet1 As Worksheet
    Dim Sheet2 As Worksheet
        
    If Not SheetExists(SETTINGS_SHEET_NAME) And Not SheetExists(LEGACY_SETTINGS_SHEET_NAME) Then
        Set sheet1 = ActiveWorkbook.Worksheets.Add(Before:=ActiveWorkbook.Sheets(1))
        sheet1.Name = SETTINGS_SHEET_NAME
    End If
    
    If Not SheetExists("Project Details") Then
        Set Sheet2 = ActiveWorkbook.Worksheets.Add(Before:=ActiveWorkbook.Sheets(2))
        Sheet2.Name = "Project Details"
    End If
    
    Set sheet1 = SettingsSheet(ActiveWorkbook)
        sheet1.Columns("A").ColumnWidth = 72.71
        sheet1.Columns("B").ColumnWidth = 44.71
        
        sheet1.Range("A1").Value = "Connection Name"
        sheet1.Range("A2").Value = "Windows Authentication"
        sheet1.Range("A3").Value = "User Name"
        sheet1.Range("A7").Value = "Default Project Name"
        sheet1.Range("A9").Value = "Project Names"
        OfferProjectDropdown sheet1
    
    Set Sheet2 = ActiveWorkbook.Sheets("Project Details")
        Sheet2.Columns("B").ColumnWidth = 22.14
        Sheet2.Columns("C").ColumnWidth = 39.43
        
        Sheet2.Range("B4:C11").FormulaArray = "=ArcoProjectSettings()"
        Sheet2.Range("C4:C11").Interior.Color = 10092543
        Sheet2.Range("C4:C11").HorizontalAlignment = xlCenter
        Sheet2.Range("C4:C11").Font.Color = 255 ' Red
        Sheet2.Range("C4:C11").Font.Bold = True
        
        Dim borders() As Variant
        borders = Array(xlEdgeLeft, xlEdgeTop, xlEdgeBottom, xlEdgeRight, xlInsideVertical)
        For i = LBound(borders) To UBound(borders)
            With Sheet2.Range("B4:C11").borders(borders(i))
                .LineStyle = xlContinuous
                .Weight = xlMedium
            End With
        Next i
        
        Sheet2.Range("C6:C8").NumberFormat = "m/d/yy"
        
    On Error Resume Next
    
    On Error GoTo 0
End Sub

Sub LoadAddIn()
    errCount = 0
    skipDataProcess = False
    pendingUpdate = False
    Application.StatusBar = "Calculation Resumed"
End Sub

Sub UnloadAddIn()
    On Error GoTo ErrorHandler
    Dim addIn As addIn
    
    For Each addIn In AddIns
        If StrComp(addIn.Name, "Arco.xlam", vbTextCompare) = 0 _
           Or StrComp(addIn.Name, "ARCRHO_BETA.xlam", vbTextCompare) = 0 Then
            addIn.Installed = False
            Exit For
        End If
    Next addIn
    
ErrorHandler:
    ' MsgBox "An error occurred: " & Err.Description
    ' MsgBox "An error occurred when unloading the add-in"
    Err.Clear
    On Error GoTo 0
End Sub

Sub CheckUpdates()
    Dim exePath As String
    Dim retVal As Long
    
    exePath = "\\Ne7saswpn02\e\ResQ\Excel Add-ins\Update\dist\AutoUpdate.exe"
    
    ' Run the executable
    retVal = Shell(exePath, vbNormalFocus)
    
    ' Check the return Value
End Sub

' The Reset Add-in References button opens ufAddinReferences, which retargets
' add-in links and renames old formulas through ReferenceRepair.
