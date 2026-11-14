---
name: user-folder-tests-touch-real-folders
description: tests that run a hosted service or the folder rename can write to the real server root and the real user profile; pin the root and pass explicit paths
metadata:
  type: feedback
---

Three things I did on 2026-11-14 on the Server PC (NE7SASWPN02) while testing the per-user server folder, each of which touched something real and had to be undone by hand:

- A Gateway executor test that ran a real service (not a mock) wrote `E:\Arco Server\users\alice\...` into the production root. The executor's own root does not steer `app_server.config`; only `ARCRHO_RUNTIME_SERVER_ROOT` does.
- A Node test of the folder rename renamed my real `Documents\ArcRho`, because the home Documents folder was a built-in default rather than an argument.
- The frontend Python suite creates `%LOCALAPPDATA%\Arco\logs\client_read_latency.jsonl` and an empty `Documents\Arco\macros` in the real profile on every run. This predates the change (it used to land in the ArcRho folders, where it went unnoticed).

**Why:** none of these fail a test; the damage is only visible by looking at the real folders afterwards.

**How to apply:** in a test that runs a server-side service, patch `os.environ` with `ARCRHO_RUNTIME_SERVER_ROOT` set to the test's own folder. Give any function that moves or deletes user folders explicit paths and no machine default in tests. After running the suites on a PC whose folders have not been renamed yet, look for a stray `%LOCALAPPDATA%\Arco`, `Documents\Arco` and `<server root>\users` and remove what the run created. Related: [[user-folder-on-server-and-arco-rename]], [[job-tests-read-live-gateway]].
