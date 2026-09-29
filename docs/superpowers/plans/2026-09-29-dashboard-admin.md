# Dashboard and Admin Console (v2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a web dashboard to the WhatsApp engine: an admin console for the owner (every business and number, QR linking, Meta keys, logins, pause, audit) and a dashboard for each business (bot settings, staff and groups, Sheet permissions, chats).

**Architecture:** Everything stays in the one FastAPI service, container and SQLite file. Business settings move from `clients.yaml` into a `businesses` table (JSON config validated by the same `client_from_dict` rules), Meta keys become per business (sealed with `SECRET_KEY`), and each business gets its own Meta webhook URL. Server-rendered Jinja2 pages with Pico.css; logins with invites, scrypt passwords, sessions, CSRF and two-step login for admins. Saving a setting swaps `bot.clients` at once.

**Tech Stack:** Python 3.12 (uv), FastAPI, Jinja2, cryptography (Fernet), sqlite3, gspread, httpx; pytest, ruff. Pico.css 2.0.6 vendored as a static file.

**Spec:** `docs/superpowers/specs/2026-09-28-dashboard-admin-design.md` (builds on `docs/superpowers/specs/2026-09-23-whatsapp-engine-design.md`)

## Global Constraints

- Python `>=3.12`, managed by uv; `[tool.uv] package = false`; run every command from the repo root with `uv run`.
- New runtime dependencies are exactly `jinja2` and `cryptography`. Add nothing else: forms are parsed with `urllib.parse.parse_qs` (no `python-multipart`), passwords use `hashlib.scrypt`, TOTP uses `hmac`/`struct`/`base64`.
- Ruff runs with `select = ["E4", "E7", "E9", "F"]`: no unused imports, no `;`-joined statements, no one-line `def x(): y`, no assigned lambdas.
- Everything stays in the one FastAPI service, container and SQLite file (`DB_PATH`).
- `SECRET_KEY` is required: `create_app` raises `RuntimeError("Set SECRET_KEY in .env ...")` when it is empty. Meta access tokens, Meta app secrets and TOTP secrets are stored sealed by `Vault`.
- Invite links last 7 days. Admin sessions end 12 hours after login, business sessions 7 days after. Passwords have at least 10 characters and are stored as `scrypt$16384$8$1$<salt hex>$<hash hex>`. TOTP: RFC 6238, SHA-1, 30-second steps, 6 digits, one step of drift. 5 failed logins (or codes) within 15 minutes pause that email (or user) for 15 minutes.
- Session cookie `wa_session`: `HttpOnly`, `Secure`, `SameSite=Lax`, path `/`; the database stores only its SHA-256.
- Every signed-in `POST` must carry the session's CSRF token in the form field `csrf`; missing or wrong → 403.
- Every response carries `Content-Security-Policy: default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; form-action 'self'`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`.
- `/app/...` routes require `role = business` and never take a business id; `/admin/...` routes require `role = admin` with a passed second step (`mfa_ok`).
- Meta keys are write-only on screen (a hint shows the last 4 characters of the token); audit `detail` never contains a secret (it says `(changed)`).
- Logs never contain message text; chat ids only as the 12-character HMAC; failed logins log a 12-character hash of the email.
- Business ids and number session names: 3–32 lowercase letters, digits or dashes, not starting or ending with a dash (`[a-z0-9][a-z0-9-]{1,30}[a-z0-9]`).
- One group number per business (`numbers.business_id` is `UNIQUE`).
- All v1 engine tests keep passing; the v1 `/webhooks/meta` address keeps working for businesses on the `.env` Meta app.
- Commit after every task with the message given; stage only the files you changed, by name (never `git add -A` or `git add .`).

## Plan decisions (read these before reviewing against the spec)

1. **No htmx.** The spec's three live parts work with plain forms: "Check access" and "What a customer would see" are submit buttons that re-render the page, and the QR page refreshes itself with `<meta http-equiv="refresh" content="3">`. No JavaScript at all, so the CSP needs no `script-src` exceptions and the CSRF token travels only in the form field (no `X-CSRF-Token` header). Add htmx later if the reloads feel clunky.
2. **`Sheets.tab_headers(sheet_id)`** instead of the spec's `Sheets.tabs(...)`: the test fake `FakeSheets` already uses a `tabs` attribute for its rows.
3. **Two extra focused modules:** `app/sheet_rules.py` (the §8.4 guardrail checks) and `app/numbers_pages.py` (the numbers inventory, split from `app/admin_pages.py`).
4. **`sessions.totp_pending`** holds a sealed, not-yet-confirmed TOTP secret during an admin's first two-step setup.
5. **Audit `actor`** is the user's id as a string (or `system`); the audit page shows emails.
6. **The Sheet id** is editable by admins only; business users see it read-only.
7. **"Latest requests for a human"** on the business home shows the 10 newest Handoffs rows (the tab keeps every request, so "waiting" would be inaccurate).
8. **Route helper:** page handlers are plain functions `handler(request, ctx, form)` run in a worker thread (they call Google Sheets and WAHA, which block). `app.web.route` wraps them, parses and CSRF-checks POST forms, and registers them on a router.
9. **Admin overview, official number column:** shows whether the Meta keys are saved (or need re-entering); activity shows in the two replies-this-month columns, so there is no separate last-message time.

## Review Focus

- **Reaching another business by editing a URL or form value** (a chat id, a login's `user_id`, a number's session) must give 404/403, never data. Pinned: Task 9 `test_chats_stay_inside_the_business`, Task 11 `test_business_logins_invite_new_link_and_disable`, Task 12 `test_business_users_cannot_manage_numbers`.
- **Saving Sheet permissions while the Sheet can't be read** must not wipe the saved permissions. Pinned: Task 10 `test_permissions_are_not_wiped_when_the_sheet_cant_be_read`.
- **Secrets never leave the server:** no Meta token or app secret in any page or audit entry; TOTP secrets sealed. Pinned: Task 3 `test_meta_keys_are_sealed_kept_when_blank_and_never_audited`, Task 7 `test_admin_sessions_need_the_second_step_and_last_12_hours`, Task 11 `test_meta_keys_are_write_only_and_reach_the_bot`.
- **A webhook signed by one business's Meta app** carrying another business's number must be ignored; a paused business's webhooks get a 200 and nothing is queued. Pinned: Task 6 `test_a_business_webhook_checks_its_own_app_secret_and_only_its_own_number`, `test_paused_businesses_get_a_200_and_nothing_is_queued`.
- **WAHA or Google Sheets down** must never break a page: statuses read `UNREACHABLE`, errors are shown, nothing crashes. Pinned: Task 10 `test_staff_page_keeps_saved_groups_when_waha_is_down`, Task 12 `test_numbers_page_survives_waha_being_down`.

---

## File Structure

| File | Responsibility |
|---|---|
| `app/db.py` | `Db`: one SQLite connection behind a re-entrant lock; `script`, `all`, `one`, `write`, `insert`, `transaction` |
| `app/vault.py` | `Vault(secret_key)`: `seal` / `open` with Fernet; `VaultError` |
| `app/config.py` (modify) | `Settings.secret_key/public_url/waha_webhook_url`; `Client` secret fields (hidden from `repr`); `client_from_dict` |
| `app/registry.py` | `Registry`: businesses (JSON config), numbers inventory, audit log, `clients()`, first-run import |
| `app/whatsapp.py` (modify) | Meta calls take a per-business token; `MetaClient.number_info`; WAHA session management; `session_phone` |
| `app/store.py` (modify) | `conversations`, `chat`, `replies_since` |
| `app/sheets.py` (modify) | `tab_headers`, `service_account_email`, `sheet_error` |
| `app/bot.py` (modify) | Passes the business's Meta token to sends and voice downloads |
| `app/main.py` (modify) | `open_registry`, live `reload`, per-business Meta webhook, dashboard wiring |
| `app/auth.py` | `Auth`: users, invites, passwords, sessions, TOTP, rate limit |
| `app/web.py` | Templates, `Form`, sign-in dependencies, CSRF, `route`, security headers, error pages, `/login` `/invite` `/logout` `/` |
| `app/cli.py` | `python -m app.cli create-admin EMAIL` / `admin-link EMAIL` |
| `app/pages.py` | Business screens mounted at `/app` and `/admin/b/{id}`: home, settings, chats, staff, Sheet |
| `app/sheet_rules.py` | §8.4 guardrails: contact-column detection, per-tab problems |
| `app/admin_pages.py` | Overview, new business, official number, group number, logins, pause, audit, admins |
| `app/numbers_pages.py` | Numbers inventory: add, QR link page, QR image, relink, log out, assign, notes, delete |
| `app/templates/*.html` | Jinja2 pages extending `base.html` |
| `app/static/pico.min.css`, `app/static/app.css` | Vendored Pico.css 2.0.6 and a few overrides |
| `tests/fakes.py` (modify) | Registry helpers; `FakeMeta`/`FakeWaha`/`FakeSheets` gain the new calls |
| `tests/webkit.py` | `Site` (an app with in-memory stores), signed-in browsers, `csrf()` |
| `Caddyfile`, `docker-compose.yml`, `Dockerfile`, `.env.example`, `README.md`, `docs/setup-guide.md` (modify) | Public paths, `PUBLIC_URL`, the app's Python on the container PATH, `SECRET_KEY`, operator docs |

---

### Task 1: Dependencies, shared database helper and the vault

**Files:**
- Modify: `pyproject.toml`, `uv.lock`
- Create: `app/db.py`, `app/vault.py`
- Test: `tests/test_db_vault.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `app.db.Db(path: str)` with `script(sql) -> None`, `all(sql, args=()) -> list[sqlite3.Row]`, `one(sql, args=()) -> sqlite3.Row | None`, `write(sql, args=()) -> int` (rowcount), `insert(sql, args=()) -> int` (lastrowid), and `transaction()` (context manager; `write`/`all` may be called inside it; any exception rolls everything back). Foreign keys are enforced.
  - `app.vault.Vault(secret_key: str)` with `seal(text) -> str` and `open(token) -> str`; `open` raises `app.vault.VaultError` (message mentions `SECRET_KEY`) when the key is different; `Vault("")` raises `ValueError`.

- [ ] **Step 1: Add the two dependencies**

In `pyproject.toml`, change the `dependencies` list to:
```toml
dependencies = [
  "fastapi>=0.115",
  "uvicorn>=0.30",
  "httpx>=0.27",
  "openai>=3.19",
  "gspread>=6.1",
  "pyyaml>=6.0",
  "tzdata>=2024.1",
  "jinja2>=3.1",
  "cryptography>=44",
]
```

Run: `uv sync`
Expected: `jinja2` and `cryptography` are installed and `uv.lock` is updated.

- [ ] **Step 2: Write the failing tests**

`tests/test_db_vault.py`:
```python
import sqlite3

import pytest

from app.db import Db
from app.vault import Vault, VaultError


def test_db_reads_writes_and_rolls_back_a_failed_transaction():
    db = Db(":memory:")
    db.script("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)")
    assert db.insert("INSERT INTO t (name) VALUES (?)", ("a",)) == 1
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction():
            db.write("INSERT INTO t (name) VALUES (?)", ("b",))
            db.write("INSERT INTO t (name) VALUES (?)", ("a",))  # duplicate: the whole transaction rolls back
    assert [r["name"] for r in db.all("SELECT name FROM t ORDER BY id")] == ["a"]
    assert db.one("SELECT name FROM t WHERE name = ?", ("zzz",)) is None
    assert db.write("UPDATE t SET name = ? WHERE name = ?", ("c", "a")) == 1


def test_db_enforces_foreign_keys(tmp_path):
    db = Db(str(tmp_path / "data" / "x.db"))
    db.script("CREATE TABLE p (id TEXT PRIMARY KEY); CREATE TABLE c (p TEXT REFERENCES p(id));")
    with pytest.raises(sqlite3.IntegrityError):
        db.write("INSERT INTO c (p) VALUES ('missing')")


def test_vault_round_trip_and_wrong_key():
    sealed = Vault("key-one").seal("EAAG-secret-token")
    assert "EAAG" not in sealed
    assert Vault("key-one").open(sealed) == "EAAG-secret-token"
    with pytest.raises(VaultError, match="SECRET_KEY"):
        Vault("key-two").open(sealed)
    with pytest.raises(ValueError):
        Vault("")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_db_vault.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.db'`

- [ ] **Step 4: Implement `Db` and `Vault`**

`app/db.py`:
```python
"""One shared SQLite connection for the dashboard's tables (businesses, numbers, audit, users, sessions)."""
from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class Db:
    # ponytail: one connection behind one lock, like Store; fine for tens of businesses on one server.
    def __init__(self, path: str) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()  # re-entrant, so write() works inside transaction()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA foreign_keys=ON")

    def script(self, sql: str) -> None:
        with self._lock:
            self._conn.executescript(sql)

    def all(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    def one(self, sql: str, args: tuple = ()) -> sqlite3.Row | None:
        rows = self.all(sql, args)
        return rows[0] if rows else None

    def write(self, sql: str, args: tuple = ()) -> int:
        with self._lock:
            return self._conn.execute(sql, args).rowcount

    def insert(self, sql: str, args: tuple = ()) -> int:
        with self._lock:
            return self._conn.execute(sql, args).lastrowid

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """All writes inside commit together or not at all."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")
```

`app/vault.py`:
```python
"""Encrypts the secrets kept in the database (Meta keys, TOTP secrets) with SECRET_KEY."""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


class VaultError(Exception):
    """A sealed value can't be opened, usually because SECRET_KEY changed."""


class Vault:
    def __init__(self, secret_key: str) -> None:
        if not secret_key:
            raise ValueError("SECRET_KEY is empty")
        self._fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode()).digest()))

    def seal(self, text: str) -> str:
        return self._fernet.encrypt(text.encode()).decode()

    def open(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken:
            raise VaultError("A saved secret can't be read; was SECRET_KEY changed?") from None
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_db_vault.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock app/db.py app/vault.py tests/test_db_vault.py
git commit -m "feat: shared SQLite helper and a vault for secrets"
```

### Task 2: Settings, hidden Client secrets and `client_from_dict`

**Files:**
- Modify: `app/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `Settings.secret_key: str = ""`, `Settings.public_url: str = ""`, `Settings.waha_webhook_url: str = "http://engine:8000/webhooks/waha"` (read from `SECRET_KEY`, `PUBLIC_URL`, `WAHA_WEBHOOK_URL`).
  - `Client.meta_access_token`, `Client.meta_app_secret`, `Client.meta_verify_token`: `str`, default `""`, excluded from `repr`.
  - `app.config.client_from_dict(client_id: str, c: dict) -> Client`: builds one client from a `clients.yaml`-shaped dict; raises `ValueError` for a missing `business`/`bot_name`/`sheet_id` ("... is required"), an unknown time zone, bad tab rules (v1 messages), or `retention_days` that isn't a whole number (`"whole number"`) or is outside 1–3650 (`"between 1 and 3650"`).
  - `load_clients(path)` keeps its behaviour, built on `client_from_dict`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_config.py`, replace the import block with:
```python
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from app.config import Settings, client_from_dict, load_clients, same_phone
from tests.fakes import make_client
```

Append to `tests/test_config.py`:
```python
def test_client_from_dict_matches_the_yaml_loader_and_hides_secrets():
    raw = yaml.safe_load(Path("clients.example.yaml").read_text(encoding="utf-8"))["clients"]["sweetbakes"]
    assert client_from_dict("sweetbakes", raw) == load_clients("clients.example.yaml")["sweetbakes"]
    secret = replace(make_client(), meta_access_token="EAAG-token", meta_app_secret="app-secret",
                     meta_verify_token="verify")
    assert "EAAG-token" not in repr(secret) and "app-secret" not in repr(secret) and "verify" not in repr(secret)


@pytest.mark.parametrize("change, message", [
    ({"business": ""}, "business is required"),
    ({"bot_name": None}, "bot_name is required"),
    ({"retention_days": 5000}, "between 1 and 3650"),
    ({"retention_days": "abc"}, "whole number"),
])
def test_client_from_dict_explains_what_is_wrong(change, message):
    raw = {"business": "B", "bot_name": "S", "sheet_id": "s", **change}
    with pytest.raises(ValueError, match=message):
        client_from_dict("x", raw)


def test_new_settings_have_safe_defaults():
    s = Settings()
    assert s.secret_key == "" and s.public_url == ""
    assert s.waha_webhook_url == "http://engine:8000/webhooks/waha"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with `ImportError: cannot import name 'client_from_dict' from 'app.config'`

- [ ] **Step 3: Implement**

In `app/config.py`, add these three fields at the end of the `Settings` field list (after `google_service_account_file`):
```python
    secret_key: str = ""  # required by the dashboard: encrypts Meta keys and TOTP secrets in the database
    public_url: str = ""  # e.g. https://bot.example.com; compose sets it from DOMAIN
    waha_webhook_url: str = "http://engine:8000/webhooks/waha"  # where WAHA sessions created by the dashboard post
```

Add these three fields at the end of the `Client` field list (after `date_format`):
```python
    meta_access_token: str = field(default="", repr=False)  # this business's own Meta keys (from the dashboard)
    meta_app_secret: str = field(default="", repr=False)
    meta_verify_token: str = field(default="", repr=False)
```

Replace the whole `load_clients` function with:
```python
def client_from_dict(client_id: str, c: dict) -> Client:
    """One client from a clients.yaml entry or a stored business config; raises ValueError saying what's wrong."""
    for key in ("business", "bot_name", "sheet_id"):
        if not str(c.get(key) or "").strip():
            raise ValueError(f"{client_id}: {key} is required")
    timezone = c.get("timezone") or "UTC"
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"{client_id}: unknown timezone {timezone!r}") from None
    try:
        retention_days = int(c.get("retention_days") or 90)
    except (TypeError, ValueError):
        raise ValueError(f"{client_id}: retention_days must be a whole number of days") from None
    if not 1 <= retention_days <= 3650:
        raise ValueError(f"{client_id}: retention_days must be between 1 and 3650")
    return Client(
        id=client_id,
        business=str(c["business"]),
        bot_name=str(c["bot_name"]),
        sheet_id=str(c["sheet_id"]),
        tabs={tab: _tab_rule(client_id, tab, rule or {}) for tab, rule in (c.get("tabs") or {}).items()},
        timezone=timezone,
        instructions=c.get("instructions") or "",
        knowledge_tab=c.get("knowledge_tab") or "Knowledge",
        handoff_tab=c.get("handoff_tab") or "Handoffs",
        meta_phone_number_id=str(c["meta_phone_number_id"]) if c.get("meta_phone_number_id") else None,
        waha_session=c.get("waha_session") or None,
        staff_chats=frozenset(c.get("staff_chats") or []),
        staff_numbers=frozenset(digits(str(n)) for n in c.get("staff_numbers") or []),
        staff_alert_chat=c.get("staff_alert_chat") or None,
        retention_days=retention_days,
        date_format=c.get("date_format") or None,
    )


def load_clients(path: str) -> dict[str, Client]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return {cid: client_from_dict(cid, c or {}) for cid, c in (raw.get("clients") or {}).items()}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS (14 passed)

Run: `uv run pytest -q`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat: client_from_dict, dashboard settings and hidden per-business Meta keys"
```

### Task 3: The registry (businesses, numbers, audit log)

**Files:**
- Create: `app/registry.py`
- Modify: `tests/fakes.py` (imports; append registry helpers)
- Test: `tests/test_registry.py`

**Interfaces:**
- Consumes: `Db` (Task 1), `Vault`, `VaultError` (Task 1), `client_from_dict`, `Client`, `Settings`, `digits` (Task 2).
- Produces:
  - `app.registry.SLUG`: compiled `[a-z0-9][a-z0-9-]{1,30}[a-z0-9]` (use `SLUG.fullmatch`).
  - `app.registry.Business` (frozen dataclass): `id, config: dict, meta_phone_number_id: str | None, has_meta_token: bool, has_meta_secret: bool, meta_token_hint: str, meta_verify_token: str, active: bool, number: str | None, keys_unreadable: bool`.
  - `app.registry.Number` (frozen dataclass): `session, business_id: str | None, phone: str, notes: str`.
  - `app.registry.Registry(db, vault, clock=time.time)`; attributes `db`, `vault`. Methods:
    - reading: `is_empty() -> bool`, `businesses() -> list[Business]`, `business(business_id) -> Business | None`, `clients() -> dict[str, Client]` (active businesses only), `numbers() -> list[Number]`, `number(session) -> Number | None`, `audit_log(business_id=None, limit=100) -> list[sqlite3.Row]` (newest first; columns `at, actor, business_id, action, detail`).
    - writing (each raises `ValueError` with a message for the page): `create_business(business_id, config, actor, action="business.create")`, `save_config(business_id, changes, actor)`, `save_meta(business_id, phone_number_id, access_token, app_secret, actor)` (empty token/secret = keep), `set_active(business_id, active, actor)`, `add_number(session, notes, actor)`, `save_number_notes(session, notes, actor)`, `set_number_phone(session, phone)`, `assign_number(session, business_id | None, actor)`, `delete_number(session, actor)`, `audit(actor, business_id, action, detail: dict)`, `import_yaml(path, settings) -> int`.
  - `tests.fakes`: `acme_config() -> dict`, `memory_registry(secret="test-secret") -> Registry`, `registry_with_acme(meta=True) -> Registry` (business `acme` = `make_client()`'s settings, Meta keys `106540352242922` / `acme-token` / `acme-secret`, number `acme` assigned).

- [ ] **Step 1: Add the registry helpers to the fakes**

In `tests/fakes.py`, replace the import block with:
```python
from __future__ import annotations

import itertools
import json

from app.bot import Bot
from app.config import Client, TabRule
from app.db import Db
from app.llm import ModelReply, ToolCall
from app.registry import Registry
from app.store import Store
from app.vault import Vault
from app.whatsapp import Incoming
```

Append to `tests/fakes.py`:
```python
def acme_config() -> dict:
    """make_client()'s settings as the dashboard stores them."""
    return {
        "business": "Sweet Bakes", "bot_name": "Sara", "sheet_id": "sheet-1", "timezone": "Asia/Karachi",
        "instructions": "Orders need 24 hours notice.", "date_format": "%d/%m/%Y",
        "knowledge_tab": "Knowledge", "handoff_tab": "Handoffs",
        "tabs": {
            "Prices": {"customer": ["read"]},
            "Orders": {"customer": ["own", "append"], "owner_column": "Phone",
                       "fill": {"Name": "name", "Phone": "phone"}},
            "Staff Notes": {},
            "Expenses": {},
        },
        "staff_chats": ["staff@g.us"], "staff_numbers": ["923001111111"], "staff_alert_chat": "staff@g.us",
    }


def memory_registry(secret: str = "test-secret") -> Registry:
    return Registry(Db(":memory:"), Vault(secret))


def registry_with_acme(meta: bool = True) -> Registry:
    """A registry holding the acme bakery, its own Meta keys and its group number 'acme'."""
    registry = memory_registry()
    registry.create_business("acme", acme_config(), actor="test")
    if meta:
        registry.save_meta("acme", "106540352242922", "acme-token", "acme-secret", actor="test")
    registry.add_number("acme", "", actor="test")
    registry.assign_number("acme", "acme", actor="test")
    return registry
```

- [ ] **Step 2: Write the failing tests**

`tests/test_registry.py`:
```python
import json

import pytest

from app.config import Settings
from app.registry import Registry
from app.vault import Vault
from tests.fakes import acme_config, memory_registry, registry_with_acme


def test_a_new_business_becomes_an_engine_client():
    client = registry_with_acme().clients()["acme"]
    assert client.bot_name == "Sara" and client.waha_session == "acme"
    assert client.meta_phone_number_id == "106540352242922"
    assert client.meta_access_token == "acme-token" and client.meta_app_secret == "acme-secret"
    assert client.tabs["Orders"].owner_column == "Phone" and client.staff_numbers == {"923001111111"}
    assert len(client.meta_verify_token) >= 30


@pytest.mark.parametrize("business_id, change, message", [
    ("Sweet_Bakes", {}, "web id"),
    ("acme", {"timezone": "Mars/Base"}, "timezone"),
    ("acme", {"colour": "red"}, "Unknown settings"),
])
def test_invalid_businesses_are_refused(business_id, change, message):
    with pytest.raises(ValueError, match=message):
        memory_registry().create_business(business_id, {**acme_config(), **change}, actor="t")


def test_duplicate_business_ids_are_refused():
    with pytest.raises(ValueError, match="already exists"):
        registry_with_acme().create_business("acme", acme_config(), actor="t")


def test_saving_settings_merges_validates_and_audits_only_what_changed():
    registry = registry_with_acme()
    registry.save_config("acme", {"bot_name": "Zara", "business": "Sweet Bakes"}, actor="7")
    assert registry.clients()["acme"].bot_name == "Zara"
    entry = registry.audit_log("acme")[0]
    assert entry["action"] == "settings.save" and entry["actor"] == "7"
    assert json.loads(entry["detail"]) == {"bot_name": "Zara"}
    with pytest.raises(ValueError, match="timezone"):
        registry.save_config("acme", {"timezone": "Mars/Base"}, actor="7")
    assert registry.clients()["acme"].timezone == "Asia/Karachi"


def test_meta_keys_are_sealed_kept_when_blank_and_never_audited():
    registry = registry_with_acme()
    row = registry.db.one("SELECT * FROM businesses WHERE id = 'acme'")
    assert "acme-token" not in row["meta_access_token"] and "acme-secret" not in row["meta_app_secret"]
    registry.save_meta("acme", "106540352242922", "", "", actor="7")  # blank = keep what is saved
    business = registry.business("acme")
    assert business.has_meta_token and business.has_meta_secret and business.meta_token_hint == "oken"
    assert registry.clients()["acme"].meta_access_token == "acme-token"
    assert all("acme-token" not in e["detail"] and "acme-secret" not in e["detail"] for e in registry.audit_log())
    with pytest.raises(ValueError, match="digits"):
        registry.save_meta("acme", "not-a-number", "", "", actor="7")


def test_a_phone_number_id_belongs_to_one_business():
    registry = registry_with_acme()
    registry.create_business("other", acme_config(), actor="t")
    with pytest.raises(ValueError, match="Another business"):
        registry.save_meta("other", "106540352242922", "t", "s", actor="t")


def test_keys_sealed_with_another_secret_key_need_re_entering():
    registry = registry_with_acme()
    other = Registry(registry.db, Vault("a-different-key"))
    assert other.business("acme").keys_unreadable is True
    client = other.clients()["acme"]
    assert client.meta_access_token == "" and client.bot_name == "Sara"


def test_paused_businesses_leave_the_engine():
    registry = registry_with_acme()
    registry.set_active("acme", False, actor="7")
    assert "acme" not in registry.clients() and registry.business("acme").active is False
    registry.set_active("acme", True, actor="7")
    assert "acme" in registry.clients()
    assert [e["action"] for e in registry.audit_log("acme")][:2] == ["business.resume", "business.pause"]


def test_numbers_are_assigned_one_per_business_and_deleted_only_when_free():
    registry = registry_with_acme()
    registry.add_number("spare-1", "Jazz SIM, Rs 500", actor="7")
    registry.assign_number("spare-1", "acme", actor="7")  # moves acme off its old number
    assert registry.number("acme").business_id is None
    assert registry.clients()["acme"].waha_session == "spare-1"
    with pytest.raises(ValueError, match="Unassign"):
        registry.delete_number("spare-1", actor="7")
    registry.delete_number("acme", actor="7")
    assert [n.session for n in registry.numbers()] == ["spare-1"]
    registry.save_number_notes("spare-1", "Jazz SIM, renew 1 Nov", actor="7")
    assert registry.number("spare-1").notes == "Jazz SIM, renew 1 Nov"
    with pytest.raises(ValueError, match="already exists"):
        registry.add_number("spare-1", "", actor="7")
    with pytest.raises(ValueError, match="session name"):
        registry.add_number("Bad Name", "", actor="7")


def test_clients_yaml_is_imported_with_the_env_meta_keys():
    registry = memory_registry()
    settings = Settings(meta_access_token="EAAG-pilot", meta_app_secret="pilot-secret", meta_verify_token="verify-me")
    assert registry.import_yaml("clients.example.yaml", settings) == 1
    client = registry.clients()["sweetbakes"]
    assert client.waha_session == "sweetbakes" and client.meta_phone_number_id == "106540352242922"
    assert client.meta_access_token == "EAAG-pilot" and client.meta_verify_token == "verify-me"
    assert client.tabs["Orders"].fill == {"Name": "name", "Phone": "phone"}
    assert registry.audit_log("sweetbakes")[-1]["action"] == "business.import"


def test_an_invalid_clients_yaml_imports_nothing(tmp_path):
    path = tmp_path / "clients.yaml"
    path.write_text("clients:\n  good:\n    business: B\n    bot_name: S\n    sheet_id: s\n"
                    "  bad:\n    business: B\n    bot_name: S\n    sheet_id: s\n    timezone: Mars/Base\n",
                    encoding="utf-8")
    registry = memory_registry()
    with pytest.raises(ValueError, match="timezone"):
        registry.import_yaml(str(path), Settings())
    assert registry.is_empty()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.registry'`

- [ ] **Step 4: Implement the registry**

`app/registry.py`:
```python
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
"""
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{1,30}[a-z0-9]")
CONFIG_KEYS = frozenset({"business", "bot_name", "sheet_id", "timezone", "date_format", "instructions",
                         "knowledge_tab", "handoff_tab", "staff_chats", "staff_numbers", "staff_alert_chat",
                         "retention_days", "tabs"})
SELECT_BUSINESS = "SELECT b.*, n.session FROM businesses b LEFT JOIN numbers n ON n.business_id = b.id"


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
        return Business(id=row["id"], config=json.loads(row["config"]),
                        meta_phone_number_id=row["meta_phone_number_id"], has_meta_token=bool(token),
                        has_meta_secret=bool(secret), meta_token_hint=(token or "")[-4:],
                        meta_verify_token=row["meta_verify_token"], active=bool(row["active"]),
                        number=row["session"], keys_unreadable=token is None or secret is None)

    def businesses(self) -> list[Business]:
        return [self._business(r) for r in self.db.all(SELECT_BUSINESS + " ORDER BY b.id")]

    def business(self, business_id: str | None) -> Business | None:
        row = self.db.one(SELECT_BUSINESS + " WHERE b.id = ?", (business_id,))
        return self._business(row) if row else None

    def clients(self) -> dict[str, Client]:
        """Every active business as the engine's Client, with its Meta keys opened."""
        out = {}
        for row in self.db.all(SELECT_BUSINESS + " WHERE b.active = 1"):
            raw = {**json.loads(row["config"]), "meta_phone_number_id": row["meta_phone_number_id"],
                   "waha_session": row["session"]}
            try:
                client = client_from_dict(row["id"], raw)
            except ValueError:
                log.exception("business_config_invalid business=%s", row["id"])
                continue
            out[client.id] = replace(client, meta_access_token=self._open(row["meta_access_token"]) or "",
                                     meta_app_secret=self._open(row["meta_app_secret"]) or "",
                                     meta_verify_token=row["meta_verify_token"])
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
        for business_id, entry in entries.items():  # check everything before writing anything
            if not SLUG.fullmatch(business_id):
                raise ValueError(f"Rename {business_id!r} in clients.yaml: web ids are 3-32 lowercase letters, "
                                 "digits or dashes.")
            unknown = set(entry) - CONFIG_KEYS - {"meta_phone_number_id", "waha_session"}
            if unknown:
                raise ValueError(f"{business_id}: unknown settings {', '.join(sorted(unknown))}")
            client_from_dict(business_id, entry)
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_registry.py -v`
Expected: PASS (13 passed)

Run: `uv run pytest -q && uv run ruff check .`
Expected: all tests pass; `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add app/registry.py tests/fakes.py tests/test_registry.py
git commit -m "feat: registry of businesses, numbers and the audit log"
```

### Task 4: Per-business Meta tokens and WAHA session management

**Files:**
- Modify: `app/whatsapp.py`, `app/bot.py`, `tests/fakes.py`, `tests/test_bot.py`
- Test: `tests/test_whatsapp_manage.py`

**Interfaces:**
- Consumes: `Settings` (Task 2), `Client.meta_access_token` (Task 2).
- Produces:
  - `MetaClient.send_text(phone_number_id, to, text, reply_to=None, token=None)` and `MetaClient.download(media_id, token=None)`: use `token`, else the `.env` token.
  - `MetaClient.number_info(phone_number_id, token=None) -> dict` (Meta's `display_phone_number`, `verified_name`); raises `SendError("meta status=... code=... <Meta's message>")`.
  - `WahaClient.create_session(name, webhook_url, webhook_secret)`, `start(name)`, `logout(name)`, `delete(name)`, `session_info(name) -> dict`, `qr_png(name) -> bytes`, `groups(name) -> list[{"id", "name"}]` (only `@g.us` ids, sorted by name, case-insensitive). All raise `SendError` when WAHA fails (`"waha status=<code>"`) or is unreachable (`"waha unreachable: <Type>"`). `status(name)` keeps returning `"UNREACHABLE"` instead of raising.
  - `app.whatsapp.session_phone(info: dict) -> str`: digits of `info["me"]["id"]`, `""` until linked.
  - `Bot` passes the business's own Meta token to replies and Meta voice downloads.
  - `tests.fakes.FakeMeta`: `tokens: list` (the token of every send and download), `info: dict | Exception` (returned or raised by `number_info`).
  - `tests.fakes.FakeWaha`: `created: list[(name, url, secret)]`, `calls: list[(action, name)]` for `create/start/logout/delete/qr`, `phones: dict[name, jid]`, `group_list: dict[name, list]`, `manage_fail: Exception | None`; `session_info` raises `SendError("waha status=404")` for a session not in `statuses`.

- [ ] **Step 1: Update the fakes**

In `tests/fakes.py`, change the line `from app.whatsapp import Incoming` to:
```python
from app.whatsapp import Incoming, SendError
```

Replace the whole `FakeMeta` class with:
```python
class FakeMeta:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str | None]] = []
        self.audio: dict[str, bytes] = {}
        self.fail: Exception | None = None
        self.tokens: list[str | None] = []  # the token of every send and download
        self.info: dict | Exception = {"display_phone_number": "+1 555 0100", "verified_name": "Sweet Bakes"}

    def send_text(self, phone_number_id: str, to: str, text: str, reply_to: str | None = None,
                  token: str | None = None) -> str:
        if self.fail:
            raise self.fail
        self.tokens.append(token)
        self.sent.append((to, text, reply_to))
        return f"wamid.out-{len(self.sent)}"

    def download(self, media_id: str, token: str | None = None) -> bytes:
        self.tokens.append(token)
        return self.audio[media_id]

    def number_info(self, phone_number_id: str, token: str | None = None) -> dict:
        if isinstance(self.info, Exception):
            raise self.info
        return self.info
```

Replace the whole `FakeWaha` class with:
```python
class FakeWaha:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str | None]] = []
        self.audio: dict[str, bytes] = {}
        self.statuses: dict[str, str] = {}
        self.fail: Exception | None = None
        self.created: list[tuple[str, str, str]] = []  # sessions the dashboard created: (name, url, secret)
        self.calls: list[tuple[str, str]] = []  # (action, session) for create/start/logout/delete/qr
        self.phones: dict[str, str] = {}  # session -> linked jid, reported once WORKING
        self.group_list: dict[str, list[dict]] = {}
        self.manage_fail: Exception | None = None

    def send_text(self, session: str, chat_id: str, text: str, reply_to: str | None = None) -> str:
        if self.fail:
            raise self.fail
        self.sent.append((chat_id, text, reply_to))
        return f"waha-{len(self.sent)}"

    def download(self, url: str) -> bytes:
        return self.audio[url]

    def status(self, session: str) -> str:
        return self.statuses.get(session, "WORKING")

    def _manage(self, action: str, name: str) -> None:
        if self.manage_fail:
            raise self.manage_fail
        self.calls.append((action, name))

    def create_session(self, name: str, webhook_url: str, webhook_secret: str) -> None:
        self._manage("create", name)
        self.created.append((name, webhook_url, webhook_secret))
        self.statuses[name] = "SCAN_QR_CODE"

    def start(self, name: str) -> None:
        self._manage("start", name)
        self.statuses[name] = "SCAN_QR_CODE"

    def logout(self, name: str) -> None:
        self._manage("logout", name)
        self.statuses[name] = "STOPPED"

    def delete(self, name: str) -> None:
        self._manage("delete", name)
        self.statuses.pop(name, None)

    def session_info(self, name: str) -> dict:
        if self.manage_fail:
            raise self.manage_fail
        if name not in self.statuses:
            raise SendError("waha status=404")
        info: dict = {"name": name, "status": self.statuses[name]}
        if name in self.phones:
            info["me"] = {"id": self.phones[name]}
        return info

    def qr_png(self, name: str) -> bytes:
        self._manage("qr", name)
        return b"\x89PNG fake qr"

    def groups(self, name: str) -> list[dict]:
        if self.manage_fail:
            raise self.manage_fail
        return self.group_list.get(name, [])
```

- [ ] **Step 2: Write the failing tests**

`tests/test_whatsapp_manage.py`:
```python
import json

import httpx
import pytest

from app.config import Settings
from app.whatsapp import MetaClient, SendError, WahaClient, session_phone

SETTINGS = Settings(meta_access_token="env-token", waha_url="http://waha:3000", waha_api_key="wkey")


def mock(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_meta_uses_the_businesss_own_token_else_the_env_token():
    seen = []

    def handler(request):
        seen.append(request.headers["authorization"])
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": "wamid.1"}]})
        if request.url.path == "/v26.0/media-1":
            return httpx.Response(200, json={"url": "https://lookaside.fbsbx.com/m"})
        return httpx.Response(200, content=b"OggS")

    meta = MetaClient(SETTINGS, mock(handler))
    meta.send_text("1", "923001234567", "hi", token="biz-token")
    meta.send_text("1", "923001234567", "hi")
    meta.download("media-1", token="biz-token")
    assert seen == ["Bearer biz-token", "Bearer env-token", "Bearer biz-token", "Bearer biz-token"]


def test_meta_number_info_for_test_connection():
    def handler(request):
        assert request.url.params["fields"] == "display_phone_number,verified_name"
        if request.headers["authorization"] == "Bearer good":
            return httpx.Response(200, json={"display_phone_number": "+1 555 0100", "verified_name": "Sweet Bakes"})
        return httpx.Response(401, json={"error": {"code": 190, "message": "Error validating access token"}})

    meta = MetaClient(SETTINGS, mock(handler))
    assert meta.number_info("106540352242922", "good")["verified_name"] == "Sweet Bakes"
    with pytest.raises(SendError, match="code=190 Error validating access token"):
        meta.number_info("106540352242922", "expired")


def test_waha_session_management_calls():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path, request.headers["x-api-key"]))
        if request.url.path == "/api/sessions" and request.method == "POST":
            assert json.loads(request.content) == {"name": "shop-1", "start": True, "config": {"webhooks": [{
                "url": "http://engine:8000/webhooks/waha", "events": ["message", "group.v2.join"],
                "hmac": {"key": "hook-secret"}}]}}
            return httpx.Response(201, json={"name": "shop-1"})
        if request.url.path == "/api/sessions/shop-1" and request.method == "GET":
            return httpx.Response(200, json={"name": "shop-1", "status": "WORKING",
                                             "me": {"id": "923330000000@c.us", "pushName": "Sara"}})
        if request.url.path == "/api/shop-1/auth/qr":
            assert request.url.params["format"] == "image"
            return httpx.Response(200, content=b"\x89PNG")
        return httpx.Response(200, json={})

    waha = WahaClient(SETTINGS, mock(handler))
    waha.create_session("shop-1", "http://engine:8000/webhooks/waha", "hook-secret")
    waha.start("shop-1")
    waha.logout("shop-1")
    waha.delete("shop-1")
    assert session_phone(waha.session_info("shop-1")) == "923330000000"
    assert waha.status("shop-1") == "WORKING" and waha.qr_png("shop-1") == b"\x89PNG"
    assert [(method, path) for method, path, _ in calls[:4]] == [
        ("POST", "/api/sessions"), ("POST", "/api/sessions/shop-1/start"), ("POST", "/api/sessions/shop-1/logout"),
        ("DELETE", "/api/sessions/shop-1")]
    assert {key for _, _, key in calls} == {"wkey"}
    assert session_phone({"status": "SCAN_QR_CODE"}) == ""


def test_waha_groups_are_normalised_from_every_engine_shape():
    def handler(request):
        return httpx.Response(200, json=[
            {"JID": "120363001@g.us", "Name": "Bakery team"},  # GOWS
            {"id": "120363002@g.us", "subject": "cake fans"},  # NOWEB
            {"id": {"_serialized": "120363003@g.us"}, "name": "Delivery riders"},  # WEBJS
            {"id": "923001234567@c.us", "name": "not a group"},
            "junk",
        ])

    assert WahaClient(SETTINGS, mock(handler)).groups("shop-1") == [
        {"id": "120363001@g.us", "name": "Bakery team"},
        {"id": "120363002@g.us", "name": "cake fans"},
        {"id": "120363003@g.us", "name": "Delivery riders"},
    ]


def test_waha_groups_accept_an_object_keyed_by_id():
    def handler(request):
        return httpx.Response(200, json={"120363009@g.us": {"id": "120363009@g.us", "subject": "Staff"}})

    assert WahaClient(SETTINGS, mock(handler)).groups("shop-1") == [{"id": "120363009@g.us", "name": "Staff"}]


def test_waha_management_failures_raise_senderror():
    def down(request):
        raise httpx.ConnectError("refused")

    waha = WahaClient(SETTINGS, mock(down))
    with pytest.raises(SendError, match="unreachable"):
        waha.create_session("shop-1", "u", "s")
    assert waha.status("shop-1") == "UNREACHABLE"
    missing = WahaClient(SETTINGS, mock(lambda request: httpx.Response(404)))
    with pytest.raises(SendError, match="404"):
        missing.session_info("nope")
```

In `tests/test_bot.py`, add this line at the top of the import block:
```python
from dataclasses import replace
```

Append to `tests/test_bot.py`:
```python
def test_replies_and_voice_downloads_use_the_businesss_own_meta_token():
    bot, _ = make_bot(say("Chocolate cake is Rs 2500."), transcript="price of chocolate cake?")
    bot.clients["acme"] = replace(bot.clients["acme"], meta_access_token="biz-token")
    bot.meta.audio["voice-1"] = b"OggS"
    bot.handle(incoming("", kind="audio", audio="voice-1"))
    assert bot.meta.tokens == ["biz-token", "biz-token"]  # the download, then the reply
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_whatsapp_manage.py tests/test_bot.py -v`
Expected: FAIL with `ImportError: cannot import name 'session_phone' from 'app.whatsapp'` (and the new bot test failing on `tokens`)

- [ ] **Step 4: Implement**

In `app/whatsapp.py`, add this function right after `_meta_error_code`:
```python
def _meta_error_message(response: httpx.Response) -> str:
    try:
        return str((response.json().get("error") or {}).get("message", ""))[:200]
    except ValueError:
        return ""
```

Replace the whole `MetaClient` class with:
```python
class MetaClient:
    def __init__(self, settings: Settings, http: httpx.Client, sleep: Callable[[float], None] = time.sleep) -> None:
        self._http = http
        self._sleep = sleep
        self._base = f"https://graph.facebook.com/{settings.meta_graph_version}"
        self._token = settings.meta_access_token  # the .env token, for a business without keys of its own

    def _headers(self, token: str | None) -> dict[str, str]:
        return {"Authorization": f"Bearer {token or self._token}"}

    def send_text(self, phone_number_id: str, to: str, text: str, reply_to: str | None = None,
                  token: str | None = None) -> str | None:
        body: dict = {"messaging_product": "whatsapp", "recipient_type": "individual", "type": "text",
                      "text": {"body": text}}
        body["to" if to.isdigit() else "recipient"] = to  # username users only have a BSUID
        if reply_to:
            body["context"] = {"message_id": reply_to}
        url, headers = f"{self._base}/{phone_number_id}/messages", self._headers(token)
        try:
            r = self._http.post(url, json=body, headers=headers)
            if r.status_code == 429 or (r.status_code >= 400 and _meta_error_code(r) == 130429):
                self._sleep(2)
                r = self._http.post(url, json=body, headers=headers)
        except httpx.HTTPError as e:
            raise SendError(f"meta unreachable: {type(e).__name__}") from e
        if r.status_code >= 400:
            raise SendError(f"meta status={r.status_code} code={_meta_error_code(r)}")
        try:
            return ((r.json().get("messages") or [{}])[0]).get("id")
        except ValueError:
            return None  # sent, but a non-JSON 2xx body means the provider's id is unknown

    def download(self, media_id: str, token: str | None = None) -> bytes:
        headers = self._headers(token)
        info = self._http.get(f"{self._base}/{media_id}", headers=headers)
        info.raise_for_status()
        media = self._http.get(info.json()["url"], headers=headers)  # the URL expires after 5 minutes
        media.raise_for_status()
        return media.content

    def number_info(self, phone_number_id: str, token: str | None = None) -> dict:
        """What Meta says about a number, for "Test connection"; raises SendError carrying Meta's reason."""
        try:
            r = self._http.get(f"{self._base}/{phone_number_id}", headers=self._headers(token),
                               params={"fields": "display_phone_number,verified_name"})
        except httpx.HTTPError as e:
            raise SendError(f"meta unreachable: {type(e).__name__}") from e
        if r.status_code >= 400:
            raise SendError(f"meta status={r.status_code} code={_meta_error_code(r)} {_meta_error_message(r)}")
        return r.json()
```

Replace the whole `WahaClient` class with:
```python
class WahaClient:
    def __init__(self, settings: Settings, http: httpx.Client) -> None:
        self._http = http
        self._base = settings.waha_url.rstrip("/")
        self._auth = {"X-Api-Key": settings.waha_api_key}

    def _call(self, method: str, path: str, headers: dict | None = None, **kwargs) -> httpx.Response:
        try:
            r = self._http.request(method, f"{self._base}{path}", headers={**self._auth, **(headers or {})},
                                   **kwargs)
        except httpx.HTTPError as e:
            raise SendError(f"waha unreachable: {type(e).__name__}") from e
        if r.status_code >= 400:
            raise SendError(f"waha status={r.status_code}")
        return r

    def send_text(self, session: str, chat_id: str, text: str, reply_to: str | None = None) -> str | None:
        body = {"session": session, "chatId": chat_id, "text": text}
        if reply_to:
            body["reply_to"] = reply_to
        r = self._call("POST", "/api/sendText", json=body)
        try:
            return _waha_id(r.json())
        except ValueError:
            return None  # sent, but a non-JSON 2xx body means the provider's id is unknown

    def download(self, url: str) -> bytes:
        r = self._http.get(url, headers=self._auth)
        r.raise_for_status()
        return r.content

    def status(self, session: str) -> str:
        try:
            return str(self.session_info(session).get("status", "UNKNOWN"))
        except (SendError, ValueError):
            return "UNREACHABLE"

    def session_info(self, name: str) -> dict:
        return self._call("GET", f"/api/sessions/{name}").json()

    def create_session(self, name: str, webhook_url: str, webhook_secret: str) -> None:
        """A new session for a purchased number, posting its messages and group joins to the engine."""
        webhook = {"url": webhook_url, "events": ["message", "group.v2.join"], "hmac": {"key": webhook_secret}}
        self._call("POST", "/api/sessions", json={"name": name, "start": True, "config": {"webhooks": [webhook]}})

    def start(self, name: str) -> None:
        self._call("POST", f"/api/sessions/{name}/start")

    def logout(self, name: str) -> None:
        self._call("POST", f"/api/sessions/{name}/logout")

    def delete(self, name: str) -> None:
        self._call("DELETE", f"/api/sessions/{name}")

    def qr_png(self, name: str) -> bytes:
        return self._call("GET", f"/api/{name}/auth/qr", params={"format": "image"},
                          headers={"Accept": "image/png"}).content

    def groups(self, name: str) -> list[dict]:
        """The groups this number is in, as [{"id": "...@g.us", "name": "..."}], whatever the engine's shape."""
        data = self._call("GET", f"/api/{name}/groups").json()
        found = []
        for group in (data.values() if isinstance(data, dict) else data) or []:
            if not isinstance(group, dict):
                continue
            group_id = _jid(group.get("id") or group.get("JID") or "")
            if group_id.endswith("@g.us"):
                name_ = group.get("subject") or group.get("name") or group.get("Name") or group_id
                found.append({"id": group_id, "name": str(name_)})
        return sorted(found, key=lambda g: g["name"].lower())


def session_phone(info: dict) -> str:
    """The linked number's digits from WAHA's session info ('' until linked)."""
    return digits(_user((info.get("me") or {}).get("id")))
```

In `app/bot.py`, in `Bot.handle`, replace:
```python
                m.audio_bytes = self.meta.download(m.audio) if m.channel == "meta" else self.waha.download(m.audio)
```
with:
```python
                if m.channel == "meta":
                    client = self.clients.get(m.client_id)
                    token = client.meta_access_token if client else ""
                    m.audio_bytes = self.meta.download(m.audio, token=token or None)
                else:
                    m.audio_bytes = self.waha.download(m.audio)
```

In `Bot._deliver`, replace:
```python
                msg_id = self.meta.send_text(client.meta_phone_number_id, address, text)
```
with:
```python
                msg_id = self.meta.send_text(client.meta_phone_number_id, address, text,
                                             token=client.meta_access_token or None)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_whatsapp_manage.py tests/test_whatsapp_send.py tests/test_bot.py -v`
Expected: PASS (6 new tests in `test_whatsapp_manage.py`, the new bot test, and every existing test in those files)

Run: `uv run pytest -q && uv run ruff check .`
Expected: all tests pass; `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add app/whatsapp.py app/bot.py tests/fakes.py tests/test_bot.py tests/test_whatsapp_manage.py
git commit -m "feat: per-business Meta tokens and WAHA session management"
```

### Task 5: Chat history queries and Sheet helpers

**Files:**
- Modify: `app/store.py`, `app/sheets.py`, `tests/fakes.py`, `tests/test_store.py`, `tests/test_sheets.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `Store.conversations(client_id, limit=100) -> list[sqlite3.Row]` with keys `chat_id, channel, last_at, messages, name` (name = the latest human sender's name), newest first.
  - `Store.chat(client_id, chat_id, limit=200) -> list[sqlite3.Row]` with keys `sender_name, text, from_bot, created_at, channel`, oldest first; always filtered by `client_id`.
  - `Store.replies_since(client_id, since) -> dict` like `{"meta": 3, "waha": 5}` (bot messages per channel; both keys always present).
  - `Sheets.tab_headers(sheet_id) -> dict[str, list[str]]`: every tab title with its trimmed header row, in the Sheet's order.
  - `app.sheets.service_account_email(path) -> str` (`""` when the key file can't be read).
  - `app.sheets.sheet_error(error, email) -> str`: "No Sheet with that id, or it isn't shared with {email}." / "Share the Sheet with {email} as Editor." / "Tab '...' is not in the Sheet." / "Google Sheets couldn't be reached right now." (`email` falls back to "the service account").
  - `tests.fakes.FakeSheets.tab_headers(sheet_id)` and `FakeSheets.fail_tabs: Exception | None` (raised by `tab_headers` when set).

- [ ] **Step 1: Update the Sheets fake**

In `tests/fakes.py`, in `FakeSheets.__init__`, add after `self.fail_append = False`:
```python
        self.fail_tabs: Exception | None = None  # raised by tab_headers, like an unshared or deleted Sheet
```

Add this method to `FakeSheets`, after `headers`:
```python
    def tab_headers(self, sheet_id: str) -> dict[str, list[str]]:
        if self.fail_tabs:
            raise self.fail_tabs
        return {name: self.headers(sheet_id, name) for name in self.tabs}
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_store.py`:
```python
def test_conversations_and_chat_history_are_per_business():
    s = Store(":memory:")
    s.save_message("acme", "meta", "1", "user-ali", "user-ali", "Ali", "hi", False, 10.0)
    s.save_message("acme", "meta", "2", "user-ali", "bot", "Sara", "hello", True, 11.0)
    s.save_message("acme", "waha", "3", "g@g.us", "p1", "Bilal", "@Sara hi", False, 20.0)
    s.save_message("other", "meta", "4", "user-zed", "user-zed", "Zed", "psst", False, 30.0)
    rows = s.conversations("acme")
    assert [(r["chat_id"], r["channel"], r["messages"], r["name"], r["last_at"]) for r in rows] == [
        ("g@g.us", "waha", 1, "Bilal", 20.0), ("user-ali", "meta", 2, "Ali", 11.0)]
    assert [(r["sender_name"], r["text"], r["from_bot"]) for r in s.chat("acme", "user-ali")] == [
        ("Ali", "hi", 0), ("Sara", "hello", 1)]
    assert s.chat("acme", "user-zed") == []


def test_replies_since_counts_bot_messages_per_channel():
    s = Store(":memory:")
    s.save_message("acme", "meta", "1", "c", "bot", "Sara", "a", True, 100.0)
    s.save_message("acme", "waha", "2", "g", "bot", "Sara", "b", True, 100.0)
    s.save_message("acme", "waha", "3", "g", "bot", "Sara", "c", True, 10.0)
    s.save_message("acme", "meta", "4", "c", "u", "Ali", "d", False, 100.0)
    assert s.replies_since("acme", 50.0) == {"meta": 1, "waha": 1}
    assert s.replies_since("other", 0.0) == {"meta": 0, "waha": 0}
```

In `tests/test_sheets.py`, replace the import line `from app.sheets import Sheets` with:
```python
import gspread

from app.sheets import Sheets, service_account_email, sheet_error
```

In `tests/test_sheets.py`, replace the whole `FakeBook` class with:
```python
class FakeBook:
    def __init__(self, tabs):
        self.tabs = tabs
        for title, ws in tabs.items():
            ws.title = title

    def worksheet(self, tab):
        return self.tabs[tab]

    def worksheets(self):
        return list(self.tabs.values())
```

Append to `tests/test_sheets.py`:
```python
def test_tab_headers_list_every_tab_with_its_trimmed_header_row():
    sheets = Sheets(FakeGC({"Prices": FakeWorksheet([["Item ", "Price"]]), "Empty": FakeWorksheet([[]])}))
    assert sheets.tab_headers("s") == {"Prices": ["Item", "Price"], "Empty": []}


def test_service_account_email_and_friendly_sheet_errors(tmp_path):
    key = tmp_path / "key.json"
    key.write_text('{"client_email": "bot@proj.iam.gserviceaccount.com"}', encoding="utf-8")
    email = service_account_email(str(key))
    assert email == "bot@proj.iam.gserviceaccount.com"
    assert service_account_email(str(tmp_path / "missing.json")) == ""
    assert "isn't shared with bot@proj" in sheet_error(gspread.exceptions.SpreadsheetNotFound(), email)

    class Forbidden(Exception):
        code = 403

    assert sheet_error(Forbidden(), email) == "Share the Sheet with bot@proj.iam.gserviceaccount.com as Editor."
    assert sheet_error(gspread.exceptions.WorksheetNotFound("Orders"), email) == "Tab 'Orders' is not in the Sheet."
    assert "couldn't be reached" in sheet_error(RuntimeError("down"), "")
    assert "the service account" in sheet_error(gspread.exceptions.SpreadsheetNotFound(), "")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_store.py tests/test_sheets.py -v`
Expected: FAIL with `ImportError: cannot import name 'service_account_email' from 'app.sheets'` (and `AttributeError` for the new `Store` methods)

- [ ] **Step 4: Implement**

Append to the `Store` class in `app/store.py` (after `writable`):
```python
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
```

In `app/sheets.py`, replace the import block with:
```python
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

import gspread
```

Add this method to the `Sheets` class (after `knowledge`):
```python
    def tab_headers(self, sheet_id: str) -> dict[str, list[str]]:
        """Every tab's title with its trimmed header row, in the Sheet's order ("Check access")."""
        book = self._gc.open_by_key(sheet_id)
        return {ws.title: [str(h).strip() for h in ws.row_values(1)] for ws in book.worksheets()}
```

Append to `app/sheets.py`:
```python
def service_account_email(path: str) -> str:
    """The address businesses share their Sheet with ('' when the key file can't be read)."""
    try:
        return str(json.loads(Path(path).read_text(encoding="utf-8")).get("client_email", ""))
    except (OSError, ValueError):
        return ""


def sheet_error(error: Exception, email: str) -> str:
    """A Google Sheets failure as one sentence telling the person what to do."""
    who = email or "the service account"
    code = getattr(error, "code", None) or getattr(getattr(error, "response", None), "status_code", None)
    if isinstance(error, gspread.exceptions.SpreadsheetNotFound) or code == 404:
        return f"No Sheet with that id, or it isn't shared with {who}."
    if code == 403:
        return f"Share the Sheet with {who} as Editor."
    if isinstance(error, gspread.exceptions.WorksheetNotFound):
        return f"Tab {str(error)!r} is not in the Sheet."
    return "Google Sheets couldn't be reached right now."
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_store.py tests/test_sheets.py -v`
Expected: PASS (the 4 new tests and every existing test in those files)

Run: `uv run pytest -q && uv run ruff check .`
Expected: all tests pass; `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add app/store.py app/sheets.py tests/fakes.py tests/test_store.py tests/test_sheets.py
git commit -m "feat: chat history queries and Sheet access helpers"
```

### Task 6: Engine wiring: settings from the registry, live reload, per-business Meta webhooks

**Files:**
- Modify: `app/main.py`, `tests/test_api.py`
- Test: `tests/test_webhooks_business.py`

**Interfaces:**
- Consumes: `Registry`, `Db`, `Vault` (Tasks 1, 3); `Settings.secret_key` (Task 2); `Client` Meta fields (Task 2); `tests.fakes.memory_registry`, `registry_with_acme`, `acme_config` (Task 3).
- Produces:
  - `app.main.build_bot(settings, clients: dict[str, Client]) -> Bot`.
  - `app.main.open_registry(settings) -> Registry`: opens the dashboard database; on the first start (empty `businesses` table) with `CLIENTS_FILE` present as a file, imports it once.
  - `app.main.create_app(settings=None, bot=None, registry=None) -> FastAPI`: raises `RuntimeError` mentioning `SECRET_KEY` when it is empty. `app.state.settings`, `app.state.registry`, `app.state.bot`, and `app.state.reload()` (sets `bot.clients = registry.clients()`).
  - Routes `GET/POST /webhooks/meta/{business_id}`: that business's verify token and app secret; only that business's own phone number id is accepted; an unknown business → 404; a paused business's POST → 200 with nothing queued.
  - The v1 `GET/POST /webhooks/meta` keep using the `.env` token and secret, and route only to businesses with no app secret of their own or whose app secret equals `META_APP_SECRET`.
  - Webhook and `/health` lookups are built from `bot.clients` on every request.

- [ ] **Step 1: Update the v1 API tests for the new `create_app`**

In `tests/test_api.py`, replace:
```python
from tests.fakes import FakeWaha, make_bot, make_client, say
```
with:
```python
from tests.fakes import FakeWaha, make_bot, make_client, memory_registry, say
```

Replace the `SETTINGS = ...` line with:
```python
SETTINGS = Settings(secret_key="test-secret", meta_app_secret="app-secret", meta_verify_token="verify-me",
                    waha_webhook_secret="hook-secret")
```

In `http_and_bot`, replace `return TestClient(create_app(SETTINGS, bot)), bot` with:
```python
    return TestClient(create_app(SETTINGS, bot, registry=memory_registry())), bot
```

In `test_end_to_end_meta_webhook_produces_a_reply`, replace `http = TestClient(create_app(SETTINGS, bot))` with:
```python
    http = TestClient(create_app(SETTINGS, bot, registry=memory_registry()))
```

- [ ] **Step 2: Write the failing tests**

`tests/test_webhooks_business.py`:
```python
import hashlib
import hmac
import json
import shutil

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app, open_registry
from tests.fakes import acme_config, registry_with_acme
from tests.payloads import META_PNID, meta_text

SETTINGS = Settings(secret_key="test-secret", meta_app_secret="env-secret", meta_verify_token="env-verify")


class Recorder:
    """Stands in for the bot: remembers what the webhooks queued."""

    def __init__(self, clients) -> None:
        self.clients = clients
        self.handled = []

    def handle(self, m) -> None:
        self.handled.append(m)


def signed(body: bytes, secret: str) -> dict:
    return {"X-Hub-Signature-256": "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest(),
            "Content-Type": "application/json"}


def site():
    registry = registry_with_acme()
    bot = Recorder(registry.clients())
    return TestClient(create_app(SETTINGS, bot, registry=registry)), bot, registry


def test_the_app_refuses_to_start_without_a_secret_key():
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app(Settings(), Recorder({}), registry=registry_with_acme())


def test_each_business_answers_metas_handshake_with_its_own_verify_token():
    http, bot, _ = site()
    token = bot.clients["acme"].meta_verify_token
    ok = http.get("/webhooks/meta/acme", params={"hub.mode": "subscribe", "hub.verify_token": token,
                                                 "hub.challenge": "42"})
    assert ok.status_code == 200 and ok.text == "42"
    wrong = http.get("/webhooks/meta/acme", params={"hub.mode": "subscribe", "hub.verify_token": "env-verify",
                                                    "hub.challenge": "42"})
    assert wrong.status_code == 403
    assert http.get("/webhooks/meta/nope", params={"hub.mode": "subscribe", "hub.verify_token": token}).status_code == 403


def test_a_business_webhook_checks_its_own_app_secret_and_only_its_own_number():
    http, bot, registry = site()
    body = json.dumps(meta_text()).encode()  # addressed to acme's number, META_PNID
    assert http.post("/webhooks/meta/acme", content=body, headers=signed(body, "env-secret")).status_code == 403
    assert http.post("/webhooks/meta/acme", content=body, headers=signed(body, "acme-secret")).status_code == 200
    assert [m.client_id for m in bot.handled] == ["acme"]
    registry.create_business("other", {**acme_config(), "business": "Other Co"}, actor="t")
    registry.save_meta("other", "999000999", "other-token", "other-secret", actor="t")
    bot.clients = registry.clients()
    # Other's Meta app signs a message for acme's number: ignored, still a 200 so Meta stops retrying.
    assert http.post("/webhooks/meta/other", content=body, headers=signed(body, "other-secret")).status_code == 200
    assert len(bot.handled) == 1
    assert http.post("/webhooks/meta/nope", content=body, headers=signed(body, "acme-secret")).status_code == 404


def test_paused_businesses_get_a_200_and_nothing_is_queued():
    http, bot, registry = site()
    registry.set_active("acme", False, actor="t")
    bot.clients = registry.clients()
    body = json.dumps(meta_text()).encode()
    assert http.post("/webhooks/meta/acme", content=body, headers=signed(body, "acme-secret")).status_code == 200
    assert bot.handled == []


def test_the_v1_address_only_serves_businesses_on_the_env_meta_app():
    http, bot, registry = site()  # acme has an app secret of its own
    body = json.dumps(meta_text()).encode()
    assert http.post("/webhooks/meta", content=body, headers=signed(body, "env-secret")).status_code == 200
    assert bot.handled == []
    registry.save_meta("acme", META_PNID, "", "env-secret", actor="t")  # the pilot's keys came from .env
    bot.clients = registry.clients()
    http.post("/webhooks/meta", content=body, headers=signed(body, "env-secret"))
    assert [m.client_id for m in bot.handled] == ["acme"]


def test_reload_hands_saved_settings_to_the_bot():
    http, bot, registry = site()
    registry.save_config("acme", {"bot_name": "Zara"}, actor="t")
    assert bot.clients["acme"].bot_name == "Sara"
    http.app.state.reload()
    assert bot.clients["acme"].bot_name == "Zara"


def test_first_start_imports_clients_yaml_once(tmp_path):
    shutil.copy("clients.example.yaml", tmp_path / "clients.yaml")
    settings = Settings(secret_key="k", db_path=str(tmp_path / "a.db"), clients_file=str(tmp_path / "clients.yaml"),
                        meta_access_token="EAAG", meta_app_secret="s", meta_verify_token="v")
    assert "sweetbakes" in open_registry(settings).clients()
    (tmp_path / "clients.yaml").write_text("clients: {}\n", encoding="utf-8")
    assert "sweetbakes" in open_registry(settings).clients()  # the database is the source of truth now
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_webhooks_business.py tests/test_api.py -v`
Expected: FAIL with `ImportError: cannot import name 'open_registry' from 'app.main'` (and `TypeError: create_app() got an unexpected keyword argument 'registry'` in `test_api.py`)

- [ ] **Step 4: Implement**

In `app/main.py`, replace everything from the module docstring down to (not including) `def maintain(` with:
```python
"""HTTP entry points: Meta and WAHA webhooks, health, the dashboard, and the daily maintenance loop."""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from app.bot import Bot
from app.config import Client, Settings
from app.db import Db
from app.llm import LLM
from app.registry import Registry
from app.sheets import Sheets
from app.store import Store
from app.vault import Vault
from app.whatsapp import (GroupJoin, MetaClient, WahaClient, parse_meta, parse_waha, verify_meta_signature,
                          verify_waha_hmac)

log = logging.getLogger("app")
DAY = 86_400


def build_bot(settings: Settings, clients: dict[str, Client]) -> Bot:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if settings.log_hash_key == "change-me":
        log.warning("LOG_HASH_KEY is not set; hashed chat ids in the logs can be reversed")
    http = httpx.Client(timeout=30)
    return Bot(
        store=Store(settings.db_path),
        sheets=Sheets.from_service_account(settings.google_service_account_file),
        llm=LLM(settings),
        meta=MetaClient(settings, http),
        waha=WahaClient(settings, http),
        clients=clients,
        log_key=settings.log_hash_key,
    )


def open_registry(settings: Settings) -> Registry:
    """The dashboard's database; the very first start imports clients.yaml (the v1 settings) once."""
    registry = Registry(Db(settings.db_path), Vault(settings.secret_key))
    if Path(settings.clients_file).is_file():
        if registry.is_empty():
            count = registry.import_yaml(settings.clients_file, settings)
            log.info("imported %s business(es) from %s", count, settings.clients_file)
        else:
            log.info("clients.yaml is ignored: businesses are managed in the dashboard")
    return registry


```

Replace the whole `create_app` function with:
```python
def create_app(settings: Settings | None = None, bot: Bot | None = None,
               registry: Registry | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if not settings.secret_key:
        raise RuntimeError("Set SECRET_KEY in .env (make one with: openssl rand -hex 32), then restart.")
    registry = registry or open_registry(settings)
    bot = bot or build_bot(settings, registry.clients())

    def reload() -> None:
        """Hand freshly saved settings to the bot; its next message uses them."""
        bot.clients = registry.clients()

    def sessions() -> dict[str, Client]:
        return {c.waha_session: c for c in bot.clients.values() if c.waha_session}

    def env_app_phones() -> dict[str, Client]:
        """The v1 /webhooks/meta address serves only businesses on the .env Meta app."""
        return {c.meta_phone_number_id: c for c in bot.clients.values() if c.meta_phone_number_id
                and (not c.meta_app_secret or c.meta_app_secret == settings.meta_app_secret)}

    def queue_meta(body: bytes, phones: dict[str, Client], tasks: BackgroundTasks) -> Response:
        try:
            messages = parse_meta(json.loads(body), phones)
        except (ValueError, AttributeError, TypeError):
            log.warning("meta_webhook_unparsable")  # still a 200: the signature was valid
            messages = []
        for m in messages:
            tasks.add_task(bot.handle, m)  # Meta retries slow answers, so reply 200 first and work after
        return JSONResponse({"ok": True})

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async def daily() -> None:
            while True:
                try:
                    await asyncio.to_thread(maintain, bot, settings.backup_dir, time.time())
                except Exception:
                    log.exception("maintenance_failed")
                await asyncio.sleep(DAY)

        task = asyncio.create_task(daily())
        yield
        task.cancel()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings, app.state.registry, app.state.bot, app.state.reload = settings, registry, bot, reload

    @app.get("/webhooks/meta")
    def meta_verify(request: Request) -> Response:
        q = request.query_params
        if (q.get("hub.mode") == "subscribe" and settings.meta_verify_token
                and q.get("hub.verify_token") == settings.meta_verify_token):
            return PlainTextResponse(q.get("hub.challenge", ""))
        return Response(status_code=403)

    @app.post("/webhooks/meta")
    async def meta_webhook(request: Request, tasks: BackgroundTasks) -> Response:
        body = await request.body()
        if not verify_meta_signature(settings.meta_app_secret, body, request.headers.get("x-hub-signature-256")):
            return Response(status_code=403)
        return queue_meta(body, env_app_phones(), tasks)

    @app.get("/webhooks/meta/{business_id}")
    def business_meta_verify(business_id: str, request: Request) -> Response:
        client, q = bot.clients.get(business_id), request.query_params
        if (client and client.meta_verify_token and q.get("hub.mode") == "subscribe"
                and hmac.compare_digest(q.get("hub.verify_token", "").encode(), client.meta_verify_token.encode())):
            return PlainTextResponse(q.get("hub.challenge", ""))
        return Response(status_code=403)

    @app.post("/webhooks/meta/{business_id}")
    async def business_meta_webhook(business_id: str, request: Request, tasks: BackgroundTasks) -> Response:
        client = bot.clients.get(business_id)
        if client is None:  # a paused business still gets its 200, so Meta stops retrying
            return Response(status_code=200 if registry.business(business_id) else 404)
        body = await request.body()
        if not verify_meta_signature(client.meta_app_secret, body, request.headers.get("x-hub-signature-256")):
            return Response(status_code=403)
        # Only this business's own number: another business's Meta app can't inject messages through here.
        own = {client.meta_phone_number_id: client} if client.meta_phone_number_id else {}
        return queue_meta(body, own, tasks)

    @app.post("/webhooks/waha")
    async def waha_webhook(request: Request, tasks: BackgroundTasks) -> Response:
        body = await request.body()
        if not verify_waha_hmac(settings.waha_webhook_secret, body, request.headers):
            return Response(status_code=403)
        try:
            event = parse_waha(json.loads(body), sessions())
        except (ValueError, AttributeError, TypeError):
            log.warning("waha_webhook_unparsable")
            event = None
        if isinstance(event, GroupJoin):
            tasks.add_task(bot.greet, event.client_id, event.chat_id)
        elif event is not None:
            tasks.add_task(bot.handle, event)
        return JSONResponse({"ok": True})

    @app.get("/health")
    def health() -> JSONResponse:
        statuses = {name: bot.waha.status(name) for name in sessions()}
        ok = bot.store.writable() and all(status == "WORKING" for status in statuses.values())
        return JSONResponse({"ok": ok, "waha": statuses}, status_code=200 if ok else 503)

    return app
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_webhooks_business.py tests/test_api.py -v`
Expected: PASS (7 new tests and every existing API test)

Run: `uv run pytest -q && uv run ruff check .`
Expected: all tests pass; `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add app/main.py tests/test_api.py tests/test_webhooks_business.py
git commit -m "feat: business settings from the registry, live reload and per-business Meta webhooks"
```

### Task 7: Logins: users, invites, passwords, sessions, two-step codes

**Files:**
- Create: `app/auth.py`
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: `Db`, `Vault` (Task 1); the `businesses` table from `Registry` (Task 3), which `users.business_id` references.
- Produces (`app/auth.py`):
  - Constants `INVITE_TTL = 604800`, `ADMIN_SESSION_TTL = 43200`, `BUSINESS_SESSION_TTL = 604800`, `MIN_PASSWORD = 10`.
  - `AuthError(Exception)`: its text is shown to the person.
  - `User` (frozen dataclass): `id: int, email, name, role ("admin" | "business"), business_id: str | None, has_password: bool, has_totp: bool, disabled: bool`.
  - `Session` (frozen dataclass): `user: User, csrf: str, mfa_ok: bool`.
  - `hash_password(password) -> str`, `verify_password(password, stored | None) -> bool`.
  - `new_totp_secret() -> str` (base32), `totp(secret, at: float) -> str` (6 digits), `totp_ok(secret, code, at) -> bool` (±1 step), `totp_uri(secret, email) -> str` (`otpauth://totp/...`).
  - `Auth(db, vault, clock=time.time)`; attribute `db`. Methods: `users(business_id=None, role=None) -> list[User]`, `user(user_id) -> User | None`, `by_email(email) -> User | None`, `invite(email, name, role, business_id) -> str` (one-time token), `new_link(user_id, reset_totp=False) -> str` (old password stops working, all sessions end), `invited_user(token) -> User | None`, `accept_invite(token, password) -> User`, `login(email, password) -> (cookie_token, User)`, `session(cookie_token) -> Session | None`, `totp_setup_secret(cookie_token) -> str` (stable until confirmed), `pass_totp(cookie_token, code) -> bool` (raises `AuthError` after 5 wrong codes), `logout(cookie_token)`, `set_disabled(user_id, disabled)`.
  - Login rate limit: 5 wrong passwords for one email (case-insensitive) within 15 minutes pause it for 15 minutes ("Too many tries...").

- [ ] **Step 1: Write the failing tests**

`tests/test_auth.py`:
```python
import pytest

from app.auth import Auth, AuthError, hash_password, new_totp_secret, totp, totp_ok, verify_password
from tests.fakes import registry_with_acme

NOW = 1_790_000_000.0
RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # base32 of "12345678901234567890", RFC 6238's SHA-1 key
PASSWORD = "correct horse battery"


def make_auth():
    registry = registry_with_acme()
    clock = [NOW]
    return Auth(registry.db, registry.vault, clock=lambda: clock[0]), clock


def test_passwords_are_salted_scrypt_hashes():
    stored = hash_password(PASSWORD)
    assert stored.startswith("scrypt$16384$8$1$") and "horse" not in stored
    assert stored != hash_password(PASSWORD)
    assert verify_password(PASSWORD, stored) and not verify_password("wrong", stored)
    assert not verify_password("anything", None) and not verify_password("anything", "garbage")


@pytest.mark.parametrize("at, code", [(59, "287082"), (1111111109, "081804"), (1111111111, "050471"),
                                      (1234567890, "005924"), (2000000000, "279037")])
def test_totp_matches_rfc_6238(at, code):
    assert totp(RFC_SECRET, at) == code


def test_totp_allows_one_step_of_clock_drift():
    secret = new_totp_secret()
    assert totp_ok(secret, totp(secret, NOW - 30), NOW) and totp_ok(secret, totp(secret, NOW + 30), NOW)
    assert not totp_ok(secret, totp(secret, NOW - 90), NOW)


def test_invite_accept_login_and_session():
    auth, clock = make_auth()
    token = auth.invite("Owner@SweetBakes.pk", "Owner", "business", "acme")
    assert auth.invited_user(token).email == "Owner@SweetBakes.pk"
    with pytest.raises(AuthError, match="10 characters"):
        auth.accept_invite(token, "short")
    auth.accept_invite(token, PASSWORD)
    with pytest.raises(AuthError, match="expired or was already used"):
        auth.accept_invite(token, PASSWORD)
    cookie, user = auth.login("owner@sweetbakes.pk", PASSWORD)  # emails match whatever the case
    session = auth.session(cookie)
    assert user.business_id == "acme" and session.mfa_ok is True and len(session.csrf) > 20
    clock[0] += 7 * 86_400
    assert auth.session(cookie) is None


def test_invites_expire_after_seven_days():
    auth, clock = make_auth()
    token = auth.invite("late@example.com", "", "business", "acme")
    clock[0] += 7 * 86_400 + 1
    assert auth.invited_user(token) is None


def test_bad_invites_are_refused():
    auth, _ = make_auth()
    auth.invite("a@example.com", "", "admin", None)
    with pytest.raises(AuthError, match="already has a login"):
        auth.invite("A@example.com", "", "admin", None)
    with pytest.raises(AuthError, match="needs a business"):
        auth.invite("b@example.com", "", "business", None)
    with pytest.raises(AuthError, match="No such business"):
        auth.invite("c@example.com", "", "business", "nope")
    with pytest.raises(AuthError, match="valid email"):
        auth.invite("not-an-email", "", "admin", None)


def test_five_wrong_passwords_pause_the_email_for_15_minutes():
    auth, clock = make_auth()
    auth.accept_invite(auth.invite("a@example.com", "", "admin", None), PASSWORD)
    for _ in range(5):
        with pytest.raises(AuthError, match="Wrong email or password"):
            auth.login("a@example.com", "nope")
    with pytest.raises(AuthError, match="Too many tries"):
        auth.login("A@example.com", PASSWORD)
    clock[0] += 15 * 60 + 1
    assert auth.login("a@example.com", PASSWORD)[1].role == "admin"


def test_admin_sessions_need_the_second_step_and_last_12_hours():
    auth, clock = make_auth()
    auth.accept_invite(auth.invite("a@example.com", "", "admin", None), PASSWORD)
    cookie, _ = auth.login("a@example.com", PASSWORD)
    assert auth.session(cookie).mfa_ok is False
    secret = auth.totp_setup_secret(cookie)
    assert auth.totp_setup_secret(cookie) == secret  # stable until confirmed
    assert auth.pass_totp(cookie, "000000") is False
    assert auth.pass_totp(cookie, totp(secret, NOW)) is True
    assert auth.session(cookie).mfa_ok is True and auth.by_email("a@example.com").has_totp
    stored = auth.db.one("SELECT totp_secret FROM users WHERE email = 'a@example.com'")["totp_secret"]
    assert secret not in stored  # sealed
    clock[0] += 12 * 3600
    assert auth.session(cookie) is None
    second, _ = auth.login("a@example.com", PASSWORD)
    assert auth.pass_totp(second, totp(secret, clock[0])) is True  # the saved secret, not a new one


def test_wrong_codes_are_rate_limited():
    auth, _ = make_auth()
    auth.accept_invite(auth.invite("a@example.com", "", "admin", None), PASSWORD)
    cookie, _ = auth.login("a@example.com", PASSWORD)
    auth.totp_setup_secret(cookie)
    for _ in range(5):
        assert auth.pass_totp(cookie, "000000") is False
    with pytest.raises(AuthError, match="Too many wrong codes"):
        auth.pass_totp(cookie, "000000")


def test_new_links_and_disabling_end_every_session():
    auth, _ = make_auth()
    auth.accept_invite(auth.invite("o@example.com", "", "business", "acme"), PASSWORD)
    cookie, user = auth.login("o@example.com", PASSWORD)
    auth.set_disabled(user.id, True)
    assert auth.session(cookie) is None
    with pytest.raises(AuthError, match="Wrong email or password"):
        auth.login("o@example.com", PASSWORD)
    auth.set_disabled(user.id, False)
    cookie, _ = auth.login("o@example.com", PASSWORD)
    link = auth.new_link(user.id)
    assert auth.session(cookie) is None and auth.invited_user(link).id == user.id
    with pytest.raises(AuthError):
        auth.login("o@example.com", PASSWORD)  # the old password stopped working


def test_logout_ends_the_session():
    auth, _ = make_auth()
    auth.accept_invite(auth.invite("o@example.com", "", "business", "acme"), PASSWORD)
    cookie, _ = auth.login("o@example.com", PASSWORD)
    auth.logout(cookie)
    assert auth.session(cookie) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.auth'`

- [ ] **Step 3: Implement**

`app/auth.py`:
```python
"""Dashboard logins: users, invite links, passwords, sessions, two-step codes (TOTP) and a login rate limit."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import sqlite3
import struct
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from urllib.parse import quote

from app.db import Db
from app.vault import Vault

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  name TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL CHECK (role IN ('admin', 'business')),
  business_id TEXT REFERENCES businesses(id),
  password_hash TEXT,
  totp_secret TEXT,
  invite_hash TEXT,
  invite_expires REAL,
  disabled INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  CHECK ((role = 'admin') = (business_id IS NULL))
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  csrf TEXT NOT NULL,
  mfa_ok INTEGER NOT NULL DEFAULT 0,
  totp_pending TEXT,
  expires_at REAL NOT NULL
);
"""
INVITE_TTL = 7 * 86_400
ADMIN_SESSION_TTL = 12 * 3600
BUSINESS_SESSION_TTL = 7 * 86_400
MIN_PASSWORD = 10
MAX_FAILURES, PAUSE = 5, 15 * 60
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1


class AuthError(Exception):
    """Shown to the person: wrong password, expired link, too many tries, ..."""


@dataclass(frozen=True)
class User:
    id: int
    email: str
    name: str
    role: str  # "admin" or "business"
    business_id: str | None
    has_password: bool
    has_totp: bool
    disabled: bool


@dataclass(frozen=True)
class Session:
    user: User
    csrf: str
    mfa_ok: bool


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    try:
        _, n, r, p, salt, digest = (stored or "").split("$")
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32)
    except ValueError:
        return False
    return hmac.compare_digest(got.hex(), digest)


def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp(secret: str, at: float) -> str:
    """RFC 6238 with SHA-1, 30-second steps and 6 digits, as authenticator apps expect."""
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    mac = hmac.new(key, struct.pack(">Q", int(at // 30)), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    return f"{(struct.unpack('>I', mac[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


def totp_ok(secret: str, code: str, at: float) -> bool:
    code = code.replace(" ", "").strip()
    return any(hmac.compare_digest(totp(secret, at + drift * 30), code) for drift in (-1, 0, 1))


def totp_uri(secret: str, email: str) -> str:
    return f"otpauth://totp/{quote('WhatsApp Assistant:' + email)}?secret={secret}&issuer=WhatsApp%20Assistant"


class RateLimit:
    """MAX_FAILURES failures within PAUSE seconds pause a key for PAUSE seconds (in memory)."""

    def __init__(self) -> None:
        self._failures: defaultdict[str, deque[float]] = defaultdict(deque)
        self._until: dict[str, float] = {}

    def blocked(self, key: str, now: float) -> bool:
        return self._until.get(key, 0.0) > now

    def fail(self, key: str, now: float) -> None:
        failures = self._failures[key]
        failures.append(now)
        while failures and failures[0] <= now - PAUSE:
            failures.popleft()
        if len(failures) >= MAX_FAILURES:
            self._until[key] = now + PAUSE
            failures.clear()

    def clear(self, key: str) -> None:
        self._failures.pop(key, None)
        self._until.pop(key, None)


class Auth:
    def __init__(self, db: Db, vault: Vault, clock=time.time) -> None:
        self.db, self.vault, self.clock = db, vault, clock
        self.limits = RateLimit()
        db.script(SCHEMA)

    @staticmethod
    def _user(row: sqlite3.Row) -> User:
        return User(id=row["id"], email=row["email"], name=row["name"], role=row["role"],
                    business_id=row["business_id"], has_password=bool(row["password_hash"]),
                    has_totp=bool(row["totp_secret"]), disabled=bool(row["disabled"]))

    def users(self, business_id: str | None = None, role: str | None = None) -> list[User]:
        sql, args = "SELECT * FROM users WHERE 1 = 1", []
        if business_id is not None:
            sql += " AND business_id = ?"
            args.append(business_id)
        if role is not None:
            sql += " AND role = ?"
            args.append(role)
        return [self._user(r) for r in self.db.all(sql + " ORDER BY email", tuple(args))]

    def user(self, user_id: int) -> User | None:
        row = self.db.one("SELECT * FROM users WHERE id = ?", (user_id,))
        return self._user(row) if row else None

    def by_email(self, email: str) -> User | None:
        row = self.db.one("SELECT * FROM users WHERE email = ?", (email.strip(),))
        return self._user(row) if row else None

    def invite(self, email: str, name: str, role: str, business_id: str | None) -> str:
        """Create a login and return its one-time invite token, for {public_url}/invite/{token}."""
        email = email.strip()
        if "@" not in email or len(email) > 254:
            raise AuthError("Enter a valid email address.")
        if role not in ("admin", "business") or (role == "business") != bool(business_id):
            raise AuthError("A business login needs a business; an admin login must not have one.")
        token, now = secrets.token_urlsafe(32), self.clock()
        try:
            self.db.write("INSERT INTO users (email, name, role, business_id, invite_hash, invite_expires,"
                          " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                          (email, name.strip(), role, business_id or None, _sha(token), now + INVITE_TTL, now))
        except sqlite3.IntegrityError as e:
            if "FOREIGN KEY" in str(e):
                raise AuthError("No such business.") from None
            raise AuthError("That email already has a login.") from None
        return token

    def new_link(self, user_id: int, reset_totp: bool = False) -> str:
        """A fresh invite link: the old password stops working and every session ends."""
        token = secrets.token_urlsafe(32)
        with self.db.transaction():
            sql = "UPDATE users SET password_hash = NULL, invite_hash = ?, invite_expires = ?"
            if reset_totp:
                sql += ", totp_secret = NULL"
            if not self.db.write(sql + " WHERE id = ?", (_sha(token), self.clock() + INVITE_TTL, user_id)):
                raise AuthError("No such login.")
            self.db.write("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        return token

    def invited_user(self, token: str) -> User | None:
        row = self.db.one("SELECT * FROM users WHERE invite_hash = ? AND invite_expires > ? AND disabled = 0",
                          (_sha(token), self.clock()))
        return self._user(row) if row else None

    def accept_invite(self, token: str, password: str) -> User:
        if len(password) < MIN_PASSWORD:
            raise AuthError(f"Use at least {MIN_PASSWORD} characters.")
        user = self.invited_user(token)
        if user is None:
            raise AuthError("This link has expired or was already used. Ask for a new one.")
        self.db.write("UPDATE users SET password_hash = ?, invite_hash = NULL, invite_expires = NULL WHERE id = ?",
                      (hash_password(password), user.id))
        return user

    def login(self, email: str, password: str) -> tuple[str, User]:
        key, now = f"login:{email.strip().lower()}", self.clock()
        if self.limits.blocked(key, now):
            raise AuthError("Too many tries. Wait 15 minutes and try again.")
        row = self.db.one("SELECT * FROM users WHERE email = ? AND disabled = 0", (email.strip(),))
        if row is None or not verify_password(password, row["password_hash"]):
            self.limits.fail(key, now)
            raise AuthError("Wrong email or password.")
        self.limits.clear(key)
        user = self._user(row)
        token = secrets.token_urlsafe(32)
        ttl = ADMIN_SESSION_TTL if user.role == "admin" else BUSINESS_SESSION_TTL
        self.db.write("INSERT INTO sessions (token_hash, user_id, csrf, mfa_ok, expires_at) VALUES (?, ?, ?, ?, ?)",
                      (_sha(token), user.id, secrets.token_urlsafe(24), int(user.role != "admin"), now + ttl))
        return token, user

    def session(self, token: str) -> Session | None:
        row = self.db.one("SELECT s.csrf, s.mfa_ok, s.expires_at, u.* FROM sessions s JOIN users u ON u.id = s.user_id"
                          " WHERE s.token_hash = ?", (_sha(token),))
        if row is None:
            return None
        if row["expires_at"] <= self.clock() or row["disabled"]:
            self.db.write("DELETE FROM sessions WHERE token_hash = ?", (_sha(token),))
            return None
        return Session(user=self._user(row), csrf=row["csrf"], mfa_ok=bool(row["mfa_ok"]))

    def totp_setup_secret(self, token: str) -> str:
        """The secret to show during an admin's first two-step setup; kept with the session until confirmed."""
        row = self.db.one("SELECT totp_pending FROM sessions WHERE token_hash = ?", (_sha(token),))
        if row is None:
            raise AuthError("Your session ended. Log in again.")
        if row["totp_pending"]:
            return self.vault.open(row["totp_pending"])
        secret = new_totp_secret()
        self.db.write("UPDATE sessions SET totp_pending = ? WHERE token_hash = ?",
                      (self.vault.seal(secret), _sha(token)))
        return secret

    def pass_totp(self, token: str, code: str) -> bool:
        row = self.db.one("SELECT s.user_id, s.totp_pending, u.totp_secret FROM sessions s"
                          " JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?", (_sha(token),))
        if row is None:
            return False
        key, now = f"totp:{row['user_id']}", self.clock()
        if self.limits.blocked(key, now):
            raise AuthError("Too many wrong codes. Wait 15 minutes and try again.")
        sealed = row["totp_secret"] or row["totp_pending"]
        if not sealed or not totp_ok(self.vault.open(sealed), code, now):
            self.limits.fail(key, now)
            return False
        self.limits.clear(key)
        with self.db.transaction():
            if not row["totp_secret"]:
                self.db.write("UPDATE users SET totp_secret = ? WHERE id = ?", (row["totp_pending"], row["user_id"]))
            self.db.write("UPDATE sessions SET mfa_ok = 1, totp_pending = NULL WHERE token_hash = ?", (_sha(token),))
        return True

    def logout(self, token: str) -> None:
        self.db.write("DELETE FROM sessions WHERE token_hash = ?", (_sha(token),))

    def set_disabled(self, user_id: int, disabled: bool) -> None:
        with self.db.transaction():
            self.db.write("UPDATE users SET disabled = ? WHERE id = ?", (int(disabled), user_id))
            if disabled:
                self.db.write("DELETE FROM sessions WHERE user_id = ?", (user_id,))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_auth.py -v`
Expected: PASS (15 passed)

Run: `uv run pytest -q && uv run ruff check .`
Expected: all tests pass; `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add app/auth.py tests/test_auth.py
git commit -m "feat: dashboard logins with invites, sessions and two-step codes"
```

### Task 8: Web plumbing, sign-in pages and the admin command

**Files:**
- Create: `app/web.py`, `app/cli.py`, `app/templates/base.html`, `app/templates/login.html`, `app/templates/totp.html`, `app/templates/invite.html`, `app/templates/message.html`, `app/static/pico.min.css` (downloaded), `app/static/app.css`, `tests/webkit.py`
- Modify: `app/main.py`
- Test: `tests/test_web_auth.py`

**Interfaces:**
- Consumes: `Auth`, `AuthError`, `Session`, `totp`, `totp_uri`, TTL constants (Task 7); `create_app` (Task 6); `tests.fakes.make_bot`, `registry_with_acme` (Tasks 3–4).
- Produces (`app/web.py`):
  - `COOKIE = "wa_session"`, `STATIC` (the static folder), `templates` (Jinja2, with a `localtime(timestamp, timezone)` filter), `router` (sign-in routes).
  - `Form` with `get(name, default="")` (stripped), `raw(name)` (as typed), `all(name) -> list[str]`, `has(name) -> bool`.
  - Dependencies: `any_session` (signed in, second step or not), `signed_in`, `admin_only`, `business_only`; each returns a `Session` or raises (303 to `/login` or `/login/totp`, or 403).
  - `route(router, path, scope, methods=("GET",))`: decorator registering `handler(request, ctx, form)`; `ctx` is what the `scope` dependency returns (a `Session`, or an object with `.session`); POST forms arrive parsed and CSRF-checked (403 otherwise); GET gets `form=None`; the handler runs in a worker thread.
  - `render(request, name, sess=None, status=200, **ctx) -> HTMLResponse` (adds `user`, `csrf`, `ok` from `?ok=<code>` via `OK_MESSAGES`, `error`), `redirect(url)` (303), `public_url(request) -> str`, `security_headers` (middleware), `http_error` (exception handler).
  - Routes: `GET /`, `GET/POST /login`, `GET/POST /login/totp`, `GET/POST /invite/{token}`, `POST /logout`.
- Produces (`app/cli.py`): `main(argv=None) -> int`: `create-admin EMAIL` and `admin-link EMAIL` print `{PUBLIC_URL}/invite/<token>` and return 0; unknown admin → 1; bad usage → 2.
- Produces (`app/main.py`): `create_app(settings=None, bot=None, registry=None, auth=None)`; `app.state.auth`; security headers on every response; `/static` mounted; the sign-in routes included.
- Produces (`tests/webkit.py`): `NOW`, `PASSWORD`, `SETTINGS`, `Site(registry=None, bot=None)` with `.registry`, `.auth`, `.bot`, `.app`, `browser()`, `business_user(email="owner@sweetbakes.pk", business_id="acme")`, `admin(email="admin@example.com")`; and `csrf(http, path) -> str`.

- [ ] **Step 1: Write the test helpers and the failing tests**

`tests/webkit.py`:
```python
"""Helpers for dashboard tests: an app with in-memory stores, and signed-in browsers."""
from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.auth import Auth, totp
from app.config import Settings
from app.main import create_app
from tests.fakes import make_bot, registry_with_acme

NOW = 1_790_000_000.0  # the fake bot's clock too
PASSWORD = "correct horse battery"
SETTINGS = Settings(secret_key="test-secret", public_url="https://bot.example.com", meta_app_secret="env-secret",
                    meta_verify_token="env-verify", waha_webhook_secret="hook-secret")


class Site:
    """One running dashboard over in-memory stores, with the acme bakery set up."""

    def __init__(self, registry=None, bot=None) -> None:
        self.registry = registry or registry_with_acme()
        self.auth = Auth(self.registry.db, self.registry.vault, clock=lambda: NOW)
        self.bot = bot or make_bot()[0]
        self.bot.clients = self.registry.clients()
        self.app = create_app(SETTINGS, self.bot, registry=self.registry, auth=self.auth)

    def browser(self) -> TestClient:
        return TestClient(self.app, base_url="https://testserver")

    def business_user(self, email: str = "owner@sweetbakes.pk", business_id: str = "acme") -> TestClient:
        self.auth.accept_invite(self.auth.invite(email, "Owner", "business", business_id), PASSWORD)
        http = self.browser()
        assert http.post("/login", data={"email": email, "password": PASSWORD},
                         follow_redirects=False).headers["location"] == "/app"
        return http

    def admin(self, email: str = "admin@example.com") -> TestClient:
        self.auth.accept_invite(self.auth.invite(email, "Admin", "admin", None), PASSWORD)
        http = self.browser()
        http.post("/login", data={"email": email, "password": PASSWORD}, follow_redirects=False)
        secret = re.search(r'id="totp-secret">([A-Z2-7]+)<', http.get("/login/totp").text).group(1)
        r = http.post("/login/totp", data={"csrf": csrf(http, "/login/totp"), "code": totp(secret, NOW)},
                      follow_redirects=False)
        assert r.headers["location"] == "/admin"
        return http


def csrf(http: TestClient, path: str) -> str:
    """The CSRF token printed in the forms of the page at `path`."""
    return re.search(r'name="csrf" value="([^"]+)"', http.get(path).text).group(1)
```

`tests/test_web_auth.py`:
```python
import re

from app.auth import Auth, totp
from app.cli import main as cli_main
from app.db import Db
from app.vault import Vault
from tests.webkit import NOW, PASSWORD, Site, csrf


def test_the_start_page_sends_people_to_the_right_place():
    site = Site()
    assert site.browser().get("/", follow_redirects=False).headers["location"] == "/login"
    assert site.business_user().get("/", follow_redirects=False).headers["location"] == "/app"


def test_login_page_and_security_headers():
    r = Site().browser().get("/login")
    assert r.status_code == 200 and 'name="password"' in r.text
    assert r.headers["x-frame-options"] == "DENY" and "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["referrer-policy"] == "same-origin"


def test_session_cookie_is_locked_down():
    site = Site()
    site.auth.accept_invite(site.auth.invite("o@example.com", "", "business", "acme"), PASSWORD)
    r = site.browser().post("/login", data={"email": "o@example.com", "password": PASSWORD}, follow_redirects=False)
    cookie = r.headers["set-cookie"].lower()
    assert r.headers["location"] == "/app"
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie and "max-age=604800" in cookie


def test_wrong_passwords_are_refused_then_paused():
    site = Site()
    site.auth.accept_invite(site.auth.invite("o@example.com", "", "business", "acme"), PASSWORD)
    http = site.browser()
    for _ in range(5):
        assert "Wrong email or password" in http.post("/login", data={"email": "o@example.com", "password": "x"}).text
    assert "Too many tries" in http.post("/login", data={"email": "o@example.com", "password": PASSWORD}).text


def test_invite_link_sets_a_password():
    site = Site()
    token = site.auth.invite("new@example.com", "New", "business", "acme")
    http = site.browser()
    assert "new@example.com" in http.get(f"/invite/{token}").text
    assert "don't match" in http.post(f"/invite/{token}", data={"password": PASSWORD, "confirm": "other one!!"}).text
    assert "Password set" in http.post(f"/invite/{token}", data={"password": PASSWORD, "confirm": PASSWORD}).text
    assert http.get(f"/invite/{token}").status_code == 404


def test_admins_set_up_and_pass_two_step_login():
    site = Site()
    site.auth.accept_invite(site.auth.invite("admin@example.com", "", "admin", None), PASSWORD)
    http = site.browser()
    r = http.post("/login", data={"email": "admin@example.com", "password": PASSWORD}, follow_redirects=False)
    assert r.headers["location"] == "/login/totp"
    page = http.get("/login/totp").text
    secret = re.search(r'id="totp-secret">([A-Z2-7]+)<', page).group(1)
    assert "otpauth://totp/" in page
    token = csrf(http, "/login/totp")
    assert "didn't match" in http.post("/login/totp", data={"csrf": token, "code": "000000"}).text
    r = http.post("/login/totp", data={"csrf": token, "code": totp(secret, NOW)}, follow_redirects=False)
    assert r.headers["location"] == "/admin"


def test_logout_needs_the_form_token_and_ends_the_session():
    site = Site()
    site.auth.accept_invite(site.auth.invite("admin@example.com", "", "admin", None), PASSWORD)
    http = site.browser()
    http.post("/login", data={"email": "admin@example.com", "password": PASSWORD})
    token = csrf(http, "/login/totp")
    assert http.post("/logout", data={}).status_code == 403
    assert http.post("/logout", data={"csrf": token}, follow_redirects=False).headers["location"] == "/login"
    assert http.get("/login/totp", follow_redirects=False).headers["location"] == "/login"


def test_create_admin_and_admin_link_print_working_invite_links(tmp_path, monkeypatch, capsys):
    db_path = str(tmp_path / "a.db")
    monkeypatch.setenv("DB_PATH", db_path)
    monkeypatch.setenv("SECRET_KEY", "cli-secret")
    monkeypatch.setenv("PUBLIC_URL", "https://bot.example.com")
    assert cli_main(["create-admin", "owner@example.com"]) == 0
    first = capsys.readouterr().out.strip()
    assert first.startswith("https://bot.example.com/invite/")
    assert cli_main(["admin-link", "owner@example.com"]) == 0
    second = capsys.readouterr().out.strip()
    auth = Auth(Db(db_path), Vault("cli-secret"))
    assert auth.invited_user(second.rsplit("/", 1)[1]).email == "owner@example.com"
    assert auth.invited_user(first.rsplit("/", 1)[1]) is None
    assert cli_main(["admin-link", "nobody@example.com"]) == 1
    assert cli_main(["bogus"]) == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_web_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.cli'` (and `create_app() got an unexpected keyword argument 'auth'`)

- [ ] **Step 3: Implement the web plumbing**

`app/web.py`:
```python
"""Dashboard plumbing: templates, who is signed in, forms and CSRF, security headers, and the sign-in pages."""
from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from app.auth import ADMIN_SESSION_TTL, BUSINESS_SESSION_TTL, AuthError, Session, totp_uri

log = logging.getLogger("web")
HERE = Path(__file__).parent
STATIC = HERE / "static"
COOKIE = "wa_session"
OK_MESSAGES = {
    "saved": "Saved.",
    "created": "Business created.",
    "password": "Password set. You can log in now.",
    "paused": "Business paused: the bot ignores its messages.",
    "resumed": "Business resumed.",
    "assigned": "Group number updated.",
    "deleted": "Number deleted.",
}
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; form-action 'self'",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
}
EXPIRED_LINK = "This link has expired or was already used. Ask for a new one."


def localtime(timestamp: float, timezone: str | None = None) -> str:
    return datetime.fromtimestamp(timestamp, ZoneInfo(timezone or "UTC")).strftime("%Y-%m-%d %H:%M")


templates = Jinja2Templates(directory=HERE / "templates")
templates.env.filters["localtime"] = localtime
router = APIRouter()


class Form:
    """A submitted application/x-www-form-urlencoded body."""

    def __init__(self, data: dict[str, list[str]]) -> None:
        self.data = data

    def get(self, name: str, default: str = "") -> str:
        values = self.data.get(name)
        return values[0].strip() if values else default

    def raw(self, name: str) -> str:
        """Exactly as typed: passwords and keys."""
        values = self.data.get(name)
        return values[0] if values else ""

    def all(self, name: str) -> list[str]:
        return [v.strip() for v in self.data.get(name, []) if v.strip()]

    def has(self, name: str) -> bool:
        return name in self.data


async def read_form(request: Request) -> Form:
    body = (await request.body()).decode("utf-8", errors="replace")
    return Form(parse_qs(body, keep_blank_values=True))


def session_of(request: Request) -> Session | None:
    token = request.cookies.get(COOKIE)
    return request.app.state.auth.session(token) if token else None


def any_session(request: Request) -> Session:
    """Signed in, with or without the second step (the two-step pages use this)."""
    sess = session_of(request)
    if sess is None:
        raise HTTPException(303, headers={"Location": "/login"})
    return sess


def signed_in(sess: Session = Depends(any_session)) -> Session:
    if not sess.mfa_ok:
        raise HTTPException(303, headers={"Location": "/login/totp"})
    return sess


def admin_only(sess: Session = Depends(signed_in)) -> Session:
    if sess.user.role != "admin":
        raise HTTPException(403, "This page is for admins.")
    return sess


def business_only(sess: Session = Depends(signed_in)) -> Session:
    if sess.user.role != "business":
        raise HTTPException(403, "This page is for business logins; admins use /admin.")
    return sess


async def posted(request: Request, sess: Session) -> Form:
    """The submitted form, after checking its CSRF token against the session's."""
    form = await read_form(request)
    if not hmac.compare_digest(form.get("csrf").encode(), sess.csrf.encode()):
        raise HTTPException(403, "This form has expired. Go back, reload the page and try again.")
    return form


def route(router: APIRouter, path: str, scope, methods: tuple[str, ...] = ("GET",)):
    """Register handler(request, ctx, form) at `path`.

    `scope` is a dependency returning the signed-in Session, or an object with a `.session`. The handler is a plain
    function run in a worker thread, because pages call Google Sheets and WAHA, which block. POST forms arrive parsed
    and CSRF-checked; GET requests get form=None.
    """
    def register(handler):
        async def endpoint(request: Request, ctx=Depends(scope)) -> Response:
            sess = ctx if isinstance(ctx, Session) else ctx.session
            form = await posted(request, sess) if request.method == "POST" else None
            return await run_in_threadpool(handler, request, ctx, form)

        endpoint.__name__ = handler.__name__
        router.add_api_route(path, endpoint, methods=list(methods))
        return handler
    return register


def render(request: Request, name: str, sess: Session | None = None, status: int = 200, **ctx) -> HTMLResponse:
    ctx.setdefault("ok", OK_MESSAGES.get(request.query_params.get("ok", ""), ""))
    ctx.setdefault("error", "")
    context = {"user": sess.user if sess else None, "csrf": sess.csrf if sess else "", **ctx}
    return templates.TemplateResponse(request, name, context, status_code=status)


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def public_url(request: Request) -> str:
    return request.app.state.settings.public_url.rstrip("/") or str(request.base_url).rstrip("/")


async def security_headers(request: Request, call_next) -> Response:
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response


async def http_error(request: Request, exc: HTTPException) -> Response:
    """Redirects from the sign-in checks, and friendly 403/404 pages."""
    if exc.status_code == 303 and exc.headers:
        return redirect(exc.headers["Location"])
    title = {403: "Not allowed", 404: "Not found"}.get(exc.status_code, "Something went wrong")
    return render(request, "message.html", status=exc.status_code, title=title, message=str(exc.detail))


def _email_hash(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:12]


def _totp_page(request: Request, sess: Session, error: str = "") -> HTMLResponse:
    secret = "" if sess.user.has_totp else request.app.state.auth.totp_setup_secret(request.cookies[COOKIE])
    return render(request, "totp.html", sess, title="Two-step login", secret=secret, error=error,
                  uri=totp_uri(secret, sess.user.email) if secret else "")


@router.get("/")
def start(request: Request) -> Response:
    sess = session_of(request)
    if sess is None:
        return redirect("/login")
    return redirect("/admin" if sess.user.role == "admin" else "/app")


@router.get("/login")
def login_page(request: Request) -> HTMLResponse:
    return render(request, "login.html", title="Log in", email="")


@router.post("/login")
async def login(request: Request) -> Response:
    form = await read_form(request)
    email = form.get("email")
    try:
        token, user = request.app.state.auth.login(email, form.raw("password"))
    except AuthError as e:
        log.warning("login_failed email=%s", _email_hash(email))
        return render(request, "login.html", title="Log in", email=email, error=str(e))
    response = redirect("/login/totp" if user.role == "admin" else "/app")
    ttl = ADMIN_SESSION_TTL if user.role == "admin" else BUSINESS_SESSION_TTL
    response.set_cookie(COOKIE, token, max_age=ttl, httponly=True, secure=True, samesite="lax")
    return response


@router.get("/login/totp")
def totp_page(request: Request, sess: Session = Depends(any_session)) -> Response:
    if sess.mfa_ok:
        return redirect("/admin" if sess.user.role == "admin" else "/app")
    return _totp_page(request, sess)


@router.post("/login/totp")
async def totp_check(request: Request, sess: Session = Depends(any_session)) -> Response:
    form = await posted(request, sess)
    try:
        passed = request.app.state.auth.pass_totp(request.cookies[COOKIE], form.get("code"))
    except AuthError as e:
        return _totp_page(request, sess, error=str(e))
    if passed:
        return redirect("/admin")
    return _totp_page(request, sess, error="That code didn't match. Check the time on your phone and try again.")


@router.get("/invite/{token}")
def invite_page(request: Request, token: str) -> HTMLResponse:
    user = request.app.state.auth.invited_user(token)
    if user is None:
        return render(request, "message.html", status=404, title="Link expired", message=EXPIRED_LINK)
    return render(request, "invite.html", title="Set your password", email=user.email)


@router.post("/invite/{token}")
async def invite_accept(request: Request, token: str) -> Response:
    form, auth = await read_form(request), request.app.state.auth
    user = auth.invited_user(token)
    if user is None:
        return render(request, "message.html", status=404, title="Link expired", message=EXPIRED_LINK)
    if form.raw("password") != form.raw("confirm"):
        return render(request, "invite.html", title="Set your password", email=user.email,
                      error="The two passwords don't match.")
    try:
        auth.accept_invite(token, form.raw("password"))
    except AuthError as e:
        return render(request, "invite.html", title="Set your password", email=user.email, error=str(e))
    return redirect("/login?ok=password")


@router.post("/logout")
async def logout(request: Request, sess: Session = Depends(any_session)) -> Response:
    await posted(request, sess)
    request.app.state.auth.logout(request.cookies[COOKIE])
    response = redirect("/login")
    response.delete_cookie(COOKIE, secure=True, httponly=True, samesite="lax")
    return response
```

- [ ] **Step 4: Add the page frame, the sign-in templates and the stylesheet**

Download Pico.css (MIT licensed; its licence header stays in the file):
```bash
curl -fsSL https://cdn.jsdelivr.net/npm/@picocss/pico@2.0.6/css/pico.min.css -o app/static/pico.min.css
```
Expected: `app/static/pico.min.css` exists, is larger than 50 KB, and `head -c 200 app/static/pico.min.css` shows `Pico CSS` and `v2.0.6`. If the download fails, stop and report it (don't substitute another file).

`app/static/app.css`:
```css
/* A few additions to Pico.css */
.notice { padding: 0.75rem 1rem; border-radius: 0.5rem; }
.notice.ok { background: #e7f6ec; color: #1b5e20; }
.notice.error { background: #fdecea; color: #b71c1c; }
form.inline { display: inline; margin: 0; }
form.inline button { width: auto; margin: 0 0.25rem 0 0; padding: 0.25rem 0.75rem; }
.badge { padding: 0.1rem 0.5rem; border-radius: 1rem; font-size: 0.85em; background: #eceff1; color: #263238; }
.badge.good { background: #e7f6ec; color: #1b5e20; }
.badge.bad { background: #fdecea; color: #b71c1c; }
img.qr { max-width: 280px; background: #fff; padding: 0.5rem; }
nav.tabs { flex-wrap: wrap; }
```

`app/templates/base.html`:
```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {% if refresh %}<meta http-equiv="refresh" content="{{ refresh }}">{% endif %}
  <title>{{ title }} · WhatsApp Assistant</title>
  <link rel="stylesheet" href="/static/pico.min.css">
  <link rel="stylesheet" href="/static/app.css">
</head>
<body>
<header class="container">
  <nav>
    <ul><li><strong>WhatsApp Assistant</strong></li></ul>
    {% if user %}
    <ul>
      {% if user.role == "admin" %}
      <li><a href="/admin">Businesses</a></li>
      <li><a href="/admin/numbers">Numbers</a></li>
      <li><a href="/admin/admins">Admins</a></li>
      {% endif %}
      <li>
        <form method="post" action="/logout" class="inline">
          <input type="hidden" name="csrf" value="{{ csrf }}">
          <button type="submit" class="secondary outline">Log out</button>
        </form>
      </li>
    </ul>
    {% endif %}
  </nav>
</header>
<main class="container">
  {% if business_nav %}{% include "_business_nav.html" %}{% endif %}
  {% if ok %}<p class="notice ok">{{ ok }}</p>{% endif %}
  {% if error %}<p class="notice error">{{ error }}</p>{% endif %}
  {% block content %}{% endblock %}
</main>
</body>
</html>
```

`app/templates/login.html`:
```html
{% extends "base.html" %}
{% block content %}
<article>
  <h1>Log in</h1>
  <form method="post" action="/login">
    <label>Email <input type="email" name="email" value="{{ email }}" required autofocus autocomplete="username"></label>
    <label>Password <input type="password" name="password" required autocomplete="current-password"></label>
    <button type="submit">Log in</button>
  </form>
</article>
{% endblock %}
```

`app/templates/totp.html`:
```html
{% extends "base.html" %}
{% block content %}
<article>
  <h1>Two-step login</h1>
  {% if secret %}
  <p>Admins need a 6-digit code from an authenticator app (Google Authenticator, Microsoft Authenticator, ...).
     Open the app, choose <em>Enter a setup key</em>, and type this key:</p>
  <p><code id="totp-secret">{{ secret }}</code></p>
  <p><small>Or open this link on the phone that has the app: <a href="{{ uri }}">{{ uri }}</a></small></p>
  {% else %}
  <p>Enter the 6-digit code from your authenticator app.</p>
  {% endif %}
  <form method="post" action="/login/totp">
    <input type="hidden" name="csrf" value="{{ csrf }}">
    <label>6-digit code <input name="code" inputmode="numeric" autocomplete="one-time-code" required autofocus></label>
    <button type="submit">Continue</button>
  </form>
</article>
{% endblock %}
```

`app/templates/invite.html`:
```html
{% extends "base.html" %}
{% block content %}
<article>
  <h1>Set your password</h1>
  <p>Login: <strong>{{ email }}</strong></p>
  <form method="post">
    <label>Password (at least 10 characters)
      <input type="password" name="password" required minlength="10" autocomplete="new-password"></label>
    <label>Password again
      <input type="password" name="confirm" required minlength="10" autocomplete="new-password"></label>
    <button type="submit">Save password</button>
  </form>
</article>
{% endblock %}
```

`app/templates/message.html`:
```html
{% extends "base.html" %}
{% block content %}
<article>
  <h1>{{ title }}</h1>
  <p>{{ message }}</p>
  <p><a href="/">Go to the start page</a></p>
</article>
{% endblock %}
```

- [ ] **Step 5: Add the admin command**

`app/cli.py`:
```python
"""Server commands for the dashboard.

  python -m app.cli create-admin EMAIL   create an admin login and print its invite link
  python -m app.cli admin-link EMAIL     print a fresh link for a locked-out admin (resets password and two-step)
"""
from __future__ import annotations

import sys

from app.auth import Auth, AuthError
from app.config import Settings
from app.db import Db
from app.registry import Registry
from app.vault import Vault


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[0] not in ("create-admin", "admin-link"):
        print(__doc__)
        return 2
    settings = Settings.from_env()
    if not settings.secret_key:
        print("Set SECRET_KEY in .env first (make one with: openssl rand -hex 32).")
        return 1
    db, vault = Db(settings.db_path), Vault(settings.secret_key)
    Registry(db, vault)  # creates the businesses table that logins refer to
    auth = Auth(db, vault)
    command, email = args
    try:
        if command == "create-admin":
            token = auth.invite(email, "", "admin", None)
        else:
            user = auth.by_email(email)
            if user is None or user.role != "admin":
                print(f"No admin login for {email}.")
                return 1
            token = auth.new_link(user.id, reset_totp=True)
    except AuthError as e:
        print(e)
        return 1
    print(f"{settings.public_url.rstrip('/') or 'https://<your-domain>'}/invite/{token}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Wire the dashboard into the app**

In `app/main.py`, change the FastAPI import line to:
```python
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
```
and add after it:
```python
from fastapi.staticfiles import StaticFiles
```
Add these imports to the `app.` import group (keep it alphabetical):
```python
from app import web
from app.auth import Auth
```

Change the `create_app` signature and its first lines to:
```python
def create_app(settings: Settings | None = None, bot: Bot | None = None, registry: Registry | None = None,
               auth: Auth | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if not settings.secret_key:
        raise RuntimeError("Set SECRET_KEY in .env (make one with: openssl rand -hex 32), then restart.")
    registry = registry or open_registry(settings)
    auth = auth or Auth(registry.db, registry.vault)
    bot = bot or build_bot(settings, registry.clients())
```

Right after the line `app.state.settings, app.state.registry, app.state.bot, app.state.reload = ...`, add:
```python
    app.state.auth = auth
    app.middleware("http")(web.security_headers)
    app.add_exception_handler(HTTPException, web.http_error)
    app.mount("/static", StaticFiles(directory=web.STATIC), name="static")
    app.include_router(web.router)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_web_auth.py -v`
Expected: PASS (8 passed)

Run: `uv run pytest -q && uv run ruff check .`
Expected: all tests pass; `All checks passed!`

- [ ] **Step 8: Commit**

```bash
git add app/web.py app/cli.py app/main.py app/templates/base.html app/templates/login.html app/templates/totp.html app/templates/invite.html app/templates/message.html app/static/pico.min.css app/static/app.css tests/webkit.py tests/test_web_auth.py
git commit -m "feat: dashboard sign-in pages, security headers and the create-admin command"
```

### Task 9: Business screens: home, bot settings, chats

**Files:**
- Create: `app/pages.py`, `app/templates/_business_nav.html`, `app/templates/business_home.html`, `app/templates/settings.html`, `app/templates/chats.html`, `app/templates/chat.html`
- Modify: `app/main.py`
- Test: `tests/test_pages.py`

**Interfaces:**
- Consumes: `route`, `render`, `redirect`, `Form`, `admin_only`, `business_only` (Task 8); `Session` (Task 7); `Registry.business`, `save_config` (Task 3); `Store.conversations`, `chat`, `replies_since` (Task 5); `app.state.reload` (Task 6); `tests.webkit.Site`, `csrf`, `NOW` (Task 8).
- Produces (`app/pages.py`):
  - `router`; `TIMEZONES` (sorted IANA names); `DATE_FORMATS` (`{"%d/%m/%Y": "15/06/2026", "%m/%d/%Y": "06/15/2026", "%Y-%m-%d": "2026-06-15", "%d-%m-%Y": "15-06-2026", "%d.%m.%Y": "15.06.2026"}`).
  - `Scope` (frozen dataclass): `session: Session, business: Business, base: str` (`"/app"` or `"/admin/b/<id>"`), property `is_admin`.
  - Dependencies `app_scope` (business login → its own business) and `admin_scope` (admin + `business_id` path parameter → 404 when unknown).
  - `screen(path, methods=("GET",))`: registers a `handler(request, scope, form)` at `/app{path}` and `/admin/b/{business_id}{path}`.
  - `page(request, scope, template, **ctx)`: renders with the business tabs on top.
  - `save(request, scope, changes)`: `registry.save_config` then `app.state.reload()`; raises `ValueError`.
  - `month_start(now, timezone) -> float`.
  - Screens: `""` (home), `/settings` (GET/POST), `/chats`, `/chat?id=<chat id>`.

- [ ] **Step 1: Write the failing tests**

`tests/test_pages.py`:
```python
from tests.fakes import acme_config
from tests.webkit import NOW, Site, csrf

SETTINGS_FORM = {"business": "Sweet Bakes", "bot_name": "Zara", "instructions": "Be brief.",
                 "timezone": "Asia/Karachi", "date_format": "%d/%m/%Y", "retention_days": "5"}


def test_signed_out_visitors_are_sent_to_login():
    r = Site().browser().get("/app/settings", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_business_home_shows_numbers_replies_and_handoffs():
    site = Site()
    store = site.bot.store
    store.save_message("acme", "meta", "b1", "user-1", "bot", "Sara", "hi", True, NOW - 60)
    store.save_message("acme", "waha", "b2", "g@g.us", "bot", "Sara", "hi", True, NOW - 60)
    store.save_message("acme", "waha", "b3", "g@g.us", "bot", "Sara", "old", True, NOW - 40 * 86_400)
    site.bot.sheets.tabs["Handoffs"].append({"Time": "2026-09-21 10:00", "Name": "Ali", "Phone": "923001234567",
                                             "Chat": "user-1", "Question": "wedding cake", "Reason": "custom"})
    page = site.business_user().get("/app").text
    assert "Sweet Bakes" in page and "wedding cake" in page and "WORKING" in page
    assert 'id="meta-replies">1<' in page and 'id="group-replies">1<' in page


def test_settings_save_reaches_the_bot_at_once_and_is_audited():
    site = Site()
    http = site.business_user()
    r = http.post("/app/settings", data={**SETTINGS_FORM, "csrf": csrf(http, "/app/settings")})
    assert "Saved." in r.text
    client = site.bot.clients["acme"]
    assert client.bot_name == "Zara" and client.instructions == "Be brief."
    assert client.retention_days == 90  # only admins change how long chats are kept
    assert site.registry.audit_log("acme")[0]["action"] == "settings.save"


def test_invalid_settings_are_refused_with_a_message():
    site = Site()
    http = site.business_user()
    token = csrf(http, "/app/settings")
    r = http.post("/app/settings", data={**SETTINGS_FORM, "timezone": "Mars/Base", "csrf": token})
    assert "unknown timezone" in r.text and site.bot.clients["acme"].bot_name == "Sara"
    r = http.post("/app/settings", data={**SETTINGS_FORM, "date_format": "%Q", "csrf": token})
    assert "Pick a date format" in r.text


def test_posts_without_the_form_token_are_refused():
    http = Site().business_user()
    assert http.post("/app/settings", data=SETTINGS_FORM).status_code == 403


def test_chats_stay_inside_the_business():
    site = Site()
    site.registry.create_business("other", {**acme_config(), "business": "Other Co"}, actor="t")
    store = site.bot.store
    store.save_message("acme", "meta", "m1", "user-ali", "user-ali", "Ali", "Do you deliver?", False, NOW - 30)
    store.save_message("acme", "meta", "m2", "user-ali", "bot", "Sara", "Yes, free above Rs 3000.", True, NOW - 20)
    store.save_message("other", "meta", "m3", "user-zed", "user-zed", "Zed", "secret order", False, NOW - 10)
    http = site.business_user()
    listing = http.get("/app/chats").text
    assert "Ali" in listing and "Zed" not in listing
    chat = http.get("/app/chat", params={"id": "user-ali"}).text
    assert "Do you deliver?" in chat and "free above Rs 3000" in chat
    assert http.get("/app/chat", params={"id": "user-zed"}).status_code == 404


def test_business_users_cannot_open_admin_screens_and_admins_can_open_any_business():
    site = Site()
    assert site.business_user().get("/admin/b/acme/settings").status_code == 403
    admin = site.admin()
    page = admin.get("/admin/b/acme/settings")
    assert page.status_code == 200 and "Keep chat history for" in page.text
    assert admin.get("/app/settings").status_code == 403
    assert admin.get("/admin/b/nope/settings").status_code == 404
    token = csrf(admin, "/admin/b/acme/settings")
    admin.post("/admin/b/acme/settings", data={**SETTINGS_FORM, "retention_days": "30", "csrf": token})
    assert site.bot.clients["acme"].retention_days == 30
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_pages.py -v`
Expected: FAIL (the `/app/...` routes don't exist yet: 404s and failed asserts)

- [ ] **Step 3: Implement the screens**

`app/pages.py`:
```python
"""Business screens, each written once and mounted twice: /app/... for a business login (the business comes from the
session) and /admin/b/{business_id}/... for admins."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, available_timezones

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from app.auth import Session
from app.registry import Business
from app.web import Form, admin_only, business_only, redirect, render, route

log = logging.getLogger("pages")
router = APIRouter()
TIMEZONES = sorted(available_timezones())
DATE_FORMATS = {"%d/%m/%Y": "15/06/2026", "%m/%d/%Y": "06/15/2026", "%Y-%m-%d": "2026-06-15",
                "%d-%m-%Y": "15-06-2026", "%d.%m.%Y": "15.06.2026"}


@dataclass(frozen=True)
class Scope:
    """The business a screen shows, who is looking, and the URL prefix for the screen's links."""
    session: Session
    business: Business
    base: str

    @property
    def is_admin(self) -> bool:
        return self.session.user.role == "admin"


def app_scope(request: Request, sess: Session = Depends(business_only)) -> Scope:
    business = request.app.state.registry.business(sess.user.business_id)
    if business is None:
        raise HTTPException(404, "This business no longer exists.")
    return Scope(sess, business, "/app")


def admin_scope(request: Request, business_id: str, sess: Session = Depends(admin_only)) -> Scope:
    business = request.app.state.registry.business(business_id)
    if business is None:
        raise HTTPException(404, "No such business.")
    return Scope(sess, business, f"/admin/b/{business_id}")


def screen(path: str, methods: tuple[str, ...] = ("GET",)):
    """Mount handler(request, scope, form) for business logins and for admins."""
    def register(handler):
        route(router, f"/app{path}", app_scope, methods)(handler)
        route(router, "/admin/b/{business_id}" + path, admin_scope, methods)(handler)
        return handler
    return register


def page(request: Request, scope: Scope, name: str, **ctx) -> Response:
    """Render a business screen with the business tabs on top."""
    return render(request, name, scope.session, business=scope.business, base=scope.base,
                  is_admin=scope.is_admin, business_nav=True, **ctx)


def save(request: Request, scope: Scope, changes: dict) -> None:
    """Validate and store setting changes, then hand them to the bot at once. Raises ValueError for the form."""
    request.app.state.registry.save_config(scope.business.id, changes, actor=str(scope.session.user.id))
    request.app.state.reload()


def month_start(now: float, timezone: str) -> float:
    local = datetime.fromtimestamp(now, ZoneInfo(timezone))
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()


@screen("")
def home(request: Request, scope: Scope, form: Form | None) -> Response:
    bot, business = request.app.state.bot, scope.business
    config = business.config
    handoffs, handoff_error = [], ""
    try:
        handoffs = bot.sheets.rows(config["sheet_id"], config.get("handoff_tab") or "Handoffs")[-10:][::-1]
    except Exception:
        log.exception("handoffs_unreadable business=%s", business.id)
        handoff_error = "Couldn't read the Handoffs tab."
    return page(request, scope, "business_home.html", title=config["business"],
                group_status=bot.waha.status(business.number) if business.number else "not linked",
                replies=bot.store.replies_since(business.id, month_start(bot.clock(), config.get("timezone") or "UTC")),
                handoffs=handoffs, handoff_error=handoff_error)


@screen("/settings", ("GET", "POST"))
def settings_page(request: Request, scope: Scope, form: Form | None) -> Response:
    config, error = scope.business.config, ""
    if form is not None:
        changes = {"business": form.get("business"), "bot_name": form.get("bot_name"),
                   "instructions": form.get("instructions"), "timezone": form.get("timezone"),
                   "date_format": form.get("date_format") or None}
        if scope.is_admin:
            retention = form.get("retention_days") or "90"
            changes["retention_days"] = int(retention) if retention.isdigit() else retention
        if changes["date_format"] is not None and changes["date_format"] not in DATE_FORMATS:
            error = "Pick a date format from the list."
        else:
            try:
                save(request, scope, changes)
            except ValueError as e:
                error = str(e)
            else:
                return redirect(f"{scope.base}/settings?ok=saved")
        config = {**config, **changes}
    return page(request, scope, "settings.html", title="Bot settings", config=config, error=error,
                timezones=TIMEZONES, date_formats=DATE_FORMATS)


@screen("/chats")
def chats_page(request: Request, scope: Scope, form: Form | None) -> Response:
    return page(request, scope, "chats.html", title="Chats",
                chats=request.app.state.bot.store.conversations(scope.business.id))


@screen("/chat")
def chat_page(request: Request, scope: Scope, form: Form | None) -> Response:
    chat_id = request.query_params.get("id", "")
    messages = request.app.state.bot.store.chat(scope.business.id, chat_id)  # always within this business
    if not messages:
        raise HTTPException(404, "No such chat.")
    return page(request, scope, "chat.html", title="Chat", chat_id=chat_id, messages=messages)
```

- [ ] **Step 4: Add the templates**

`app/templates/_business_nav.html`:
```html
<nav class="tabs">
  <ul>
    <li><strong>{{ business.config.business }}</strong>{% if not business.active %} <span class="badge bad">paused</span>{% endif %}</li>
  </ul>
  <ul>
    <li><a href="{{ base }}">Home</a></li>
    <li><a href="{{ base }}/settings">Bot settings</a></li>
    <li><a href="{{ base }}/staff">Staff &amp; groups</a></li>
    <li><a href="{{ base }}/sheet">Sheet</a></li>
    <li><a href="{{ base }}/chats">Chats</a></li>
  </ul>
</nav>
```

`app/templates/business_home.html`:
```html
{% extends "base.html" %}
{% block content %}
{% if not business.active %}<p class="notice error">This business is paused: the bot is not answering anyone.</p>{% endif %}
<div class="grid">
  <article>
    <h3>Official number</h3>
    <p>{% if business.meta_phone_number_id and business.has_meta_token %}Connected (ID {{ business.meta_phone_number_id }}){% else %}Not set up yet{% endif %}</p>
    <p>Replies this month: <strong id="meta-replies">{{ replies.meta }}</strong><br>
       <small>Meta charges for replies after 1,000 a month.</small></p>
  </article>
  <article>
    <h3>Group number</h3>
    <p><span class="badge {{ 'good' if group_status == 'WORKING' else 'bad' }}">{{ group_status }}</span></p>
    <p>Replies this month: <strong id="group-replies">{{ replies.waha }}</strong></p>
  </article>
</div>
<h2>Latest requests for a human</h2>
{% if handoff_error %}<p class="notice error">{{ handoff_error }}</p>
{% elif not handoffs %}<p>None yet.</p>
{% else %}
<table>
  <thead><tr><th>Time</th><th>Name</th><th>Phone</th><th>Question</th><th>Reason</th></tr></thead>
  <tbody>
  {% for h in handoffs %}
    <tr><td>{{ h.Time }}</td><td>{{ h.Name }}</td><td>{{ h.Phone }}</td><td>{{ h.Question }}</td><td>{{ h.Reason }}</td></tr>
  {% endfor %}
  </tbody>
</table>
{% endif %}
{% endblock %}
```

`app/templates/settings.html`:
```html
{% extends "base.html" %}
{% block content %}
<h1>Bot settings</h1>
<form method="post">
  <input type="hidden" name="csrf" value="{{ csrf }}">
  <label>Business name <input name="business" value="{{ config.business }}" required></label>
  <label>Bot name <input name="bot_name" value="{{ config.bot_name }}" required></label>
  <label>Instructions for the bot
    <textarea name="instructions" rows="6">{{ config.instructions or '' }}</textarea>
    <small>Tone, opening hours, delivery rules... The bot also reads your Knowledge tab.</small>
  </label>
  <label>Time zone
    <select name="timezone">
      {% for tz in timezones %}<option value="{{ tz }}"{% if tz == (config.timezone or 'UTC') %} selected{% endif %}>{{ tz }}</option>{% endfor %}
    </select>
  </label>
  <label>How dates are typed into your Sheet by hand
    <select name="date_format">
      <option value="">Only like 2026-06-15</option>
      {% for fmt, example in date_formats.items() %}<option value="{{ fmt }}"{% if fmt == config.date_format %} selected{% endif %}>{{ example }} → read as 2026-06-15</option>{% endfor %}
    </select>
  </label>
  {% if is_admin %}
  <label>Keep chat history for (days)
    <input type="number" name="retention_days" min="1" max="3650" value="{{ config.retention_days or 90 }}"></label>
  {% endif %}
  <button type="submit">Save</button>
</form>
{% endblock %}
```

`app/templates/chats.html`:
```html
{% extends "base.html" %}
{% block content %}
<h1>Chats</h1>
{% if not chats %}<p>No conversations yet.</p>{% else %}
<table>
  <thead><tr><th>Who</th><th>Where</th><th>Last message</th><th>Messages</th></tr></thead>
  <tbody>
  {% for c in chats %}
    <tr>
      <td><a href="{{ base }}/chat?id={{ c.chat_id|urlencode }}">{% if c.chat_id.endswith('@g.us') %}Group {{ c.chat_id[:10] }}...{% else %}{{ c.name or c.chat_id }}{% endif %}</a></td>
      <td>{% if c.chat_id.endswith('@g.us') %}Group{% elif c.channel == 'meta' %}Official number{% else %}Group number, private chat{% endif %}</td>
      <td>{{ c.last_at|localtime(business.config.timezone) }}</td>
      <td>{{ c.messages }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
{% endif %}
{% endblock %}
```

`app/templates/chat.html`:
```html
{% extends "base.html" %}
{% block content %}
<p><a href="{{ base }}/chats">← All chats</a></p>
<h1>Chat</h1>
{% for m in messages %}
<article>
  <header><strong>{{ m.sender_name or ('Bot' if m.from_bot else 'Customer') }}</strong>
    <small>{{ m.created_at|localtime(business.config.timezone) }}</small></header>
  <p>{{ m.text or '(voice note or media)' }}</p>
</article>
{% endfor %}
{% endblock %}
```

- [ ] **Step 5: Mount the screens**

In `app/main.py`, add to the `app.` import group:
```python
from app import pages
```
and right after `app.include_router(web.router)`, add:
```python
    app.include_router(pages.router)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_pages.py -v`
Expected: PASS (7 passed)

Run: `uv run pytest -q && uv run ruff check .`
Expected: all tests pass; `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add app/pages.py app/main.py app/templates/_business_nav.html app/templates/business_home.html app/templates/settings.html app/templates/chats.html app/templates/chat.html tests/test_pages.py
git commit -m "feat: business dashboard home, bot settings and chat viewer"
```

### Task 10: Business screens: staff and groups, Sheet permissions with guardrails

**Files:**
- Create: `app/sheet_rules.py`, `app/templates/staff.html`, `app/templates/sheet.html`
- Modify: `app/pages.py`
- Test: `tests/test_sheet_rules.py`, `tests/test_pages_staff_sheet.py`

**Interfaces:**
- Consumes: `screen`, `page`, `save`, `Scope` (Task 9); `WahaClient.groups` via `bot.waha` and `SendError` (Task 4); `Sheets.tab_headers`, `service_account_email`, `sheet_error` (Task 5); `client_from_dict`, `digits` (Task 2); `Caller`, `lookup_rows` (v1 `app/tools.py`).
- Produces:
  - `app.sheet_rules.CONTACT_WORDS`, `sensitive_columns(headers) -> list[str]`, `tab_problems(tab, rule, headers, confirmed) -> list[str]`.
  - `app.pages.tabs_from_form(form, sheet_tabs) -> (tabs, problems)` and `app.pages.customer_preview(sheets, business_id, config, tab) -> {"tab", "error", "rows", "phone"}`.
  - Screens `/staff` (GET/POST) and `/sheet` (GET/POST; actions `save`, `preview:<tab>`, and `sheet_id` for admins only). The Sheet form carries a hidden `tabs_listed` field; a POST without it, or while the Sheet can't be read, saves nothing. Per-tab field names use the tab's position `i` in `tab_headers` order: `use{i}`, `read{i}`, `own{i}`, `owner{i}`, `append{i}`, `fill_name{i}`, `fill_phone{i}`, `confirm{i}`.

- [ ] **Step 1: Write the failing tests**

`tests/test_sheet_rules.py`:
```python
from app.sheet_rules import sensitive_columns, tab_problems

HEADERS = ["Date", "Item", "Qty", "Name", "Phone"]


def test_contact_columns_are_flagged():
    assert sensitive_columns(["Item", "Customer Phone", "Email", "CNIC no", "Price"]) == [
        "Customer Phone", "Email", "CNIC no"]
    assert sensitive_columns(["Item", "Price"]) == []


def test_tab_problems_explain_each_guardrail():
    ok = {"customer": ["own", "append"], "owner_column": "Phone", "fill": {"Name": "name", "Phone": "phone"}}
    assert tab_problems("Orders", ok, HEADERS, confirmed=False) == []
    assert "pick which column" in tab_problems("Orders", {"customer": ["own"], "owner_column": ""}, HEADERS, False)[0]
    assert "'Mobile' is not in the tab" in tab_problems(
        "Orders", {"customer": ["append"], "fill": {"Mobile": "phone"}}, HEADERS, False)[0]
    assert "every customer would see Phone" in tab_problems("Orders", {"customer": ["read"]}, HEADERS, False)[0]
    assert tab_problems("Orders", {"customer": ["read"]}, HEADERS, confirmed=True) == []
```

`tests/test_pages_staff_sheet.py`:
```python
import gspread

from app.whatsapp import SendError
from tests.fakes import registry_with_acme
from tests.webkit import Site, csrf


def indexes(site) -> dict[str, int]:
    """Each tab's position on the Sheet screen, which names its form fields (use0, read0, ...)."""
    return {tab: i for i, tab in enumerate(site.bot.sheets.tab_headers("sheet-1"))}


def test_staff_numbers_need_a_country_code_and_reach_the_bot():
    site = Site()
    http = site.business_user()
    token = csrf(http, "/app/staff")
    bad = http.post("/app/staff", data={"csrf": token, "staff_numbers": "+92 300 1111111\n0300 2222222"})
    assert "starting with +" in bad.text and site.bot.clients["acme"].staff_numbers == {"923001111111"}
    ok = http.post("/app/staff", data={"csrf": token, "staff_numbers": "+92 300 1111111\n+92 321 2222222"})
    assert "Saved." in ok.text
    assert site.bot.clients["acme"].staff_numbers == {"923001111111", "923212222222"}


def test_staff_groups_come_from_the_group_numbers_own_list():
    site = Site()
    site.bot.waha.group_list["acme"] = [{"id": "staff@g.us", "name": "Bakery team"},
                                        {"id": "fans@g.us", "name": "Cake fans"}]
    http = site.business_user()
    page = http.get("/app/staff").text
    assert "Bakery team" in page and "Cake fans" in page
    http.post("/app/staff", data={"csrf": csrf(http, "/app/staff"), "staff_numbers": "+92 300 1111111",
                                  "groups_listed": "1", "staff_chats": ["staff@g.us", "fans@g.us", "evil@g.us"],
                                  "alert": "fans@g.us"})
    client = site.bot.clients["acme"]
    assert client.staff_chats == {"staff@g.us", "fans@g.us"} and client.staff_alert_chat == "fans@g.us"


def test_staff_page_keeps_saved_groups_when_waha_is_down():
    site = Site()
    site.bot.waha.manage_fail = SendError("waha unreachable: ConnectError")
    http = site.business_user()
    assert "read the group number" in http.get("/app/staff").text
    http.post("/app/staff", data={"csrf": csrf(http, "/app/staff"), "staff_numbers": "+92 300 1111111"})
    assert site.bot.clients["acme"].staff_chats == {"staff@g.us"}


def test_staff_page_asks_to_link_a_group_number_first():
    registry = registry_with_acme()
    registry.assign_number("acme", None, actor="t")
    assert "Link a group number first" in Site(registry=registry).business_user().get("/app/staff").text


def test_sheet_page_lists_tabs_and_explains_sharing_problems():
    site = Site()
    http = site.business_user()
    page = http.get("/app/sheet").text
    assert "Prices" in page and "Expenses" in page and "Item, Price" in page
    site.bot.sheets.fail_tabs = gspread.exceptions.SpreadsheetNotFound()
    assert "No Sheet with that id" in http.get("/app/sheet").text


def test_permissions_save_from_the_real_sheet_tabs():
    site = Site()
    http = site.business_user()
    i = indexes(site)
    data = {"csrf": csrf(http, "/app/sheet"), "action": "save", "tabs_listed": "1", "knowledge_tab": "Knowledge",
            "handoff_tab": "Handoffs",
            f"use{i['Prices']}": "on", f"read{i['Prices']}": "on",
            f"use{i['Orders']}": "on", f"own{i['Orders']}": "on", f"owner{i['Orders']}": "Phone",
            f"append{i['Orders']}": "on", f"fill_name{i['Orders']}": "Name", f"fill_phone{i['Orders']}": "Phone",
            f"use{i['Expenses']}": "on"}
    assert "Saved." in http.post("/app/sheet", data=data).text
    tabs = site.bot.clients["acme"].tabs
    assert set(tabs) == {"Prices", "Orders", "Expenses"}  # Staff Notes unticked: hidden from the bot
    assert tabs["Orders"].customer == {"own", "append"} and tabs["Orders"].owner_column == "Phone"
    assert tabs["Orders"].fill == {"Name": "name", "Phone": "phone"} and tabs["Expenses"].customer == frozenset()


def test_read_all_on_a_tab_with_contact_columns_needs_an_extra_tick():
    site = Site()
    http = site.business_user()
    i = indexes(site)["Orders"]
    data = {"csrf": csrf(http, "/app/sheet"), "action": "save", "tabs_listed": "1", f"use{i}": "on", f"read{i}": "on"}
    refused = http.post("/app/sheet", data=data).text
    assert "every customer would see Phone" in refused
    assert "read" not in site.bot.clients["acme"].tabs["Orders"].customer
    assert "Saved." in http.post("/app/sheet", data={**data, f"confirm{i}": "on"}).text
    assert site.bot.clients["acme"].tabs["Orders"].customer == {"read"}


def test_own_rows_need_an_owner_column():
    site = Site()
    http = site.business_user()
    i = indexes(site)["Orders"]
    r = http.post("/app/sheet", data={"csrf": csrf(http, "/app/sheet"), "action": "save", "tabs_listed": "1",
                                      f"use{i}": "on", f"own{i}": "on", f"owner{i}": ""})
    assert "pick which column holds" in r.text


def test_preview_shows_what_a_sample_customer_would_see_without_saving():
    site = Site()
    http = site.business_user()
    i = indexes(site)["Orders"]
    r = http.post("/app/sheet", data={"csrf": csrf(http, "/app/sheet"), "action": "preview:Orders",
                                      "tabs_listed": "1", f"use{i}": "on", f"own{i}": "on", f"owner{i}": "Phone"})
    assert "Chocolate cake" in r.text and "Carrot cake" not in r.text  # only the first row's customer, Ali
    assert site.bot.clients["acme"].tabs["Orders"].customer == {"own", "append"}  # nothing was saved


def test_permissions_are_not_wiped_when_the_sheet_cant_be_read():
    site = Site()
    http = site.business_user()
    token = csrf(http, "/app/sheet")
    site.bot.sheets.fail_tabs = RuntimeError("Google is down")
    r = http.post("/app/sheet", data={"csrf": token, "action": "save", "tabs_listed": "1"})
    assert "Google Sheets couldn" in r.text
    assert set(site.bot.clients["acme"].tabs) == {"Prices", "Orders", "Staff Notes", "Expenses"}


def test_only_admins_change_the_sheet_id():
    site = Site()
    http = site.business_user()
    assert http.post("/app/sheet", data={"csrf": csrf(http, "/app/sheet"), "action": "sheet_id",
                                         "sheet_id": "someone-elses"}).status_code == 403
    admin = site.admin()
    admin.post("/admin/b/acme/sheet", data={"csrf": csrf(admin, "/admin/b/acme/sheet"), "action": "sheet_id",
                                            "sheet_id": "sheet-2"})
    assert site.bot.clients["acme"].sheet_id == "sheet-2"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_sheet_rules.py tests/test_pages_staff_sheet.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.sheet_rules'`

- [ ] **Step 3: Implement the guardrails**

`app/sheet_rules.py`:
```python
"""Guardrails for the Sheet permissions screen: what a wrong tick could expose to customers."""
from __future__ import annotations

CONTACT_WORDS = ("phone", "mobile", "whatsapp", "number", "contact", "email", "cnic")


def sensitive_columns(headers: list[str]) -> list[str]:
    """Columns whose names suggest personal contact details."""
    return [h for h in headers if any(word in h.lower() for word in CONTACT_WORDS)]


def tab_problems(tab: str, rule: dict, headers: list[str], confirmed: bool) -> list[str]:
    """Why this tab's ticked permissions can't be saved; empty when they can."""
    problems = []
    customer = set(rule.get("customer") or [])
    if "own" in customer and rule.get("owner_column") not in headers:
        problems.append(f"{tab}: pick which column holds the customer's phone number.")
    for column in rule.get("fill") or {}:
        if column not in headers:
            problems.append(f"{tab}: column {column!r} is not in the tab.")
    exposed = sensitive_columns(headers)
    if "read" in customer and exposed and not confirmed:
        problems.append(f"{tab}: every customer would see {', '.join(exposed)}. Tick “I understand every customer "
                        "can see these columns” to allow it.")
    return problems
```

- [ ] **Step 4: Implement the staff and Sheet screens**

In `app/pages.py`, replace the import block with:
```python
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, available_timezones

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from app.auth import Session
from app.config import client_from_dict, digits
from app.registry import Business
from app.sheet_rules import sensitive_columns, tab_problems
from app.sheets import service_account_email, sheet_error
from app.tools import Caller, lookup_rows
from app.web import Form, admin_only, business_only, redirect, render, route
from app.whatsapp import SendError
```

Append to `app/pages.py`:
```python
@screen("/staff", ("GET", "POST"))
def staff_page(request: Request, scope: Scope, form: Form | None) -> Response:
    business, bot = scope.business, request.app.state.bot
    config, error = business.config, ""
    groups, groups_error = [], ""
    if business.number:
        try:
            groups = bot.waha.groups(business.number)
        except SendError as e:
            groups_error = f"Couldn't read the group number's groups ({e}). Your saved groups are kept."
    numbers_text = "\n".join(f"+{n}" for n in config.get("staff_numbers") or [])
    if form is not None:
        numbers_text = form.get("staff_numbers")
        lines = [line.strip() for line in numbers_text.splitlines() if line.strip()]
        bad = [line for line in lines if not line.startswith("+") or not 10 <= len(digits(line)) <= 15]
        changes: dict = {"staff_numbers": [digits(line) for line in lines]}
        if form.has("groups_listed"):  # only when this page showed the groups: WAHA being down keeps the saved ones
            ids = {group["id"] for group in groups}
            changes["staff_chats"] = [chat for chat in form.all("staff_chats") if chat in ids]
            changes["staff_alert_chat"] = form.get("alert") if form.get("alert") in ids else None
        if bad:
            error = ("Write each staff number in international format starting with +, like +92 300 1111111: "
                     + ", ".join(bad))
        else:
            try:
                save(request, scope, changes)
            except ValueError as e:
                error = str(e)
            else:
                return redirect(f"{scope.base}/staff?ok=saved")
        config = {**config, **changes}
    return page(request, scope, "staff.html", title="Staff & groups", config=config, error=error,
                numbers_text=numbers_text, groups=groups, groups_error=groups_error)


def tabs_from_form(form: Form, sheet_tabs: dict[str, list[str]]) -> tuple[dict, list[str]]:
    """The per-tab permissions ticked on the Sheet screen, and why any can't be saved."""
    tabs, problems = {}, []
    for i, (tab, headers) in enumerate(sheet_tabs.items()):
        if not form.has(f"use{i}"):
            continue  # the bot doesn't use this tab at all
        customer = [access for access in ("read", "own", "append") if form.has(f"{access}{i}")]
        rule: dict = {"customer": customer}
        if "own" in customer:
            rule["owner_column"] = form.get(f"owner{i}")
        if "append" in customer:
            rule["fill"] = {form.get(f"fill_{source}{i}"): source for source in ("name", "phone")
                            if form.get(f"fill_{source}{i}")}
        problems += tab_problems(tab, rule, headers, confirmed=form.has(f"confirm{i}"))
        tabs[tab] = rule
    return tabs, problems


def customer_preview(sheets, business_id: str, config: dict, tab: str) -> dict:
    """What a sample customer would get from the bot's lookup on this tab, with the unsaved permissions."""
    try:
        client = client_from_dict(business_id, config)
    except ValueError as e:
        return {"tab": tab, "error": str(e), "rows": [], "phone": None}
    rule, phone = client.tabs.get(tab), None
    try:
        if rule and "own" in rule.customer:  # the customer whose number is in the first data row
            rows = sheets.rows(client.sheet_id, tab)
            first = next((r for r in rows if str(r.get(rule.owner_column, "")).strip()), None)
            phone = digits(str(first[rule.owner_column])) if first else None
        result = lookup_rows(sheets, client, Caller("customer", False, "Sample customer", phone), tab, "")
    except Exception:
        log.exception("preview_failed business=%s", business_id)
        return {"tab": tab, "error": "The tab couldn't be read right now.", "rows": [], "phone": phone}
    return {"tab": tab, "error": result.get("error", ""), "rows": result.get("rows", [])[:5], "phone": phone}


@screen("/sheet", ("GET", "POST"))
def sheet_page(request: Request, scope: Scope, form: Form | None) -> Response:
    state, business = request.app.state, scope.business
    config, error, preview = dict(business.config), "", None
    email = service_account_email(state.settings.google_service_account_file)
    action = form.get("action") if form is not None else ""
    if action == "sheet_id":
        if not scope.is_admin:
            raise HTTPException(403, "Only admins can change which Sheet a business uses.")
        try:
            save(request, scope, {"sheet_id": form.get("sheet_id")})
        except ValueError as e:
            error = str(e)
        else:
            return redirect(f"{scope.base}/sheet?ok=saved")
    sheet_tabs, sheet_problem = {}, ""
    try:
        sheet_tabs = state.bot.sheets.tab_headers(config["sheet_id"])
    except Exception as e:
        sheet_problem = sheet_error(e, email)
    if form is not None and action != "sheet_id":
        if sheet_problem or not form.has("tabs_listed"):  # never save a form that didn't list the Sheet's tabs
            error = sheet_problem or "Reload the page and try again."
        else:
            tabs, problems = tabs_from_form(form, sheet_tabs)
            config.update(tabs=tabs, knowledge_tab=form.get("knowledge_tab") or "Knowledge",
                          handoff_tab=form.get("handoff_tab") or "Handoffs")
            if problems:
                error = " ".join(problems)
            elif action.startswith("preview:"):
                preview = customer_preview(state.bot.sheets, business.id, config, action.removeprefix("preview:"))
            else:
                try:
                    save(request, scope, {key: config[key] for key in ("tabs", "knowledge_tab", "handoff_tab")})
                except ValueError as e:
                    error = str(e)
                else:
                    return redirect(f"{scope.base}/sheet?ok=saved")
    return page(request, scope, "sheet.html", title="Sheet & permissions", config=config, email=email,
                sheet_tabs=sheet_tabs, sheet_problem=sheet_problem, error=error, preview=preview,
                sensitive={tab: sensitive_columns(headers) for tab, headers in sheet_tabs.items()})
```

- [ ] **Step 5: Add the templates**

`app/templates/staff.html`:
```html
{% extends "base.html" %}
{% block content %}
<h1>Staff &amp; groups</h1>
<p>Staff can use every tab the bot uses and save rows without a YES. Everyone else is a customer.</p>
<form method="post">
  <input type="hidden" name="csrf" value="{{ csrf }}">
  <label>Staff WhatsApp numbers, one per line, with the country code
    <textarea name="staff_numbers" rows="4" placeholder="+92 300 1111111">{{ numbers_text }}</textarea>
  </label>
  <h2>Groups</h2>
  {% if not business.number %}
  <p>Link a group number first; then its groups appear here.</p>
  {% elif groups_error %}
  <p class="notice error">{{ groups_error }}</p>
  {% else %}
  <input type="hidden" name="groups_listed" value="1">
  {% if not groups %}<p>The group number isn't in any groups yet.</p>{% endif %}
  <table>
    <thead><tr><th>Group</th><th>Staff group</th><th>Gets "needs a person" alerts</th></tr></thead>
    <tbody>
      <tr><td><em>No alerts</em></td><td></td>
        <td><input type="radio" name="alert" value=""{% if not config.staff_alert_chat %} checked{% endif %}></td></tr>
      {% for g in groups %}
      <tr>
        <td>{{ g.name }}</td>
        <td><input type="checkbox" name="staff_chats" value="{{ g.id }}"{% if g.id in (config.staff_chats or []) %} checked{% endif %}></td>
        <td><input type="radio" name="alert" value="{{ g.id }}"{% if g.id == config.staff_alert_chat %} checked{% endif %}></td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% endif %}
  <button type="submit">Save</button>
</form>
{% endblock %}
```

`app/templates/sheet.html`:
```html
{% extends "base.html" %}
{% block content %}
<h1>Sheet &amp; permissions</h1>
<p>Share the Google Sheet with <strong>{{ email or "the service account (ask your admin for the address)" }}</strong> as <em>Editor</em>.</p>
{% if is_admin %}
<form method="post" class="grid">
  <input type="hidden" name="csrf" value="{{ csrf }}">
  <input name="sheet_id" value="{{ config.sheet_id }}" aria-label="Sheet id" required>
  <button type="submit" name="action" value="sheet_id" class="secondary">Change Sheet</button>
</form>
{% else %}
<p>Sheet id: <code>{{ config.sheet_id }}</code></p>
{% endif %}
<p><a href="{{ base }}/sheet">Check access again</a></p>
{% if sheet_problem %}
<p class="notice error">{{ sheet_problem }}</p>
{% else %}
<form method="post">
  <input type="hidden" name="csrf" value="{{ csrf }}">
  <input type="hidden" name="tabs_listed" value="1">
  <div class="grid">
    <label>Knowledge tab (read into every answer)
      <select name="knowledge_tab">{% for t in sheet_tabs %}<option{% if t == config.knowledge_tab %} selected{% endif %}>{{ t }}</option>{% endfor %}</select>
    </label>
    <label>Handoffs tab (where "needs a person" rows go)
      <select name="handoff_tab">{% for t in sheet_tabs %}<option{% if t == config.handoff_tab %} selected{% endif %}>{{ t }}</option>{% endfor %}</select>
    </label>
  </div>
  {% for tab, headers in sheet_tabs.items() %}
  {% set i = loop.index0 %}
  {% set rule = (config.tabs or {}).get(tab) %}
  {% set access = (rule or {}).get("customer") or [] %}
  {% set fill = (rule or {}).get("fill") or {} %}
  <article>
    <header>
      <label><input type="checkbox" name="use{{ i }}"{% if rule is not none %} checked{% endif %}>
        <strong>{{ tab }}</strong>: the bot uses this tab (staff can look up and add rows)</label>
      <small>Columns: {{ headers|join(", ") or "(no header row)" }}</small>
    </header>
    <p>Customers can:</p>
    <label><input type="checkbox" name="read{{ i }}"{% if "read" in access %} checked{% endif %}> read all rows</label>
    <label><input type="checkbox" name="own{{ i }}"{% if "own" in access %} checked{% endif %}> see only their own rows, found by the phone number in
      <select name="owner{{ i }}"><option value="">(pick a column)</option>{% for h in headers %}<option{% if h == (rule or {}).get("owner_column") %} selected{% endif %}>{{ h }}</option>{% endfor %}</select>
    </label>
    <label><input type="checkbox" name="append{{ i }}"{% if "append" in access %} checked{% endif %}> add rows (after replying YES), putting their WhatsApp name in
      <select name="fill_name{{ i }}"><option value="">(none)</option>{% for h in headers %}<option{% if fill.get(h) == "name" %} selected{% endif %}>{{ h }}</option>{% endfor %}</select>
      and their phone in
      <select name="fill_phone{{ i }}"><option value="">(none)</option>{% for h in headers %}<option{% if fill.get(h) == "phone" %} selected{% endif %}>{{ h }}</option>{% endfor %}</select>
    </label>
    {% if sensitive[tab] %}
    <p class="notice error">This tab has contact columns: {{ sensitive[tab]|join(", ") }}.</p>
    <label><input type="checkbox" name="confirm{{ i }}"> I understand every customer can see these columns if "read all rows" is ticked</label>
    {% endif %}
    <button type="submit" name="action" value="preview:{{ tab }}" class="secondary">What a customer would see</button>
    {% if preview and preview.tab == tab %}
      {% if preview.error %}<p class="notice error">A customer would be told: {{ preview.error }}</p>
      {% elif not preview.rows %}<p>A customer would see no rows.</p>
      {% else %}
      <p>A customer{% if preview.phone %} with the number {{ preview.phone }}{% endif %} would see:</p>
      <table>
        <thead><tr>{% for h in headers %}<th>{{ h }}</th>{% endfor %}</tr></thead>
        <tbody>{% for r in preview.rows %}<tr>{% for h in headers %}<td>{{ r[h] }}</td>{% endfor %}</tr>{% endfor %}</tbody>
      </table>
      {% endif %}
    {% endif %}
  </article>
  {% endfor %}
  <button type="submit" name="action" value="save">Save permissions</button>
</form>
{% endif %}
{% endblock %}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_sheet_rules.py tests/test_pages_staff_sheet.py tests/test_pages.py -v`
Expected: PASS (2 + 11 new tests, and Task 9's 7)

Run: `uv run pytest -q && uv run ruff check .`
Expected: all tests pass; `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add app/sheet_rules.py app/pages.py app/templates/staff.html app/templates/sheet.html tests/test_sheet_rules.py tests/test_pages_staff_sheet.py
git commit -m "feat: staff, groups and Sheet permissions with guardrails and a customer preview"
```

### Task 11: Admin console: overview, new business, official number, group number, logins, pause, audit, admins

**Files:**
- Create: `app/admin_pages.py`, `app/templates/admin_overview.html`, `app/templates/admin_new.html`, `app/templates/admin_meta.html`, `app/templates/admin_number.html`, `app/templates/logins.html`, `app/templates/admin_audit.html`
- Modify: `app/templates/_business_nav.html`, `app/main.py`
- Test: `tests/test_admin_pages.py`

**Interfaces:**
- Consumes: `route`, `render`, `redirect`, `public_url`, `Form`, `admin_only` (Task 8); `Scope`, `admin_scope`, `page`, `month_start`, `TIMEZONES` (Task 9); `Registry` methods (Task 3); `Auth` methods (Task 7); `MetaClient.number_info` via `bot.meta` (Task 4); `Sheets.tab_headers`, `service_account_email`, `sheet_error` (Task 5).
- Produces (`app/admin_pages.py`, all admin-only):
  - `GET /admin` (overview), `GET/POST /admin/new`, `GET/POST /admin/admins`.
  - For a business: `GET/POST /admin/b/{id}/meta` (actions `save`, `test`), `GET/POST /admin/b/{id}/number`, `GET/POST /admin/b/{id}/logins` (actions `invite`, `link`, `disable`, `enable`), `POST /admin/b/{id}/pause` (field `active` = `0`/`1`), `GET /admin/b/{id}/audit`.
  - Login actions on a `user_id` outside the business (or a non-admin on the admins page) → 404. Nobody can disable their own login.

- [ ] **Step 1: Write the failing tests**

`tests/test_admin_pages.py`:
```python
import re

from app.whatsapp import SendError
from tests.fakes import acme_config
from tests.webkit import NOW, PASSWORD, Site, csrf


def test_overview_shows_every_business_with_number_status_and_replies():
    site = Site()
    site.registry.create_business("other", {**acme_config(), "business": "Other Co"}, actor="t")
    site.bot.clients = site.registry.clients()
    site.bot.waha.statuses["acme"] = "SCAN_QR_CODE"
    site.bot.store.save_message("acme", "meta", "b1", "c", "bot", "Sara", "hi", True, NOW - 60)
    page = site.admin().get("/admin").text
    assert "Sweet Bakes" in page and "Other Co" in page and "SCAN_QR_CODE" in page and "not linked" in page
    biz = site.business_user()
    assert biz.get("/admin").status_code == 403 and biz.get("/admin/admins").status_code == 403


def test_admins_must_finish_two_step_login_first():
    site = Site()
    site.auth.accept_invite(site.auth.invite("a@example.com", "", "admin", None), PASSWORD)
    http = site.browser()
    http.post("/login", data={"email": "a@example.com", "password": PASSWORD})
    assert http.get("/admin", follow_redirects=False).headers["location"] == "/login/totp"


def test_adding_a_business_checks_the_sheet_and_goes_live_at_once():
    site = Site()
    admin = site.admin()
    form = {"csrf": csrf(admin, "/admin/new"), "id": "bakehouse", "business": "Bake House", "bot_name": "Noor",
            "timezone": "Asia/Karachi", "sheet_id": "sheet-1", "instructions": "Be kind."}
    check = admin.post("/admin/new", data={**form, "action": "check"}).text
    assert "The Sheet is readable" in check and "Prices" in check
    assert 'value="bake-house"' in admin.post("/admin/new", data={**form, "id": "", "action": "check"}).text
    bad = admin.post("/admin/new", data={**form, "id": "Bake House", "action": "create"}).text
    assert "web id" in bad and "bakehouse" not in site.bot.clients
    created = admin.post("/admin/new", data={**form, "action": "create"})
    assert "Business created." in created.text and site.bot.clients["bakehouse"].bot_name == "Noor"
    assert "already exists" in admin.post("/admin/new", data={**form, "action": "create"}).text


def test_meta_keys_are_write_only_and_reach_the_bot():
    site = Site()
    admin = site.admin()
    token = csrf(admin, "/admin/b/acme/meta")
    r = admin.post("/admin/b/acme/meta", data={"csrf": token, "action": "save", "phone_number_id": "106540352242922",
                                               "access_token": "EAAG-new-token-9876", "app_secret": ""})
    assert "Saved." in r.text and "EAAG-new-token-9876" not in r.text and "9876" in r.text
    client = site.bot.clients["acme"]
    assert client.meta_access_token == "EAAG-new-token-9876" and client.meta_app_secret == "acme-secret"
    page = admin.get("/admin/b/acme/meta").text
    assert "https://bot.example.com/webhooks/meta/acme" in page and client.meta_verify_token in page
    assert "acme-secret" not in page and "EAAG-new-token-9876" not in page


def test_test_connection_shows_metas_answer():
    site = Site()
    admin = site.admin()
    token = csrf(admin, "/admin/b/acme/meta")
    ok = admin.post("/admin/b/acme/meta", data={"csrf": token, "action": "test"}).text
    assert "+1 555 0100" in ok and "Sweet Bakes" in ok
    site.bot.meta.info = SendError("meta status=401 code=190 Error validating access token")
    assert "Error validating access token" in admin.post("/admin/b/acme/meta",
                                                         data={"csrf": token, "action": "test"}).text


def test_assigning_a_group_number_moves_the_bot_to_it():
    site = Site()
    site.registry.add_number("spare-1", "", actor="t")
    admin = site.admin()
    token = csrf(admin, "/admin/b/acme/number")
    admin.post("/admin/b/acme/number", data={"csrf": token, "session": "spare-1"})
    assert site.bot.clients["acme"].waha_session == "spare-1"
    admin.post("/admin/b/acme/number", data={"csrf": token, "session": ""})
    assert site.bot.clients["acme"].waha_session is None


def test_business_logins_invite_new_link_and_disable():
    site = Site()
    site.registry.create_business("other", {**acme_config(), "business": "Other Co"}, actor="t")
    stranger = site.auth.invite("zed@other.co", "", "business", "other")
    admin = site.admin()
    token = csrf(admin, "/admin/b/acme/logins")
    page = admin.post("/admin/b/acme/logins", data={"csrf": token, "action": "invite", "email": "mgr@sweetbakes.pk",
                                                    "name": "Manager"}).text
    link = re.search(r"https://bot\.example\.com(/invite/[\w-]+)", page).group(1)
    browser = site.browser()
    browser.post(link, data={"password": PASSWORD, "confirm": PASSWORD})
    browser.post("/login", data={"email": "mgr@sweetbakes.pk", "password": PASSWORD})
    assert browser.get("/app").status_code == 200
    user = site.auth.by_email("mgr@sweetbakes.pk")
    admin.post("/admin/b/acme/logins", data={"csrf": token, "action": "disable", "user_id": str(user.id)})
    assert browser.get("/app", follow_redirects=False).headers["location"] == "/login"
    assert "user.disable" in [e["action"] for e in site.registry.audit_log("acme")]
    other_user = site.auth.invited_user(stranger)
    assert admin.post("/admin/b/acme/logins", data={"csrf": token, "action": "link",
                                                    "user_id": str(other_user.id)}).status_code == 404


def test_pausing_a_business_stops_its_bot_and_shows_a_banner():
    site = Site()
    admin = site.admin()
    token = csrf(admin, "/admin/b/acme")
    r = admin.post("/admin/b/acme/pause", data={"csrf": token, "active": "0"})
    assert "Business paused" in r.text and "acme" not in site.bot.clients
    assert "is paused" in site.business_user().get("/app").text
    admin.post("/admin/b/acme/pause", data={"csrf": token, "active": "1"})
    assert "acme" in site.bot.clients


def test_audit_log_names_who_changed_what_without_secrets():
    site = Site()
    admin = site.admin()
    admin.post("/admin/b/acme/settings", data={"csrf": csrf(admin, "/admin/b/acme/settings"), "business": "Sweet Bakes",
                                               "bot_name": "Zara", "instructions": "", "timezone": "Asia/Karachi",
                                               "date_format": "", "retention_days": "90"})
    page = admin.get("/admin/b/acme/audit").text
    assert "settings.save" in page and "admin@example.com" in page
    assert "acme-token" not in page and "acme-secret" not in page


def test_admins_can_invite_admins_but_not_disable_themselves():
    site = Site()
    admin = site.admin()
    token = csrf(admin, "/admin/admins")
    page = admin.post("/admin/admins", data={"csrf": token, "action": "invite", "email": "helper@example.com"}).text
    assert "/invite/" in page and "helper@example.com" in page
    me = site.auth.by_email("admin@example.com")
    assert "your own login" in admin.post("/admin/admins", data={"csrf": token, "action": "disable",
                                                                 "user_id": str(me.id)}).text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_admin_pages.py -v`
Expected: FAIL (the admin routes don't exist yet: 404s and failed asserts)

- [ ] **Step 3: Implement the admin screens**

`app/admin_pages.py`:
```python
"""Admin-only screens: every business at a glance, adding a business, a business's official number, group number,
logins, pause and audit log, and the list of admins."""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.auth import AuthError, Session
from app.pages import TIMEZONES, Scope, admin_scope, month_start, page
from app.sheets import service_account_email, sheet_error
from app.web import Form, admin_only, public_url, redirect, render, route
from app.whatsapp import SendError

router = APIRouter()
NEW_FIELDS = ("id", "business", "bot_name", "timezone", "sheet_id", "instructions")


@route(router, "/admin", admin_only)
def overview(request: Request, sess: Session, form: Form | None) -> Response:
    state = request.app.state
    rows = []
    for business in state.registry.businesses():
        timezone = business.config.get("timezone") or "UTC"
        rows.append({"b": business,
                     "group": state.bot.waha.status(business.number) if business.number else "not linked",
                     "replies": state.bot.store.replies_since(business.id, month_start(state.bot.clock(), timezone))})
    return render(request, "admin_overview.html", sess, title="Businesses", rows=rows)


@route(router, "/admin/new", admin_only, ("GET", "POST"))
def new_business(request: Request, sess: Session, form: Form | None) -> Response:
    state = request.app.state
    email = service_account_email(state.settings.google_service_account_file)
    values, error, sheet_tabs = {"timezone": "Asia/Karachi"}, "", None
    if form is not None:
        values = {key: form.get(key) for key in NEW_FIELDS}
        values["id"] = values["id"] or "-".join(re.findall(r"[a-z0-9]+", values["business"].lower()))[:32].strip("-")
        if form.get("action") == "check":
            try:
                sheet_tabs = state.bot.sheets.tab_headers(values["sheet_id"])
            except Exception as e:
                error = sheet_error(e, email)
        else:
            config = {key: values[key] for key in NEW_FIELDS if key != "id"}
            config.update(knowledge_tab="Knowledge", handoff_tab="Handoffs", tabs={})
            try:
                state.registry.create_business(values["id"], config, actor=str(sess.user.id))
            except ValueError as e:
                error = str(e)
            else:
                state.reload()
                return redirect(f"/admin/b/{values['id']}?ok=created")
    return render(request, "admin_new.html", sess, title="Add a business", values=values, error=error, email=email,
                  sheet_tabs=sheet_tabs, timezones=TIMEZONES)


@route(router, "/admin/b/{business_id}/meta", admin_scope, ("GET", "POST"))
def meta_page(request: Request, scope: Scope, form: Form | None) -> Response:
    state, business = request.app.state, scope.business
    error, test = "", None
    if form is not None and form.get("action") == "test":
        client = state.bot.clients.get(business.id)
        if client is None:
            error = "Resume the business before testing it."
        elif not client.meta_phone_number_id or not client.meta_access_token:
            error = "Save the phone number ID and access token first."
        else:
            try:
                test = state.bot.meta.number_info(client.meta_phone_number_id, token=client.meta_access_token)
            except SendError as e:
                error = f"Meta refused: {e}"
    elif form is not None:
        try:
            state.registry.save_meta(business.id, form.get("phone_number_id"), form.raw("access_token").strip(),
                                     form.raw("app_secret").strip(), actor=str(scope.session.user.id))
        except ValueError as e:
            error = str(e)
        else:
            state.reload()
            return redirect(f"{scope.base}/meta?ok=saved")
    return page(request, scope, "admin_meta.html", title="Official number", error=error, test=test,
                webhook=f"{public_url(request)}/webhooks/meta/{business.id}")


@route(router, "/admin/b/{business_id}/number", admin_scope, ("GET", "POST"))
def number_page(request: Request, scope: Scope, form: Form | None) -> Response:
    state, business = request.app.state, scope.business
    free = [n for n in state.registry.numbers() if n.business_id in (None, business.id)]
    error = ""
    if form is not None:
        session, actor = form.get("session"), str(scope.session.user.id)
        try:
            if session and session not in {n.session for n in free}:
                raise ValueError("That number belongs to another business; unassign it there first.")
            if session:
                state.registry.assign_number(session, business.id, actor=actor)
            elif business.number:
                state.registry.assign_number(business.number, None, actor=actor)
        except ValueError as e:
            error = str(e)
        else:
            state.reload()
            return redirect(f"{scope.base}/number?ok=assigned")
    return page(request, scope, "admin_number.html", title="Group number", numbers=free, error=error)


def manage_logins(request: Request, sess: Session, form: Form | None, business_id: str | None) -> dict:
    """Invite / new link / disable / enable, for one business's logins, or for the admins when business_id is None."""
    state, role = request.app.state, "business" if business_id else "admin"
    ctx = {"error": "", "link": "", "link_email": ""}
    if form is not None:
        action, actor = form.get("action"), str(sess.user.id)
        try:
            if action == "invite":
                token = state.auth.invite(form.get("email"), form.get("name"), role, business_id)
                ctx.update(link=f"{public_url(request)}/invite/{token}", link_email=form.get("email"))
                state.registry.audit(actor, business_id, "user.invite", {"email": form.get("email")})
            else:
                user_id = form.get("user_id")
                user = state.auth.user(int(user_id)) if user_id.isdigit() else None
                if user is None or user.role != role or user.business_id != business_id:
                    raise HTTPException(404, "No such login here.")
                if action == "link":
                    token = state.auth.new_link(user.id)
                    ctx.update(link=f"{public_url(request)}/invite/{token}", link_email=user.email)
                elif action in ("disable", "enable"):
                    if user.id == sess.user.id:
                        raise AuthError("You can't disable your own login.")
                    state.auth.set_disabled(user.id, action == "disable")
                else:
                    raise AuthError("Unknown action.")
                state.registry.audit(actor, business_id, f"user.{action}", {"email": user.email})
        except AuthError as e:
            ctx["error"] = str(e)
    users = state.auth.users(business_id=business_id, role=role) if business_id else state.auth.users(role=role)
    return {**ctx, "users": users, "self_id": sess.user.id}


@route(router, "/admin/b/{business_id}/logins", admin_scope, ("GET", "POST"))
def logins_page(request: Request, scope: Scope, form: Form | None) -> Response:
    ctx = manage_logins(request, scope.session, form, scope.business.id)
    return page(request, scope, "logins.html", title="Logins", **ctx)


@route(router, "/admin/admins", admin_only, ("GET", "POST"))
def admins_page(request: Request, sess: Session, form: Form | None) -> Response:
    return render(request, "logins.html", sess, title="Admins", **manage_logins(request, sess, form, None))


@route(router, "/admin/b/{business_id}/pause", admin_scope, ("POST",))
def pause(request: Request, scope: Scope, form: Form | None) -> Response:
    active = form.get("active") == "1"
    request.app.state.registry.set_active(scope.business.id, active, actor=str(scope.session.user.id))
    request.app.state.reload()
    return redirect(f"{scope.base}?ok={'resumed' if active else 'paused'}")


@route(router, "/admin/b/{business_id}/audit", admin_scope)
def audit_page(request: Request, scope: Scope, form: Form | None) -> Response:
    state = request.app.state
    actors = {str(user.id): user.email for user in state.auth.users()}
    return page(request, scope, "admin_audit.html", title="Audit log", actors=actors,
                entries=state.registry.audit_log(scope.business.id))
```

- [ ] **Step 4: Add the templates**

Replace `app/templates/_business_nav.html` with:
```html
<nav class="tabs">
  <ul>
    <li><strong>{{ business.config.business }}</strong>{% if not business.active %} <span class="badge bad">paused</span>{% endif %}</li>
  </ul>
  <ul>
    <li><a href="{{ base }}">Home</a></li>
    <li><a href="{{ base }}/settings">Bot settings</a></li>
    <li><a href="{{ base }}/staff">Staff &amp; groups</a></li>
    <li><a href="{{ base }}/sheet">Sheet</a></li>
    <li><a href="{{ base }}/chats">Chats</a></li>
    {% if is_admin %}
    <li><a href="{{ base }}/meta">Official number</a></li>
    <li><a href="{{ base }}/number">Group number</a></li>
    <li><a href="{{ base }}/logins">Logins</a></li>
    <li><a href="{{ base }}/audit">Audit log</a></li>
    <li>
      <form method="post" action="{{ base }}/pause" class="inline">
        <input type="hidden" name="csrf" value="{{ csrf }}">
        <input type="hidden" name="active" value="{{ '0' if business.active else '1' }}">
        <button type="submit" class="secondary outline">{{ "Pause business" if business.active else "Resume business" }}</button>
      </form>
    </li>
    {% endif %}
  </ul>
</nav>
```

`app/templates/admin_overview.html`:
```html
{% extends "base.html" %}
{% block content %}
<h1>Businesses</h1>
<p><a href="/admin/new" role="button">Add a business</a></p>
{% if not rows %}<p>No businesses yet.</p>{% else %}
<table>
  <thead><tr><th>Business</th><th>Official number</th><th>Group number</th><th>Official replies this month</th><th>Group replies this month</th></tr></thead>
  <tbody>
  {% for r in rows %}
  <tr>
    <td><a href="/admin/b/{{ r.b.id }}">{{ r.b.config.business }}</a>{% if not r.b.active %} <span class="badge bad">paused</span>{% endif %}</td>
    <td>{% if r.b.keys_unreadable %}<span class="badge bad">re-enter keys</span>{% elif r.b.meta_phone_number_id and r.b.has_meta_token %}<span class="badge good">keys saved</span>{% else %}not set{% endif %}</td>
    <td><span class="badge {{ 'good' if r.group == 'WORKING' else 'bad' }}">{{ r.group }}</span></td>
    <td>{{ r.replies.meta }}</td>
    <td>{{ r.replies.waha }}</td>
  </tr>
  {% endfor %}
  </tbody>
</table>
{% endif %}
{% endblock %}
```

`app/templates/admin_new.html`:
```html
{% extends "base.html" %}
{% block content %}
<h1>Add a business</h1>
<p>First ask the business to share its Google Sheet with <strong>{{ email or "the client_email in your Google key file" }}</strong> as <em>Editor</em>.</p>
<form method="post">
  <input type="hidden" name="csrf" value="{{ csrf }}">
  <label>Web id (lowercase letters, digits and dashes; it goes into the business's webhook address)
    <input name="id" value="{{ values.id or '' }}" required></label>
  <label>Business name <input name="business" value="{{ values.business or '' }}" required></label>
  <label>Bot name <input name="bot_name" value="{{ values.bot_name or '' }}" required></label>
  <label>Time zone
    <select name="timezone">{% for tz in timezones %}<option{% if tz == values.timezone %} selected{% endif %}>{{ tz }}</option>{% endfor %}</select>
  </label>
  <label>Google Sheet id (the long code in the Sheet's web address)
    <input name="sheet_id" value="{{ values.sheet_id or '' }}" required></label>
  <label>Instructions for the bot <textarea name="instructions" rows="4">{{ values.instructions or '' }}</textarea></label>
  {% if sheet_tabs is not none %}<div class="notice ok"><p>The Sheet is readable. Its tabs and columns:</p>
    <ul>{% for tab, headers in sheet_tabs.items() %}<li><strong>{{ tab }}</strong>: {{ headers|join(", ") or "(no header row)" }}</li>{% endfor %}</ul></div>{% endif %}
  <div class="grid">
    <button type="submit" name="action" value="check" class="secondary">Check Sheet access</button>
    <button type="submit" name="action" value="create">Create business</button>
  </div>
</form>
{% endblock %}
```

`app/templates/admin_meta.html`:
```html
{% extends "base.html" %}
{% block content %}
<h1>Official number (Meta)</h1>
{% if business.keys_unreadable %}<p class="notice error">The saved keys can't be read (was SECRET_KEY changed?). Enter them again.</p>{% endif %}
<form method="post">
  <input type="hidden" name="csrf" value="{{ csrf }}">
  <label>Phone number ID <input name="phone_number_id" value="{{ business.meta_phone_number_id or '' }}" inputmode="numeric"></label>
  <label>Access token {% if business.has_meta_token %}<small>(saved, ends in ••••{{ business.meta_token_hint }}; leave empty to keep it)</small>{% endif %}
    <input type="password" name="access_token" autocomplete="off"></label>
  <label>App secret {% if business.has_meta_secret %}<small>(saved; leave empty to keep it)</small>{% endif %}
    <input type="password" name="app_secret" autocomplete="off"></label>
  <div class="grid">
    <button type="submit" name="action" value="save">Save keys</button>
    <button type="submit" name="action" value="test" class="secondary">Test connection</button>
  </div>
</form>
{% if test %}<p class="notice ok">Meta says this is {{ test.display_phone_number }} ({{ test.verified_name }}).</p>{% endif %}
<h2>Paste these into the business's Meta app</h2>
<p>In the app's WhatsApp webhook settings:</p>
<ul>
  <li>Callback URL: <code>{{ webhook }}</code></li>
  <li>Verify token: <code>{{ business.meta_verify_token }}</code></li>
  <li>Subscribe to the <code>messages</code> field.</li>
</ul>
{% endblock %}
```

`app/templates/admin_number.html`:
```html
{% extends "base.html" %}
{% block content %}
<h1>Group number</h1>
<p>Now: {% if business.number %}<strong>{{ business.number }}</strong>{% else %}none{% endif %}</p>
<form method="post">
  <input type="hidden" name="csrf" value="{{ csrf }}">
  <label>Use this purchased number
    <select name="session">
      <option value="">(none)</option>
      {% for n in numbers %}<option value="{{ n.session }}"{% if n.session == business.number %} selected{% endif %}>{{ n.session }}{% if n.phone %} (+{{ n.phone }}){% endif %}</option>{% endfor %}
    </select>
  </label>
  <button type="submit">Save</button>
</form>
<p><a href="/admin/numbers">Manage purchased numbers</a></p>
{% endblock %}
```

`app/templates/logins.html`:
```html
{% extends "base.html" %}
{% block content %}
<h1>{{ title }}</h1>
{% if link %}
<p class="notice ok">Send this one-time link to {{ link_email }} (for example on WhatsApp). It works for 7 days:<br><code>{{ link }}</code></p>
{% endif %}
<table>
  <thead><tr><th>Email</th><th>Name</th><th>Status</th><th></th></tr></thead>
  <tbody>
  {% for u in users %}
  <tr>
    <td>{{ u.email }}</td>
    <td>{{ u.name }}</td>
    <td>{% if u.disabled %}disabled{% elif not u.has_password %}invited{% else %}active{% endif %}</td>
    <td>
      <form method="post" class="inline">
        <input type="hidden" name="csrf" value="{{ csrf }}">
        <input type="hidden" name="user_id" value="{{ u.id }}">
        <button type="submit" name="action" value="link" class="secondary outline">New link</button>
        {% if u.id != self_id %}
        <button type="submit" name="action" value="{{ 'enable' if u.disabled else 'disable' }}" class="secondary outline">{{ "Enable" if u.disabled else "Disable" }}</button>
        {% endif %}
      </form>
    </td>
  </tr>
  {% else %}
  <tr><td colspan="4">No logins yet.</td></tr>
  {% endfor %}
  </tbody>
</table>
<h2>Invite someone</h2>
<form method="post">
  <input type="hidden" name="csrf" value="{{ csrf }}">
  <div class="grid">
    <input type="email" name="email" placeholder="Email" aria-label="Email" required>
    <input name="name" placeholder="Name" aria-label="Name">
    <button type="submit" name="action" value="invite">Create login</button>
  </div>
</form>
{% endblock %}
```

`app/templates/admin_audit.html`:
```html
{% extends "base.html" %}
{% block content %}
<h1>Audit log</h1>
<table>
  <thead><tr><th>When</th><th>Who</th><th>What</th><th>Details</th></tr></thead>
  <tbody>
  {% for e in entries %}
  <tr>
    <td>{{ e.at|localtime(business.config.timezone) }}</td>
    <td>{{ actors.get(e.actor, e.actor) }}</td>
    <td>{{ e.action }}</td>
    <td><code>{{ e.detail }}</code></td>
  </tr>
  {% else %}
  <tr><td colspan="4">No changes yet.</td></tr>
  {% endfor %}
  </tbody>
</table>
{% endblock %}
```

- [ ] **Step 5: Mount the admin screens**

In `app/main.py`, add to the `app.` import group:
```python
from app import admin_pages
```
and right after `app.include_router(pages.router)`, add:
```python
    app.include_router(admin_pages.router)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_admin_pages.py -v`
Expected: PASS (10 passed)

Run: `uv run pytest -q && uv run ruff check .`
Expected: all tests pass; `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add app/admin_pages.py app/main.py app/templates/_business_nav.html app/templates/admin_overview.html app/templates/admin_new.html app/templates/admin_meta.html app/templates/admin_number.html app/templates/logins.html app/templates/admin_audit.html tests/test_admin_pages.py
git commit -m "feat: admin console for businesses, Meta keys, group numbers, logins, pause and audit"
```

### Task 12: Purchased-numbers inventory with QR linking

**Files:**
- Create: `app/numbers_pages.py`, `app/templates/numbers.html`, `app/templates/number_link.html`
- Modify: `app/main.py`
- Test: `tests/test_numbers_pages.py`

**Interfaces:**
- Consumes: `route`, `render`, `redirect`, `Form`, `admin_only` (Task 8); `Registry` number methods (Task 3); `WahaClient` management methods and `session_phone` (Task 4); `Settings.waha_webhook_url`, `waha_webhook_secret`.
- Produces (all admin-only): `GET/POST /admin/numbers` (list; POST adds a number and creates its WAHA session), `GET /admin/numbers/{session}` (link page: QR while `SCAN_QR_CODE`, refreshes every 3 seconds while `SCAN_QR_CODE` or `STARTING`, saves the phone once `WORKING`), `GET /admin/numbers/{session}/qr.png`, and `POST` to `/admin/numbers/{session}/relink`, `/logout`, `/assign` (field `business_id`, empty = unassign), `/notes`, `/delete` (only when unassigned; then logs out and deletes the WAHA session, best effort).
- A session WAHA doesn't know shows as `NOT CREATED`; WAHA down shows `UNREACHABLE`; errors are shown on the page.

- [ ] **Step 1: Write the failing tests**

`tests/test_numbers_pages.py`:
```python
from app.whatsapp import SendError
from tests.webkit import Site, csrf


def test_adding_a_number_creates_its_waha_session_and_opens_the_qr_page():
    site = Site()
    admin = site.admin()
    token = csrf(admin, "/admin/numbers")
    r = admin.post("/admin/numbers", data={"csrf": token, "session": "shop-2", "notes": "Zong SIM"})
    assert site.bot.waha.created == [("shop-2", "http://engine:8000/webhooks/waha", "hook-secret")]
    assert 'src="/admin/numbers/shop-2/qr.png' in r.text and 'http-equiv="refresh"' in r.text
    png = admin.get("/admin/numbers/shop-2/qr.png")
    assert png.headers["content-type"] == "image/png" and png.content.startswith(b"\x89PNG")
    assert "already exists" in admin.post("/admin/numbers", data={"csrf": token, "session": "shop-2"}).text
    assert "session name" in admin.post("/admin/numbers", data={"csrf": token, "session": "Shop 2"}).text


def test_a_linked_number_saves_its_phone_and_stops_refreshing():
    site = Site()
    site.registry.add_number("shop-2", "", actor="t")
    site.bot.waha.statuses["shop-2"] = "WORKING"
    site.bot.waha.phones["shop-2"] = "923330000000@c.us"
    page = site.admin().get("/admin/numbers/shop-2").text
    assert "+923330000000" in page and "http-equiv" not in page
    assert site.registry.number("shop-2").phone == "923330000000"


def test_relink_creates_a_missing_session_or_starts_a_stopped_one():
    site = Site()
    site.registry.add_number("shop-2", "", actor="t")
    admin = site.admin()
    token = csrf(admin, "/admin/numbers/shop-2")
    assert "NOT CREATED" in admin.get("/admin/numbers/shop-2").text
    admin.post("/admin/numbers/shop-2/relink", data={"csrf": token})
    assert ("create", "shop-2") in site.bot.waha.calls
    site.bot.waha.statuses["shop-2"] = "STOPPED"
    admin.post("/admin/numbers/shop-2/relink", data={"csrf": token})
    assert ("start", "shop-2") in site.bot.waha.calls


def test_assigning_from_the_number_page_and_deleting_only_free_numbers():
    site = Site()
    site.registry.add_number("shop-2", "", actor="t")
    admin = site.admin()
    token = csrf(admin, "/admin/numbers/shop-2")
    admin.post("/admin/numbers/shop-2/assign", data={"csrf": token, "business_id": "acme"})
    assert site.bot.clients["acme"].waha_session == "shop-2"
    assert "Unassign" in admin.post("/admin/numbers/shop-2/delete", data={"csrf": token}).text
    admin.post("/admin/numbers/shop-2/assign", data={"csrf": token, "business_id": ""})
    admin.post("/admin/numbers/shop-2/notes", data={"csrf": token, "notes": "spare, Jazz"})
    assert site.registry.number("shop-2").notes == "spare, Jazz"
    r = admin.post("/admin/numbers/shop-2/delete", data={"csrf": token})
    assert "Number deleted." in r.text and site.registry.number("shop-2") is None
    assert ("delete", "shop-2") in site.bot.waha.calls


def test_numbers_page_survives_waha_being_down():
    site = Site()
    site.bot.waha.statuses["acme"] = "UNREACHABLE"
    site.bot.waha.manage_fail = SendError("waha unreachable: ConnectError")
    admin = site.admin()
    assert "UNREACHABLE" in admin.get("/admin/numbers").text
    assert "UNREACHABLE" in admin.get("/admin/numbers/acme").text
    token = csrf(admin, "/admin/numbers/acme")
    assert "unreachable" in admin.post("/admin/numbers/acme/logout", data={"csrf": token}).text


def test_business_users_cannot_manage_numbers():
    http = Site().business_user()
    assert http.get("/admin/numbers").status_code == 403
    assert http.get("/admin/numbers/acme/qr.png").status_code == 403
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_numbers_pages.py -v`
Expected: FAIL (no `/admin/numbers` routes yet)

- [ ] **Step 3: Implement the inventory screens**

`app/numbers_pages.py`:
```python
"""The purchased-number inventory: add a number, link it by QR code, relink, log out, assign, notes, delete."""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.auth import Session
from app.registry import Number
from app.web import Form, admin_only, redirect, render, route
from app.whatsapp import SendError, session_phone

log = logging.getLogger("numbers")
router = APIRouter()
LIVE = ("SCAN_QR_CODE", "STARTING")  # statuses worth refreshing the page for


def _number(request: Request) -> Number:
    number = request.app.state.registry.number(request.path_params["session"])
    if number is None:
        raise HTTPException(404, "No such number.")
    return number


def _link_page(request: Request, sess: Session, number: Number, error: str = "") -> Response:
    """The number's status, with the QR code while WhatsApp waits for a scan."""
    state = request.app.state
    try:
        info = state.bot.waha.session_info(number.session)
        status = str(info.get("status", "UNKNOWN"))
    except SendError as e:
        info, status = {}, "NOT CREATED" if "404" in str(e) else "UNREACHABLE"
    phone = session_phone(info)
    if status == "WORKING" and phone and phone != number.phone:
        state.registry.set_number_phone(number.session, phone)
        number = state.registry.number(number.session)
    return render(request, "number_link.html", sess, title=number.session, number=number, status=status,
                  error=error, businesses=state.registry.businesses(), now=int(time.time()),
                  refresh=3 if status in LIVE else 0)


@route(router, "/admin/numbers", admin_only, ("GET", "POST"))
def numbers_page(request: Request, sess: Session, form: Form | None) -> Response:
    state = request.app.state
    error, values = "", {"session": "", "notes": ""}
    if form is not None:
        values = {"session": form.get("session"), "notes": form.get("notes")}
        try:
            state.registry.add_number(values["session"], values["notes"], actor=str(sess.user.id))
        except ValueError as e:
            error = str(e)
        else:
            try:
                state.bot.waha.create_session(values["session"], state.settings.waha_webhook_url,
                                              state.settings.waha_webhook_secret)
            except SendError as e:
                error = f"Saved {values['session']}, but WAHA couldn't create it ({e}). Open it and press Relink."
            else:
                return redirect(f"/admin/numbers/{values['session']}")
    rows = [{"n": n, "status": state.bot.waha.status(n.session)} for n in state.registry.numbers()]
    names = {b.id: b.config["business"] for b in state.registry.businesses()}
    return render(request, "numbers.html", sess, title="Numbers", rows=rows, names=names, error=error, **values)


@route(router, "/admin/numbers/{session}", admin_only)
def link_page(request: Request, sess: Session, form: Form | None) -> Response:
    return _link_page(request, sess, _number(request))


@route(router, "/admin/numbers/{session}/qr.png", admin_only)
def qr_image(request: Request, sess: Session, form: Form | None) -> Response:
    number = _number(request)
    try:
        png = request.app.state.bot.waha.qr_png(number.session)
    except SendError:
        return Response(status_code=502)
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


@route(router, "/admin/numbers/{session}/relink", admin_only, ("POST",))
def relink(request: Request, sess: Session, form: Form | None) -> Response:
    state, number = request.app.state, _number(request)
    waha = state.bot.waha
    try:
        try:
            status = waha.session_info(number.session).get("status")
        except SendError as e:
            if "404" not in str(e):
                raise
            waha.create_session(number.session, state.settings.waha_webhook_url, state.settings.waha_webhook_secret)
        else:
            if status in ("STOPPED", "FAILED"):
                waha.start(number.session)
    except SendError as e:
        return _link_page(request, sess, number, error=f"WAHA said: {e}")
    return redirect(f"/admin/numbers/{number.session}")


@route(router, "/admin/numbers/{session}/logout", admin_only, ("POST",))
def logout_number(request: Request, sess: Session, form: Form | None) -> Response:
    state, number = request.app.state, _number(request)
    try:
        state.bot.waha.logout(number.session)
    except SendError as e:
        return _link_page(request, sess, number, error=f"WAHA said: {e}")
    state.registry.audit(str(sess.user.id), number.business_id, "number.logout", {"session": number.session})
    return redirect(f"/admin/numbers/{number.session}")


@route(router, "/admin/numbers/{session}/assign", admin_only, ("POST",))
def assign(request: Request, sess: Session, form: Form | None) -> Response:
    state, number = request.app.state, _number(request)
    try:
        state.registry.assign_number(number.session, form.get("business_id") or None, actor=str(sess.user.id))
    except ValueError as e:
        return _link_page(request, sess, number, error=str(e))
    state.reload()
    return redirect(f"/admin/numbers/{number.session}?ok=assigned")


@route(router, "/admin/numbers/{session}/notes", admin_only, ("POST",))
def notes(request: Request, sess: Session, form: Form | None) -> Response:
    number = _number(request)
    request.app.state.registry.save_number_notes(number.session, form.get("notes"), actor=str(sess.user.id))
    return redirect(f"/admin/numbers/{number.session}?ok=saved")


@route(router, "/admin/numbers/{session}/delete", admin_only, ("POST",))
def delete(request: Request, sess: Session, form: Form | None) -> Response:
    state, number = request.app.state, _number(request)
    try:
        state.registry.delete_number(number.session, actor=str(sess.user.id))
    except ValueError as e:
        return _link_page(request, sess, number, error=str(e))
    for step in (state.bot.waha.logout, state.bot.waha.delete):  # best effort: the number is gone here already
        try:
            step(number.session)
        except SendError:
            log.warning("waha_cleanup_failed step=%s session=%s", step.__name__, number.session)
    return redirect("/admin/numbers?ok=deleted")
```

- [ ] **Step 4: Add the templates**

`app/templates/numbers.html`:
```html
{% extends "base.html" %}
{% block content %}
<h1>Purchased numbers</h1>
<p>Each number is a SIM in a spare phone, linked like WhatsApp Web. Keep every phone online at least once every 14 days.</p>
<table>
  <thead><tr><th>Session</th><th>Phone</th><th>Status</th><th>Business</th><th>Notes</th></tr></thead>
  <tbody>
  {% for r in rows %}
  <tr>
    <td><a href="/admin/numbers/{{ r.n.session }}">{{ r.n.session }}</a></td>
    <td>{% if r.n.phone %}+{{ r.n.phone }}{% endif %}</td>
    <td><span class="badge {{ 'good' if r.status == 'WORKING' else 'bad' }}">{{ r.status }}</span></td>
    <td>{{ names.get(r.n.business_id, "—") }}</td>
    <td>{{ r.n.notes }}</td>
  </tr>
  {% else %}
  <tr><td colspan="5">No numbers yet.</td></tr>
  {% endfor %}
  </tbody>
</table>
<h2>Add a number</h2>
<form method="post" action="/admin/numbers">
  <input type="hidden" name="csrf" value="{{ csrf }}">
  <div class="grid">
    <input name="session" placeholder="Session name, e.g. sweetbakes-1" aria-label="Session name" value="{{ session }}" required>
    <input name="notes" placeholder="Notes: carrier, SIM cost, renewal date" aria-label="Notes" value="{{ notes }}">
    <button type="submit">Add and show the QR code</button>
  </div>
</form>
{% endblock %}
```

`app/templates/number_link.html`:
```html
{% extends "base.html" %}
{% block content %}
<p><a href="/admin/numbers">← All numbers</a></p>
<h1>{{ number.session }}</h1>
<p>Status: <span class="badge {{ 'good' if status == 'WORKING' else 'bad' }}">{{ status }}</span>{% if number.phone %} · +{{ number.phone }}{% endif %}</p>
{% if status == "SCAN_QR_CODE" %}
<p>On the purchased phone open WhatsApp → Settings → Linked devices → Link a device, and scan:</p>
<img class="qr" src="/admin/numbers/{{ number.session }}/qr.png?t={{ now }}" alt="QR code that links this number">
<p><small>This page refreshes every 3 seconds.</small></p>
{% elif status == "WORKING" %}
<p class="notice ok">Linked. Add this number to the business's WhatsApp groups; it introduces itself there.</p>
{% elif status == "STARTING" %}
<p>Starting... this page refreshes every 3 seconds.</p>
{% else %}
<p>Not running. Press <em>Relink</em> to start it and get a new QR code.</p>
{% endif %}
<div class="grid">
  <form method="post" action="/admin/numbers/{{ number.session }}/relink">
    <input type="hidden" name="csrf" value="{{ csrf }}"><button type="submit" class="secondary">Relink</button></form>
  <form method="post" action="/admin/numbers/{{ number.session }}/logout">
    <input type="hidden" name="csrf" value="{{ csrf }}"><button type="submit" class="secondary">Log out</button></form>
  {% if not number.business_id %}
  <form method="post" action="/admin/numbers/{{ number.session }}/delete">
    <input type="hidden" name="csrf" value="{{ csrf }}"><button type="submit" class="secondary">Delete</button></form>
  {% endif %}
</div>
<h2>Business</h2>
<form method="post" action="/admin/numbers/{{ number.session }}/assign">
  <input type="hidden" name="csrf" value="{{ csrf }}">
  <select name="business_id" aria-label="Business">
    <option value="">(unassigned)</option>
    {% for b in businesses %}<option value="{{ b.id }}"{% if b.id == number.business_id %} selected{% endif %}>{{ b.config.business }}</option>{% endfor %}
  </select>
  <button type="submit">Save</button>
</form>
<h2>Notes</h2>
<form method="post" action="/admin/numbers/{{ number.session }}/notes">
  <input type="hidden" name="csrf" value="{{ csrf }}">
  <input name="notes" value="{{ number.notes }}" aria-label="Notes">
  <button type="submit">Save notes</button>
</form>
{% endblock %}
```

- [ ] **Step 5: Mount the inventory screens**

In `app/main.py`, add to the `app.` import group:
```python
from app import numbers_pages
```
and right after `app.include_router(admin_pages.router)`, add:
```python
    app.include_router(numbers_pages.router)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_numbers_pages.py -v`
Expected: PASS (6 passed)

Run: `uv run pytest -q && uv run ruff check .`
Expected: all tests pass; `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add app/numbers_pages.py app/main.py app/templates/numbers.html app/templates/number_link.html tests/test_numbers_pages.py
git commit -m "feat: purchased-number inventory with QR linking from the browser"
```

### Task 13: Deployment and operator docs

**Files:**
- Modify: `Caddyfile`, `docker-compose.yml`, `Dockerfile`, `.env.example`, `README.md`, `docs/setup-guide.md`

**Interfaces:**
- Consumes: every route from Tasks 6–12; `python -m app.cli` (Task 8); `Settings.public_url`, `secret_key` (Task 2).
- Produces: Caddy serves the dashboard and both Meta webhook forms; the engine gets `PUBLIC_URL=https://${DOMAIN}`; `python` inside the engine container is the app's own environment (so `docker compose exec engine python -m app.cli ...` works); `.env.example` documents `SECRET_KEY`; the README and the setup guide explain the dashboard.

- [ ] **Step 1: Open the dashboard paths in Caddy**

In `Caddyfile`, replace the line
```
	@public path /webhooks/meta /health
```
with (tab-indented like the rest of the file):
```
	@public path / /login /login/* /logout /invite/* /admin /admin/* /app /app/* /static/* /webhooks/meta /webhooks/meta/* /health
```

- [ ] **Step 2: Give the engine its public URL, put its Python first on the PATH, document `SECRET_KEY`**

In `docker-compose.yml`, in the `engine` service's `environment:` block, add after `WAHA_URL: http://waha:3000`:
```yaml
      PUBLIC_URL: https://${DOMAIN}  # the dashboard's webhook addresses and invite links
```

In `Dockerfile`, add right after the line `ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy`:
```dockerfile
ENV PATH="/srv/.venv/bin:$PATH"
```
Without it, `python` in the container is the image's bare Python, which lacks the app's packages, so `docker compose exec engine python -m app.cli ...` fails with `ModuleNotFoundError`.

In `.env.example`, add right after the `LOG_HASH_KEY=` line:
```
# Encrypts the Meta keys and two-step secrets the dashboard saves. Required. Changing it means re-entering Meta keys.
SECRET_KEY=
```
and replace the comment line `# Public HTTPS name for Caddy (Meta's webhook)` with:
```
# Public HTTPS name for Caddy (the dashboard and Meta's webhooks); compose sets PUBLIC_URL=https://$DOMAIN
```

- [ ] **Step 3: Document the dashboard in the README**

In `README.md`, insert this section right before the line `## One-time setup for a pilot client`:
```markdown
## The dashboard

`https://$DOMAIN/` is a web dashboard:
- **Admins** see every business and number: add a business, paste its Meta keys, link purchased numbers by QR code, invite logins, pause a business, and read chats and the audit log.
- **Each business** logs in to change its bot settings, staff, groups and Sheet permissions, and to read its chats.

1. Set `SECRET_KEY` in `.env` (`openssl rand -hex 32`). The engine won't start without it. It encrypts the Meta keys stored in the database, so changing it means re-entering them.
2. Run `docker compose up -d --build`, then create your admin login: `docker compose exec engine python -m app.cli create-admin you@example.com`. Open the printed link, set a password, and set up two-step login with an authenticator app.
3. Locked out? `docker compose exec engine python -m app.cli admin-link you@example.com` prints a fresh link (it resets the password and the two-step login).
4. Each business has its own Meta webhook address, `https://$DOMAIN/webhooks/meta/<business-id>`, shown with its verify token on the business's *Official number* page.

Upgrading from `clients.yaml`: the first start with an empty dashboard database imports `clients.yaml` and the `.env` Meta keys once. After that the dashboard is the source of truth and `clients.yaml` is ignored. The old address `https://$DOMAIN/webhooks/meta` keeps working for businesses on the `.env` Meta app.

```

Also in `README.md`:
- Replace `A WhatsApp AI assistant for one business at a time:` with `A WhatsApp AI assistant for small businesses, run for many businesses from one server:`.
- Replace the line `` Design: `docs/superpowers/specs/2026-09-23-whatsapp-engine-design.md`. `` with `` Design: `docs/superpowers/specs/2026-09-23-whatsapp-engine-design.md` (engine) and `docs/superpowers/specs/2026-09-28-dashboard-admin-design.md` (dashboard). ``
- In `## Local development`, replace `` `.env`, `clients.yaml` and the Google key in `secrets/`. `` (the start of the paragraph's second line) with `` `.env` (with `SECRET_KEY`), the Google key in `secrets/` and, on the first start only, `clients.yaml`. ``
- In `### 4. WAHA (purchased number, groups)`, replace step 5 with:
```markdown
5. Add the number to the client's groups. The bot introduces itself on join. Then, in the dashboard, open the business → **Staff & groups**, tick the staff group and pick the group that gets "needs a person" alerts. No restart needed.
```

- [ ] **Step 4: Add the dashboard to the setup guide**

In `docs/setup-guide.md`:

1. In the `## Contents` list, replace the last three items with:
```markdown
13. [Part K: the dashboard](#13-part-k-the-dashboard)
14. [Day-to-day tasks](#14-day-to-day-tasks)
15. [Troubleshooting](#15-troubleshooting)
16. [Glossary](#16-glossary)
```
2. Rename the headings `## 13. Day-to-Day Tasks`, `## 14. Troubleshooting` and `## 15. Glossary` to `## 14. Day-to-Day Tasks`, `## 15. Troubleshooting` and `## 16. Glossary`.
3. In `### Create .env`, change the bullet that starts `` - `LOG_HASH_KEY`, `WAHA_API_KEY`, `` so its list of names reads `` `LOG_HASH_KEY`, `SECRET_KEY`, `WAHA_API_KEY`, `WAHA_WEBHOOK_SECRET`, `WAHA_DASHBOARD_PASSWORD` ``.
4. In `## 4. Part B: clients.yaml, Field by Field`, replace the sentence `` `clients.yaml` holds every setting for every client — the engine reads it once at startup. `` with:
```markdown
`clients.yaml` holds the settings for your first client. On its very first start the engine copies them into its database; after that you change settings in the dashboard (Part K), and later edits to `clients.yaml` are ignored.
```
5. Right under the heading `## 8. Part F: Connect Meta's Webhook`, add:
```markdown
> **With the dashboard (Part K):** every business also has its own webhook address, shown with its verify token on the business's **Official number** page. This first business can keep the address below: it keeps working for the business whose Meta keys are in `.env`. Businesses you add later must use their own address.
```
6. Right under the heading `### Link WAHA to the phone`, add:
```markdown
> **Your first business's number** is linked here, over the SSH tunnel, with the session name from `clients.yaml`. For every later business, add and link its number in the dashboard instead (Part K, **Numbers → Add a number**): no tunnel needed.
```
7. In `### Add the bot to groups`, replace steps 9 and 10 (from the line starting `9. List the client's group ids` down to the end of step 10's second code block, the one with `docker compose restart engine`) with:
```markdown
9. Tell the bot which group is the staff group, in the dashboard. If you haven't made your admin login yet, do Part K, "Create your admin login", now. Then open `https://<your-domain>/admin` → your business → **Staff & groups**, tick **Staff group** next to the staff group, pick the same group under **Gets "needs a person" alerts**, and press **Save**.
   - You should see: "Saved." The bot uses it from the next message; no restart needed.
```
and renumber the next step, `11. Check`, to `10. Check`.
8. Right under the heading `### If the purchased number gets banned`, add:
```markdown
> **With the dashboard (Part K):** step 2 is easier: open **Numbers** → the number → **Log out**, then **Relink**, and scan the new QR code with the new phone. No SSH tunnel needed.
```
9. In the Day-to-Day Tasks part, replace the two bullets that start `- **Add a staff member or group:**` and `- **Add a new tab:**` (four lines in all) with:
```markdown
- **Add a staff member or group:** in the dashboard, open the business → **Staff & groups**, add the number or
  tick the group, and press **Save**. The bot uses it from the next message.
- **Add a new tab:** create the tab and its header row in the Sheet, then in the dashboard open the business →
  **Sheet**, tick "the bot uses this tab", choose what customers may do, and press **Save permissions**.
- **Add a new business:** follow Part K, "Add a business".
```
10. In the Troubleshooting part: replace the text `(open the dashboard through the SSH` + line break + `  tunnel and relink it — Part G)` with `(relink it: in the dashboard, **Numbers** → the` + line break + `  number → **Relink**; or through the SSH tunnel as in Part G)`; and replace `` without updating `clients.yaml`. `` with `without updating the business's **Sheet** page in the dashboard.`
11. In the Glossary part, replace the two-line bullet that starts `- **Session (WAHA):**` with:
```markdown
- **Session (WAHA):** one connected WhatsApp login inside WAHA, identified by a name you choose. The
  dashboard's **Numbers** page lists them; each business gets one on its **Group number** page.
- **Dashboard:** the engine's own website at `https://<your-domain>/`, where you manage businesses, numbers
  and logins (Part K). Not the same as WAHA's dashboard, which only opens through the SSH tunnel.
```
12. Insert this whole part right before the line `## 14. Day-to-Day Tasks`:
````markdown
## 13. Part K: The Dashboard

The engine has a web dashboard at `https://<your-domain>/`. **You** (the admin) manage every business and number there. **Each business** gets its own login to change its bot settings, staff and Sheet permissions, and to read its chats.

### Create your admin login (once)

1. Check that `.env` has `SECRET_KEY` (Part E).
   **bash, on the server:**
   ```bash
   cd Whatsapp-assistant
   grep SECRET_KEY .env
   ```
   You should see: `SECRET_KEY=` followed by a long random value. If it's empty, put one in with `openssl rand -hex 32` and run `docker compose up -d`.
   > **Warning:** keep `SECRET_KEY` safe and don't change it. It encrypts the Meta keys saved in the dashboard; if it changes, you must re-enter every business's Meta keys.
2. Create your login.
   **bash, on the server:**
   ```bash
   docker compose exec engine python -m app.cli create-admin you@example.com
   ```
   You should see: one line starting with `https://<your-domain>/invite/`.
3. Open that link on your laptop and choose a password (at least 10 characters). Then log in at `https://<your-domain>/login`.
4. Two-step login: install **Google Authenticator** (or Microsoft Authenticator) on your phone, choose **Enter a setup key**, type the key the page shows, then type the 6-digit code from the app. From now on you type a fresh code after your password each time.
   - Lost your phone? On the server run `docker compose exec engine python -m app.cli admin-link you@example.com`. It prints a new link that resets your password and your two-step login.

### Add a business

1. Ask the business to share its Google Sheet with the service-account email (Part A) as **Editor**.
2. In the dashboard: **Businesses → Add a business**. Fill in the names, the time zone, the Sheet id and the instructions, and the web id (for example `sweetbakes`; leave it empty to get one made from the business name). Press **Check Sheet access**.
   You should see: "The Sheet is readable" and each tab with its columns. Then press **Create business**.
3. **Sheet** tab: tick which tabs the bot uses and what customers may do on each one (Part B explains read, own rows and add rows). Press **What a customer would see** to check before you save.
4. **Staff & groups** tab: add staff numbers with the country code (for example `+92 300 1111111`). Once a group number is linked, tick the staff groups and the group that gets alerts.
5. **Official number** tab: paste the business's Meta **phone number ID**, **access token** and **app secret** (Part C) and press **Save keys**, then **Test connection**.
   You should see: the number and the business's verified name. Copy the **Callback URL** and **Verify token** from this page into the business's Meta app webhook settings (Part F) and subscribe to `messages`.
6. **Numbers** (top menu) → **Add a number**: type a session name (for example `sweetbakes-1`) and notes (carrier, SIM cost, renewal date), press **Add and show the QR code**, and scan it with the purchased phone (WhatsApp → Settings → Linked devices → Link a device).
   You should see: the status change to `WORKING`. Then open the business's **Group number** tab, pick this number and save.
7. **Logins** tab: type the owner's email and press **Create login**. Send them the one-time link it shows (it works for 7 days). They set their own password and log in at `https://<your-domain>/login`.

### Pause a business

A business that stops paying: open it and press **Pause business**. The bot ignores all its messages (so there are no Meta charges); nothing is deleted. **Resume business** turns it back on.

### Dashboard click-through test

1. Log in as admin. The Businesses page lists your businesses, and the group number shows `WORKING`.
2. Add a test business. Its home page opens with "Business created."
3. Change its bot name on **Bot settings**, then message its official number: the reply uses the new name (no restart needed).
4. Invite a business login, open the link in a private browser window, set a password and log in: you see only that business.
5. As that business login, open `https://<your-domain>/admin`: you get "Not allowed".
6. **Numbers → Add a number** shows a QR code; after scanning, the status becomes `WORKING` and the phone number appears.
7. Pause the test business: a message to its number gets no reply. Resume it.

### Upgrading from clients.yaml

If you ran the engine before the dashboard existed: add `SECRET_KEY` to `.env`, then run `git pull` and `docker compose up -d --build`. On that first start the engine copies `clients.yaml` and the Meta keys from `.env` into the dashboard database, once. After that, change settings only in the dashboard (`clients.yaml` is ignored). The first business keeps working on the old webhook address `https://<your-domain>/webhooks/meta`; switch it to its own address (on its Official number tab) whenever convenient.

````

- [ ] **Step 5: Verify the stack**

Run: `uv run pytest -q && uv run ruff check .`
Expected: all tests pass; `All checks passed!`

Run (Git Bash; `MSYS_NO_PATHCONV=1` stops Git Bash rewriting the `/srv/...` and `/etc/...` paths):
```bash
test -f .env || cp .env.example .env
docker compose config --quiet
docker build -t whatsapp-assistant .
docker run --rm whatsapp-assistant python -c "import app.main, app.web, app.pages, app.admin_pages, app.numbers_pages, app.cli; print('ok')"
MSYS_NO_PATHCONV=1 docker run --rm whatsapp-assistant ls /srv/app/templates /srv/app/static
MSYS_NO_PATHCONV=1 docker run --rm -e DOMAIN=localhost -v "$(pwd)/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2 caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
```
Expected: no output from `config --quiet`; the image builds; `ok`; both folders are listed (with `base.html` and `pico.min.css`); Caddy prints `Valid configuration`.

- [ ] **Step 6: Commit**

```bash
git add Caddyfile docker-compose.yml Dockerfile .env.example README.md docs/setup-guide.md
git commit -m "docs: dashboard setup, public paths and SECRET_KEY"
```

- [ ] **Step 7: Owner checkpoint: live dashboard test**

On the VPS, after `docker compose up -d --build`, work through **Part K → Dashboard click-through test** in `docs/setup-guide.md`. It also confirms the two go-live risks from the spec (§13): WAHA's real group-list and QR responses on the GOWS session, and Meta's answer to **Test connection**.
