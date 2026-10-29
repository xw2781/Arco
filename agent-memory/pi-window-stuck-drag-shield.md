---
name: pi-window-stuck-drag-shield
description: An agent click that lands on a Project Instance window's resize edge can leave a drag shield over the whole page; reopen the project tab to clear it
metadata:
  type: reference
---

On 2026-10-29, while GUI-testing a dataset window with `tools/arco_window_control`, a click meant for the window content landed on `div.pi-window-resize` because the window had just reopened at a different spot. Every later click and drag hit `div.pi-window-drag-shield` instead: the resize gesture captured the pointer and never got its pointer-up, so the shield from `beginWindowDragCapture` in `ui/project_instance/project_instance_windows.js` stayed in place. A click on the title bar or a short `drag` did not release it.

**Why:** the shield is removed only when the captured pointer ends, and the agent's input does not end it once it is stuck.

**How to apply:** take a fresh screenshot after a window opens before clicking inside it (see [[desktop-input-control-works]]). If the hit report says `pi-window-drag-shield`, close the project tab and reopen the project from Project Explorer. That reloads the page without saving anything.
