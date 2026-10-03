# WhatsApp Assistant Engine — Setup Guide

This is a beginner walkthrough for setting up the WhatsApp Assistant Engine and its web dashboard, written for
someone who has never used a VPS, SSH, Docker, DNS, Google Cloud or Meta's developer tools before. Parts A–J
set up your first client; Part K is the dashboard, where you add every client after that, link their numbers
and give them their own logins. If you want the short, technical version once you know your way around, read
`README.md`. The full technical designs are `docs/superpowers/specs/2026-09-23-whatsapp-engine-design.md` (the
engine) and `docs/superpowers/specs/2026-09-28-dashboard-admin-design.md` (the dashboard).

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

Six parts work together:

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
- **A web dashboard.** Built into the engine, at `https://<your-domain>/`. You (the admin) see every client
  and every number there, add new clients, link purchased numbers by scanning a QR code, and pause a client
  who stops paying. Each client gets their own login to change their bot's settings and read their chats.

Everything below walks through getting all six pieces talking to each other for your first client. After
that, each new client takes a few minutes in the dashboard (Part K).

## 2. Before You Start: Checklist

Gather these before you begin:

- [ ] A Google account (free) — for the Sheet and a small Google Cloud project.
- [ ] The **client's** Meta Business portfolio, with you added as an admin. (This is Meta's account system for
  businesses — see the [glossary](#16-glossary). You need the client to grant you access, or to do the Meta
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
- [ ] An authenticator app on your own phone (Google Authenticator or Microsoft Authenticator, both free). The
  dashboard asks admins for a 6-digit code from it at every login.

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

    > **Tip:** with the dashboard you can skip this step. Add the business with the empty, shared Sheet, and its
    > owner opens **Setup** (Part K, "Guided setup"): it asks about the business and creates these tabs with their
    > headers. Only the empty Sheet and the share (step 13) are needed.
12. Whichever tabs staff will hand-type dates into: the bot itself always writes dates as `2026-06-30`
    (YYYY-MM-DD), but a date someone types in by hand must match the client's `date_format` (Part B) — e.g.
    `30/06/2026` for a client using `%d/%m/%Y` — or totals will report that row as unreadable.

> **Warning:** the whole Knowledge tab goes into every reply the bot writes, to anyone who messages it. Never
> put customer names, phone numbers or other private details in it; keep those in tabs like Orders, where each
> customer only sees their own rows.

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
       staff_numbers: ["+92 300 1111111"]
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

   `clients.example.yaml` also has `staff_chats` and `staff_alert_chat` lines with made-up group ids. Delete
   both: you'll pick the real groups in the dashboard in Part G.

   Field by field:
   - **`sweetbakes`** (the top key): a short internal id for this client — 3–32 lowercase letters, digits or
     dashes (for example `sweetbakes`). Customers never see it, but it appears in this client's dashboard
     addresses and in its own Meta webhook address, so pick it once and keep it.
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
   - **`staff_numbers`**: full phone numbers with country code, exactly as WhatsApp reports them. Staff are
     recognized only by the full number — matched exactly, not just the last digits. You can change them
     later on the dashboard's **Staff & groups** page.
   - **Staff groups and the alert group** (`staff_chats` / `staff_alert_chat`): leave these out. They are the
     WhatsApp groups where *everyone* counts as staff, and the group where "someone needs a human" alerts are
     posted. You tick them in the dashboard in Part G, once the group number is in those groups.
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
     - You can change all of this later on the dashboard's **Sheet** page, which can also show you what a
       customer would see before you save.

   **Who counts as staff:** a staff phone number is staff only when messaging 1:1 (either number) — not
   inside a group. Inside a group, only whether the group itself is ticked as a staff group decides; a staff
   number that posts in a customer group is still treated as a customer there, so private rows never leak into
   a customer group. Customers in any group (staff or otherwise) only ever get `read`
   access — proposing rows and seeing "my own" rows both require a private 1:1 chat.

   **Staff vs. customer saves:** a staff append (e.g. logging an expense) is saved to the Sheet immediately,
   with a reply showing exactly what was saved. A customer append is only a *proposal* until they reply YES.

## 5. Part C: Meta (Official Number)

This part happens **in the client's own Meta Business portfolio** — not yours. If you don't have access yet,
ask the client to add you as an admin first (checklist, part 2).

> Meta renames and moves these menus from time to time. If a label below doesn't match what you see, look for
> a menu item with a similar name — the *goal* of each step is what matters.

> **For clients you add later** (Part K), you get the same three values the same way, but paste them into the
> dashboard's **Official number** page instead of `clients.yaml` and `.env`; the dashboard makes each client's
> verify token for you.

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

   > **Warning:** `SECRET_KEY` locks the Meta keys and two-step logins the dashboard saves, and the engine
   > won't start without it. Save a copy of your whole `.env` somewhere private (a password manager), and
   > never change `SECRET_KEY` afterwards. If it's lost or changed, every client's Meta keys must be pasted in
   > again and every admin must reset their two-step login, and a backup can't be fully restored without it.

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
   - You should see: a line ending `imported 1 business(es) from /config/clients.yaml`. The engine has copied
     `clients.yaml` into its database; this happens only on this very first start.
   - If instead you see an error naming a client id, a `waha_session` or a setting, fix that line in
     `clients.yaml` on your laptop, upload it again (step 7), and run `docker compose restart engine`.
     Nothing is copied until every entry is valid, so it's safe to retry.
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

### Create your dashboard login

12. Create your admin login now: follow **Part K → Create your admin login (once)**, then come back here.
    From Part G on, you'll use the dashboard at `https://<your-domain>/`.

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

### Link the number to the server

On its first start the server copied your client's `waha_session` name (`sweetbakes` in the example) from
`clients.yaml` into the dashboard's list of numbers. Now connect the purchased phone to it. (For clients you
add later, you add their number in the same place: Part K, **Numbers → Add a number**.)

4. In the dashboard, click **Numbers** (top menu).
   - You should see: `sweetbakes` in the list, with the status `UNREACHABLE`: nothing is connected yet.
5. Click `sweetbakes`, then press **Relink**.
   - You should see: the status `SCAN_QR_CODE` and a QR code. The page refreshes itself every few seconds, so
     leave it open.
6. On the spare phone: WhatsApp → **Settings → Linked Devices → Link a Device**, and scan that QR code.
   - You should see: within a few seconds the status changes to `WORKING`, and the phone number appears.

> **Warning:** keep that phone charged and online (connected to the internet) at least once every 14 days.
> If it stays offline longer than that, WhatsApp logs the linked device out and you'll need to relink it.

### If the dashboard can't show the QR code

Only needed if step 5 shows an error (such as "WAHA said: ...") or no QR code appears. This links the number
through WAHA's own dashboard instead, over an SSH tunnel.

1. Open an SSH tunnel from your laptop — this makes the server's WAHA dashboard reachable from your laptop's
   browser, without exposing it to the internet. Keep this window open until you're done.
   **PowerShell, on your laptop:**
   ```powershell
   ssh -L 3000:127.0.0.1:3000 root@your.server.ip
   ```
2. In that same SSH session (you're now on the server, in your home directory), move into the project folder,
   load the WAHA secrets from `.env`, and create the session. The session **name must exactly match
   `waha_session`** in `clients.yaml` (`sweetbakes` in the example). If it answers that the session already
   exists (step 5 may have created it), that's fine: go on to step 3.
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
   - You should see: a JSON response describing the session.
3. On your **laptop** (keep the SSH/tunnel window open), open a browser to `http://localhost:3000/dashboard`.
   Log in with `WAHA_DASHBOARD_USERNAME` / `WAHA_DASHBOARD_PASSWORD` from `.env`.
4. On the spare phone: WhatsApp → **Settings → Linked Devices → Link a Device**, and scan the QR code shown
   on WAHA's dashboard.
   - You should see: the session's status change to "WORKING" there, and on your dashboard's **Numbers** page.

### Add the bot to groups

7. On the spare phone, add the number to each of the client's WhatsApp groups, the normal way (add
   participant). The bot posts its AI-disclosure intro automatically the moment it's added to a group.
8. Tell the bot which group is the staff group: in the dashboard open **Businesses** → your business →
   **Staff & groups**, tick **Staff group** next to the staff group, pick the same group under
   **Gets "needs a person" alerts**, and press **Save**.
   - You should see: "Saved." The bot uses it from the next message; no restart needed.
9. Check `https://<your-domain>/health` again.
   - You should see: `{"ok": true, ...}` now that the number is `WORKING`.

### If the purchased number gets banned

This is the real risk described in the warning above. If it happens:

1. Get a new SIM and install WhatsApp on it.
2. In the dashboard: **Numbers** → the number → **Log out**, then **Relink**, and scan the new QR code with the
   new phone (WhatsApp → Settings → Linked Devices → Link a Device).
   - If the dashboard can't show the QR code: open the SSH tunnel as in "If the dashboard can't show the QR
     code" above, then on the server `cd Whatsapp-assistant`, load `WAHA_API_KEY` from `.env`
     (`cat .env | grep WAHA_` then `export WAHA_API_KEY=...`), log out the old session and start it again:
     ```bash
     curl -X POST http://localhost:3000/api/sessions/sweetbakes/logout -H "X-Api-Key: $WAHA_API_KEY"
     curl -X POST http://localhost:3000/api/sessions/sweetbakes/start -H "X-Api-Key: $WAHA_API_KEY"
     ```
     and scan the new QR code on WAHA's dashboard (`http://localhost:3000/dashboard`).
3. Add the new number to the groups again.
4. The new number won't automatically re-introduce itself in groups where the bot already spoke before (the
   chat history survives the swap), so post the intro there yourself, once, by hand:
   > Hi, I'm Sara, Sweet Bakes's AI assistant. I read messages here so I can answer when you @mention me.

Group ids don't change and all history lives in the server's database, so nothing is lost by swapping numbers.

## 10. Part H: Monitoring and Backups

1. Point a free uptime monitor (e.g. UptimeRobot) at `https://<your-domain>/health`. It'll alert you if the
   database stops being writable or a group number drops out of `WORKING`. With several clients it turns red
   if *any* client's group number stops working; the dashboard's **Businesses** page shows which one.
2. The engine backs itself up automatically every day, to `data/backups/assistant-YYYYMMDD.db` on the server
   (inside your project folder), keeping the last 7 days. The dashboard's clients, numbers, logins and saved
   Meta keys live in the same database, so they're in these backups too. The Meta keys and two-step logins in
   a backup can only be read with the same `SECRET_KEY`, so keep your copy of `.env` with your backups.
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
4. **Staff expense, saved instantly.** From a staff phone (a number on the dashboard's **Staff & groups**
   page), 1:1, or in the staff group with an @mention, send: "spent 1500 on petrol today". You should see: an immediate reply starting "✅ Saved to
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
12. **The dashboard.** Work through Part K's **Dashboard click-through test**.

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

A business login sees only its own business: **Home** (both numbers' status, replies this month, and the latest requests for a person), **Setup**, **Bot settings**, **Staff & groups**, **Sheet** and **Chats**. Meta keys, the group number, logins, how long chats are kept and the Sheet id stay with you.

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

### Logins: reset a password or remove access

- **A business owner forgot their password:** open the business → **Logins** → **New link** next to their email, and send them the new link. Their old password stops working and they're signed out everywhere.
- **Someone should no longer have access:** press **Disable** next to their email (**Enable** undoes it).
- **Other admins:** the **Admins** page (top menu) works the same way. Nobody can disable their own login.
- **You're locked out, or lost your phone:** on the server run `docker compose exec engine python -m app.cli admin-link you@example.com` and open the link it prints.

### Let staff send email (optional)

Staff can ask the bot in WhatsApp to send an email from the business's own Gmail account, for example "email
this month's expenses to accountant@example.com". The bot writes the email and shows it first:

> 📧 Send this email?
> To: accountant@example.com
> Subject: September expenses
> ...
> Reply YES to send or NO to cancel.

It sends only after the same staff member replies YES (within 10 minutes). Customers can't send email.

To set it up, the business owner (or you) does this once:

1. In the business's Gmail account, turn on **2-Step Verification** (Google Account → Security).
2. Still in Security, open **App passwords**, create one named "WhatsApp assistant", and copy the 16 letters
   Google shows. This is not the normal Gmail password.
3. In the dashboard, open the business → **Email**, enter the Gmail address and the app password, and press
   **Save**.
4. Press **Send a test email**.
   You should see: "Sent. Check the inbox of …", and the test email arrives in that Gmail inbox.

Limits: one recipient per email, plain text only (no attachments), at most 50 emails per business a day. The
request, the preview and the "✅ Email sent" reply stay in the business's **Chats**, as the record of what was
sent. **Remove email** on the same page switches it off.

### Let the bot search the web (optional)

When the Sheet and the Knowledge tab don't have the answer, the bot can search the web, using your AI provider's
own search and the `LLM_API_KEY` already in `.env` (no new account). It works with OpenAI, Gemini and Ollama
Cloud; with any other `LLM_BASE_URL` the switches are greyed out.

1. Open the business → **Settings** → **Web search**.
2. Tick **Staff can ask the bot to search the web**. Tick **Customers too** only if customers should get it as
   well (it needs the staff switch on).
3. Press **Save**.
4. From a staff phone, ask the bot something only the web knows, like "what's PIA's helpline number?".
   You should see: an answer that names the website it came from, with a link.

For customers the bot is strict: the web is only for general facts like directions or public holidays, never the
business's own prices, stock, orders, hours or policies (those come only from the Sheet and Knowledge), and never
other businesses. Limits: 2 searches per message, 10 per customer chat and 100 per business a day. Each search
costs money on your AI provider's bill (Gemini lists about $35 per 1,000 searches; check your provider's
pricing).

### The Sheet page's safety checks

- A tab can only get permissions if it exists in the Sheet. "See their own rows" needs an owner column (the column holding the customer's phone number), and the columns picked for the customer's name and phone must be real columns of that tab.
- A tab with a column that looks like contact details (phone, mobile, whatsapp, number, contact, email or cnic) gets a warning. Letting customers **read all rows** there needs an extra tick, "I understand every customer can see these columns". Think twice before giving it.
- **What a customer would see** runs the bot's real lookup with your unsaved choices, as a sample customer, and shows the rows (or the exact message) they'd get. Nothing is saved until you press **Save permissions**.
- **Knowledge tab** and **Handoffs tab** list the Sheet's tabs; **(none)** means the default names, `Knowledge` and `Handoffs`.
- If the Sheet can't be read (not shared, or a wrong id), nothing is saved and the permissions stay as they were.

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

If you ran the engine before the dashboard existed:

1. Add `SECRET_KEY` to `.env` (Part E, step 6), and save a copy of `.env` somewhere private.
2. Update and restart, during quiet hours.
   **bash, on the server:**
   ```bash
   cd Whatsapp-assistant
   git pull
   docker compose up -d --build
   docker compose restart caddy
   ```
   The last line makes Caddy read the updated `Caddyfile`, which opens the dashboard's addresses. Without it the
   dashboard only answers "not found".
3. Check the one-time import: run `docker compose logs engine | grep imported`.
   You should see: `imported 1 business(es) from /config/clients.yaml` (the number of clients in your file).
   On that first start the engine copied `clients.yaml` and the Meta keys from `.env` into the dashboard
   database, once. From now on, change settings only in the dashboard; `clients.yaml` is ignored.
   - If the engine refuses to start and names a client id or `waha_session`, fix that name in `clients.yaml` and
     run `docker compose restart engine`. Nothing is imported until every entry is valid.
4. Create your admin login (the first section of this part).
5. The first business keeps working on the old webhook address `https://<your-domain>/webhooks/meta`. Switch it
   to its own address (on its **Official number** page) whenever convenient.

## 14. Day-to-Day Tasks

- **Change a price or an answer:** just edit the cell in the Sheet directly. Price/answer values themselves
  show up on the very next question; the Knowledge tab's text and any tab's column names can take up to 5
  minutes to refresh (they're cached briefly to avoid hammering Google's API).
- **Add a staff member or group:** in the dashboard, open the business → **Staff & groups**, add the number or
  tick the group, and press **Save**. The bot uses it from the next message.
- **Add a new tab:** create the tab and its header row in the Sheet, then in the dashboard open the business →
  **Sheet**, tick "the bot uses this tab", choose what customers may do, and press **Save permissions**.
- **Add a new business:** follow Part K, "Add a business".
- **See how much each client used this month:** the dashboard's **Businesses** page shows each client's
  official and group replies this month (Meta charges for official replies after 1,000 a month).
- **Read a client's chats:** open the business → **Chats**.
- **A client stopped paying:** open the business → **Pause business** (Part K). Nothing is deleted.
- **Reset a login or remove someone's access:** Part K, "Logins: reset a password or remove access".
- **Let staff send email:** Part K, "Let staff send email (optional)".
- **Update to a new version of the code:** on the server, during quiet hours (a restart drops any message
  that was received but not yet answered — there's no queue):
  ```bash
  cd Whatsapp-assistant
  git pull
  docker compose up -d --build
  docker compose restart caddy
  ```
  The last line makes Caddy read any change to the `Caddyfile`; it's quick and harmless when nothing changed.
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

**Dashboard problems:**

- **The engine won't start, and its log says "Set SECRET_KEY in .env".** Add `SECRET_KEY` to `.env`
  (Part E, step 6), then run `docker compose up -d`.
- **The engine won't start, and its log names a client id or a `waha_session`.** That entry in `clients.yaml`
  breaks the naming rule (3–32 lowercase letters, digits or dashes) or repeats another entry. Fix it, upload it
  again and run `docker compose restart engine`; nothing is imported until every entry is valid.
- **`https://<your-domain>/login` shows "not found".** Caddy is still using an old `Caddyfile`: run
  `docker compose restart caddy`.
- **"Too many tries. Wait 15 minutes and try again."** Five wrong passwords for one email pause it for 15
  minutes. Wait, then try again carefully.
- **"This link has expired or was already used."** Invite and reset links work once, for 7 days. Get a new one:
  for a business login, **Logins → New link**; for an admin,
  `docker compose exec engine python -m app.cli admin-link <their email>`.
- **The two-step code is refused ("That code didn't match").** Codes depend on the time, so set your phone's
  clock to automatic. Lost the phone? Use `admin-link` (above); it resets the password and the two-step login.
- **"Your two-step login can't be read (was SECRET_KEY changed?)", or a business's Official number page says
  its saved keys can't be read.** `SECRET_KEY` changed. If you have the old value, put it back in `.env` and
  run `docker compose up -d`. Otherwise reset each admin with `admin-link`, and paste each business's Meta keys
  again on its **Official number** page.
- **"Test connection" says "Meta refused: ...".** The phone number ID or the access token is wrong or has
  expired. Copy them again from the client's Meta app (Part C), press **Save keys**, then test again.
- **The Sheet page (or Add a business) says "Share the Sheet with ... as Editor" or "No Sheet with that
  id".** Share the Sheet with the service-account email shown on the page, as Editor (Part A, step 13), or
  check the Sheet id.
- **A number shows `UNREACHABLE` on the Numbers page.** Either it isn't linked yet (open it and press
  **Relink**), or WAHA itself is down: on the server, `docker compose ps` should list `waha` as running, and
  `docker compose logs waha` shows why it isn't.
- **"Gmail refused the email address or app password".** The app password is wrong or was deleted, or 2-Step
  Verification was turned off. Make a new app password (Part K, "Let staff send email") and save it on the
  business's **Email** page. A Google Workspace account whose admin has turned app passwords off can't use this.

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
- **Admin / business login:** an admin (you) sees every business in the dashboard; a business login sees
  only its own. Nobody can sign up on their own: every login starts as an invite link.
- **Invite link:** a one-time link that lets a new login choose its password. It works for 7 days.
- **Two-step login:** after the password, admins also type a 6-digit code from an authenticator app on their
  phone, so a stolen password alone isn't enough.
- **`SECRET_KEY`:** the random value in `.env` that locks the Meta keys and two-step logins saved in the
  dashboard's database. Keep a copy, and never change it.
- **App password:** a 16-letter password Google creates for one app, so it can use a Gmail account without the
  account's real password. It needs 2-Step Verification, and you can delete it any time in the Google account.
- **QR linking:** connecting a phone number to WAHA by scanning a QR code with WhatsApp's own
  Linked Devices feature — the same mechanism as linking WhatsApp Web.
- **Group id (`…@g.us`):** WAHA's identifier for one WhatsApp group chat.
- **Service account:** a Google account created for a program rather than a person, used here so the engine
  can read and write a client's Sheet without ever holding the client's own Google password.
- **BSUID (business-scoped user id):** the id Meta uses to identify a customer in official-API webhooks; a
  customer's actual phone number may be hidden from the business, but their BSUID is always present.
