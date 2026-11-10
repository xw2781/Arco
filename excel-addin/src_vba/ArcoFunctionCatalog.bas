Attribute VB_Name = "ArcoFunctionCatalog"
Option Private Module
Option Explicit

' What the add-in says about each Arco worksheet function and its arguments.
' The Insert Function panel builds its pages from this list, the build
' registers the same text for Excel's own function dialog, and the pickers use
' it to recognise an Arco formula. The argument order matches the function's
' declaration in ArcRhoFunctions.bas.
'
' Argument kinds decide the input a page shows:
'   path, triangle, vector, project, folder
'                                    a list read from the Arco Server
'   bool, length, period_type        a short fixed list
'   number                           typed
'   hidden                           kept for ResQ workbooks; never shown

Private catalog As Collection
Private current As Object

Public Function ArcoFunctions() As Collection
    If catalog Is Nothing Then BuildCatalog
    Set ArcoFunctions = catalog
End Function

' The catalog entry for a function name, or Nothing.
Public Function ArcoFunctionByName(ByVal functionName As String) As Object
    Dim fn As Object
    For Each fn In ArcoFunctions()
        If StrComp(fn("Name"), functionName, vbTextCompare) = 0 Then
            Set ArcoFunctionByName = fn
            Exit Function
        End If
    Next fn
End Function

' The catalog function a formula calls at its top level, such as "ArcoTriCell"
' for "=ArcoTriCell(B1, ...)", or "" when it starts with anything else.
Public Function ArcoFormulaFunction(ByVal formulaText As String) As String
    Dim fn As Object, head As String
    head = UCase$(Trim$(formulaText))
    If Left$(head, 1) <> "=" Then Exit Function
    head = Mid$(head, 2)
    For Each fn In ArcoFunctions()
        If Left$(head, Len(fn("Name")) + 1) = UCase$(fn("Name")) & "(" Then
            ArcoFormulaFunction = fn("Name")
            Exit Function
        End If
    Next fn
End Function

Private Sub BuildCatalog()
    Set catalog = New Collection

    AddFunction "ArcoTri", "Triangle", _
        "Returns a whole triangle. It spills down and to the right from the cell."
    AddPathArgs "TriangleName", "triangle"
    AddArg "Cumulative", "bool", False, "TRUE", "TRUE returns cumulative amounts, FALSE incremental."
    AddArg "Transposed", "bool", False, "FALSE", "TRUE puts development ages down the rows and origin periods across."
    AddArg "Calendar", "bool", False, "FALSE", "TRUE lays the columns out by calendar period instead of development age."
    AddProjectAndLengthArgs True

    AddFunction "ArcoTriCell", "Triangle", _
        "Returns one value from a triangle."
    AddPathArgs "TriangleName", "triangle"
    AddArg "OriginPeriod", "number", True, "", "Row of the triangle: 1 is the first origin period."
    AddArg "DevelopmentPeriod", "number", True, "", "Column of the triangle: 1 is the first development age."
    AddArg "Cumulative", "bool", False, "TRUE", "TRUE returns cumulative amounts, FALSE incremental."
    AddProjectAndLengthArgs True

    AddFunction "ArcoTriDiag", "Triangle", _
        "Returns one diagonal of a triangle, one value per origin period."
    AddPathArgs "TriangleName", "triangle"
    AddArg "DiagonalIndex", "number", False, "0", "0 is the latest diagonal, 1 the one before it, and so on."
    AddArg "Cumulative", "bool", False, "TRUE", "TRUE returns cumulative amounts, FALSE incremental."
    AddArg "Transposed", "bool", False, "FALSE", "TRUE returns the diagonal across a row instead of down a column."
    AddProjectAndLengthArgs True

    AddFunction "ArcoTriOrigin", "Triangle", _
        "Returns one origin period's row of a triangle."
    AddPathArgs "TriangleName", "triangle"
    AddArg "OriginPeriod", "number", True, "", "Row of the triangle: 1 is the first origin period."
    AddArg "Cumulative", "bool", False, "TRUE", "TRUE returns cumulative amounts, FALSE incremental."
    AddArg "Transposed", "bool", False, "FALSE", "TRUE returns the row down a column instead."
    AddProjectAndLengthArgs True

    AddFunction "ArcoVec", "Vector", _
        "Returns a whole vector, one value per origin period, down a column."
    AddPathArgs "VectorName", "vector"
    AddArg "Transposed", "bool", False, "FALSE", "TRUE returns the vector across a row instead."
    AddProjectAndLengthArgs False

    AddFunction "ArcoVecCell", "Vector", _
        "Returns one value from a vector."
    AddPathArgs "VectorName", "vector"
    AddArg "Index", "number", True, "", "Position in the vector: 1 is the first origin period."
    AddProjectAndLengthArgs False

    AddFunction "ArcoHeaders", "Project", _
        "Returns a project's origin period or development age labels."
    AddArg "periodType", "period_type", True, "", "0 returns origin period labels, 1 development age labels."
    AddArg "Transposed", "bool", True, "", "FALSE lists the labels down a column, TRUE across a row."
    AddArg "PeriodLength", "length", False, "12", "Months in each period: 12 annual, 6 half-year, 3 quarterly, 1 monthly."
    AddArg "ProjectName", "project", False, """Default""", "Project to read. Default is the workbook's default project."
    AddArg "StoredPeriodLength", "hidden", False, "-1", "Not used; kept so older workbooks still calculate."
    AddArg "Calendar", "bool", False, "FALSE", "TRUE labels development periods by calendar period instead of age."

    AddFunction "ArcoProjectSettings", "Project", _
        "Returns a project's settings, such as its dates and period lengths, as a two-column table."
    AddArg "ProjectName", "project", False, """Default""", "Project to read. Default is the workbook's default project."

    AddFunction "ArcoProjectNames", "Project", _
        "Lists the projects on the Arco Server, one name per row."
    AddArg "Folder", "folder", False, "", "Folder of the Arco project list, such as Legacy. Blank lists every project."
    AddArg "ShowFullPath", "bool", False, "FALSE", "TRUE puts each project's folder in front of its name, such as Legacy\My Project."
End Sub

Private Sub AddFunction(ByVal functionName As String, ByVal group As String, ByVal summary As String)
    Set current = CreateObject("Scripting.Dictionary")
    current("Name") = functionName
    current("Group") = group
    current("Summary") = summary
    current.Add "Args", New Collection
    catalog.Add current
End Sub

' Default is the argument's value exactly as the function assumes it when left
' out, written as it would appear in a formula.
Private Sub AddArg(ByVal argName As String, ByVal kind As String, ByVal required As Boolean, _
                   ByVal defaultText As String, ByVal hint As String)
    Dim arg As Object
    Set arg = CreateObject("Scripting.Dictionary")
    arg("Name") = argName
    arg("Kind") = kind
    arg("Required") = required
    arg("Default") = defaultText
    arg("Hint") = hint
    current("Args").Add arg
End Sub

Private Sub AddPathArgs(ByVal datasetArg As String, ByVal datasetKind As String)
    AddArg "Path", "path", True, "", "Reserving class path, such as PRNJ - PA\PA\NJ\Direct Group\COL."
    AddArg datasetArg, datasetKind, True, "", "Dataset name, such as Net Loss--Paid."
End Sub

Private Sub AddProjectAndLengthArgs(ByVal isTriangle As Boolean)
    AddArg "ProjectName", "project", False, """Default""", "Project to read. Default is the workbook's default project."
    If isTriangle Then
        AddArg "OriginLength", "length", False, "12", "Months in each origin period: 12 annual, 6 half-year, 3 quarterly, 1 monthly."
        AddArg "DevelopmentLength", "length", False, "12", "Months in each development period."
    Else
        AddArg "PeriodLength", "length", False, "12", "Months in each origin period: 12 annual, 6 half-year, 3 quarterly, 1 monthly."
    End If
    AddArg "ByTypeName", "hidden", False, "", "Not used; kept so ResQ workbooks still calculate."
    AddArg "SuppressWarnings", "hidden", False, "", "Not used; kept so ResQ workbooks still calculate."
End Sub
