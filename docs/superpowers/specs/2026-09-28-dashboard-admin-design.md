# Dashboard and Admin Console (v2) — Design

**Date:** 2026-09-28 · **Owner:** Jawad · **Status:** design approved in brainstorming (sections 1–3); this document awaits owner review.
**Builds on:** `docs/superpowers/specs/2026-09-23-whatsapp-engine-design.md` (the v1 engine, now on `main`).

## 1. Goal

v1 runs one business, configured by hand in `clients.yaml` and `.env`, with numbers linked over an SSH tunnel.
v2 lets the owner sell to many businesses without touching the server:

- **The owner (admin)** onboards a business, links its purchased group number by scanning a QR code in the browser,
  pastes its Meta keys, sees every number's status at a glance, and reads any chat.
- **Each business** logs in to its own dashboard to change its bot's settings, staff, Sheet permissions and to read
  its chats.

This is sub-project 2 from the v1 spec §1. Billing (sub-project 3) stays out.

## 2. Users and success criteria

| Role | Who | Sees |
|---|---|---|
| `admin` | The owner and anyone they add | Every business and every number |
| `business` | Staff of one business (several logins per business allowed) | Only their own business |

Success means:
1. A new business is live — Sheet checked, official number connected, group number linked, logins handed out —
   using only the browser.
2. The admin overview shows every number's status and this month's reply counts on one page.
3. A business changes its bot name, instructions, staff and tab permissions itself, and the bot uses the change on
   its very next message, with no restart.
4. No business can see or change another business's data.

## 3. Scope

**In:** admin console, business dashboard, per-business Meta credentials and webhook URL, WAHA session management
from the browser, database-backed business settings with a one-time import from `clients.yaml`, invites,
two-step login for admins, audit log, chat viewer, monthly reply counts.

**Out of v2:** public sign-up, billing and payments, sending email, Meta Embedded Signup / Tech Provider onboarding,
document upload or search, editing Sheet rows from the dashboard, charts, more than one group number per business,
languages other than English, a mobile app.

## 4. Architecture

Everything stays in the one FastAPI service, container and SQLite file from v1.

```
Browser ── Caddy ── engine (FastAPI)
                     ├─ webhooks (v1) ─ Bot ─ Store / Sheets / LLM / Meta / WAHA
                     ├─ web.py          login, invites, two-step login, CSRF, page rendering
                     ├─ pages.py        business screens (mounted for businesses and for admins)
                     ├─ admin_pages.py  admin-only screens
                     ├─ registry.py     businesses, numbers, audit  ─┐
                     ├─ auth.py         users, sessions              ├─ db.py (shared SQLite connection)
                     └─ vault.py        encrypts Meta keys and TOTP secrets
```

New modules and their single jobs:

| Module | Job |
|---|---|
| `app/db.py` | `Db`: one SQLite connection behind a lock, with `all`, `one`, `write`, `script` helpers. Shared by `Registry` and `Auth`. (`Store` keeps its own connection to the same file.) |
| `app/vault.py` | `Vault(secret_key)`: `seal(text) -> str` and `open(token) -> str` using Fernet from `cryptography`, keyed by SHA-256 of `SECRET_KEY`. `open` raises `VaultError` when the key changed. |
| `app/registry.py` | `Registry(db, vault)`: businesses, numbers inventory, audit log, `clients() -> dict[str, Client]`, the first-run import. |
| `app/auth.py` | `Auth(db, vault)`: users, invites, passwords, sessions, TOTP, login rate limit. |
| `app/web.py` | Shared web plumbing: templates, the logged-in-user dependencies, CSRF check, form parsing, security headers, and the login / logout / invite / two-step routes. |
| `app/pages.py` | The business screens (home, bot settings, staff & groups, Sheet & permissions, chats), written once and mounted at `/app/...` (business from the login) and `/admin/b/{business_id}/...` (admins only). |
| `app/admin_pages.py` | Admin-only screens: overview, new business, official number, group number, logins, audit log, numbers inventory, admins. |
| `app/cli.py` | `python -m app.cli create-admin EMAIL` (prints an invite link) and `python -m app.cli admin-link EMAIL` (a fresh invite link for a locked-out admin). |
| `app/templates/*.html` | Jinja2 pages extending one `base.html`. |
| `app/static/` | Vendored `htmx.min.js` and `pico.min.css` (no CDN), plus a small `app.css`. |

**Live settings.** `Bot.clients` becomes a value the app replaces: every successful save calls
`app.state.reload()`, which sets `bot.clients = registry.clients()` (one atomic attribute swap). Webhook routes and
`/health` build their phone-number and session lookups from `bot.clients` on each request instead of once at start.
A message already in flight finishes with the settings it started with.

**New dependencies:** `jinja2` (templates) and `cryptography` (Fernet). Forms are parsed with
`urllib.parse.parse_qs`, so `python-multipart` is not needed.

## 5. Data model

New tables live in the same SQLite file as `messages` (so daily backups include them). Meta keys and TOTP secrets
are stored sealed by `Vault`; everything else is plain.

```sql
CREATE TABLE businesses (
  id TEXT PRIMARY KEY,                 -- slug: lowercase letters, digits, dashes; 3-32 chars; e.g. "sweetbakes"
  config TEXT NOT NULL,                -- JSON, same keys as a v1 clients.yaml entry, minus meta_phone_number_id
                                       -- and waha_session (see below)
  meta_phone_number_id TEXT UNIQUE,    -- NULL until set
  meta_access_token TEXT,              -- sealed; NULL until set
  meta_app_secret TEXT,                -- sealed; NULL until set
  meta_verify_token TEXT NOT NULL,     -- generated at creation (secrets.token_urlsafe(24)); shown to paste into Meta
  active INTEGER NOT NULL DEFAULT 1,   -- 0 = paused: Registry.clients() leaves it out, so the bot ignores its messages
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE numbers (                 -- the purchased group numbers (one WAHA session each)
  session TEXT PRIMARY KEY,            -- WAHA session name: lowercase letters, digits, dashes; 3-32 chars
  business_id TEXT UNIQUE REFERENCES businesses(id),  -- NULL = unassigned; UNIQUE = one number per business
  phone TEXT NOT NULL DEFAULT '',      -- digits, filled in from WAHA once linked
  notes TEXT NOT NULL DEFAULT '',      -- free text: carrier, SIM cost, renewal date
  created_at REAL NOT NULL
);
CREATE TABLE audit (
  id INTEGER PRIMARY KEY,
  at REAL NOT NULL,
  actor TEXT NOT NULL,                 -- user id, or "system" for the import
  business_id TEXT,
  action TEXT NOT NULL,                -- e.g. business.create, settings.save, meta.save, number.assign, user.invite
  detail TEXT NOT NULL DEFAULT ''      -- JSON of changed field names and new values; secrets become "(changed)"
);
CREATE TABLE users (
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  name TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL CHECK (role IN ('admin', 'business')),
  business_id TEXT REFERENCES businesses(id),
  password_hash TEXT,                  -- NULL until the invite is accepted
  totp_secret TEXT,                    -- sealed; admins only; NULL until set up
  invite_hash TEXT,                    -- SHA-256 of the invite token
  invite_expires REAL,
  disabled INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  CHECK ((role = 'admin') = (business_id IS NULL))
);
CREATE TABLE sessions (
  token_hash TEXT PRIMARY KEY,         -- SHA-256 of the cookie value
  user_id INTEGER NOT NULL REFERENCES users(id),
  csrf TEXT NOT NULL,
  mfa_ok INTEGER NOT NULL DEFAULT 0,   -- admins: 1 once the TOTP step passed
  expires_at REAL NOT NULL
);
```

The business `config` JSON is validated by the same code that validated `clients.yaml` (§6.2), so the engine's
permission rules are unchanged: `business`, `bot_name`, `sheet_id`, `timezone`, `date_format`, `instructions`,
`knowledge_tab`, `handoff_tab`, `staff_chats`, `staff_numbers` (stored as digits), `staff_alert_chat`,
`retention_days`, `tabs` (tab → `{customer: [...], owner_column, fill}`).

## 6. Engine changes

### 6.1 Settings and Client

- `Settings` gains `secret_key` (required: `create_app` raises `RuntimeError("Set SECRET_KEY in .env ...")` when
  empty), `public_url` (e.g. `https://bot.example.com`; compose sets it to `https://${DOMAIN}`; used for webhook URLs
  and invite links) and `waha_webhook_url` (default `http://engine:8000/webhooks/waha`, used when creating WAHA
  sessions).
- `Client` gains `meta_access_token`, `meta_app_secret` and `meta_verify_token`, all `field(default="", repr=False)`
  so they never appear in logs or tracebacks.

### 6.2 Business settings from the database

- `app/config.py`: the per-entry body of `load_clients` moves into `client_from_dict(business_id, raw) -> Client`
  (same validation: access words, `own` needs `owner_column`, `fill` values, time zone). `load_clients(path)` keeps
  working by calling it for each YAML entry.
- `Registry.clients()` builds a `Client` for each **active** business from `config` plus `meta_phone_number_id`,
  the assigned number's `session` as `waha_session`, and the opened Meta secrets. A paused business is left out, so
  its webhooks find no business and its messages are ignored (still with a 200). A business whose sealed secrets can't be opened (the
  `SECRET_KEY` changed) loads without Meta keys and shows "re-enter keys" on its admin page.
- Every save validates with `client_from_dict` before writing; a `ValueError` goes back to the form.

### 6.3 Per-business Meta webhook and keys

- New routes `GET` and `POST /webhooks/meta/{business_id}`:
  - `GET` answers Meta's handshake only when `hub.verify_token` equals that business's `meta_verify_token`
    (constant-time compare).
  - `POST` checks the signature with that business's `meta_app_secret`, then parses with a lookup that holds **only
    that business's** `meta_phone_number_id`. A message addressed to any other number is ignored with a 200, so one
    business's Meta app can't inject messages into another business. Unknown `business_id` → 404.
- The v1 routes `GET/POST /webhooks/meta` stay for the pilot: they use `META_APP_SECRET` / `META_VERIFY_TOKEN` from
  `.env` and route only to businesses that have no app secret of their own or whose app secret equals
  `META_APP_SECRET`.
- `MetaClient.send_text(..., token=None)` and `MetaClient.download(media_id, token=None)` use the given token, else
  the `.env` token. `Bot` passes `client.meta_access_token or None`.
- `MetaClient.number_info(phone_number_id, token) -> dict` (`GET /{id}?fields=display_phone_number,verified_name`)
  powers "Test connection"; a failure raises `SendError` carrying Meta's status, code and message.

### 6.4 WAHA session management

`WahaClient` gains, each returning plain data or raising `SendError` when WAHA fails or is unreachable:

| Method | WAHA call |
|---|---|
| `create_session(name, webhook_url, webhook_secret)` | `POST /api/sessions` with `start: true` and a webhook for events `message` and `group.v2.join`, signed with `WAHA_WEBHOOK_SECRET` |
| `start(name)` / `logout(name)` / `delete(name)` | `POST /api/sessions/{name}/start`, `POST .../logout`, `DELETE /api/sessions/{name}` |
| `session_info(name) -> dict` | `GET /api/sessions/{name}` (status, and `me.id` once linked); `status()` reuses it |
| `qr_png(name) -> bytes` | `GET /api/{name}/auth/qr?format=image` |
| `groups(name) -> list[dict]` | `GET /api/{name}/groups`, normalised to `{"id", "name"}` from the known engine shapes (`id` / `id._serialized` / `JID`; `subject` / `name` / `Name`) |

### 6.5 Sheets additions

- `Sheets.tabs(sheet_id) -> dict[str, list[str]]`: every worksheet title with its trimmed header row (for "Check
  access" and the permission editor).
- `service_account_email(path) -> str`: the `client_email` from the Google key file, shown as "share your Sheet with".

### 6.6 Store additions

- `conversations(client_id, limit=100)`: one row per chat — `chat_id`, `channel`, last message time, last human
  sender name, message count — newest first.
- `chat(client_id, chat_id, limit=200)`: that chat's messages, oldest first. Always filtered by `client_id`.
- `replies_since(client_id, since) -> dict[str, int]`: bot messages per channel (`meta`, `waha`) since a time;
  the pages pass the start of the month in the business's time zone.

### 6.7 First-run import

On startup, when the `businesses` table is empty and `CLIENTS_FILE` exists, the app imports it once:
each entry becomes a business (id = its YAML key); `meta_phone_number_id` moves to its column; if `.env` has
`META_ACCESS_TOKEN` / `META_APP_SECRET`, they are sealed into that business and `meta_verify_token` is set to
`META_VERIFY_TOKEN`, so the webhook already configured at Meta keeps verifying; `waha_session` becomes a `numbers` row
assigned to it; the audit log records `business.import` by `system`. After that the database is the source of truth
and `clients.yaml` is ignored (the app logs this once at startup).

## 7. Accounts and security

- **No public sign-up.** An admin creates a login (email, name, role, business) and receives a one-time invite link
  `{public_url}/invite/{token}` valid for 7 days. The person opens it and sets a password. A forgotten password is
  solved the same way: the admin creates a fresh link (the old password stops working and all sessions end). The
  first admin comes from `python -m app.cli create-admin EMAIL`.
- **Passwords:** at least 10 characters; stored as `scrypt$16384$8$1$<salt>$<hash>` via `hashlib.scrypt`; compared
  in constant time; never logged.
- **Two-step login (admins, required):** after the password, a 6-digit TOTP code (RFC 6238: SHA-1, 30 s steps, one
  step of clock drift allowed). First login shows the secret as text and as an `otpauth://` link to add to Google
  Authenticator or similar, then asks for a code before finishing. The secret is sealed. Business users: password only.
- **Sessions:** cookie `wa_session` (random 32 bytes, `HttpOnly`, `Secure`, `SameSite=Lax`, path `/`); the database
  stores its SHA-256. Admin sessions end 12 hours after login, business sessions 7 days after. Logout deletes the
  session; a new invite link, disabling a user or losing admin rights deletes all of that user's sessions.
- **CSRF:** every signed-in `POST` must carry the session's CSRF token (hidden form field `csrf`, or header
  `X-CSRF-Token` for htmx requests, set once on `<body>` with `hx-headers`). Missing or wrong → 403.
- **Login rate limit:** 5 failed attempts for one email within 15 minutes pause that email for 15 minutes (in
  memory; a restart clears it). Failed logins are logged with a hash of the email, never the email itself.
- **Isolation:** `/app/...` routes require `role = business` and never take a business id — it comes from the
  session. Chat ids from the URL are always looked up together with the session's business, so another business's
  chat returns 404. `/admin/...` requires `role = admin` with `mfa_ok = 1` (business sessions are created with
  `mfa_ok = 1`, since they have no second step).
- **Meta keys are write-only:** pages show "saved, ends in ••••1234"; changing one means typing a new value; only
  admins see the Official number screen.
- **Headers on every page:** `Content-Security-Policy: default-src 'self'; img-src 'self' data:; frame-ancestors
  'none'; form-action 'self'`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: same-origin`. htmx is configured with `includeIndicatorStyles: false` so no inline styles are
  needed.
- **Logs** keep the v1 rules: no message text, chat ids only as the 12-character HMAC.

## 8. Screens

Server-rendered pages (Jinja2 + Pico.css), with htmx for the small live parts (QR refresh, "Check access",
permission preview). English only. Every page shows a success or error banner after a save.

### 8.1 Sign-in pages

`/login` (email + password), `/login/totp` (code; first time: setup), `/invite/{token}` (set password), `/logout`
(POST). `/` sends admins to `/admin` and business users to `/app`.

### 8.2 Admin console (`/admin`)

- **Overview:** one row per business — official number status (not set / keys saved / last message time), group
  number status from WAHA (`WORKING`, needs QR, stopped, unreachable), official and group replies this month (Meta
  bills official replies after 1,000 a month), and a link to the business.
- **New business:** id (suggested from the name), business name, bot name, time zone (dropdown), instructions,
  Sheet id; the page shows the service-account email to share the Sheet with and a **Check access** button listing
  the tabs and their columns. Creating it sets `knowledge_tab` and `handoff_tab` to `Knowledge` / `Handoffs` if those
  tabs exist, and no customer permissions (staff-only) until someone sets them.
- **Business page** (`/admin/b/{id}`): the business screens from §8.3, plus:
  - **Official number:** phone number ID, access token, app secret (write-only); shows the webhook URL
    `{public_url}/webhooks/meta/{id}` and the verify token to paste into Meta; **Test connection** shows the number
    and verified name Meta returns, or Meta's error.
  - **Group number:** assign one unassigned number from the inventory, or unassign.
  - **Logins:** list, invite, new link, disable.
  - **Pause / Resume:** a paused business's bot ignores all messages on both numbers; its settings, number and
    logins stay, and its dashboard shows a "paused" banner. Deleting a business is out of v2.
  - **Audit log:** newest first.
- **Numbers** (`/admin/numbers`): every purchased number — session, phone, live status, assigned business, notes.
  **Add number** (session name + notes) creates the WAHA session and opens the link page: the QR image refreshes
  and the status is polled every 3 seconds until `WORKING`, then the phone is saved from WAHA's `me.id`. Also
  **Relink** (start + QR), **Log out**, **Assign / Unassign**, **Delete** (only when unassigned; logs out and deletes
  the WAHA session).
- **Admins** (`/admin/admins`): invite, new link, disable.

### 8.3 Business screens (`/app` for a business; `/admin/b/{id}` for admins)

- **Home:** both numbers' status, replies this month by channel, and the 10 newest rows of the Handoffs tab (or
  "couldn't read the Handoffs tab").
- **Bot settings:** bot name, business name, instructions, time zone, date format (dropdown of common formats,
  e.g. `%d/%m/%Y`, `%m/%d/%Y`, `%Y-%m-%d`, `%d-%m-%Y`, `%d.%m.%Y`) with a live example
  ("15/06/2026 → 2026-06-15"), retention days (admins only).
- **Staff & groups:** staff numbers, one per line, in international format starting with `+` (stored as digits);
  staff groups chosen by checkbox from the group number's own list of groups, and the alert group by radio button.
  Without a linked group number the page says "Link a group number first".
- **Sheet & permissions:** the email to share with and **Check access**; then one row per tab found in the Sheet:
  - customers can **read all rows** / **see their own rows** (then pick the owner column) / **add rows** (then pick
    which columns get the customer's WhatsApp name and phone); none ticked = staff only;
  - the Knowledge and Handoffs tab selectors;
  - a **What a customer would see** button per tab (§8.4).
- **Chats:** conversation list (name or number, channel, last message time, message count) → the full history,
  read-only. Messages older than `retention_days` are gone, as in v1.

### 8.4 Guardrails for Sheet permissions

- Only tabs that exist in the Sheet (per **Check access**) can be given permissions; `own` requires an owner
  column that is one of that tab's headers; `fill` columns must be headers too.
- **Phone-like columns:** a tab gets a warning when any header contains `phone`, `mobile`, `whatsapp`, `number`,
  `contact`, `email` or `cnic` (case-insensitive). Saving "read all rows" on such a tab needs an extra tick, "I
  understand every customer can see these columns"; without it the save is refused with that message.
- **Preview:** runs the engine's real `lookup_rows` against the Sheet with the *unsaved* form values, as a sample
  customer (for `own` tabs, the customer whose number is in the first data row) — shows up to 5 rows or the exact
  error a customer would get.

## 9. Error handling

- **WAHA unreachable or failing:** status reads "unreachable"; actions show WAHA's error in the banner; pages still
  render.
- **Sheet not shared / wrong id / tab missing:** "Share the Sheet with {email} as Editor", "No Sheet with that id",
  "Tab 'Orders' is not in the Sheet".
- **Meta test fails:** Meta's status, error code and message in the banner.
- **Invalid input:** the form is re-rendered with the entered values and the message next to the field;
  nothing is saved.
- **Vault can't open a secret:** that business loads without Meta keys; its admin page asks to re-enter them.
- **Concurrent edits:** last save wins; the audit log keeps both.

## 10. Deployment changes

- `.env.example`: `SECRET_KEY=` (generate with `openssl rand -hex 32`); a comment that `PUBLIC_URL` comes from
  `DOMAIN` via compose.
- `docker-compose.yml` (engine): `PUBLIC_URL: https://${DOMAIN}`.
- `Caddyfile`: the public paths become `/`, `/login*`, `/logout`, `/invite/*`, `/admin*`, `/app*`, `/static/*`,
  `/webhooks/meta`, `/webhooks/meta/*`, `/health` (the 1 MB request limit stays; WAHA stays private).
- `README.md` and `docs/setup-guide.md`: create the first admin, add a business in the browser, the new per-business
  webhook URL, and a short click-through test list.

## 11. Testing

pytest, no network, as in v1 (the 117 engine tests keep passing).

- **Unit:** `Vault` round trip and wrong key; password hashing; invite expiry and single use; sessions and expiry;
  TOTP against RFC 6238 test vectors; rate limit; `client_from_dict` parity with `load_clients`; `Registry` CRUD,
  one-number-per-business, audit entries (secrets never in `detail`), `clients()` composition, first-run import;
  guardrail checks; `WahaClient` management calls and group-shape normalisation through `httpx.MockTransport`;
  new `Store` queries.
- **Web (TestClient over `https://testserver`):** login, two-step, invite, logout; admin pages refuse business users
  (403) and admins without two-step; business A can't open business B's chat (404); POST without CSRF → 403; saves
  reach `bot.clients` immediately; Meta keys never appear in any response; per-business webhook handshake,
  signature and cross-business message rejection; the v1 `/webhooks/meta` still works for the pilot.
- **Manual:** a click-through list in the setup guide (create admin, add business, link a number by QR, invite a
  business user, change a setting and see the bot use it).

## 12. Decisions log (owner decisions in brainstorming, 2026-09-28)

- **Who logs in:** the owner as admin plus each business; the owner creates business logins; no public sign-up.
- **Official numbers:** each business keeps its own Meta app; the admin pastes its keys; each business gets its own
  webhook URL. Embedded Signup comes later.
- **Business powers:** bot settings, chats and handoffs, staff and groups, and Sheet tab permissions (with the §8.4
  guardrails). Meta keys, number assignment, logins and retention stay admin-only.
- **Approach:** built into the engine — FastAPI + Jinja2 + htmx, same SQLite file and container.
- **Security:** admins must use two-step login; business users use passwords only in v2.
- **One group number per business.**
- **Added while writing this spec (owner to confirm):** admins can pause and resume a business (§8.2), so a
  business that stops paying stops getting bot replies; deleting a business stays out of v2.

## 13. Risks to verify at go-live

- WAHA's `GET /api/{session}/groups` and QR endpoints are checked only against fixtures; confirm the shapes with the
  live GOWS session during the smoke test.
- Meta's `GET /{phone-number-id}` fields used by **Test connection**; confirm with the pilot's number.
- Existing deployments must add `SECRET_KEY` before upgrading, or the engine refuses to start (by design).
