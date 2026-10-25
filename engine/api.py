"""
What the route modules (routes/) share: the route table, the error that becomes
an HTTP status, and the engine process's long-lived workers.
"""

from __future__ import annotations

import re

import sync

VERSION = "3.0.0"   # keep in step with tauri.conf.json, Cargo.toml and package.json (the self-test checks)

ROUTES: list[tuple[str, re.Pattern, callable]] = []


def route(method: str, pattern: str):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn))
        return fn
    return deco


class ApiError(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status


ANALYSER = None  # engines.Analyser, set in server.main()


def need_stockfish() -> None:
    """Refuses at once, with this system's install command, instead of queueing games that would all fail."""
    import engines
    import store
    import system
    if not engines._which("stockfish", store.get_settings().get("stockfish_path", "")):
        raise ApiError(400, system.install_hint("stockfish") + " Setup has the steps.")
SYNCER = sync.Syncer()
