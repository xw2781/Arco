# Excel Add-in Build and Release

After making changes under `excel-addin/`, automatically run the non-interactive build and release scripts unless the user explicitly asks not to build or release.

Every release is a new version with its own notes:

- Raise `ARCRHO_VERSION` in `excel-addin/src_vba/Core.bas` (patch for fixes, minor for new features) once per release, not once per edit.
- Add a `## <version> - <yyyy-mm-dd>` entry at the top of `excel-addin/RELEASE_NOTES.md` with one plain-English bullet per change a user would notice. If the version has not been released yet, add to its existing entry instead.
- The build refuses to run when the newest notes entry is not `ARCRHO_VERSION`, and the release refuses a version that is already on the share. The release publishes the notes beside the add-in as `Arco Release Notes.md`, which the About window opens.

Run the scripts from the clone you edited. The beta workbook, the signature files, and the rollback archive exist only in the Server PC clone `E:\XWSpace\Repos\ArcRho`, so point the scripts there:

- Step 1: `powershell -NoProfile -ExecutionPolicy Bypass -File "<clone>\excel-addin\tools\build_xlam.ps1" -TargetPath "E:\XWSpace\Repos\ArcRho\excel-addin\beta\ARCRHO_BETA.xlam"`
- Check: `py -3.10 <clone>\excel-addin\tools\verify_built_addin.py "E:\XWSpace\Repos\ArcRho\excel-addin\beta\ARCRHO_BETA.xlam"`
- Step 2: `powershell -NoProfile -ExecutionPolicy Bypass -File "<clone>\excel-addin\tools\release_xlam.ps1" -BetaPath "E:\XWSpace\Repos\ArcRho\excel-addin\beta\ARCRHO_BETA.xlam" -SignatureDir "E:\XWSpace\Repos\ArcRho\excel-addin\signature" -ArchiveDir "E:\XWSpace\Repos\ArcRho\excel-addin\beta\Archive" -ExtractDir "E:\XWSpace\Repos\ArcRho\excel-addin\beta\_release_unpack"`

Run from the Server PC clone itself, the scripts need no path arguments.

Treat this as pre-approved by the repository instructions for Excel add-in changes, but still follow environment requirements for sandbox escalation because the scripts update the beta add-in and release add-in outside the repository. Do not use `Step 1+2 - Build and Release ArcRho.bat` for agent validation because its interactive prompt can hang in agent terminals. If either direct script is blocked, fails, or times out, report that clearly.
