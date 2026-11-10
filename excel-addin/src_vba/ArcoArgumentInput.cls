VERSION 1.0 CLASS
BEGIN
  MultiUse = -1
END
Attribute VB_Name = "ArcoArgumentInput"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = False
Attribute VB_Exposed = False
Option Explicit

' One argument's box on the Insert Function panel. The panel builds its controls
' at run time, so their events arrive here and are handed back to the panel.
' A hidden argument has no Box; it only holds its place in the formula.

Public Arg As Object
Public Panel As Object
Public WithEvents Box As MSForms.ComboBox
Attribute Box.VB_VarHelpID = -1
' Beside the box: what the argument puts into the formula.
Public Preview As MSForms.Label
' True between a key typed into the box and the change it makes, so a list is
' filtered by typing but not by picking an item from it.
Public Typed As Boolean
' What the box held before its last change, put back when the cell entry of
' its list is chosen.
Public LastText As String

Private Sub Box_KeyPress(ByVal KeyAscii As MSForms.ReturnInteger)
    Typed = True
End Sub

' A box built at run time raises no Enter event, so a click, or the key that
' brought the focus here, tells the panel which argument is being filled in.
Private Sub Box_MouseDown(ByVal Button As Integer, ByVal Shift As Integer, ByVal X As Single, ByVal Y As Single)
    Panel.ArgumentEntered Me
End Sub

Private Sub Box_KeyDown(ByVal KeyCode As MSForms.ReturnInteger, ByVal Shift As Integer)
    If Panel.ArgumentKey(Me, CInt(KeyCode)) Then KeyCode = 0
End Sub

Private Sub Box_KeyUp(ByVal KeyCode As MSForms.ReturnInteger, ByVal Shift As Integer)
    Panel.ArgumentEntered Me
End Sub

Private Sub Box_Change()
    Panel.ArgumentChanged Me
    Typed = False
End Sub

Private Sub Box_DropButtonClick()
    Panel.ArgumentDropDown Me
End Sub

Private Sub Box_Click()
    Panel.ArgumentClicked Me
End Sub
