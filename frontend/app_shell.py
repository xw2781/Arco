from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from app_server.app_control_flags import restart_flag, shutdown_flag

BASE_DIR = Path(__file__).resolve().parent


def build_cmd(host: str, port: int, reload: bool, app_mode: str = "arcrho") -> list[str]:
    app_target = "app_server.arcode_main:app" if app_mode == "arcode" else "app_server.main:app"
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        app_target,
        "--host",
        host,
        "--port",
        str(port),
    ]
    if reload:
        cmd.append("--reload")
    return cmd


def terminate_process_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def ensure_env_defaults(env: dict[str, str]) -> dict[str, str]:
    env = dict(env)
    env.setdefault("TRI_DATA_DIR", str(BASE_DIR))
    if env.get("ARCRHO_APP_MODE", "").strip().lower() == "arcode":
        env.setdefault("ARCODE_DATA_DIR", str(Path.home() / "Documents" / "Arcode" / "scripts"))
    return env


def run_supervisor(host: str, port: int, reload: bool) -> None:
  env = ensure_env_defaults(os.environ)
  app_mode = "arcode" if env.get("ARCRHO_APP_MODE", "").strip().lower() == "arcode" else "arcrho"
  cmd = build_cmd(host, port, reload, app_mode)
  RESTART_FLAG = restart_flag(BASE_DIR, port)
  SHUTDOWN_FLAG = shutdown_flag(BASE_DIR, port)
  console_mode = env.get("ARCRHO_BACKEND_CONSOLE", "").strip().lower()
  if os.name == "nt":
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    if console_mode not in {"same", "hidden"}:
      creationflags |= subprocess.CREATE_NEW_CONSOLE
  else:
    creationflags = 0

  while True:
    if SHUTDOWN_FLAG.exists():
      try:
        SHUTDOWN_FLAG.unlink()
      except Exception:
        pass
      break
    if RESTART_FLAG.exists():
      try:
        RESTART_FLAG.unlink()
      except Exception:
        pass

    proc = subprocess.Popen(
      cmd,
      cwd=str(BASE_DIR),
      env=env,
      creationflags=creationflags,
    )

    while True:
      if proc.poll() is not None:
        code = proc.returncode
        print(f"uvicorn exited with code {code}")
        break
      if SHUTDOWN_FLAG.exists():
        try:
          SHUTDOWN_FLAG.unlink()
        except Exception:
          pass
        terminate_process_tree(proc)
        return
      if RESTART_FLAG.exists():
        try:
          RESTART_FLAG.unlink()
        except Exception:
          pass
        terminate_process_tree(proc)
        break
      time.sleep(0.4)

    time.sleep(0.5)


def main() -> None:
    parser = argparse.ArgumentParser(description="ArcRho app supervisor")
    default_port = 28766 if os.environ.get("ARCRHO_APP_MODE", "").strip().lower() == "arcode" else 28765
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=default_port)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    run_supervisor(args.host, args.port, args.reload)


if __name__ == "__main__":
    main()
