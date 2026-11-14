# Agent Screen Control Indicator

Shows, unmistakably, that an agent is driving the mouse and keyboard rather than a person, and
gives the agent a pointer of its own.

Three surfaces appear while it is on:

- a soft glow along all four edges of the primary screen;
- the agent's own pointer: a grey arrow with a white rim and an amber glow, separate from the
  real pointer;
- an always-on-top panel naming the agent, its current action, and how long it has been in control.

The panel carries a **Release** button. Everything else is click-through, so the overlay can
never intercept a click meant for ResQ or ArcRho.

## Using it

```powershell
$c = 'tools\agent_screen_control\agent_screen_control.ps1'

& $c windows -Window 'ResQ'
& $c screenshot -Window 'ResQ Reserving' -Out temp\gui\resq.png -Zoom 0.5
& $c start  -Agent 'Claude Opus 5' -Action 'Opening the ResQ project list' -Position TopRight
& $c click  -X 812 -Y 440 -Window 'ResQ' -Action 'Clicking Open Project'
& $c click  -X 812 -Y 520 -Button Double -Window 'ResQ'
& $c drag   -X 300 -Y 200 -ToX 600 -ToY 200 -Window 'ResQ'
& $c move   -X 900 -Y 600
& $c action -Action 'Waiting for the project to load'
& $c status
& $c stop
```

`start` writes the state and launches a hidden helper process that draws the overlay.
`action` replaces the line on the panel and refreshes the heartbeat. `stop` takes the overlay
down. An agent should call `start` before its first injected click and `stop` in the same
block that finishes the work, so the indicator cannot outlive the control it advertises.

## Seeing the screen

`windows` and `screenshot` need no `start`; they only look.

- **`windows`** lists visible windows front to back with their position in real pixels and
  their process. `-Window <text>` filters on title or process name. A program's main window is
  often not the one Windows reports: ResQ's is `ResQ Reserving System`, while its taskbar entry
  is a zero-size window. Dialogs such as `Select a Project` are separate windows.
- **`screenshot -Out <png>`** saves the whole screen, a region (`-X -Y -Width -Height`), or one
  window (`-Window <text>`, the frontmost on-screen match). `-Zoom 0.5` halves it. It prints
  the region's origin: a point at `(px, py)` in an unzoomed image is at `(origin x + px,
  origin y + py)` on screen, and dividing by the zoom first undoes a zoom.
- **A screenshot shows what is on screen.** When another window covers the one asked for, the
  command names it; bring the right window forward first.

Keep images small: capture the region that matters rather than the whole 2048-wide screen,
and zoom in (`-Zoom 2` or `3`) on a thin target such as a divider or a tree arrow.

## The agent's pointer

The agent's pointer is drawn by the overlay and never replaces the real one.

- **`move`** glides it to a point along a gently curved path, speeding up and easing in like a
  hand reaching for something. It leans slightly with its sideways speed.
- **`click`** glides it to the target, then the real pointer jumps there for about a tenth of a
  second, clicks, and jumps back to where the person left it. `-Button Right` and
  `-Button Double` work the same way.
- **`drag`** glides to the start, then holds the real left button and moves the real pointer
  along with the drawn one to `-ToX`/`-ToY`, because a drag cannot be faked in an instant.
  The real pointer returns afterwards.
- **At rest** the arrow sways slightly about its tip and its glow breathes, so it is plain the
  agent is still working. The sway calms when the panel shows WAITING.

Each command waits until the pointer has finished and prints the window it hit. Coordinates
are **real screen pixels**, the same pixels a screenshot of the screen shows.

### Options on the pointer commands

| Option | Default | Effect |
| :--- | :--- | :--- |
| `-X`, `-Y` | required | Target, in real screen pixels |
| `-ToX`, `-ToY` | required for `drag` | Where the drag ends |
| `-Button` | `Left` | `Left`, `Right`, or `Double` (for `click`) |
| `-Window` | none | Refuse unless the window under the target has this text in its title or process name |
| `-Action` | unchanged | New line for the panel, set as the command starts |
| `-TimeoutSeconds` | 15 | Give up waiting for the overlay after this long |

Always pass `-Window` on a click that matters. If another window has come up over the target,
the command refuses with exit code 4 and names the window it found, rather than clicking it.

### Exit codes

| Code | Meaning |
| :--- | :--- |
| 0 | Done |
| 2 | Not started, or bad arguments |
| 3 | Release was requested; stop driving the screen |
| 4 | Refused or failed; the warning says why (wrong window, under the panel, timeout) |

## Options on `start`

| Option | Default | Effect |
| :--- | :--- | :--- |
| `-Agent` | `Agent` | Name shown on the panel |
| `-Position` | `TopCenter` | `TopCenter`, `TopRight`, `BottomCenter`, `BottomRight` |
| `-Color` | `#FF9A1F` | Accent for the edge glow, the pointer's glow, and the panel border |
| `-Thickness` | scaled 28px | Edge glow thickness in pixels |
| `-NoCursor` / `-NoEdges` | off | Hide the agent's pointer or the edge glow |
| `-IdleExitMinutes` | 20 | Overlay gives up if no heartbeat arrives for this long |

To see the pointer without clicking anything, run `& $c demo`. It glides around the screen,
taps a few spots, rests between moves, and turns the overlay off at the end.

## Release: how a person takes back control

Clicking **Release** turns every surface red and sets a flag in the state file. From then on
`click`, `drag`, `move`, `action`, and `status` exit with code **3**, and a click already on
its way is dropped before the real pointer moves. A drag in progress lets go of the button.

```powershell
& $c click -X 812 -Y 440 -Window 'ResQ'
if ($LASTEXITCODE -eq 3) { throw 'The user asked for the screen back.' }
```

The button cannot seize the mouse from the agent; nothing in Windows can do that from another
process. It is a signal the agent must obey, so an agent must check the exit code after every
step rather than only at the end.

## What the display tells you

- **Amber edges and a grey arrow with an amber glow** — an agent holds the mouse and keyboard.
- **The arrow swaying gently** — the agent is working but not moving the pointer right now.
- **WAITING on the panel** — no heartbeat for 25 seconds. The agent is thinking or waiting on
  something slow. This is normal between steps.
- **Everything red** — a release has been requested and not yet acknowledged.
- **Nothing on screen** — no agent is driving.

## Limits worth knowing

- **Hands off during a drag.** A click borrows the real pointer for about a tenth of a second,
  so moving your own mouse at the same time rarely matters. A drag holds the real button for
  its whole glide; moving your mouse then will fight it.
- **Keep the Remote Desktop window open.** A minimised Remote Desktop window stops the remote
  screen drawing, and clicks and screenshots then fail. Covering the window is fine.
- **Primary screen only.** The glow frames the primary monitor.
- **The overlay is in screenshots.** An agent that takes screenshots to decide what to click
  will see its own glow, arrow, and panel. The panel covers a band near one corner; move it
  with `-Position` when it sits on something the agent needs to read. A click aimed at the
  panel is refused.
- **Elevated windows.** Windows does not let this tool click into an app running as
  administrator; the click is silently dropped.
- **Z-order is reclaimed once a second.** Some applications, ResQ among them, push themselves
  above other always-on-top windows; the overlay takes the top back rather than fighting per
  frame, so it can be covered for up to a second.

## How it is put together

- `agent_screen_control.ps1` — the only entry point: the `windows` / `screenshot` / `start` /
  `action` / `move` / `click` / `drag` / `stop` / `status` / `demo` commands, and the hidden
  `overlay` mode that the others launch.
- `AgentScreenControl.cs` — the overlay itself, compiled at run time by `Add-Type`. It must
  stay C# 5 and ASCII, because `Add-Type` reads it with the console's default encoding. It
  also performs the real clicks, so it knows exactly when the drawn pointer has arrived.
- State lives in `%APPDATA%\Arco\agent_screen_control\state.json`. Each pointer command
  carries a sequence number, and the overlay answers in `cursor_ack.json` beside it. The
  helper's process id is kept there too. All of it is transient runtime state, not ArcRho
  project data.
- `overlay.log` beside them has one line per pointer command, with the time each step
  began. Read it when a command times out: a timeout does not mean the click failed, only that
  it was not confirmed in time. `start` clears the log, so it only ever covers one session.
- The overlay works in real screen pixels (per-monitor DPI awareness). The older
  system-awareness mode goes wrong after a Remote Desktop reconnect at a different scale:
  Windows then stretches the process, and its coordinates drift 25% away from a screenshot's.

If `start` reports that the overlay exited immediately, run it in the foreground to see the
compiler error:

```powershell
powershell -NoProfile -STA -File tools\agent_screen_control\agent_screen_control.ps1 overlay
```
