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
from app.config import client_from_dict, digits
from app.mailer import MailError
from app.registry import Business
from app.sheet_rules import sensitive_columns, tab_problems
from app.sheets import service_account_email, sheet_error
from app.tools import Caller, lookup_rows
from app.web import Form, admin_only, business_only, redirect, render, route
from app.whatsapp import SendError

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
                   "personality": form.get("personality"), "instructions": form.get("instructions"), "timezone": form.get("timezone"),
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
        # only when this request could itself read the groups: WAHA down (now, or already at page load) keeps the saved ones
        if form.has("groups_listed") and not groups_error:
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
    config, error, preview, problems = dict(business.config), "", None, []
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
            knowledge = form.get("knowledge_tab")
            handoff = form.get("handoff_tab")
            # only a tab this request read: the bot reads a missing Knowledge tab as empty, which fails safe
            config.update(tabs=tabs, knowledge_tab=knowledge if knowledge in sheet_tabs else "Knowledge",
                          handoff_tab=handoff if handoff in sheet_tabs else "Handoffs")
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
                sheet_tabs=sheet_tabs, sheet_problem=sheet_problem, error=error, preview=preview, problems=problems,
                sensitive={tab: sensitive_columns(headers) for tab, headers in sheet_tabs.items()})


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
