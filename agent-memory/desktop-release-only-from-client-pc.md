---
name: desktop-release-only-from-client-pc
description: the desktop app release is built and published only on the Client PC; never offer or start it from the Server PC
metadata:
  node_type: memory
  type: feedback
  originSessionId: e5c82069-8544-44ee-aebf-2c2de9a79a83
  modified: 2026-11-10T03:15:44.623Z
---

Build and publish the Arco desktop release only on the Client PC (L-H2MQ6280FVP). The Server PC (NE7SASWPN02) has no permission to do it.

**Why:** user correction on 2026-11-09 during the [[arco-server-root-move]], after I offered to start the release build from a Server PC session.

**How to apply:** run `hostname` first (see [[dev-pc-and-client-pc-identity]]). On the Server PC, list the release as a step for the user and do not offer to run it. Server component deploys and the Excel add-in release are fine from the Server PC.
