import json

import httpx
import pytest

from app.config import Settings
from app.whatsapp import MetaClient, SendError, WahaClient

SETTINGS = Settings(meta_access_token="tok", meta_graph_version="v26.0", waha_url="http://waha:3000",
                    waha_api_key="wkey")


def mock(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_meta_sends_to_a_phone_and_quotes():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"messaging_product": "whatsapp", "messages": [{"id": "wamid.OUT"}]})

    meta = MetaClient(SETTINGS, mock(handler))
    assert meta.send_text("106540352242922", "16505551234", "Hello", reply_to="wamid.IN") == "wamid.OUT"
    request = seen[0]
    assert str(request.url) == "https://graph.facebook.com/v26.0/106540352242922/messages"
    assert request.headers["authorization"] == "Bearer tok"
    assert json.loads(request.content) == {
        "messaging_product": "whatsapp", "recipient_type": "individual", "type": "text",
        "text": {"body": "Hello"}, "to": "16505551234", "context": {"message_id": "wamid.IN"}}


def test_meta_sends_to_a_username_user_by_bsuid():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"messages": [{"id": "wamid.2"}]})

    MetaClient(SETTINGS, mock(handler)).send_text("1", "US.13491208655302741918", "Hi")
    assert bodies[0]["recipient"] == "US.13491208655302741918" and "to" not in bodies[0]


def test_meta_retries_a_rate_limit_once_and_raises_other_errors():
    calls = []

    def limited_then_ok(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(400, json={"error": {"code": 130429, "message": "(#130429) Rate limit hit"}})
        return httpx.Response(200, json={"messages": [{"id": "wamid.3"}]})

    assert MetaClient(SETTINGS, mock(limited_then_ok), sleep=lambda s: None).send_text("1", "1", "x") == "wamid.3"
    assert len(calls) == 2

    def window_closed(request):
        return httpx.Response(400, json={"error": {"code": 131047, "message": "Re-engagement message"}})

    with pytest.raises(SendError, match="131047"):
        MetaClient(SETTINGS, mock(window_closed), sleep=lambda s: None).send_text("1", "1", "x")


def test_meta_media_download_is_two_authenticated_steps():
    def handler(request):
        assert request.headers["authorization"] == "Bearer tok"
        if request.url.path == "/v26.0/1908647269898587":
            return httpx.Response(200, json={
                "messaging_product": "whatsapp", "id": "1908647269898587", "mime_type": "audio/ogg",
                "file_size": 4, "url": "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=1"})
        return httpx.Response(200, content=b"OggS")

    assert MetaClient(SETTINGS, mock(handler)).download("1908647269898587") == b"OggS"


def test_waha_send_download_and_status():
    def handler(request):
        assert request.headers["x-api-key"] == "wkey"
        if request.url.path == "/api/sendText":
            assert json.loads(request.content) == {"session": "acme", "chatId": "123@g.us", "text": "Hi",
                                                   "reply_to": "false_123@g.us_3EB0AA_4567@lid"}
            return httpx.Response(201, json={"id": "true_123@g.us_3EB0CC"})
        if request.url.path == "/api/files/acme/3EB0AA.oga":
            return httpx.Response(200, content=b"OggS")
        if request.url.path == "/api/sessions/acme":
            return httpx.Response(200, json={"name": "acme", "status": "WORKING"})
        return httpx.Response(404)

    waha = WahaClient(SETTINGS, mock(handler))
    assert waha.send_text("acme", "123@g.us", "Hi", reply_to="false_123@g.us_3EB0AA_4567@lid") == "true_123@g.us_3EB0CC"
    assert waha.download("http://waha:3000/api/files/acme/3EB0AA.oga") == b"OggS"
    assert waha.status("acme") == "WORKING"


def test_waha_errors_and_id_shapes():
    down = WahaClient(SETTINGS, mock(lambda request: httpx.Response(500)))
    with pytest.raises(SendError):
        down.send_text("acme", "123@g.us", "Hi")
    assert down.status("acme") == "UNREACHABLE"
    webjs = WahaClient(SETTINGS, mock(lambda request: httpx.Response(201, json={"id": {"_serialized": "true_1@c.us_AA"}})))
    assert webjs.send_text("acme", "1@c.us", "Hi") == "true_1@c.us_AA"
