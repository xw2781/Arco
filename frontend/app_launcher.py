from __future__ import annotations

import os
import subprocess
import sys
import time
import ctypes
from pathlib import Path


def start_app(
    project_dir: str | Path = Path(__file__).resolve().parent,
    host: str = "127.0.0.1",
    port: int = 28765,
    reload: bool = True,
) -> None:
    """
    Launch the ArcRho FastAPI app and optionally open the UI in the default browser.
    """
    
    project_dir = Path(project_dir)

    candidates = [
        project_dir,
        Path(os.getcwd()),
        Path(os.getcwd()).parent,
    ]
    project_dir = next((p for p in candidates if (p / "app_shell.py").exists()), project_dir)

    app_shell = project_dir / "app_shell.py"
    if not app_shell.exists():
        raise FileNotFoundError(f"app_shell.py not found in: {project_dir}")

    url = f"http://{host}:{port}/"

    cmd = [sys.executable, str(app_shell), "--host", host, "--port", str(port)]
    if reload:
        cmd.append("--reload")

    env = os.environ.copy()
    env.setdefault("TRI_DATA_DIR", str(project_dir))

    print("Working dir:", project_dir)
    print("Command:", " ".join(cmd))
    print("UI URL:", url)

    subprocess.Popen(
        cmd,
        cwd=str(project_dir),
        env=env,
    )

    # Give uvicorn a moment to bind the port, then open browser
    # if open_browser:
    #     time.sleep(1.5)
    #     webbrowser.open(url)


def start_browser(
    host: str = "127.0.0.1",
    port: int = 28765,
) -> None:
    """
    Launch Chrome in app mode (no tabs/address bar), windowed,
    sized to ~2/3 of the primary screen.
    """
    url = f"http://{host}:{port}/"

    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    chrome = next((p for p in chrome_paths if Path(p).exists()), None)
    if chrome is None:
        raise FileNotFoundError("Chrome not found on this system")

    # Get screen resolution (Windows)
    user32 = ctypes.windll.user32
    screen_w = user32.GetSystemMetrics(0)
    screen_h = user32.GetSystemMetrics(1)

    win_w = int(screen_w * 2 / 3)
    win_h = int(screen_h * 2 / 3)

    # Center the window
    pos_x = (screen_w - win_w) // 2
    pos_y = (screen_h - win_h) // 2

    # Resolve writable profile dir
    localappdata = os.environ.get("LOCALAPPDATA") or str(
        Path.home() / "AppData" / "Local"
    )
    user_data_dir = Path(localappdata) / "Arco_AppMode_Profile"
    user_data_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        chrome,
        f"--app={url}",
        f"--user-data-dir={str(user_data_dir)}",
        f"--window-size={win_w},{win_h}",
        f"--window-position={pos_x},{pos_y}",
    ]

    subprocess.Popen(cmd)



if __name__ == "__main__":
    start_app()
    time.sleep(1)
    start_browser()
