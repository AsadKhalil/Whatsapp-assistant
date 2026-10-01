# Email Sending for Staff — Design

**Date:** 2026-09-30 · **Owner:** Jawad · **Status:** design approved in chat (2026-09-30); this document awaits owner review.
**Builds on:** `docs/superpowers/specs/2026-09-23-whatsapp-engine-design.md` (the engine) and
`docs/superpowers/specs/2026-09-28-dashboard-admin-design.md` (the dashboard).

## 1. Goal

A business's staff can ask the bot in WhatsApp to send an email ("email this month's expenses to
accountant@example.com"). The bot writes it, shows a preview, and after the staff member replies YES sends it from
the business's own Gmail account.

## 2. Users and success criteria

Staff are whoever the engine already treats as staff: a staff number messaging either number 1:1, or anyone in a
group ticked as a staff group. Customers can never send email.

Success means:
1. A staff member asks for an email and, after YES, the recipient gets it from the business's Gmail address.
2. No email leaves without a preview and a YES from the same person in the same chat.
3. Customers can't make the bot send email.
4. The Gmail app password is never shown on a page, written to the audit log, or logged.
5. Setting email up for a business takes about 15 minutes in the dashboard, with a test button to prove it works.

## 3. Scope

**In:** one plain-text email to one address per request; per-business Gmail address and app password (Gmail
SMTP); an **Email** page in the dashboard with a test button; preview + YES/NO confirmation; a daily cap.

**Out:** attachments, HTML, CC/BCC or several recipients, reading or receiving email, Google sign-in (OAuth),
email services (SendGrid and the like), scheduled emails, customers sending email, email templates.

## 4. Approach

Gmail's SMTP server (`smtp.gmail.com`, port 587, STARTTLS) with a Google **app password**, using Python's
standard `smtplib` and `email` modules — no new dependency. Considered and not chosen:
- Gmail API with Google sign-in (OAuth): no stored password, but every business would need a Google Cloud OAuth
  setup, and Google must review the app before other people can connect.
- A transactional email service (Resend, SendGrid): best deliverability, but emails come from our domain, not
  the business's Gmail, it costs money past a free tier, and it needs DNS setup.

Sending lives in its own small module (`app/mailer.py`), so another way of sending can replace it later.

## 5. Behaviour

### 5.1 In chat

- The AI is offered a `send_email(to, subject, body)` tool **only when** the caller is staff **and** the
  business has email set up (both an address and a readable app password). Customers are never offered it, so
  if a customer asks, the AI can only say it can't send email. If the AI calls it anyway for a customer, or for a
  business without email, the engine refuses with an error and nothing is stored or sent.
- When the AI calls it, the engine checks the request (§5.2), stores it as the sender's **pending email** for
  10 minutes (the same lifetime as a customer's proposed row), and ends the turn with a preview the code writes
  (not the AI):

  ```
  📧 Send this email?
  To: accountant@example.com
  Subject: September expenses

  <the email text>

  Reply YES to send or NO to cancel.
  ```
- **YES** from the same sender in the same chat, within 10 minutes: the engine sends it (§5.3) and replies
  "✅ Email sent to accountant@example.com." If sending fails, it replies "Couldn't send the email: <reason>"
  and keeps the pending email, so YES can retry after the problem is fixed.
- **NO**: "Cancelled, nothing was sent."
- A newer `send_email` from the same sender replaces their earlier pending email. One preview per turn.
- The YES words are the engine's existing ones (`yes`, `haan`, `ji`, 👍 …), and the same "only the person who
  asked can answer" rule applies as for customer proposals.

### 5.2 Checks before the preview

- `to`: exactly one address — `something@something.something`, no spaces, commas, semicolons, angle brackets or
  quotes, at most 254 characters. Anything else goes back to the AI as an error ("That isn't one email address")
  so it can ask the staff member.
- `subject`: 1–200 characters after trimming; line breaks become spaces.
- `body`: 1–3,500 characters after trimming, so the preview fits in one WhatsApp message (4,096 characters).
- **Daily cap:** at most 50 emails sent per business in any 24 hours. Checked before the preview and again at
  send time; when reached: "This business has sent 50 emails in the last 24 hours. Try again later."

### 5.3 Sending

- From: the business name and its Gmail address (`"Sweet Bakes" <sweetbakes@gmail.com>`); To: the one address;
  the subject; the text as plain UTF-8.
- `smtp.gmail.com:587`, STARTTLS, log in with the address and app password, send, 30-second timeout.
- Errors become one readable reason:
  - Gmail refused the login → "Gmail refused the email address or app password (check the business's Email page)".
  - Gmail refused the recipient → "Gmail refused the address <to>".
  - Anything else (network, timeout) → "Gmail couldn't be reached right now".
- Sending runs where the bot already works (the webhook's background task), so it never delays the webhook's
  answer to Meta or WAHA.

### 5.4 Records and privacy

- Each email sent adds a row to a new `emails_sent(client_id, at)` table in the message store, used only for the
  daily cap; the daily maintenance deletes rows older than two days.
- Pending emails live in a new `pending_emails` table in the message store (one per business + chat + sender,
  with an expiry); the daily maintenance deletes expired ones, as it does for pending rows.
- Logs record `email_sent client=<id>` or `email_failed client=<id> error=<kind>` — never the address, subject
  or text.
- The conversation itself (the request, the preview, YES, "✅ Email sent") is kept like every chat and shows in
  the dashboard's **Chats**, subject to the business's retention days. That is the record of what was sent.

## 6. Settings

### 6.1 Storage

- A new registry table `email_accounts(business_id TEXT PRIMARY KEY REFERENCES businesses(id), address TEXT NOT
  NULL, app_password TEXT NOT NULL, updated_at REAL NOT NULL)`. The app password is sealed with `Vault`, like
  the Meta keys. A separate table (rather than new columns on `businesses`) means existing databases need no
  migration: it is created with `CREATE TABLE IF NOT EXISTS`.
- `Registry.save_email(business_id, address, app_password, actor)`: checks the address (as §5.2) and the app
  password (16 letters once spaces are removed; Google shows it as four groups of four); an empty app password
  keeps the saved one; audit `email.save` with detail `{"address": <address>, "app_password": "(changed)"}` when
  a new password was given.
- `Registry.remove_email(business_id, actor)`: deletes the row; audit `email.remove`.
- `Client` gains `email_address: str = ""` and `email_app_password: str = field(default="", repr=False)`.
  `Registry.clients()` fills them; a password that can't be opened (SECRET_KEY changed) leaves email switched off
  for that business.
- `Business` (what pages see) gains `email_address`, `has_email_password` and `email_unreadable`.

### 6.2 The Email page

- A business screen at `/app/email` (business logins) and `/admin/b/{id}/email` (admins), with an **Email** tab
  in the business navigation. Both can open it, because it is the business's own Gmail account (unlike Meta
  keys, which stay admin-only).
- Fields: **Gmail address**; **App password** (write-only: shows "saved" when one is stored; leave it empty to
  keep it); **Save**; **Remove email**; **Send a test email**.
- The test sends "Email is set up for <business>." to the Gmail address itself and shows "Sent — check the inbox
  of <address>" or the reason it failed. It uses the saved settings and doesn't count toward the daily cap.
- Help text on the page: turn on 2-Step Verification in the Google account, then Google Account → Security →
  App passwords → create one named "WhatsApp assistant", and paste the 16 letters here.
- If the saved password can't be read: "The saved app password can't be read (was SECRET_KEY changed?). Enter it
  again."
- Every save reloads the bot's settings at once (`app.state.reload()`), as for every other setting.

## 7. Error handling

- Gmail errors: shown in chat (§5.3) and on the test button's result; the pending email is kept.
- Unreadable app password: email is off for that business until the password is entered again.
- Cap reached: the message in §5.2.
- A pending email expires after 10 minutes; a later YES is then an ordinary message.

## 8. Testing

pytest, no network, as for the engine and dashboard:
- A `FakeMailer` records sends and can be told to fail.
- The tool is offered to staff of a business with email set up, and not to customers or to businesses without
  email.
- Preview → YES sends once with the business's address and name; NO cancels; another sender's YES does nothing;
  an expired pending email does nothing; a failed send keeps the pending email.
- Bad address, several addresses, a subject over 200 or text over 3,500 characters are refused before any preview.
- The 51st email in 24 hours is refused.
- `app/mailer.py` against a fake `smtplib.SMTP`: STARTTLS, login and send are called; each error maps to its reason.
- Registry: the app password is sealed, never in the audit log or on a page; `clients()` fills the fields;
  remove; an unreadable password switches email off.
- Email page: write-only password, save and remove, test success and failure, a business can't reach another
  business's page, POSTs need the CSRF token.
- Logs never contain the address, subject or text.

## 9. Decisions log

- Owner chose: staff can email any address; Gmail with an app password (2026-09-30).
- A preview and YES are required even for staff (staff Sheet rows save at once), because an email leaves the
  business.
- One recipient, plain text, no attachments in this version.
- Both the business and admins manage the Email page, since it is the business's own Gmail.
- At most 50 emails per business in any 24 hours.

## 10. Risks

- Google or a Workspace admin can turn off app passwords for an account; the test button then shows Gmail's
  refusal, and Google sign-in (OAuth) or an email service would be the next step.
- Gmail may file the emails as spam if they look like spam; sending plain text from the business's own address
  keeps this low.
- A staff member can email Sheet data to anyone (the owner's choice); the preview, the YES and the record in Chats
  are the controls.
