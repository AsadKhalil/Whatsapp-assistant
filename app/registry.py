"""Businesses, the purchased-number inventory and the audit log: the dashboard's source of truth."""
from __future__ import annotations

import json
import logging
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

from app.config import Client, Settings, client_from_dict, digits
from app.db import Db
from app.mailer import is_email
from app.vault import Vault, VaultError

log = logging.getLogger("registry")

SCHEMA = """
CREATE TABLE IF NOT EXISTS businesses (
  id TEXT PRIMARY KEY,
  config TEXT NOT NULL,
  meta_phone_number_id TEXT UNIQUE,
  meta_access_token TEXT,
  meta_app_secret TEXT,
  meta_verify_token TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS numbers (
  session TEXT PRIMARY KEY,
  business_id TEXT UNIQUE REFERENCES businesses(id),
  phone TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY,
  at REAL NOT NULL,
  actor TEXT NOT NULL,
  business_id TEXT,
  action TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS audit_by_business ON audit (business_id, at);
CREATE TABLE IF NOT EXISTS email_accounts (
  business_id TEXT PRIMARY KEY REFERENCES businesses(id),
  address TEXT NOT NULL,
  app_password TEXT NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS setups (
  business_id TEXT PRIMARY KEY REFERENCES businesses(id),
  messages TEXT NOT NULL,     -- JSON list of {"role": "user"|"assistant", "content": str}
  draft TEXT,                 -- JSON draft, or NULL
  turn_day TEXT NOT NULL,     -- UTC date of the counted AI calls, YYYY-MM-DD
  turns INTEGER NOT NULL,     -- AI calls made on turn_day
  applied_at REAL,            -- last successful Apply, or NULL
  updated_at REAL NOT NULL
);
"""
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{1,30}[a-z0-9]")
CONFIG_KEYS = frozenset({"business", "bot_name", "sheet_id", "timezone", "date_format", "instructions", "personality",
                         "knowledge_tab", "handoff_tab", "staff_chats", "staff_numbers", "staff_alert_chat",
                         "retention_days", "tabs", "web_search_staff", "web_search_customers"})
SELECT_BUSINESS = ("SELECT b.*, n.session, e.address AS email_address, e.app_password AS email_app_password"
                   " FROM businesses b LEFT JOIN numbers n ON n.business_id = b.id"
                   " LEFT JOIN email_accounts e ON e.business_id = b.id")
SETUP_KEEP = 30 * 86_400  # seconds an untouched setup interview is kept


@dataclass(frozen=True)
class Business:
    """One business as the pages see it: its settings, and which secrets are saved (never the secrets)."""
    id: str
    config: dict
    meta_phone_number_id: str | None
    has_meta_token: bool
    has_meta_secret: bool
    meta_token_hint: str  # last 4 characters of the access token, or ""
    meta_verify_token: str
    active: bool
    number: str | None  # the assigned WAHA session
    keys_unreadable: bool  # sealed Meta keys can't be opened: SECRET_KEY changed
    email_address: str = ""  # the business's Gmail for staff emails, or ""
    has_email_password: bool = False
    email_unreadable: bool = False  # the saved app password can't be opened: SECRET_KEY changed


@dataclass(frozen=True)
class Number:
    session: str
    business_id: str | None
    phone: str
    notes: str


class Registry:
    def __init__(self, db: Db, vault: Vault, clock=time.time) -> None:
        self.db, self.vault, self.clock = db, vault, clock
        db.script(SCHEMA)

    # --- audit

    def audit(self, actor: str, business_id: str | None, action: str, detail: dict) -> None:
        self.db.write("INSERT INTO audit (at, actor, business_id, action, detail) VALUES (?, ?, ?, ?, ?)",
                      (self.clock(), actor, business_id, action,
                       json.dumps(detail, ensure_ascii=False, sort_keys=True)))

    def audit_log(self, business_id: str | None = None, limit: int = 100) -> list[sqlite3.Row]:
        if business_id is None:
            return self.db.all("SELECT * FROM audit ORDER BY at DESC, id DESC LIMIT ?", (limit,))
        return self.db.all("SELECT * FROM audit WHERE business_id = ? ORDER BY at DESC, id DESC LIMIT ?",
                           (business_id, limit))

    # --- businesses

    def is_empty(self) -> bool:
        return self.db.one("SELECT 1 FROM businesses LIMIT 1") is None

    def _open(self, sealed: str | None) -> str | None:
        """The secret; "" when none is saved; None when it can't be opened."""
        if not sealed:
            return ""
        try:
            return self.vault.open(sealed)
        except VaultError:
            return None

    def _business(self, row: sqlite3.Row) -> Business:
        token, secret = self._open(row["meta_access_token"]), self._open(row["meta_app_secret"])
        email_password = self._open(row["email_app_password"])
        return Business(id=row["id"], config=json.loads(row["config"]),
                        meta_phone_number_id=row["meta_phone_number_id"], has_meta_token=bool(token),
                        has_meta_secret=bool(secret), meta_token_hint=(token or "")[-4:],
                        meta_verify_token=row["meta_verify_token"], active=bool(row["active"]),
                        number=row["session"], keys_unreadable=token is None or secret is None,
                        email_address=row["email_address"] or "", has_email_password=bool(email_password),
                        email_unreadable=email_password is None)

    def businesses(self) -> list[Business]:
        return [self._business(r) for r in self.db.all(SELECT_BUSINESS + " ORDER BY b.id")]

    def business(self, business_id: str | None) -> Business | None:
        row = self.db.one(SELECT_BUSINESS + " WHERE b.id = ?", (business_id,))
        return self._business(row) if row else None

    def clients(self, include_paused: bool = False) -> dict[str, Client]:
        """Every active business as the engine's Client, with its Meta keys opened; paused ones too when asked."""
        query = SELECT_BUSINESS if include_paused else SELECT_BUSINESS + " WHERE b.active = 1"
        out = {}
        for row in self.db.all(query):
            raw = {**json.loads(row["config"]), "meta_phone_number_id": row["meta_phone_number_id"],
                   "waha_session": row["session"]}
            try:
                client = client_from_dict(row["id"], raw)
            except ValueError:
                log.exception("business_config_invalid business=%s", row["id"])
                continue
            # an app secret that can't be opened becomes one no signature matches, so both webhooks fail closed
            app_secret = self._open(row["meta_app_secret"])
            # no app password, or one that can't be opened, leaves email switched off for this business
            email_password = self._open(row["email_app_password"]) or ""
            out[client.id] = replace(client, meta_access_token=self._open(row["meta_access_token"]) or "",
                                     meta_app_secret=secrets.token_hex(32) if app_secret is None else app_secret,
                                     meta_verify_token=row["meta_verify_token"],
                                     email_address=(row["email_address"] or "") if email_password else "",
                                     email_app_password=email_password)
        return out

    def _clean(self, business_id: str, config: dict) -> dict:
        """Known settings only, staff numbers as digits, validated exactly like clients.yaml."""
        unknown = set(config) - CONFIG_KEYS
        if unknown:
            raise ValueError(f"Unknown settings: {', '.join(sorted(unknown))}")
        config = {**config, "staff_numbers": [digits(str(n)) for n in config.get("staff_numbers") or []]}
        client_from_dict(business_id, config)
        return config

    def create_business(self, business_id: str, config: dict, actor: str, action: str = "business.create") -> None:
        if not SLUG.fullmatch(business_id or ""):
            raise ValueError("The web id must be 3-32 lowercase letters, digits or dashes, like sweetbakes.")
        config = self._clean(business_id, config)
        now = self.clock()
        try:
            self.db.write("INSERT INTO businesses (id, config, meta_verify_token, created_at, updated_at)"
                          " VALUES (?, ?, ?, ?, ?)",
                          (business_id, json.dumps(config, ensure_ascii=False), secrets.token_urlsafe(24), now, now))
        except sqlite3.IntegrityError:
            raise ValueError(f"A business with the web id {business_id!r} already exists.") from None
        self.audit(actor, business_id, action, {"business": config["business"]})

    def save_config(self, business_id: str, changes: dict, actor: str) -> None:
        business = self.business(business_id)
        if business is None:
            raise ValueError("No such business.")
        config = self._clean(business_id, {**business.config, **changes})
        self.db.write("UPDATE businesses SET config = ?, updated_at = ? WHERE id = ?",
                      (json.dumps(config, ensure_ascii=False), self.clock(), business_id))
        changed = {key: config[key] for key in changes if business.config.get(key) != config.get(key)}
        if changed:
            self.audit(actor, business_id, "settings.save", changed)

    def save_meta(self, business_id: str, phone_number_id: str, access_token: str, app_secret: str,
                  actor: str) -> None:
        """The official number's keys; an empty token or secret keeps the saved one."""
        phone_number_id = (phone_number_id or "").strip()
        if phone_number_id and not phone_number_id.isdigit():
            raise ValueError("The phone number ID is digits only (Meta shows it next to the number).")
        sets, args = ["meta_phone_number_id = ?"], [phone_number_id or None]
        detail = {"meta_phone_number_id": phone_number_id}
        if access_token:
            sets.append("meta_access_token = ?")
            args.append(self.vault.seal(access_token))
            detail["access_token"] = "(changed)"
        if app_secret:
            sets.append("meta_app_secret = ?")
            args.append(self.vault.seal(app_secret))
            detail["app_secret"] = "(changed)"
        try:
            found = self.db.write(f"UPDATE businesses SET {', '.join(sets)}, updated_at = ? WHERE id = ?",
                                  (*args, self.clock(), business_id))
        except sqlite3.IntegrityError:
            raise ValueError("Another business already uses that phone number ID.") from None
        if not found:
            raise ValueError("No such business.")
        self.audit(actor, business_id, "meta.save", detail)

    def set_active(self, business_id: str, active: bool, actor: str) -> None:
        if not self.db.write("UPDATE businesses SET active = ?, updated_at = ? WHERE id = ?",
                             (int(active), self.clock(), business_id)):
            raise ValueError("No such business.")
        self.audit(actor, business_id, "business.resume" if active else "business.pause", {})

    # --- email

    def save_email(self, business_id: str, address: str, app_password: str, actor: str) -> None:
        """The business's Gmail for staff emails; an empty app password keeps the saved one."""
        address = (address or "").strip()
        app_password = "".join((app_password or "").split())
        if not is_email(address):
            raise ValueError("Enter one Gmail address, like sweetbakes@gmail.com.")
        if app_password and not re.fullmatch(r"[A-Za-z]{16}", app_password):
            raise ValueError("The app password is the 16 letters Google shows (spaces don't matter), "
                             "not your normal Gmail password.")
        if self.business(business_id) is None:
            raise ValueError("No such business.")
        detail = {"address": address}
        if app_password:
            self.db.write("INSERT INTO email_accounts (business_id, address, app_password, updated_at)"
                          " VALUES (?, ?, ?, ?) ON CONFLICT (business_id) DO UPDATE SET address = excluded.address,"
                          " app_password = excluded.app_password, updated_at = excluded.updated_at",
                          (business_id, address, self.vault.seal(app_password), self.clock()))
            detail["app_password"] = "(changed)"
        elif not self.db.write("UPDATE email_accounts SET address = ?, updated_at = ? WHERE business_id = ?",
                               (address, self.clock(), business_id)):
            raise ValueError("Enter the app password too.")
        self.audit(actor, business_id, "email.save", detail)

    def remove_email(self, business_id: str, actor: str) -> None:
        if self.db.write("DELETE FROM email_accounts WHERE business_id = ?", (business_id,)):
            self.audit(actor, business_id, "email.remove", {})

    # --- guided setup

    def _day(self) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(self.clock()))

    def setup(self, business_id: str) -> dict:
        """The business's setup interview: its messages, its draft (or None) and when it was last applied."""
        row = self.db.one("SELECT messages, draft, applied_at FROM setups WHERE business_id = ?", (business_id,))
        if row is None:
            return {"messages": [], "draft": None, "applied_at": None}
        return {"messages": json.loads(row["messages"]), "draft": json.loads(row["draft"]) if row["draft"] else None,
                "applied_at": row["applied_at"]}

    def save_setup(self, business_id: str, messages: list[dict], draft: dict | None) -> None:
        """Store the conversation and draft. The day's AI call count is kept, so Start over can't reset it."""
        self.db.write("INSERT INTO setups (business_id, messages, draft, turn_day, turns, updated_at)"
                      " VALUES (?, ?, ?, ?, 0, ?) ON CONFLICT (business_id) DO UPDATE SET"
                      " messages = excluded.messages, draft = excluded.draft, updated_at = excluded.updated_at",
                      (business_id, json.dumps(messages, ensure_ascii=False),
                       None if draft is None else json.dumps(draft, ensure_ascii=False), self._day(), self.clock()))

    def spend_setup_call(self, business_id: str, limit: int) -> bool:
        """Count one AI call for today (UTC); False, counting nothing, once `limit` calls were made today."""
        today = self._day()
        with self.db.transaction():
            row = self.db.one("SELECT turn_day, turns FROM setups WHERE business_id = ?", (business_id,))
            turns = row["turns"] if row and row["turn_day"] == today else 0
            if turns >= limit:
                return False
            self.db.write("INSERT INTO setups (business_id, messages, turn_day, turns, updated_at)"
                          " VALUES (?, '[]', ?, ?, ?) ON CONFLICT (business_id) DO UPDATE SET"
                          " turn_day = excluded.turn_day, turns = excluded.turns, updated_at = excluded.updated_at",
                          (business_id, today, turns + 1, self.clock()))
        return True

    def setup_applied(self, business_id: str, actor: str, detail: dict) -> None:
        """Record a successful Apply: what was added (never Knowledge text)."""
        self.db.write("UPDATE setups SET applied_at = ?, updated_at = ? WHERE business_id = ?",
                      (self.clock(), self.clock(), business_id))
        self.audit(actor, business_id, "setup.apply", detail)

    def purge_setups(self, now: float) -> int:
        """Forget setup interviews nobody touched for 30 days."""
        return self.db.write("DELETE FROM setups WHERE updated_at < ?", (now - SETUP_KEEP,))

    # --- numbers

    @staticmethod
    def _number(row: sqlite3.Row) -> Number:
        return Number(session=row["session"], business_id=row["business_id"], phone=row["phone"],
                      notes=row["notes"])

    def numbers(self) -> list[Number]:
        return [self._number(r) for r in self.db.all("SELECT * FROM numbers ORDER BY session")]

    def number(self, session: str) -> Number | None:
        row = self.db.one("SELECT * FROM numbers WHERE session = ?", (session,))
        return self._number(row) if row else None

    def add_number(self, session: str, notes: str, actor: str) -> None:
        if not SLUG.fullmatch(session or ""):
            raise ValueError("The session name must be 3-32 lowercase letters, digits or dashes, like sweetbakes-1.")
        try:
            self.db.write("INSERT INTO numbers (session, notes, created_at) VALUES (?, ?, ?)",
                          (session, notes.strip(), self.clock()))
        except sqlite3.IntegrityError:
            raise ValueError(f"A number called {session!r} already exists.") from None
        self.audit(actor, None, "number.add", {"session": session})

    def save_number_notes(self, session: str, notes: str, actor: str) -> None:
        if not self.db.write("UPDATE numbers SET notes = ? WHERE session = ?", (notes.strip(), session)):
            raise ValueError("No such number.")
        self.audit(actor, None, "number.notes", {"session": session})

    def set_number_phone(self, session: str, phone: str) -> None:
        self.db.write("UPDATE numbers SET phone = ? WHERE session = ?", (digits(phone), session))

    def assign_number(self, session: str, business_id: str | None, actor: str) -> None:
        """Give a number to a business (taking the business off any other number), or unassign it with None."""
        number = self.number(session)
        if number is None:
            raise ValueError("No such number.")
        if business_id is not None and self.business(business_id) is None:
            raise ValueError("No such business.")
        with self.db.transaction():
            if business_id is not None:
                self.db.write("UPDATE numbers SET business_id = NULL WHERE business_id = ?", (business_id,))
            self.db.write("UPDATE numbers SET business_id = ? WHERE session = ?", (business_id, session))
        self.audit(actor, business_id or number.business_id,
                   "number.assign" if business_id else "number.unassign", {"session": session})

    def delete_number(self, session: str, actor: str) -> None:
        number = self.number(session)
        if number is None:
            raise ValueError("No such number.")
        if number.business_id:
            raise ValueError("Unassign the number from its business before deleting it.")
        self.db.write("DELETE FROM numbers WHERE session = ?", (session,))
        self.audit(actor, None, "number.delete", {"session": session})

    # --- first run

    def import_yaml(self, path: str, settings: Settings) -> int:
        """First start only: copy clients.yaml, and the pilot's .env Meta keys, into the database."""
        entries = {str(k): dict(v or {}) for k, v in
                   ((yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}).get("clients") or {}).items()}
        seen: set[tuple[str, str]] = set()
        for business_id, entry in entries.items():  # check everything before writing anything
            if not SLUG.fullmatch(business_id):
                raise ValueError(f"Rename {business_id!r} in clients.yaml: web ids are 3-32 lowercase letters, "
                                 "digits or dashes.")
            unknown = set(entry) - CONFIG_KEYS - {"meta_phone_number_id", "waha_session"}
            if unknown:
                raise ValueError(f"{business_id}: unknown settings {', '.join(sorted(unknown))}")
            client_from_dict(business_id, entry)
            session = str(entry.get("waha_session") or "")
            if session and not SLUG.fullmatch(session):
                raise ValueError(f"{business_id}: waha_session {session!r} must be 3-32 lowercase letters, "
                                 "digits or dashes")
            phone_number_id = str(entry.get("meta_phone_number_id") or "").strip()
            if phone_number_id and not phone_number_id.isdigit():
                raise ValueError(f"{business_id}: meta_phone_number_id must be digits")
            for key, value in (("waha_session", session), ("meta_phone_number_id", phone_number_id)):
                if value and (key, value) in seen:
                    raise ValueError(f"{business_id}: {key} {value!r} is already used by another client")
                seen.add((key, value))
        for business_id, entry in entries.items():
            phone_number_id = str(entry.pop("meta_phone_number_id", "") or "")
            session = entry.pop("waha_session", None)
            self.create_business(business_id, entry, actor="system", action="business.import")
            if phone_number_id:
                self.save_meta(business_id, phone_number_id, settings.meta_access_token, settings.meta_app_secret,
                               actor="system")
                if settings.meta_verify_token:  # the webhook already configured at Meta keeps verifying
                    self.db.write("UPDATE businesses SET meta_verify_token = ? WHERE id = ?",
                                  (settings.meta_verify_token, business_id))
            if session:
                self.add_number(str(session), "imported from clients.yaml", actor="system")
                self.assign_number(str(session), business_id, actor="system")
        return len(entries)
