---
name: dev-pc-and-client-pc-identity
description: Sessions run on either L-H2MQ6280FVP (Client PC) or NE7SASWPN02 (Server PC, formerly Dev PC, hosts E:\ArcRho Server and ResQ) - run hostname to tell which, never assume
metadata:
  node_type: memory
  type: project
  originSessionId: 05c09575-2234-4404-bf4e-fcede99def6e
  modified: 2026-08-29T02:22:20.373Z
---

Two machines matter for ArcRho work, and which one the session is on changes what is reachable.

**Run `hostname` before claiming anything that depends on which machine this is.** Sessions happen
on both, so neither box is "the current machine". A session in `E:\XWSpace\Repos\Arco` is usually
on the Server PC; one in `c:\Users\xwei\Repos\Arco` is on the Client PC. Both profiles are named
`xwei`, so the user name settles nothing.

`AGENT_GUIDELINES.md` renamed the shared machine from **Dev PC** to **Server PC** on 2026-08-21,
since development now happens on the client machine. Older memories and commit messages still
say "Dev PC" and mean the same box.

**Client PC — `L-H2MQ6280FVP`** (HP EliteBook, `PRCINS.NET`, user `xwei`). Since 2026-08-13
this holds the main local repo at `c:\Users\xwei\Repos\Arco`. It is a **Client PC** as
`AGENT_GUIDELINES.md` defines the term: it reaches the ArcRho Server workspace over the network rather
than locally. It was chosen deliberately to reproduce network-latency issues that do not appear
on the Server PC. `gh` is installed and authenticated here as `xw2781`, so releases can be
published from this machine.

**Server PC — `NE7SASWPN02`** (Windows Server 2019, user profile `xwei.PRCINS`). Hosts
`E:\ArcRho Server`, `E:\XWSpace`, and the source repo at `E:\XWSpace\Repos\Arco`. ResQ is
installed and its COM class is registered here, so ResQ/COM work (see [[resq-com-probe]] and
[[resq-percentage-developed-enum]]) can run in this session when the hostname says this is the box.
Confirmed 2026-08-28 by `hostname` plus a `HKCR\ResQ3Automation.ResQApplication` registry read.

On the Client PC, `E:` and `F:` are **mapped network drives onto the Server PC** (`\\NE7SASWPN02\E`,
`\\NE7SASWPN02\F`). So every `E:\...` path in the repo instructions and in older memories —
`E:\ArcRho Server\shared\macros`, `E:\ArcRho Server\config\config.json`,
`E:\XWSpace\Build ArcRho App` — resolves here over SMB and depends on the Server PC being up. That
network hop is the point when reproducing latency bugs, and it is also why a memory written on
the Server PC that says "local disk" may mean "network drive" here.

Building and releasing without the Server PC is covered by [[arcrho-local-release-build]].
