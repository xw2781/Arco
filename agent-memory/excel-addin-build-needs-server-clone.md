---
name: excel-addin-build-needs-server-clone
description: "the Excel add-in builds and releases from the Client PC by running the working clone's scripts with path arguments into E:\\XWSpace\\Repos\\Arco; the beta workbook, signature files, and rollback archive live only in that server clone"
metadata:
  node_type: memory
  type: project
  originSessionId: 77f89e08-e1c5-4e9e-93b2-da102d57416d
  modified: 2026-09-28T13:25:00.000Z
---

`excel-addin/beta/` and `excel-addin/signature/` are gitignored and exist **only** in the server clone `E:\XWSpace\Repos\Arco`. A fresh clone (including the Client PC working clone `C:\Users\xwei\Repos\Arco`) has neither, so its own `tools/build_xlam.ps1` stops at "Target XLAM not found" and `tools/release_xlam.ps1` at "Signature folder not found".

**Working recipe from the Client PC (since 2026-09-28, 4.2.1):** run the **working clone's** scripts and point their paths at the server clone. The server clone's scripts are stale (it is behind), and since 4.2.1 the build needs `excel-addin/RELEASE_NOTES.md` beside `src_vba` and the release checks the version. Exact commands are in `agent-instructions/excel-addin-build-and-release.md`. The older recipe (server clone's scripts with `-SourceDir`) skips the release-notes check and must not be used.

- `git` refuses the E: clone ("dubious ownership") unless run with `-c safe.directory='*'`; it is usually behind and dirty with other work, which does not matter because only its gitignored `beta\` and `signature\` folders are used.
- The build can fail once with "ARCRHO_BETA.xlam ... being used by another process" right after it rewrote the ribbon XML inside the zip. That is a share write race, not a user's Excel; rerun the same command. The user's own Excel windows never need closing.
- "Importing new UserForm ufBuildTriangle.frm" is a benign build warning; the verify script still reports all modules matching.
- Excel COM refuses to set `Application.Calculation` before a workbook exists; add the workbook first in any probe script.

Why the build stays on that clone's artifacts: `build_xlam.ps1` updates `beta\ARCRHO_BETA.xlam` **in place** (it never creates the workbook, which carries the ribbon and userform package); `release_xlam.ps1` needs `signature\vbaProjectSignature*.bin` to re-sign the VBA project; and the release **moves** the live `E:\ArcRho Server\Excel Add-ins\ArcRho.xlam` into that clone's `beta\Archive`, so one archive keeps the whole rollback history.

Related: [[arcrho-local-release-build]], [[dev-pc-and-client-pc-identity]], [[deploy-without-asking]], [[build-listener-request-read-race]].
