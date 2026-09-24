"""Webhook bodies shaped like the real ones: Meta Graph v26.0 docs, WAHA 2026.9 (GOWS engine)."""
from __future__ import annotations

META_PNID = "106540352242922"
BSUID = "US.13491208655302741918"
BOT_ME = {"id": "923330000000@c.us", "lid": "99990000@lid", "jid": "923330000000:12@s.whatsapp.net",
          "pushName": "Sara"}


def _meta_envelope(value: dict) -> dict:
    value = {"messaging_product": "whatsapp",
             "metadata": {"display_phone_number": "15550783881", "phone_number_id": META_PNID}, **value}
    return {"object": "whatsapp_business_account",
            "entry": [{"id": "102290129340398", "changes": [{"field": "messages", "value": value}]}]}


def meta_message(message: dict, *, phone: str | None = "16505551234", user_id: str | None = BSUID,
                 name: str = "Sheena Nelson") -> dict:
    contact: dict = {"profile": {"name": name}}
    msg = {"id": "wamid.HBgLMTY1MDM4Nzk0MzkVAgASGBQzQTRBNjU5OUFFRTAzODEwMTQ0RgA=", "timestamp": "1749416383",
           **message}
    if phone:
        contact["wa_id"] = phone
        msg["from"] = phone
    if user_id:
        contact["user_id"] = user_id
        msg["from_user_id"] = user_id
    return _meta_envelope({"contacts": [contact], "messages": [msg]})


def meta_text(body: str = "Does it come in another color?", **kw) -> dict:
    return meta_message({"type": "text", "text": {"body": body}}, **kw)


def meta_voice(**kw) -> dict:
    return meta_message({"type": "audio", "audio": {
        "mime_type": "audio/ogg; codecs=opus", "sha256": "wvqXMe6n7n1W0zphvLPoLj+s/NtKqmr3zZ7YzTP7xFI=",
        "id": "1908647269898587", "voice": True}}, **kw)


def meta_status() -> dict:
    return _meta_envelope({"statuses": [{"id": "wamid.OUT", "status": "delivered", "timestamp": "1749416390",
                                         "recipient_id": "16505551234", "recipient_user_id": BSUID}]})


def waha_message(body: str = "@99990000 how much is the cake?", *, chat: str = "120363041234567890@g.us",
                 participant: str = "45670000@lid", mentioned: tuple[str, ...] = ("99990000@lid",),
                 sender_alt: str | None = "923001234567@s.whatsapp.net", push_name: str = "Ali",
                 media: dict | None = None, reply_to: dict | None = None, from_me: bool = False,
                 session: str = "acme", event: str = "message") -> dict:
    info = {"PushName": push_name, **({"SenderAlt": sender_alt} if sender_alt else {})}
    context = {"mentionedJID": list(mentioned)} if mentioned else {}
    is_group = chat.endswith("@g.us")
    return {
        "id": "evt_01", "timestamp": 1741249702485, "event": event, "session": session, "engine": "GOWS",
        "me": BOT_ME,
        "payload": {
            "id": f"false_{chat}_3EB0AA_{participant}", "timestamp": 1667561485, "from": chat,
            "fromMe": from_me, "source": "app", "participant": participant if is_group else None,
            "body": body, "hasMedia": media is not None, "media": media, "replyTo": reply_to,
            "_data": {"Info": info, "Message": {"extendedTextMessage": {"text": body, "contextInfo": context}}},
        },
    }


def waha_join(group: str = "120363041234567890@g.us", session: str = "acme") -> dict:
    return {"id": "evt_02", "timestamp": 1741249702485, "event": "group.v2.join", "session": session,
            "engine": "GOWS", "me": BOT_ME,
            "payload": {"group": {"id": group, "subject": "Sweet Bakes customers", "participants": []},
                        "timestamp": 1741249702, "_data": {}}}
