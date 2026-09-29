# WhatsApp Assistant Engine — Setup Guide

This is a beginner walkthrough for setting up the WhatsApp Assistant Engine for a pilot client, written for
someone who has never used a VPS, SSH, Docker, DNS, Google Cloud or Meta's developer tools before. It expands
every step in the README's "One-time setup for a pilot client" section into plain-language instructions. If
you want the short, technical version once you know your way around, read `README.md`. If you want the full
technical design, read `docs/superpowers/specs/2026-09-23-whatsapp-engine-design.md`.

The examples throughout use a pretend client: **Sweet Bakes**, a home bakery in Lahore, Pakistan, with a bot
named **Sara**. Replace those names, `+92` numbers and `Asia/Karachi` timezone with your real client's details.

**How to read this guide:**
- Every command is in its own grey box, labelled either **PowerShell, on your laptop** (your Windows machine)
  or **bash, on the server** (typed after you've connected to the VPS over SSH). Don't mix them up — the same
  word can mean different things in each.
- `<angle brackets>` mark a placeholder you replace with your own value.
- A "You should see:" line after a step tells you how to know it worked.
- `> **Warning:**` callouts mark things that can break the bot or cost money if you skip them.

## Contents

1. [What you're building](#1-what-youre-building)
2. [Before you start: checklist](#2-before-you-start-checklist)
3. [Part A: the Google Sheet](#3-part-a-the-google-sheet)
4. [Part B: clients.yaml, field by field](#4-part-b-clientsyaml-field-by-field)
5. [Part C: Meta (official number)](#5-part-c-meta-official-number)
6. [Part D: the AI keys](#6-part-d-the-ai-keys)
7. [Part E: the server](#7-part-e-the-server)
8. [Part F: connect Meta's webhook](#8-part-f-connect-metas-webhook)
9. [Part G: the group number (WAHA)](#9-part-g-the-group-number-waha)
10. [Part H: monitoring and backups](#10-part-h-monitoring-and-backups)
11. [Part I: test everything](#11-part-i-test-everything)
12. [Part J: choosing the AI model](#12-part-j-choosing-the-ai-model)
13. [Part K: the dashboard](#13-part-k-the-dashboard)
14. [Day-to-day tasks](#14-day-to-day-tasks)
15. [Troubleshooting](#15-troubleshooting)
16. [Glossary](#16-glossary)

## 1. What You're Building

Five parts work together for one client:

- **The client's official WhatsApp number** (Meta Cloud API). This is the number their customers already know.
  It handles 1:1 chats only. Meta charges for this: from 2026-10-01, every bot reply is a paid message once a
  number has used its 1,000 free replies for the month. The client needs a payment method on file, or Meta
  simply stops delivering replies.
- **A second, purchased number** (run through a tool called WAHA). This one lives in the client's WhatsApp
  *groups* and answers when someone @mentions it. WAHA itself is free software — since version 2026.6.1, every
  feature that used to be paid (including unlimited connections) is free. You still need to buy a prepaid SIM
  and a spare phone to hold it.
- **A Google Sheet.** This is the client's actual data: prices, knowledge, orders, expenses. You and the
  client can edit it directly at any time; the bot reads and writes to it.
- **A server.** One small rented computer that runs the assistant software (the "engine"), WAHA, and a web
  server (Caddy) that gives it a secure `https://` address. Renting a VPS (virtual private server) typically
  costs a few dollars a month. A domain name for it typically costs about $10 a year.
- **An AI provider.** The engine sends each conversation to an AI model to write replies. The built-in default,
  `gpt-6-luna`, costs $0.10 / $0.50 per 1M tokens — in practice a single WhatsApp reply costs a small fraction
  of a cent (running all 15 of the project's test conversations costs only a few cents in total).

Everything below walks through getting all five pieces talking to each other for one client.

## 2. Before You Start: Checklist

Gather these before you begin:

- [ ] A Google account (free) — for the Sheet and a small Google Cloud project.
- [ ] The **client's** Meta Business portfolio, with you added as an admin. (This is Meta's account system for
  businesses — see the [glossary](#15-glossary). You need the client to grant you access, or to do the Meta
  steps together with them.)
- [ ] An account with a VPS provider (a company that rents out small servers by the month — any provider that
  offers an Ubuntu server works, e.g. DigitalOcean, Hetzner, or Linode/Akamai).
- [ ] A domain name, from any registrar (e.g. `assistant-sweetbakes.com`).
- [ ] An OpenAI API key with paid credit on it. You need this even if you plan to use Gemini or Ollama for
  chat, because voice notes are transcribed through an OpenAI-style endpoint, and Gemini's OpenAI-compatible
  layer has no transcription endpoint of its own.
- [ ] A spare phone and a prepaid SIM card, for the purchased "group" number.
- [ ] Your Windows laptop with PowerShell. Modern Windows already includes `ssh` and `scp` (used below), so
  there's nothing extra to install for those.

## 3. Part A: The Google Sheet

### Get the project folder onto your laptop

1. Open the GitHub page: `https://github.com/AsadKhalil/Whatsapp-assistant`. If you can see the code without
   logging in, it's public; if it asks you to sign in, it's private and you'll need access from the owner.
2. Click the green **Code** button and choose **Download ZIP** (simplest option — no extra software needed).
   Extract it somewhere easy to find, e.g. `C:\Users\<you>\whatsapp-assistant`.
   - If you're comfortable with Git and have it installed, `git clone https://github.com/AsadKhalil/Whatsapp-assistant.git`
     works too.
   - You should see: a folder containing files like `README.md`, `.env.example` and `clients.example.yaml`.

Everything below that says "in your project folder" means this folder.

### Create a Google Cloud project and a service account key

A **service account** is a Google account made for a program instead of a person — it's how the engine is
allowed to read and write the client's Sheet without ever knowing the client's Google password.

3. Go to `https://console.cloud.google.com` and sign in with your Google account.
4. Create a new project (top bar → **New Project**). Name it anything, e.g. `sweetbakes-assistant`.
   *(Google moves these menus around occasionally — look for "New Project" near the top of the console, or
   under a project-picker dropdown.)*
5. With that project selected, search for **Google Sheets API** in the console's search bar and click
   **Enable**.
   - You should see: a page confirming the API is enabled for your project.
6. Go to **IAM & Admin → Service Accounts** and create one (any name, e.g. `assistant-bot`). No special role
   is needed — access is granted by sharing the Sheet directly, in the next section.
7. Open the new service account, go to its **Keys** tab, and choose **Add Key → Create new key → JSON**. This
   downloads a `.json` file to your laptop.
8. Move and rename that file to `secrets\google-service-account.json` inside your project folder (create the
   `secrets` folder if it doesn't exist).
   - You should see: `secrets\google-service-account.json` inside your project folder.
9. Note the service account's email address — it looks like `assistant-bot@sweetbakes-assistant.iam.gserviceaccount.com`.
   You'll need it in a moment. It's inside the JSON file (the `client_email` field) and on the service account's page.

> **Warning:** Never commit this JSON file to git or share it outside this project — anyone who has it can
> read and write the client's Sheet.

### Create the Sheet and its tabs

10. Go to `https://sheets.google.com` and create a new, blank spreadsheet for this client.
11. Create these tabs (right-click the tab bar → rename, or the `+` button to add a tab). Row 1 of each tab is
    the header row — the column names — and every header name in a tab must be unique:
    - **Knowledge** — headers `Question | Answer`. This whole tab is read into every AI reply, so keep it
      short and only put things worth the AI knowing by heart.
    - **Handoffs** — headers `Time | Name | Phone | Chat | Question | Reason`. The engine writes to this
      itself when it can't help someone; you don't type into it.
    - Your client's own tabs, from what you plan to put in `clients.yaml` (Part B). For example:
      - **Prices** — your own columns, e.g. `Item | Price`.
      - **Orders** — needs at least a `Name` and a `Phone` column (the engine fills these in automatically),
        plus whatever else you want to track, e.g. `Item | Date`.
      - **Expenses** — headers `Date | Item | Amount | Category`.
12. Whichever tabs staff will hand-type dates into: the bot itself always writes dates as `2026-06-30`
    (YYYY-MM-DD), but a date someone types in by hand must match the client's `date_format` (Part B) — e.g.
    `30/06/2026` for a client using `%d/%m/%Y` — or totals will report that row as unreadable.

### Share the Sheet and note the sheet_id

13. Click **Share** (top right of the Sheet) and add the service account's email from step 9, with **Editor**
    access. Uncheck "notify people" — it's not a real inbox.
    - You should see: the service account listed under people with access.
14. Copy the Sheet's ID from its URL. It's the long string of letters/numbers between `/d/` and `/edit`:
    `https://docs.google.com/spreadsheets/d/`**`1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789`**`/edit`. You'll paste
    this into `clients.yaml` as `sheet_id` next.

## 4. Part B: clients.yaml, Field by Field

`clients.yaml` holds the settings for your first client. On its very first start the engine copies them into its database; after that you change settings in the dashboard (Part K), and later edits to `clients.yaml` are ignored. It's listed in
`.gitignore` on purpose (it can contain real phone numbers), so you create your own copy.

1. In your project folder, copy `clients.example.yaml` to `clients.yaml`.
   **PowerShell, on your laptop:**
   ```powershell
   Copy-Item clients.example.yaml clients.yaml
   ```
2. Open `clients.yaml` in Notepad (`notepad clients.yaml`) and edit it. Here's the full example, for Sweet
   Bakes, with every field explained below:

   ```yaml
   clients:
     sweetbakes:
       business: Sweet Bakes
       bot_name: Sara
       timezone: Asia/Karachi
       date_format: "%d/%m/%Y"
       instructions: |
         We are a home bakery in Lahore. Cakes need 24 hours notice.
         Delivery is free above Rs 3000. Be warm and brief.
       sheet_id: 1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789
       knowledge_tab: Knowledge
       handoff_tab: Handoffs
       meta_phone_number_id: "106540352242922"
       waha_session: sweetbakes
       staff_chats: ["120363041234567890@g.us"]
       staff_numbers: ["+92 300 1111111"]
       staff_alert_chat: "120363041234567890@g.us"
       retention_days: 90
       tabs:
         Prices: {customer: [read]}
         Orders:
           customer: [own, append]
           owner_column: Phone
           fill: {Name: name, Phone: phone}
         Expenses: {}
         Handoffs: {}
   ```

   Field by field:
   - **`sweetbakes`** (the top key): a short internal id for this client — 3–32 lowercase letters, digits or
     dashes (for example `sweetbakes`). Used internally only; customers never see it.
   - **`business`**: the business's name, as the AI will say it to customers.
   - **`bot_name`**: what the bot calls itself, e.g. "Sara".
   - **`timezone`**: a real IANA timezone name (e.g. `Asia/Karachi`, `America/New_York`) — an invalid name
     stops the engine from starting. Used so "today" and "this month" totals, and the current time shown to
     the AI, are correct for the client's location.
   - **`date_format`**: how dates look when a *person* types them into the Sheet by hand, as a Python date
     pattern (`%d/%m/%Y` = day/month/year, e.g. `30/06/2026`). The bot's own writes are always `YYYY-MM-DD`
     regardless of this setting — this only affects rows people type in themselves.
   - **`instructions`**: free-text business knowledge, written as if you're briefing a new employee — hours,
     policies, tone. Goes straight into the AI's instructions.
   - **`sheet_id`**: from Part A, step 14.
   - **`knowledge_tab`** / **`handoff_tab`**: the tab names from Part A (defaults are already `Knowledge` and
     `Handoffs` if you leave these out).
   - **`meta_phone_number_id`**: from Part C — the internal ID Meta assigns the number, not the phone number
     itself. Keep the quote marks; it's a long number and YAML can otherwise mangle it.
   - **`waha_session`**: a short id you invent for this client's WAHA connection — 3–32 lowercase letters,
     digits or dashes (for example `sweetbakes`). You'll create a WAHA session with this *exact* name in Part G —
     they must match.
   - **`staff_chats`**: WhatsApp group ids (see [glossary](#15-glossary)) where *everyone* is treated as staff.
     You'll get these ids in Part G, once the group number exists.
   - **`staff_numbers`**: full phone numbers with country code, exactly as WhatsApp reports them. Staff are
     recognized only by the full number — matched exactly, not just the last digits.
   - **`staff_alert_chat`**: the group id (usually one of `staff_chats`) where "someone needs a human" alerts
     get posted.
   - **`retention_days`**: how many days of chat history the engine keeps before deleting it automatically
     (default 90 if omitted).
   - **`tabs`**: which Sheet tabs the bot can use in chat, and who may do what on each:
     - `customer: [read]` — customers can look up and total rows, but not add any.
     - `customer: [own, append]` — customers can see and total *only their own* rows (matched by
       `owner_column`, e.g. `Phone`), and propose new rows.
     - `customer: [append]` — customers can propose new rows but not read existing ones (e.g. a "Leads" tab).
     - No `customer` key at all (like `Expenses: {}` above) — customers can't touch this tab; it's staff-only.
     - `owner_column`: required whenever `own` is used — the column that identifies whose row it is.
     - `fill`: columns the engine fills in automatically from the customer's WhatsApp profile when they
       propose a row — only `name` or `phone` are valid sources.
     - **Staff can read and add on every tab listed here**, regardless of its `customer` setting. A tab left
       out of `tabs:` entirely can't be used from chat at all, by anyone, even staff.

   **Who counts as staff:** a phone number in `staff_numbers` is staff only when messaging 1:1 (either
   number) — not inside a group. Inside a group, only the group's own membership in `staff_chats` decides;
   someone in `staff_numbers` who posts in a customer group is still treated as a customer there, so private
   rows never leak into a customer group. Customers in any group (staff or otherwise) only ever get `read`
   access — proposing rows and seeing "my own" rows both require a private 1:1 chat.

   **Staff vs. customer saves:** a staff append (e.g. logging an expense) is saved to the Sheet immediately,
   with a reply showing exactly what was saved. A customer append is only a *proposal* until they reply YES.

## 5. Part C: Meta (Official Number)

This part happens **in the client's own Meta Business portfolio** — not yours. If you don't have access yet,
ask the client to add you as an admin first (checklist, part 2).

> Meta renames and moves these menus from time to time. If a label below doesn't match what you see, look for
> a menu item with a similar name — the *goal* of each step is what matters.

1. In the client's Meta Business portfolio, create a new app and add the **WhatsApp** product to it.
2. Add the client's real business phone number to the app. **It cannot stay active in the regular WhatsApp
   app at the same time** — moving it to the Cloud API takes it off the phone.
   > **Warning:** if the client is currently using that number in the normal WhatsApp or WhatsApp Business
   > app, they will lose access to it there once it's added here. Make sure they're ready for that.
3. Find the **Phone number ID** for the number you just added (shown on the app's WhatsApp setup page, next
   to the number — it's a long internal ID, not the phone number itself). Copy it into `clients.yaml` as
   `meta_phone_number_id`.
4. Create a **system user** with admin access to the app, and generate a token for it with the
   `whatsapp_business_messaging` and `whatsapp_business_management` permissions checked. Copy that token into
   `.env` as `META_ACCESS_TOKEN` (Part E).
   > **Warning:** this token is shown only once when generated — copy it somewhere safe immediately.
5. Find the page that shows your app's secret (usually under the app's Settings → Basic, next to "App
   Secret" — click "Show"). Copy it into `.env` as `META_APP_SECRET`.
6. Invent a **verify token** — any random string you make up yourself (it just proves the webhook request in
   Part F really came from you setting it up). Put the same value in `.env` as `META_VERIFY_TOKEN`. You can
   generate a random one on the server later with `openssl rand -hex 32` if you'd rather not make one up.
7. Add a payment method to the client's WhatsApp account (in the Business Settings for this WhatsApp Business
   Account).
   > **Warning:** from 2026-10-01, every bot reply after the first 1,000 per number per month is a paid
   > message. Without a payment method on file, Meta stops delivering replies once the free allowance runs out.

The webhook itself (the URL Meta sends messages to) is set up in [Part F](#8-part-f-connect-metas-webhook),
after the server is running — you need a live `https://` address first.

**Trying things out first:** every new Meta app also comes with a free test phone number, usable with a
short list of verified recipient numbers and no payment method required. It's a safe way to try the setup
end-to-end before touching the client's real number.

## 6. Part D: The AI Keys

These go in `.env` (created properly in Part E). From `.env.example`:

- **`LLM_API_KEY`**: your AI provider's API key (for chat replies).
- **`LLM_MODEL`**: which model to use. The built-in options: `gpt-6-luna` | `gemini-3.5-flash-lite` |
  `gemini-3.8-flash` | `gpt-oss:120b`. Default: `gpt-6-luna`.
- **`LLM_BASE_URL`**: which provider. Leave empty for OpenAI. For Gemini:
  `https://generativelanguage.googleapis.com/v1beta/openai/`. For Ollama Cloud: `https://ollama.com/v1`.
- **`LLM_REASONING_EFFORT`**: **leave this empty.** The engine sets it automatically (`"none"` for OpenAI,
  since OpenAI only allows tool use with reasoning off; nothing at all for other providers).
- **`STT_BASE_URL`** / **`STT_API_KEY`** / **`STT_MODEL`**: speech-to-text, for voice notes. Leave
  `STT_BASE_URL` empty for OpenAI (the default, `gpt-transcribe`). Leave `STT_API_KEY` empty to reuse
  `LLM_API_KEY`.

> **Why you need an OpenAI key even on Gemini or Ollama:** voice notes are transcribed through an
> OpenAI-style `/audio/transcriptions` endpoint. Gemini's OpenAI-compatibility layer doesn't have one, so
> transcription always needs a real OpenAI key in `STT_API_KEY` (or in `LLM_API_KEY`, which it falls back to)
> — even when chat replies run on Gemini or Ollama.

## 7. Part E: The Server

### Rent the server and point your domain at it

1. Rent an Ubuntu VPS. Pick at least **2 GB of RAM** — WAHA runs a full WhatsApp Web client in the
   background, which needs more memory than the engine itself. Your provider will give you the server's IP
   address and a login (often `root`).
2. At your domain registrar, add an **A record** for your domain (or a subdomain like
   `assistant.sweetbakes.com`) pointing at the server's IP address.
   - You should see: after a few minutes (sometimes longer), the domain resolves to your server's IP.
     Check with, in PowerShell:
     ```powershell
     nslookup assistant.sweetbakes.com
     ```
     You should see the server's IP address in the answer.

### Connect and install Docker

3. Connect to the server from your laptop.
   **PowerShell, on your laptop:**
   ```powershell
   ssh root@your.server.ip
   ```
   You should see: a Linux command prompt — you're now typing directly on the server.
4. Install Docker with the official convenience script.
   **bash, on the server:**
   ```bash
   curl -fsSL https://get.docker.com | sh
   ```
   If you're not logged in as `root`, put `sudo` in front: `curl -fsSL https://get.docker.com | sudo sh`.
   - You should see: Docker installing, ending with a message that it's done.
   ```bash
   docker compose version
   ```
   - You should see: a version number printed (not "command not found").

### Get the code onto the server

5. Install git and clone the repository.
   **bash, on the server:**
   ```bash
   sudo apt-get update && sudo apt-get install -y git
   ```
   - **If the repo is public:**
     ```bash
     git clone https://github.com/AsadKhalil/Whatsapp-assistant.git
     ```
   - **If the repo is private:** either install GitHub's `gh` command-line tool and run `gh auth login`
     (choose HTTPS, log in through the browser link it gives you), then `gh repo clone AsadKhalil/Whatsapp-assistant`;
     or create a fine-grained personal access token on GitHub (Settings → Developer settings) scoped to just
     this repo with read-only Contents access, then:
     ```bash
     git clone https://<your-token>@github.com/AsadKhalil/Whatsapp-assistant.git
     ```
   - You should see (after `ls Whatsapp-assistant`): an `app` folder, `docker-compose.yml` and `README.md`.
   ```bash
   cd Whatsapp-assistant
   ```

### Create .env

6. Copy the template and fill it in.
   **bash, on the server:**
   ```bash
   cp .env.example .env
   nano .env
   ```
   In `nano`: move around with the arrow keys, type to edit, **Ctrl+O then Enter** to save, **Ctrl+X** to
   exit. Fill in every value:
   - `LOG_HASH_KEY`, `SECRET_KEY`, `WAHA_API_KEY`, `WAHA_WEBHOOK_SECRET`, `WAHA_DASHBOARD_PASSWORD`: random secrets. Open a
     second terminal or just run this first and copy each result in:
     ```bash
     openssl rand -hex 32
     ```
   - `META_APP_SECRET`, `META_VERIFY_TOKEN`, `META_ACCESS_TOKEN`: from Part C.
   - `LLM_*` / `STT_*`: from Part D.
   - `DOMAIN`: the domain you pointed at this server, e.g. `assistant.sweetbakes.com`.
   - Everything else (`DB_PATH`, `BACKUP_DIR`, `CLIENTS_FILE`, `GOOGLE_SERVICE_ACCOUNT_FILE`, `WAHA_URL`,
     `WAHA_DASHBOARD_USERNAME`, `META_GRAPH_VERSION`): leave the example defaults as they are.

   > **Warning:** if `LOG_HASH_KEY` is left blank, the engine starts anyway but logs a warning that hashed
   > chat ids in the logs can be reversed — always set it.

### Upload clients.yaml and the Google key

7. From your **laptop** (not the server), upload the two files you prepared in Parts A and B. Open a new
   PowerShell window (keep it separate from the SSH session) in your project folder:
   **PowerShell, on your laptop:**
   ```powershell
   scp clients.yaml root@your.server.ip:~/Whatsapp-assistant/clients.yaml
   scp secrets\google-service-account.json root@your.server.ip:~/Whatsapp-assistant/secrets/google-service-account.json
   ```
   (`scp` may need the destination `secrets` folder to already exist — if it errors, first run
   `ssh root@your.server.ip "mkdir -p ~/Whatsapp-assistant/secrets"` and try again.)
   - You should see: both files listed if you run `ls clients.yaml secrets/` back on the server.

### Launch it

8. Back in your SSH session on the server:
   **bash, on the server:**
   ```bash
   docker compose up -d --build
   ```
   This builds and starts three containers: the engine, WAHA, and Caddy. Caddy fetches an HTTPS certificate
   for your domain on its own — no extra step needed.
9. Watch it start up:
   ```bash
   docker compose logs -f engine
   ```
   Press **Ctrl+C** to stop watching (this doesn't stop the container).
10. In a browser, visit `https://<your-domain>/health`.
    - You should see: a `503` response with something like `{"ok": false, "waha": {"sweetbakes": "..."}}`.
      **This is expected right now** — it turns `ok: true` only once the WAHA session is linked, in Part G.

### Firewall

11. Only three ports need to be open to the internet: **22** (SSH), **80** and **443** (Caddy/HTTPS). WAHA's
    port (3000) is deliberately *not* public — Docker Compose binds it to the server's own loopback address,
    reachable only through an SSH tunnel (Part G), never from the open internet.
    **bash, on the server:**
    ```bash
    sudo ufw allow 22
    sudo ufw allow 80
    sudo ufw allow 443
    sudo ufw enable
    ```
    If your VPS provider also has its own separate cloud firewall setting, open the same three ports there too.

## 8. Part F: Connect Meta's Webhook

> **With the dashboard (Part K):** every business also has its own webhook address, shown with its verify token on the business's **Official number** page. This first business can keep the address below: it keeps working for the business whose Meta keys are in `.env`. Businesses you add later must use their own address.

Now that the server is live with a real `https://` address, go back to the client's Meta app (Part C) and
point it at your server.

1. In the app's WhatsApp configuration page, set:
   - **Callback URL**: `https://<your-domain>/webhooks/meta`
   - **Verify token**: the `META_VERIFY_TOKEN` value you put in `.env`
2. Click to verify/save it.
   - You should see: Meta showing the webhook as verified (a checkmark or "Verified" status). If it fails,
     double check the domain resolves, `https://<your-domain>/health` loads at all, and the verify token
     matches `.env` exactly.
3. Subscribe to the **`messages`** field (a checkbox next to that field on the same page).
4. Confirm it works: from a personal phone, send any message to the client's official WhatsApp number.
   - You should see: a reply starting with "Hi, I'm Sara, Sweet Bakes's AI assistant." (using your bot's real
     name and business).

## 9. Part G: The Group Number (WAHA)

> **Warning — read this first:** WAHA connects a WhatsApp number the same way WhatsApp Web does, on a normal
> consumer account. This is not how Meta intends WhatsApp to be automated, and it breaks WhatsApp's Terms of
> Service — the purchased number can be suspended without warning. **Only ever use this on the purchased
> number, never the client's real business number.** Sell this feature as a done-for-you add-on, with the
> risk written into your agreement with the client.

### Set up the phone

1. Put the prepaid SIM in the spare phone and install WhatsApp on it as normal.
2. Set its About text to something like "AI assistant for Sweet Bakes".
3. Save this number as a contact on the phones of anyone who'll @mention it (staff, at least), under the
   bot's name (e.g. "Sara") — this makes @mentioning it show a friendly name instead of a raw number, though
   either works.

### Link WAHA to the phone

> **Your first business's number** is linked here, over the SSH tunnel, with the session name from `clients.yaml`. For every later business, add and link its number in the dashboard instead (Part K, **Numbers → Add a number**): no tunnel needed.

4. Open an SSH tunnel from your laptop — this makes the server's WAHA dashboard reachable from your laptop's
   browser, without exposing it to the internet. Keep this window open for the rest of this section.
   **PowerShell, on your laptop:**
   ```powershell
   ssh -L 3000:127.0.0.1:3000 root@your.server.ip
   ```
5. In that same SSH session (you're now on the server, in your home directory), move into the project folder,
   load the WAHA secrets from `.env`, and create the session. The session **name must exactly match
   `waha_session`** in `clients.yaml` (`sweetbakes` in the example).
   **bash, on the server (same SSH window):**
   ```bash
   cd Whatsapp-assistant
   cat .env | grep WAHA_
   export WAHA_API_KEY=<paste the WAHA_API_KEY value from above>
   export WAHA_WEBHOOK_SECRET=<paste the WAHA_WEBHOOK_SECRET value from above>
   curl -X POST http://localhost:3000/api/sessions -H "X-Api-Key: $WAHA_API_KEY" -H "Content-Type: application/json" \
     -d '{"name":"sweetbakes","start":true,"config":{"webhooks":[{"url":"http://engine:8000/webhooks/waha",
          "events":["message","group.v2.join"],"hmac":{"key":"'"$WAHA_WEBHOOK_SECRET"'"}}]}}'
   ```
   - You should see: a JSON response describing the new session.
6. On your **laptop** (keep the SSH/tunnel window open), open a browser to `http://localhost:3000/dashboard`.
   Log in with `WAHA_DASHBOARD_USERNAME` / `WAHA_DASHBOARD_PASSWORD` from `.env`.
7. On the spare phone: WhatsApp → **Settings → Linked Devices → Link a Device**, and scan the QR code shown
   on the dashboard.
   - You should see: the session's status change to "WORKING" on the dashboard.

> **Warning:** keep that phone charged and online (connected to the internet) at least once every 14 days.
> If it stays offline longer than that, WhatsApp logs the linked device out and you'll need to relink it.

### Add the bot to groups

8. On the spare phone, add the number to each of the client's WhatsApp groups, the normal way (add
   participant). The bot posts its AI-disclosure intro automatically the moment it's added to a group.
9. Tell the bot which group is the staff group, in the dashboard. If you haven't made your admin login yet, do Part K, "Create your admin login", now. Then open `https://<your-domain>/admin` → your business → **Staff & groups**, tick **Staff group** next to the staff group, pick the same group under **Gets "needs a person" alerts**, and press **Save**.
   - You should see: "Saved." The bot uses it from the next message; no restart needed.
10. Check `https://<your-domain>/health` again.
    - You should see: `{"ok": true, ...}` now that the WAHA session is `WORKING`.

### If the purchased number gets banned

> **With the dashboard (Part K):** step 2 is easier: open **Numbers** → the number → **Log out**, then **Relink**, and scan the new QR code with the new phone. No SSH tunnel needed.

This is the real risk described in the warning above. If it happens:

1. Get a new SIM and install WhatsApp on it.
2. Reconnect the same way as in "Link WAHA to the phone" above: open the SSH tunnel from your laptop
   (`ssh -L 3000:127.0.0.1:3000 root@your.server.ip`), then on the server, `cd Whatsapp-assistant`, load
   `WAHA_API_KEY` from `.env` again (`cat .env | grep WAHA_` then `export WAHA_API_KEY=...`). Then log out the
   old session and start fresh:
   ```bash
   curl -X POST http://localhost:3000/api/sessions/sweetbakes/logout -H "X-Api-Key: $WAHA_API_KEY"
   curl -X POST http://localhost:3000/api/sessions/sweetbakes/start -H "X-Api-Key: $WAHA_API_KEY"
   ```
   Then scan the new QR code on the dashboard, as in step 7 above.
3. Add the new number to the groups again.
4. The new number won't automatically re-introduce itself in groups where the bot already spoke before (the
   chat history survives the swap), so post the intro there yourself, once, by hand:
   > Hi, I'm Sara, Sweet Bakes's AI assistant. I read messages here so I can answer when you @mention me.

Group ids don't change and all history lives in the server's database, so nothing is lost by swapping numbers.

## 10. Part H: Monitoring and Backups

1. Point a free uptime monitor (e.g. UptimeRobot) at `https://<your-domain>/health`. It'll alert you if the
   database stops being writable or the WAHA session drops out of `WORKING`.
2. The engine backs itself up automatically every day, to `data/backups/assistant-YYYYMMDD.db` on the server
   (inside your project folder), keeping the last 7 days.
3. To copy backups to your laptop, from PowerShell:
   **PowerShell, on your laptop:**
   ```powershell
   scp "root@your.server.ip:~/Whatsapp-assistant/data/backups/*.db" C:\Users\<you>\Backups\
   ```

## 11. Part I: Test Everything

Work through this list after Parts E, F and G are all done. "You should see" tells you what a pass looks
like.

1. **Intro on the first reply only.** From a customer number that has never messaged the bot before, send
   the official number a message, e.g. "Hi". You should see: a reply starting with "Hi, I'm Sara, Sweet
   Bakes's AI assistant." Send a second message. You should see: a normal reply, **without** repeating the
   intro.
2. **Price question, from Prices.** Send: a question matching a row in your Prices tab, e.g. "How much is the
   chocolate cake?" You should see: a reply stating the price from that tab.
3. **Order flow.** Send: "I want to order 2 cakes." You should see: a proposal reply starting "Add to
   Orders:" listing the details, ending "Reply YES to confirm or NO to cancel." Reply: "YES". You should see:
   "✅ Added to Orders." — and a new row in the Orders tab with your name and phone number filled in.
4. **Staff expense, saved instantly.** From a `staff_numbers` phone (1:1), or in the staff group with an
   @mention, send: "spent 1500 on petrol today". You should see: an immediate reply starting "✅ Saved to
   Expenses:" — no YES/NO step.
5. **Staff totals.** Send: "what did we spend this month?" You should see: a reply with a total that matches
   what you get adding up the Expenses tab yourself for this month.
6. **Voice note.** Send a short voice note asking something simple (e.g. a price question). You should see: a
   normal, relevant reply — proof the transcription step is working.
7. **Group: intro on join.** Add the group number to a fresh WhatsApp group. You should see: it posts its
   intro immediately, unprompted.
8. **Group: no reply without a mention.** In that group, send a plain message that doesn't mention or reply
   to the bot, e.g. "what time is it". You should see: no reply at all.
9. **Group: quoted reply on @mention.** In the group, type `@` and pick the bot's contact from the suggestions
   (or reply directly to one of the bot's earlier messages), then ask a question. You should see: a reply
   that quotes your message.
10. **Handoff.** Send: "talk to a person". You should see: an acknowledgement reply (e.g. "I've passed this
    to the team..."), a new row in the Handoffs tab, and an alert message in the staff group.
11. **Log privacy.** On the server, run `docker compose logs engine` and skim the output. You should see:
    short hashed ids and event names — you should **not** see any of the message text you sent, or a full
    phone number, anywhere in the log.

## 12. Part J: Choosing the AI Model

The engine can run on OpenAI, Gemini, or Ollama Cloud. Pick the cheapest one that still answers correctly, by
playing 15 scripted test conversations against each one.

1. Install `uv` (the Python tool used to run everything in this project) on your laptop.
   **PowerShell, on your laptop:**
   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```
   - You should see: a confirmation message. Check it with `uv --version` — you should see a version number.
2. In your project folder on your laptop, install the project's dependencies:
   ```powershell
   uv sync
   ```
3. If you don't already have a `.env` file in this folder on your laptop, create one and add a real OpenAI
   key to it (this step uses a pretend bakery and a pretend Sheet built into the test code, so your real
   `clients.yaml` and Google key aren't needed here):
   ```powershell
   Copy-Item .env.example .env
   notepad .env
   ```
   Paste your OpenAI key next to `LLM_API_KEY`, save, and close.
4. Run the three evaluation commands. **Each of these costs a small amount of real API credit** (a few cents
   total for all three).
   ```powershell
   uv run --env-file .env python -m evals.run --model gpt-6-luna
   ```
   ```powershell
   $env:GEMINI_KEY = "<your Gemini API key>"
   uv run --env-file .env python -m evals.run --base-url https://generativelanguage.googleapis.com/v1beta/openai/ --model gemini-3.5-flash-lite --api-key $env:GEMINI_KEY
   ```
   ```powershell
   $env:OLLAMA_KEY = "<your Ollama Cloud API key>"
   uv run --env-file .env python -m evals.run --base-url https://ollama.com/v1 --model gpt-oss:120b --api-key $env:OLLAMA_KEY
   ```
5. Read the output. Each line is one test case, starting `PASS` or `FAIL`, and the last line reads something
   like `13/15 passed with gpt-6-luna`.
   - You should see: 15 `PASS`/`FAIL` lines per model, and a final score line.
6. Pick the **cheapest** model that scored 15/15. Set it on the **server**, then restart: SSH back in
   (`ssh root@your.server.ip`), move into the project folder, and edit `.env` again:
   **bash, on the server:**
   ```bash
   cd Whatsapp-assistant
   nano .env
   ```
   Set `LLM_MODEL` (and `LLM_BASE_URL` / `LLM_API_KEY` too, if you're not using OpenAI), save and exit, then:
   ```bash
   docker compose up -d
   ```

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
   > **Warning:** keep `SECRET_KEY` safe and don't change it. It encrypts the Meta keys saved in the dashboard; if it changes, you must re-enter every business's Meta keys. Every admin must also reset their two-step login with `docker compose exec engine python -m app.cli admin-link <their email>`.
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

If you ran the engine before the dashboard existed: add `SECRET_KEY` to `.env`, then run `git pull` and `docker compose up -d --build`. On that first start the engine copies `clients.yaml` and the Meta keys from `.env` into the dashboard database, once. After that, change settings only in the dashboard (`clients.yaml` is ignored). The first business keeps working on the old webhook address `https://<your-domain>/webhooks/meta`; switch it to its own address (on its Official number tab) whenever convenient. If the engine refuses to start and names a client id or `waha_session`, fix that name in `clients.yaml` and start it again; nothing is imported until every entry is valid.

## 14. Day-to-Day Tasks

- **Change a price or an answer:** just edit the cell in the Sheet directly. Price/answer values themselves
  show up on the very next question; the Knowledge tab's text and any tab's column names can take up to 5
  minutes to refresh (they're cached briefly to avoid hammering Google's API).
- **Add a staff member or group:** in the dashboard, open the business → **Staff & groups**, add the number or
  tick the group, and press **Save**. The bot uses it from the next message.
- **Add a new tab:** create the tab and its header row in the Sheet, then in the dashboard open the business →
  **Sheet**, tick "the bot uses this tab", choose what customers may do, and press **Save permissions**.
- **Add a new business:** follow Part K, "Add a business".
- **Update to a new version of the code:** on the server, during quiet hours (a restart drops any message
  that was received but not yet answered — there's no queue):
  ```bash
  git pull
  docker compose up -d --build
  ```
- **View logs:** `docker compose logs -f engine` (or `waha`, or `caddy`).
- **Restart:** `docker compose restart engine` (just the engine) or `docker compose restart` (everything).

## 15. Troubleshooting

- **`/health` returns 503.** Either the WAHA session isn't `WORKING` (relink it: in the dashboard, **Numbers** → the
  number → **Relink**; or through the SSH tunnel as in Part G) or the database isn't writable (check the server isn't out of disk space).
- **No reply on the official number.** Check, in order: the webhook shows verified in Meta (Part F); the
  logs (`docker compose logs engine`) for `403` responses on `/webhooks/meta` (means `META_APP_SECRET`
  doesn't match); an expired or revoked `META_ACCESS_TOKEN`; a missing payment method (Part C); and Meta's
  24-hour customer-service window (a reply can only be sent within 24 hours of the customer's last message —
  check the logs for a `send_failed` line).
- **No reply in a group.** The bot only replies when @mentioned or replied to directly — a plain message
  never gets a reply. Also check you haven't hit the loop-breaker limit of 6 bot replies per chat per 10
  minutes.
- **"The sheet couldn't be reached right now."** Usually the Sheet isn't shared with the service account
  email (Part A), or a tab was renamed in the Sheet without updating the business's **Sheet** page in the dashboard.
- **Totals report rows as "unreadable".** Either a date in that tab doesn't match `date_format`, or an
  amount cell has non-numeric text in it that the engine can't parse as a number.
- **Voice notes aren't understood.** Confirm there's a real, working OpenAI key in `STT_API_KEY` (or
  `LLM_API_KEY`, which it falls back to) — Gemini alone can't transcribe. Also check the note isn't over
  1 MB (about 5 minutes); longer notes are refused with a polite message rather than processed.
- **The bot says it's passed the question to the team, when it shouldn't have.** This means the AI model
  either failed to answer or ran out of steps trying — check the Handoffs tab for a new row describing what
  happened.
- **`git push` says "Invalid username or token".** GitHub no longer accepts a plain password over `git push`.
  Run `gh auth login`, or create a personal access token and use it in place of your password.

## 16. Glossary

- **VPS (virtual private server):** a small rented computer, always on, reachable over the internet — this is
  where the engine, WAHA and Caddy run.
- **SSH:** a secure way to open a remote command line on another computer (your server) from your own.
- **SSH tunnel:** forwards a port on your laptop through the SSH connection to a port on the server, so you
  can reach something that isn't otherwise open to the internet — used here to reach WAHA's dashboard.
- **Docker / Docker Compose:** Docker packages a piece of software and everything it needs to run into a
  self-contained "container". Compose starts and manages several containers together (here: `engine`, `waha`,
  `caddy`) from one `docker-compose.yml` file.
- **DNS A record:** the setting at your domain registrar that points a domain name at a server's IP address.
- **HTTPS / Caddy:** HTTPS is the secure, encrypted form of the web (`https://`). Caddy is the web server in
  this stack that automatically obtains a free certificate for your domain and forwards traffic to the engine.
- **Webhook:** a URL that another service (Meta, WAHA) automatically sends a request to the moment something
  happens — here, the moment a new WhatsApp message arrives.
- **API key / token:** a secret string that proves to a service (Meta, WAHA, an AI provider) that a request
  is allowed, instead of logging in with a password each time.
- **Meta Business portfolio:** Meta's account structure for a business, grouping its apps, WhatsApp numbers
  and the people who can manage them.
- **WABA (WhatsApp Business Account):** the record inside Meta's system that owns a business's number(s) on
  the Cloud API.
- **Phone number ID:** the internal id Meta assigns a WhatsApp number once it's added to an app — this, not
  the phone number itself, is what's used in API calls and goes in `meta_phone_number_id`.
- **WAHA:** the open-source tool this project uses to connect a second WhatsApp number the way WhatsApp Web
  does, so it can be present in existing groups (which Meta's official API can't join).
- **Session (WAHA):** one connected WhatsApp login inside WAHA, identified by a name you choose. The
  dashboard's **Numbers** page lists them; each business gets one on its **Group number** page.
- **Dashboard:** the engine's own website at `https://<your-domain>/`, where you manage businesses, numbers
  and logins (Part K). Not the same as WAHA's dashboard, which only opens through the SSH tunnel.
- **QR linking:** connecting a phone number to WAHA by scanning a QR code with WhatsApp's own
  Linked Devices feature — the same mechanism as linking WhatsApp Web.
- **Group id (`…@g.us`):** WAHA's identifier for one WhatsApp group chat.
- **Service account:** a Google account created for a program rather than a person, used here so the engine
  can read and write a client's Sheet without ever holding the client's own Google password.
- **BSUID (business-scoped user id):** the id Meta uses to identify a customer in official-API webhooks; a
  customer's actual phone number may be hidden from the business, but their BSUID is always present.
