# Guided Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A business owner sets up their assistant by chatting with an AI on a new **Setup** screen: the AI drafts the Sheet tabs, Knowledge rows, tab permissions and the bot's persona (name, a new Personality setting, Instructions), the owner edits the draft, and **Apply** adds it to the Sheet and settings. Apply only adds.

**Architecture:** A new `app/guided_setup.py` holds the `propose_setup` tool, the draft checks, the interview turn (over the existing `LLM.complete`) and Apply's Sheet steps. The registry stores each business's interview in a new `setups` table and counts AI calls per UTC day. `app/sheets.py` gains three add-only writes (new tab, new columns, many rows). The screen is one more `screen()` in `app/pages.py` with one template, `app/templates/setup.html`; no new JavaScript.

**Tech Stack:** Python 3.12 (uv), FastAPI, Jinja2, Pico.css, sqlite3, gspread 6.2, the OpenAI SDK's Chat Completions (OpenAI, Gemini, Ollama); pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-10-02-guided-setup-design.md`

## Global Constraints

- Python `>=3.12`, uv, `[tool.uv] package = false`; run everything from the repo root with `uv run`.
- No new dependencies. No new JavaScript (the existing busy-button and `data-confirm` behaviour in `app/static/app.js` is enough).
- Ruff `select = ["E4", "E7", "E9", "F"]`: no unused imports, no `;`-joined statements, no one-line `def x(): y`, no assigned lambdas.
- Every response carries a `Content-Security-Policy` without `'unsafe-inline'`: templates must not use `style="..."`, inline handlers or inline `<script>`. Styles go in `app/static/app.css` (bump `app.css?v=` in `base.html` when it changes).
- Jinja autoescape stays on. Every signed-in POST carries the session's CSRF token in the form field `csrf`.
- Caps (spec §5.2, §6.4, §6.5): at most **60** AI calls per business per UTC day, retries included; at most **30** owner messages per interview (only **Send** is blocked after that); a typed message is at most **2,000** characters; `bot_name` 1-40 characters, `personality` at most 1,500, `instructions` at most 4,000; at most **10** tabs; a tab name is 1-100 characters with none of `[ ] * ? / \ :`, not the Knowledge or Handoffs tab's name, unique ignoring case; at most **20** columns per tab, each 1-40 characters, unique ignoring case; at most **60** Knowledge rows, question at most 200 characters, answer at most 1,000.
- Fixed text (spec): the greeting "Hi! I'll ask a few quick questions about {business}, then suggest how your assistant should work. What does your business do?"; "Please make the draft now with what you know."; "Call propose_setup now with the whole draft."; "(I made a draft.)"; "The assistant couldn't answer right now. Try again."; "That's the limit for today. Your answers are saved; come back tomorrow, or edit the draft by hand."
- Knowledge tab headers `Question | Answer`; Handoffs tab headers `Time | Name | Phone | Chat | Question | Reason`, under the names in the business's `knowledge_tab` / `handoff_tab` settings (defaults `Knowledge`, `Handoffs`).
- Sheet writes use `value_input_option="RAW"`. Apply never deletes, renames, moves or clears anything, never changes permissions a tab already has, and replaces persona fields only when Replace is ticked.
- The conversation is never written to the audit log or the application log. Logs: `setup_turn business=… outcome=question|draft|retry|error|limit`, `setup_apply business=… tabs=… columns=… rows=…`, `setup_apply_failed business=… error=<kind>`. The `setup.apply` audit entry holds tab names, columns per tab and a row count, never Knowledge text.
- Setup interviews not updated for 30 days are deleted by the daily maintenance job.
- Commit after every task; stage only the files you changed, by name (never `git add -A` / `git add .`); never stage `.env` or `.DS_Store`.

## Plan decisions

1. **Work happens in the worktree `.worktrees/guided-setup` on branch `feat/guided-setup`** (from `149a62b`). Web search is being built at the same time in the main working tree; the expected merge overlaps are a few lines in `app/config.py`, `app/registry.py`, `app/bot.py`, `app/pages.py`, `app/templates/settings.html` and `tests/fakes.py`.
2. **The current draft goes to the AI in the system prompt**, with its problems, instead of as JSON inside the stored owner message (spec §6.2). The conversation on screen stays readable, and each AI call carries the draft once instead of once per change request.
3. **The greeting is shown, not stored or sent.** The prompt tells the AI the screen already asked what the business does. Some providers refuse a conversation whose first message is the assistant's.
4. **`propose_setup` takes `name_column` and `phone_column`** instead of a free-form `fill` object, because Gemini rejects object schemas without listed properties. The stored draft keeps `fill` as `{column: "name"|"phone"}`, like the Sheet settings.
5. **Existing Knowledge/Handoffs tabs get their missing columns too** (adds only), so Knowledge rows always land under `Question`/`Answer`.
6. **Problems are computed whenever the draft is shown** (against the Sheet as it is now), not stored. A **Save my changes** button stores hand edits and refreshes the column pickers and problems.
7. **A new AI draft resets the ticks:** every tab used, every Knowledge row kept, "I understand" unticked, Replace ticked only where nothing is saved yet. Hand edits persist until the next AI draft.
8. **The 30-message limit counts every owner message** (including draft and change requests) and blocks only **Send**.
9. **A new tab needs at least one column** (not in the spec; an empty header row would give the bot nothing to read).
10. **After Apply the conversation and draft are kept**, so the owner can run it again or change something.
11. **The 30-day clean-up removes `applied_at` too.** The Home card also needs `tabs` empty, so it only comes back for a business that has no tab permissions at all.

## Review Focus

- **Malformed `propose_setup` arguments** (columns as one comma string, a list where a string belongs, numbers as names): they must become a checked draft, never a crash. Pinned: Task 4 `test_malformed_proposals_are_tidied_not_crashed_on`.
- **The Sheet changed after the draft** (a tab added by hand, in another case): Apply treats it as the existing tab and adds only the missing columns. Pinned: Task 4 `test_a_tab_matching_an_existing_one_ignoring_case_adds_only_missing_columns`, Task 6 `test_apply_adds_only_what_is_missing_and_skips_known_questions`.
- **A question repeated by the AI, or already in the Sheet with other spacing or case:** added once. Pinned: Task 6 `test_apply_adds_only_what_is_missing_and_skips_known_questions`.
- **`=FORMULA` text in a header, column or answer:** stored as text. Pinned: Task 3 `test_a_new_tab_gets_its_header_row_as_typed`, `test_new_columns_go_after_the_last_header_cell_widening_the_tab`, `test_knowledge_rows_go_in_one_call_matched_by_header_ignoring_case`.
- **A hand-made POST with absurd counts, or a Sheet that stops being readable mid-setup:** reading is bounded, and Apply is refused with the reason. Pinned: Task 7 `test_a_bogus_posted_draft_is_bounded_and_an_unreadable_sheet_blocks_apply`.

---

## File Structure

| File | Responsibility |
|---|---|
| `app/guided_setup.py` (create) | `PROPOSE_SETUP_SPEC`, the draft shape and its checks, the interview turn, Apply's Sheet steps, the summary, the draft screen's view data |
| `app/config.py` (modify) | `Client.personality` |
| `app/registry.py` (modify) | `personality` in `CONFIG_KEYS`; the `setups` table and `setup`, `save_setup`, `spend_setup_call`, `setup_applied`, `purge_setups` |
| `app/bot.py` (modify) | "Personality and tone" section in the system prompt |
| `app/sheets.py` (modify) | `add_tab`, `add_columns`, `append_rows` (RAW, cache dropped) |
| `app/main.py` (modify) | `maintain(..., registry=)` forgets old interviews; the daily loop passes the registry |
| `app/pages.py` (modify) | Personality on Settings; `rule_from_form` shared with the Sheet screen; `draft_from_form`, `apply_setup`, the `/setup` screen; the Home card flag |
| `app/templates/setup.html` (create) | Chat, draft and result views |
| `app/templates/settings.html`, `business_home.html`, `base.html` (modify) | Personality box and Guided setup link; Home card; **Setup** tab |
| `app/static/app.css` (modify) | `.pre-line` for chat bubbles and saved text |
| `tests/fakes.py` (modify) | `FakeSheets` writes and failures, `Forbidden`, `SETUP_ARGS` |
| `tests/test_guided_setup.py` (create) | Checks, turns, Apply |
| `tests/test_pages_setup.py` (create) | The screen end to end |
| `docs/setup-guide.md`, `README.md` (modify) | Guided setup docs |

The draft (stored, posted back by the form, and shown to the AI) has this shape everywhere:

```python
{"bot_name": "Mia", "personality": "...", "instructions": "...",
 "replace": {"bot_name": False, "personality": True, "instructions": False},
 "tabs": [{"name": "Orders", "purpose": "Customer cake orders", "columns": ["Date", "Name", "Phone"],
           "customer": ["own", "append"], "owner_column": "Phone", "fill": {"Name": "name", "Phone": "phone"},
           "use": True, "confirmed": False}],
 "knowledge": [{"question": "What are your hours?", "answer": "Tue-Sun 10am-8pm", "keep": True}]}
```

---

### Task 1: Personality setting

**Files:**
- Modify: `app/config.py` (`Client`, `client_from_dict`)
- Modify: `app/registry.py:58-60` (`CONFIG_KEYS`)
- Modify: `app/pages.py:98-119` (`settings_page`)
- Modify: `app/templates/settings.html`
- Modify: `app/bot.py:310-360` (`_system_prompt`)
- Test: `tests/test_config.py`, `tests/test_pages.py`, `tests/test_bot.py`

**Interfaces:**
- Produces: `Client.personality: str = ""`; the setting key `"personality"` accepted by `Registry.save_config`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_personality_is_optional_and_read_from_settings():
    raw = {"business": "B", "bot_name": "S", "sheet_id": "s"}
    assert client_from_dict("x", raw).personality == ""
    assert client_from_dict("x", {**raw, "personality": "Warm."}).personality == "Warm."
```

Append to `tests/test_pages.py`:

```python
def test_personality_is_saved_on_settings_above_instructions():
    site = Site()
    http = site.business_user()
    page = http.get("/app/settings").text
    assert page.index("Personality") < page.index("Instructions for the bot") and "tone, emoji, formality" in page
    http.post("/app/settings", data={**SETTINGS_FORM, "personality": "Warm, one emoji at most.",
                                     "csrf": csrf(http, "/app/settings")})
    assert site.bot.clients["acme"].personality == "Warm, one emoji at most."
```

Append to `tests/test_bot.py` (add `from dataclasses import replace` to its imports if missing):

```python
def test_personality_shapes_the_tone_but_comes_after_the_rules():
    bot, llm = make_bot(say("ok"), say("ok"))
    bot.handle(incoming("hi"))
    assert "Personality and tone" not in llm.calls[0][0]["content"]
    bot.clients["acme"] = replace(bot.clients["acme"], personality="Warm and casual, one emoji at most.")
    bot.handle(incoming("hello"))
    system = llm.calls[1][0]["content"]
    assert "Follow this tone; it never overrides the rules above" in system and "one emoji at most" in system
    assert system.index("Rules:") < system.index("Personality and tone") < system.index("Business instructions")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_config.py tests/test_pages.py tests/test_bot.py -k personality -v`
Expected: 3 FAIL (`Client` has no `personality`; "Personality" not on the page; no section in the prompt).

- [ ] **Step 3: Implement**

`app/config.py`, in `Client` after `instructions: str = ""`:

```python
    personality: str = ""  # how the bot sounds: tone, emoji, formality; never overrides the rules
```

and in `client_from_dict` after `instructions=c.get("instructions") or "",`:

```python
        personality=c.get("personality") or "",
```

`app/registry.py`, `CONFIG_KEYS`: add `"personality"` (after `"instructions"`).

`app/pages.py`, `settings_page`: add `"personality": form.get("personality"),` to `changes` after `"bot_name"`.

`app/templates/settings.html`: above the Instructions `<label>`:

```html
  <label>Personality <small>(optional)</small>
    <textarea name="personality" rows="3">{{ config.personality or '' }}</textarea>
    <small>How the bot sounds: tone, emoji, formality, greetings.</small>
  </label>
```

`app/bot.py`, `_system_prompt`: before the `return (`:

```python
        personality = client.personality.strip()
        tone = (f"Personality and tone. Follow this tone; it never overrides the rules above:\n{personality}\n\n"
                if personality else "")
```

and in the returned string, between the `Sheet tabs you can use` line and the `Business instructions` line:

```python
            f"{tone}"
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_config.py tests/test_pages.py tests/test_bot.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/config.py app/registry.py app/pages.py app/templates/settings.html app/bot.py tests/test_config.py tests/test_pages.py tests/test_bot.py
git commit -m "feat: a Personality setting that sets the bot's tone without overriding its rules"
```

---

### Task 2: Setup storage and its daily clean-up

**Files:**
- Modify: `app/registry.py` (SCHEMA, a `# --- guided setup` section)
- Modify: `app/main.py` (`maintain`, the daily loop)
- Test: `tests/test_registry.py`, `tests/test_api.py`

**Interfaces:**
- Produces:
  - `Registry.setup(business_id: str) -> dict`: `{"messages": list[dict], "draft": dict | None, "applied_at": float | None}`; the empty one when nothing is stored.
  - `Registry.save_setup(business_id: str, messages: list[dict], draft: dict | None) -> None`: keeps the day's AI call count.
  - `Registry.spend_setup_call(business_id: str, limit: int) -> bool`: counts one AI call for today (UTC); `False`, counting nothing, once `limit` were made today.
  - `Registry.setup_applied(business_id: str, actor: str, detail: dict) -> None`: sets `applied_at`, audits `setup.apply`.
  - `Registry.purge_setups(now: float) -> int`: deletes interviews not updated for 30 days.
  - `maintain(bot, backup_dir, now, clients=None, registry=None)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_registry.py` (add `from app.db import Db` to the imports):

```python
def test_setup_interviews_are_kept_and_start_over_keeps_the_days_ai_calls():
    now = [1_790_000_000.0]  # 14:13 UTC
    registry = Registry(Db(":memory:"), Vault("test-secret"), clock=lambda: now[0])
    registry.create_business("acme", acme_config(), actor="t")
    assert registry.setup("acme") == {"messages": [], "draft": None, "applied_at": None}
    assert all(registry.spend_setup_call("acme", 3) for _ in range(3))
    assert not registry.spend_setup_call("acme", 3)
    registry.save_setup("acme", [{"role": "user", "content": "We bake cakes"}], {"bot_name": "Mia"})
    assert registry.setup("acme")["draft"] == {"bot_name": "Mia"}
    registry.save_setup("acme", [], None)  # Start over
    assert registry.setup("acme")["messages"] == [] and not registry.spend_setup_call("acme", 3)
    now[0] += 86_400  # the next UTC day
    assert registry.spend_setup_call("acme", 3)
    registry.setup_applied("acme", actor="7", detail={"knowledge_rows": 2})
    assert registry.setup("acme")["applied_at"] == now[0]
    entry = registry.audit_log("acme")[0]
    assert entry["action"] == "setup.apply" and json.loads(entry["detail"]) == {"knowledge_rows": 2}
```

Append to `tests/test_api.py` (add `import time` and `acme_config` to the imports from `tests.fakes`):

```python
def test_maintenance_forgets_setup_interviews_untouched_for_30_days(tmp_path):
    registry = memory_registry()
    registry.create_business("acme", acme_config(), actor="t")
    registry.save_setup("acme", [{"role": "user", "content": "We bake cakes"}], None)
    bot = RecordingBot(Store(str(tmp_path / "a.db")))
    maintain(bot, str(tmp_path / "backups"), time.time() + 29 * 86_400, registry=registry)
    assert registry.setup("acme")["messages"]
    maintain(bot, str(tmp_path / "backups"), time.time() + 31 * 86_400, registry=registry)
    assert registry.setup("acme")["messages"] == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_registry.py tests/test_api.py -k "setup" -v`
Expected: 2 FAIL (`Registry` has no `setup`).

- [ ] **Step 3: Implement**

`app/registry.py`: append to `SCHEMA` (inside the string, after `email_accounts`):

```sql
CREATE TABLE IF NOT EXISTS setups (
  business_id TEXT PRIMARY KEY REFERENCES businesses(id),
  messages TEXT NOT NULL,     -- JSON list of {"role": "user"|"assistant", "content": str}
  draft TEXT,                 -- JSON draft, or NULL
  turn_day TEXT NOT NULL,     -- UTC date of the counted AI calls, YYYY-MM-DD
  turns INTEGER NOT NULL,     -- AI calls made on turn_day
  applied_at REAL,            -- last successful Apply, or NULL
  updated_at REAL NOT NULL
);
```

Below `SELECT_BUSINESS`:

```python
SETUP_KEEP = 30 * 86_400  # seconds an untouched setup interview is kept
```

Add a section after `# --- email`:

```python
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
```

`app/main.py`, `maintain`:

```python
def maintain(bot: Bot, backup_dir: str, now: float, clients: dict[str, Client] | None = None,
             registry: Registry | None = None) -> None:
    """Drop expired pending writes, messages past each client's retention and untouched setup interviews, then
    keep 7 backups.

    Every business's retention, paused ones too when `clients` is passed (from `registry.clients
    (include_paused=True)`); defaults to `bot.clients` (active businesses only).
    """
    bot.store.purge_expired_pending(now)
    for client in (bot.clients if clients is None else clients).values():
        bot.store.delete_older_than(client.id, now - client.retention_days * DAY)
    if registry is not None:
        registry.purge_setups(now)
    folder = Path(backup_dir)
    ...  # unchanged
```

and in `lifespan.daily()`:

```python
                    await asyncio.to_thread(maintain, bot, settings.backup_dir, time.time(),
                                            registry.clients(include_paused=True), registry)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_registry.py tests/test_api.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/registry.py app/main.py tests/test_registry.py tests/test_api.py
git commit -m "feat: store each business's setup interview, count its AI calls per day, forget it after 30 days"
```

---

### Task 3: Add-only Sheet writes

**Files:**
- Modify: `app/sheets.py` (`Sheets`)
- Modify: `tests/fakes.py` (`FakeSheets`, new `Forbidden`)
- Test: `tests/test_sheets.py`

**Interfaces:**
- Produces:
  - `Sheets.add_tab(sheet_id: str, tab: str, headers: list[str]) -> None`
  - `Sheets.add_columns(sheet_id: str, tab: str, columns: list[str]) -> None`: after the last header cell; widens the tab.
  - `Sheets.append_rows(sheet_id: str, tab: str, rows: list[dict[str, str]]) -> None`: one call; keys matched to headers ignoring case and spaces.
  - All three store RAW and drop the tab's cached headers and Knowledge text.
  - `FakeSheets.add_tab/add_columns/append_rows` with the same signatures; `FakeSheets.written: list[tuple]` (`("add_tab", tab, headers)`, `("add_columns", tab, columns)`, `("append_rows", tab, rows)`); `FakeSheets.fail_writes: set[str]` makes writes to those tabs raise `Forbidden` (an error with `code = 403`, like lost access).

- [ ] **Step 1: Write the failing tests**

In `tests/test_sheets.py`, replace `FakeWorksheet` and `FakeBook` with:

```python
class FakeWorksheet:
    def __init__(self, values, col_count=26):
        self.values = values  # first row is the header
        self.col_count = col_count
        self.appended = []
        self.writes = []  # value_input_option of every update and append_rows

    def get_all_records(self):
        head, *body = self.values
        return [dict(zip(head, r)) for r in body]

    def row_values(self, n):
        return self.values[n - 1]

    def append_row(self, row, value_input_option):
        self.appended.append((row, value_input_option))

    def update(self, values, range_name, value_input_option):
        row, col = gspread.utils.a1_to_rowcol(range_name)
        self.values[row - 1][col - 1:] = values[0]
        self.writes.append(value_input_option)

    def add_cols(self, cols):
        self.col_count += cols

    def append_rows(self, values, value_input_option):
        self.values.extend(values)
        self.writes.append(value_input_option)


class FakeBook:
    def __init__(self, tabs):
        self.tabs = tabs
        for title, ws in tabs.items():
            ws.title = title

    def worksheet(self, tab):
        return self.tabs[tab]

    def worksheets(self):
        return list(self.tabs.values())

    def add_worksheet(self, title, rows, cols):
        ws = FakeWorksheet([[]], col_count=cols)
        ws.title = title
        self.tabs[title] = ws
        return ws
```

Append:

```python
def test_a_new_tab_gets_its_header_row_as_typed():
    gc = FakeGC({})
    Sheets(gc).add_tab("s", "Orders", ["Date", "=Name"])
    ws = gc.book.tabs["Orders"]
    assert ws.values == [["Date", "=Name"]] and ws.writes == ["RAW"] and ws.col_count == 26


def test_new_columns_go_after_the_last_header_cell_widening_the_tab():
    ws = FakeWorksheet([["Date", "", "Item"], ["2026-06-01", "x", "Cake"]], col_count=4)
    sheets = Sheets(FakeGC({"Orders": ws}))
    assert sheets.headers("s", "Orders", now=0) == ["Date", "", "Item"]
    sheets.add_columns("s", "Orders", ["Status", "=Notes"])
    assert ws.values == [["Date", "", "Item", "Status", "=Notes"], ["2026-06-01", "x", "Cake"]]
    assert ws.col_count == 5 and ws.writes == ["RAW"]
    assert sheets.headers("s", "Orders", now=1) == ["Date", "", "Item", "Status", "=Notes"]  # cache dropped


def test_knowledge_rows_go_in_one_call_matched_by_header_ignoring_case():
    ws = FakeWorksheet([["question", "Answer "], ["Hours?", "9-5"]])
    sheets = Sheets(FakeGC({"Knowledge": ws}))
    assert "Lahore" not in sheets.knowledge("s", "Knowledge", now=0)
    sheets.append_rows("s", "Knowledge", [{"Question": "=1+1", "Answer": "Two"},
                                          {"Question": "Where?", "Answer": "Lahore"}])
    assert ws.values[2:] == [["=1+1", "Two"], ["Where?", "Lahore"]] and ws.writes == ["RAW"]
    assert "Lahore" in sheets.knowledge("s", "Knowledge", now=1)  # cache dropped
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_sheets.py -v`
Expected: the 3 new tests FAIL (`Sheets` has no `add_tab`, `add_columns`, `append_rows`).

- [ ] **Step 3: Implement**

`app/sheets.py`, in `Sheets` after `append`:

```python
    def add_tab(self, sheet_id: str, tab: str, headers: list[str]) -> None:
        """A new tab whose first row is `headers`, stored as typed."""
        ws = self._gc.open_by_key(sheet_id).add_worksheet(tab, rows=1000, cols=max(26, len(headers)))
        ws.update([headers], "A1", value_input_option="RAW")
        self._forget(sheet_id, tab)

    def add_columns(self, sheet_id: str, tab: str, columns: list[str]) -> None:
        """Write `columns` after the last header cell, widening the tab if needed; no existing cell changes."""
        ws = self._gc.open_by_key(sheet_id).worksheet(tab)  # fresh: a cached tab's size may be out of date
        start = len(ws.row_values(1)) + 1
        end = start + len(columns) - 1
        if ws.col_count < end:
            ws.add_cols(end - ws.col_count)
        ws.update([columns], gspread.utils.rowcol_to_a1(1, start), value_input_option="RAW")
        self._forget(sheet_id, tab)

    def append_rows(self, sheet_id: str, tab: str, rows: list[dict[str, str]]) -> None:
        """Many rows in one call, matched to the headers ignoring case and spaces, stored as typed."""
        ws = self._tab(sheet_id, tab)
        headers = [h.strip().casefold() for h in ws.row_values(1)]
        values = []
        for row in rows:
            by_header = {k.strip().casefold(): v for k, v in row.items()}
            values.append([by_header.get(h, "") for h in headers])
        ws.append_rows(values, value_input_option="RAW")
        self._forget(sheet_id, tab)

    def _forget(self, sheet_id: str, tab: str) -> None:
        """Drop what's cached about a tab after changing it."""
        for kind in ("headers", "knowledge"):
            self._cache.pop((kind, sheet_id, tab), None)
```

`tests/fakes.py`: above `class FakeSheets`:

```python
class Forbidden(Exception):
    """What Google raises when the Sheet is no longer shared with the robot account."""
    code = 403
```

In `FakeSheets.__init__`, after `self.fail_tabs`:

```python
        self.written: list[tuple] = []  # add_tab / add_columns / append_rows calls, in order
        self.fail_writes: set[str] = set()  # tabs whose writes raise Forbidden
```

and after `append`:

```python
    def _write(self, kind: str, tab: str, value) -> None:
        if tab in self.fail_writes:
            raise Forbidden(tab)
        self.written.append((kind, tab, value))

    def add_tab(self, sheet_id: str, tab: str, headers: list[str]) -> None:
        self._write("add_tab", tab, list(headers))
        self.tabs[tab] = []
        self._headers[tab] = list(headers)

    def add_columns(self, sheet_id: str, tab: str, columns: list[str]) -> None:
        self._write("add_columns", tab, list(columns))
        self._headers[tab] = self.headers(sheet_id, tab) + list(columns)

    def append_rows(self, sheet_id: str, tab: str, rows: list[dict[str, str]]) -> None:
        self._write("append_rows", tab, [dict(r) for r in rows])
        self.tabs[tab].extend(dict(r) for r in rows)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_sheets.py -q && uv run ruff check app tests`
Expected: all PASS; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add app/sheets.py tests/fakes.py tests/test_sheets.py
git commit -m "feat: add-only Sheet writes: a new tab with headers, columns after the last header, many rows at once"
```

---

### Task 4: The draft and its checks

**Files:**
- Create: `app/guided_setup.py`
- Modify: `tests/fakes.py` (append `SETUP_ARGS`)
- Test: `tests/test_guided_setup.py` (create)

**Interfaces:**
- Consumes: `tab_problems(tab, rule, headers, confirmed)` from `app/sheet_rules.py`; `client_from_dict`, `FILL_SOURCES` from `app/config.py`.
- Produces (all in `app/guided_setup.py`):
  - constants `MAX_TABS = 10`, `MAX_COLUMNS = 20`, `MAX_ROWS = 60`, `LIMITS`, `LABELS = {"bot_name": "Bot name", "personality": "Personality", "instructions": "Instructions"}`, `PERSONA` (its keys), `KNOWLEDGE_COLUMNS`, `HANDOFF_COLUMNS`, `PROPOSE_SETUP_SPEC: dict`
  - `split_columns(value) -> list[str]`
  - `find_tab(name: str, names) -> str | None`
  - `has_permissions(name: str, config: dict) -> bool`
  - `draft_from_args(args: dict, config: dict) -> dict`
  - `system_tabs(config: dict) -> list[tuple[str, list[str]]]`: `[(knowledge tab, KNOWLEDGE_COLUMNS), (handoff tab, HANDOFF_COLUMNS)]`
  - `tab_plan(name: str, columns: list[str], sheet_tabs: dict[str, list[str]]) -> dict`: `{"existing": str | None, "add": list[str], "headers": list[str]}`
  - `rule_of(tab: dict) -> dict`
  - `setup_changes(draft: dict, sheet_tabs: dict, config: dict) -> dict`
  - `check_draft(draft: dict, sheet_tabs: dict, config: dict) -> list[tuple[str, str]]`: `(where, message)` with `where` in `"persona"`, `"tab{i}"`, `"row{i}"`, `""`
  - `tests.fakes.SETUP_ARGS`: a valid `propose_setup` argument dict for the bakery.

- [ ] **Step 1: Write the failing tests**

Append to `tests/fakes.py`:

```python
# A valid propose_setup call for the bakery: one new tab, one existing tab named in another case, two questions
# (the second is already in bakery_sheets()'s Knowledge tab, spelled differently).
SETUP_ARGS = {
    "bot_name": "Mia", "personality": "Warm and casual. One emoji at most.",
    "instructions": "We deliver within Lahore only.",
    "tabs": [{"name": "Bookings", "purpose": "Table bookings", "columns": ["Date", "Name", "Phone", "Guests"],
              "customer": ["own", "append"], "owner_column": "Phone", "name_column": "Name",
              "phone_column": "Phone"},
             {"name": "orders", "purpose": "Cake orders", "columns": ["Date", "Item", "Status"],
              "customer": ["read"]}],
    "knowledge": [{"question": "What are your hours?", "answer": "Tue-Sun 10am-8pm"},
                  {"question": " delivery? ", "answer": "Free above Rs 3000"}],
}
```

Create `tests/test_guided_setup.py`:

```python
from app.guided_setup import check_draft, draft_from_args, setup_changes, tab_plan
from tests.fakes import SETUP_ARGS, acme_config, bakery_sheets


def sheet_tabs() -> dict[str, list[str]]:
    return bakery_sheets().tab_headers("sheet-1")


def draft(**changes) -> dict:
    return {**draft_from_args(SETUP_ARGS, acme_config()), **changes}


def a_tab(name: str, **changes) -> dict:
    return {"name": name, "purpose": "", "columns": ["Date"], "customer": [], "owner_column": "", "fill": {},
            "use": True, "confirmed": False, **changes}


def test_a_proposal_becomes_a_draft_with_replace_ticked_only_where_nothing_is_saved():
    d = draft_from_args(SETUP_ARGS, acme_config())
    assert d["replace"] == {"bot_name": False, "personality": True, "instructions": False}
    bookings = d["tabs"][0]
    assert bookings["fill"] == {"Name": "name", "Phone": "phone"} and bookings["use"] and not bookings["confirmed"]
    assert d["knowledge"][1] == {"question": "delivery?", "answer": "Free above Rs 3000", "keep": True}
    assert check_draft(d, sheet_tabs(), acme_config()) == []


def test_malformed_proposals_are_tidied_not_crashed_on():
    d = draft_from_args({"bot_name": 7, "tabs": [{"name": "Leads", "columns": "Name, phone ,", "customer": "read",
                                                    "fill": {"Phone": ["phone"]}, "owner_column": "PHONE"}, "junk"],
                         "knowledge": [{"question": "", "answer": ""}, "x", {"question": "Q?"}]}, acme_config())
    assert d["bot_name"] == "" and d["tabs"] == [{"name": "Leads", "purpose": "", "columns": ["Name", "phone"],
                                                  "customer": [], "owner_column": "phone", "fill": {},
                                                  "use": True, "confirmed": False}]
    assert d["knowledge"] == [{"question": "Q?", "answer": "", "keep": True}]
    assert {where for where, _ in check_draft(d, sheet_tabs(), acme_config())} == {"persona", "row0"}


def test_tab_names_follow_googles_rules_and_leave_out_the_knowledge_and_handoffs_tabs():
    tabs = [a_tab(name) for name in ("Orders/2026", "knowledge", "Leads", "LEADS", "", "x" * 101)]
    tabs.append(a_tab("Skipped/", use=False))  # unticked tabs aren't checked
    problems = check_draft(draft(tabs=tabs), sheet_tabs(), acme_config())
    assert [where for where, _ in problems] == ["tab0", "tab1", "tab3", "tab4", "tab5"]
    text = " ".join(message for _, message in problems)
    assert "can't contain" in text and "Knowledge or Handoffs" in text and "two tabs have this name" in text


def test_caps_on_tabs_columns_rows_and_text():
    tabs = [a_tab(f"T{i}", columns=["A"]) for i in range(11)]
    tabs[0]["columns"] = [f"C{i}" for i in range(21)]
    tabs[1]["columns"] = ["A", "a", "x" * 41]
    rows = [{"question": f"Q{i}?", "answer": "A", "keep": True} for i in range(61)]
    rows[0]["answer"] = "x" * 1001
    problems = check_draft(draft(tabs=tabs, knowledge=rows, bot_name="x" * 41, personality="x" * 1501,
                                 instructions="x" * 4001), sheet_tabs(), acme_config())
    text = " ".join(message for _, message in problems)
    for expected in ("At most 10 tabs", "at most 20 columns", "at most 40 characters", "same name",
                     "At most 60 Knowledge rows", "at most 1,000", "Bot name: 1 to 40",
                     "Personality: at most 1,500", "Instructions: at most 4,000"):
        assert expected in text, expected


def test_a_tab_matching_an_existing_one_ignoring_case_adds_only_missing_columns():
    assert tab_plan("orders", ["date", "Status"], sheet_tabs()) == {
        "existing": "Orders", "add": ["Status"], "headers": ["Date", "Item", "Qty", "Name", "Phone", "Status"]}
    assert tab_plan("Bookings", ["Date"], sheet_tabs()) == {"existing": None, "add": ["Date"], "headers": ["Date"]}
    assert "new tab needs at least one column" in check_draft(draft(tabs=[a_tab("Empty", columns=[])]),
                                                              sheet_tabs(), acme_config())[0][1]


def test_permissions_pass_the_sheet_pages_checks_on_the_final_headers():
    config = {**acme_config(), "tabs": {}}  # no tab has permissions yet
    orders = a_tab("orders", columns=["Status"], customer=["read"])
    refused = check_draft(draft(tabs=[orders]), sheet_tabs(), config)
    assert [where for where, _ in refused] == ["tab0"] and "every customer would see Phone" in refused[0][1]
    assert check_draft(draft(tabs=[{**orders, "confirmed": True}]), sheet_tabs(), config) == []
    own = {**orders, "customer": ["own", "append"], "owner_column": "Mobile",
           "fill": {"Status": "name", "Nope": "phone"}}
    text = " ".join(message for _, message in check_draft(draft(tabs=[own]), sheet_tabs(), config))
    assert "pick which column holds" in text and "'Nope' is not in the tab" in text and "'Status'" not in text


def test_saved_permissions_are_kept_and_persona_follows_the_replace_ticks():
    d = draft()
    d["replace"] = {"bot_name": False, "personality": True, "instructions": False}
    changes = setup_changes(d, sheet_tabs(), acme_config())
    assert changes["personality"] == SETUP_ARGS["personality"] and "bot_name" not in changes
    assert "instructions" not in changes
    assert changes["tabs"]["Orders"] == acme_config()["tabs"]["Orders"]  # already set: untouched
    assert changes["tabs"]["Bookings"] == {"customer": ["own", "append"], "owner_column": "Phone",
                                          "fill": {"Name": "name", "Phone": "phone"}}
    d["tabs"][0]["use"] = False
    assert "tabs" not in setup_changes(d, sheet_tabs(), acme_config())
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_guided_setup.py -v`
Expected: ERROR at collection, `ModuleNotFoundError: No module named 'app.guided_setup'`.

- [ ] **Step 3: Implement**

Create `app/guided_setup.py`:

```python
"""Guided setup: an AI interview drafts the Sheet tabs, Knowledge rows, permissions and persona; Apply adds them.

The AI only drafts. Apply is plain code that adds tabs, columns and Knowledge rows and saves settings. It never
deletes, renames or moves anything, so pressing it again finishes a job that stopped part-way.
"""
from __future__ import annotations

from app.config import FILL_SOURCES, client_from_dict
from app.sheet_rules import tab_problems

MAX_TABS, MAX_COLUMNS, MAX_ROWS = 10, 20, 60
LIMITS = {"bot_name": 40, "personality": 1500, "instructions": 4000}
LABELS = {"bot_name": "Bot name", "personality": "Personality", "instructions": "Instructions"}
PERSONA = tuple(LABELS)
KNOWLEDGE_COLUMNS = ["Question", "Answer"]
HANDOFF_COLUMNS = ["Time", "Name", "Phone", "Chat", "Question", "Reason"]  # what Bot._handoff writes
BAD_NAME_CHARACTERS = set("[]*?/\\:")  # Google refuses these in tab names

PROPOSE_SETUP_SPEC: dict = {"type": "function", "function": {
    "name": "propose_setup",
    "description": "Propose the whole setup for the owner to review: the bot's persona, the Sheet tabs with their "
                   "columns and what customers may do on each, and Knowledge questions with answers. Nothing "
                   "changes until the owner applies it.",
    "parameters": {"type": "object", "properties": {
        "bot_name": {"type": "string", "description": "The assistant's name, at most 40 characters."},
        "personality": {"type": "string", "description": "How the bot sounds: tone, emoji, formality, greetings. "
                                                         "At most 1,500 characters."},
        "instructions": {"type": "string", "description": "Rules the bot follows: hours, delivery, policies. "
                                                          "At most 4,000 characters."},
        "tabs": {"type": "array", "description": "At most 10 tabs, not counting the Knowledge and Handoffs tabs.",
                 "items": {"type": "object", "properties": {
                     "name": {"type": "string", "description": "A short tab name, e.g. Orders."},
                     "purpose": {"type": "string", "description": "One line: what the tab is for."},
                     "columns": {"type": "array", "items": {"type": "string"},
                                 "description": "Column names, at most 20, each at most 40 characters."},
                     "customer": {"type": "array", "items": {"type": "string", "enum": ["read", "own", "append"]},
                                  "description": "What customers may do: read all rows, see only their own rows "
                                                 "(own), add rows (append). Empty for staff only."},
                     "owner_column": {"type": "string",
                                      "description": "With own: the column holding the customer's phone number."},
                     "name_column": {"type": "string", "description": "With append: the column the system fills "
                                                                      "with the customer's WhatsApp name."},
                     "phone_column": {"type": "string", "description": "With append: the column the system fills "
                                                                       "with the customer's phone number."},
                 }, "required": ["name", "purpose", "columns", "customer"]}},
        "knowledge": {"type": "array", "description": "At most 60 questions customers ask, with the answers. Never "
                                                      "private information: anyone who messages the bot sees it.",
                      "items": {"type": "object", "properties": {
                          "question": {"type": "string"}, "answer": {"type": "string"}},
                          "required": ["question", "answer"]}},
    }, "required": ["bot_name", "personality", "instructions", "tabs", "knowledge"]},
}}


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def split_columns(value) -> list[str]:
    """Column names from a list or a comma-separated string. Commas always separate: the form edits them so."""
    items = value if isinstance(value, list) else [value]
    return [c.strip() for item in items if isinstance(item, str) for c in item.split(",") if c.strip()]


def find_tab(name: str, names) -> str | None:
    """The tab called `name` ignoring case (Google treats such names as the same tab), or None."""
    return next((t for t in names if t.casefold() == name.casefold()), None)


def has_permissions(name: str, config: dict) -> bool:
    """Whether the tab already has saved permissions; setup never changes those."""
    return find_tab(name, config.get("tabs") or {}) is not None


def _spelled(name: str, columns: list[str]) -> str:
    """`name` spelled like the matching column, so the column pickers show it."""
    return find_tab(name, columns) or name


def draft_from_args(args: dict, config: dict) -> dict:
    """propose_setup's arguments as a draft: every tab used, every row kept, Replace ticked where nothing is saved."""
    tabs = []
    for raw in args.get("tabs") if isinstance(args.get("tabs"), list) else []:
        if not isinstance(raw, dict):
            continue
        columns = split_columns(raw.get("columns"))
        fill = {}
        if isinstance(raw.get("fill"), dict):
            fill = {_text(k): v for k, v in raw["fill"].items() if isinstance(v, str) and v in FILL_SOURCES}
        for source in ("name", "phone"):
            if _text(raw.get(f"{source}_column")):
                fill[_text(raw.get(f"{source}_column"))] = source
        customer = raw.get("customer") if isinstance(raw.get("customer"), list) else []
        tabs.append({"name": _text(raw.get("name")), "purpose": _text(raw.get("purpose")), "columns": columns,
                     "customer": [access for access in ("read", "own", "append") if access in customer],
                     "owner_column": _spelled(_text(raw.get("owner_column")), columns),
                     "fill": {_spelled(column, columns): source for column, source in fill.items() if column},
                     "use": True, "confirmed": False})
    knowledge = [{"question": _text(row.get("question")), "answer": _text(row.get("answer")), "keep": True}
                 for row in (args.get("knowledge") if isinstance(args.get("knowledge"), list) else [])
                 if isinstance(row, dict)]
    return {**{key: _text(args.get(key)) for key in PERSONA},
            "replace": {key: not str(config.get(key) or "").strip() for key in PERSONA},
            "tabs": tabs, "knowledge": [row for row in knowledge if row["question"] or row["answer"]]}


def system_tabs(config: dict) -> list[tuple[str, list[str]]]:
    """The Knowledge and Handoffs tabs, under the business's names for them, with the columns the bot uses."""
    return [(config.get("knowledge_tab") or "Knowledge", KNOWLEDGE_COLUMNS),
            (config.get("handoff_tab") or "Handoffs", HANDOFF_COLUMNS)]


def tab_plan(name: str, columns: list[str], sheet_tabs: dict[str, list[str]]) -> dict:
    """How a drafted tab meets the Sheet: the existing tab's title (or None), the columns to add, the final headers."""
    existing = find_tab(name, sheet_tabs)
    current = sheet_tabs[existing] if existing else []
    have = {h.casefold() for h in current}
    add = [c for c in columns if c.casefold() not in have]
    return {"existing": existing, "add": add, "headers": current + add}


def rule_of(tab: dict) -> dict:
    """A drafted tab's permissions as the Sheet page saves them."""
    rule: dict = {"customer": list(tab["customer"])}
    if "own" in tab["customer"]:
        rule["owner_column"] = tab["owner_column"]
    if "append" in tab["customer"]:
        rule["fill"] = dict(tab["fill"])
    return rule


def setup_changes(draft: dict, sheet_tabs: dict[str, list[str]], config: dict) -> dict:
    """The settings Apply saves: permissions for used tabs that have none yet, and each persona field ticked Replace."""
    saved = dict(config.get("tabs") or {})
    added = {}
    for tab in draft["tabs"]:
        name = find_tab(tab["name"], sheet_tabs) or tab["name"]
        if tab["use"] and not has_permissions(name, config):
            added[name] = rule_of(tab)
    changes: dict = {key: draft[key] for key in PERSONA if draft["replace"].get(key)}
    if added:
        changes["tabs"] = {**saved, **added}
    return changes


def check_draft(draft: dict, sheet_tabs: dict[str, list[str]], config: dict) -> list[tuple[str, str]]:
    """What stops a draft being applied, as (where, message): where is "persona", "tab{i}", "row{i}" or ""."""
    problems: list[tuple[str, str]] = []
    if not 1 <= len(draft["bot_name"]) <= LIMITS["bot_name"]:
        problems.append(("persona", f"Bot name: 1 to {LIMITS['bot_name']} characters."))
    for key in ("personality", "instructions"):
        if len(draft[key]) > LIMITS[key]:
            problems.append(("persona", f"{LABELS[key]}: at most {LIMITS[key]:,} characters."))
    used = [(i, tab) for i, tab in enumerate(draft["tabs"]) if tab["use"]]
    if len(used) > MAX_TABS:
        problems.append(("", f"At most {MAX_TABS} tabs: untick some."))
    reserved = {name.casefold() for name, _ in system_tabs(config)}
    seen: set[str] = set()
    for i, tab in used:
        name, columns, where = tab["name"], tab["columns"], f"tab{i}"
        label = name or f"Tab {i + 1}"
        if not 1 <= len(name) <= 100:
            problems.append((where, f"{label}: a tab name is 1 to 100 characters."))
        if BAD_NAME_CHARACTERS & set(name):
            problems.append((where, f"{label}: a tab name can't contain [ ] * ? / \\ or :."))
        if name.casefold() in reserved:
            problems.append((where, f"{label}: that's the Knowledge or Handoffs tab, which setup adds by itself."))
        if name.casefold() in seen:
            problems.append((where, f"{label}: two tabs have this name."))
        seen.add(name.casefold())
        if len(columns) > MAX_COLUMNS:
            problems.append((where, f"{label}: at most {MAX_COLUMNS} columns."))
        long = [c for c in columns if len(c) > 40]
        if long:
            problems.append((where, f"{label}: column names are at most 40 characters ({', '.join(long)})."))
        if len({c.casefold() for c in columns}) < len(columns):
            problems.append((where, f"{label}: two columns have the same name."))
        plan = tab_plan(name, columns, sheet_tabs)
        if plan["existing"] is None and not columns:
            problems.append((where, f"{label}: a new tab needs at least one column."))
        if not has_permissions(plan["existing"] or name, config):
            problems += [(where, p) for p in tab_problems(plan["existing"] or name, rule_of(tab), plan["headers"],
                                                          confirmed=tab["confirmed"])]
    kept = [(i, row) for i, row in enumerate(draft["knowledge"]) if row["keep"]]
    if len(kept) > MAX_ROWS:
        problems.append(("", f"At most {MAX_ROWS} Knowledge rows: remove some."))
    for i, row in kept:
        if not row["question"] or not row["answer"]:
            problems.append((f"row{i}", f"Knowledge row {i + 1}: it needs a question and an answer."))
        if len(row["question"]) > 200 or len(row["answer"]) > 1000:
            problems.append((f"row{i}", f"Knowledge row {i + 1}: a question is at most 200 characters, an answer "
                                        "at most 1,000."))
    if not problems:  # last, exactly as any settings save would check it
        try:
            client_from_dict("setup", {**config, **setup_changes(draft, sheet_tabs, config)})
        except ValueError as e:
            problems.append(("", str(e)))
    return problems
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_guided_setup.py -q && uv run ruff check app tests`
Expected: 7 PASS; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add app/guided_setup.py tests/fakes.py tests/test_guided_setup.py
git commit -m "feat: the guided setup draft, its propose_setup tool, and the checks it must pass"
```

---

### Task 5: The interview turn

**Files:**
- Modify: `app/guided_setup.py`
- Test: `tests/test_guided_setup.py`

**Interfaces:**
- Consumes: `LLM.complete(messages, tools) -> ModelReply` (`.text`, `.tool_calls: list[ToolCall(id, name, arguments)]`, `.message`); Task 4's `draft_from_args`, `check_draft`, `has_permissions`, `system_tabs`, `PROPOSE_SETUP_SPEC`, `LABELS`, `PERSONA`.
- Produces:
  - constants `DAILY_CALLS = 60`, `MAX_OWNER_MESSAGES = 30`, `MAX_MESSAGE = 2000`, `GREETING` (with `{business}`), `DRAFT_NOW`, `REMINDER`, `MADE_DRAFT`, `AI_DOWN`, `LIMIT`
  - `class SetupError(Exception)`: a turn that changed nothing; `str(e)` is for the owner.
  - `@dataclass Turn(messages: list[dict], draft: dict | None = None, problems: list[tuple[str, str]] = [])`
  - `setup_prompt(config: dict, sheet_tabs: dict | None, draft: dict | None, problems: list) -> str`
  - `take_turn(llm, spend: Callable[[], bool], business_id: str, config: dict, sheet_tabs: dict | None, messages: list[dict], draft: dict | None, owner_text: str, want_draft: bool) -> Turn`; raises `SetupError(AI_DOWN)` or `SetupError(LIMIT)`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_guided_setup.py`, replace the imports with:

```python
import pytest

from app.guided_setup import (AI_DOWN, DRAFT_NOW, MADE_DRAFT, REMINDER, SetupError, check_draft, draft_from_args,
                              setup_changes, tab_plan, take_turn)
from tests.fakes import SETUP_ARGS, ScriptedLLM, acme_config, bakery_sheets, call, say
```

Append:

```python
class Budget:
    """spend() for take_turn: allows `left` AI calls."""

    def __init__(self, left: int = 60) -> None:
        self.left, self.used = left, 0

    def __call__(self) -> bool:
        if self.used >= self.left:
            return False
        self.used += 1
        return True


def turn(llm, budget=None, current=None, text="We bake cakes", want_draft=False):
    return take_turn(llm, budget or Budget(), "acme", acme_config(), sheet_tabs(), [], current, text, want_draft)


def test_a_plain_answer_is_the_next_question_and_the_prompt_builds_on_the_sheet():
    llm = ScriptedLLM(say("What do customers ask about most?"))
    t = turn(llm)
    assert t.messages == [{"role": "user", "content": "We bake cakes"},
                          {"role": "assistant", "content": "What do customers ask about most?"}] and t.draft is None
    system = llm.calls[0][0]["content"]
    assert "- Orders: Date, Item, Qty, Name, Phone (permissions already set)" in system
    assert "Sweet Bakes" in system and "- Bot name: Sara" in system and "one short question at a time" in system
    assert llm.tools == [["propose_setup"]]


def test_a_proposal_is_checked_and_becomes_the_draft():
    t = turn(ScriptedLLM(call("propose_setup", **SETUP_ARGS)))
    assert t.messages[-1] == {"role": "assistant", "content": MADE_DRAFT}
    assert t.draft["bot_name"] == "Mia" and t.problems == []


def test_a_failing_draft_goes_back_once_then_is_shown_with_its_problems():
    bad = {**SETUP_ARGS, "bot_name": ""}
    llm, budget = ScriptedLLM(call("propose_setup", **bad), call("propose_setup", **bad)), Budget()
    t = turn(llm, budget)
    feedback = llm.calls[1][-1]
    assert feedback["role"] == "tool" and "Bot name: 1 to 40" in feedback["content"]
    assert budget.used == 2 and t.draft["bot_name"] == ""
    assert t.problems == [("persona", "Bot name: 1 to 40 characters.")]
    fixed = turn(ScriptedLLM(call("propose_setup", **bad), call("propose_setup", **SETUP_ARGS)))
    assert fixed.problems == [] and fixed.draft["bot_name"] == "Mia"


def test_a_draft_request_answered_in_text_gets_one_reminder():
    llm = ScriptedLLM(say("Sure! What are your hours?"), call("propose_setup", **SETUP_ARGS))
    t = turn(llm, text=DRAFT_NOW, want_draft=True)
    assert llm.calls[1][-1] == {"role": "user", "content": REMINDER} and t.draft is not None
    stubborn = turn(ScriptedLLM(say("First, your hours?"), say("I still need your hours.")), want_draft=True)
    assert stubborn.draft is None and stubborn.messages[-1]["content"] == "I still need your hours."


def test_the_current_draft_and_its_problems_go_to_the_ai():
    current = draft(bot_name="")
    llm = ScriptedLLM(call("propose_setup", **SETUP_ARGS))
    turn(llm, current=current, text="Make it formal", want_draft=True)
    system = llm.calls[0][0]["content"]
    assert '"bot_name": ""' in system and "Bot name: 1 to 40 characters." in system


def test_ai_errors_and_the_daily_cap_change_nothing():
    budget = Budget()
    with pytest.raises(SetupError, match=AI_DOWN):
        turn(ScriptedLLM(fail=True), budget)
    assert budget.used == 1  # a failed call counts too
    bad = {**SETUP_ARGS, "bot_name": ""}
    with pytest.raises(SetupError, match="limit for today"):  # the retry is the second call
        turn(ScriptedLLM(call("propose_setup", **bad), call("propose_setup", **SETUP_ARGS)), Budget(left=1))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_guided_setup.py -v`
Expected: ERROR at collection, `ImportError: cannot import name 'AI_DOWN'`.

- [ ] **Step 3: Implement**

`app/guided_setup.py`: replace the imports with:

```python
import json
import logging
from dataclasses import dataclass, field
from typing import Callable

from app.config import FILL_SOURCES, client_from_dict
from app.sheet_rules import tab_problems

log = logging.getLogger("setup")
```

Add below `BAD_NAME_CHARACTERS`:

```python
DAILY_CALLS = 60  # AI calls per business per UTC day, retries included
MAX_OWNER_MESSAGES = 30  # then only "Make the draft now"
MAX_MESSAGE = 2000  # characters in one typed message
GREETING = ("Hi! I'll ask a few quick questions about {business}, then suggest how your assistant should work. "
            "What does your business do?")
DRAFT_NOW = "Please make the draft now with what you know."
REMINDER = "Call propose_setup now with the whole draft."
MADE_DRAFT = "(I made a draft.)"
AI_DOWN = "The assistant couldn't answer right now. Try again."
LIMIT = "That's the limit for today. Your answers are saved; come back tomorrow, or edit the draft by hand."
```

Append at the end of the file:

```python
class SetupError(Exception):
    """A turn that changed nothing; the message is for the owner."""


@dataclass
class Turn:
    messages: list[dict]  # the conversation to store
    draft: dict | None = None  # a new draft from the AI, or None
    problems: list[tuple[str, str]] = field(default_factory=list)  # the new draft's, after one retry


def setup_prompt(config: dict, sheet_tabs: dict[str, list[str]] | None, draft: dict | None,
                 problems: list[tuple[str, str]]) -> str:
    """The interview's instructions, with the Sheet and settings as they are now and the current draft."""
    if sheet_tabs is None:
        tabs = "(the Sheet couldn't be read right now)"
    else:
        tabs = "\n".join(f"- {tab}: {', '.join(h for h in headers if h) or '(no header row)'}"
                         + (" (permissions already set)" if has_permissions(tab, config) else "")
                         for tab, headers in sheet_tabs.items()) or "(no tabs yet)"
    current = "\n".join(f"- {LABELS[key]}: {str(config.get(key) or '').strip() or '(empty)'}" for key in PERSONA)
    knowledge, handoffs = (name for name, _ in system_tabs(config))
    text = (
        f"You are helping the owner of {config['business']} set up {config.get('bot_name') or 'the assistant'}, "
        "the business's WhatsApp AI assistant. The screen already greeted them and asked what the business does.\n"
        "Rules:\n"
        "- Ask one short question at a time, in the owner's language. About 6 to 12 questions in total.\n"
        "- Cover: what the business sells or does; what customers ask about; what should be recorded (orders, "
        "bookings, leads, expenses...) and which details each needs; what customers may look up (only their own "
        "orders? a price list?); hours, location, prices and policies; the bot's name and tone.\n"
        "- Tab and column names: short, plain English unless the owner asks otherwise. A tab where customers see "
        "their own rows needs a phone column, given as owner_column.\n"
        "- Never put private information in Knowledge (staff phone numbers, costs, margins, passwords): anyone who "
        "messages the bot can be told everything in it.\n"
        f"- Don't propose the {knowledge} or {handoffs} tabs: setup adds them by itself.\n"
        "- Build on what exists: keep existing tab names and columns.\n"
        "- When you know enough, or the owner asks for the draft, call propose_setup with the whole draft.\n\n"
        f"The Sheet's tabs now:\n{tabs}\n\n"
        f"The current settings:\n{current}"
    )
    if draft is not None:
        text += ("\n\nThe current draft, which the owner may have edited by hand (\"use\": false means they "
                 f"unticked a tab, \"keep\": false a Knowledge row):\n{json.dumps(draft, ensure_ascii=False)}")
        if problems:
            text += "\n\nProblems in it to fix:\n" + "\n".join(f"- {message}" for _, message in problems)
    return text


def take_turn(llm, spend: Callable[[], bool], business_id: str, config: dict,
              sheet_tabs: dict[str, list[str]] | None, messages: list[dict], draft: dict | None, owner_text: str,
              want_draft: bool) -> Turn:
    """The owner's message and the AI's answer: its next question, or a checked draft.

    `spend()` counts one AI call and returns False once today's calls are used up. A draft that fails the checks
    goes back to the AI once; a draft request answered in text gets one reminder. Raises SetupError, changing
    nothing, when the AI fails or the cap is reached.
    """
    convo = [*messages, {"role": "user", "content": owner_text}]
    current = check_draft(draft, sheet_tabs or {}, config) if draft is not None else []
    calls = [{"role": "system", "content": setup_prompt(config, sheet_tabs, draft, current)}, *convo]
    reminded = retried = False
    while True:
        if not spend():
            log.info("setup_turn business=%s outcome=limit", business_id)
            raise SetupError(LIMIT)
        try:
            reply = llm.complete(calls, [PROPOSE_SETUP_SPEC])
        except Exception as e:
            log.warning("setup_turn business=%s outcome=error error=%s", business_id, type(e).__name__)
            raise SetupError(AI_DOWN) from None
        proposal = next((c for c in reply.tool_calls if c.name == "propose_setup"), None)
        if proposal is None:
            if want_draft and not reminded and reply.text:
                reminded = True
                calls += [reply.message, {"role": "user", "content": REMINDER}]
                log.info("setup_turn business=%s outcome=retry", business_id)
                continue
            if not reply.text:
                log.warning("setup_turn business=%s outcome=error error=empty", business_id)
                raise SetupError(AI_DOWN)
            log.info("setup_turn business=%s outcome=question", business_id)
            return Turn([*convo, {"role": "assistant", "content": reply.text}])
        new = draft_from_args(proposal.arguments, config)
        problems = check_draft(new, sheet_tabs or {}, config)
        if problems and not retried:
            retried = True
            feedback = json.dumps({"error": "Fix these problems and call propose_setup again with the whole draft.",
                                   "problems": [message for _, message in problems]}, ensure_ascii=False)
            # every tool call needs its answer, or the provider refuses the next request
            calls += [reply.message, *({"role": "tool", "tool_call_id": c.id, "content": feedback}
                                       for c in reply.tool_calls)]
            log.info("setup_turn business=%s outcome=retry", business_id)
            continue
        log.info("setup_turn business=%s outcome=draft", business_id)
        return Turn([*convo, {"role": "assistant", "content": MADE_DRAFT}], new, problems)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_guided_setup.py -q && uv run ruff check app tests`
Expected: 13 PASS; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add app/guided_setup.py tests/test_guided_setup.py
git commit -m "feat: the guided setup interview: one question at a time, then a checked draft, with capped retries"
```

---

### Task 6: Apply's Sheet steps and the summary

**Files:**
- Modify: `app/guided_setup.py`
- Test: `tests/test_guided_setup.py`

**Interfaces:**
- Consumes: Task 3's `sheets.add_tab/add_columns/append_rows`, `sheets.rows(sheet_id, tab) -> list[dict]`; `sheet_error(error, email) -> str` from `app/sheets.py`; Task 4's `tab_plan`, `system_tabs`, `find_tab`.
- Produces:
  - `same_question(text: str) -> str`: compared ignoring case and spacing.
  - `known_questions(sheets, config: dict, sheet_tabs: dict) -> set[str]`
  - `@dataclass Applied(created: list[str], columns: dict[str, list[str]], rows: int, error: str)`
  - `apply_sheet(sheets, business_id: str, config: dict, draft: dict, sheet_tabs: dict, email: str) -> Applied`
  - `summary(done: Applied, changes: dict, config: dict) -> list[str]`

- [ ] **Step 1: Write the failing tests**

In `tests/test_guided_setup.py`, change the imports to:

```python
from app.guided_setup import (AI_DOWN, DRAFT_NOW, MADE_DRAFT, REMINDER, SetupError, apply_sheet, check_draft,
                              draft_from_args, setup_changes, summary, tab_plan, take_turn)
from tests.fakes import SETUP_ARGS, FakeSheets, ScriptedLLM, acme_config, bakery_sheets, call, say
```

Append:

```python
def test_apply_adds_only_what_is_missing_and_skips_known_questions():
    sheets = bakery_sheets()
    d = draft()
    d["knowledge"].append({"question": "WHAT are  your hours?", "answer": "Twice", "keep": True})  # repeated
    done = apply_sheet(sheets, "acme", acme_config(), d, sheets.tab_headers("sheet-1"), "")
    assert done.error == "" and sheets.written == [
        ("add_tab", "Bookings", ["Date", "Name", "Phone", "Guests"]),
        ("add_columns", "Orders", ["Status"]),
        ("append_rows", "Knowledge", [{"Question": "What are your hours?", "Answer": "Tue-Sun 10am-8pm"}])]
    assert summary(done, {"personality": "x"}, acme_config()) == [
        "Added tab Bookings.", "Added column Status to Orders.", "Added 1 Knowledge row.", "Saved Personality."]


def test_a_new_sheet_gets_the_knowledge_and_handoffs_tabs_first():
    sheets = FakeSheets({})
    done = apply_sheet(sheets, "acme", acme_config(), draft(tabs=[]), {}, "")
    assert [w[:2] for w in sheets.written] == [("add_tab", "Knowledge"), ("add_tab", "Handoffs"),
                                               ("append_rows", "Knowledge")]
    assert sheets.headers("sheet-1", "Handoffs") == ["Time", "Name", "Phone", "Chat", "Question", "Reason"]
    assert done.created == ["Knowledge", "Handoffs"] and done.rows == 2
    changes = {"tabs": {**acme_config()["tabs"], "Leads": {"customer": []}}, "bot_name": "Mia", "personality": "x"}
    assert summary(done, changes, acme_config())[-2:] == ["Saved permissions for Leads.",
                                                          "Saved Bot name and Personality."]


def test_a_failed_step_stops_and_running_again_finishes_without_repeating():
    sheets = bakery_sheets()
    sheets.fail_writes = {"Knowledge"}
    first = apply_sheet(sheets, "acme", acme_config(), draft(), sheets.tab_headers("sheet-1"),
                        "bot@x.iam.gserviceaccount.com")
    assert first.created == ["Bookings"] and first.columns == {"Orders": ["Status"]} and first.rows == 0
    assert first.error == "Share the Sheet with bot@x.iam.gserviceaccount.com as Editor."
    sheets.fail_writes = set()
    second = apply_sheet(sheets, "acme", acme_config(), draft(), sheets.tab_headers("sheet-1"), "")
    assert second.created == [] and second.columns == {} and second.rows == 1 and second.error == ""
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_guided_setup.py -v`
Expected: ERROR at collection, `ImportError: cannot import name 'apply_sheet'`.

- [ ] **Step 3: Implement**

`app/guided_setup.py`: add to the imports

```python
from app.sheets import sheet_error
```

Append:

```python
def same_question(text: str) -> str:
    """A question as Apply compares it: ignoring case and surrounding or repeated spaces."""
    return " ".join(text.split()).casefold()


def known_questions(sheets, config: dict, sheet_tabs: dict[str, list[str]]) -> set[str]:
    """The questions already in the Knowledge tab; none when the tab doesn't exist yet."""
    tab = find_tab(system_tabs(config)[0][0], sheet_tabs)
    if tab is None:
        return set()
    return {same_question(str(value)) for row in sheets.rows(config["sheet_id"], tab)
            for key, value in row.items() if key.casefold() == "question"}


@dataclass
class Applied:
    created: list[str] = field(default_factory=list)  # tabs added
    columns: dict[str, list[str]] = field(default_factory=dict)  # columns added, per existing tab
    rows: int = 0  # Knowledge rows added
    error: str = ""  # why the Sheet steps stopped; "" when they all worked


def apply_sheet(sheets, business_id: str, config: dict, draft: dict, sheet_tabs: dict[str, list[str]],
                email: str) -> Applied:
    """Add the missing tabs, then the missing columns, then the new Knowledge rows; stop at the first failure.

    `draft` must have passed check_draft against `sheet_tabs`, read just now. Every step skips what already
    exists, so running it again finishes the job.
    """
    done = Applied()
    wanted = [*system_tabs(config), *((tab["name"], tab["columns"]) for tab in draft["tabs"] if tab["use"])]
    sheet_id = config["sheet_id"]
    try:
        for name, columns in wanted:
            if tab_plan(name, columns, sheet_tabs)["existing"] is None:
                sheets.add_tab(sheet_id, name, columns)
                sheet_tabs = {**sheet_tabs, name: list(columns)}
                done.created.append(name)
        for name, columns in wanted:
            plan = tab_plan(name, columns, sheet_tabs)
            if plan["add"]:
                sheets.add_columns(sheet_id, plan["existing"], plan["add"])
                done.columns[plan["existing"]] = plan["add"]
        seen, rows = known_questions(sheets, config, sheet_tabs), []
        for row in draft["knowledge"]:
            if row["keep"] and same_question(row["question"]) not in seen:
                seen.add(same_question(row["question"]))
                rows.append({"Question": row["question"], "Answer": row["answer"]})
        if rows:
            sheets.append_rows(sheet_id, find_tab(wanted[0][0], sheet_tabs), rows)
            done.rows = len(rows)
    except Exception as e:
        log.warning("setup_apply_failed business=%s error=%s", business_id, type(e).__name__)
        done.error = sheet_error(e, email)
    return done


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def summary(done: Applied, changes: dict, config: dict) -> list[str]:
    """What Apply did, in plain words."""
    lines = []
    if done.created:
        lines.append(f"Added {'tab' if len(done.created) == 1 else 'tabs'} {_and(done.created)}.")
    for tab, columns in done.columns.items():
        lines.append(f"Added {'column' if len(columns) == 1 else 'columns'} {_and(columns)} to {tab}.")
    if done.rows:
        lines.append(f"Added {done.rows} Knowledge {'row' if done.rows == 1 else 'rows'}.")
    permitted = [tab for tab in changes.get("tabs", {}) if tab not in (config.get("tabs") or {})]
    if permitted:
        lines.append(f"Saved permissions for {_and(permitted)}.")
    persona = [LABELS[key] for key in PERSONA if key in changes]
    if persona:
        lines.append(f"Saved {_and(persona)}.")
    return lines
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_guided_setup.py -q && uv run ruff check app tests`
Expected: 16 PASS; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add app/guided_setup.py tests/test_guided_setup.py
git commit -m "feat: Apply adds missing tabs, columns and Knowledge rows, stops cleanly, and can run again"
```

---

### Task 7: The Setup screen

**Files:**
- Modify: `app/guided_setup.py` (append `draft_view`; import `sensitive_columns`)
- Modify: `app/pages.py` (`rule_from_form`, `tabs_from_form`, `draft_from_form`, `apply_setup`, `setup_page`)
- Create: `app/templates/setup.html`
- Modify: `app/templates/base.html` (Setup tab; `app.css?v=12`)
- Modify: `app/static/app.css` (`.pre-line`)
- Test: `tests/test_pages_setup.py` (create)

**Interfaces:**
- Consumes: everything from Tasks 2-6; `screen`, `page`, `save`, `Scope` in `app/pages.py`; `sheet_error`, `service_account_email`; `sensitive_columns`.
- Produces:
  - `guided_setup.draft_view(sheets, config, draft, sheet_tabs) -> dict`: `{"plans": [tab_plan + {"configured", "sensitive"}], "system": [{"name", **tab_plan}], "present": [bool per Knowledge row], "problems": check_draft(...)}`
  - `pages.rule_from_form(form, i) -> dict` (shared with the Sheet screen)
  - `pages.draft_from_form(form) -> dict`: reads at most `FORM_MAX = 100` tabs and rows.
  - Route `/setup` (GET, POST) for `/app/setup` and `/admin/b/{id}/setup`. POST `action`: `send`, `draft_now`, `start_over`, `change`, `back`, `save`, `apply`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pages_setup.py`:

```python
import json

import app.guided_setup
from app.guided_setup import draft_from_args
from tests.fakes import SETUP_ARGS, acme_config, call, make_bot, registry_with_acme, say
from tests.webkit import Site, csrf


def site_with(*replies, tabs=None, **llm_options) -> Site:
    registry = registry_with_acme()
    if tabs is not None:
        registry.save_config("acme", {"tabs": tabs}, actor="t")
    return Site(registry=registry, bot=make_bot(*replies, **llm_options)[0])


def stored_draft(site: Site) -> dict:
    draft = draft_from_args(SETUP_ARGS, acme_config())
    site.registry.save_setup("acme", [], draft)
    return draft


def posted(draft: dict, token: str, action: str, **extra) -> dict:
    """The fields the draft screen posts for `draft`, as a browser sends them."""
    data = {"csrf": token, "action": action, "tab_count": str(len(draft["tabs"])),
            "row_count": str(len(draft["knowledge"])),
            **{key: draft[key] for key in ("bot_name", "personality", "instructions")},
            **{f"replace_{key}": "on" for key, ticked in draft["replace"].items() if ticked}}
    for i, tab in enumerate(draft["tabs"]):
        data.update({f"name{i}": tab["name"], f"purpose{i}": tab["purpose"], f"columns{i}": ", ".join(tab["columns"]),
                     f"owner{i}": tab["owner_column"], **{f"{access}{i}": "on" for access in tab["customer"]},
                     **{f"fill_{source}{i}": column for column, source in tab["fill"].items()}})
        data.update({f"use{i}": "on"} if tab["use"] else {})
        data.update({f"confirm{i}": "on"} if tab["confirmed"] else {})
    for i, row in enumerate(draft["knowledge"]):
        data.update({f"question{i}": row["question"], f"answer{i}": row["answer"]})
        data.update({} if row["keep"] else {f"remove{i}": "on"})
    return {**data, **extra}


def test_the_interview_asks_one_question_at_a_time_then_shows_the_draft():
    site = site_with(say("What do customers ask about most?"), call("propose_setup", **SETUP_ARGS))
    http = site.business_user()
    assert "quick questions about Sweet Bakes" in http.get("/app/setup").text
    token = csrf(http, "/app/setup")
    page = http.post("/app/setup", data={"csrf": token, "action": "send", "text": "We bake cakes"}).text
    assert "We bake cakes" in page and "What do customers ask about most?" in page
    page = http.post("/app/setup", data={"csrf": token, "action": "send", "text": "Prices and delivery"}).text
    assert "Bookings" in page and "New tab" in page and "Exists: adds columns Status" in page
    assert "already in your Sheet" in page
    assert site.bot.sheets.written == [] and site.bot.clients["acme"].personality == ""  # nothing applied yet
    assert [m["role"] for m in site.registry.setup("acme")["messages"]] == ["user", "assistant", "user", "assistant"]


def test_apply_adds_only_and_saves_only_the_ticked_settings():
    site = site_with()
    draft = stored_draft(site)
    http = site.business_user()
    page = http.post("/app/setup", data=posted(draft, csrf(http, "/app/setup"), "apply")).text
    for line in ("Added tab Bookings.", "Added column Status to Orders.", "Added 1 Knowledge row.",
                 "Saved permissions for Bookings.", "Saved Personality."):
        assert line in page, line
    client = site.bot.clients["acme"]
    assert client.personality == SETUP_ARGS["personality"] and client.bot_name == "Sara"  # Replace unticked
    assert client.tabs["Bookings"].customer == {"own", "append"}
    assert client.tabs["Orders"].customer == {"own", "append"}  # had permissions: untouched by the draft's read
    entry = site.registry.audit_log("acme")[0]
    assert entry["action"] == "setup.apply" and json.loads(entry["detail"]) == {
        "tabs_created": ["Bookings"], "columns_added": {"Orders": ["Status"]}, "knowledge_rows": 1}
    assert site.registry.setup("acme")["applied_at"] is not None


def test_a_sheet_failure_stops_before_the_settings_and_a_second_apply_finishes():
    site = site_with()
    draft = stored_draft(site)
    site.bot.sheets.fail_writes = {"Knowledge"}
    http = site.business_user()
    token = csrf(http, "/app/setup")
    page = http.post("/app/setup", data=posted(draft, token, "apply")).text
    assert "Added tab Bookings." in page and "Share the Sheet with" in page and "Nothing in the settings changed" in page
    assert site.bot.clients["acme"].personality == "" and "Bookings" not in site.bot.clients["acme"].tabs
    assert site.registry.audit_log("acme")[0]["action"] != "setup.apply"
    site.bot.sheets.fail_writes = set()
    page = http.post("/app/setup", data=posted(draft, token, "apply")).text
    assert "Added 1 Knowledge row." in page and "Added tab" not in page and "Saved Personality." in page
    assert [w[0] for w in site.bot.sheets.written] == ["add_tab", "add_columns", "append_rows"]


def test_problems_block_apply_and_show_at_the_tab():
    site = site_with()
    draft = stored_draft(site)
    http = site.business_user()
    page = http.post("/app/setup", data=posted(draft, csrf(http, "/app/setup"), "apply", name0="Bookings/2026")).text
    assert "Fix the problems marked below" in page
    card = page.split('id="tab-0"', 1)[1].split("</article>", 1)[0]
    assert 'class="field-error"' in card and "a tab name can" in card
    assert site.bot.sheets.written == [] and site.registry.setup("acme")["draft"]["tabs"][0]["name"] == "Bookings/2026"


def test_asking_for_a_change_sends_the_hand_edited_draft_and_back_to_chat_keeps_edits():
    site = site_with(call("propose_setup", **{**SETUP_ARGS, "bot_name": "Zoe"}))
    draft = stored_draft(site)
    http = site.business_user()
    token = csrf(http, "/app/setup")
    page = http.post("/app/setup", data=posted(draft, token, "change", bot_name="Zed", text="Make it formal")).text
    system, *rest = site.bot.llm.calls[0]
    assert '"bot_name": "Zed"' in system["content"] and rest[-1] == {"role": "user", "content": "Make it formal"}
    assert site.registry.setup("acme")["draft"]["bot_name"] == "Zoe" and 'value="Zoe"' in page
    r = http.post("/app/setup", data=posted(draft, token, "back", bot_name="Kept"), follow_redirects=False)
    assert r.headers["location"] == "/app/setup?view=chat#reply"
    assert site.registry.setup("acme")["draft"]["bot_name"] == "Kept"


def test_the_daily_cap_counts_retries_and_start_over_doesnt_reset_it(monkeypatch):
    monkeypatch.setattr(app.guided_setup, "DAILY_CALLS", 2)
    bad = {**SETUP_ARGS, "bot_name": ""}
    site = site_with(call("propose_setup", **bad), call("propose_setup", **bad))
    http = site.business_user()
    token = csrf(http, "/app/setup")
    http.post("/app/setup", data={"csrf": token, "action": "draft_now"})  # a failing draft and its retry: 2 calls
    assert site.registry.setup("acme")["draft"]["bot_name"] == ""  # shown with its problems
    http.post("/app/setup", data={"csrf": token, "action": "start_over"})
    page = http.post("/app/setup", data={"csrf": token, "action": "send", "text": "We bake cakes"}).text
    assert "the limit for today" in page and ">We bake cakes</textarea>" in page
    assert site.registry.setup("acme") == {"messages": [], "draft": None, "applied_at": None}


def test_an_ai_error_keeps_the_owners_text_and_the_conversation():
    site = site_with(fail=True)
    http = site.business_user()
    page = http.post("/app/setup", data={"csrf": csrf(http, "/app/setup"), "action": "send",
                                         "text": "We bake cakes"}).text
    assert "answer right now" in page and ">We bake cakes</textarea>" in page
    assert site.registry.setup("acme")["messages"] == []


def test_thirty_answers_leave_only_make_the_draft_now():
    site = site_with()
    site.registry.save_setup("acme", [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}] * 30,
                             None)
    http = site.business_user()
    page = http.get("/app/setup").text
    assert 'name="text"' not in page and 'value="draft_now"' in page
    r = http.post("/app/setup", data={"csrf": csrf(http, "/app/setup"), "action": "send", "text": "one more"})
    assert "most answers for one interview" in r.text and site.bot.llm.calls == []


def test_setup_is_per_business_and_open_to_admins_even_when_paused():
    site = site_with()
    site.registry.save_setup("acme", [{"role": "user", "content": "Our secret recipe"}], None)
    site.registry.create_business("other", {**acme_config(), "business": "Other Co"}, actor="t")
    assert "Our secret recipe" not in site.business_user("owner@other.pk", "other").get("/app/setup").text
    assert site.business_user().get("/admin/b/acme/setup").status_code == 403
    site.registry.set_active("acme", False, actor="t")
    assert "Our secret recipe" in site.admin().get("/admin/b/acme/setup").text


def test_a_bogus_posted_draft_is_bounded_and_an_unreadable_sheet_blocks_apply():
    site = site_with()
    http = site.business_user()
    token = csrf(http, "/app/setup")
    r = http.post("/app/setup", data={"csrf": token, "action": "save", "tab_count": "999999999", "row_count": "-1"})
    assert r.status_code == 200 and len(site.registry.setup("acme")["draft"]["tabs"]) == 100
    site.bot.sheets.fail_tabs = RuntimeError("Google is down")
    page = http.post("/app/setup", data={"csrf": token, "action": "apply", "tab_count": "0", "row_count": "0"}).text
    assert "Google Sheets couldn" in page and site.bot.sheets.written == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_pages_setup.py -v`
Expected: FAIL: `/app/setup` is 404 (`'quick questions about Sweet Bakes' in '...Not found...'`), and similar.

- [ ] **Step 3: Implement**

`app/guided_setup.py`: change `from app.sheet_rules import tab_problems` to

```python
from app.sheet_rules import sensitive_columns, tab_problems
```

and append:

```python
def draft_view(sheets, config: dict, draft: dict, sheet_tabs: dict[str, list[str]]) -> dict:
    """What the draft screen shows beside the draft: how each tab meets the Sheet, rows already there, problems."""
    try:
        known = known_questions(sheets, config, sheet_tabs)
    except Exception:
        log.exception("setup_knowledge_unreadable")
        known = set()
    plans = []
    for tab in draft["tabs"]:
        plan = tab_plan(tab["name"], tab["columns"], sheet_tabs)
        plans.append({**plan, "configured": has_permissions(plan["existing"] or tab["name"], config),
                      "sensitive": sensitive_columns(plan["headers"])})
    return {"plans": plans,
            "system": [{"name": name, **tab_plan(name, columns, sheet_tabs)} for name, columns in system_tabs(config)],
            "present": [same_question(row["question"]) in known for row in draft["knowledge"]],
            "problems": check_draft(draft, sheet_tabs, config)}
```

`app/pages.py`: add `from app import guided_setup` to the imports (with the other `app` imports, sorted: `from app import guided_setup` goes first). Replace `tabs_from_form` with:

```python
def rule_from_form(form: Form, i: int) -> dict:
    """The permissions ticked for tab i; the Sheet and Setup screens use the same field names."""
    customer = [access for access in ("read", "own", "append") if form.has(f"{access}{i}")]
    rule: dict = {"customer": customer}
    if "own" in customer:
        rule["owner_column"] = form.get(f"owner{i}")
    if "append" in customer:
        rule["fill"] = {form.get(f"fill_{source}{i}"): source for source in ("name", "phone")
                        if form.get(f"fill_{source}{i}")}
    return rule


def tabs_from_form(form: Form, sheet_tabs: dict[str, list[str]]) -> tuple[dict, list[str]]:
    """The per-tab permissions ticked on the Sheet screen, and why any can't be saved."""
    tabs, problems = {}, []
    for i, (tab, headers) in enumerate(sheet_tabs.items()):
        if not form.has(f"use{i}"):
            continue  # the bot doesn't use this tab at all
        rule = rule_from_form(form, i)
        problems += tab_problems(tab, rule, headers, confirmed=form.has(f"confirm{i}"))
        tabs[tab] = rule
    return tabs, problems
```

Append to `app/pages.py`:

```python
FORM_MAX = 100  # most tabs or Knowledge rows read back from one posted draft


def _count(form: Form, name: str) -> int:
    value = form.get(name)
    return min(int(value), FORM_MAX) if value.isdigit() else 0


def draft_from_form(form: Form) -> dict:
    """The draft as posted from the Setup screen, hand edits included."""
    tabs = []
    for i in range(_count(form, "tab_count")):
        rule = rule_from_form(form, i)
        tabs.append({"name": form.get(f"name{i}"), "purpose": form.get(f"purpose{i}"),
                     "columns": guided_setup.split_columns(form.get(f"columns{i}")), "customer": rule["customer"],
                     "owner_column": rule.get("owner_column", ""), "fill": rule.get("fill", {}),
                     "use": form.has(f"use{i}"), "confirmed": form.has(f"confirm{i}")})
    knowledge = [{"question": form.get(f"question{i}"), "answer": form.get(f"answer{i}"),
                  "keep": not form.has(f"remove{i}")} for i in range(_count(form, "row_count"))]
    return {**{key: form.get(key) for key in guided_setup.PERSONA},
            "replace": {key: form.has(f"replace_{key}") for key in guided_setup.PERSONA},
            "tabs": tabs, "knowledge": knowledge}


def apply_setup(request: Request, scope: Scope, draft: dict, sheet_tabs: dict[str, list[str]], email: str) -> dict:
    """Apply a checked draft: the Sheet first, the settings only when every Sheet step worked."""
    business, config = scope.business, scope.business.config
    done = guided_setup.apply_sheet(request.app.state.bot.sheets, business.id, config, draft, sheet_tabs, email)
    error, changes = done.error, {}
    if not error:
        changes = guided_setup.setup_changes(draft, sheet_tabs, config)
        try:
            if changes:
                save(request, scope, changes)
        except ValueError as e:
            error, changes = str(e), {}
    if not error:
        request.app.state.registry.setup_applied(business.id, str(scope.session.user.id), {
            "tabs_created": done.created, "columns_added": done.columns, "knowledge_rows": done.rows})
        log.info("setup_apply business=%s tabs=%s columns=%s rows=%s", business.id, len(done.created),
                 sum(len(columns) for columns in done.columns.values()), done.rows)
    return {"lines": guided_setup.summary(done, changes, config), "error": error}


@screen("/setup", ("GET", "POST"))
def setup_page(request: Request, scope: Scope, form: Form | None) -> Response:
    """Guided setup: the owner chats with the AI, edits its draft, and Apply adds it to the Sheet and settings."""
    state, business = request.app.state, scope.business
    registry, config = state.registry, business.config
    saved = registry.setup(business.id)
    messages, draft = saved["messages"], saved["draft"]
    email = service_account_email(state.settings.google_service_account_file)
    sheet_tabs, sheet_problem = None, ""
    try:
        sheet_tabs = state.bot.sheets.tab_headers(config["sheet_id"])
    except Exception as e:
        sheet_problem = sheet_error(e, email)
    action = form.get("action") if form is not None else ""
    view = "chat" if request.query_params.get("view") == "chat" or draft is None else "draft"
    error, text, result = "", "", None
    if action == "start_over":
        registry.save_setup(business.id, [], None)
        return redirect(f"{scope.base}/setup")
    if action in ("save", "back", "change", "apply"):  # every post from the draft screen keeps the hand edits
        draft, view = draft_from_form(form), "draft"
        registry.save_setup(business.id, messages, draft)
        if action == "save":
            return redirect(f"{scope.base}/setup")
        if action == "back":
            return redirect(f"{scope.base}/setup?view=chat#reply")
    if action in ("send", "draft_now", "change"):
        owner_text = guided_setup.DRAFT_NOW if action == "draft_now" else form.get("text")
        text = "" if action == "draft_now" else owner_text
        if action == "send" and sum(m["role"] == "user" for m in messages) >= guided_setup.MAX_OWNER_MESSAGES:
            error = "That's the most answers for one interview. Press Make the draft now."
        elif not owner_text or len(owner_text) > guided_setup.MAX_MESSAGE:
            error = f"Write a message of 1 to {guided_setup.MAX_MESSAGE:,} characters."
        else:
            try:
                turn = guided_setup.take_turn(
                    state.bot.llm, lambda: registry.spend_setup_call(business.id, guided_setup.DAILY_CALLS),
                    business.id, config, sheet_tabs, messages, draft, owner_text, want_draft=action != "send")
            except guided_setup.SetupError as e:
                error = str(e)
            else:
                registry.save_setup(business.id, turn.messages, turn.draft or draft)
                return redirect(f"{scope.base}/setup" + ("" if turn.draft else "?view=chat#reply"))
    elif action == "apply":
        if sheet_problem:
            error = sheet_problem
        elif guided_setup.check_draft(draft, sheet_tabs, config):
            error = "Fix the problems marked below, then press Apply again."
        else:
            result = apply_setup(request, scope, draft, sheet_tabs, email)
    if sheet_problem:
        view = "chat"  # the draft screen needs the Sheet's tabs
    shown = (guided_setup.draft_view(state.bot.sheets, config, draft, sheet_tabs)
             if view == "draft" and result is None else {})
    return page(request, scope, "setup.html", title="Guided setup", view=view, result=result, error=error,
                config=config, messages=messages, draft=draft, text=text, sheet_problem=sheet_problem,
                greeting=guided_setup.GREETING.format(business=config["business"]),
                owner_messages=sum(m["role"] == "user" for m in messages),
                max_messages=guided_setup.MAX_OWNER_MESSAGES, max_message=guided_setup.MAX_MESSAGE,
                persona=guided_setup.LABELS, limits=guided_setup.LIMITS, **shown)
```

Create `app/templates/setup.html`:

```html
{% extends "base.html" %}
{% block content %}
<h1>Guided setup</h1>
{% if result %}
<section class="setup-phase">
  <header class="phase-head"><span class="phase-tag">{{ "Stopped" if result.error else "Done" }}</span>
    <h2>{{ "Setup stopped part-way" if result.error else "Setup applied" }}</h2></header>
  {% for line in result.lines %}<p>{{ line }}</p>{% endfor %}
  {% if result.error %}
  <p class="notice error">{{ result.error }} Nothing in the settings changed. Fix that, then press Apply again: it
    skips what is already there.</p>
  {% elif not result.lines %}
  <p>Everything in the draft was already in place.</p>
  {% endif %}
  <p><a href="{{ base }}">Home</a> · <a href="{{ base }}/sheet">Sheet page</a> · <a href="{{ base }}/setup">Back to the draft</a></p>
</section>
{% elif view == "draft" %}
<p class="muted lede">Check the draft and change anything you like. Nothing in your Sheet or settings changes until
  you press <strong>Apply</strong>, and Apply only adds: it never deletes, renames or moves anything.</p>
<p><a href="{{ base }}/setup?view=chat">See the conversation</a></p>
{% if problems %}
<div class="notice error"><p>Fix these before you apply:</p>
  <ul>{% for where, message in problems %}<li>{{ message }}</li>{% endfor %}</ul></div>
{% endif %}
<form method="post">
  <input type="hidden" name="csrf" value="{{ csrf }}">
  <input type="hidden" name="tab_count" value="{{ draft.tabs|length }}">
  <input type="hidden" name="row_count" value="{{ draft.knowledge|length }}">

  <h2>How the bot sounds</h2>
  {% for where, message in problems if where == "persona" %}<p class="field-error">{{ message }}</p>{% endfor %}
  {% for key, label in persona.items() %}
  <article>
    <div class="grid">
      {% if config[key] %}
      <div><p><strong>{{ label }} now</strong></p><p class="pre-line">{{ config[key] }}</p></div>
      {% endif %}
      <label>{{ label }}{% if config[key] %}, suggested{% endif %}
        {% if key == "bot_name" %}<input name="bot_name" value="{{ draft.bot_name }}" maxlength="{{ limits.bot_name }}">
        {% else %}<textarea name="{{ key }}" rows="{{ 3 if key == 'personality' else 6 }}" maxlength="{{ limits[key] }}">{{ draft[key] }}</textarea>{% endif %}
      </label>
    </div>
    <label><input type="checkbox" name="replace_{{ key }}"{% if draft.replace[key] %} checked{% endif %}>
      {% if config[key] %}Replace the current {{ label|lower }} with the suggestion{% else %}Save this {{ label|lower }}{% endif %}</label>
  </article>
  {% endfor %}

  <h2>Sheet tabs</h2>
  {% for s in system %}
  <article>
    <header><strong>{{ s.name }}</strong>
      {% if s.existing is none %}<span class="badge good">New tab</span>
      {% elif s.add %}<span class="badge">Exists: adds columns {{ s.add|join(", ") }}</span>
      {% else %}<span class="badge">Exists: nothing to add</span>{% endif %}
      <small>Columns: {{ s.headers|select|join(", ") }}</small></header>
    <p class="muted">{% if loop.first %}Read into every answer the bot gives.{% else %}Where requests for a person are written.{% endif %} Always included.</p>
  </article>
  {% endfor %}
  {% for tab in draft.tabs %}
  {% set i = loop.index0 %}{% set plan = plans[i] %}
  <article id="tab-{{ i }}">
    <header>
      <label><input type="checkbox" class="use-tab" name="use{{ i }}"{% if tab.use %} checked{% endif %}> Use this tab</label>
      {% if plan.existing is none %}<span class="badge good">New tab</span>
      {% elif plan.add %}<span class="badge">Exists: adds columns {{ plan.add|join(", ") }}</span>
      {% else %}<span class="badge">Exists: nothing to add</span>{% endif %}
    </header>
    {% for where, message in problems if where == "tab" ~ i %}<p class="field-error">{{ message }}</p>{% endfor %}
    <div class="tab-options">
      {% if plan.existing is none %}
      <label>Tab name <input name="name{{ i }}" value="{{ tab.name }}" maxlength="100"></label>
      {% else %}
      <p><strong>{{ plan.existing }}</strong></p><input type="hidden" name="name{{ i }}" value="{{ plan.existing }}">
      {% endif %}
      <input type="hidden" name="purpose{{ i }}" value="{{ tab.purpose }}">
      {% if tab.purpose %}<p class="muted">{{ tab.purpose }}</p>{% endif %}
      <label>Columns <small>Separated by commas.{% if plan.existing %} Columns already in the tab stay as they are; new ones go after the last one.{% endif %}</small>
        <input name="columns{{ i }}" value="{{ tab.columns|join(', ') }}"></label>
      {% if plan.configured %}
      <p class="muted">Permissions stay as they are; change them on the <a href="{{ base }}/sheet">Sheet page</a>.</p>
      {% else %}
      <p>Customers can (staff can always look up and add rows):</p>
      <label><input type="checkbox" name="read{{ i }}"{% if "read" in tab.customer %} checked{% endif %}> read all rows</label>
      <label><input type="checkbox" name="own{{ i }}"{% if "own" in tab.customer %} checked{% endif %}> see only their own rows, found by the phone number in
        <select name="owner{{ i }}"><option value="">(pick a column)</option>{% for h in plan.headers if h %}<option{% if h == tab.owner_column %} selected{% endif %}>{{ h }}</option>{% endfor %}</select>
      </label>
      <label><input type="checkbox" name="append{{ i }}"{% if "append" in tab.customer %} checked{% endif %}> add rows (after replying YES), putting their WhatsApp name in
        <select name="fill_name{{ i }}"><option value="">(none)</option>{% for h in plan.headers if h %}<option{% if tab.fill.get(h) == "name" %} selected{% endif %}>{{ h }}</option>{% endfor %}</select>
        and their phone in
        <select name="fill_phone{{ i }}"><option value="">(none)</option>{% for h in plan.headers if h %}<option{% if tab.fill.get(h) == "phone" %} selected{% endif %}>{{ h }}</option>{% endfor %}</select>
      </label>
      {% if plan.sensitive %}
      <p class="notice warn">This tab has contact columns: {{ plan.sensitive|join(", ") }}.</p>
      <label><input type="checkbox" name="confirm{{ i }}"{% if tab.confirmed %} checked{% endif %}> I understand every customer can see these columns if "read all rows" is ticked</label>
      {% endif %}
      {% endif %}
    </div>
  </article>
  {% endfor %}

  <h2>Knowledge</h2>
  <p class="notice warn">Anyone who messages the bot can be told these answers. Never add private details such as
    staff phone numbers, costs or passwords.</p>
  {% for row in draft.knowledge %}
  {% set i = loop.index0 %}
  <article id="row-{{ i }}">
    {% for where, message in problems if where == "row" ~ i %}<p class="field-error">{{ message }}</p>{% endfor %}
    {% if present[i] %}<p><span class="badge">already in your Sheet</span> This question won't be added again.</p>{% endif %}
    <label>Question <input name="question{{ i }}" value="{{ row.question }}" maxlength="200"></label>
    <label>Answer <textarea name="answer{{ i }}" rows="2" maxlength="1000">{{ row.answer }}</textarea></label>
    <label><input type="checkbox" name="remove{{ i }}"{% if not row.keep %} checked{% endif %}> Remove this row</label>
  </article>
  {% else %}
  <p class="muted">No Knowledge rows in this draft.</p>
  {% endfor %}

  <h2>Ask the AI to change something</h2>
  <label>What should change? <small>For example: make it more formal; add a Deliveries tab.</small>
    <textarea name="text" rows="2" maxlength="{{ max_message }}">{{ text }}</textarea></label>
  <div class="grid">
    <button type="submit" name="action" value="change" class="secondary">Ask the AI</button>
    <button type="submit" name="action" value="back" class="secondary">Back to chat</button>
  </div>

  <h2>Apply</h2>
  <div class="grid">
    <button type="submit" name="action" value="save" class="secondary">Save my changes</button>
    <button type="submit" name="action" value="apply"
            data-confirm="Apply this setup to {{ business.config.business }}? It adds the tabs, columns and Knowledge rows to your Sheet and saves the ticked settings. Nothing is deleted.">Apply</button>
  </div>
</form>
{% else %}
<p class="muted lede">Answer a few questions and the assistant drafts your Sheet tabs, Knowledge, permissions and how
  the bot sounds. Nothing changes until you press <strong>Apply</strong> on the draft.</p>
{% if sheet_problem and sheet_problem != error %}<p class="notice error">{{ sheet_problem }}</p>{% endif %}
{% if draft %}<p><a href="{{ base }}/setup">Open the draft →</a></p>{% endif %}
<div class="chat">
  <div class="msg bot"><p>{{ greeting }}</p></div>
  {% for m in messages %}
  <div class="msg {{ 'customer' if m.role == 'user' else 'bot' }}"><p class="pre-line">{{ m.content }}</p></div>
  {% endfor %}
</div>
<form method="post" id="reply">
  <input type="hidden" name="csrf" value="{{ csrf }}">
  {% if owner_messages < max_messages %}
  <label>Your answer <textarea name="text" rows="3" maxlength="{{ max_message }}" required>{{ text }}</textarea></label>
  <div class="grid">
    <button type="submit" name="action" value="send">Send</button>
    <button type="submit" name="action" value="draft_now" class="secondary" formnovalidate>Make the draft now</button>
  </div>
  {% else %}
  <p class="notice warn">That's the most answers for one interview. Make the draft now; you can change it afterwards.</p>
  <button type="submit" name="action" value="draft_now">Make the draft now</button>
  {% endif %}
</form>
{% if messages or draft %}
<section class="danger-zone">
  <h2>Start over</h2>
  <p class="muted">Clears the conversation and the draft. Nothing in your Sheet or settings changes.</p>
  <form method="post">
    <input type="hidden" name="csrf" value="{{ csrf }}">
    <button type="submit" name="action" value="start_over" class="danger"
            data-confirm="Start over? The conversation and the draft are cleared. Nothing in your Sheet or settings changes.">Start over</button>
  </form>
</section>
{% endif %}
{% endif %}
{% endblock %}
```

`app/templates/base.html`: after `<li><a href="{{ base }}">Home</a></li>` add `<li><a href="{{ base }}/setup">Setup</a></li>`, and change `app.css?v=11` to `app.css?v=12`.

`app/static/app.css`: append

```css
/* Guided setup: chat bubbles and saved text keep their line breaks */
.pre-line { white-space: pre-line; }
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_pages_setup.py tests/test_web_ux.py tests/test_pages_staff_sheet.py -q && uv run ruff check app tests`
Expected: all PASS (the Sheet screen still works with `rule_from_form`; the new template has no inline styles); ruff clean.

- [ ] **Step 5: Commit**

```bash
git add app/guided_setup.py app/pages.py app/templates/setup.html app/templates/base.html app/static/app.css tests/test_pages_setup.py
git commit -m "feat: the Setup screen: chat with the AI, edit its draft, and Apply it (adds only)"
```

---

### Task 8: Home card, Settings link and docs

**Files:**
- Modify: `app/pages.py` (`home`)
- Modify: `app/templates/business_home.html`, `app/templates/settings.html`
- Modify: `docs/setup-guide.md` (Part A step 11, Part K), `README.md`
- Test: `tests/test_pages_setup.py`

**Interfaces:**
- Consumes: `Registry.setup(business_id)["applied_at"]`, `Registry.setup_applied`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pages_setup.py`:

```python
def test_home_shows_the_setup_card_until_set_up_and_settings_links_to_it():
    site = site_with(tabs={})
    http = site.business_user()
    assert "Set up your assistant" in http.get("/app").text
    assert "Guided setup" in http.get("/app/settings").text
    site.registry.save_setup("acme", [], None)
    site.registry.setup_applied("acme", actor="t", detail={})
    assert "Set up your assistant" not in http.get("/app").text
    assert "Set up your assistant" not in site_with().business_user().get("/app").text  # set up by hand: tabs saved
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_pages_setup.py -k setup_card -v`
Expected: FAIL (`'Set up your assistant' in ...` is False).

- [ ] **Step 3: Implement**

`app/pages.py`, `home`: add to the `page(...)` call

```python
                setup_card=not config.get("tabs") and request.app.state.registry.setup(business.id)["applied_at"] is None,
```

`app/templates/business_home.html`: after the paused notice (line 3), add

```html
{% if setup_card %}
<section class="setup-phase">
  <header class="phase-head"><span class="phase-tag">Start here</span><h2>Set up your assistant</h2></header>
  <p class="muted lede">Answer a few questions and the assistant drafts your Sheet tabs, Knowledge, permissions and
    how the bot sounds. Nothing changes until you press Apply.</p>
  <p><a href="{{ base }}/setup">Start guided setup →</a></p>
</section>
{% endif %}
```

`app/templates/settings.html`: after `<h1>Bot settings</h1>` add

```html
<p class="muted">Starting out? <a href="{{ base }}/setup">Guided setup</a> drafts these settings, your Sheet tabs and
  Knowledge by asking you a few questions.</p>
```

`docs/setup-guide.md`, Part A: after step 11's list (before step 12), add

```markdown
    > **Tip:** with the dashboard you can skip this step. Add the business with the empty, shared Sheet, and its
    > owner opens **Setup** (Part K, "Guided setup"): it asks about the business and creates these tabs with their
    > headers. Only the empty Sheet and the share (step 13) are needed.
```

Part K, the paragraph listing what a business login sees: add **Setup** after **Home**. Then add a section after "Add a business":

```markdown
### Guided setup (the owner sets up the bot by chatting)

A business with an empty, shared Sheet can be set up by its owner without this guide's Sheet section. Their
**Home** shows "Set up your assistant" until it is done.

1. Open **Setup**. The assistant asks about the business one question at a time (usually 6 to 12 questions).
   **Make the draft now** skips ahead.
2. The draft shows: the bot's name, **Personality** (how it sounds: tone, emoji, formality) and **Instructions**,
   with the current text beside the suggestion and a **Replace** tick; the tabs with their columns and what
   customers may do on each; and Knowledge questions with answers. Edit anything by hand, or type a change for
   the AI ("make it more formal", "add a Deliveries tab").
3. Press **Apply**.
   You should see: what was added, for example "Added tabs Orders and Bookings. Added 8 Knowledge rows. Saved
   Personality."

- Apply only adds. It never deletes, renames or moves tabs or columns, never changes the permissions of a tab that
  already has some (change those on **Sheet**), and replaces the name, Personality or Instructions only where
  **Replace** is ticked. The Knowledge and Handoffs tabs are created when missing.
- The permissions pass the same checks as the Sheet page (below).
- If the Sheet stops being readable part-way (for example the share was removed), Apply stops before changing any
  setting and lists what it already added. Fix it and press **Apply** again: it skips what is already there.
- The AI is used at most 60 times per business per day; after that, editing the draft and **Apply** still work.
  An interview nobody touches for 30 days is forgotten. Admins can open any business's **Setup** to help.
- **Personality** is also on **Bot settings**. It sets the bot's tone and never overrides its rules.
```

`README.md`, "The dashboard" list: add after the "Each business" bullet

```markdown
- **Guided setup:** a business owner answers a few questions and the AI drafts their Sheet tabs, Knowledge,
  permissions and the bot's persona; nothing changes until they press **Apply**, which only adds.
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest -q && uv run ruff check .`
Expected: everything PASSES; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add app/pages.py app/templates/business_home.html app/templates/settings.html docs/setup-guide.md README.md tests/test_pages_setup.py
git commit -m "feat: a Home card and a Settings link to guided setup, and its docs"
```
