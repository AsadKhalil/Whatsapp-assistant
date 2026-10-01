"""Admin-only screens: every business at a glance, adding a business, a business's official number, group number,
logins, pause and audit log, and the list of admins."""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.auth import AuthError, Session
from app.pages import TIMEZONES, Scope, admin_scope, month_start, page
from app.sheets import service_account_email, sheet_error
from app.web import Form, admin_only, public_url, redirect, render, route
from app.whatsapp import SendError

router = APIRouter()
NEW_FIELDS = ("id", "business", "bot_name", "timezone", "sheet_id", "instructions")


@route(router, "/admin", admin_only)
def overview(request: Request, sess: Session, form: Form | None) -> Response:
    state = request.app.state
    rows = []
    for business in state.registry.businesses():
        timezone = business.config.get("timezone") or "UTC"
        rows.append({"b": business,
                     "group": state.bot.waha.status(business.number) if business.number else "not linked",
                     "replies": state.bot.store.replies_since(business.id, month_start(state.bot.clock(), timezone))})
    return render(request, "admin_overview.html", sess, title="Businesses", rows=rows,
                  robot_email=service_account_email(state.settings.google_service_account_file))


@route(router, "/admin/new", admin_only, ("GET", "POST"))
def new_business(request: Request, sess: Session, form: Form | None) -> Response:
    state = request.app.state
    email = service_account_email(state.settings.google_service_account_file)
    values, error, sheet_tabs = {"timezone": "Asia/Karachi"}, "", None
    if form is not None:
        values = {key: form.get(key) for key in NEW_FIELDS}
        values["id"] = values["id"] or "-".join(re.findall(r"[a-z0-9]+", values["business"].lower()))[:32].strip("-")
        if form.get("action") == "check":
            try:
                sheet_tabs = state.bot.sheets.tab_headers(values["sheet_id"])
            except Exception as e:
                error = sheet_error(e, email)
        else:
            config = {key: values[key] for key in NEW_FIELDS if key != "id"}
            config.update(knowledge_tab="Knowledge", handoff_tab="Handoffs", tabs={})
            try:
                state.registry.create_business(values["id"], config, actor=str(sess.user.id))
            except ValueError as e:
                error = str(e)
            else:
                state.reload()
                return redirect(f"/admin/b/{values['id']}?ok=created")
    return render(request, "admin_new.html", sess, title="Add a business", values=values, error=error, email=email,
                  sheet_tabs=sheet_tabs, timezones=TIMEZONES)


@route(router, "/admin/b/{business_id}/meta", admin_scope, ("GET", "POST"))
def meta_page(request: Request, scope: Scope, form: Form | None) -> Response:
    state, business = request.app.state, scope.business
    error, test = "", None
    if form is not None and form.get("action") == "test":
        client = state.bot.clients.get(business.id)
        if client is None:
            error = "Resume the business before testing it."
        elif not client.meta_phone_number_id or not client.meta_access_token:
            error = "Save the phone number ID and access token first."
        else:
            try:
                test = state.bot.meta.number_info(client.meta_phone_number_id, token=client.meta_access_token)
            except SendError as e:
                error = f"Meta refused: {e}"
    elif form is not None:
        try:
            state.registry.save_meta(business.id, form.get("phone_number_id"), form.raw("access_token").strip(),
                                     form.raw("app_secret").strip(), actor=str(scope.session.user.id))
        except ValueError as e:
            error = str(e)
        else:
            state.reload()
            return redirect(f"{scope.base}/meta?ok=saved")
    return page(request, scope, "admin_meta.html", title="Official number", error=error, test=test,
                webhook=f"{public_url(request)}/webhooks/meta/{business.id}")


@route(router, "/admin/b/{business_id}/number", admin_scope, ("GET", "POST"))
def number_page(request: Request, scope: Scope, form: Form | None) -> Response:
    state, business = request.app.state, scope.business
    free = [n for n in state.registry.numbers() if n.business_id in (None, business.id)]
    error = ""
    if form is not None:
        session, actor = form.get("session"), str(scope.session.user.id)
        try:
            if session and session not in {n.session for n in free}:
                raise ValueError("That number belongs to another business; unassign it there first.")
            if session:
                state.registry.assign_number(session, business.id, actor=actor)
            elif business.number:
                state.registry.assign_number(business.number, None, actor=actor)
        except ValueError as e:
            error = str(e)
        else:
            state.reload()
            return redirect(f"{scope.base}/number?ok=assigned")
    return page(request, scope, "admin_number.html", title="Group number", numbers=free, error=error)


def manage_logins(request: Request, sess: Session, form: Form | None, business_id: str | None) -> dict:
    """Invite / new link / disable / enable, for one business's logins, or for the admins when business_id is None."""
    state, role = request.app.state, "business" if business_id else "admin"
    ctx = {"error": "", "link": "", "link_email": ""}
    if form is not None:
        action, actor = form.get("action"), str(sess.user.id)
        try:
            if action == "invite":
                token = state.auth.invite(form.get("email"), form.get("name"), role, business_id)
                ctx.update(link=f"{public_url(request)}/invite/{token}", link_email=form.get("email"))
                state.registry.audit(actor, business_id, "user.invite", {"email": form.get("email")})
            else:
                user_id = form.get("user_id")
                user = state.auth.user(int(user_id)) if user_id.isdigit() else None
                if user is None or user.role != role or user.business_id != business_id:
                    raise HTTPException(404, "No such login here.")
                if action == "link":
                    token = state.auth.new_link(user.id)
                    ctx.update(link=f"{public_url(request)}/invite/{token}", link_email=user.email)
                elif action in ("disable", "enable"):
                    if user.id == sess.user.id:
                        raise AuthError("You can't disable your own login.")
                    state.auth.set_disabled(user.id, action == "disable")
                else:
                    raise AuthError("Unknown action.")
                state.registry.audit(actor, business_id, f"user.{action}", {"email": user.email})
        except AuthError as e:
            ctx["error"] = str(e)
    users = state.auth.users(business_id=business_id, role=role) if business_id else state.auth.users(role=role)
    return {**ctx, "users": users, "self_id": sess.user.id}


@route(router, "/admin/b/{business_id}/logins", admin_scope, ("GET", "POST"))
def logins_page(request: Request, scope: Scope, form: Form | None) -> Response:
    ctx = manage_logins(request, scope.session, form, scope.business.id)
    return page(request, scope, "logins.html", title="Logins", **ctx)


@route(router, "/admin/admins", admin_only, ("GET", "POST"))
def admins_page(request: Request, sess: Session, form: Form | None) -> Response:
    return render(request, "logins.html", sess, title="Admins", **manage_logins(request, sess, form, None))


@route(router, "/admin/b/{business_id}/pause", admin_scope, ("POST",))
def pause(request: Request, scope: Scope, form: Form | None) -> Response:
    active = form.get("active") == "1"
    request.app.state.registry.set_active(scope.business.id, active, actor=str(scope.session.user.id))
    request.app.state.reload()
    return redirect(f"{scope.base}?ok={'resumed' if active else 'paused'}")


@route(router, "/admin/b/{business_id}/audit", admin_scope)
def audit_page(request: Request, scope: Scope, form: Form | None) -> Response:
    state = request.app.state
    actors = {str(user.id): user.email for user in state.auth.users()}
    return page(request, scope, "admin_audit.html", title="Audit log", actors=actors,
                entries=state.registry.audit_log(scope.business.id))
