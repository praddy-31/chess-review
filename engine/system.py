"""
Everything that differs between macOS, Windows and Linux, in one place.

  data_dir()       where chess.sqlite lives (the native shell's main.rs uses the
                   same folders: keep them in step)
                     macOS    ~/Library/Application Support/Chess Review
                     Windows  %APPDATA%\\Chess Review
                     Linux    $XDG_DATA_HOME/chess-review (~/.local/share/chess-review)
  downloads_dir()  where exports are saved
  engine_dirs()    folders searched for stockfish / lc0 beyond the PATH (apps
                   started from Finder or a desktop menu get a short PATH)
  reveal(folder)   shows a folder in Finder / Explorer / the file manager
  open_url(url)    opens a link in the default browser
  low_priority()   how to start an engine so the computer stays responsive
  setup()          the install commands the Setup page shows on this system

The release is a macOS app; Windows and Linux are build-from-source and
community-supported (README).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser

MAC, WINDOWS = sys.platform == "darwin", sys.platform.startswith("win")
LINUX = not (MAC or WINDOWS)
NAME = "mac" if MAC else "windows" if WINDOWS else "linux"
EXE = ".exe" if WINDOWS else ""


def data_dir() -> str:
    if MAC:
        return os.path.expanduser("~/Library/Application Support/Chess Review")
    if WINDOWS:
        return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming"), "Chess Review")
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "chess-review")


def downloads_dir() -> str:
    if LINUX:
        try:   # the desktop's own name for it (localised on some systems)
            out = subprocess.run(["xdg-user-dir", "DOWNLOAD"], capture_output=True, text=True, timeout=3).stdout.strip()
            if out and out != os.path.expanduser("~") and os.path.isdir(out):
                return out
        except (OSError, subprocess.SubprocessError):
            pass
    return os.path.join(os.path.expanduser("~"), "Downloads")


def engine_dirs() -> list[str]:
    if "CHESS_REVIEW_ENGINE_DIRS" in os.environ:   # override (the UI test's clean computer sets it empty)
        return [d for d in os.environ["CHESS_REVIEW_ENGINE_DIRS"].split(os.pathsep) if d]
    if MAC:
        return ["/opt/homebrew/bin", "/usr/local/bin"]
    if WINDOWS:   # winget's command links
        local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        return [os.path.join(local, "Microsoft", "WinGet", "Links")]
    return ["/usr/games", "/usr/local/bin", "/snap/bin", os.path.expanduser("~/.local/bin")]


def reveal(folder: str) -> bool:
    """Shows a folder in the system's file manager."""
    cmd = ["open", folder] if MAC else ["explorer", folder] if WINDOWS else ["xdg-open", folder]
    try:
        subprocess.Popen(cmd)
        return True
    except OSError:
        return False


def open_url(url: str) -> None:
    if MAC:
        subprocess.Popen(["open", url])
    else:
        webbrowser.open(url)


def low_priority(cmd: str) -> "str | list[str]":
    """An engine command at low priority (nice 10) where that exists."""
    nice = None if WINDOWS else shutil.which("nice") or ("/usr/bin/nice" if os.path.exists("/usr/bin/nice") else None)
    return [nice, "-n", "10", cmd] if nice else cmd


def file_manager() -> str:
    return "Finder" if MAC else "Explorer" if WINDOWS else "the file manager"


MAIA_BANDS = [1100, 1200, 1300, 1400, 1500, 1600, 1700, 1800, 1900]   # the nets the Maia project publishes


def setup(data: str, maia_bands: "list[int] | None" = None) -> dict:
    """What the Setup page shows: the shell to paste into and one command per part.
    maia_bands: the nets to download (default all; Setup passes the missing ones)."""
    weights = " ".join(str(b) for b in (maia_bands or MAIA_BANDS))
    maia_url = "https://github.com/CSSLab/maia-chess/raw/master/maia_weights/maia-{r}.pb.gz"
    book_url = "https://github.com/niklasf/python-chess/raw/master/data/polyglot/performance.bin"
    if WINDOWS:
        d = data.replace(os.path.expanduser("~"), "$HOME")
        return {
            "os": NAME, "shell": "PowerShell",
            "stockfish": "winget install --id Stockfish.Stockfish -e",
            "stockfish_note": f"Or download it from stockfishchess.org, unzip it into \"{d}\\engines\" and press Check again.",
            "lc0": None,
            "lc0_note": f"Download lc0 from github.com/LeelaChessZero/lc0/releases and unzip it into \"{d}\\engines\".",
            "maia": f'$d = "{d}\\maia"; mkdir -Force $d | Out-Null; foreach ($r in {weights.replace(" ", ",")}) '
                    f'{{ iwr "{maia_url.format(r="$r")}" -OutFile "$d\\maia-$r.pb.gz" }}',
            "book": f'$d = "{d}\\book"; mkdir -Force $d | Out-Null; iwr "{book_url}" -OutFile "$d\\performance.bin"',
        }
    q = '"' + data.replace(os.path.expanduser("~"), "$HOME")
    maia = (f'mkdir -p {q}/maia" && cd {q}/maia" && for r in {weights}; do '
            f'curl -fLO {maia_url.format(r="$r")}; done')
    book = f'mkdir -p {q}/book" && curl -fL -o {q}/book/performance.bin" {book_url}'
    if MAC:
        return {"os": NAME, "shell": "Terminal", "stockfish": "brew install stockfish", "stockfish_note": "No Homebrew? Get it at brew.sh first.",
                "lc0": "brew install lc0", "lc0_note": "", "maia": maia, "book": book}
    return {"os": NAME, "shell": "a terminal",
            "stockfish": "sudo apt install stockfish",
            "stockfish_note": "That's Debian and Ubuntu; elsewhere: sudo dnf install stockfish (Fedora) or sudo pacman -S stockfish (Arch).",
            "lc0": None,
            "lc0_note": f"lc0 isn't packaged by most distributions: build it from github.com/LeelaChessZero/lc0, or put the binary in {q}/engines\".",
            "maia": maia, "book": book}


def install_hint(name: str = "stockfish") -> str:
    """One line for an error message: how to get the engine here."""
    s = setup(data_dir())
    return f"{name.capitalize()} not found. " + (f"Install it with: {s[name]}" if s.get(name) else s.get(f"{name}_note", ""))
