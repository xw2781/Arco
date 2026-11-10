# Check: the add-in can sign and send one Gateway request

A one-minute manual check that the add-in signs a request the way the ArcRho
Server verifies it, and that this PC can reach the Gateway. There is no
automated harness for the add-in's VBA, so this is the check. The fixed request
both halves sign is pinned to the Python contract by
`frontend/tests/test_excel_addin_gateway_signing.py`, which runs on its own.

## Without Excel

```
cscript //nologo excel-addin\tools\verify_gateway_signing.vbs
```

It prints the body digest and the signature for the fixed request, each beside
the value the contract produces, and ends with `match`. It exits `0` on a match
and `1` otherwise, so it can be run from a script. Nothing is sent anywhere.

## From Excel

With the add-in loaded, run `CheckArcRhoGateway` in the Immediate window, or
`ArcRhoGatewayCheckReport` from anywhere that wants the text. It signs the same
fixed request, then talks to the Gateway this PC is pointed at.

| Line | What it means |
| :--- | :--- |
| `vector digest` | The hash of the request body matches the contract. |
| `vector signature` | The signature over that body matches the contract. |
| `credential` | The user name and Gateway address from `%APPDATA%\ArcRho\arcrho_gateway.json`, or `none on this PC`. |
| `health` | `200` — the Gateway is up. |
| `capabilities` | `200` and the list of what this Gateway serves. |
| `signed request` | `400` — a deliberately unreadable request the Gateway accepted the signature for and then refused. `401` would mean the signature was refused. |

`400` is the pass on the last line. It is a request the server cannot read, sent
only to prove that the signature was checked and accepted first, and it reads no
project data.

## Recorded run

2026-09-12 on the developer Client PC `L-H2MQ6280FVP`, Excel 16.0 driven over
COM, add-in version 2.4.0, against the Gateway on `NE7SASWPN02`.

```
Arco Gateway check, add-in 2.4.0
vector digest    match    bede0538b3ba1824f3572ce81a492868099b0bfc4ba90b1ce9c105cb3cfc5656
vector signature match    3a81facfc86c05784d7978f8a2f2de06b6172b513c9f75d496777aff6008d2d0
credential       xwei at http://NE7SASWPN02.PRCINS.NET:28767
health           200 {"ok":true}
capabilities     200 {"ok":true,"hosted_save_http":true,"contract_version":1,...}
signed request   400 {"detail":"Not a workspace-read request."}
```

The standalone script printed the same two values and exited `0` on the same
day and the same PC.
