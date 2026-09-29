"""Helpers for dashboard tests: an app with in-memory stores, and signed-in browsers."""
from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.auth import Auth, totp
from app.config import Settings
from app.main import create_app
from tests.fakes import make_bot, registry_with_acme

NOW = 1_790_000_000.0  # the fake bot's clock too
PASSWORD = "correct horse battery"
SETTINGS = Settings(secret_key="test-secret", public_url="https://bot.example.com", meta_app_secret="env-secret",
                    meta_verify_token="env-verify", waha_webhook_secret="hook-secret")


class Site:
    """One running dashboard over in-memory stores, with the acme bakery set up."""

    def __init__(self, registry=None, bot=None) -> None:
        self.registry = registry or registry_with_acme()
        self.auth = Auth(self.registry.db, self.registry.vault, clock=lambda: NOW)
        self.bot = bot or make_bot()[0]
        self.bot.clients = self.registry.clients()
        self.app = create_app(SETTINGS, self.bot, registry=self.registry, auth=self.auth)

    def browser(self) -> TestClient:
        return TestClient(self.app, base_url="https://testserver")

    def business_user(self, email: str = "owner@sweetbakes.pk", business_id: str = "acme") -> TestClient:
        self.auth.accept_invite(self.auth.invite(email, "Owner", "business", business_id), PASSWORD)
        http = self.browser()
        assert http.post("/login", data={"email": email, "password": PASSWORD},
                         follow_redirects=False).headers["location"] == "/app"
        return http

    def admin(self, email: str = "admin@example.com") -> TestClient:
        self.auth.accept_invite(self.auth.invite(email, "Admin", "admin", None), PASSWORD)
        http = self.browser()
        http.post("/login", data={"email": email, "password": PASSWORD}, follow_redirects=False)
        secret = re.search(r'id="totp-secret">([A-Z2-7]+)<', http.get("/login/totp").text).group(1)
        r = http.post("/login/totp", data={"csrf": csrf(http, "/login/totp"), "code": totp(secret, NOW)},
                      follow_redirects=False)
        assert r.headers["location"] == "/admin"
        return http


def csrf(http: TestClient, path: str) -> str:
    """The CSRF token printed in the forms of the page at `path`."""
    return re.search(r'name="csrf" value="([^"]+)"', http.get(path).text).group(1)
