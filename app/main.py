"""HTTP entry points: Meta and WAHA webhooks, health, the dashboard, and the daily maintenance loop."""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app import admin_pages, numbers_pages, pages, web
from app.auth import Auth
from app.bot import Bot
from app.config import Client, Settings
from app.db import Db
from app.llm import LLM
from app.mailer import Mailer
from app.registry import Registry
from app.sheets import Sheets
from app.store import Store
from app.vault import Vault
from app.whatsapp import (GroupJoin, MetaClient, WahaClient, parse_meta, parse_waha, verify_meta_signature,
                          verify_waha_hmac)

log = logging.getLogger("app")
DAY = 86_400


def build_bot(settings: Settings, clients: dict[str, Client]) -> Bot:
    if settings.log_hash_key == "change-me":
        log.warning("LOG_HASH_KEY is not set; hashed chat ids in the logs can be reversed")
    http = httpx.Client(timeout=30)
    return Bot(
        store=Store(settings.db_path),
        sheets=Sheets.from_service_account(settings.google_service_account_file),
        llm=LLM(settings),
        meta=MetaClient(settings, http),
        waha=WahaClient(settings, http),
        clients=clients,
        log_key=settings.log_hash_key,
        mailer=Mailer(),
    )


def open_registry(settings: Settings) -> Registry:
    """The dashboard's database; the very first start imports clients.yaml (the v1 settings) once."""
    registry = Registry(Db(settings.db_path), Vault(settings.secret_key))
    if Path(settings.clients_file).is_file():
        if registry.is_empty():
            count = registry.import_yaml(settings.clients_file, settings)
            log.info("imported %s business(es) from %s", count, settings.clients_file)
        else:
            log.info("clients.yaml is ignored: businesses are managed in the dashboard")
    return registry


def maintain(bot: Bot, backup_dir: str, now: float, clients: dict[str, Client] | None = None) -> None:
    """Drop expired pending writes and messages past each client's retention, then keep 7 backups.

    Every business's retention, paused ones too when `clients` is passed (from `registry.clients
    (include_paused=True)`); defaults to `bot.clients` (active businesses only).
    """
    bot.store.purge_expired_pending(now)
    for client in (bot.clients if clients is None else clients).values():
        bot.store.delete_older_than(client.id, now - client.retention_days * DAY)
    folder = Path(backup_dir)
    bot.store.backup(str(folder / f"assistant-{time.strftime('%Y%m%d', time.gmtime(now))}.db"))
    for old in sorted(folder.glob("assistant-*.db"))[:-7]:
        old.unlink()


def create_app(settings: Settings | None = None, bot: Bot | None = None, registry: Registry | None = None,
               auth: Auth | None = None) -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = settings or Settings.from_env()
    if not settings.secret_key:
        raise RuntimeError("Set SECRET_KEY in .env (make one with: openssl rand -hex 32), then restart.")
    registry = registry or open_registry(settings)
    auth = auth or Auth(registry.db, registry.vault)
    bot = bot or build_bot(settings, registry.clients())

    def reload() -> None:
        """Hand freshly saved settings to the bot; its next message uses them."""
        bot.clients = registry.clients()

    def sessions() -> dict[str, Client]:
        return {c.waha_session: c for c in bot.clients.values() if c.waha_session}

    def env_app_phones() -> dict[str, Client]:
        """The v1 /webhooks/meta address serves only businesses on the .env Meta app."""
        return {c.meta_phone_number_id: c for c in bot.clients.values() if c.meta_phone_number_id
                and (not c.meta_app_secret or c.meta_app_secret == settings.meta_app_secret)}

    def queue_meta(body: bytes, phones: dict[str, Client], tasks: BackgroundTasks) -> Response:
        try:
            messages = parse_meta(json.loads(body), phones)
        except (ValueError, AttributeError, TypeError):
            log.warning("meta_webhook_unparsable")  # still a 200: the signature was valid
            messages = []
        for m in messages:
            tasks.add_task(bot.handle, m)  # Meta retries slow answers, so reply 200 first and work after
        return JSONResponse({"ok": True})

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async def daily() -> None:
            while True:
                try:
                    await asyncio.to_thread(maintain, bot, settings.backup_dir, time.time(),
                                            registry.clients(include_paused=True))
                except Exception:
                    log.exception("maintenance_failed")
                await asyncio.sleep(DAY)

        task = asyncio.create_task(daily())
        yield
        task.cancel()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings, app.state.registry, app.state.bot, app.state.reload = settings, registry, bot, reload
    app.state.auth = auth
    app.middleware("http")(web.security_headers)
    app.add_exception_handler(HTTPException, web.http_error)
    app.mount("/static", StaticFiles(directory=web.STATIC), name="static")
    app.include_router(web.router)
    app.include_router(pages.router)
    app.include_router(admin_pages.router)
    app.include_router(numbers_pages.router)

    @app.get("/webhooks/meta")
    def meta_verify(request: Request) -> Response:
        q = request.query_params
        if (q.get("hub.mode") == "subscribe" and settings.meta_verify_token
                and q.get("hub.verify_token") == settings.meta_verify_token):
            return PlainTextResponse(q.get("hub.challenge", ""))
        return Response(status_code=403)

    @app.post("/webhooks/meta")
    async def meta_webhook(request: Request, tasks: BackgroundTasks) -> Response:
        body = await request.body()
        if not verify_meta_signature(settings.meta_app_secret, body, request.headers.get("x-hub-signature-256")):
            return Response(status_code=403)
        return queue_meta(body, env_app_phones(), tasks)

    @app.get("/webhooks/meta/{business_id}")
    def business_meta_verify(business_id: str, request: Request) -> Response:
        client, q = bot.clients.get(business_id), request.query_params
        if (client and client.meta_verify_token and q.get("hub.mode") == "subscribe"
                and hmac.compare_digest(q.get("hub.verify_token", "").encode(), client.meta_verify_token.encode())):
            return PlainTextResponse(q.get("hub.challenge", ""))
        return Response(status_code=403)

    @app.post("/webhooks/meta/{business_id}")
    async def business_meta_webhook(business_id: str, request: Request, tasks: BackgroundTasks) -> Response:
        client = bot.clients.get(business_id)
        if client is None:  # a paused business still gets its 200, so Meta stops retrying
            return Response(status_code=200 if registry.business(business_id) else 404)
        body = await request.body()
        if not verify_meta_signature(client.meta_app_secret, body, request.headers.get("x-hub-signature-256")):
            return Response(status_code=403)
        # Only this business's own number: another business's Meta app can't inject messages through here.
        own = {client.meta_phone_number_id: client} if client.meta_phone_number_id else {}
        return queue_meta(body, own, tasks)

    @app.post("/webhooks/waha")
    async def waha_webhook(request: Request, tasks: BackgroundTasks) -> Response:
        body = await request.body()
        if not verify_waha_hmac(settings.waha_webhook_secret, body, request.headers):
            return Response(status_code=403)
        try:
            event = parse_waha(json.loads(body), sessions())
        except (ValueError, AttributeError, TypeError):
            log.warning("waha_webhook_unparsable")
            event = None
        if isinstance(event, GroupJoin):
            tasks.add_task(bot.greet, event.client_id, event.chat_id)
        elif event is not None:
            tasks.add_task(bot.handle, event)
        return JSONResponse({"ok": True})

    @app.get("/health")
    def health() -> JSONResponse:
        statuses = {name: bot.waha.status(name) for name in sessions()}
        ok = bot.store.writable() and all(status == "WORKING" for status in statuses.values())
        return JSONResponse({"ok": ok, "waha": statuses}, status_code=200 if ok else 503)

    return app
