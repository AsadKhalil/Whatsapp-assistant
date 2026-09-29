import json

import httpx
import pytest

from app.config import Settings
from app.whatsapp import MetaClient, SendError, WahaClient, session_phone

SETTINGS = Settings(meta_access_token="env-token", waha_url="http://waha:3000", waha_api_key="wkey")


def mock(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_meta_uses_the_businesss_own_token_else_the_env_token():
    seen = []

    def handler(request):
        seen.append(request.headers["authorization"])
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": "wamid.1"}]})
        if request.url.path == "/v26.0/media-1":
            return httpx.Response(200, json={"url": "https://lookaside.fbsbx.com/m"})
        return httpx.Response(200, content=b"OggS")

    meta = MetaClient(SETTINGS, mock(handler))
    meta.send_text("1", "923001234567", "hi", token="biz-token")
    meta.send_text("1", "923001234567", "hi")
    meta.download("media-1", token="biz-token")
    assert seen == ["Bearer biz-token", "Bearer env-token", "Bearer biz-token", "Bearer biz-token"]


def test_meta_number_info_for_test_connection():
    def handler(request):
        assert request.url.params["fields"] == "display_phone_number,verified_name"
        if request.headers["authorization"] == "Bearer good":
            return httpx.Response(200, json={"display_phone_number": "+1 555 0100", "verified_name": "Sweet Bakes"})
        return httpx.Response(401, json={"error": {"code": 190, "message": "Error validating access token"}})

    meta = MetaClient(SETTINGS, mock(handler))
    assert meta.number_info("106540352242922", "good")["verified_name"] == "Sweet Bakes"
    with pytest.raises(SendError, match="code=190 Error validating access token"):
        meta.number_info("106540352242922", "expired")


def test_waha_session_management_calls():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path, request.headers["x-api-key"]))
        if request.url.path == "/api/sessions" and request.method == "POST":
            assert json.loads(request.content) == {"name": "shop-1", "start": True, "config": {"webhooks": [{
                "url": "http://engine:8000/webhooks/waha", "events": ["message", "group.v2.join"],
                "hmac": {"key": "hook-secret"}}]}}
            return httpx.Response(201, json={"name": "shop-1"})
        if request.url.path == "/api/sessions/shop-1" and request.method == "GET":
            return httpx.Response(200, json={"name": "shop-1", "status": "WORKING",
                                             "me": {"id": "923330000000@c.us", "pushName": "Sara"}})
        if request.url.path == "/api/shop-1/auth/qr":
            assert request.url.params["format"] == "image"
            return httpx.Response(200, content=b"\x89PNG")
        return httpx.Response(200, json={})

    waha = WahaClient(SETTINGS, mock(handler))
    waha.create_session("shop-1", "http://engine:8000/webhooks/waha", "hook-secret")
    waha.start("shop-1")
    waha.logout("shop-1")
    waha.delete("shop-1")
    assert session_phone(waha.session_info("shop-1")) == "923330000000"
    assert waha.status("shop-1") == "WORKING" and waha.qr_png("shop-1") == b"\x89PNG"
    assert [(method, path) for method, path, _ in calls[:4]] == [
        ("POST", "/api/sessions"), ("POST", "/api/sessions/shop-1/start"), ("POST", "/api/sessions/shop-1/logout"),
        ("DELETE", "/api/sessions/shop-1")]
    assert {key for _, _, key in calls} == {"wkey"}
    assert session_phone({"status": "SCAN_QR_CODE"}) == ""


def test_waha_groups_are_normalised_from_every_engine_shape():
    def handler(request):
        return httpx.Response(200, json=[
            {"JID": "120363001@g.us", "Name": "Bakery team"},  # GOWS
            {"id": "120363002@g.us", "subject": "cake fans"},  # NOWEB
            {"id": {"_serialized": "120363003@g.us"}, "name": "Delivery riders"},  # WEBJS
            {"id": "923001234567@c.us", "name": "not a group"},
            "junk",
        ])

    assert WahaClient(SETTINGS, mock(handler)).groups("shop-1") == [
        {"id": "120363001@g.us", "name": "Bakery team"},
        {"id": "120363002@g.us", "name": "cake fans"},
        {"id": "120363003@g.us", "name": "Delivery riders"},
    ]


def test_waha_groups_accept_an_object_keyed_by_id():
    def handler(request):
        return httpx.Response(200, json={"120363009@g.us": {"id": "120363009@g.us", "subject": "Staff"}})

    assert WahaClient(SETTINGS, mock(handler)).groups("shop-1") == [{"id": "120363009@g.us", "name": "Staff"}]


def test_waha_management_failures_raise_senderror():
    def down(request):
        raise httpx.ConnectError("refused")

    waha = WahaClient(SETTINGS, mock(down))
    with pytest.raises(SendError, match="unreachable"):
        waha.create_session("shop-1", "u", "s")
    assert waha.status("shop-1") == "UNREACHABLE"
    missing = WahaClient(SETTINGS, mock(lambda request: httpx.Response(404)))
    with pytest.raises(SendError, match="404"):
        missing.session_info("nope")
