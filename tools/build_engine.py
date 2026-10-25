#!/usr/bin/env python3
"""
Freezes the Python engine (engine/server.py + python-chess + web/) into
engine/build/dist/chess-engine/ with PyInstaller, so the app needs no Python
on the machine it runs on. Works on macOS, Windows and Linux; run it with any
Python 3.10+ from anywhere (`npm run build` in tauri/ runs it first).

  1. engine/.venv: created if missing, then requirements + PyInstaller
  2. the piece images (tools/make_pieces.py)
  3. PyInstaller --onedir
  4. a smoke test: the frozen engine starts and answers /api/status
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENG = os.path.join(ROOT, "engine")
WINDOWS = sys.platform.startswith("win")
VENV_PY = os.path.join(ENG, ".venv", "Scripts" if WINDOWS else "bin", "python.exe" if WINDOWS else "python3")


def run(*cmd: str) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ENG)


def main() -> int:
    if sys.version_info < (3, 10):
        sys.exit("Python 3.10 or newer is needed to build the engine")
    if not os.path.exists(VENV_PY):
        run(sys.executable, "-m", "venv", os.path.join(ENG, ".venv"))
    run(VENV_PY, "-m", "pip", "install", "-q", "--upgrade", "pip")
    run(VENV_PY, "-m", "pip", "install", "-q", "-r", "requirements.txt", "pyinstaller")
    run(VENV_PY, os.path.join(ROOT, "tools", "make_pieces.py"))
    shutil.rmtree(os.path.join(ENG, "build"), ignore_errors=True)
    dist = os.path.join(ENG, "build", "dist")
    run(VENV_PY, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN", "--onedir", "--name", "chess-engine",
        "--distpath", dist, "--workpath", os.path.join(ENG, "build", "work"), "--specpath", os.path.join(ENG, "build"),
        "--add-data", f"{os.path.join(ROOT, 'web')}{os.pathsep}web",          # PyInstaller wants ';' on Windows, ':' elsewhere
        "--add-data", f"{os.path.join(ENG, 'data')}{os.pathsep}data",
        "--collect-submodules", "chess", "--collect-submodules", "routes",
        os.path.join(ENG, "server.py"))
    return smoke(os.path.join(dist, "chess-engine", "chess-engine" + (".exe" if WINDOWS else "")))


def smoke(exe: str) -> int:
    """The frozen engine starts and answers, in a throwaway data folder."""
    data = tempfile.mkdtemp()
    out = open(os.path.join(data, "out.txt"), "w")
    proc = subprocess.Popen([exe, "--token", "smoke"], env={**os.environ, "CHESS_REVIEW_DATA": data}, stdout=out, stderr=out)
    ok = False
    try:
        for _ in range(120):
            info = os.path.join(data, "server.json")
            if os.path.exists(info):
                try:
                    port = json.load(open(info))["port"]
                    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/status", headers={"X-Token": "smoke"})
                    ok = "version" in json.load(urllib.request.urlopen(req, timeout=5))
                    break
                except (ValueError, OSError):
                    pass
            time.sleep(0.25)
    finally:
        proc.kill()
        proc.wait()
        out.close()
    if not ok:
        print("frozen engine smoke test failed:", open(os.path.join(data, "out.txt")).read(), file=sys.stderr)
    shutil.rmtree(data, ignore_errors=True)
    size = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(os.path.dirname(exe)) for f in fs)
    print(f"engine size: {size / 1e6:.0f} MB")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
