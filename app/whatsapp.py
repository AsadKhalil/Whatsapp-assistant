"""WhatsApp in and out: Meta Cloud API (official number) and WAHA (the purchased group number)."""
from __future__ import annotations

import hashlib
import hmac
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import httpx

from app.config import Client, Settings, digits

# Meta message types; anything not listed (reaction, system, request_welcome, ...) is ignored.
META_KINDS = {"text": "text", "audio": "audio", **{t: "unsupported" for t in (
    "image", "video", "document", "sticker", "location", "contacts", "interactive", "button", "unsupported")}}
MENTION_KEYS = {"mentionedJID", "mentionedJid", "mentionedJidList"}  # GOWS, NOWEB, WEBJS
NAME_KEYS = {"PushName", "pushName", "notifyName"}


@dataclass
class Incoming:
    client_id: str
    channel: str  # "meta" or "waha"
    msg_id: str
    chat_id: str  # conversation key: Meta BSUID (or phone), or the WAHA chat id
    address: str  # where replies go: Meta phone or BSUID, or the WAHA chat id
    is_group: bool
    sender_id: str
    sender_name: str
    sender_phone: str | None  # digits only; None when WhatsApp hides the number
    kind: str  # "text", "audio" or "unsupported"
    text: str = ""
    audio: str | None = None  # Meta media id, or WAHA media URL
    audio_bytes: bytes | None = None  # the downloaded note, filled before per-chat processing starts
    reply_to: str | None = None
    mentions_bot: bool = False
    from_me: bool = False


@dataclass(frozen=True)
class GroupJoin:
    client_id: str
    chat_id: str


def verify_meta_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    """Meta signs the raw body with the app secret: 'X-Hub-Signature-256: sha256=<hex>'."""
    if not app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def verify_waha_hmac(secret: str, body: bytes, headers: Mapping[str, str]) -> bool:
    """WAHA signs the raw body with HMAC-SHA512, hex, in 'X-Webhook-Hmac'."""
    signature = headers.get("x-webhook-hmac")
    if not secret or not signature or headers.get("x-webhook-hmac-algorithm", "sha512") != "sha512":
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)


def parse_meta(payload: dict, by_phone_number_id: dict[str, Client]) -> list[Incoming]:
    out = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            client = by_phone_number_id.get(str((value.get("metadata") or {}).get("phone_number_id", "")))
            if client is None:
                continue
            names = {}
            for contact in value.get("contacts") or []:
                for key in (contact.get("user_id"), contact.get("wa_id")):
                    if key:
                        names[key] = (contact.get("profile") or {}).get("name", "")
            for msg in value.get("messages") or []:
                kind = META_KINDS.get(msg.get("type", ""))
                phone = digits(msg.get("from")) or None
                user = msg.get("from_user_id") or phone
                if kind is None or not user or not msg.get("id"):
                    continue
                out.append(Incoming(
                    client_id=client.id, channel="meta", msg_id=msg["id"], chat_id=user, address=phone or user,
                    is_group=False, sender_id=user, sender_name=names.get(user) or names.get(phone or "", ""),
                    sender_phone=phone, kind=kind,
                    text=(msg.get("text") or {}).get("body", "") if kind == "text" else "",
                    audio=(msg.get("audio") or {}).get("id") if kind == "audio" else None,
                    reply_to=(msg.get("context") or {}).get("id"),
                ))
    return out


def _user(jid: object) -> str:
    """'923001234567:12@s.whatsapp.net' -> '923001234567'."""
    return str(jid or "").split("@")[0].split(":")[0]


def _jid(value: object) -> str:
    if isinstance(value, dict):  # WEBJS sometimes sends {"_serialized": ...}
        return str(value.get("_serialized") or value.get("user") or "")
    return str(value)


def _phone(jid: object) -> str | None:
    """Digits of a phone-number id; None for '@lid' ids, which hide the number."""
    jid = str(jid or "")
    if not jid.endswith(("@c.us", "@s.whatsapp.net")):
        return None
    return digits(_user(jid)) or None


def _walk(data: object):
    """Every (key, value) in nested dicts and lists, skipping quoted messages."""
    if isinstance(data, dict):
        for key, value in data.items():
            if key == "quotedMessage":
                continue
            yield key, value
            yield from _walk(value)
    elif isinstance(data, list):
        for item in data:
            yield from _walk(item)


def parse_waha(envelope: dict, by_session: dict[str, Client]) -> Incoming | GroupJoin | None:
    client = by_session.get(str(envelope.get("session", "")))
    event, p = envelope.get("event"), envelope.get("payload") or {}
    if client is None:
        return None
    if event == "group.v2.join":
        group_id = (p.get("group") or {}).get("id")
        return GroupJoin(client.id, group_id) if group_id else None
    if event != "message":
        return None
    if not str(p.get("id") or ""):
        return None  # without an id, the next id-less event would dedupe against this one
    chat = str(p.get("from") or "")
    if not chat.endswith(("@g.us", "@c.us", "@s.whatsapp.net", "@lid")):
        return None  # contacts' Status posts (status@broadcast) and channels (...@newsletter) aren't chats
    is_group = chat.endswith("@g.us")
    sender = str((p.get("participant") if is_group else chat) or "")
    body = str(p.get("body") or "")
    media = p.get("media") or {}
    if p.get("hasMedia"):
        kind = "audio" if str(media.get("mimetype", "")).startswith("audio/") else "unsupported"
    elif body:
        kind = "text"
    else:
        return None  # reactions, locations and other empty messages
    raw = p.get("_data") or {}
    me = envelope.get("me") or {}
    bot = {_user(me.get("id")), _user(me.get("lid"))} - {""}
    mentioned = {_user(_jid(v)) for key, value in _walk(raw)
                 if key in MENTION_KEYS and isinstance(value, list) for v in value}
    reply = p.get("replyTo") or {}
    addressed = (bool(bot & mentioned) or any(re.search(rf"@{re.escape(u)}(?!\d)", body) for u in bot)
                 or _user(reply.get("participant")) in bot)
    name = next((v for key, v in _walk(raw) if key in NAME_KEYS and isinstance(v, str) and v), "")
    alt = next((v for key, v in _walk(raw) if key == "SenderAlt" and isinstance(v, str)), None)
    return Incoming(
        client_id=client.id, channel="waha", msg_id=str(p.get("id", "")), chat_id=chat, address=chat,
        is_group=is_group, sender_id=sender, sender_name=name, sender_phone=_phone(sender) or _phone(alt),
        kind=kind, text=body if kind == "text" else "", audio=media.get("url") if kind == "audio" else None,
        reply_to=reply.get("id"), mentions_bot=addressed, from_me=bool(p.get("fromMe")),
    )


class SendError(Exception):
    """A message was not delivered; the text carries the provider's status and error code."""


def _meta_error_code(response: httpx.Response) -> int | None:
    try:
        return (response.json().get("error") or {}).get("code")
    except ValueError:
        return None


def _meta_error_message(response: httpx.Response, hide: str = "") -> str:
    try:
        message = str((response.json().get("error") or {}).get("message", ""))
    except ValueError:
        return ""
    if hide:
        message = message.replace(hide, "(hidden)")
    return message[:200]


class MetaClient:
    def __init__(self, settings: Settings, http: httpx.Client, sleep: Callable[[float], None] = time.sleep) -> None:
        self._http = http
        self._sleep = sleep
        self._base = f"https://graph.facebook.com/{settings.meta_graph_version}"
        self._token = settings.meta_access_token  # the .env token, for a business without keys of its own

    def _headers(self, token: str | None) -> dict[str, str]:
        return {"Authorization": f"Bearer {token or self._token}"}

    def send_text(self, phone_number_id: str, to: str, text: str, reply_to: str | None = None,
                  token: str | None = None) -> str | None:
        body: dict = {"messaging_product": "whatsapp", "recipient_type": "individual", "type": "text",
                      "text": {"body": text}}
        body["to" if to.isdigit() else "recipient"] = to  # username users only have a BSUID
        if reply_to:
            body["context"] = {"message_id": reply_to}
        url, headers = f"{self._base}/{phone_number_id}/messages", self._headers(token)
        try:
            r = self._http.post(url, json=body, headers=headers)
            if r.status_code == 429 or (r.status_code >= 400 and _meta_error_code(r) == 130429):
                self._sleep(2)
                r = self._http.post(url, json=body, headers=headers)
        except httpx.HTTPError as e:
            raise SendError(f"meta unreachable: {type(e).__name__}") from e
        if r.status_code >= 400:
            raise SendError(f"meta status={r.status_code} code={_meta_error_code(r)}")
        try:
            return ((r.json().get("messages") or [{}])[0]).get("id")
        except ValueError:
            return None  # sent, but a non-JSON 2xx body means the provider's id is unknown

    def download(self, media_id: str, token: str | None = None) -> bytes:
        headers = self._headers(token)
        info = self._http.get(f"{self._base}/{media_id}", headers=headers)
        info.raise_for_status()
        media = self._http.get(info.json()["url"], headers=headers)  # the URL expires after 5 minutes
        media.raise_for_status()
        return media.content

    def number_info(self, phone_number_id: str, token: str | None = None) -> dict:
        """What Meta says about a number, for "Test connection"; raises SendError carrying Meta's reason."""
        try:
            r = self._http.get(f"{self._base}/{phone_number_id}", headers=self._headers(token),
                               params={"fields": "display_phone_number,verified_name"})
        except httpx.HTTPError as e:
            raise SendError(f"meta unreachable: {type(e).__name__}") from e
        if r.status_code >= 400:
            raise SendError(f"meta status={r.status_code} code={_meta_error_code(r)} "
                            f"{_meta_error_message(r, hide=token or self._token)}")
        return r.json()


def _waha_id(data: dict) -> str | None:
    value = data.get("id")
    if isinstance(value, dict):  # WEBJS shape
        value = value.get("_serialized") or value.get("id")
    return str(value) if value else None


class WahaClient:
    def __init__(self, settings: Settings, http: httpx.Client) -> None:
        self._http = http
        self._base = settings.waha_url.rstrip("/")
        self._auth = {"X-Api-Key": settings.waha_api_key}

    def _call(self, method: str, path: str, headers: dict | None = None, **kwargs) -> httpx.Response:
        try:
            r = self._http.request(method, f"{self._base}{path}", headers={**self._auth, **(headers or {})},
                                   **kwargs)
        except httpx.HTTPError as e:
            raise SendError(f"waha unreachable: {type(e).__name__}") from e
        if r.status_code >= 400:
            raise SendError(f"waha status={r.status_code}")
        return r

    def send_text(self, session: str, chat_id: str, text: str, reply_to: str | None = None) -> str | None:
        body = {"session": session, "chatId": chat_id, "text": text}
        if reply_to:
            body["reply_to"] = reply_to
        r = self._call("POST", "/api/sendText", json=body)
        try:
            return _waha_id(r.json())
        except ValueError:
            return None  # sent, but a non-JSON 2xx body means the provider's id is unknown

    def download(self, url: str) -> bytes:
        r = self._http.get(url, headers=self._auth)
        r.raise_for_status()
        return r.content

    def status(self, session: str) -> str:
        try:
            return str(self.session_info(session).get("status", "UNKNOWN"))
        except (SendError, ValueError):
            return "UNREACHABLE"

    def session_info(self, name: str) -> dict:
        return self._call("GET", f"/api/sessions/{name}").json()

    def create_session(self, name: str, webhook_url: str, webhook_secret: str) -> None:
        """A new session for a purchased number, posting its messages and group joins to the engine."""
        webhook = {"url": webhook_url, "events": ["message", "group.v2.join"], "hmac": {"key": webhook_secret}}
        self._call("POST", "/api/sessions", json={"name": name, "start": True, "config": {"webhooks": [webhook]}})

    def start(self, name: str) -> None:
        self._call("POST", f"/api/sessions/{name}/start")

    def logout(self, name: str) -> None:
        self._call("POST", f"/api/sessions/{name}/logout")

    def delete(self, name: str) -> None:
        self._call("DELETE", f"/api/sessions/{name}")

    def qr_png(self, name: str) -> bytes:
        return self._call("GET", f"/api/{name}/auth/qr", params={"format": "image"},
                          headers={"Accept": "image/png"}).content

    def groups(self, name: str) -> list[dict]:
        """The groups this number is in, as [{"id": "...@g.us", "name": "..."}], whatever the engine's shape."""
        data = self._call("GET", f"/api/{name}/groups").json()
        found = []
        for group in (data.values() if isinstance(data, dict) else data) or []:
            if not isinstance(group, dict):
                continue
            group_id = _jid(group.get("id") or group.get("JID") or "")
            if group_id.endswith("@g.us"):
                name_ = group.get("subject") or group.get("name") or group.get("Name") or group_id
                found.append({"id": group_id, "name": str(name_)})
        return sorted(found, key=lambda g: g["name"].lower())


def session_phone(info: dict) -> str:
    """The linked number's digits from WAHA's session info ('' until linked)."""
    return digits(_user((info.get("me") or {}).get("id")))
