import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app, maintain
from app.store import Store
from tests.fakes import FakeWaha, make_client
from tests.payloads import meta_status, meta_text, waha_join, waha_message

SETTINGS = Settings(meta_app_secret="app-secret", meta_verify_token="verify-me", waha_webhook_secret="hook-secret")


class RecordingBot:
    """Stands in for app.bot.Bot at the HTTP layer."""

    def __init__(self, store: Store | None = None) -> None:
        client = make_client()
        self.clients = {client.id: client}
        self.store = store or Store(":memory:")
        self.waha = FakeWaha()
        self.handled, self.greeted = [], []

    def handle(self, m) -> None:
        self.handled.append(m)

    def greet(self, client_id: str, chat_id: str) -> None:
        self.greeted.append((client_id, chat_id))


def http_and_bot():
    bot = RecordingBot()
    return TestClient(create_app(SETTINGS, bot)), bot


def meta_headers(body: bytes) -> dict:
    return {"X-Hub-Signature-256": "sha256=" + hmac.new(b"app-secret", body, hashlib.sha256).hexdigest(),
            "Content-Type": "application/json"}


def waha_headers(body: bytes) -> dict:
    return {"X-Webhook-Hmac": hmac.new(b"hook-secret", body, hashlib.sha512).hexdigest(),
            "X-Webhook-Hmac-Algorithm": "sha512", "Content-Type": "application/json"}


def test_meta_verification_handshake():
    http, _ = http_and_bot()
    ok = http.get("/webhooks/meta", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me",
                                            "hub.challenge": "1158201444"})
    assert ok.status_code == 200 and ok.text == "1158201444"
    bad = http.get("/webhooks/meta", params={"hub.mode": "subscribe", "hub.verify_token": "nope",
                                             "hub.challenge": "1"})
    assert bad.status_code == 403


# Review focus: status webhooks are answered 200 and never reach the bot.
def test_meta_webhook_checks_the_signature_and_queues_messages():
    http, bot = http_and_bot()
    body = json.dumps(meta_text()).encode()
    assert http.post("/webhooks/meta", content=body, headers={"X-Hub-Signature-256": "sha256=00"}).status_code == 403
    assert bot.handled == []
    assert http.post("/webhooks/meta", content=body, headers=meta_headers(body)).status_code == 200
    assert [m.text for m in bot.handled] == ["Does it come in another color?"]
    status = json.dumps(meta_status()).encode()
    assert http.post("/webhooks/meta", content=status, headers=meta_headers(status)).status_code == 200
    assert len(bot.handled) == 1


def test_waha_webhook_routes_messages_and_group_joins():
    http, bot = http_and_bot()
    body = json.dumps(waha_message()).encode()
    assert http.post("/webhooks/waha", content=body, headers={"X-Webhook-Hmac": "00"}).status_code == 403
    assert http.post("/webhooks/waha", content=body, headers=waha_headers(body)).status_code == 200
    assert bot.handled[0].mentions_bot is True
    join = json.dumps(waha_join()).encode()
    assert http.post("/webhooks/waha", content=join, headers=waha_headers(join)).status_code == 200
    assert bot.greeted == [("acme", "120363041234567890@g.us")]


# Review focus: a body that fails to parse still gets its 200 once the signature is valid.
def test_signed_but_unparsable_bodies_still_get_a_200():
    http, bot = http_and_bot()
    junk = b"not json"
    assert http.post("/webhooks/meta", content=junk, headers=meta_headers(junk)).status_code == 200
    assert http.post("/webhooks/waha", content=junk, headers=waha_headers(junk)).status_code == 200
    assert bot.handled == [] and bot.greeted == []


def test_health_reflects_the_waha_session():
    http, bot = http_and_bot()
    assert http.get("/health").json() == {"ok": True, "waha": {"acme": "WORKING"}}
    bot.waha.statuses["acme"] = "SCAN_QR_CODE"
    r = http.get("/health")
    assert r.status_code == 503 and r.json()["waha"] == {"acme": "SCAN_QR_CODE"}


def test_maintenance_deletes_old_messages_and_keeps_seven_backups(tmp_path):
    bot = RecordingBot(Store(str(tmp_path / "data" / "a.db")))
    bot.store.save_message("acme", "meta", "old", "c", "u", "Ali", "x", False, 0.0)
    start = 100 * 86_400
    for day in range(9):
        maintain(bot, str(tmp_path / "backups"), start + day * 86_400)
    assert bot.store.history("acme", "c", 10) == []
    assert len(list((tmp_path / "backups").glob("assistant-*.db"))) == 7
