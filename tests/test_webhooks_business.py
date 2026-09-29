import hashlib
import hmac
import json
import shutil

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app, open_registry
from tests.fakes import acme_config, registry_with_acme
from tests.payloads import META_PNID, meta_text

SETTINGS = Settings(secret_key="test-secret", meta_app_secret="env-secret", meta_verify_token="env-verify")


class Recorder:
    """Stands in for the bot: remembers what the webhooks queued."""

    def __init__(self, clients) -> None:
        self.clients = clients
        self.handled = []

    def handle(self, m) -> None:
        self.handled.append(m)


def signed(body: bytes, secret: str) -> dict:
    return {"X-Hub-Signature-256": "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest(),
            "Content-Type": "application/json"}


def site():
    registry = registry_with_acme()
    bot = Recorder(registry.clients())
    return TestClient(create_app(SETTINGS, bot, registry=registry)), bot, registry


def test_the_app_refuses_to_start_without_a_secret_key():
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app(Settings(), Recorder({}), registry=registry_with_acme())


def test_each_business_answers_metas_handshake_with_its_own_verify_token():
    http, bot, _ = site()
    token = bot.clients["acme"].meta_verify_token
    ok = http.get("/webhooks/meta/acme", params={"hub.mode": "subscribe", "hub.verify_token": token,
                                                 "hub.challenge": "42"})
    assert ok.status_code == 200 and ok.text == "42"
    wrong = http.get("/webhooks/meta/acme", params={"hub.mode": "subscribe", "hub.verify_token": "env-verify",
                                                    "hub.challenge": "42"})
    assert wrong.status_code == 403
    assert http.get("/webhooks/meta/nope", params={"hub.mode": "subscribe", "hub.verify_token": token}).status_code == 403


def test_a_business_webhook_checks_its_own_app_secret_and_only_its_own_number():
    http, bot, registry = site()
    body = json.dumps(meta_text()).encode()  # addressed to acme's number, META_PNID
    assert http.post("/webhooks/meta/acme", content=body, headers=signed(body, "env-secret")).status_code == 403
    assert http.post("/webhooks/meta/acme", content=body, headers=signed(body, "acme-secret")).status_code == 200
    assert [m.client_id for m in bot.handled] == ["acme"]
    registry.create_business("other", {**acme_config(), "business": "Other Co"}, actor="t")
    registry.save_meta("other", "999000999", "other-token", "other-secret", actor="t")
    bot.clients = registry.clients()
    # Other's Meta app signs a message for acme's number: ignored, still a 200 so Meta stops retrying.
    assert http.post("/webhooks/meta/other", content=body, headers=signed(body, "other-secret")).status_code == 200
    assert len(bot.handled) == 1
    assert http.post("/webhooks/meta/nope", content=body, headers=signed(body, "acme-secret")).status_code == 404


def test_paused_businesses_get_a_200_and_nothing_is_queued():
    http, bot, registry = site()
    registry.set_active("acme", False, actor="t")
    bot.clients = registry.clients()
    body = json.dumps(meta_text()).encode()
    assert http.post("/webhooks/meta/acme", content=body, headers=signed(body, "acme-secret")).status_code == 200
    assert bot.handled == []


def test_the_v1_address_only_serves_businesses_on_the_env_meta_app():
    http, bot, registry = site()  # acme has an app secret of its own
    body = json.dumps(meta_text()).encode()
    assert http.post("/webhooks/meta", content=body, headers=signed(body, "env-secret")).status_code == 200
    assert bot.handled == []
    registry.save_meta("acme", META_PNID, "", "env-secret", actor="t")  # the pilot's keys came from .env
    bot.clients = registry.clients()
    http.post("/webhooks/meta", content=body, headers=signed(body, "env-secret"))
    assert [m.client_id for m in bot.handled] == ["acme"]


def test_reload_hands_saved_settings_to_the_bot():
    http, bot, registry = site()
    registry.save_config("acme", {"bot_name": "Zara"}, actor="t")
    assert bot.clients["acme"].bot_name == "Sara"
    http.app.state.reload()
    assert bot.clients["acme"].bot_name == "Zara"


def test_first_start_imports_clients_yaml_once(tmp_path):
    shutil.copy("clients.example.yaml", tmp_path / "clients.yaml")
    settings = Settings(secret_key="k", db_path=str(tmp_path / "a.db"), clients_file=str(tmp_path / "clients.yaml"),
                        meta_access_token="EAAG", meta_app_secret="s", meta_verify_token="v")
    assert "sweetbakes" in open_registry(settings).clients()
    (tmp_path / "clients.yaml").write_text("clients: {}\n", encoding="utf-8")
    assert "sweetbakes" in open_registry(settings).clients()  # the database is the source of truth now
