
' Give Excel's own Insert Function dialog the descriptions the Arco function
' catalog holds, so it says what the Insert Function panel says. Run by the
' build, which saves them into the add-in.
Sub RegisterArcoFunctionHelp()
    Dim book As Workbook, wasAddin As Boolean
    Dim fn As Object, arg As Object, descriptions() As String, i As Long

    Set book = ThisWorkbook
    wasAddin = book.IsAddin
    If wasAddin Then book.IsAddin = False

    For Each fn In ArcoFunctions()
        ReDim descriptions(0 To fn("Args").Count - 1)
        i = 0
        For Each arg In fn("Args")
            descriptions(i) = arg("Hint")
            If Len(arg("Default")) > 0 Then descriptions(i) = descriptions(i) & " Default " & arg("Default") & "."
            i = i + 1
        Next arg
        Application.MacroOptions Macro:=book.Name & "!" & fn("Name"), _
            Description:=fn("Summary"), Category:="Arco Tools", _
            ArgumentDescriptions:=descriptions
    Next fn

    If wasAddin Then book.IsAddin = True
End Sub

Sub SetAddinDescription()
    With ThisWorkbook.BuiltinDocumentProperties
        .item("Title").Value = "Arco"
        .item("Comments").Value = "Actuarial Reserving Co-intelligence"
        .item("Subject").Value = "Actuarial Utilities"
    End With
    ThisWorkbook.Save
End Sub




