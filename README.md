# WhatsApp Assistant Engine

A WhatsApp AI assistant for one business at a time:
- **Customer 1:1 chats** run on the business's official number (Meta Cloud API).
- **Group @mentions** run on a purchased number linked through WAHA.
- **Answers** come from the business's Google Sheet. Customers' new rows are added only after they reply YES;
  staff rows are saved at once.
- **Voice notes** are transcribed.

Design: `docs/superpowers/specs/2026-09-23-whatsapp-engine-design.md`.

> **Risk:** WAHA drives WhatsApp Web on a normal account. That breaks WhatsApp's Terms of Service, and the purchased number can be banned without warning. Keep the group bot on its own number, never the client's main number. Sell it as a done-for-you add-on with the risk written into the agreement.

## Local development

```bash
uv sync
uv run pytest
uv run ruff check .
```

Run against real services with `uv run --env-file .env uvicorn app.main:create_app --factory --port 8000`. It needs
`.env`, `clients.yaml` and the Google key in `secrets/`. Run a single worker (the default): the per-chat locks and
the SQLite connection live in one process.

## One-time setup for a pilot client

### 1. Google Sheet
1. In Google Cloud, create a project, enable the **Google Sheets API**, and create a **service account**. Download its JSON key to `secrets/google-service-account.json`.
2. Share the client's Sheet with the service account's email as **Editor**.
3. Give the Sheet these tabs. Header names in row 1 must be unique:
   - `Knowledge`: `Question | Answer`. It is read into every prompt, so keep it short.
   - `Handoffs`: `Time | Name | Phone | Chat | Question | Reason`.
   - The client's own tabs from `clients.yaml`, e.g. `Prices`; `Orders` with a `Phone` column; `Expenses` with `Date | Item | Amount | Category`.
   - The bot writes dates as `2026-06-30`. Dates typed in by hand must match the client's `date_format`, or totals will report those rows as unreadable.
4. Copy `clients.example.yaml` to `clients.yaml` and fill in `sheet_id`, the tabs and the staff numbers
   (with the country code).

### 2. Meta (official number, customer 1:1)
1. In the **client's** Meta Business portfolio, create an app with the WhatsApp product and add their phone number. It must not be on the WhatsApp app at the same time.
2. Create a system user token with `whatsapp_business_messaging` and `whatsapp_business_management`. Put it in `META_ACCESS_TOKEN`. Put the app secret in `META_APP_SECRET`, and the phone number ID in `clients.yaml` as `meta_phone_number_id`.
3. Set the webhook to `https://$DOMAIN/webhooks/meta` with your `META_VERIFY_TOKEN`, and subscribe to the `messages` field.
4. **Add a payment method to the client's WhatsApp account.** From 2026-10-01, every bot reply after 1,000 free per number per month is a paid service message. Without a payment method, Meta stops delivering replies.

### 3. Deploy (one VPS)
1. Point an A record for `DOMAIN` at the VPS.
2. Copy `.env`, `clients.yaml` and `secrets/` onto the VPS.
3. Run `docker compose up -d --build`. Caddy fetches the HTTPS certificate on its own.
   A restart drops messages that were accepted but not yet processed (there is no queue in v1),
   so deploy during quiet hours.
4. Check `https://$DOMAIN/health`. It returns 503 until the WAHA session is linked.

### 4. WAHA (purchased number, groups)
1. Put the purchased SIM in a phone and install WhatsApp. Set the About text to "AI assistant for <business>".
2. Open a tunnel with `ssh -L 3000:127.0.0.1:3000 you@vps`. Export `WAHA_API_KEY` and `WAHA_WEBHOOK_SECRET` in
   your shell first (the same values as in `.env`). Then create the session:
   ```bash
   curl -X POST http://localhost:3000/api/sessions -H "X-Api-Key: $WAHA_API_KEY" -H "Content-Type: application/json" \
     -d '{"name":"sweetbakes","start":true,"config":{"webhooks":[{"url":"http://engine:8000/webhooks/waha",
          "events":["message","group.v2.join"],"hmac":{"key":"'"$WAHA_WEBHOOK_SECRET"'"}}]}}'
   ```
3. Open `http://localhost:3000/dashboard` and scan the QR code with the purchased phone (Linked devices).
4. **Keep that phone online at least every 14 days.** Otherwise WhatsApp logs the bot out.
5. Add the number to the client's groups. The bot introduces itself on join. List group ids with `GET /api/sweetbakes/groups`. Put the staff group ids in `staff_chats` and `staff_alert_chat`, then run `docker compose restart engine`.

### 5. Monitoring
Point a free uptime monitor (e.g. UptimeRobot) at `https://$DOMAIN/health`. It turns red if the database isn't writable or the WAHA session isn't `WORKING`.

## If the purchased number is banned
1. Get a new SIM and install WhatsApp on it.
2. Log out the old WAHA session (`POST /api/sessions/sweetbakes/logout`), start it again (`POST /api/sessions/sweetbakes/start`) and scan the new QR.
3. Add the new number to the groups.
4. The new number won't re-introduce itself in groups where the bot already spoke (history survives the swap),
   so post the intro there once by hand: "Hi, I'm <bot_name>, <business>'s AI assistant. I read messages here
   so I can answer when you @mention me."

Group ids don't change and history lives in SQLite, so nothing is lost.

## Choosing the model
Play the scripted chats against each candidate. This uses real API credit, a few cents per run:
```bash
uv run --env-file .env python -m evals.run --model gpt-6-luna
uv run --env-file .env python -m evals.run --base-url https://generativelanguage.googleapis.com/v1beta/openai/ --model gemini-3.5-flash-lite --api-key $GEMINI_KEY
uv run --env-file .env python -m evals.run --base-url https://ollama.com/v1 --model gpt-oss:120b --api-key $OLLAMA_KEY
```
Set `LLM_MODEL` to the cheapest one that passes every case. Reports land in `evals/reports/`.

## Backups
The engine writes `data/backups/assistant-YYYYMMDD.db` daily and keeps 7. Copy them off the server, e.g. with `rclone`, if the client needs more than that.
