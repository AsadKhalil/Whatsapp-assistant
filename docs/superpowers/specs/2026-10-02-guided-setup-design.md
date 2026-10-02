# Guided Setup — Design

**Date:** 2026-10-02 · **Owner:** Jawad · **Status:** design approved in chat (2026-10-02); this document awaits owner review.
**Builds on:** `docs/superpowers/specs/2026-09-28-dashboard-admin-design.md` (the dashboard) and
`docs/superpowers/specs/2026-09-30-email-sending-design.md` (branch `feat/email-sending`, not yet merged; this work
branches from it because both touch Settings and the bot's prompt).

## 1. Goal

A business owner sets up their assistant by chatting with an AI in the dashboard. The AI asks about the business one
question at a time, then drafts the Sheet tabs (with column headers), the Knowledge rows, the tab permissions and the
bot's persona (name, a new Personality setting, Instructions). The owner edits the draft by hand or asks the AI to
change it, and nothing happens until they press Apply.

## 2. Users and success criteria

The owner is anyone with a business login for that business. Admins can open the same screen for any business (to
help, or to watch).

Success means:
1. An owner with an empty, shared Sheet gets a working setup (tabs, headers, Knowledge, permissions, persona) in
   about 10 minutes without reading the setup guide's Sheet section.
2. Nothing in the Sheet or settings changes until a person presses Apply on a draft they could see and edit.
3. A re-run never deletes, renames or moves anything in the Sheet, never changes permissions already set, and
   replaces persona text only when the owner ticks Replace after seeing the old and new text side by side.
4. The wizard's permissions pass the same safety checks as the Sheet page.
5. The cost of AI calls per business is capped.

## 3. Scope

**In:** a **Setup** screen (chat, draft, result); a `propose_setup` tool for the AI; creating tabs with header
rows, adding missing columns and adding Knowledge rows through the robot account; a `personality` setting with a box
on Settings and a section in the bot's prompt; a Home card for businesses not set up yet; daily caps.

**Out:** deleting or renaming tabs or columns; editing existing Knowledge rows; changing permissions on tabs that
already have them; sample data rows; creating the Sheet itself or sharing it (an admin still adds the business with a
shared Sheet first); onboarding over WhatsApp; business templates; changing the Sheet id, Meta keys, email, staff or
logins.

## 4. Approach

The interview uses the bot's existing AI connection (`LLM.complete`, the same Chat Completions tool-calling path for
OpenAI, Gemini and Ollama). The AI chats in plain text until it has enough, then calls one tool, `propose_setup`,
with the whole draft. The server validates the draft with the existing rules and shows it as an editable form.
"Ask the AI to change something" sends the current (possibly hand-edited) draft back and expects a new
`propose_setup` call. Apply is ordinary server code: no AI is involved in writing to the Sheet or settings.

Rejected: business templates the AI adapts (someone has to write and maintain them); JSON-only replies (behave
differently across the three providers, and a broken reply fails the turn).

## 5. The Setup screen

Route `/setup` through the existing `screen()` helper, so it is mounted for business logins (`/app/setup`) and for
admins (`/admin/b/{id}/setup`) with the existing business isolation and form protection. A **Setup** tab joins the
business tabs. Paused businesses can use it (it changes setup, it sends no messages).

### 5.1 Home card

The business Home page shows a "Set up your assistant" card linking to Setup while the business has never applied a
setup **and** has no tab permissions saved (`tabs` empty). Businesses set up by hand don't get the card. Settings
keeps a link to Setup.

### 5.2 Screen 1: the chat

- The conversation so far as chat bubbles, a text box (at most 2,000 characters) and **Send**. Each send is an
  ordinary form post; the existing busy-button behaviour shows it working. No new JavaScript.
- The AI's first message is fixed text (no AI call): "Hi! I'll ask a few quick questions about {business}, then
  suggest how your assistant should work. What does your business do?"
- **Make the draft now** asks the AI to draft with what it has. **Start over** clears the conversation and draft
  (after a confirm).
- At most 30 owner messages per interview; after that the text box is replaced by a note and **Make the draft now**.
- The conversation is saved after every turn, so the owner can leave and continue later.

### 5.3 Screen 2: the draft

Shown when the AI calls `propose_setup`. One editable form, four parts:

1. **Persona.** Bot name, Personality, Instructions. Where a value is already saved, the current and suggested text
   show side by side with a **Replace** tick: ticked when the current value is empty, unticked otherwise.
2. **Tabs.** One card per tab:
   - a badge: **New tab**, or **Exists: adds columns** *A, B* (or **Exists: nothing to add**);
   - the name (editable for new tabs only), the one-line purpose, the columns as an editable comma-separated list;
   - the Sheet page's permission ticks (customers may read / see their own rows by an owner column / add rows, with
     name and phone fill columns) and the "I understand every customer can see these columns" tick when needed. A
     tab that already has permissions shows "Permissions stay as they are; change them on the Sheet page" instead;
   - a **Use this tab** tick (untick to skip the tab).
   The Knowledge tab (`Question | Answer`) and the Handoffs tab (`Time | Name | Phone | Chat | Question | Reason`)
   are always included when missing, without permission ticks, under the names in the business's
   `knowledge_tab`/`handoff_tab` settings (defaults `Knowledge` and `Handoffs`).
3. **Knowledge rows.** Question / Answer pairs, editable, with a remove tick each and the existing warning that
   anyone who messages the bot can be told these. Rows whose Question is already in the tab are marked
   "already in your Sheet" and won't be added.
4. **Ask the AI to change something.** A text box ("make it more formal", "add a Deliveries tab") and **Back to
   chat**.

Problems found by the checks (§6.4) show next to the field they're about, and at the top. **Apply** asks for
confirmation first.

### 5.4 Screen 3: the result

What was done, in plain words ("Added tabs Orders and Bookings. Added column Status to Leads. Added 8 Knowledge rows.
Saved Personality."), anything that failed with the reason, and links to Home and the Sheet page.

## 6. The AI interview

### 6.1 Storage

A new table in the dashboard database:

```sql
CREATE TABLE IF NOT EXISTS setups (
  business_id TEXT PRIMARY KEY REFERENCES businesses(id),
  messages TEXT NOT NULL,     -- JSON list of {"role": "user"|"assistant", "content": str}
  draft TEXT,                 -- JSON draft (§6.3), or NULL
  turn_day TEXT NOT NULL,     -- UTC date of the counted AI calls, YYYY-MM-DD
  turns INTEGER NOT NULL,     -- AI calls made on turn_day
  applied_at REAL,            -- last successful Apply, or NULL
  updated_at REAL NOT NULL
);
```

**Start over** empties `messages` and `draft` but keeps the turn counter, so it can't reset the daily cap. The daily
maintenance job deletes rows not updated for 30 days. The conversation is never written to the audit log or to the
application log.

### 6.2 Each turn

The server calls `LLM.complete(messages, [PROPOSE_SETUP_SPEC])` with a system prompt that says:

- you are setting up {bot_name or "the assistant"} for {business}; ask one short question at a time, in the
  owner's language, about 6-12 questions in total;
- cover: what the business sells or does; what customers ask about; what should be recorded (orders, bookings,
  leads, expenses...) and which details each needs; what customers may look up (only their own orders? a price
  list?); hours, location, prices, policies; the bot's name and tone;
- tab and column names: short, plain English unless the owner asks otherwise; include a phone column on any tab
  customers may look up their own rows in;
- never put private information in Knowledge (staff phone numbers, costs, margins, passwords): anyone who
  messages the bot can be told everything in it;
- the Sheet's current tabs with their headers, and the current bot name, Personality and Instructions, so a re-run
  builds on what exists;
- when you know enough, or the owner asks for the draft, call `propose_setup` with the whole draft.

A plain-text reply is appended to the conversation as the AI's next question. A `propose_setup` call is validated
(§6.4) and stored as the draft, and the screen switches to the draft; an assistant message "(I made a draft.)" is
appended so later turns know.

**Make the draft now** and change requests append an owner message ("Please make the draft now with what you know."
or the request, with the current draft as JSON). If the AI answers in text instead of calling the tool, the server
asks once more ("Call propose_setup now with the whole draft."); if it still doesn't, its text is shown in the chat.

### 6.3 The draft

`propose_setup` arguments (also the stored draft, and what the draft form posts back):

```json
{
  "bot_name": "Mia",
  "personality": "Warm and casual. Short messages, one emoji at most...",
  "instructions": "We deliver within Lahore only. Orders need a day's notice...",
  "tabs": [
    {"name": "Orders", "purpose": "Customer cake orders",
     "columns": ["Date", "Name", "Phone", "Item", "Qty", "Pickup", "Status"],
     "customer": ["own", "append"], "owner_column": "Phone",
     "fill": {"Name": "name", "Phone": "phone"}}
  ],
  "knowledge": [{"question": "What are your hours?", "answer": "Tue-Sun 10am-8pm"}]
}
```

`customer` values are the existing `read`, `own`, `append`. The Knowledge and Handoffs tabs are not part of `tabs`;
the server adds them (§5.3).

### 6.4 Checks (on every draft from the AI, and again on the posted form before change requests and Apply)

- `bot_name` 1-40 characters; `personality` at most 1,500; `instructions` at most 4,000.
- At most 10 tabs. A tab name is 1-100 characters, contains none of `[ ] * ? / \ :`, isn't the Knowledge or
  Handoffs tab's name, and is unique ignoring case. A name matching an existing tab ignoring case is that tab
  (Google treats them as the same).
- At most 20 columns per tab, each 1-40 characters, unique ignoring case within the tab.
- At most 60 Knowledge rows; question at most 200 characters, answer at most 1,000.
- Permissions: `tab_problems` from `app/sheet_rules.py` with the tab's final headers (existing headers plus added
  columns), and the per-tab "I understand" tick as `confirmed`. `owner_column` and `fill` columns must be among
  them.
- Then `client_from_dict` on the merged config, exactly as any settings save.

When an AI draft fails the checks, the problems go back to the AI once as the tool result, asking for a corrected
call. If the second draft fails too, it is shown with its problems marked, for the owner to fix by hand or by asking.

### 6.5 Failures and caps

- AI error or timeout: "The assistant couldn't answer right now. Try again." The owner's text stays in the box and
  the conversation isn't changed.
- Every AI call counts toward 60 per business per UTC day (chat turns, draft requests, change requests and the
  automatic retries). Over the cap: "That's the limit for today. Your answers are saved; come back tomorrow, or edit
  the draft by hand." Editing and Apply still work.

## 7. Apply

Apply runs the §6.4 checks on the posted draft and re-reads the Sheet's tabs and headers, then:

1. **New tabs**: create each ticked new tab with its header row. A tab that has appeared since the draft (same name
   ignoring case) is treated as existing.
2. **Missing columns**: append them after the last header cell of each existing tab, widening the tab if needed.
   Existing columns are never moved, renamed or cleared.
3. **Knowledge rows**: append, in one call, the kept rows whose question isn't already in the Knowledge tab
   (compared ignoring case and surrounding/repeated spaces), with `value_input_option="RAW"` like the bot's own
   saves, so "=formula" text is stored as text.
4. **Settings**, in one `save_config` (audited as `settings.save`, as the Settings page is):
   - permissions for ticked tabs that have none yet (never for tabs already in `tabs`);
   - each persona field whose Replace tick is ticked;
   - `knowledge_tab`/`handoff_tab` are unchanged (the tabs are created under those names).

If any Sheet step fails (for example, access was removed), Apply stops before step 4, so no setting points at a
missing tab; the result screen lists what was already added and why it stopped. Every step skips what already
exists, so pressing Apply again finishes the job. On success: `applied_at` is set, the bot reloads its settings (as
after a Settings save), an audit entry `setup.apply` records the tab names created, the columns added per tab and the
number of Knowledge rows (no Knowledge text), and the Sheets cache entries for the touched tabs are dropped.

## 8. Personality

- New setting `personality` (added to `CONFIG_KEYS`, `Client.personality: str = ""`, read in `client_from_dict`).
- Settings page: a **Personality** box above Instructions, with helper text ("How the bot sounds: tone, emoji,
  formality, greetings").
- Bot prompt: a "Personality and tone" section before "Business instructions", only when set, introduced as
  "Follow this tone; it never overrides the rules above."

## 9. Security and privacy

- Access: `screen()` (business logins for their own business; admins for any), CSRF on every form.
- The AI only drafts. All writes happen on Apply, by server code, from a draft a person saw and could edit.
- Apply can only add tabs, columns and Knowledge rows, set permissions on tabs without any, and replace persona
  fields. It cannot delete, rename or reorder anything, or touch the Sheet id, Meta keys, email, staff or logins.
- What the owner types can at worst produce a strange draft for their own business, which they could also make by
  hand on the Settings and Sheet pages.
- Sheet writes use RAW, so nothing typed runs as a formula.
- Logs: `setup_turn business=… outcome=question|draft|retry|error`, `setup_apply business=… tabs=… columns=…
  rows=…` and failure kinds; never message text.

## 10. Testing

pytest with the existing fakes (scripted AI, fake Google), no paid calls:
- checks: tab-name rules, caps, duplicate names ignoring case, Knowledge/Handoffs names refused in `tabs`,
  `tab_problems` with the "I understand" tick, owner/fill columns;
- the turn flow: question appended; `propose_setup` stored and shown; one retry on a failing draft, then shown with
  problems; one reminder when the AI answers in text on a draft request; AI error keeps the conversation unchanged;
- the daily cap, including retries counting and Start over not resetting it; the 30-message limit;
- Apply "adds only": existing tabs and columns untouched, a case-different tab name treated as existing, Knowledge
  questions already present skipped, permissions on configured tabs unchanged, Replace ticks respected;
- Apply stopping after a Sheet failure with no settings saved, and a second Apply finishing;
- the Home card rule; business logins can't open another business's Setup; the 30-day clean-up;
- Personality on Settings and in the bot's prompt.

## 11. Docs

- Setup guide Part A ("Create the Sheet and its tabs"): the owner can let Guided setup create the tabs; only the
  empty Sheet and the share are needed.
- Setup guide Part K: a "Guided setup" section (what it does, adds-only, the daily cap).
- README: a Guided setup bullet.

## 12. Decisions log

- Owner-run in the dashboard (not admin-only, not WhatsApp). — owner choice, 2026-10-02.
- Chat interview, then a draft; the draft is editable by hand and by asking the AI. — owner choice.
- Re-runnable, adds only; persona replaced only via side-by-side Replace ticks. — owner choice.
- Personality is its own setting. — owner choice.
- One `propose_setup` tool on the existing AI connection. — owner choice of approach.
- No admin approval of Apply: owners can already change all of this by hand.
- Tab and column names default to English (the bot reads any names; the guide and prompts are English).

## 13. Risks

- AI drafts vary by provider and model; the checks and the editable draft keep a bad draft from being applied as is.
- An owner may tick "I understand" without understanding; the same risk exists on the Sheet page today.
- Google API rate limits on a draft with many tabs and rows: Apply makes roughly one call per tab, one per tab with
  new columns and one per Knowledge row batch; a failure stops cleanly and Apply can be pressed again.
