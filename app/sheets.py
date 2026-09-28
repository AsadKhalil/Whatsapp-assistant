"""Google Sheets through a service account: each client shares their Sheet with its email."""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

import gspread

CACHE_TTL = 300  # seconds; knowledge text and column names are re-read at most this often


class Sheets:
    def __init__(self, gc: Any) -> None:
        self._gc = gc
        self._tabs: dict[tuple[str, str], Any] = {}
        self._cache: dict[tuple, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_service_account(cls, path: str) -> "Sheets":
        return cls(gspread.service_account(filename=path))

    def _tab(self, sheet_id: str, tab: str) -> Any:
        with self._lock:
            key = (sheet_id, tab)
            if key not in self._tabs:
                self._tabs[key] = self._gc.open_by_key(sheet_id).worksheet(tab)
            return self._tabs[key]

    def _cached(self, key: tuple, load: Callable[[], Any], now: float | None) -> Any:
        now = time.time() if now is None else now
        hit = self._cache.get(key)
        if hit and now - hit[0] < CACHE_TTL:
            return hit[1]
        value = load()
        self._cache[key] = (now, value)
        return value

    def rows(self, sheet_id: str, tab: str) -> list[dict]:
        return self._tab(sheet_id, tab).get_all_records()

    def headers(self, sheet_id: str, tab: str, now: float | None = None) -> list[str]:
        return self._cached(("headers", sheet_id, tab),
                            lambda: [h.strip() for h in self._tab(sheet_id, tab).row_values(1)], now)

    def append(self, sheet_id: str, tab: str, row: dict[str, str]) -> None:
        ws = self._tab(sheet_id, tab)
        headers = [h.strip() for h in ws.row_values(1)]
        # RAW stores text as typed, so "=IMPORTXML(...)" sent in a chat never runs as a formula.
        ws.append_row([row.get(h, "") for h in headers], value_input_option="RAW")
        self._cache.pop(("headers", sheet_id, tab), None)  # a renamed column converges on the next read

    def knowledge(self, sheet_id: str, tab: str, now: float | None = None) -> str:
        def load() -> str:
            lines = (" | ".join(f"{k}: {v}" for k, v in r.items() if str(v).strip())
                     for r in self.rows(sheet_id, tab))
            return "\n".join(line for line in lines if line)

        return self._cached(("knowledge", sheet_id, tab), load, now)
