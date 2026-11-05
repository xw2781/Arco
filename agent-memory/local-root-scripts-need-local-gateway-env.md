---
name: local-root-scripts-need-local-gateway-env
description: A tools/ script run against the local test root with only ARCRHO_SERVER_ROOT set sends its Engine calculations to the production Gateway; set the local credential and URL too
metadata:
  type: feedback
---

A script that imports `app_server` services (the restate tools, a dataset load) is a Client-PC process: every Engine calculation and propagation submit goes to the Gateway named by the user's credential, which is production's. Setting `ARCRHO_SERVER_ROOT` to the local root redirects only the file paths.

**Why:** 2026-11-04, Fake refresh step 3 on NE7SASWPN02: a `restate_percentage_developed.py --dry-run` with only `ARCRHO_SERVER_ROOT='E:\XWSpace\Arco Server'` deleted 76 local engine CSVs (stale cache cleared before the request) and had the production Engine regenerate the same 76 CSVs in production's `NJ_Annual_Prod_202605_Fake`; the local copies were never written. A dry run of that tool is not read-only: reading precedents regenerates engine caches.

**How to apply:** set all three, exactly as `local_server.py launch-app` does, and check `config.load_gateway_config()["url"]` is `http://127.0.0.1:28767` before running:

```
export ARCRHO_SERVER_ROOT='E:\XWSpace\Arco Server'
export ARCRHO_GATEWAY_CONFIG="$APPDATA\\ArcRho\\arcrho_gateway.local.json"
export ARCRHO_GATEWAY_URL='http://127.0.0.1:28767'
```

The local Gateway must be running (`local_server.py start`): on the Server PC production's Gateway listens on `0.0.0.0:28767`, so with the local one stopped `127.0.0.1:28767` still answers, from production. Check `/api/capabilities` `server_id` against the local root's `config\config.json`. Related: [[local-test-root]], [[scripts-save-through-gateway-client]].
