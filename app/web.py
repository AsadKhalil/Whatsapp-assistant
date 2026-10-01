"""Dashboard plumbing: templates, who is signed in, forms and CSRF, security headers, and the sign-in pages."""
from __future__ import annotations

import hashlib
import hmac
import io
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

import qrcode
from qrcode.image.svg import SvgPathImage

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from starlette.concurrency import run_in_threadpool

from app.auth import ADMIN_SESSION_TTL, BUSINESS_SESSION_TTL, AuthError, Session, totp_uri

log = logging.getLogger("web")
HERE = Path(__file__).parent
STATIC = HERE / "static"
COOKIE = "wa_session"
OK_MESSAGES = {
    "saved": "Saved.",
    "created": "Business created.",
    "password": "Password set. You can log in now.",
    "paused": "Business paused: the bot ignores its messages.",
    "resumed": "Business resumed.",
    "assigned": "Group number updated.",
    "deleted": "Number deleted.",
    "email_removed": "Email removed: the bot no longer sends email for this business.",
}
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; form-action 'self'",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
}
EXPIRED_LINK = "This link has expired or was already used. Ask for a new one."


def localtime(timestamp: float, timezone: str | None = None) -> str:
    return datetime.fromtimestamp(timestamp, ZoneInfo(timezone or "UTC")).strftime("%Y-%m-%d %H:%M")


templates = Jinja2Templates(directory=HERE / "templates")
templates.env.filters["localtime"] = localtime
router = APIRouter()


class Form:
    """A submitted application/x-www-form-urlencoded body."""

    def __init__(self, data: dict[str, list[str]]) -> None:
        self.data = data

    def get(self, name: str, default: str = "") -> str:
        values = self.data.get(name)
        return values[0].strip() if values else default

    def raw(self, name: str) -> str:
        """Exactly as typed: passwords and keys."""
        values = self.data.get(name)
        return values[0] if values else ""

    def all(self, name: str) -> list[str]:
        return [v.strip() for v in self.data.get(name, []) if v.strip()]

    def has(self, name: str) -> bool:
        return name in self.data


async def read_form(request: Request) -> Form:
    body = (await request.body()).decode("utf-8", errors="replace")
    return Form(parse_qs(body, keep_blank_values=True))


def session_of(request: Request) -> Session | None:
    token = request.cookies.get(COOKIE)
    return request.app.state.auth.session(token) if token else None


def any_session(request: Request) -> Session:
    """Signed in, with or without the second step (the two-step pages use this)."""
    sess = session_of(request)
    if sess is None:
        raise HTTPException(303, headers={"Location": "/login"})
    return sess


def signed_in(sess: Session = Depends(any_session)) -> Session:
    if not sess.mfa_ok:
        raise HTTPException(303, headers={"Location": "/login/totp"})
    return sess


def admin_only(sess: Session = Depends(signed_in)) -> Session:
    if sess.user.role != "admin":
        raise HTTPException(403, "This page is for admins.")
    return sess


def business_only(sess: Session = Depends(signed_in)) -> Session:
    if sess.user.role != "business":
        raise HTTPException(403, "This page is for business logins; admins use /admin.")
    return sess


async def posted(request: Request, sess: Session) -> Form:
    """The submitted form, after checking its CSRF token against the session's."""
    form = await read_form(request)
    if not hmac.compare_digest(form.get("csrf").encode(), sess.csrf.encode()):
        raise HTTPException(403, "This form has expired. Go back, reload the page and try again.")
    return form


def route(router: APIRouter, path: str, scope, methods: tuple[str, ...] = ("GET",)):
    """Register handler(request, ctx, form) at `path`.

    `scope` is a dependency returning the signed-in Session, or an object with a `.session`. The handler is a plain
    function run in a worker thread, because pages call Google Sheets and WAHA, which block. POST forms arrive parsed
    and CSRF-checked; GET requests get form=None.
    """
    def register(handler):
        async def endpoint(request: Request, ctx=Depends(scope)) -> Response:
            sess = ctx if isinstance(ctx, Session) else ctx.session
            form = await posted(request, sess) if request.method == "POST" else None
            return await run_in_threadpool(handler, request, ctx, form)

        endpoint.__name__ = handler.__name__
        router.add_api_route(path, endpoint, methods=list(methods))
        return handler
    return register


def render(request: Request, name: str, sess: Session | None = None, status: int = 200, **ctx) -> HTMLResponse:
    ctx.setdefault("ok", OK_MESSAGES.get(request.query_params.get("ok", ""), ""))
    ctx.setdefault("error", "")
    context = {"user": sess.user if sess else None, "csrf": sess.csrf if sess else "", **ctx}
    return templates.TemplateResponse(request, name, context, status_code=status)


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def public_url(request: Request) -> str:
    return request.app.state.settings.public_url.rstrip("/") or str(request.base_url).rstrip("/")


async def security_headers(request: Request, call_next) -> Response:
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response


async def http_error(request: Request, exc: HTTPException) -> Response:
    """Redirects from the sign-in checks, and friendly 403/404 pages."""
    if exc.status_code == 303 and exc.headers:
        return redirect(exc.headers["Location"])
    title = {403: "Not allowed", 404: "Not found"}.get(exc.status_code, "Something went wrong")
    return render(request, "message.html", status=exc.status_code, title=title, message=str(exc.detail))


def _email_hash(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:12]


def _totp_qr(uri: str) -> Markup:
    """The setup key as an inline SVG; CSS sizes it and colors the modules."""
    buf = io.BytesIO()
    qrcode.make(uri, image_factory=SvgPathImage, box_size=10).save(buf)
    return Markup(buf.getvalue().decode())


def _totp_page(request: Request, sess: Session, error: str = "") -> HTMLResponse:
    secret = "" if sess.user.has_totp else request.app.state.auth.totp_setup_secret(request.cookies[COOKIE])
    uri = totp_uri(secret, sess.user.email) if secret else ""
    return render(request, "totp.html", sess, title="Two-step login", secret=secret, error=error,
                  uri=uri, qr_svg=_totp_qr(uri) if uri else "")


@router.get("/")
def start(request: Request) -> Response:
    sess = session_of(request)
    if sess is None:
        return redirect("/login")
    return redirect("/admin" if sess.user.role == "admin" else "/app")


@router.get("/login")
def login_page(request: Request) -> HTMLResponse:
    return render(request, "login.html", title="Log in", email="")


@router.post("/login")
async def login(request: Request) -> Response:
    form = await read_form(request)
    email = form.get("email")
    try:
        token, user = await run_in_threadpool(request.app.state.auth.login, email, form.raw("password"))
    except AuthError as e:
        log.warning("login_failed email=%s", _email_hash(email))
        return render(request, "login.html", title="Log in", email=email, error=str(e))
    response = redirect("/login/totp" if user.role == "admin" else "/app")
    ttl = ADMIN_SESSION_TTL if user.role == "admin" else BUSINESS_SESSION_TTL
    response.set_cookie(COOKIE, token, max_age=ttl, httponly=True, secure=True, samesite="lax")
    return response


@router.get("/login/totp")
def totp_page(request: Request, sess: Session = Depends(any_session)) -> Response:
    if sess.mfa_ok:
        return redirect("/admin" if sess.user.role == "admin" else "/app")
    return _totp_page(request, sess)


@router.post("/login/totp")
async def totp_check(request: Request, sess: Session = Depends(any_session)) -> Response:
    form = await posted(request, sess)
    try:
        passed = await run_in_threadpool(request.app.state.auth.pass_totp, request.cookies[COOKIE], form.get("code"))
    except AuthError as e:
        return _totp_page(request, sess, error=str(e))
    if passed:
        return redirect("/admin")
    return _totp_page(request, sess,
                      error=Markup("That code didn't match. Check the time on your phone and try again."))


@router.get("/invite/{token}")
def invite_page(request: Request, token: str) -> HTMLResponse:
    user = request.app.state.auth.invited_user(token)
    if user is None:
        return render(request, "message.html", status=404, title="Link expired", message=EXPIRED_LINK)
    return render(request, "invite.html", title="Set your password", email=user.email)


@router.post("/invite/{token}")
async def invite_accept(request: Request, token: str) -> Response:
    form, auth = await read_form(request), request.app.state.auth
    user = auth.invited_user(token)
    if user is None:
        return render(request, "message.html", status=404, title="Link expired", message=EXPIRED_LINK)
    if form.raw("password") != form.raw("confirm"):
        return render(request, "invite.html", title="Set your password", email=user.email,
                      error=Markup("The two passwords don't match."))
    try:
        await run_in_threadpool(auth.accept_invite, token, form.raw("password"))
    except AuthError as e:
        return render(request, "invite.html", title="Set your password", email=user.email, error=str(e))
    return redirect("/login?ok=password")


@router.post("/logout")
async def logout(request: Request, sess: Session = Depends(any_session)) -> Response:
    await posted(request, sess)
    request.app.state.auth.logout(request.cookies[COOKIE])
    response = redirect("/login")
    response.delete_cookie(COOKIE, secure=True, httponly=True, samesite="lax")
    return response
