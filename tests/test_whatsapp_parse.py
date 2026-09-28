import hashlib
import hmac

from app.whatsapp import GroupJoin, parse_meta, parse_waha, verify_meta_signature, verify_waha_hmac
from tests.fakes import make_client
from tests.payloads import BSUID, META_PNID, meta_status, meta_text, meta_voice, waha_join, waha_message

CLIENT = make_client()
BY_PHONE = {META_PNID: CLIENT}
BY_SESSION = {"acme": CLIENT}


def first_message(payload):
    return payload["entry"][0]["changes"][0]["value"]["messages"][0]


def test_meta_text_is_keyed_by_bsuid_and_answered_on_the_phone():
    [m] = parse_meta(meta_text(), BY_PHONE)
    assert (m.client_id, m.channel, m.kind, m.text) == ("acme", "meta", "text", "Does it come in another color?")
    assert m.chat_id == m.sender_id == BSUID
    assert m.address == m.sender_phone == "16505551234"
    assert m.sender_name == "Sheena Nelson" and m.is_group is False


def test_meta_username_user_without_a_phone_is_answered_by_bsuid():
    [m] = parse_meta(meta_text(phone=None), BY_PHONE)
    assert m.sender_phone is None and m.address == BSUID and m.sender_name == "Sheena Nelson"


def test_meta_without_bsuid_falls_back_to_the_phone():
    [m] = parse_meta(meta_text(user_id=None), BY_PHONE)
    assert m.chat_id == "16505551234"


def test_meta_voice_note_carries_the_media_id():
    [m] = parse_meta(meta_voice(), BY_PHONE)
    assert m.kind == "audio" and m.audio == "1908647269898587" and m.text == ""


def test_meta_quoted_reply_and_unsupported_types():
    quoted = meta_text()
    first_message(quoted)["context"] = {"from": "15550783881", "id": "wamid.PREV"}
    assert parse_meta(quoted, BY_PHONE)[0].reply_to == "wamid.PREV"
    image = meta_text()
    msg = first_message(image)
    msg["type"] = "image"
    msg.pop("text")
    msg["image"] = {"id": "1"}
    assert parse_meta(image, BY_PHONE)[0].kind == "unsupported"


# Review focus: webhooks that are not messages must be ignored quietly.
def test_meta_statuses_reactions_and_unknown_numbers_are_ignored():
    assert parse_meta(meta_status(), BY_PHONE) == []
    reaction = meta_text()
    msg = first_message(reaction)
    msg["type"] = "reaction"
    msg.pop("text")
    assert parse_meta(reaction, BY_PHONE) == []
    assert parse_meta(meta_text(), {}) == []
    no_id = meta_text()
    first_message(no_id).pop("id")
    assert parse_meta(no_id, BY_PHONE) == []


def test_waha_group_mention_is_detected_through_the_bots_lid():
    m = parse_waha(waha_message(), BY_SESSION)
    assert m.is_group and m.mentions_bot and m.kind == "text"
    assert m.chat_id == m.address == "120363041234567890@g.us"
    assert m.sender_id == "45670000@lid" and m.sender_name == "Ali"
    assert m.sender_phone == "923001234567"  # from GOWS SenderAlt, since the participant id is a LID


def test_waha_mention_in_the_body_only_still_counts():
    m = parse_waha(waha_message("@923330000000 hi", mentioned=()), BY_SESSION)
    assert m.mentions_bot is True


def test_waha_group_message_without_mention_is_not_addressed():
    assert parse_waha(waha_message("just chatting", mentioned=()), BY_SESSION).mentions_bot is False
    assert parse_waha(waha_message("@999900001234 hi", mentioned=()), BY_SESSION).mentions_bot is False


def test_waha_mention_inside_a_quoted_message_does_not_count():
    payload = waha_message("I agree", mentioned=())
    context = payload["payload"]["_data"]["Message"]["extendedTextMessage"]["contextInfo"]
    context["quotedMessage"] = {"extendedTextMessage": {
        "text": "@99990000 hi", "contextInfo": {"mentionedJID": ["99990000@lid"]}}}
    assert parse_waha(payload, BY_SESSION).mentions_bot is False


def test_waha_reply_to_the_bot_counts_as_a_mention():
    reply = {"id": "true_120363041234567890@g.us_3EB0BB", "participant": "923330000000@c.us", "body": "Rs 2500"}
    m = parse_waha(waha_message("and the carrot one?", mentioned=(), reply_to=reply), BY_SESSION)
    assert m.mentions_bot and m.reply_to == "true_120363041234567890@g.us_3EB0BB"


def test_waha_voice_note_with_a_hidden_phone():
    media = {"url": "http://waha:3000/api/files/acme/3EB0AA.oga", "mimetype": "audio/ogg; codecs=opus",
             "filename": None, "error": None}
    m = parse_waha(waha_message("", mentioned=(), media=media, sender_alt=None), BY_SESSION)
    assert m.kind == "audio" and m.audio == media["url"] and m.sender_phone is None


# Review focus: non-message events and unknown sessions are ignored; joins become GroupJoin.
def test_waha_direct_chat_image_own_message_join_and_unknown_session():
    m = parse_waha(waha_message("hi", chat="923001234567@c.us", mentioned=()), BY_SESSION)
    assert m.is_group is False and m.sender_id == "923001234567@c.us" and m.sender_phone == "923001234567"
    image = waha_message("look", mentioned=(), media={"url": "http://waha:3000/f/x.jpg", "mimetype": "image/jpeg"})
    assert parse_waha(image, BY_SESSION).kind == "unsupported"
    assert parse_waha(waha_message(from_me=True), BY_SESSION).from_me is True
    assert parse_waha(waha_message("", mentioned=()), BY_SESSION) is None  # empty text, no media
    no_id = waha_message("hi", chat="923001234567@c.us", mentioned=())
    no_id["payload"]["id"] = None
    assert parse_waha(no_id, BY_SESSION) is None  # no id to deduplicate on
    assert parse_waha(waha_join(), BY_SESSION) == GroupJoin("acme", "120363041234567890@g.us")
    assert parse_waha(waha_message(session="other"), BY_SESSION) is None
    assert parse_waha(waha_message(event="session.status"), BY_SESSION) is None


def test_status_broadcast_and_newsletter_chats_are_ignored():
    assert parse_waha(waha_message(chat="status@broadcast", mentioned=()), BY_SESSION) is None
    assert parse_waha(waha_message(chat="123456@newsletter", mentioned=()), BY_SESSION) is None


def test_signatures():
    body = b'{"x": 1}'
    good = "sha256=" + hmac.new(b"app-secret", body, hashlib.sha256).hexdigest()
    assert verify_meta_signature("app-secret", body, good)
    assert not verify_meta_signature("app-secret", body, "sha256=00")
    assert not verify_meta_signature("", body, good)
    assert not verify_meta_signature("app-secret", body, None)
    headers = {"x-webhook-hmac": hmac.new(b"hook-secret", body, hashlib.sha512).hexdigest(),
               "x-webhook-hmac-algorithm": "sha512"}
    assert verify_waha_hmac("hook-secret", body, headers)
    assert not verify_waha_hmac("hook-secret", body + b" ", headers)
    assert not verify_waha_hmac("", body, headers)
