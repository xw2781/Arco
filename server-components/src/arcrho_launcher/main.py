from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Optional
import subprocess

_MODULE_ROOT = Path(__file__).resolve().parent
_SOURCE_ROOT = _MODULE_ROOT.parent
_PRODUCT_ROOT = _SOURCE_ROOT.parent
_BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", _MODULE_ROOT)).resolve()

for _path in (_PRODUCT_ROOT, _SOURCE_ROOT, _BUNDLE_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

try:
    from src.utils import component_app_name, get_project_root, resolve_app_exe
except ModuleNotFoundError:
    from utils import component_app_name, get_project_root, resolve_app_exe


os.environ.setdefault("ARCRHO_ROOT", str(get_project_root()))


def remove_startup_shortcut(shortcut_name: str) -> Optional[Path]:
    """
    Delete a shortcut from the current user's Startup folder if it exists.

    Args:
      shortcut_name: Shortcut file name, with or without the .lnk suffix.

    Returns:
      Path to the deleted shortcut, or None if no shortcut was present.
    """
    name = shortcut_name.strip()
    if not name:
        raise ValueError("shortcut_name is empty")
    if not name.lower().endswith(".lnk"):
        name = f"{name}.lnk"

    startup_dir = Path(os.environ["APPDATA"]) / r"Microsoft\Windows\Start Menu\Programs\Startup"
    lnk_path = startup_dir / name
    if not lnk_path.exists():
        return None

    lnk_path.unlink()
    return lnk_path


def install_startup_shortcut(
    exe_path: str | os.PathLike,
    shortcut_name: Optional[str] = None,
    args: str = "",
    work_dir: Optional[str | os.PathLike] = None,
    icon_path: Optional[str | os.PathLike] = None,
    description: str = "",
) -> Path:
    """
    Create (or overwrite) a .lnk shortcut in the current user's Startup folder.

    Requirements:
      pip install pywin32

    Args:
      exe_path: Full path to the .exe.
      shortcut_name: Shortcut file name (without .lnk). Defaults to exe file stem.
      args: Command-line arguments for the target.
      work_dir: Working directory. Defaults to exe folder.
      icon_path: Path to .ico or .exe to use as icon. Defaults to exe_path.
      description: Shortcut description.

    Returns:
      Path to the created shortcut (.lnk).
    """
    exe = Path(exe_path).expanduser().resolve()
    if not exe.exists():
        raise FileNotFoundError(f"EXE not found: {exe}")
    if exe.suffix.lower() != ".exe":
        raise ValueError(f"Target must be an .exe: {exe}")

    name = (shortcut_name or exe.stem).strip()
    if not name:
        raise ValueError("shortcut_name is empty")

    startup_dir = Path(os.environ["APPDATA"]) / r"Microsoft\Windows\Start Menu\Programs\Startup"
    startup_dir.mkdir(parents=True, exist_ok=True)
    lnk_path = startup_dir / f"{name}.lnk"

    wd = Path(work_dir).expanduser().resolve() if work_dir else exe.parent
    ico = Path(icon_path).expanduser().resolve() if icon_path else exe

    # Create shortcut via WScript.Shell
    try:
        import win32com.client  # type: ignore
    except ImportError as e:
        raise ImportError("pywin32 is required: pip install pywin32") from e

    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortcut(str(lnk_path))
    shortcut.TargetPath = str(exe)
    shortcut.Arguments = args or ""
    shortcut.WorkingDirectory = str(wd)
    shortcut.Description = description or ""
    shortcut.IconLocation = str(ico)  # can be exe or ico
    shortcut.Save()

    return lnk_path


def start_app_exe(exe_path: str | os.PathLike) -> None:
    """Start an app with its own folder as working directory.

    A child that inherits this launcher's working directory keeps the launcher
    folder locked for as long as it runs, which blocks redeploying the
    launcher. Each app pins only its own folder, and every deploy script
    already stops its own app before swapping that folder.
    """

    exe = Path(exe_path)
    subprocess.Popen([str(exe)], cwd=str(exe.parent), close_fds=True)


def main():
    # The Launcher was "ADAS Shell", then "ArcRho Launcher" until 2026-11-09.
    for old_name in ("ADAS Shell", "ArcRho Launcher"):
        removed_lnk = remove_startup_shortcut(old_name)
        if removed_lnk:
            print("\n> Removed old startup shortcut:", removed_lnk); time.sleep(0.5)

    lnk = install_startup_shortcut(
        resolve_app_exe("launcher"),
        shortcut_name=component_app_name("launcher"),
        args="--silent",
        description=f"Launch {component_app_name('launcher')} at login",
    )

    print("\n> Shortcut created:", lnk); time.sleep(0.5)

    print('\n> Start Applications ...')

    start_app_exe(resolve_app_exe("orchestrator"))
    start_app_exe(resolve_app_exe("bridge"))

    print('\n> Done'); time.sleep(2)


if __name__ == "__main__":
    main()
    sys.exit(0)
