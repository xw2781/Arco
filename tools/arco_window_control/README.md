# Arco Window Control

Lets an agent look at and drive one Arco window, and nothing outside it, while the person at
the desk watches and can take over at any moment.

It is the Arco-only counterpart of [`agent_screen_control`](../agent_screen_control/README.md).
Use this tool for anything inside Arco; use the desktop tool only for other applications
(ResQ, Excel) and for Windows dialogs such as file pickers, which are not part of Arco's page.

## How it differs from the desktop tool

- **Nothing outside Arco can be clicked.** Input goes straight into Arco's page, not to Windows,
  so a wrong coordinate can at worst land on the wrong part of Arco.
- **The real pointer never moves.** The person can keep working in other applications, and the
  agent can work while Arco sits behind other windows.
- **Coordinates are window pixels**, measured from the top-left of Arco's window content. An
  unzoomed screenshot uses the same pixels, so there is no screen-position or display-scaling
  arithmetic.
- **Pausing is exact.** Arco can tell the agent's input from the person's, so any click, key
  press, or wheel turn the person makes in Arco pauses the agent, and their click still does
  what they meant.

## Using it

```powershell
$c = 'tools\arco_window_control\arco_window_control.ps1'

& $c windows
& $c start  -Agent 'Claude Opus 5.5' -Action 'Opening Project Explorer'
& $c screenshot -Out temp\gui\arco.png -Zoom 0.5
& $c click  -X 548 -Y 278 -Action 'Opening Project Explorer'
& $c click  -X 548 -Y 278 -Button Double
& $c drag   -X 300 -Y 200 -ToX 600 -ToY 200
& $c scroll -X 400 -Y 500 -Delta 300
& $c type   -Text 'NJ Annual'
& $c key    -Key 'Ctrl+S'
& $c move   -X 900 -Y 600
& $c action -Action 'Waiting for the table to load'
& $c status
& $c stop
```

`windows` and `screenshot` need no `start`; they only look. Every other command needs a
session. Call `start` before the first input and `stop` in the same block that finishes the
work.

Each pointer command glides the agent's pointer to the target and prints the element it
landed on, looking into the frames that hold each workspace page:

```
Left click at (75, 637).
Hit: div.tree-folder-name "2026 Q2" (inside iframe)
```

## Seeing the window

- **`windows`** lists Arco's windows with their ids, roles (`main`, `arcode`), and sizes.
- **`screenshot -Out <png>`** saves the window, or a region with `-X -Y -Width -Height`.
  `-Zoom 0.5` halves it and `-Zoom 2` enlarges a thin target. The command prints the origin: a
  point `(px, py)` in the image is the window point `(origin x + px / zoom, origin y + py / zoom)`.
- **The overlay is left out** of screenshots so it never hides what the agent needs to read.
  `-ShowOverlay` keeps it, to check what the person sees.
- A minimised Arco is restored before a screenshot or `start`, because a minimised window
  paints nothing.

## Commands and options

| Command | Options |
| :--- | :--- |
| `start` | `-Agent`, `-Action`, `-Position` (`TopCenter`, `TopRight`, `BottomCenter`, `BottomRight`), `-Window` (`main`, `arcode`, an id, or title text), `-NoPointer`, `-IdleExitMinutes` (default 20) |
| `click` | `-X -Y`, `-Button` (`Left`, `Right`, `Double`), `-Action` |
| `drag` | `-X -Y -ToX -ToY`, `-Action` |
| `scroll` | `-X -Y -Delta` (positive scrolls down), `-Action` |
| `move` | `-X -Y`, `-Action` |
| `type` | `-Text` (a new line presses Enter), `-Action` |
| `key` | `-Key` such as `Enter`, `Escape`, `Tab`, `Ctrl+S`, `Shift+Tab`, `F2`, `Up`, `-Action` |
| `action` | `-Action`, the new line for the banner |
| `screenshot` | `-Out`, `-Window`, `-X -Y -Width -Height`, `-Zoom`, `-ShowOverlay` |
| `windows`, `status`, `stop`, `demo` | none |

Every command also takes `-AppPid` to pick one of several running Arco apps (the newest is used
otherwise), `-App Arcode` to drive Arcode, and `-TimeoutSeconds` (default 30).

A click refuses a point outside the window or under the agent's banner; move the banner with
`start -Position` when it covers the target.

### Exit codes

| Code | Meaning |
| :--- | :--- |
| 0 | Done |
| 2 | Not started, Arco is not running, or bad arguments |
| 3 | The person paused or ended the agent's control; stop driving Arco |
| 4 | Refused or failed; the warning says why |

```powershell
& $c click -X 548 -Y 278
if ($LASTEXITCODE -eq 3) { throw 'The user took control of Arco.' }
```

Check the exit code after every step, not only at the end.

## How the person takes over

| The person | What happens |
| :--- | :--- |
| Clicks, types, or scrolls anywhere in the Arco window | Their input works as normal and the agent pauses |
| Moves the mouse over Arco while the agent is dragging | The drag is let go and the agent pauses |
| Presses **Ctrl+Alt+Esc**, wherever the focus is | The agent pauses |
| Presses **Pause** on the banner | The agent pauses |
| Presses **Resume** on the banner | The agent may continue |
| Presses **End** on the banner | The overlay goes; the agent's commands are refused until it runs `stop` |

A pause takes effect at once: a glide stops where it is, a drag lets go of the button, and
typing stops after the current character. The agent's next command exits with code 3 and says
why. Only the person can resume; an agent cannot resume itself.

## What the window shows

- **Amber edges, a grey arrow with an amber glow, and a banner** naming the agent, its current
  step, and how long it has had control: an agent is driving.
- **The arrow swaying gently**: the agent is working but not moving the pointer.
- **Waiting on the banner**: no command for 25 seconds; the agent is thinking or waiting.
- **Everything red with Paused**: the person paused the agent.
- **Nothing**: no agent is driving. A session ends by itself after 20 minutes without a command,
  so the overlay cannot outlive the agent.

## How it works

The Arco desktop app runs a small endpoint on `127.0.0.1` and publishes its port and a token,
new at every launch, in `%APPDATA%\Arco\agent_window_control.json`. This script reads that
file and posts one command at a time. The app sends the input with Electron's
`webContents.sendInputEvent`, which goes through Chromium's real hit-testing: a click on a
control hidden behind another one fails the way the person's would. The overlay runs in an
isolated world of the window's page, so Arco's own scripts cannot see or change it. The source
is under [`frontend/electron/agent_control/`](../../frontend/electron/agent_control/).

## Limits worth knowing

- **Arco must be a version with this feature.** Changes to the agent control host take effect
  only when Arco restarts; reloading the page is not enough.
- **Native dialogs are out of reach.** Windows file pickers and system message boxes are not part
  of Arco's page. Arco's own in-page dialogs, such as Quit, work normally.
- **The stop key is taken for the whole session.** While an agent is in control, Ctrl+Alt+Esc
  belongs to Arco in every application. In a windowed Remote Desktop session, Windows key
  combinations may stay on the local computer; the banner and a click in Arco always work.
- **Hover follows the agent.** The page sees the agent's pointer move, so hover effects appear
  under it. The person's own pointer over Arco moves the hover back.
