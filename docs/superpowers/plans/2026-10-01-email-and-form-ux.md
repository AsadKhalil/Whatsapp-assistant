# Staff Email Sending and Dashboard Form UX — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the problems a UX audit found in the dashboard's forms, then let staff ask the bot in WhatsApp to send an email from the business's Gmail, after a preview and a YES.

**Architecture:** The UX fixes are template, CSS and `app.js` changes, plus passing per-tab Sheet problems to the template. Email: a small `app/mailer.py` sends through Gmail SMTP with an app password (standard library only); the registry stores each business's Gmail address and sealed app password in a new `email_accounts` table; the bot offers a `send_email` tool only to staff of a business with email set up, stores the email as pending, and sends it on YES; a new **Email** business screen manages the settings.

**Tech Stack:** Python 3.12 (uv), FastAPI, Jinja2, Pico.css, vanilla JS, sqlite3, `smtplib`/`email`/`ssl` from the standard library; pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-09-30-email-sending-design.md` (email). The UX fixes come from the audit below (ui-ux-pro-max guidelines, 2026-10-01).

## Global Constraints

- Python `>=3.12`, uv, `[tool.uv] package = false`; run commands from the repo root with `uv run`.
- No new dependencies. Email uses `smtplib`, `email` and `ssl` from the standard library.
- Ruff `select = ["E4", "E7", "E9", "F"]`: no unused imports, no `;`-joined statements, no one-line `def x(): y`, no assigned lambdas.
- Every response carries `Content-Security-Policy: default-src 'self'; ...`, so templates must not use inline `style="..."` attributes, inline event handlers or inline `<script>`; styles go in `app/static/app.css`, behaviour in `app/static/app.js`.
- Jinja autoescape stays on. `Markup` may only wrap literal constants or generated SVG, never user or formatted text.
- Every signed-in POST carries the session's CSRF token in the form field `csrf`.
- Secrets are write-only on screen and never logged or audited: the Gmail app password is sealed with `Vault`; audit detail says `(changed)`.
- Email (spec): staff only; one recipient; plain text; preview + YES from the same sender in the same chat within 10 minutes; at most 50 emails per business per rolling 24 hours; Gmail SMTP `smtp.gmail.com:587` with STARTTLS and certificate checks; logs carry `email_sent client=<id>` / `email_failed client=<id> error=<kind>` and never the address, subject or text.
- Commit after every task; stage only the files you changed, by name (never `git add -A` / `git add .`); never stage `.env` or `.DS_Store`.

## Plan decisions

1. **Email text limit is 3,500 characters**, not the spec's 5,000: the preview goes back to WhatsApp, which refuses messages over 4,096 characters, and the staff member must see the whole email they confirm. The spec is updated to match in Task 6.
2. **`MailError` carries a `kind`** (`auth`, `recipient`, `network`, `message`) so logs can say what failed without the address (the human message for the recipient error contains the address).
3. **`is_email()` lives in `app/mailer.py`** and is shared by the registry (the Gmail address) and the bot (the recipient).
4. **Pending emails and the daily email count** live in the message store (`pending_emails`, `emails_sent`), next to pending Sheet rows.
5. **Pause/Resume moves from the business tab bar to the bottom of the admin's business Home page**, in a separated "danger zone" with a confirmation.
6. **Not changed from the audit:** status codes stay as `WORKING` / `SCAN_QR_CODE` / `UNREACHABLE` (the setup guide quotes them, and the pages already show plain hints beside them); validation messages keep their wording (HTML `required`/`min`/`max` attributes already stop the inputs that would trigger them); no show-password toggle (password managers work, autocomplete is set); the long time-zone list stays a native select (type-to-jump works).

## UX audit (2026-10-01, ui-ux-pro-max guidelines) — what each task fixes

| # | Finding | Guideline | Fixed in |
|---|---|---|---|
| 1 | Inline `style="..."` on 8 elements is blocked by the CSP, so the first-run steps restart at 1 in each section and spacing tweaks never apply | CSP / layout | Task 1 |
| 2 | The business **Home** tab is highlighted on every business page (prefix match) | `nav-state-active` | Task 1 |
| 3 | Destructive actions run on one click and look like normal buttons: number **Log out** (stops the bot in all groups) and **Delete**, login **Disable** and **New link**, **Pause business** | `confirmation-dialogs`, `destructive-emphasis` | Task 1 |
| 4 | **Pause business** sits inside the tab bar with the navigation links | `destructive-nav-separation` | Task 1 |
| 5 | Slow buttons (Check Sheet access, Test connection, preview, Add number, Relink) give no feedback and can be pressed twice | `loading-buttons`, `submit-feedback` | Task 1 |
| 6 | Page errors aren't announced to screen readers and don't take focus | `aria-live-errors`, `focus-management` | Task 1 |
| 7 | No skip link to the content | `skip-links` | Task 1 |
| 8 | Copy buttons say "Copied" even when copying failed | `error-feedback` | Task 1 |
| 9 | Invite form and number notes/business fields have placeholder or aria-only labels | `input-labels` | Task 2 |
| 10 | Optional fields aren't marked; the web id doesn't say it can be left empty | `required-indicators`, `input-helper-text` | Task 2 |
| 11 | Staff table checkboxes and radios have no accessible names | `form-labels` | Task 2 |
| 12 | "What a customer would see" reloads the page at the top, away from the tab's result | `state-preservation` | Task 2 |
| 13 | Sheet permission problems show only at the top of a long page, not at the tab | `error-placement` | Task 2 |
| 14 | Options of tabs the bot doesn't use look as active as the rest; the contact-columns warning is styled as an error | `progressive-disclosure`, `color-not-only` | Task 2 |
| 15 | "Test connection" tests the *saved* keys, which the page doesn't say | `error-clarity` | Task 2 |
| 16 | The service-account email on Add a business and Sheet has no copy button | `redundant-entry` | Task 2 |

## Review Focus

- **A customer, or any message, getting an email sent:** only staff may ever trigger a send. Pinned: Task 5 `test_a_customer_cant_send_email_even_if_the_model_tries`, `test_only_the_staff_member_who_asked_can_confirm`.
- **An email sent without the person seeing it:** the preview must show the exact recipient, subject and text, and fit in one WhatsApp message. Pinned: Task 5 `test_staff_email_is_previewed_then_sent_on_yes`, `test_bad_emails_go_back_to_the_model_without_a_preview`.
- **The app password leaking:** never on a page, in the audit log, in `repr`, or in logs. Pinned: Task 4 `test_email_settings_are_sealed_audited_without_the_password_and_reach_the_client`, Task 5 `test_logs_never_hold_the_email`, Task 6 `test_a_business_sets_up_email_and_the_password_is_never_shown`.
- **Gmail failing:** the staff member gets a reason and can retry with YES; the test button shows Gmail's answer. Pinned: Task 5 `test_a_failed_send_keeps_the_email_for_another_yes`, Task 6 `test_the_test_button_sends_to_the_gmail_address_and_shows_gmails_answer`.
- **Inline styles creeping back** and breaking silently under the CSP. Pinned: Task 1 `test_templates_have_no_inline_styles_or_handlers`.

---

## File Structure

| File | Responsibility |
|---|---|
| `app/static/app.js` (modify) | Toasts, copy buttons (with a fallback), current-tab marking, confirmations, busy buttons, focusing page errors |
| `app/static/app.css` (modify) | Classes replacing inline styles; `.danger` buttons; `.danger-zone`; `.skip-link`; `.notice.warn`; `.field-error`; dimmed unused Sheet tabs |
| `app/templates/*.html` (modify) | Labels, helper text, confirmations, the Pause section, the Email tab |
| `app/pages.py` (modify) | Passes Sheet `problems` to the template; the Email screen |
| `app/mailer.py` (create) | `Mailer.send` over Gmail SMTP, `MailError`, `is_email` |
| `app/config.py` (modify) | `Client.email_address`, `Client.email_app_password` |
| `app/registry.py` (modify) | `email_accounts` table, `save_email`, `remove_email`, email fields on `Business` and `Client` |
| `app/store.py` (modify) | `pending_emails` and `emails_sent` tables and their methods |
| `app/tools.py` (modify) | `SEND_EMAIL_SPEC`, `email_request`, `email_preview` |
| `app/bot.py` (modify) | Offers `send_email` to staff, previews, sends on YES, daily cap |
| `app/main.py` (modify) | `build_bot` gives the bot a `Mailer` |
| `app/web.py` (modify) | `OK_MESSAGES["email_removed"]` |
| `app/templates/email.html` (create) | The Email screen |
| `tests/fakes.py` (modify) | `FakeMailer`; `ScriptedLLM.tools`; `make_bot` passes a `FakeMailer` |
| `tests/test_web_ux.py`, `tests/test_mailer.py`, `tests/test_bot_email.py`, `tests/test_pages_email.py` (create) | Tests |
| `docs/setup-guide.md`, `README.md`, the email spec (modify) | Docs |

---

### Task 1: UX — CSP-safe layout, current tab, confirmations, busy buttons, announced errors

**Files:**
- Modify: `app/static/app.js`, `app/static/app.css`, `app/templates/base.html`, `app/templates/admin_meta.html`, `app/templates/admin_number.html`, `app/templates/admin_overview.html`, `app/templates/business_home.html`, `app/templates/number_link.html`, `app/templates/numbers.html`, `app/templates/logins.html`
- Test: `tests/test_web_ux.py` (create)

**Interfaces:**
- Consumes: `tests.webkit.Site`, `csrf`; existing routes.
- Produces: CSS classes `.lede`, `ol.steps.from-5`, `ol.steps.from-7`, `button.danger`, `.danger-zone`, `.skip-link`; the `data-confirm="question"` attribute (on a submit button or its form) that `app.js` turns into a confirmation; `id="main"` on `<main>`; `id="page-error" role="alert"` on the page error. Later tasks use `button.danger`, `.danger-zone`, `.lede` and `data-confirm`.

- [ ] **Step 1: Write the failing tests**

`tests/test_web_ux.py`:
```python
from pathlib import Path

from tests.webkit import Site, csrf


def test_templates_have_no_inline_styles_or_handlers():
    """The Content-Security-Policy blocks inline styles and handlers, so they would silently do nothing."""
    for path in Path("app/templates").glob("*.html"):
        text = path.read_text(encoding="utf-8")
        assert ' style="' not in text and " onclick=" not in text and " onsubmit=" not in text, path.name


def test_pages_have_a_skip_link_and_errors_are_announced():
    site = Site()
    http = site.business_user()
    page = http.post("/app/settings", data={"csrf": csrf(http, "/app/settings"), "business": "Sweet Bakes",
                                            "bot_name": "Sara", "instructions": "", "timezone": "Mars/Base",
                                            "date_format": ""}).text
    assert 'href="#main"' in page and 'id="main"' in page
    assert 'id="page-error"' in page and 'role="alert"' in page


def test_pause_lives_on_the_business_home_with_a_confirmation_not_in_the_tabs():
    site = Site()
    admin = site.admin()
    home = admin.get("/admin/b/acme").text
    assert 'data-confirm="Pause Sweet Bakes?' in home and 'class="danger"' in home
    assert "Pause business" not in admin.get("/admin/b/acme/settings").text
    assert "Pause business" not in site.business_user().get("/app").text


def test_destructive_buttons_ask_first():
    site = Site()
    site.registry.add_number("spare-1", "", actor="t")
    site.auth.invite("mgr@sweetbakes.pk", "", "business", "acme")
    admin = site.admin()
    number = admin.get("/admin/numbers/spare-1").text
    assert 'data-confirm="Log out spare-1?' in number and 'data-confirm="Delete spare-1?' in number
    logins = admin.get("/admin/b/acme/logins").text
    assert 'data-confirm="Disable mgr@sweetbakes.pk?' in logins
    assert 'data-confirm="Make a new link for mgr@sweetbakes.pk?' in logins
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_web_ux.py -v`
Expected: FAIL — the inline-style test names `admin_meta.html` (or another template with `style="`), and the other three fail their assertions.

- [ ] **Step 3: Replace the inline styles with classes**

Make exactly these replacements:
- `app/templates/admin_meta.html`: `<p class="muted" style="margin-top:0">` → `<p class="muted lede">`; `<p style="margin-top:.3rem">` → `<p class="lede">`.
- `app/templates/admin_number.html`: `<p class="muted" style="margin-top:0">` → `<p class="muted lede">`.
- `app/templates/admin_overview.html`: `<ol class="steps" style="counter-reset: step 4">` → `<ol class="steps from-5">`; `<ol class="steps" style="counter-reset: step 6">` → `<ol class="steps from-7">`.
- `app/templates/business_home.html`: `<p class="muted" style="margin:.3rem 0 0">` → `<p class="muted lede">`.
- `app/templates/number_link.html`: `<p class="muted" style="margin-top: .4rem">` → `<p class="muted lede">`.
- `app/templates/numbers.html`: `<p class="muted" style="margin:0">` → `<p class="muted lede">`.

Append to `app/static/app.css`:
```css
/* Replacements for inline styles, which the Content-Security-Policy blocks */
.lede { margin: 0.3rem 0 0; }
ol.steps.from-5 { counter-reset: step 4; }
ol.steps.from-7 { counter-reset: step 6; }

/* Skip link: hidden until a keyboard user tabs to it */
.skip-link {
  position: absolute; left: -999px; top: 0.5rem; z-index: 20;
  padding: 0.45rem 0.9rem; border-radius: 0.5rem; background: var(--surface); color: var(--ink);
}
.skip-link:focus { left: 0.5rem; }

/* Destructive actions: red outline, kept apart from the primary buttons */
button.danger { background: transparent; color: var(--danger); border: 1px solid var(--danger-line); }
button.danger:hover, button.danger:focus-visible {
  background: var(--danger-soft); color: var(--danger); border-color: var(--danger);
}
.danger-zone {
  margin-top: 2.5rem; padding: 1rem 1.25rem; border: 1px solid var(--danger-line); border-radius: 0.75rem;
}
.danger-zone h2 { margin-bottom: 0.3rem; font-size: 1.1rem; }
```

- [ ] **Step 4: Skip link, main landmark, announced errors, no Pause in the tabs**

In `app/templates/base.html`:
- Right after `<body>`, add: `<a class="skip-link" href="#main">Skip to content</a>`
- Change `<main class="container">` to `<main class="container" id="main" tabindex="-1">`.
- Delete the whole `<li>` that holds the pause form (from `<li>` before `<form method="post" action="{{ base }}/pause" class="inline">` to its closing `</li>`), leaving `{% endif %}` and `</ul></nav>{% endif %}` in place.
- Change `{% if error %}<p class="notice error">{{ error }}</p>{% endif %}` to:
```html
  {% if error %}<p class="notice error" id="page-error" role="alert" tabindex="-1">{{ error }}</p>{% endif %}
```

Append to the end of `app/templates/business_home.html`, just before `{% endblock %}`:
```html
{% if is_admin %}
<section class="danger-zone">
  {% if business.active %}
  <h2>Pause this business</h2>
  <p class="muted">The bot stops answering all of this business's messages, on both numbers. Nothing is deleted,
    and you can resume it at any time.</p>
  {% else %}
  <h2>Resume this business</h2>
  <p class="muted">The bot starts answering this business's messages again.</p>
  {% endif %}
  <form method="post" action="{{ base }}/pause">
    <input type="hidden" name="csrf" value="{{ csrf }}">
    <input type="hidden" name="active" value="{{ '0' if business.active else '1' }}">
    {% if business.active %}
    <button type="submit" class="danger"
            data-confirm="Pause {{ business.config.business }}? The bot stops answering all its messages until you resume it.">Pause business</button>
    {% else %}
    <button type="submit">Resume business</button>
    {% endif %}
  </form>
</section>
{% endif %}
```

- [ ] **Step 5: Confirm the destructive buttons**

In `app/templates/number_link.html`, replace the Log out and Delete forms inside `<div class="grid">` with:
```html
  <form method="post" action="/admin/numbers/{{ number.session }}/logout">
    <input type="hidden" name="csrf" value="{{ csrf }}">
    <button type="submit" class="danger"
            data-confirm="Log out {{ number.session }}? The bot stops answering in its groups until the phone scans a new QR code.">Log out</button></form>
  {% if not number.business_id %}
  <form method="post" action="/admin/numbers/{{ number.session }}/delete">
    <input type="hidden" name="csrf" value="{{ csrf }}">
    <button type="submit" class="danger"
            data-confirm="Delete {{ number.session }}? It is removed from the server and its phone must be linked again to use it.">Delete</button></form>
  {% endif %}
```

In `app/templates/logins.html`, replace the two buttons inside the per-user `<form method="post" class="inline">` with:
```html
        <button type="submit" name="action" value="link" class="secondary outline"
                data-confirm="Make a new link for {{ u.email }}? Their current password stops working and they're signed out.">New link</button>
        {% if u.id != self_id %}
        {% if u.disabled %}
        <button type="submit" name="action" value="enable" class="secondary outline">Enable</button>
        {% else %}
        <button type="submit" name="action" value="disable" class="danger"
                data-confirm="Disable {{ u.email }}? They are signed out at once and can't log in until you enable them.">Disable</button>
        {% endif %}
        {% endif %}
```

- [ ] **Step 6: Make app.js confirm, show progress, fix the current tab and the copy fallback**

Replace the whole of `app/static/app.js` with:
```javascript
/* Dashboard niceties: toasts, copy buttons, the current tab, confirmations, busy buttons. No dependencies. */
(function () {
  "use strict";

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Toasts: the server puts the confirmation into #toasts[data-ok]; show it briefly.
  var host = document.getElementById("toasts");
  if (host && host.dataset.ok) {
    toast(host.dataset.ok, "ok");
  }

  function toast(text, kind) {
    var el = document.createElement("div");
    el.className = "toast " + kind;
    var dot = document.createElement("span");
    dot.className = "dot";
    dot.setAttribute("aria-hidden", "true");
    el.appendChild(dot);
    el.appendChild(document.createTextNode(text));
    el.title = "Dismiss";
    host.appendChild(el);
    requestAnimationFrame(function () { el.classList.add("in"); });
    var timer = setTimeout(dismiss, 5000);
    el.addEventListener("click", dismiss);
    function dismiss() {
      clearTimeout(timer);
      el.classList.remove("in");
      setTimeout(function () { el.remove(); }, reduceMotion ? 0 : 250);
    }
  }

  // A page that failed to save shows its error at the top: move focus there so it is read out.
  var problem = document.getElementById("page-error");
  if (problem) problem.focus();

  // Copy buttons: <button class="copy-btn" data-copy="...">. Without clipboard access, select the text instead.
  document.addEventListener("click", function (event) {
    var btn = event.target.closest(".copy-btn");
    if (!btn) return;
    var before = btn.textContent;
    var show = function (label) {
      btn.textContent = label;
      setTimeout(function () { btn.textContent = before; }, 1800);
    };
    var selectText = function () {
      var code = btn.parentElement && btn.parentElement.querySelector("code");
      if (code) {
        var range = document.createRange();
        range.selectNodeContents(code);
        var selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
      }
      show("Press Ctrl+C");
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(btn.dataset.copy).then(function () { show("Copied"); }, selectText);
    } else {
      selectText();
    }
  });

  // Mark the open page's tab in each nav: the longest matching link, so "Home" isn't lit on every page.
  var here = location.pathname.replace(/\/$/, "") || "/";
  document.querySelectorAll(".topbar-nav, nav.tabs").forEach(function (nav) {
    var best = null;
    var bestLength = -1;
    nav.querySelectorAll("a").forEach(function (a) {
      var url = new URL(a.href, location.origin);
      if (url.origin !== location.origin) return;
      var target = url.pathname.replace(/\/$/, "") || "/";
      var matches = target === here || here.indexOf(target + "/") === 0;
      if (matches && target.length > bestLength) {
        best = a;
        bestLength = target.length;
      }
    });
    if (best) best.setAttribute("aria-current", "page");
  });

  // Destructive actions: data-confirm="question" on the button (or its form) asks first.
  // Then the pressed button shows it's working and the form can't be sent twice.
  document.addEventListener("submit", function (event) {
    var form = event.target;
    var button = event.submitter;
    var question = (button && button.dataset.confirm) || form.dataset.confirm;
    if (question && !window.confirm(question)) {
      event.preventDefault();
      return;
    }
    if (button) button.setAttribute("aria-busy", "true");
    // Disable after this tick, so the pressed button's name and value still go with the form.
    setTimeout(function () {
      form.querySelectorAll("button[type=submit], button:not([type])").forEach(function (b) { b.disabled = true; });
    }, 0);
  });

  // Back to a page kept in memory: undo the busy state so its buttons work again.
  window.addEventListener("pageshow", function (event) {
    if (!event.persisted) return;
    document.querySelectorAll("[aria-busy=true]").forEach(function (b) { b.removeAttribute("aria-busy"); });
    document.querySelectorAll("form button[disabled]").forEach(function (b) { b.disabled = false; });
  });
})();
```

In `app/templates/base.html`, bump the cache-busting query strings so browsers load the new files: `app.css?v=10` → `app.css?v=11`, and `src="/static/app.js"` → `src="/static/app.js?v=2"`.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_web_ux.py -v`
Expected: PASS (4 passed)

Run: `uv run pytest -q && uv run ruff check .`
Expected: all tests pass; `All checks passed!`

- [ ] **Step 8: Commit**

```bash
git add app/static/app.js app/static/app.css app/templates/base.html app/templates/admin_meta.html app/templates/admin_number.html app/templates/admin_overview.html app/templates/business_home.html app/templates/number_link.html app/templates/numbers.html app/templates/logins.html tests/test_web_ux.py
git commit -m "fix: CSP-safe layout, confirmations for destructive actions, busy buttons and announced errors"
```

### Task 2: UX — visible labels, helper text, and a Sheet page that keeps your place

**Files:**
- Modify: `app/pages.py`, `app/static/app.css`, `app/templates/logins.html`, `app/templates/numbers.html`, `app/templates/number_link.html`, `app/templates/admin_new.html`, `app/templates/settings.html`, `app/templates/staff.html`, `app/templates/sheet.html`, `app/templates/admin_meta.html`
- Test: `tests/test_web_ux.py`

**Interfaces:**
- Consumes: Task 1's classes; `tests.webkit.Site`, `csrf`; `FakeWaha.group_list`.
- Produces: the Sheet template receives `problems: list[str]` (each starts with `"<tab>: "`); each Sheet tab card has `id="tab-<i>"`; CSS classes `.notice.warn`, `.field-error`, `.tab-options`, `.use-tab`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web_ux.py`:
```python
def test_invite_and_number_forms_have_visible_labels():
    site = Site()
    site.registry.add_number("spare-1", "", actor="t")
    admin = site.admin()
    logins = admin.get("/admin/b/acme/logins").text
    assert 'aria-label="Email"' not in logins and "<label>Email" in logins
    number = admin.get("/admin/numbers/spare-1").text
    assert 'aria-label="Notes"' not in number and 'aria-label="Business"' not in number
    assert "<label>Answers for" in number


def test_staff_table_controls_are_named_for_screen_readers():
    site = Site()
    site.bot.waha.group_list["acme"] = [{"id": "staff@g.us", "name": "Kitchen staff"}]
    page = site.business_user().get("/app/staff").text
    assert 'aria-label="Kitchen staff: staff group"' in page and 'aria-label="Kitchen staff: gets alerts"' in page
    assert 'aria-label="No alerts"' in page


def test_sheet_preview_returns_to_its_tab_and_problems_show_at_the_tab():
    site = Site()
    http = site.business_user()
    i = list(site.bot.sheets.tab_headers("sheet-1")).index("Orders")
    page = http.get("/app/sheet").text
    assert f'id="tab-{i}"' in page and f'formaction="/app/sheet#tab-{i}"' in page
    r = http.post("/app/sheet", data={"csrf": csrf(http, "/app/sheet"), "action": "save", "tabs_listed": "1",
                                      f"use{i}": "on", f"own{i}": "on", f"owner{i}": ""})
    card = r.text.split(f'id="tab-{i}"', 1)[1].split("</article>", 1)[0]
    assert 'class="field-error"' in card and "pick which column holds" in card
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_web_ux.py -v`
Expected: the 4 Task 1 tests PASS; the 3 new ones FAIL on their assertions.

- [ ] **Step 3: Pass the Sheet problems to the template**

In `app/pages.py`, in `sheet_page`:
- Change `config, error, preview = dict(business.config), "", None` to:
```python
    config, error, preview, problems = dict(business.config), "", None, []
```
- In the final `return page(...)` call, add `problems=problems,` right after `preview=preview,`.

- [ ] **Step 4: Labels and helper text**

`app/templates/logins.html` — replace the invite form's `<div class="grid">` block (the two inputs and the **Create login** button) with:
```html
  <div class="grid">
    <label>Email <input type="email" name="email" required autocomplete="off"></label>
    <label>Name <small>(optional)</small> <input name="name" autocomplete="off"></label>
  </div>
  <button type="submit" name="action" value="invite">Create login</button>
```

`app/templates/numbers.html` — replace the add form's `<div class="grid">` block with:
```html
  <div class="grid">
    <label>Session name
      <input name="session" placeholder="e.g. sweetbakes-1" value="{{ session }}" required
             aria-describedby="session-help"></label>
    <label>Notes <small>(optional: carrier, SIM cost, renewal date)</small>
      <input name="notes" placeholder="e.g. Jazz SIM, bought 2026-10" value="{{ notes }}"></label>
  </div>
  <small id="session-help">3–32 lowercase letters, digits or dashes.</small>
```

`app/templates/number_link.html` — replace the `<h2>Business</h2>` section's form and the `<h2>Notes</h2>` section's form (keep both headings) so the end of the file reads:
```html
<h2>Business</h2>
<form method="post" action="/admin/numbers/{{ number.session }}/assign">
  <input type="hidden" name="csrf" value="{{ csrf }}">
  <label>Answers for
    <select name="business_id">
      <option value="">(unassigned)</option>
      {% for b in businesses %}<option value="{{ b.id }}"{% if b.id == number.business_id %} selected{% endif %}>{{ b.config.business }}</option>{% endfor %}
    </select></label>
  <button type="submit">Save</button>
</form>
<h2>Notes</h2>
<form method="post" action="/admin/numbers/{{ number.session }}/notes">
  <input type="hidden" name="csrf" value="{{ csrf }}">
  <label>Notes <small>(carrier, SIM cost, renewal date)</small>
    <input name="notes" value="{{ number.notes }}"></label>
  <button type="submit">Save notes</button>
</form>
{% endblock %}
```

`app/templates/admin_new.html`:
- Replace the line starting `<p>First ask the business to share its Google Sheet with` with:
```html
<p>First ask the business to share its Google Sheet, as <em>Editor</em>, with:</p>
<div class="share-row"><code>{{ email or "the client_email in your Google key file" }}</code>
  {% if email %}<button type="button" class="copy-btn" data-copy="{{ email }}">Copy</button>{% endif %}</div>
```
- Replace the web id `<label>` (its two lines) with:
```html
  <label>Web id <small>(optional)</small>
    <input name="id" value="{{ values.id or '' }}" aria-describedby="id-help"></label>
  <small id="id-help">Lowercase letters, digits and dashes, used in this business's addresses. Leave it empty to
    make one from the business name.</small>
```
- Change `<label>Instructions for the bot <textarea` to `<label>Instructions for the bot <small>(optional)</small> <textarea`.

`app/templates/settings.html` — change `<label>Instructions for the bot` to `<label>Instructions for the bot <small>(optional)</small>`.

`app/templates/admin_meta.html` — right after the closing `</div>` of the `<div class="grid">` that holds **Save keys** and **Test connection** (still inside the form), add:
```html
    <small>Test connection checks the <em>saved</em> keys, so press Save keys first.</small>
```

`app/templates/staff.html` — give the radios and checkboxes names:
- In `<input type="radio" name="alert" value=""{% if not config.staff_alert_chat %} checked{% endif %}>`, add ` aria-label="No alerts"` before the final `>`.
- In the staff-group checkbox (`name="staff_chats"`), add ` aria-label="{{ g.name }}: staff group"` before the final `>`.
- In the per-group alert radio (`name="alert" value="{{ g.id }}"`), add ` aria-label="{{ g.name }}: gets alerts"` before the final `>`.

- [ ] **Step 5: The Sheet page**

In `app/templates/sheet.html`:
1. Replace the line starting `<p>Share the Google Sheet with` with:
```html
<p>Share the Google Sheet, as <em>Editor</em>, with:</p>
<div class="share-row"><code>{{ email or "the service account (ask your admin for the address)" }}</code>
  {% if email %}<button type="button" class="copy-btn" data-copy="{{ email }}">Copy</button>{% endif %}</div>
```
2. Replace the admin "Change Sheet" form with:
```html
<form method="post" class="grid sheet-id">
  <input type="hidden" name="csrf" value="{{ csrf }}">
  <label>Sheet id <input name="sheet_id" value="{{ config.sheet_id }}" required></label>
  <button type="submit" name="action" value="sheet_id" class="secondary">Change Sheet</button>
</form>
```
3. In the per-tab loop, change `  <article>` to `  <article id="tab-{{ i }}">`.
4. Change `<input type="checkbox" name="use{{ i }}"` to `<input type="checkbox" class="use-tab" name="use{{ i }}"`.
5. Directly after the card's closing `</header>`, add:
```html
    {% for problem in problems if problem.startswith(tab ~ ":") %}
    <p class="field-error">{{ problem }}</p>
    {% endfor %}
```
6. Put `<div class="tab-options">` on the line before `<p>Customers can:</p>`, and `</div>` on the line after the "What a customer would see" `<button>` (so the preview result stays outside it).
7. Change `<p class="notice error">This tab has contact columns:` to `<p class="notice warn">This tab has contact columns:`.
8. In `<button type="submit" name="action" value="preview:{{ tab }}" class="secondary">`, add ` formaction="{{ base }}/sheet#tab-{{ i }}"` before ` class=`, so the browser comes back to this tab.

Append to `app/static/app.css`:
```css
/* Warnings (not errors), and an error shown next to the thing it is about */
:root {
  --warn-soft: oklch(96.5% 0.045 85);
  --warn-line: oklch(82% 0.1 80);
  --warn-ink: oklch(42% 0.09 65);
}
.notice.warn { background: var(--warn-soft); border-color: var(--warn-line); color: var(--warn-ink); }
.field-error { margin: 0.4rem 0; color: var(--danger); font-weight: 550; }
.field-error::before { content: "⚠ "; }

/* Sheet page: a tab the bot doesn't use keeps its options visible but quiet */
article:has(.use-tab:not(:checked)) .tab-options { opacity: 0.55; }
form.sheet-id { align-items: end; }
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_web_ux.py tests/test_pages_staff_sheet.py tests/test_admin_pages.py tests/test_numbers_pages.py -v`
Expected: PASS (7 in `test_web_ux.py`, and every existing test in the other three files)

Run: `uv run pytest -q && uv run ruff check .`
Expected: all tests pass; `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add app/pages.py app/static/app.css app/templates/logins.html app/templates/numbers.html app/templates/number_link.html app/templates/admin_new.html app/templates/settings.html app/templates/staff.html app/templates/sheet.html app/templates/admin_meta.html tests/test_web_ux.py
git commit -m "fix: visible form labels, helper text, and a Sheet page that keeps your place"
```

### Task 3: The mail sender

**Files:**
- Create: `app/mailer.py`
- Modify: `tests/fakes.py`
- Test: `tests/test_mailer.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `app.mailer.is_email(text: str) -> bool`: one address, `something@something.something`, no spaces, commas, semicolons, angle brackets or quotes, at most 254 characters.
  - `app.mailer.MailError(message: str, kind: str)` with `.kind` in `{"auth", "recipient", "network", "message"}`; `str(error)` is a sentence a person can act on.
  - `app.mailer.Mailer(smtp=smtplib.SMTP, host="smtp.gmail.com", port=587, timeout=30)` with `send(address, app_password, sender_name, to, subject, body) -> None` (spaces are removed from the app password; raises `MailError`).
  - `tests.fakes.FakeMailer` with `.sent: list[dict]` (keys `address`, `app_password`, `sender_name`, `to`, `subject`, `body`) and `.fail: Exception | None` (raised by `send` when set).

- [ ] **Step 1: Write the failing tests**

`tests/test_mailer.py`:
```python
import smtplib
import ssl

import pytest

from app.mailer import Mailer, MailError, is_email


def smtp_factory(error=None, at="send"):
    """A stand-in for smtplib.SMTP that records the conversation and can fail at one step."""
    made = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            self.args, self.calls = (host, port, timeout), []
            made.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self, context=None):
            verified = context is not None and context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
            self.calls.append(("starttls", verified))

        def login(self, user, password):
            self.calls.append(("login", user, password))
            if error is not None and at == "login":
                raise error

        def send_message(self, message):
            self.calls.append(("send", message))
            if error is not None and at == "send":
                raise error

    return FakeSMTP, made


def test_sends_one_plain_text_email_over_verified_starttls():
    smtp, made = smtp_factory()
    Mailer(smtp=smtp).send("shop@gmail.com", "abcd efgh ijkl mnop", "Sweet Bakes", "acc@example.com",
                           "September", "Total: Rs 27,300")
    conn = made[0]
    assert conn.args == ("smtp.gmail.com", 587, 30)
    assert conn.calls[0] == ("starttls", True)
    assert conn.calls[1] == ("login", "shop@gmail.com", "abcdefghijklmnop")
    message = conn.calls[2][1]
    assert message["From"] == "Sweet Bakes <shop@gmail.com>" and message["To"] == "acc@example.com"
    assert message["Subject"] == "September" and message.get_content().strip() == "Total: Rs 27,300"


@pytest.mark.parametrize("error, at, kind, reason", [
    (smtplib.SMTPAuthenticationError(535, b"bad credentials"), "login", "auth", "app password"),
    (smtplib.SMTPRecipientsRefused({"acc@example.com": (550, b"no such user")}), "send", "recipient",
     "refused the address acc@example.com"),
    (TimeoutError("slow"), "login", "network", "couldn't be reached"),
    (smtplib.SMTPServerDisconnected("bye"), "send", "network", "couldn't be reached"),
])
def test_gmail_errors_become_one_readable_reason(error, at, kind, reason):
    smtp, _ = smtp_factory(error, at)
    with pytest.raises(MailError, match=reason) as caught:
        Mailer(smtp=smtp).send("shop@gmail.com", "secretpassword12", "Sweet Bakes", "acc@example.com", "Hi", "Text")
    assert caught.value.kind == kind and "secretpassword12" not in str(caught.value)


def test_a_line_break_in_the_subject_is_refused_not_sent():
    smtp, made = smtp_factory()
    with pytest.raises(MailError) as caught:
        Mailer(smtp=smtp).send("shop@gmail.com", "pw", "Sweet Bakes", "acc@example.com", "Hi\nBcc: x@y.com", "Text")
    assert caught.value.kind == "message" and made == []


@pytest.mark.parametrize("text, ok", [
    ("acc@example.com", True), ("first.last@mail.example.co.uk", True),
    ("acc@example", False), ("not an address", False), ("a@example.com, b@example.com", False),
    ("a@example.com;b@example.com", False), ("<a@example.com>", False), ("x" * 250 + "@example.com", False),
])
def test_is_email_accepts_exactly_one_plain_address(text, ok):
    assert is_email(text) is ok
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_mailer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.mailer'`

- [ ] **Step 3: Implement the sender**

`app/mailer.py`:
```python
"""Sends one plain-text email through Gmail's SMTP server with an app password (standard library only)."""
from __future__ import annotations

import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

GMAIL_HOST, GMAIL_PORT = "smtp.gmail.com", 587
_EMAIL = re.compile(r"[^@\s,;<>\"']+@[^@\s,;<>\"']+\.[^@\s,;<>\"']+")


def is_email(text: str) -> bool:
    """Exactly one plain address like name@example.com: no lists, display names or spaces."""
    return len(text) <= 254 and _EMAIL.fullmatch(text) is not None


class MailError(Exception):
    """Sending failed. The message says why in words a person can act on; `kind` is safe to log."""

    def __init__(self, message: str, kind: str) -> None:
        super().__init__(message)
        self.kind = kind  # auth | recipient | network | message


class Mailer:
    def __init__(self, smtp=smtplib.SMTP, host: str = GMAIL_HOST, port: int = GMAIL_PORT,
                 timeout: float = 30) -> None:
        self._smtp, self._host, self._port, self._timeout = smtp, host, port, timeout

    def send(self, address: str, app_password: str, sender_name: str, to: str, subject: str, body: str) -> None:
        try:
            message = EmailMessage()
            message["From"] = formataddr((sender_name, address))
            message["To"] = to
            message["Subject"] = subject
            message.set_content(body)
        except ValueError:  # e.g. a line break in a header
            raise MailError("The address or subject has characters an email can't carry", "message") from None
        try:
            with self._smtp(self._host, self._port, timeout=self._timeout) as smtp:
                smtp.starttls(context=ssl.create_default_context())  # checks Gmail's certificate
                smtp.login(address, "".join(app_password.split()))
                smtp.send_message(message)
        except smtplib.SMTPAuthenticationError:
            raise MailError("Gmail refused the email address or app password (check the business's Email page)",
                            "auth") from None
        except smtplib.SMTPRecipientsRefused:
            raise MailError(f"Gmail refused the address {to}", "recipient") from None
        except (smtplib.SMTPException, OSError):
            raise MailError("Gmail couldn't be reached right now", "network") from None
```

Append to `tests/fakes.py`:
```python
class FakeMailer:
    """Records emails instead of sending them; set `fail` to a MailError to make sending fail."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.fail: Exception | None = None

    def send(self, address: str, app_password: str, sender_name: str, to: str, subject: str, body: str) -> None:
        if self.fail is not None:
            raise self.fail
        self.sent.append({"address": address, "app_password": app_password, "sender_name": sender_name,
                          "to": to, "subject": subject, "body": body})
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_mailer.py -v`
Expected: PASS (14 passed)

Run: `uv run pytest -q && uv run ruff check .`
Expected: all tests pass; `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add app/mailer.py tests/fakes.py tests/test_mailer.py
git commit -m "feat: send one plain-text email through Gmail with an app password"
```

### Task 4: Email settings in the registry

**Files:**
- Modify: `app/config.py`, `app/registry.py`
- Test: `tests/test_registry.py`

**Interfaces:**
- Consumes: `app.mailer.is_email` (Task 3); `Vault` sealing as for the Meta keys.
- Produces:
  - `Client.email_address: str = ""` and `Client.email_app_password: str` (default `""`, hidden from `repr`). `Registry.clients()` fills both, and leaves both empty when no app password is saved or it can't be opened.
  - `Business.email_address: str`, `Business.has_email_password: bool`, `Business.email_unreadable: bool`.
  - `Registry.save_email(business_id, address, app_password, actor) -> None`: raises `ValueError` ("Enter one Gmail address…", "…16 letters…", "Enter the app password too.", "No such business."); an empty app password keeps the saved one; audits `email.save` with `{"address": …}` plus `"app_password": "(changed)"` when a new one was given.
  - `Registry.remove_email(business_id, actor) -> None`: audits `email.remove` when something was removed.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_registry.py` (add `import pytest`, `from app.registry import Registry` and `from app.vault import Vault` to the imports if they aren't there):
```python
def test_email_settings_are_sealed_audited_without_the_password_and_reach_the_client():
    registry = registry_with_acme()
    registry.save_email("acme", " shop@gmail.com ", "abcd efgh ijkl mnop", actor="t")
    stored = registry.db.one("SELECT * FROM email_accounts WHERE business_id = 'acme'")
    assert "abcd" not in stored["app_password"]
    client = registry.clients()["acme"]
    assert client.email_address == "shop@gmail.com" and client.email_app_password == "abcdefghijklmnop"
    assert "abcdefghijklmnop" not in repr(client)
    business = registry.business("acme")
    assert business.email_address == "shop@gmail.com" and business.has_email_password
    assert not business.email_unreadable
    entry = registry.audit_log("acme")[0]
    assert entry["action"] == "email.save" and "abcd" not in entry["detail"] and "(changed)" in entry["detail"]
    registry.save_email("acme", "orders@gmail.com", "", actor="t")  # empty keeps the saved password
    assert registry.clients()["acme"].email_app_password == "abcdefghijklmnop"
    assert registry.clients()["acme"].email_address == "orders@gmail.com"
    registry.remove_email("acme", actor="t")
    assert registry.clients()["acme"].email_address == ""
    assert registry.audit_log("acme")[0]["action"] == "email.remove"


@pytest.mark.parametrize("address, password, message", [
    ("not-an-email", "abcdefghijklmnop", "Gmail address"),
    ("a@gmail.com, b@gmail.com", "abcdefghijklmnop", "Gmail address"),
    ("shop@gmail.com", "hunter2hunter2", "16 letters"),
    ("shop@gmail.com", "", "app password too"),
])
def test_bad_email_settings_are_refused(address, password, message):
    with pytest.raises(ValueError, match=message):
        registry_with_acme().save_email("acme", address, password, actor="t")


def test_an_unreadable_app_password_switches_email_off():
    registry = registry_with_acme()
    registry.save_email("acme", "shop@gmail.com", "abcdefghijklmnop", actor="t")
    reopened = Registry(registry.db, Vault("another-key"))
    assert reopened.clients()["acme"].email_address == ""
    assert reopened.business("acme").email_unreadable
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_registry.py -v`
Expected: FAIL with `AttributeError: 'Registry' object has no attribute 'save_email'` (and the other two new tests failing likewise)

- [ ] **Step 3: Implement**

In `app/config.py`, add at the end of the `Client` field list (after `meta_verify_token`):
```python
    email_address: str = ""  # the business's Gmail address for staff emails (from the dashboard)
    email_app_password: str = field(default="", repr=False)
```

In `app/registry.py`:
- Add `from app.mailer import is_email` to the `app.` imports (keep them alphabetical).
- Add to the end of `SCHEMA` (before the closing `"""`):
```sql
CREATE TABLE IF NOT EXISTS email_accounts (
  business_id TEXT PRIMARY KEY REFERENCES businesses(id),
  address TEXT NOT NULL,
  app_password TEXT NOT NULL,
  updated_at REAL NOT NULL
);
```
- Replace the `SELECT_BUSINESS = ...` line with:
```python
SELECT_BUSINESS = ("SELECT b.*, n.session, e.address AS email_address, e.app_password AS email_app_password"
                   " FROM businesses b LEFT JOIN numbers n ON n.business_id = b.id"
                   " LEFT JOIN email_accounts e ON e.business_id = b.id")
```
- Add at the end of the `Business` field list (after `keys_unreadable`):
```python
    email_address: str = ""  # the business's Gmail for staff emails, or ""
    has_email_password: bool = False
    email_unreadable: bool = False  # the saved app password can't be opened: SECRET_KEY changed
```
- In `_business`, open the app password and pass the three fields:
```python
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
```
- In `clients()`, open the app password and add the two fields to the `replace(...)` call:
```python
            # no app password, or one that can't be opened, leaves email switched off for this business
            email_password = self._open(row["email_app_password"]) or ""
            out[client.id] = replace(client, meta_access_token=self._open(row["meta_access_token"]) or "",
                                     meta_app_secret=secrets.token_hex(32) if app_secret is None else app_secret,
                                     meta_verify_token=row["meta_verify_token"],
                                     email_address=(row["email_address"] or "") if email_password else "",
                                     email_app_password=email_password)
```
- Add after `set_active`:
```python
    # --- email

    def save_email(self, business_id: str, address: str, app_password: str, actor: str) -> None:
        """The business's Gmail for staff emails; an empty app password keeps the saved one."""
        address = (address or "").strip()
        app_password = "".join((app_password or "").split())
        if not is_email(address):
            raise ValueError("Enter one Gmail address, like sweetbakes@gmail.com.")
        if app_password and not (len(app_password) == 16 and app_password.isalpha()):
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_registry.py -v`
Expected: PASS (every existing test plus 6 new cases)

Run: `uv run pytest -q && uv run ruff check .`
Expected: all tests pass; `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add app/config.py app/registry.py tests/test_registry.py
git commit -m "feat: store each business's Gmail address and sealed app password"
```

### Task 5: The bot sends email for staff, after a preview and YES

**Files:**
- Modify: `app/store.py`, `app/tools.py`, `app/bot.py`, `app/main.py`, `tests/fakes.py`
- Test: `tests/test_bot_email.py` (create), `tests/test_store.py`

**Interfaces:**
- Consumes: `Mailer`, `MailError(kind)`, `is_email`, `FakeMailer` (Task 3); `Client.email_address`, `Client.email_app_password` (Task 4).
- Produces:
  - `Store.put_pending_email(client_id, chat_id, sender_id, email: dict, expires_at)`, `Store.get_pending_email(client_id, chat_id, sender_id, now) -> dict | None`, `Store.drop_pending_email(client_id, chat_id, sender_id)`, `Store.record_email_sent(client_id, at)`, `Store.emails_sent_since(client_id, since) -> int`; `Store.purge_expired_pending(now)` also drops expired pending emails and email counts older than two days.
  - `app.tools.SEND_EMAIL_SPEC`, `MAX_SUBJECT = 200`, `MAX_BODY = 3500`, `email_request(args) -> {"email": {...}} | {"error": str}`, `email_preview(email) -> str`.
  - `Bot(..., clock=time.time, mailer=None)`; `bot.mailer`; `app.bot.EMAIL_DAILY_LIMIT = 50`.
  - `tests.fakes.ScriptedLLM.tools: list[list[str]]` (the tool names offered on each call); `make_bot()` gives the bot a `FakeMailer`.
  - `app.main.build_bot` gives the bot a real `Mailer()`.

- [ ] **Step 1: Write the failing tests**

`tests/test_bot_email.py`:
```python
import logging
from dataclasses import replace

import pytest

from app.bot import EMAIL_DAILY_LIMIT
from app.mailer import MailError
from tests.fakes import call, incoming, make_bot, say, texts

STAFF = "923001111111"  # a staff number of the acme bakery (tests.fakes.make_client)
NOW = 1_790_000_000.0
EMAIL = {"to": "acc@example.com", "subject": "September expenses", "body": "Total: Rs 27,300.\n\nSweet Bakes"}


def email_bot(*replies, **options):
    """The acme bot with its Gmail set up."""
    bot, llm = make_bot(*replies, **options)
    bot.clients["acme"] = replace(bot.clients["acme"], email_address="shop@gmail.com",
                                  email_app_password="abcdefghijklmnop")
    return bot, llm


def test_only_staff_of_a_business_with_email_are_offered_send_email():
    bot, llm = email_bot(say("Hi"), say("Hi"))
    bot.handle(incoming("hi", phone=STAFF))
    bot.handle(incoming("hi"))  # a customer
    assert "send_email" in llm.tools[0] and "send_email" not in llm.tools[1]
    assert "can't send email" in llm.calls[1][0]["content"]
    plain, plain_llm = make_bot(say("Hi"))  # no Gmail set up
    plain.handle(incoming("hi", phone=STAFF))
    assert "send_email" not in plain_llm.tools[0]


def test_staff_email_is_previewed_then_sent_on_yes():
    bot, _ = email_bot(call("send_email", **EMAIL))
    bot.handle(incoming("email the accountant september expenses", phone=STAFF))
    preview = texts(bot.meta)[-1]
    assert "To: acc@example.com" in preview and "Subject: September expenses" in preview
    assert "Total: Rs 27,300." in preview and "Reply YES to send" in preview
    assert bot.mailer.sent == []
    bot.handle(incoming("yes", phone=STAFF))
    assert bot.mailer.sent == [{"address": "shop@gmail.com", "app_password": "abcdefghijklmnop",
                                "sender_name": "Sweet Bakes", "to": "acc@example.com",
                                "subject": "September expenses", "body": EMAIL["body"]}]
    assert texts(bot.meta)[-1] == "✅ Email sent to acc@example.com."


def test_no_cancels_the_email():
    bot, _ = email_bot(call("send_email", **EMAIL))
    bot.handle(incoming("email it", phone=STAFF))
    bot.handle(incoming("no", phone=STAFF))
    assert bot.mailer.sent == [] and texts(bot.meta)[-1] == "Cancelled, nothing was sent."


def test_only_the_staff_member_who_asked_can_confirm():
    bot, _ = email_bot(call("send_email", **EMAIL))
    bot.handle(incoming("@Sara email the accountant", group="staff@g.us", mention=True, phone=STAFF))
    bot.handle(incoming("yes", group="staff@g.us", phone="923009999999"))  # another member of the staff group
    assert bot.mailer.sent == []
    bot.handle(incoming("yes", group="staff@g.us", phone=STAFF))
    assert len(bot.mailer.sent) == 1


def test_a_failed_send_keeps_the_email_for_another_yes():
    bot, _ = email_bot(call("send_email", **EMAIL))
    bot.handle(incoming("email it", phone=STAFF))
    bot.mailer.fail = MailError("Gmail couldn't be reached right now", "network")
    bot.handle(incoming("yes", phone=STAFF))
    assert "Couldn't send the email: Gmail couldn't be reached right now" in texts(bot.meta)[-1]
    bot.mailer.fail = None
    bot.handle(incoming("yes", phone=STAFF))
    assert len(bot.mailer.sent) == 1


def test_an_email_waits_ten_minutes_for_yes():
    now = [NOW]
    bot, _ = email_bot(call("send_email", **EMAIL), say("Hello!"), clock=lambda: now[0])
    bot.handle(incoming("email it", phone=STAFF))
    now[0] += 601
    bot.handle(incoming("yes", phone=STAFF))  # too late: now it's an ordinary message
    assert bot.mailer.sent == [] and texts(bot.meta)[-1] == "Hello!"


@pytest.mark.parametrize("change", [{"to": "a@example.com, b@example.com"}, {"to": "not an address"},
                                    {"subject": "x" * 201}, {"body": ""}, {"body": "x" * 3501}])
def test_bad_emails_go_back_to_the_model_without_a_preview(change):
    bot, llm = email_bot(call("send_email", **{**EMAIL, **change}), say("Which address?"))
    bot.handle(incoming("email it", phone=STAFF))
    assert "error" in llm.calls[1][-1]["content"] and texts(bot.meta)[-1].endswith("Which address?")
    assert bot.store.get_pending_email("acme", f"user-{STAFF}", f"user-{STAFF}", NOW) is None


def test_the_51st_email_in_a_day_is_refused():
    bot, llm = email_bot(call("send_email", **EMAIL), say("That's the limit for today."))
    for _ in range(EMAIL_DAILY_LIMIT):
        bot.store.record_email_sent("acme", NOW - 60)
    bot.handle(incoming("email it", phone=STAFF))
    assert "50 emails" in llm.calls[1][-1]["content"] and bot.mailer.sent == []


def test_a_customer_cant_send_email_even_if_the_model_tries():
    bot, llm = email_bot(call("send_email", **EMAIL), say("I can't send email."))
    bot.handle(incoming("email my order to me"))
    assert "isn't available" in llm.calls[1][-1]["content"] and bot.mailer.sent == []


def test_logs_never_hold_the_email(caplog):
    caplog.set_level(logging.DEBUG)
    bot, _ = email_bot(call("send_email", **EMAIL))
    bot.handle(incoming("email it", phone=STAFF))
    bot.handle(incoming("yes", phone=STAFF))
    assert "email_sent client=acme" in caplog.text
    for secret in ("acc@example.com", "September", "27,300", "abcdefghijklmnop", "shop@gmail.com"):
        assert secret not in caplog.text
```

Append to `tests/test_store.py`:
```python
def test_maintenance_forgets_expired_pending_emails_and_old_email_counts():
    s = Store(":memory:")
    s.put_pending_email("acme", "c", "u", {"to": "a@b.co"}, expires_at=100.0)
    assert s.get_pending_email("acme", "c", "u", now=50.0) == {"to": "a@b.co"}
    assert s.get_pending_email("acme", "c", "u", now=150.0) is None  # expired
    s.record_email_sent("acme", at=0.0)
    s.record_email_sent("acme", at=200_000.0)
    s.purge_expired_pending(now=200_000.0)
    assert s.get_pending_email("acme", "c", "u", now=50.0) is None  # gone from the table
    assert s.emails_sent_since("acme", 0.0) == 1  # counts older than two days are dropped
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_bot_email.py tests/test_store.py -v`
Expected: FAIL with `ImportError: cannot import name 'EMAIL_DAILY_LIMIT' from 'app.bot'` (and `AttributeError: 'Store' object has no attribute 'put_pending_email'`)

- [ ] **Step 3: Store pending emails and the email count**

In `app/store.py`, add to the end of `SCHEMA` (before the closing `"""`):
```sql
CREATE TABLE IF NOT EXISTS pending_emails (
  client_id TEXT NOT NULL,
  chat_id TEXT NOT NULL,
  sender_id TEXT NOT NULL,
  email_json TEXT NOT NULL,
  expires_at REAL NOT NULL,
  PRIMARY KEY (client_id, chat_id, sender_id)
);
CREATE TABLE IF NOT EXISTS emails_sent (
  client_id TEXT NOT NULL,
  at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS emails_sent_by_client ON emails_sent (client_id, at);
```

Replace `purge_expired_pending` with, and add after `drop_pending`:
```python
    def put_pending_email(self, client_id: str, chat_id: str, sender_id: str, email: dict[str, str],
                          expires_at: float) -> None:
        self._write("INSERT OR REPLACE INTO pending_emails VALUES (?, ?, ?, ?, ?)",
                    (client_id, chat_id, sender_id, json.dumps(email, ensure_ascii=False), expires_at))

    def get_pending_email(self, client_id: str, chat_id: str, sender_id: str, now: float) -> dict[str, str] | None:
        rows = self._all("SELECT email_json FROM pending_emails WHERE client_id = ? AND chat_id = ? AND sender_id = ?"
                         " AND expires_at > ?", (client_id, chat_id, sender_id, now))
        return json.loads(rows[0]["email_json"]) if rows else None

    def drop_pending_email(self, client_id: str, chat_id: str, sender_id: str) -> None:
        self._write("DELETE FROM pending_emails WHERE client_id = ? AND chat_id = ? AND sender_id = ?",
                    (client_id, chat_id, sender_id))

    def record_email_sent(self, client_id: str, at: float) -> None:
        self._write("INSERT INTO emails_sent (client_id, at) VALUES (?, ?)", (client_id, at))

    def emails_sent_since(self, client_id: str, since: float) -> int:
        return self._all("SELECT COUNT(*) AS n FROM emails_sent WHERE client_id = ? AND at >= ?",
                         (client_id, since))[0]["n"]

    def purge_expired_pending(self, now: float) -> int:
        """Drop pending rows and emails nobody confirmed, and email counts older than two days."""
        self._write("DELETE FROM pending_emails WHERE expires_at <= ?", (now,))
        self._write("DELETE FROM emails_sent WHERE at < ?", (now - 2 * 86_400,))
        return self._write("DELETE FROM pending_writes WHERE expires_at <= ?", (now,))
```

- [ ] **Step 4: The tool and its preview**

In `app/tools.py`, add `from app.mailer import is_email` to the imports, and add after the `TOOL_SPECS` list:
```python
# Offered only to staff of a business with email set up (see Bot._tools).
SEND_EMAIL_SPEC: dict = {"type": "function", "function": {
    "name": "send_email",
    "description": "Email one person for a staff member, from the business's Gmail. Write the whole email. The "
                   "system shows it to the staff member and sends it only after they reply YES; never say it was "
                   "sent yourself.",
    "parameters": {"type": "object", "properties": {
        "to": {"type": "string", "description": "One email address, exactly as the staff member gave it."},
        "subject": {"type": "string", "description": "A short subject line."},
        "body": {"type": "string", "description": "The email text, plain text, signed with the business name."},
    }, "required": ["to", "subject", "body"]},
}}
MAX_SUBJECT = 200
MAX_BODY = 3500  # the preview must fit in one WhatsApp message (4096 characters)


def email_request(args: dict) -> dict:
    """Check send_email's arguments: {"email": {...}} ready to preview, or {"error": ...} for the model."""
    to = str(args.get("to") or "").strip()
    subject = " ".join(str(args.get("subject") or "").split())  # one line: no line breaks in a header
    body = str(args.get("body") or "").strip()
    if not is_email(to):
        return {"error": "That isn't one email address. Ask the staff member for a single address like "
                         "name@example.com."}
    if not subject or len(subject) > MAX_SUBJECT:
        return {"error": f"The subject must be 1 to {MAX_SUBJECT} characters."}
    if not body or len(body) > MAX_BODY:
        return {"error": f"The email text must be 1 to {MAX_BODY} characters."}
    return {"email": {"to": to, "subject": subject, "body": body}}


def email_preview(email: dict[str, str]) -> str:
    return (f"📧 Send this email?\nTo: {email['to']}\nSubject: {email['subject']}\n\n{email['body']}\n\n"
            "Reply YES to send or NO to cancel.")
```

- [ ] **Step 5: The bot**

In `app/bot.py`:
1. Imports: add `from app.mailer import MailError`, and add `SEND_EMAIL_SPEC, email_preview, email_request` to the `from app.tools import (...)` list (keep it alphabetical: `SEND_EMAIL_SPEC, TOOL_SPECS, TOTAL_ARGS, Caller, build_row, describe_tabs, email_preview, email_request, lookup_rows, proposal_text, saved_text, total_rows`).
2. Constants, after `PENDING_TTL = ...`:
```python
EMAIL_DAILY_LIMIT = 50  # emails per business per rolling 24h (Gmail allows about 500)
EMAIL_LIMIT_TEXT = f"This business has sent {EMAIL_DAILY_LIMIT} emails in the last 24 hours. Try again later."
```
3. `Bot.__init__`: change the signature to `def __init__(self, store, sheets, llm, meta, waha, clients: dict[str, Client], log_key: str = "", clock=time.time, mailer=None) -> None:` and add `self.mailer = mailer  # sends staff emails; None switches email off` after `self.clock = clock`.
4. Replace the whole `_answer_pending` method with:
```python
    def _answer_pending(self, client: Client, m: Incoming, now: float) -> bool:
        """YES/NO answers this sender's pending email or proposed row; only the person who asked can answer."""
        word = normalize(m.text)
        if word not in YES and word not in NO:
            return False
        email = self.store.get_pending_email(client.id, m.chat_id, m.sender_id, now)
        pending = None if email else self.store.get_pending(client.id, m.chat_id, m.sender_id, now)
        if email is None and pending is None:
            return False
        if not self._reply_allowed(client, m, now):
            return True  # can't confirm it, so don't act on it yet
        if email is not None:
            self._answer_email(client, m, word in YES, email, now)
            return True
        if word in NO:
            self.store.drop_pending(client.id, m.chat_id, m.sender_id)
            self._send(client, m, "Cancelled, nothing was saved.")
            return True
        tab, row = pending
        try:
            self.sheets.append(client.sheet_id, tab, row)
        except Exception:
            log.exception("append_failed client=%s tab=%s", client.id, tab)
            self._send(client, m, "Couldn't save that, reply YES to try again.")
            return True
        self.store.drop_pending(client.id, m.chat_id, m.sender_id)
        self._send(client, m, f"✅ Added to {tab}.")
        return True

    def _answer_email(self, client: Client, m: Incoming, yes: bool, email: dict[str, str], now: float) -> None:
        """Send the previewed email on YES; if Gmail fails, keep it so another YES can retry."""
        if not yes:
            self.store.drop_pending_email(client.id, m.chat_id, m.sender_id)
            self._send(client, m, "Cancelled, nothing was sent.")
            return
        if not self._can_email(client, self._caller(client, m)):
            self.store.drop_pending_email(client.id, m.chat_id, m.sender_id)
            self._send(client, m, "Email isn't set up for this business any more, so nothing was sent.")
            return
        if self.store.emails_sent_since(client.id, now - DAY) >= EMAIL_DAILY_LIMIT:
            self._send(client, m, EMAIL_LIMIT_TEXT)
            return
        try:
            self.mailer.send(client.email_address, client.email_app_password, client.business,
                             email["to"], email["subject"], email["body"])
        except MailError as e:
            log.warning("email_failed client=%s error=%s", client.id, e.kind)  # never the address or text
            self._send(client, m, f"Couldn't send the email: {e}. Fix it and reply YES to try again.")
            return
        self.store.record_email_sent(client.id, now)
        self.store.drop_pending_email(client.id, m.chat_id, m.sender_id)
        log.info("email_sent client=%s", client.id)
        self._send(client, m, f"✅ Email sent to {email['to']}.")
```
5. Add after `_caller`:
```python
    def _can_email(self, client: Client, caller: Caller) -> bool:
        """Only staff, and only when the business has its Gmail set up."""
        return (caller.role == "staff" and self.mailer is not None
                and bool(client.email_address and client.email_app_password))

    def _tools(self, client: Client, caller: Caller) -> list[dict]:
        return [*TOOL_SPECS, SEND_EMAIL_SPEC] if self._can_email(client, caller) else TOOL_SPECS

    def _propose_email(self, client: Client, m: Incoming, caller: Caller, args: dict, now: float) -> dict | Final:
        """Check the email and show it; it is only sent when the same staff member replies YES."""
        if not self._can_email(client, caller):
            return {"error": "Sending email isn't available here."}
        if self.store.emails_sent_since(client.id, now - DAY) >= EMAIL_DAILY_LIMIT:
            return {"error": EMAIL_LIMIT_TEXT}
        result = email_request(args)
        if "error" in result:
            return result
        self.store.put_pending_email(client.id, m.chat_id, m.sender_id, result["email"], now + PENDING_TTL)
        return Final(email_preview(result["email"]))
```
6. In `_think`: add `tools = self._tools(client, caller)` right before `for _ in range(MAX_MODEL_CALLS):`; change `reply = self.llm.complete(messages, TOOL_SPECS)` to `reply = self.llm.complete(messages, tools)`; and change
```python
                    if caller.role != "staff":
                        break  # one proposal per customer turn: a second would replace the pending one
```
to
```python
                    if caller.role != "staff" or tool_call.name == "send_email":
                        break  # one proposal per customer turn, one email preview per turn
```
7. In `_run_tool`, make this the first branch inside the `try:`:
```python
            if name == "send_email":
                return self._propose_email(client, m, caller, args, now)
```
8. In `_system_prompt`, right before `return (`, add:
```python
        if self._can_email(client, caller):
            email_rule = ("- To email someone for a staff member, call send_email with the whole email. Never say "
                          "an email was sent; the system shows it and asks them to reply YES.\n")
            if self.store.get_pending_email(client.id, m.chat_id, m.sender_id, now):
                email_rule += ("- This staff member has an email waiting for their YES or NO, so don't ask other "
                               "yes/no questions; to change it, call send_email again with the whole email.\n")
        else:
            email_rule = "- You can't send email from this chat; if asked, say so.\n"
```
and in the returned string, add the line `f"{email_rule}"` right after `f"{pending_rule}"`.

In `app/main.py`: add `from app.mailer import Mailer` to the `app.` imports, and in `build_bot` add `mailer=Mailer(),` after `log_key=settings.log_hash_key,`.

In `tests/fakes.py`:
- In `ScriptedLLM.__init__`, add `self.tools: list[list[str]] = []  # the tool names offered on each call`; in `ScriptedLLM.complete`, add as its first line `self.tools.append([t["function"]["name"] for t in tools])`.
- In `make_bot`, pass the mailer: `Bot(Store(":memory:"), bakery_sheets(), llm, FakeMeta(), FakeWaha(), {client.id: client}, clock=clock, mailer=FakeMailer())`. (`FakeMailer` is defined further down the file; that is fine because `make_bot` only runs when called.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_bot_email.py tests/test_store.py tests/test_bot.py tests/test_bot_edges.py -v`
Expected: PASS (14 in `test_bot_email.py`, and every existing test in the other files)

Run: `uv run pytest -q && uv run ruff check .`
Expected: all tests pass; `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add app/store.py app/tools.py app/bot.py app/main.py tests/fakes.py tests/test_bot_email.py tests/test_store.py
git commit -m "feat: staff can ask the bot to email someone, after a preview and YES"
```

### Task 6: The Email page, its tab, and the docs

**Files:**
- Create: `app/templates/email.html`
- Modify: `app/pages.py`, `app/web.py`, `app/templates/base.html`, `docs/setup-guide.md`, `README.md`, `docs/superpowers/specs/2026-09-30-email-sending-design.md`
- Test: `tests/test_pages_email.py` (create)

**Interfaces:**
- Consumes: `screen`, `page`, `Scope` (pages); `Registry.save_email`, `remove_email`, `clients(include_paused=True)` (Task 4); `bot.mailer.send`, `MailError` (Tasks 3, 5); Task 1's `.lede`, `.danger-zone`, `button.danger`, `data-confirm`.
- Produces: `GET/POST /app/email` and `/admin/b/{id}/email` (actions `save`, `test`, `remove`); `OK_MESSAGES["email_removed"]`; an **Email** tab in the business navigation.

- [ ] **Step 1: Write the failing tests**

`tests/test_pages_email.py`:
```python
from app.mailer import MailError
from tests.fakes import acme_config
from tests.webkit import Site, csrf

APP_PASSWORD = "abcd efgh ijkl mnop"


def test_a_business_sets_up_email_and_the_password_is_never_shown():
    site = Site()
    http = site.business_user()
    r = http.post("/app/email", data={"csrf": csrf(http, "/app/email"), "action": "save",
                                      "address": "shop@gmail.com", "app_password": APP_PASSWORD})
    assert "Saved." in r.text and "abcd" not in r.text and "abcdefghijklmnop" not in r.text
    client = site.bot.clients["acme"]
    assert client.email_address == "shop@gmail.com" and client.email_app_password == "abcdefghijklmnop"
    assert 'value="shop@gmail.com"' in r.text and "Send a test email" in r.text


def test_the_test_button_sends_to_the_gmail_address_and_shows_gmails_answer():
    site = Site()
    site.registry.save_email("acme", "shop@gmail.com", APP_PASSWORD, actor="t")
    admin = site.admin()
    token = csrf(admin, "/admin/b/acme/email")
    ok = admin.post("/admin/b/acme/email", data={"csrf": token, "action": "test"}).text
    assert "Check the inbox of shop@gmail.com" in ok and site.bot.mailer.sent[0]["to"] == "shop@gmail.com"
    site.bot.mailer.fail = MailError("Gmail refused the email address or app password (check the business's "
                                     "Email page)", "auth")
    bad = admin.post("/admin/b/acme/email", data={"csrf": token, "action": "test"}).text
    assert "Gmail refused the email address or app password" in bad


def test_bad_settings_are_refused_and_remove_switches_email_off():
    site = Site()
    http = site.business_user()
    token = csrf(http, "/app/email")
    bad = http.post("/app/email", data={"csrf": token, "action": "save", "address": "shop@gmail.com",
                                        "app_password": "hunter2hunter2"}).text
    assert "16 letters" in bad and site.bot.clients["acme"].email_address == ""
    http.post("/app/email", data={"csrf": token, "action": "save", "address": "shop@gmail.com",
                                  "app_password": APP_PASSWORD})
    assert 'data-confirm="Remove email for Sweet Bakes?' in http.get("/app/email").text
    http.post("/app/email", data={"csrf": token, "action": "remove"})
    assert site.bot.clients["acme"].email_address == ""
    assert [e["action"] for e in site.registry.audit_log("acme")][:2] == ["email.remove", "email.save"]


def test_email_pages_stay_inside_the_business_and_need_the_form_token():
    site = Site()
    site.registry.create_business("other", {**acme_config(), "business": "Other Co"}, actor="t")
    http = site.business_user()
    assert http.get("/admin/b/other/email").status_code == 403
    assert http.post("/app/email", data={"action": "remove"}).status_code == 403  # no form token
    assert 'href="/app/email"' in http.get("/app").text  # the tab is in the business navigation
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_pages_email.py -v`
Expected: FAIL (`/app/email` doesn't exist yet: 404s and failed asserts)

- [ ] **Step 3: The screen**

In `app/pages.py`, add `from app.mailer import MailError` to the `app.` imports, and add at the end of the file:
```python
@screen("/email", ("GET", "POST"))
def email_page(request: Request, scope: Scope, form: Form | None) -> Response:
    """The business's Gmail for staff emails: save it, remove it, or send a test email to itself."""
    state, business = request.app.state, scope.business
    error, notice, address = "", "", business.email_address
    if form is not None:
        action, actor = form.get("action"), str(scope.session.user.id)
        if action == "test":
            client = state.registry.clients(include_paused=True).get(business.id)
            if client is None or not client.email_address:
                error = "Save the Gmail address and app password first."
            else:
                try:
                    state.bot.mailer.send(client.email_address, client.email_app_password, client.business,
                                          client.email_address, "Email is set up",
                                          f"Email is set up for {client.business}. Staff can now ask the WhatsApp "
                                          "assistant to send emails.")
                except MailError as e:
                    error = f"The test email wasn't sent: {e}."
                else:
                    notice = f"Sent. Check the inbox of {client.email_address}."
        else:
            address = form.get("address")
            try:
                if action == "remove":
                    state.registry.remove_email(business.id, actor=actor)
                else:
                    state.registry.save_email(business.id, address, form.raw("app_password"), actor=actor)
            except ValueError as e:
                error = str(e)
            else:
                state.reload()
                return redirect(f"{scope.base}/email?ok={'email_removed' if action == 'remove' else 'saved'}")
    return page(request, scope, "email.html", title="Email", error=error, notice=notice, address=address)
```

In `app/web.py`, add to `OK_MESSAGES`:
```python
    "email_removed": "Email removed: the bot no longer sends email for this business.",
```

In `app/templates/base.html`, in the business tab list, add after the `Chats` item:
```html
    <li><a href="{{ base }}/email">Email</a></li>
```

`app/templates/email.html`:
```html
{% extends "base.html" %}
{% block content %}
<h1>Email</h1>
<p class="muted lede">Staff can ask the assistant in WhatsApp to send an email, for example "email this month's
  expenses to our accountant". It shows the email first and sends it from this Gmail account only after they reply
  YES. Customers can't send email.</p>
{% if business.email_unreadable %}<p class="notice error">The saved app password can't be read (was SECRET_KEY changed?). Enter it again.</p>{% endif %}
{% if notice %}<p class="notice ok" role="status">{{ notice }}</p>{% endif %}

<section class="setup-phase">
  <header class="phase-head"><span class="phase-tag">Gmail</span><h2>Connect the business's Gmail</h2></header>
  <ol class="steps">
    <li>
      <div class="step-body"><strong>Turn on 2-Step Verification</strong>
        <p>In the Gmail account: Google Account → Security → 2-Step Verification. App passwords need it.</p></div>
    </li>
    <li>
      <div class="step-body"><strong>Create an app password</strong>
        <p>Google Account → Security → <em>App passwords</em>. Name it "WhatsApp assistant" and copy the 16 letters
          Google shows. It is not the normal Gmail password.</p></div>
    </li>
    <li>
      <div class="step-body"><strong>Paste both here and save</strong>
        <p>Then press <em>Send a test email</em>: it goes to this Gmail address.</p></div>
    </li>
  </ol>
  <form method="post">
    <input type="hidden" name="csrf" value="{{ csrf }}">
    <label>Gmail address <input type="email" name="address" value="{{ address }}" required autocomplete="off"></label>
    <label>App password {% if business.has_email_password %}<small>(saved; leave empty to keep it)</small>{% endif %}
      <input type="password" name="app_password" autocomplete="new-password" aria-describedby="app-password-help"
             {%- if not business.has_email_password %} required{% endif %}></label>
    <small id="app-password-help">The 16 letters Google shows, with or without the spaces.</small>
    <div class="grid">
      <button type="submit" name="action" value="save">Save</button>
      {% if business.email_address and business.has_email_password %}
      <button type="submit" name="action" value="test" class="secondary" formnovalidate>Send a test email</button>
      {% endif %}
    </div>
  </form>
</section>

{% if business.email_address %}
<section class="danger-zone">
  <h2>Remove email</h2>
  <p class="muted">The assistant stops offering to send email for this business. Nothing else changes.</p>
  <form method="post">
    <input type="hidden" name="csrf" value="{{ csrf }}">
    <button type="submit" name="action" value="remove" class="danger"
            data-confirm="Remove email for {{ business.config.business }}? Staff can't send email from WhatsApp after this.">Remove email</button>
  </form>
</section>
{% endif %}
{% endblock %}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_pages_email.py tests/test_web_ux.py -v`
Expected: PASS (4 in `test_pages_email.py`; the 7 in `test_web_ux.py` still pass, including the no-inline-styles check on the new template)

- [ ] **Step 5: The docs**

In `docs/superpowers/specs/2026-09-30-email-sending-design.md`:
- In §5.2, change `` - `body`: 1–5,000 characters after trimming. `` to `` - `body`: 1–3,500 characters after trimming, so the preview fits in one WhatsApp message (4,096 characters). ``
- In §8, change `Bad address, several addresses, too-long subject or text are refused before any preview.` to `Bad address, several addresses, a subject over 200 or text over 3,500 characters are refused before any preview.`

In `README.md`, in the bullet list at the top (after the `- **Voice notes** are transcribed.` line), add:
```markdown
- **Email:** staff can ask the bot to email someone from the business's Gmail; it shows the email and sends it only after they reply YES (set up on the business's **Email** page).
```

In `docs/setup-guide.md`:
1. In Part K, add this subsection right before the line `### The Sheet page's safety checks`:
```markdown
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
```
2. In the Day-to-Day Tasks part, after the bullet that starts `- **Reset a login or remove someone's access:**`, add:
```markdown
- **Let staff send email:** Part K, "Let staff send email (optional)".
```
3. In the Troubleshooting part, under **Dashboard problems:**, add at the end:
```markdown
- **"Gmail refused the email address or app password".** The app password is wrong or was deleted, or 2-Step
  Verification was turned off. Make a new app password (Part K, "Let staff send email") and save it on the
  business's **Email** page. A Google Workspace account whose admin has turned app passwords off can't use this.
```
4. In the Glossary part, add after the `` - **`SECRET_KEY`:** `` bullet:
```markdown
- **App password:** a 16-letter password Google creates for one app, so it can use a Gmail account without the
  account's real password. It needs 2-Step Verification, and you can delete it any time in the Google account.
```

- [ ] **Step 6: Run everything**

Run: `uv run pytest -q && uv run ruff check .`
Expected: all tests pass; `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add app/pages.py app/web.py app/templates/base.html app/templates/email.html tests/test_pages_email.py docs/setup-guide.md README.md docs/superpowers/specs/2026-09-30-email-sending-design.md
git commit -m "feat: Email page for the business's Gmail, with a test button, and docs"
```

- [ ] **Step 8: Owner checkpoint: a real email**

On the server, after `git pull`, `docker compose up -d --build` and `docker compose restart caddy`: set up a real Gmail app password on a test business's **Email** page, press **Send a test email**, then from a staff phone ask the bot to email yourself and reply YES. This is the first real check against Gmail.
