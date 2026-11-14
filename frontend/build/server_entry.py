"""
Entry point for PyInstaller bundled server.
This runs the FastAPI app with uvicorn directly.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Set base directory for resources
if getattr(sys, 'frozen', False):
    # Running as bundled exe
    BASE_DIR = Path(sys._MEIPASS)
    # For data files, use the exe's directory
    EXE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
    EXE_DIR = BASE_DIR

# Set environment variables before importing app
os.environ.setdefault("TRI_DATA_DIR", str(EXE_DIR))

def main():
    parser = argparse.ArgumentParser(description="ArcRho App Server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    import uvicorn

    # Change to the exe directory so static files are found
    os.chdir(str(EXE_DIR))

    uvicorn.run(
        "app_server.main:app",
        host=args.host,
        port=args.port,
        log_level="info",
    )

if __name__ == "__main__":
    main()
