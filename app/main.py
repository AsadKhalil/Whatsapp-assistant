"""HTTP entry points: Meta and WAHA webhooks, health, and the daily maintenance loop."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from app.bot import Bot
from app.config import Settings, load_clients
from app.llm import LLM
from app.sheets import Sheets
from app.store import Store
from app.whatsapp import (GroupJoin, MetaClient, WahaClient, parse_meta, parse_waha, verify_meta_signature,
                          verify_waha_hmac)

log = logging.getLogger("app")
DAY = 86_400


def build_bot(settings: Settings) -> Bot:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    http = httpx.Client(timeout=30)
    return Bot(
        store=Store(settings.db_path),
        sheets=Sheets.from_service_account(settings.google_service_account_file),
        llm=LLM(settings),
        meta=MetaClient(settings, http),
        waha=WahaClient(settings, http),
        clients=load_clients(settings.clients_file),
        log_key=settings.log_hash_key,
    )


def maintain(bot: Bot, backup_dir: str, now: float) -> None:
    """Drop expired pending writes and messages past each client's retention, then keep 7 backups."""
    bot.store.purge_expired_pending(now)
    for client in bot.clients.values():
        bot.store.delete_older_than(client.id, now - client.retention_days * DAY)
    folder = Path(backup_dir)
    bot.store.backup(str(folder / f"assistant-{time.strftime('%Y%m%d', time.gmtime(now))}.db"))
    for old in sorted(folder.glob("assistant-*.db"))[:-7]:
        old.unlink()


def create_app(settings: Settings | None = None, bot: Bot | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    bot = bot or build_bot(settings)
    by_phone = {c.meta_phone_number_id: c for c in bot.clients.values() if c.meta_phone_number_id}
    by_session = {c.waha_session: c for c in bot.clients.values() if c.waha_session}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async def daily() -> None:
            while True:
                try:
                    await asyncio.to_thread(maintain, bot, settings.backup_dir, time.time())
                except Exception:
                    log.exception("maintenance_failed")
                await asyncio.sleep(DAY)

        task = asyncio.create_task(daily())
        yield
        task.cancel()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

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
        try:
            messages = parse_meta(json.loads(body), by_phone)
        except (ValueError, AttributeError, TypeError):
            log.warning("meta_webhook_unparsable")  # still a 200: the signature was valid
            messages = []
        for m in messages:
            tasks.add_task(bot.handle, m)  # Meta retries slow answers, so reply 200 first and work after
        return JSONResponse({"ok": True})

    @app.post("/webhooks/waha")
    async def waha_webhook(request: Request, tasks: BackgroundTasks) -> Response:
        body = await request.body()
        if not verify_waha_hmac(settings.waha_webhook_secret, body, request.headers):
            return Response(status_code=403)
        try:
            event = parse_waha(json.loads(body), by_session)
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
        sessions = {name: bot.waha.status(name) for name in by_session}
        ok = bot.store.writable() and all(status == "WORKING" for status in sessions.values())
        return JSONResponse({"ok": ok, "waha": sessions}, status_code=200 if ok else 503)

    return app
