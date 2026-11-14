# Writing and Running Tests

Read this before adding or editing a test, or running a test suite.

## Test temporary files (MUST)
Every temporary directory a test creates must live under `tmp_data/` at the repository root, whichever test tree the test belongs to — `frontend/tests`, `python-api/tests`, `server-components/tests`, or `tools/tests`. Anchor it on the repository root rather than on the test file, so one folder collects the output of every suite:

```python
TEST_TEMP_ROOT = Path(__file__).resolve().parents[N] / "tmp_data"   # N reaches the repository root
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
self.temp = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
```

- **Never pass the repository root, a package root, or a test folder as `dir=`.** `tempfile.TemporaryDirectory(dir=REPO_ROOT)` drops a `tmp<random>` folder beside the code, and a test that raises in `setUp` never reaches the teardown that would remove it — one interrupted suite run left 33 of them loose in the root. `tmp_data/` keeps that failure mode in one place a single `rm -rf` can clear.
- **Create the directory in the test, not by hand.** `mkdir(parents=True, exist_ok=True)` at import time is enough; the folder is gitignored and must never be committed or relied on existing.
- **Still clean up.** Use `TemporaryDirectory` (or an equivalent that survives a failure) so a passing run leaves nothing behind in `tmp_data/`. The folder is a backstop for the runs that fail, not a licence to leak.
- **Applies to new and edited tests.** Do not mass-migrate existing suites as a side effect of unrelated work; when you touch a test that anchors its temp directory anywhere else — including the older `test/` folder — move that one onto `tmp_data/` as part of the change.

## Tests and the Gateway (MUST)
A developer PC is signed in to a real Gateway, so a test that patches the workspace root but not the Gateway would read from and write to that server. `python-api/src/arcrho_api/gateway_test_guard.py` prevents it: in a process started as a test run (`python -m unittest` from any folder, pytest, or a `tests/test_*.py` file run directly) and in every process that run starts, the Gateway credential points at a missing file and every Gateway client refuses a URL no test allowed, as if the Gateway were unreachable. Nothing needs importing; the guard sits in the credential lookup and the Gateway clients.
- **A test sees no Gateway.** A Gateway-only operation answers 503 in a test. Stub what the test needs (for example the propagation busy check), or run the check as a server process against the test's own temporary root.
- **A test that starts its own Gateway on loopback opts in** with `self.addCleanup(allow_test_gateway(url))`. Only loopback URLs can be allowed; allow only the server the test itself started, never the local test server at `C:\Arco Server`.
- **Record mode.** Set `ARCRHO_TEST_GATEWAY_RECORD` to a file path and every refused request is appended there with the test that sent it; a clean run records nothing.
- A new Gateway HTTP client builds its opener with `gateway_test_guard.gateway_opener()`, never `build_opener` directly.
