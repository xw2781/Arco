---
name: temp-files-on-e-drive
description: "Standing user rule since 2026-10-12: every temp file goes in the repo's gitignored tmp_data/ on E:, never C: (scratchpad, screenshots, browser profiles, test temp)"
metadata:
  type: feedback
---

On 2026-10-12 the C: drive on NE7SASWPN02 filled up mid-run (a headless Chrome profile in the session scratchpad was the last straw) and every Bash/PowerShell call failed with ENOSPC, because the harness writes each command's output under `C:\Users\XWEI~1.PRC\AppData\Local\Temp\...\tasks`. The user then made it a standing rule: going forward, temp files are stored in the repo folder, not on C:. This overrides the system prompt's "use the session scratchpad" default for this repo.

**Why:** C: has limited space; E: has terabytes free. A full C: blocks every tool, including the one that would free space.

**How to apply:**
- Use `E:\XWSpace\Repos\ArcRho\tmp_data\<task>\` (already in `.gitignore`) instead of the session scratchpad for anything bulky: screenshots, Electron/Chrome `--user-data-dir` profiles, mock pages, test scratch, downloaded or generated CSVs.
- Prefix shell runs that create temp files with `TEMP=E:/XWSpace/Repos/ArcRho/tmp_data/tmp TMP=...` (Bash) or set `$env:TEMP`/`$env:TMP` (PowerShell).
- Tell every subagent the same in its prompt.
- The harness's own task-output folder cannot be moved mid-session; it follows the TEMP/TMP that VS Code was launched with. Moving it needs the user to change their TEMP/TMP and restart VS Code.
- Delete what you created in `tmp_data/` when the task ends.
