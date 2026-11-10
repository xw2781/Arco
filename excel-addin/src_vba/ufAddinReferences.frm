VERSION 5.00
Begin {C62A69F0-16DC-11CE-9E98-00AA00574A4F} ufAddinReferences
   Caption         =   "Reset Add-in References"
   ClientHeight    =   6156
   ClientLeft      =   108
   ClientTop       =   456
   ClientWidth     =   8544.001
   OleObjectBlob   =   "ufAddinReferences.frx":0000
   StartUpPosition =   1  'CenterOwner
End
Attribute VB_Name = "ufAddinReferences"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = False
Option Explicit

Private book As Workbook
Private requested As Boolean
Private selectedTarget As Long
' Each target is a row: a bordered card behind an option button and the
' add-in's path. A click anywhere on the row picks it.
Private WithEvents arcoCard As MSForms.Label
Private WithEvents arcoRadio As MSForms.OptionButton
Private WithEvents arcoPath As MSForms.Label
Private WithEvents resqCard As MSForms.Label
Private WithEvents resqRadio As MSForms.OptionButton
Private WithEvents resqPath As MSForms.Label
Private WithEvents applyButton As MSForms.CommandButton
Private WithEvents closeButton As MSForms.CommandButton
Private summary As MSForms.TextBox
Private selecting As Boolean

Private Const SELECTED_BORDER As Long = &H417C10   ' Excel green
Private Const IDLE_BORDER As Long = &HC4C4C4

Private Function AddControl(ByVal kind As String, ByVal controlName As String, _
                            ByVal left As Single, ByVal top As Single, _
                            ByVal width As Single, ByVal height As Single, _
                            Optional ByVal caption As String = "") As Object
    Dim control As Object
    Set control = Me.Controls.Add("Forms." & kind & ".1", controlName, True)
    control.left = left
    control.top = top
    control.width = width
    control.height = height
    If Len(caption) > 0 Then control.caption = caption
    Set AddControl = control
End Function

Private Sub UserForm_Initialize()
    Me.width = 360
    Me.height = 188
    Me.caption = "Reset Add-in References"
    Set book = ActiveWorkbook
    AddControl "Label", "lblIntro", 12, 10, 324, 14, "Point " & book.Name & " at"

    Set arcoCard = AddControl("Label", "lblArcoCard", 12, 28, 324, 36)
    Set arcoRadio = AddControl("OptionButton", "optArco", 20, 31, 200, 16, "Arco")
    Set arcoPath = AddControl("Label", "lblArcoPath", 36, 48, 294, 12, ReferenceTargetPath(0))
    StyleRow arcoCard, arcoRadio, arcoPath

    Set resqCard = AddControl("Label", "lblResQCard", 12, 70, 324, 36)
    Set resqRadio = AddControl("OptionButton", "optResQ", 20, 73, 200, 16, "ResQ (64-bit)")
    Set resqPath = AddControl("Label", "lblResQPath", 36, 90, 294, 12, ReferenceTargetPath(1))
    StyleRow resqCard, resqRadio, resqPath
    If Not CanUseResQ() Then
        resqRadio.Enabled = False
        resqPath.caption = "Only available on " & RESQ_COMPUTER
    End If

    Set summary = AddControl("TextBox", "txtSummary", 12, 114, 152, 34)
    summary.MultiLine = True
    summary.Locked = True
    summary.WordWrap = True
    summary.ScrollBars = fmScrollBarsVertical
    summary.BorderStyle = fmBorderStyleNone
    summary.SpecialEffect = fmSpecialEffectFlat
    summary.BackColor = Me.BackColor
    summary.TabStop = False
    Set applyButton = AddControl("CommandButton", "cmdApply", 172, 119, 100, 24, "Update workbook")
    applyButton.Default = True
    Set closeButton = AddControl("CommandButton", "cmdClose", 278, 119, 58, 24, "Close")
    closeButton.Cancel = True
    SelectTarget 0
End Sub

Private Sub StyleRow(ByVal card As MSForms.Label, ByVal radio As MSForms.OptionButton, _
                     ByVal pathText As MSForms.Label)
    card.BorderStyle = fmBorderStyleSingle
    radio.Font.Bold = True
    pathText.ForeColor = &H555555
End Sub

Private Sub PaintRow(ByVal card As MSForms.Label, ByVal radio As MSForms.OptionButton, _
                     ByVal pathText As MSForms.Label, ByVal picked As Boolean)
    Dim fill As Long
    fill = IIf(picked, vbWhite, Me.BackColor)
    card.BackColor = fill
    card.BorderColor = IIf(picked, SELECTED_BORDER, IDLE_BORDER)
    radio.BackColor = fill
    pathText.BackColor = fill
End Sub

Private Sub SelectTarget(ByVal index As Long)
    If index = 1 And Not CanUseResQ() Then Exit Sub
    selectedTarget = index
    selecting = True
    arcoRadio.Value = (index = 0)
    resqRadio.Value = (index = 1)
    selecting = False
    PaintRow arcoCard, arcoRadio, arcoPath, index = 0
    PaintRow resqCard, resqRadio, resqPath, index = 1
    If index = 1 Then
        summary.Value = "Formulas will use ResQ names. They calculate only on " & RESQ_COMPUTER & "."
    Else
        summary.Value = "Formulas will use Arco names."
    End If
End Sub

Private Sub arcoRadio_Click()
    If Not selecting Then SelectTarget 0
End Sub

Private Sub arcoCard_Click()
    SelectTarget 0
End Sub

Private Sub arcoPath_Click()
    SelectTarget 0
End Sub

Private Sub resqRadio_Click()
    If Not selecting Then SelectTarget 1
End Sub

Private Sub resqCard_Click()
    SelectTarget 1
End Sub

Private Sub resqPath_Click()
    SelectTarget 1
End Sub

Private Sub closeButton_Click()
    requested = False
    Me.Hide
End Sub

' Run the update outside the modal Show call so ufProgressBar can be modeless.
Public Sub ShowDialog()
    Do
        requested = False
        Me.Show vbModal
        If Not requested Then Exit Do
        UpdateWorkbook
    Loop
    Unload Me
End Sub

Private Sub applyButton_Click()
    requested = True
    Me.Hide
End Sub

Public Sub UpdateWorkbook()
    Dim prefix As String
    On Error GoTo Failed
    prefix = "Arco"
    If selectedTarget = 1 Then prefix = "ResQ"
    summary.Value = UpdateWorkbookReferences(book, ReferenceTargetPath(selectedTarget), prefix)
    Exit Sub
Failed:
    summary.Value = Err.Description
End Sub

Private Sub UserForm_QueryClose(Cancel As Integer, CloseMode As Integer)
    If CloseMode = vbFormControlMenu Then
        Cancel = True
        requested = False
        Me.Hide
    End If
End Sub
