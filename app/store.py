"""SQLite storage: messages (deduplicated per client and channel) and Sheet writes waiting for YES."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY,
  client_id TEXT NOT NULL,
  channel TEXT NOT NULL,
  msg_id TEXT NOT NULL,
  chat_id TEXT NOT NULL,
  sender_id TEXT NOT NULL,
  sender_name TEXT NOT NULL DEFAULT '',
  text TEXT NOT NULL DEFAULT '',
  from_bot INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  UNIQUE (client_id, channel, msg_id)
);
CREATE INDEX IF NOT EXISTS messages_by_chat ON messages (client_id, chat_id, created_at);
CREATE TABLE IF NOT EXISTS pending_writes (
  client_id TEXT NOT NULL,
  chat_id TEXT NOT NULL,
  sender_id TEXT NOT NULL,
  tab TEXT NOT NULL,
  row_json TEXT NOT NULL,
  expires_at REAL NOT NULL,
  PRIMARY KEY (client_id, chat_id, sender_id)
);
"""


class Store:
    # ponytail: one connection behind one lock; fine for a pilot, Postgres arrives with the dashboard.
    def __init__(self, path: str) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA busy_timeout=5000")
            self._db.executescript(SCHEMA)

    def _all(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def _write(self, sql: str, args: tuple = ()) -> int:
        with self._lock:
            return self._db.execute(sql, args).rowcount

    def save_message(self, client_id: str, channel: str, msg_id: str, chat_id: str, sender_id: str,
                     sender_name: str, text: str, from_bot: bool, now: float) -> bool:
        return self._write(
            "INSERT OR IGNORE INTO messages (client_id, channel, msg_id, chat_id, sender_id, sender_name,"
            " text, from_bot, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (client_id, channel, msg_id, chat_id, sender_id, sender_name, text, int(from_bot), now),
        ) == 1

    def set_text(self, client_id: str, channel: str, msg_id: str, text: str) -> None:
        self._write("UPDATE messages SET text = ? WHERE client_id = ? AND channel = ? AND msg_id = ?",
                    (text, client_id, channel, msg_id))

    def history(self, client_id: str, chat_id: str, limit: int) -> list[sqlite3.Row]:
        rows = self._all(
            "SELECT sender_name, text, from_bot FROM messages WHERE client_id = ? AND chat_id = ?"
            " ORDER BY created_at DESC, id DESC LIMIT ?",
            (client_id, chat_id, limit),
        )
        return rows[::-1]

    def is_bot_message(self, client_id: str, channel: str, msg_id: str) -> bool:
        return bool(self._all(
            "SELECT 1 FROM messages WHERE client_id = ? AND channel = ? AND msg_id = ? AND from_bot = 1",
            (client_id, channel, msg_id)))

    def bot_has_spoken(self, client_id: str, chat_id: str) -> bool:
        return bool(self._all(
            "SELECT 1 FROM messages WHERE client_id = ? AND chat_id = ? AND from_bot = 1 LIMIT 1",
            (client_id, chat_id)))

    def bot_replies_since(self, client_id: str, chat_id: str, since: float) -> int:
        return self._all(
            "SELECT COUNT(*) AS n FROM messages WHERE client_id = ? AND chat_id = ? AND from_bot = 1"
            " AND created_at >= ?", (client_id, chat_id, since))[0]["n"]

    def put_pending(self, client_id: str, chat_id: str, sender_id: str, tab: str,
                    row: dict[str, str], expires_at: float) -> None:
        self._write(
            "INSERT OR REPLACE INTO pending_writes VALUES (?, ?, ?, ?, ?, ?)",
            (client_id, chat_id, sender_id, tab, json.dumps(row, ensure_ascii=False), expires_at))

    def get_pending(self, client_id: str, chat_id: str, sender_id: str,
                    now: float) -> tuple[str, dict[str, str]] | None:
        rows = self._all(
            "SELECT tab, row_json, expires_at FROM pending_writes"
            " WHERE client_id = ? AND chat_id = ? AND sender_id = ?", (client_id, chat_id, sender_id))
        if not rows:
            return None
        if rows[0]["expires_at"] <= now:
            self._write("DELETE FROM pending_writes WHERE client_id = ? AND chat_id = ? AND sender_id = ?"
                        " AND expires_at <= ?", (client_id, chat_id, sender_id, now))
            return None
        return rows[0]["tab"], json.loads(rows[0]["row_json"])

    def drop_pending(self, client_id: str, chat_id: str, sender_id: str) -> None:
        self._write("DELETE FROM pending_writes WHERE client_id = ? AND chat_id = ? AND sender_id = ?",
                    (client_id, chat_id, sender_id))

    def purge_expired_pending(self, now: float) -> int:
        return self._write("DELETE FROM pending_writes WHERE expires_at <= ?", (now,))

    def delete_older_than(self, client_id: str, cutoff: float) -> int:
        return self._write("DELETE FROM messages WHERE client_id = ? AND created_at < ?", (client_id, cutoff))

    def backup(self, dest: str) -> None:
        path = Path(dest)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)  # VACUUM INTO refuses to overwrite
        with self._lock:
            self._db.execute("VACUUM INTO ?", (str(path),))

    def writable(self) -> bool:
        try:
            with self._lock:
                self._db.execute("BEGIN IMMEDIATE")
                self._db.execute("ROLLBACK")
            return True
        except sqlite3.Error:
            return False

    def conversations(self, client_id: str, limit: int = 100) -> list[sqlite3.Row]:
        """One row per chat for the dashboard: newest first, with the latest human sender's name."""
        return self._all(
            "SELECT chat_id, channel, MAX(created_at) AS last_at, COUNT(*) AS messages,"
            " (SELECT h.sender_name FROM messages h WHERE h.client_id = m.client_id AND h.chat_id = m.chat_id"
            "  AND h.from_bot = 0 AND h.sender_name != '' ORDER BY h.created_at DESC, h.id DESC LIMIT 1) AS name"
            " FROM messages m WHERE client_id = ? GROUP BY chat_id, channel ORDER BY last_at DESC LIMIT ?",
            (client_id, limit))

    def chat(self, client_id: str, chat_id: str, limit: int = 200) -> list[sqlite3.Row]:
        rows = self._all(
            "SELECT sender_name, text, from_bot, created_at, channel FROM messages"
            " WHERE client_id = ? AND chat_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (client_id, chat_id, limit))
        return rows[::-1]

    def replies_since(self, client_id: str, since: float) -> dict[str, int]:
        rows = self._all("SELECT channel, COUNT(*) AS n FROM messages WHERE client_id = ? AND from_bot = 1"
                         " AND created_at >= ? GROUP BY channel", (client_id, since))
        return {"meta": 0, "waha": 0, **{r["channel"]: r["n"] for r in rows}}
