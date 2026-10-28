Option Private Module
Option Explicit

' The add-in's client for the ArcRho Gateway: the user's credential, one
' signed POST, and the two unauthenticated GET routes.
'
' The signature is owned by python-api/src/arcrho_hosted_save_http_contract.py.
' Its message is the lower-cased user name, the Unix timestamp, the method, the
' request path and the hex SHA-256 of the exact bytes sent, joined by line
' feeds and keyed by the user's secret. The server refuses a timestamp more
' than five minutes from its own clock, so the timestamp is UTC seconds.
' Nothing here needs sorted canonical JSON: the digest covers the bytes this
' client sends, whatever their order.
'
' frontend/tests/test_excel_addin_gateway_signing.py derives the vector and the
' route names below from that contract and fails if either side moves.

' The Gateway's routes. The two GET routes are open; every POST route is signed.
Public Const GATEWAY_HEALTH_PATH As String = "/api/health"
Public Const GATEWAY_CAPABILITIES_PATH As String = "/api/capabilities"
Public Const GATEWAY_WORKSPACE_READ_PATH As String = "/api/workspace-reads"
Public Const GATEWAY_ENGINE_CALCULATION_PATH As String = "/api/engine-calculations"
' The capabilities field naming the calculation operations this Gateway serves.
Public Const GATEWAY_OPERATIONS_FIELD As String = "engine_calculation_operations"

' --- begin gateway workspace read names ---
' The request spellings arcrho_workspace_read_contract owns, and the one read
' the add-in makes: the project names, reserving classes, and dataset types its
' pickers offer, answered together.
Private Const GATEWAY_READ_FUNCTION As String = "ArcRhoWorkspaceRead"
Private Const GATEWAY_READ_CONTRACT_VERSION As String = "1"
Private Const GATEWAY_READ_FORMULA_CHOICES As String = "excel_formula_choices"
Private Const GATEWAY_READ_TIMEOUT_SECONDS As Long = 60
' --- end gateway workspace read names ---

' --- begin gateway calculation names ---
' The request and answer spellings arcrho_engine_calculation_contract owns.
Private Const GATEWAY_CALCULATION_FUNCTION As String = "ArcRhoEngineCalculation"
Private Const GATEWAY_CONTRACT_VERSION As String = "1"
Private Const GATEWAY_OPERATION_DATASET_CSV As String = "dataset_csv"
Private Const GATEWAY_OUTPUT_VARIANT As String = "canonical"
Private Const GATEWAY_CSV_FIELD As String = "csv_text"
' --- end gateway calculation names ---

' How long the server may spend on one formula's figures, and how long this PC
' waits for the answer. The margin is the contract's own
' ENGINE_CALCULATION_HTTP_TIMEOUT_MARGIN_SECONDS.
Private Const DATASET_WAIT_SECONDS As Long = 60
Private Const DATASET_HTTP_TIMEOUT_SECONDS As Long = 75

' --- begin gateway signing vector ---
' One fixed request signed against sign_request in the contract above.
' "\uXXXX" stands for one character, so that this file stays ASCII.
Private Const VECTOR_SECRET As String = "probe-secret-value"
Private Const VECTOR_USER As String = "XWei"
Private Const VECTOR_TIMESTAMP As String = "1757650000"
Private Const VECTOR_METHOD As String = "POST"
Private Const VECTOR_PATH As String = "/api/workspace-reads"
Private Const VECTOR_BODY As String = "{""Function"":""ArcRhoWorkspaceRead"",""Name"":""Net Loss--Paid \u00e9""}"
Private Const VECTOR_DIGEST As String = "bede0538b3ba1824f3572ce81a492868099b0bfc4ba90b1ce9c105cb3cfc5656"
Private Const VECTOR_SIGNATURE As String = "3a81facfc86c05784d7978f8a2f2de06b6172b513c9f75d496777aff6008d2d0"
' --- end gateway signing vector ---

Private Const HEADER_USER As String = "X-ArcRho-User"
Private Const HEADER_TIMESTAMP As String = "X-ArcRho-Timestamp"
Private Const HEADER_SIGNATURE As String = "X-ArcRho-Signature"
Private Const GATEWAY_CONFIG_FILE As String = "ArcRho\arcrho_gateway.json"
' The helper on the ArcRho Server that gives this PC its own credential. The
' share is what proves who is asking, so the work happens there and not here.
Private Const CREDENTIAL_HELPER As String = "apps\ArcRho Credential\ArcRho Credential.exe"

Private gatewayConfigRead As Boolean
Private gatewayEnabled As Boolean
Private gatewayUrl As String
Private gatewayUser As String
Private gatewaySecret As String
Private gatewayRequest As Object
Private credentialInstallTried As Boolean
Private gatewayCapabilities As Object
Private gatewayServesCsv As Boolean
Private gatewayServesCsvRead As Boolean
Private gatewayRequestCounter As Long

' True when this PC carries a credential the Gateway will accept.
Public Function GatewayIsConfigured() As Boolean
    EnsureGatewayConfig
    GatewayIsConfigured = gatewayEnabled
End Function

Public Function GatewayUserName() As String
    EnsureGatewayConfig
    GatewayUserName = gatewayUser
End Function

' Sign one request and post it. Answers True when the Gateway replied at all,
' with its status and body; False when there is no credential or the request
' never reached it, with the reason in outText.
Public Function GatewayPost(ByVal requestPath As String, ByVal body As String, _
                            ByVal timeoutSeconds As Long, ByRef outStatus As Long, _
                            ByRef outText As String) As Boolean
    Dim bodyBytes As Variant
    Dim stamp As String
    Dim req As Object

    outStatus = 0
    outText = ""
    EnsureGatewayConfig
    If Not gatewayEnabled Then
        outText = "This PC has no Arco Gateway credential."
        Exit Function
    End If

    bodyBytes = Utf8Bytes(body)
    stamp = GatewayUnixTimestamp()
    Set req = GatewayRequestObject()

    On Error GoTo Failed
    req.Open "POST", gatewayUrl & requestPath, False
    req.SetTimeouts 5000, 10000, timeoutSeconds * 1000&, timeoutSeconds * 1000&
    req.SetRequestHeader "Content-Type", "application/json; charset=utf-8"
    req.SetRequestHeader HEADER_USER, gatewayUser
    req.SetRequestHeader HEADER_TIMESTAMP, stamp
    req.SetRequestHeader HEADER_SIGNATURE, _
        GatewaySignature(gatewaySecret, gatewayUser, stamp, "POST", requestPath, bodyBytes)
    req.Send bodyBytes
    outStatus = req.Status
    outText = req.ResponseText
    GatewayPost = True
    Exit Function

Failed:
    Set gatewayRequest = Nothing
    outText = Err.Description
End Function

' The open GET routes: health and capabilities carry no signature.
Public Function GatewayGet(ByVal requestPath As String, ByVal timeoutSeconds As Long, _
                           ByRef outStatus As Long, ByRef outText As String) As Boolean
    Dim req As Object

    outStatus = 0
    outText = ""
    EnsureGatewayConfig
    If Not gatewayEnabled Then
        outText = "This PC has no Arco Gateway credential."
        Exit Function
    End If

    Set req = GatewayRequestObject()
    On Error GoTo Failed
    req.Open "GET", gatewayUrl & requestPath, False
    req.SetTimeouts 5000, 10000, timeoutSeconds * 1000&, timeoutSeconds * 1000&
    req.Send
    outStatus = req.Status
    outText = req.ResponseText
    GatewayGet = True
    Exit Function

Failed:
    Set gatewayRequest = Nothing
    outText = Err.Description
End Function

Public Function GatewayIsHealthy() As Boolean
    Dim replyStatus As Long
    Dim replyText As String
    If Not GatewayGet(GATEWAY_HEALTH_PATH, 10, replyStatus, replyText) Then Exit Function
    GatewayIsHealthy = (replyStatus = 200)
End Function

' The capabilities document, read once per Excel session.
Public Function GatewayCapabilityDocument() As Object
    Dim replyStatus As Long
    Dim replyText As String

    If Not gatewayCapabilities Is Nothing Then
        Set GatewayCapabilityDocument = gatewayCapabilities
        Exit Function
    End If
    If Not GatewayGet(GATEWAY_CAPABILITIES_PATH, 10, replyStatus, replyText) Then Exit Function
    If replyStatus <> 200 Then Exit Function
    Set gatewayCapabilities = JsonParse(replyText)
    Set GatewayCapabilityDocument = gatewayCapabilities
End Function

' True when the Gateway advertises value in one of its capability lists, so a
' caller can ask before using an operation this server may be too old to serve.
Public Function GatewayAdvertises(ByVal fieldName As String, ByVal value As String) As Boolean
    Dim document As Object
    Dim items As Collection
    Dim i As Long

    Set document = GatewayCapabilityDocument()
    If document Is Nothing Then Exit Function
    If Not document.Exists(fieldName) Then Exit Function
    If Not IsObject(document(fieldName)) Then Exit Function

    Set items = document(fieldName)
    For i = 1 To items.Count
        If StrComp(Trim$(CStr(items.Item(i))), value, vbTextCompare) = 0 Then
            GatewayAdvertises = True
            Exit Function
        End If
    Next i
End Function

' True when this Gateway answers a dataset request with its figures. Asked once
' per Excel session, so a formula never pays for the capabilities call.
Public Function GatewayServesDatasetCsv() As Boolean
    If Not gatewayServesCsvRead Then
        gatewayServesCsvRead = True
        gatewayServesCsv = GatewayAdvertises(GATEWAY_OPERATIONS_FIELD, GATEWAY_OPERATION_DATASET_CSV)
    End If
    GatewayServesDatasetCsv = gatewayServesCsv
End Function

' Ask the ArcRho Server for one dataset's figures. funcArgs is the request text
' a worksheet function already builds; its pairs travel as they are, and the
' server derives the dataset's location, the acting user and the shape itself.
' Answers True with the CSV text, or False with the reason to show the user.
Public Function GatewayDatasetCsv(ByVal funcArgs As String, _
                                  ByRef outText As String, ByRef outMessage As String, _
                                  Optional ByRef outUnavailable As Boolean) As Boolean
    Dim replyStatus As Long
    Dim replyText As String
    Dim reply As Object

    outText = ""
    outMessage = ""
    outUnavailable = False
    If Not GatewayPost(GATEWAY_ENGINE_CALCULATION_PATH, _
                       DatasetCalculationBody(funcArgs), _
                       DATASET_HTTP_TIMEOUT_SECONDS, replyStatus, replyText) Then
        outMessage = "Arco Server not reached: " & OneLine(TextOrNoAnswer(replyText))
        Exit Function
    End If

    Set reply = ParsedReply(replyText)
    If replyStatus <> 200 Then
        outMessage = "Arco Server " & replyStatus & ": " & ReplyMessage(reply, replyText)
        Exit Function
    End If
    If reply Is Nothing Then
        outMessage = "Arco Server sent an answer this add-in could not read."
        Exit Function
    End If
    If Not ReplyIsOk(reply) Then
        outMessage = ReplyMessage(reply, replyText)
        If reply.Exists("status") Then outUnavailable = (CStr(reply("status")) = "published_dataset_unavailable")
        Exit Function
    End If
    If Not reply.Exists(GATEWAY_CSV_FIELD) Then
        outMessage = "Arco Server answered without the dataset's figures."
        Exit Function
    End If

    outText = CStr(reply(GATEWAY_CSV_FIELD))
    GatewayDatasetCsv = True
End Function

' Ask the ArcRho Server for the lists the pickers offer: the project names and,
' when a project is named, its reserving classes and dataset types. Answers
' True with the parsed reply, or False with the reason to show the user.
Public Function GatewayFormulaChoices(ByVal projectName As String, _
                                      ByRef outReply As Object, _
                                      ByRef outMessage As String) As Boolean
    Dim replyStatus As Long
    Dim replyText As String
    Dim reply As Object

    Set outReply = Nothing
    outMessage = ""
    EnsureGatewayCredential
    EnsureGatewayConfig
    If Not gatewayEnabled Then
        outMessage = "This PC is not set up to read Arco data. " & _
                     "Ask the Arco team to give you access, then restart Excel."
        Exit Function
    End If

    If Not GatewayPost(GATEWAY_WORKSPACE_READ_PATH, _
                       FormulaChoicesReadBody(projectName), _
                       GATEWAY_READ_TIMEOUT_SECONDS, replyStatus, replyText) Then
        outMessage = "Arco Server not reached: " & OneLine(TextOrNoAnswer(replyText))
        Exit Function
    End If

    Set reply = ParsedReply(replyText)
    If replyStatus <> 200 Then
        outMessage = "Arco Server " & replyStatus & ": " & ReplyMessage(reply, replyText)
        Exit Function
    End If
    If reply Is Nothing Then
        outMessage = "Arco Server sent an answer this add-in could not read."
        Exit Function
    End If
    If Not reply.Exists("projects") Or Not reply.Exists("reserving_classes") _
       Or Not reply.Exists("dataset_types") Then
        outMessage = "Ask the Arco team to update the Arco Server."
        Exit Function
    End If

    Set outReply = reply
    GatewayFormulaChoices = True
End Function

' The request body the workspace-read contract validates: the read's name and
' the project it is asked for, and nothing about where the project lives.
Private Function FormulaChoicesReadBody(ByVal projectName As String) As String
    Dim body As String

    body = "{" & JsonQuote("Function") & ":" & JsonQuote(GATEWAY_READ_FUNCTION)
    body = body & "," & JsonQuote("ContractVersion") & ":" & GATEWAY_READ_CONTRACT_VERSION
    body = body & "," & JsonQuote("RequestId") & ":" & JsonQuote(NextRequestId())
    body = body & "," & JsonQuote("ReadKind") & ":" & JsonQuote(GATEWAY_READ_FORMULA_CHOICES)
    body = body & "," & JsonQuote("Kwargs") & ":{"
    If Len(projectName) > 0 Then
        body = body & JsonQuote("project_name") & ":" & JsonQuote(projectName)
    End If
    body = body & "}"
    body = body & "," & JsonQuote("UserName") & ":" & JsonQuote(gatewayUser)
    body = body & "," & JsonQuote("UserDisplayName") & ":" & JsonQuote("") & "}"
    FormulaChoicesReadBody = body
End Function

' The request body the calculation contract validates: only the logical pairs
' the worksheet function asked with and the read operation. The server owns
' whether a temporary dataset cache is current.
Private Function DatasetCalculationBody(ByVal funcArgs As String) As String
    Dim body As String

    body = "{" & JsonQuote("Function") & ":" & JsonQuote(GATEWAY_CALCULATION_FUNCTION)
    body = body & "," & JsonQuote("ContractVersion") & ":" & GATEWAY_CONTRACT_VERSION
    body = body & "," & JsonQuote("RequestId") & ":" & JsonQuote(NextRequestId())
    body = body & "," & JsonQuote("Pairs") & ":[" & RequestPairsJson(funcArgs) & "]"
    body = body & "," & JsonQuote("TimeoutSeconds") & ":" & DATASET_WAIT_SECONDS
    body = body & "," & JsonQuote("OutputVariant") & ":" & JsonQuote(GATEWAY_OUTPUT_VARIANT)
    body = body & "," & JsonQuote("Operation") & ":" & JsonQuote(GATEWAY_OPERATION_DATASET_CSV)
    body = body & "," & JsonQuote("Options") & ":{}"
    body = body & "," & JsonQuote("UserName") & ":" & JsonQuote(gatewayUser)
    body = body & "," & JsonQuote("UserDisplayName") & ":" & JsonQuote("") & "}"
    DatasetCalculationBody = body
End Function

' "Key = Value" pairs, in the order the worksheet function wrote them: the
' header function's own output name is derived from that order on the server.
'
' The name a worksheet formula gives is the name of one dataset in the class,
' which is what the server calls the instance name. The share path says so by
' choosing the instance name over the type name when it builds the file name;
' this says the same thing by naming the instance, so the server can tell a
' dataset whose own name differs from its type's from a stale cache.
Private Function RequestPairsJson(ByVal funcArgs As String) As String
    Dim lines() As String
    Dim line As String
    Dim key As String
    Dim value As String
    Dim sepPos As Long
    Dim i As Long
    Dim pairs As String
    Dim instanceName As String
    Dim namesInstance As Boolean

    lines = Split(Replace(Replace(Replace(funcArgs, vbCrLf, "#"), vbCr, "#"), vbLf, "#"), "#")
    For i = LBound(lines) To UBound(lines)
        line = Trim$(lines(i))
        sepPos = InStr(1, line, "=", vbBinaryCompare)
        If sepPos > 1 Then
            key = Trim$(Left$(line, sepPos - 1))
            value = Trim$(Mid$(line, sepPos + 1))
            If Len(key) > 0 Then
                Select Case LCase$(key)
                    Case "instancename"
                        namesInstance = True
                    Case "datasetname", "trianglename", "vectorname"
                        If Len(instanceName) = 0 Then instanceName = value
                End Select
                If Len(pairs) > 0 Then pairs = pairs & ","
                pairs = pairs & "[" & JsonQuote(key) & "," & JsonQuote(value) & "]"
            End If
        End If
    Next i
    If Not namesInstance And Len(instanceName) > 0 Then
        pairs = pairs & ",[" & JsonQuote("InstanceName") & "," & JsonQuote(instanceName) & "]"
    End If
    RequestPairsJson = pairs
End Function



' A token the server logs this request under. Unique within the session, and
' made only of the characters the contract accepts.
Private Function NextRequestId() As String
    gatewayRequestCounter = gatewayRequestCounter + 1
    NextRequestId = "excel-" & Format$(Now, "yyyymmdd-hhmmss") & "-" & gatewayRequestCounter
End Function

Private Function ParsedReply(ByVal replyText As String) As Object
    On Error Resume Next
    Set ParsedReply = JsonParse(replyText)
End Function

Private Function ReplyIsOk(ByVal reply As Object) As Boolean
    If Not reply.Exists("ok") Then Exit Function
    On Error Resume Next
    ReplyIsOk = CBool(reply("ok"))
End Function

' What the server said went wrong, in the order the server says it: a refusal
' carries "detail", a run that failed carries "message", and "status" is the
' last resort before the raw answer.
Private Function ReplyMessage(ByVal reply As Object, ByVal replyText As String) As String
    Dim names As Variant
    Dim i As Long

    If Not reply Is Nothing Then
        names = Array("message", "detail", "status")
        For i = LBound(names) To UBound(names)
            If reply.Exists(CStr(names(i))) Then
                ReplyMessage = Trim$(CStr(reply(CStr(names(i)))))
                If Len(ReplyMessage) > 0 Then Exit Function
            End If
        Next i
    End If
    ReplyMessage = OneLine(TextOrNoAnswer(replyText))
End Function

Private Function TextOrNoAnswer(ByVal text As String) As String
    TextOrNoAnswer = Trim$(text)
    If Len(TextOrNoAnswer) = 0 Then TextOrNoAnswer = "no answer"
End Function

' Sign the fixed vector, then talk to the Gateway this PC is pointed at.
' Run it from the Immediate window with CheckArcRhoGateway.
Public Function ArcRhoGatewayCheckReport() As String
    Dim report As String
    Dim bodyBytes As Variant
    Dim digest As String
    Dim signature As String
    Dim replyStatus As Long
    Dim replyText As String

    bodyBytes = Utf8Bytes(UnescapeUnicode(VECTOR_BODY))
    digest = Sha256Hex(bodyBytes)
    signature = GatewaySignature(VECTOR_SECRET, VECTOR_USER, VECTOR_TIMESTAMP, _
                                 VECTOR_METHOD, VECTOR_PATH, bodyBytes)

    report = "Arco Gateway check, add-in " & ARCRHO_VERSION
    report = report & vbLf & "vector digest    " & Verdict(digest = VECTOR_DIGEST) & " " & digest
    report = report & vbLf & "vector signature " & Verdict(signature = VECTOR_SIGNATURE) & " " & signature

    EnsureGatewayConfig
    If Not gatewayEnabled Then
        ArcRhoGatewayCheckReport = report & vbLf & "credential       none on this PC"
        Exit Function
    End If
    report = report & vbLf & "credential       " & gatewayUser & " at " & gatewayUrl

    GatewayGet GATEWAY_HEALTH_PATH, 10, replyStatus, replyText
    report = report & vbLf & "health           " & replyStatus & " " & OneLine(replyText)
    GatewayGet GATEWAY_CAPABILITIES_PATH, 10, replyStatus, replyText
    report = report & vbLf & "capabilities     " & replyStatus & " " & OneLine(replyText)
    ' A signed POST the server cannot read: 400 means it accepted the signature
    ' and then refused the payload, 401 means it refused the signature.
    GatewayPost GATEWAY_WORKSPACE_READ_PATH, "{}", 10, replyStatus, replyText
    report = report & vbLf & "signed request   " & replyStatus & " " & OneLine(replyText)

    ArcRhoGatewayCheckReport = report
End Function

Public Sub CheckArcRhoGateway()
    Debug.Print ArcRhoGatewayCheckReport()
End Sub

Private Function Verdict(ByVal matched As Boolean) As String
    If matched Then
        Verdict = "match   "
    Else
        Verdict = "MISMATCH"
    End If
End Function

Private Function OneLine(ByVal text As String) As String
    OneLine = Replace(Replace(text, vbCr, " "), vbLf, " ")
    If Len(OneLine) > 200 Then OneLine = Left$(OneLine, 200) & "..."
End Function

Private Sub EnsureGatewayConfig()
    Dim credentialPath As String
    Dim credential As Object

    If gatewayConfigRead Then Exit Sub
    gatewayConfigRead = True

    credentialPath = Environ$("APPDATA") & "\" & GATEWAY_CONFIG_FILE
    If Len(Dir$(credentialPath)) = 0 Then Exit Sub
    Set credential = JsonParse(ReadUtf8TextFile(credentialPath))
    If Not credential("enabled") = True Then Exit Sub

    gatewayUrl = TrimTrailing(Trim$(CStr(credential("url"))), "/")
    gatewayUser = Trim$(CStr(credential("user")))
    gatewaySecret = Trim$(CStr(credential("secret")))
    gatewayEnabled = (Len(gatewayUrl) > 0 And Len(gatewayUser) > 0 And Len(gatewaySecret) > 0)
End Sub

' Give this PC its own access to the ArcRho Server when it has none. Called as
' a user explicitly refreshes, never when the add-in loads or a saved workbook
' calculates. Reading a workbook snapshot needs no server credential.
'
' It is tried once per Excel session: a PC away from the office should pay one
' short failure on refresh, not one per launch, and certainly not one per
' formula. A file that is already here is the answer whatever it says, because
' a credential turned off is a deliberate choice and not a missing one.
Public Sub EnsureGatewayCredential()
    Dim helperPath As String
    Dim shell As Object

    If credentialInstallTried Then Exit Sub
    credentialInstallTried = True

    On Error GoTo CleanExit
    If Len(Dir$(Environ$("APPDATA") & "\" & GATEWAY_CONFIG_FILE)) > 0 Then Exit Sub

    ' The first look at the share. When it cannot be reached this fails here,
    ' before anything is shown or started, and the session simply goes on.
    helperPath = ProductPath(CREDENTIAL_HELPER)
    If Len(Dir$(helperPath)) = 0 Then Exit Sub

    If Not disable_ufLoading Then
        ufLoading.UpdateText "Setting this PC up to read Arco data ..."
        ufLoading.Show vbModeless
    End If
    DoEvents

    Set shell = CreateObject("WScript.Shell")
    shell.Run """" & helperPath & """ """ & ProductRootPath() & """", 0, True

    ' Whatever the helper did, this session has not looked at the credential
    ' yet, so let this refresh read what is there now.
    ClearGatewayConfigCache

CleanExit:
    On Error Resume Next
    Unload ufLoading
    ufLoading.Reset
End Sub

' Forget this session's answer about the credential.
Public Sub ClearGatewayConfigCache()
    gatewayConfigRead = False
    gatewayEnabled = False
    gatewayUrl = ""
    gatewayUser = ""
    gatewaySecret = ""
End Sub

' One request object for the session, so a formula does not rebuild the
' connection the previous formula just used.
Private Function GatewayRequestObject() As Object
    If gatewayRequest Is Nothing Then
        Set gatewayRequest = CreateObject("WinHttp.WinHttpRequest.5.1")
    End If
    Set GatewayRequestObject = gatewayRequest
End Function

Private Function GatewaySignature(ByVal secret As String, ByVal user As String, _
                                  ByVal stamp As String, ByVal method As String, _
                                  ByVal requestPath As String, ByVal bodyBytes As Variant) As String
    Dim message As String
    message = LCase$(Trim$(user)) & vbLf & Trim$(stamp) & vbLf & UCase$(Trim$(method)) & _
              vbLf & Trim$(requestPath) & vbLf & Sha256Hex(bodyBytes)
    GatewaySignature = HmacSha256Hex(Utf8Bytes(secret), Utf8Bytes(message))
End Function

' The Unix second the server compares against its own clock.
Private Function GatewayUnixTimestamp() As String
    Dim clock As Object
    Dim utcNow As Date

    Set clock = CreateObject("WbemScripting.SWbemDateTime")
    clock.SetVarDate Now, True
    utcNow = clock.GetVarDate(False)
    GatewayUnixTimestamp = Format$(Int((CDbl(utcNow) - CDbl(DateSerial(1970, 1, 1))) * 86400#), "0")
End Function

' UTF-8 bytes, without the byte-order mark ADODB.Stream writes ahead of them.
Private Function Utf8Bytes(ByVal text As String) As Variant
    Dim stream As Object

    Set stream = CreateObject("ADODB.Stream")
    stream.Type = 2
    stream.Charset = "utf-8"
    stream.Open
    stream.WriteText text
    stream.Position = 0
    stream.Type = 1
    stream.Position = 3
    Utf8Bytes = stream.Read
    stream.Close
End Function

Private Function Sha256Hex(ByVal bytes As Variant) As String
    Dim digest As Object
    Set digest = CreateObject("System.Security.Cryptography.SHA256Managed")
    Sha256Hex = HexText(digest.ComputeHash_2((bytes)))
End Function

Private Function HmacSha256Hex(ByVal keyBytes As Variant, ByVal messageBytes As Variant) As String
    Dim mac As Object
    Set mac = CreateObject("System.Security.Cryptography.HMACSHA256")
    mac.Key = keyBytes
    HmacSha256Hex = HexText(mac.ComputeHash_2((messageBytes)))
End Function

Private Function HexText(ByVal bytes As Variant) As String
    Dim node As Object
    Set node = CreateObject("MSXML2.DOMDocument").createElement("hex")
    node.DataType = "bin.hex"
    node.nodeTypedValue = bytes
    HexText = LCase$(node.Text)
End Function

' Turn "\u00e9" and its like into the character it stands for, so that a source
' file carrying a fixed request can stay ASCII.
Private Function UnescapeUnicode(ByVal text As String) As String
    Dim result As String
    Dim at As Long

    result = text
    Do
        at = InStr(result, "\u")
        If at = 0 Then Exit Do
        result = Left$(result, at - 1) & ChrW$(CLng("&H" & Mid$(result, at + 2, 4))) & Mid$(result, at + 6)
    Loop
    UnescapeUnicode = result
End Function

Private Function TrimTrailing(ByVal text As String, ByVal character As String) As String
    TrimTrailing = text
    Do While Len(TrimTrailing) > 0 And Right$(TrimTrailing, 1) = character
        TrimTrailing = Left$(TrimTrailing, Len(TrimTrailing) - 1)
    Loop
End Function
