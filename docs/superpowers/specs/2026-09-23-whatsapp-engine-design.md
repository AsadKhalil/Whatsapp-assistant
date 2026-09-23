# WhatsApp Assistant Engine (v1) — Design

**Date:** 2026-09-23 · **Owner:** Jawad · **Status:** sections 1–7 agreed in brainstorming. Sections marked *(default, not yet reviewed)* are Claude's defaults, written when the owner asked to go straight to the plan.

## 1. Goal

Sell personalized WhatsApp AI assistants to businesses. The product has three sub-projects, built in this order, each with its own spec and plan:

1. **Bot engine** (this spec)
2. Self-serve client dashboard: sign-up, bot settings, document upload, connecting a Sheet and numbers, chat viewer
3. Billing and usage

v1 succeeds when one pilot client is live:
- Their customers chat 1:1 with the client's official WhatsApp number and get correct answers.
- Their groups get answers from a purchased "persona" number when someone @mentions it.
- Answers draw on business knowledge, the client's Google Sheet and recent group history.
- The bot adds Sheet rows only after a YES.
- Voice notes are understood.

## 2. Constraints (verified 2026-09-23; re-check before launch)

- **AI policy.** Meta's WhatsApp Business Solution Terms ban general-purpose AI assistants on the Cloud API, except for users with EEA or Brazil numbers. The bot is a business assistant: the AI serves the client's business.
- **Groups.** The official Groups API cannot join existing groups (bot-created only, max 8 participants, Official Business Account required). Existing groups therefore go through WAHA (unofficial, linked device) on a purchased number.
  - This breaks WhatsApp's Terms. The ban risk is contained to the purchased number.
  - Group presence is a done-for-you add-on, never a self-serve feature.
- **Pricing.** From 2026-10-01, every bot reply is a paid service message after 1,000 free per number per month. A payment method must be on the client's Meta account.
- **User identity.** Webhooks carry a business-scoped user id (BSUID), and the phone number may be absent. The official channel keys users by BSUID and stores the phone when present.
- **Linked devices** are logged out if the persona number's phone is offline for 14+ days.
- **Disclosure.** The bot always says it is an AI assistant.

## 3. Scope

**In v1:**
- One pilot client, configured by hand
- Two channels:
  - the client's official number (Cloud API) for customer 1:1 chats
  - the persona number (WAHA) for groups and staff 1:1 chats
- Knowledge in the prompt, loaded from a "Knowledge" Sheet tab
- Sheet lookups scoped by role, and Sheet appends that need a YES
- Group history as context
- Voice-note transcription
- Handoff to staff, AI disclosure, message retention

**Out of v1:** dashboard, billing, Tech Provider / Embedded Signup, coexistence, document search / embeddings, reminders and templates (bot-initiated messages), images, outgoing audio, horizontal scaling.

## 4. Architecture

```
Customer 1:1  → Meta Cloud API → POST /webhooks/meta ┐
Group / staff → WAHA           → POST /webhooks/waha ┴→ Incoming → bot.handle() → reply via the same channel
```

- **Service.** One FastAPI service. Webhooks check the signature, return 200 at once, and process the message in a FastAPI background task. There is no queue in v1.
- **Storage.** SQLite (stdlib `sqlite3`, WAL mode).
- **AI.** Called through the `openai` SDK's Chat Completions API with tool calling. `base_url`, `api_key` and `model` are settings, so OpenAI, Gemini (via its OpenAI compatibility) and Ollama Cloud share one code path.
- **Transcription.** An OpenAI-compatible `/audio/transcriptions` endpoint with its own settings. Gemini's compatibility layer has no such endpoint, so the default is OpenAI's `gpt-transcribe`, even when chat runs on Gemini or Ollama.
- **Deployment.** One VPS running Docker Compose:
  - `engine`
  - `waha`, not publicly exposed
  - `caddy`, providing HTTPS for Meta's webhook

**Simplification vs the chat design.** Client settings and chat roles live in a hand-edited `clients.yaml`, not in `clients` / `chats` tables. The dashboard project will move them into the database. SQLite holds only messages and pending writes.

## 5. Message pipeline — `bot.handle(incoming)`

1. **Save the message.** The unique key `(channel, message id)` drops Meta/WAHA retries. The bot's own echoes are saved as bot messages and never answered.
2. **Voice notes.** Download the note. If it is over 1 MB (about 5 minutes), send a polite reply composed by code. Otherwise transcribe it and store the transcript as the message text. Every voice note is transcribed, including group notes the bot won't answer, so history stays complete.
3. **Decide whether to reply.**
   - In 1:1 chats, always.
   - In groups, only when the bot is @mentioned or someone replies to one of its messages.
   - Loop breaker: at most 6 bot replies per chat per 10 minutes.
4. **Pending confirmation.** This applies if the sender has an unexpired pending write in this chat:
   - A message that is exactly a yes-word executes it. Yes-words: "yes", "y", "confirm", "haan", "ji", "نعم", "ہاں", "👍".
   - A no-word cancels it.
   - Anything else goes to the model. A new proposal replaces the old one.
5. **Build the context.**
   - The system prompt contains: persona, rules, the tabs this role may use, current date/time in the client's timezone, business instructions, and the Knowledge tab text (cached for 5 minutes).
   - The chat's last 50 messages follow, with sender names in groups.
6. **Tool loop.** Up to 4 model calls. Tools: `lookup_rows(tab, query)`, `propose_row(tab, values)`, `handoff(reason)`.
7. **Code-composed replies.** These texts are always composed by code, never by the model:
   - Write proposals: "Add to Orders: …? Reply YES to confirm."
   - Write results: "✅ Added to Orders", sent only after the Sheets API succeeds.
   - Handoff acknowledgements.
   - The AI-disclosure intro on the bot's first message in a chat.
8. **Send** the reply through the incoming channel and store it. In groups, the reply quotes the message that triggered it.

## 6. Permissions (enforced in tool code, never by the prompt)

- **Roles.**
  - `staff`: chats listed in `staff_chats`, plus 1:1 senders listed in `staff_numbers`.
  - In a group, only the group decides. A staff member writing in a customer group gets customer access, so private rows never land in a customer group.
  - `customer`: everyone else, including unknown groups.
- **Customer access** is set per tab with a set of flags:
  - `read`: all rows
  - `own`: only rows whose `owner_column` equals the sender's phone
  - `append`: may propose new rows
- **Customers in groups** get only `read` tabs. `own` and `append` work in private chats only, so one customer's orders and phone number are never shown to a whole group.
- **Staff** may `read` and `append` on every configured tab.
- **Customer appends** have their `fill` columns set by code from the sender (e.g. `Name` ← WhatsApp name, `Phone` ← phone).
- **Hidden phone numbers.** If the phone is hidden (username user):
  - `own` lookups are refused, and the model offers a handoff.
  - An append with a phone `fill` column needs the customer to type a contact number, which is then kept.
- **Lookups** return at most 20 rows.

## 7. Handoff and disclosure

- **Handoff.** `handoff` appends a row to the client's `handoff_tab` (time, name, phone, question, reason). It also posts a best-effort alert to the client's `staff_alert_chat` via WAHA. The customer gets an acknowledgement composed by code; if their phone is hidden, it asks for a contact number.
- **Disclosure.** The bot's first message in any chat starts with: "Hi, I'm {bot_name}, {business}'s AI assistant." In groups it adds: "I read messages here so I can answer when you @mention me." When the purchased number is added to a group (WAHA `group.v2.join`), it posts that intro right away.
- **Retention.** Messages older than `retention_days` (default 90) are deleted daily.

## 8. Error handling *(default, not yet reviewed)*

- **Bad webhook signature:** respond 403 and store nothing.
- **Processing errors:** logged. Meta and WAHA always get a 200 once the signature is valid.
- **Model call:** 30 s timeout and one retry. After that, send the code-composed fallback ("Sorry, I'm having trouble right now. The team will get back to you.") and add a handoff row.
- **Sheets errors inside tools:** return `{"error": ...}` to the model. It must not claim success; success text is composed by code anyway.
- **Append failure:** keep the pending write and reply "Couldn't save that, reply YES to try again."
- **Send errors:**
  - Meta's outside-24h-window error: log only.
  - Rate-limit errors: one retry after 2 s.
  - WAHA errors: log.
- **`/health`:** returns 503 unless the database is writable and the WAHA session is `WORKING`. A free external uptime monitor emails the owner.
- **Logs:** never contain message text. User ids are logged as short hashes.

## 9. Deployment and operations *(default, not yet reviewed)*

- **Docker Compose on one VPS:**
  - `engine`: `python:3.12-slim` + uv
  - `waha`: sessions on a volume, API key required, bound only to the compose network. Its dashboard is reached through an SSH tunnel for QR linking.
  - `caddy`: automatic HTTPS for `/webhooks/meta` and `/health`
- **Daily maintenance loop** in the engine: delete expired messages, then `VACUUM INTO backups/assistant-YYYYMMDD.db`, keeping 7 copies.
- **Runbook in the README:**
  - Meta app setup and webhook subscription
  - Payment method
  - Sharing the Sheet with the service-account email
  - WAHA session and QR linking
  - Swapping the persona number after a ban. History survives and group ids don't change.

## 10. Testing *(default, not yet reviewed)*

- **Automated tests:** pytest, no network.
  - Fixture payloads for Meta and WAHA parsing and signatures.
  - Store tests: dedupe, history, pending expiry, retention.
  - Permission tests.
  - Bot pipeline tests with a scripted fake model: reply/no-reply rules, mention, propose → YES / NO / expiry, handoff, intro, loop breaker, voice note, model failure.
  - API tests with FastAPI's TestClient.
  - The OpenAI SDK wrapper, tested through `httpx.MockTransport`.
- **Model choice.** An eval runner plays 13 scripted chats against each candidate provider/model, with more added from real pilot chats. It costs money and is run manually. The default model is the cheapest one that passes every case.
- **Manual smoke test:** a Meta test number, plus a WAHA session on the purchased number.

## 11. Decisions log (owner decisions in brainstorming — do not re-litigate)

- **Buyer:** businesses.
- **Users:** customers 1:1 on the official API **and** a purchased persona number in existing groups.
- **v1 capabilities:** business knowledge, reading Sheets, writing Sheets, group history.
- **Admin:** a self-serve dashboard is wanted and is built as sub-project 2, after the engine. The engine ships first with a hand-configured pilot.
- **AI providers:** Ollama Cloud, Gemini or OpenAI. The engine supports all three via `base_url`; the default is chosen by eval.
- **Approach:** A, a Python service + WAHA.
- **Voice notes:** in v1.

## 12. Amendments during planning (2026-09-23, from API research)

- **Default model: `gpt-6-luna`** ($0.10 / $0.50 per 1M tokens), the cheapest current OpenAI model.
  - OpenAI accepts tools in Chat Completions only with `reasoning_effort="none"`.
  - Gemini 2.5 Flash-Lite is closed to new API keys, so the Gemini candidates are `gemini-3.5-flash-lite` and `gemini-3.8-flash`.
  - The Ollama Cloud candidate is `gpt-oss:120b`.
- **Meta:** Graph API `v26.0`. Replies to username users (no phone number) go in the `recipient` field with the BSUID.
- **WAHA:** runs the GOWS engine (`devlikeapro/waha:gows-2026.9.1`).
  - Incoming messages carry no normalized mentions field. Mentions are read from the raw message data and from `@<digits>` in the text, and a reply quoting the bot counts as a mention.
  - Webhooks are signed with HMAC-SHA512.
- **Permission refinements** (section 6): groups are decided by the group; customers in groups get `read` tabs only; a hidden-phone customer can type a number to complete an order.
- **Group intro on join** (section 7).
- **Sheets:** appends use `RAW` input, so text sent from chat can never run as a formula.
