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
from app.registry import Business
from app.web import Form, admin_only, business_only, redirect, render, route

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
                   "instructions": form.get("instructions"), "timezone": form.get("timezone"),
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
