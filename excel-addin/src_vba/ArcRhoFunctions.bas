
Public Function ArcoTri( _
    Path As String, TriangleName As String, _
    Optional Cumulative As Boolean = True, _
    Optional Transposed As Boolean = False, _
    Optional Calendar As Boolean = False, _
    Optional ProjectName As String = "Default", _
    Optional OriginLength As Integer = 12, _
    Optional DevelopmentLength As Integer = 12, _
    Optional ByTypeName, _
    Optional SuppressWarnings _
) As Variant

    Dim v As Variant   ' <-- can hold array OR string OR error, etc.
    Dim normalizedTriangleName As String

    On Error GoTo ErrorHandler
    normalizedTriangleName = NormalizeDatasetName(TriangleName)

    v = GetDataset( _
        "Function = ArcRhoTri" & "#" & _
        "Path = " & Path & "#" & _
        "DatasetName = " & normalizedTriangleName & "#" & _
        "Cumulative = " & Cumulative & "#" & _
        "Transposed = " & Transposed & "#" & _
        "Calendar = " & Calendar & "#" & _
        "ProjectName = " & SetDefaultProject(ProjectName) & "#" & _
        "OriginLength = " & OriginLength & "#" & _
        "DevelopmentLength = " & DevelopmentLength)

    ' If GetDataset returned an error value, just pass it through
    If IsError(v) Then
        ArcoTri = v
        Exit Function
    End If

    ' If GetDataset returned an array, you may transpose it
    If IsArray(v) Then
        If Transposed Then
            ArcoTri = TransposeArray(v)
        Else
            ArcoTri = v
        End If
    Else
        ' Scalar (string/number/etc.) -> just return it directly
        ArcoTri = v
    End If

    Exit Function

ErrorHandler:
    Debug.Print "UDF error: "; Err.Number; Err.Description
    ArcoTri = "(dataset needs to be updated)"
End Function

Public Function ArcoTriDiag( _
    Path As String, TriangleName As String, _
    Optional DiagonalIndex As Long = 0, _
    Optional Cumulative As Boolean = True, _
    Optional Transposed As Boolean = False, _
    Optional ProjectName As String = "Default", _
    Optional OriginLength As Integer = 12, _
    Optional DevelopmentLength As Integer = 12, _
    Optional ByTypeName, _
    Optional SuppressWarnings _
  ) As Variant
  
    Dim tri As Variant
    Dim outArr() As Variant

    On Error Resume Next

    tri = ArcoTri( _
              Path, TriangleName, _
              Cumulative, False, False, _
              ProjectName, OriginLength, DevelopmentLength, _
              ByTypeName, SuppressWarnings)

    ' Not a triangle but the reason there is none: show it rather than the
    ' blank or the #VALUE! that reading a row out of it would leave behind.
    If Not IsArray(tri) Then
        ArcoTriDiag = tri
        Exit Function
    End If

    outArr = GetDiagonal(tri, -DiagonalIndex)
    
    If Transposed Then outArr = TransposeArray(outArr)
   
    ArcoTriDiag = outArr
    
End Function

Public Function ArcoTriCell( _
    Path As String, TriangleName As String, _
    OriginPeriod As Long, DevelopmentPeriod As Long, _
    Optional Cumulative As Boolean = True, _
    Optional ProjectName As String = "Default", _
    Optional OriginLength As Integer = 12, _
    Optional DevelopmentLength As Integer = 12, _
    Optional ByTypeName, _
    Optional SuppressWarnings _
) As Variant

    Dim tri As Variant
    On Error GoTo InvalidPeriod
    
    tri = ArcoTri( _
              Path, TriangleName, _
              Cumulative, False, False, _
              ProjectName, OriginLength, DevelopmentLength, _
              ByTypeName, SuppressWarnings)

    If Not IsArray(tri) Then
        ArcoTriCell = tri
        Exit Function
    End If

    If OriginPeriod < 1 Or DevelopmentPeriod < 1 Then GoTo InvalidPeriod
    ArcoTriCell = tri(LBound(tri, 1) + OriginPeriod - 1, LBound(tri, 2) + DevelopmentPeriod - 1)
    Exit Function
InvalidPeriod:
    ArcoTriCell = CVErr(xlErrRef)
End Function

Public Function ArcoHeaders( _
    periodType As Integer, _
    Transposed As Boolean, _
    Optional PeriodLength As Integer = 12, _
    Optional ProjectName As String = "Default", _
    Optional StoredPeriodLength As Integer = -1, _
    Optional Calendar As Boolean = False _
  ) As Variant
  
    Dim outArr As Variant
    On Error Resume Next

    outArr = GetDataset( _
      "Function = ArcRhoHeaders" & "#" & _
      "periodType = " & periodType & "#" & _
      "Transposed = " & Transposed & "#" & _
      "Calendar = " & Calendar & "#" & _
      "PeriodLength = " & PeriodLength & "#" & _
      "ProjectName = " & SetDefaultProject(ProjectName) & "#" & _
      "StoredPeriodLength = " & StoredPeriodLength _
    )

    If Not IsArray(outArr) Then
        ArcoHeaders = outArr
        Exit Function
    End If

    outArr = FormatYYYYMM_ToMmmYYYY(outArr)
    
    If Transposed Then
        ArcoHeaders = outArr
    Else
        ArcoHeaders = TransposeArray(outArr)
    End If
    
End Function

Public Function ArcoTriOrigin( _
    Path As String, TriangleName As String, _
    OriginPeriod As Long, _
    Optional Cumulative As Boolean = True, _
    Optional Transposed As Boolean = False, _
    Optional ProjectName As String = "Default", _
    Optional OriginLength As Integer = 12, _
    Optional DevelopmentLength As Integer = 12, _
    Optional ByTypeName, _
    Optional SuppressWarnings _
) As Variant

    Dim tri As Variant
    Dim outArr() As Variant
    Dim lb1 As Long, ub1 As Long
    Dim lb2 As Long, ub2 As Long
    Dim r As Long, c As Long
    On Error Resume Next
    
    tri = ArcoTri( _
            Path, TriangleName, _
            Cumulative, False, False, _
            ProjectName, OriginLength, DevelopmentLength, _
            ByTypeName, SuppressWarnings)

    If Not IsArray(tri) Then
        ArcoTriOrigin = tri
        Exit Function
    End If

    lb1 = LBound(tri, 1)
    ub1 = UBound(tri, 1)
    lb2 = LBound(tri, 2)
    ub2 = UBound(tri, 2)

    If lb1 = 0 Then
        r = OriginPeriod - 1
    Else
        r = OriginPeriod
    End If

    ReDim outArr(1 To 1, 1 To ub2 - lb2 + 1)
    For c = lb2 To ub2
        outArr(1, c - lb2 + 1) = tri(r, c)
    Next c

    If Transposed Then
        ArcoTriOrigin = TransposeArray(outArr)
    Else
        ArcoTriOrigin = outArr
    End If
    
End Function

Public Function ArcoVec( _
    Path As String, VectorName As String, _
    Optional Transposed As Boolean = False, _
    Optional ProjectName As String = "Default", _
    Optional PeriodLength As Integer = 12, _
    Optional ByTypeName, _
    Optional SuppressWarnings _
  ) As Variant
  
    Dim result As Variant
    Dim normalizedVectorName As String
    On Error Resume Next
    normalizedVectorName = NormalizeDatasetName(VectorName)
    
    result = GetDataset( _
        "Function = ArcRhoVec" & "#" & _
        "Path = " & Path & "#" & _
        "DatasetName = " & normalizedVectorName & "#" & _
        "Cumulative = True" & "#" & _
        "Transposed = " & Transposed & "#" & _
        "ProjectName = " & SetDefaultProject(ProjectName) & "#" & _
        "OriginLength = " & PeriodLength & "#" & _
        "DevelopmentLength = " & PeriodLength)

    If IsArray(result) And Transposed Then
        ArcoVec = TransposeArray(result)
    Else
        ArcoVec = result
    End If
    
End Function

Public Function ArcoVecCell( _
    Path As String, VectorName As String, Index As Integer, _
    Optional ProjectName As String = "Default", _
    Optional PeriodLength As Integer = 12, _
    Optional ByTypeName, _
    Optional SuppressWarnings _
) As Variant

    Dim vec As Variant
    On Error GoTo ErrorHandler

    vec = ArcoVec( _
              Path, VectorName, _
              Transposed:=False, _
              ProjectName:=ProjectName, _
              PeriodLength:=PeriodLength, _
              ByTypeName:=ByTypeName, _
              SuppressWarnings:=SuppressWarnings)

    If IsError(vec) Then
        ArcoVecCell = vec
        Exit Function
    End If

    If Not IsArray(vec) Then
        ArcoVecCell = vec
        Exit Function
    End If

    ' Convert 1-based Index to array's actual lower bound
    Dim lb1 As Long, lb2 As Long
    Dim ub1 As Long, ub2 As Long

    On Error Resume Next
    lb2 = LBound(vec, 2)
    If Err.Number <> 0 Then
        ' 1D array
        Err.Clear
        On Error GoTo ErrorHandler
        lb1 = LBound(vec, 1)
        ArcoVecCell = vec(lb1 + Index - 1)
    Else
        ' 2D array — index along whichever dimension has length > 1
        On Error GoTo ErrorHandler
        lb1 = LBound(vec, 1): ub1 = UBound(vec, 1)
        ub2 = UBound(vec, 2)
        If (ub2 - lb2) > 0 Then
            ' Multiple columns (1 row x N cols) — index along dim 2
            ArcoVecCell = vec(lb1, lb2 + Index - 1)
        Else
            ' Multiple rows (N rows x 1 col) — index along dim 1
            ArcoVecCell = vec(lb1 + Index - 1, lb2)
        End If
    End If

    Exit Function

ErrorHandler:
    ArcoVecCell = 0
End Function

Public Function ArcoProjectSettings(Optional ProjectName As String = "Default")
    On Error Resume Next
    ArcoProjectSettings = GetDataset( _
        "Function = ArcRhoProjectSettings" & "#" & _
        "ProjectName = " & SetDefaultProject(ProjectName))
        
End Function

' The projects on the Arco Server, one name per row: all of them, or only
' those in one folder of the Arco project tree, such as "Legacy\2025".
' ShowFullPath puts each project's folder in front of its name. Reads the list
' the add-in already holds for this Excel session; Connect and Login asks
' again.
Public Function ArcoProjectNames(Optional ByVal Folder As String = "", _
                                 Optional ByVal ShowFullPath As Boolean = False) As Variant
    Dim message As String, names As Variant, folders As Variant
    Dim picked() As String, i As Long, n As Long

    If Not LoadChoices("", message) Then
        ArcoProjectNames = message
        Exit Function
    End If
    names = ChoiceProjectNames()
    folders = ChoiceProjectFolders()
    Folder = Trim$(Replace(Folder, "/", "\"))
    ReDim picked(1 To UBound(names))
    For i = 1 To UBound(names)
        If Len(Folder) = 0 Or StrComp(folders(i), Folder, vbTextCompare) = 0 Then
            n = n + 1
            picked(n) = names(i)
            If ShowFullPath And Len(folders(i)) > 0 Then picked(n) = folders(i) & "\" & names(i)
        End If
    Next i
    ArcoProjectNames = ""
    If n = 0 Then Exit Function
    ReDim Preserve picked(1 To n)
    ArcoProjectNames = Application.WorksheetFunction.Transpose(picked)
End Function

Function ArcoReservingClasses(Optional Level, Optional WithDataOnly, Optional ProjectName) As Variant
    ArcoReservingClasses = ""
End Function

Function ArcoNodeContents(Path As String, Optional ContentType, Optional ProjectName) As Variant
    ArcoNodeContents = ""
End Function

Sub ArcoMetadata()
    qqq ActiveSheet.Name & "--" & ActiveCell.formula
End Sub
