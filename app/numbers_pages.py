"""The purchased-number inventory: add a number, link it by QR code, relink, log out, assign, notes, delete."""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.auth import Session
from app.registry import Number
from app.web import Form, admin_only, redirect, render, route
from app.whatsapp import SendError, session_phone

log = logging.getLogger("numbers")
router = APIRouter()
LIVE = ("SCAN_QR_CODE", "STARTING")  # statuses worth refreshing the page for


def _number(request: Request) -> Number:
    number = request.app.state.registry.number(request.path_params["session"])
    if number is None:
        raise HTTPException(404, "No such number.")
    return number


def _link_page(request: Request, sess: Session, number: Number, error: str = "") -> Response:
    """The number's status, with the QR code while WhatsApp waits for a scan."""
    state = request.app.state
    try:
        info = state.bot.waha.session_info(number.session)
        status = str(info.get("status", "UNKNOWN"))
    except SendError as e:
        info, status = {}, "NOT CREATED" if "404" in str(e) else "UNREACHABLE"
    phone = session_phone(info)
    if status == "WORKING" and phone and phone != number.phone:
        state.registry.set_number_phone(number.session, phone)
        number = state.registry.number(number.session)
    # note: keyword must not be "status" -- render()'s own `status` parameter is the HTTP status code.
    return render(request, "number_link.html", sess, title=number.session, number=number, waha_status=status,
                  error=error, businesses=state.registry.businesses(), now=int(time.time()),
                  refresh=3 if status in LIVE else 0)


@route(router, "/admin/numbers", admin_only, ("GET", "POST"))
def numbers_page(request: Request, sess: Session, form: Form | None) -> Response:
    state = request.app.state
    error, values = "", {"session": "", "notes": ""}
    if form is not None:
        values = {"session": form.get("session"), "notes": form.get("notes")}
        try:
            state.registry.add_number(values["session"], values["notes"], actor=str(sess.user.id))
        except ValueError as e:
            error = str(e)
        else:
            try:
                state.bot.waha.create_session(values["session"], state.settings.waha_webhook_url,
                                              state.settings.waha_webhook_secret)
            except SendError as e:
                error = f"Saved {values['session']}, but WAHA couldn't create it ({e}). Open it and press Relink."
            else:
                return redirect(f"/admin/numbers/{values['session']}")
    rows = [{"n": n, "status": state.bot.waha.status(n.session)} for n in state.registry.numbers()]
    names = {b.id: b.config["business"] for b in state.registry.businesses()}
    return render(request, "numbers.html", sess, title="Numbers", rows=rows, names=names, error=error, **values)


@route(router, "/admin/numbers/{session}", admin_only)
def link_page(request: Request, sess: Session, form: Form | None) -> Response:
    return _link_page(request, sess, _number(request))


@route(router, "/admin/numbers/{session}/qr.png", admin_only)
def qr_image(request: Request, sess: Session, form: Form | None) -> Response:
    number = _number(request)
    try:
        png = request.app.state.bot.waha.qr_png(number.session)
    except SendError:
        return Response(status_code=502)
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


@route(router, "/admin/numbers/{session}/relink", admin_only, ("POST",))
def relink(request: Request, sess: Session, form: Form | None) -> Response:
    state, number = request.app.state, _number(request)
    waha = state.bot.waha
    try:
        try:
            status = waha.session_info(number.session).get("status")
        except SendError as e:
            if "404" not in str(e):
                raise
            waha.create_session(number.session, state.settings.waha_webhook_url, state.settings.waha_webhook_secret)
        else:
            if status in ("STOPPED", "FAILED"):
                waha.start(number.session)
    except SendError as e:
        return _link_page(request, sess, number, error=f"WAHA said: {e}")
    return redirect(f"/admin/numbers/{number.session}")


@route(router, "/admin/numbers/{session}/logout", admin_only, ("POST",))
def logout_number(request: Request, sess: Session, form: Form | None) -> Response:
    state, number = request.app.state, _number(request)
    try:
        state.bot.waha.logout(number.session)
    except SendError as e:
        return _link_page(request, sess, number, error=f"WAHA said: {e}")
    state.registry.audit(str(sess.user.id), number.business_id, "number.logout", {"session": number.session})
    return redirect(f"/admin/numbers/{number.session}")


@route(router, "/admin/numbers/{session}/assign", admin_only, ("POST",))
def assign(request: Request, sess: Session, form: Form | None) -> Response:
    state, number = request.app.state, _number(request)
    try:
        state.registry.assign_number(number.session, form.get("business_id") or None, actor=str(sess.user.id))
    except ValueError as e:
        return _link_page(request, sess, number, error=str(e))
    state.reload()
    return redirect(f"/admin/numbers/{number.session}?ok=assigned")


@route(router, "/admin/numbers/{session}/notes", admin_only, ("POST",))
def notes(request: Request, sess: Session, form: Form | None) -> Response:
    number = _number(request)
    request.app.state.registry.save_number_notes(number.session, form.get("notes"), actor=str(sess.user.id))
    return redirect(f"/admin/numbers/{number.session}?ok=saved")


@route(router, "/admin/numbers/{session}/delete", admin_only, ("POST",))
def delete(request: Request, sess: Session, form: Form | None) -> Response:
    state, number = request.app.state, _number(request)
    try:
        state.registry.delete_number(number.session, actor=str(sess.user.id))
    except ValueError as e:
        return _link_page(request, sess, number, error=str(e))
    for step in (state.bot.waha.logout, state.bot.waha.delete):  # best effort: the number is gone here already
        try:
            step(number.session)
        except SendError:
            log.warning("waha_cleanup_failed step=%s session=%s", step.__name__, number.session)
    return redirect("/admin/numbers?ok=deleted")
