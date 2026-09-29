"""In-memory stand-ins shared by the tests and the eval runner. Later tasks append to this file."""
from __future__ import annotations

import itertools
import json

from app.bot import Bot
from app.config import Client, TabRule
from app.db import Db
from app.llm import ModelReply, ToolCall
from app.registry import Registry
from app.store import Store
from app.vault import Vault
from app.whatsapp import Incoming


def make_client(**overrides) -> Client:
    fields = dict(
        id="acme",
        business="Sweet Bakes",
        bot_name="Sara",
        sheet_id="sheet-1",
        timezone="Asia/Karachi",
        instructions="Orders need 24 hours notice.",
        tabs={
            "Prices": TabRule(customer=frozenset({"read"})),
            "Orders": TabRule(customer=frozenset({"own", "append"}), owner_column="Phone",
                              fill={"Name": "name", "Phone": "phone"}),
            "Staff Notes": TabRule(),
            "Expenses": TabRule(),
        },
        meta_phone_number_id="106540352242922",
        waha_session="acme",
        staff_chats=frozenset({"staff@g.us"}),
        staff_numbers=frozenset({"923001111111"}),
        staff_alert_chat="staff@g.us",
        date_format="%d/%m/%Y",
    )
    fields.update(overrides)
    return Client(**fields)


class FakeSheets:
    def __init__(self, tabs: dict[str, list[dict]], headers: dict[str, list[str]] | None = None) -> None:
        self.tabs = {name: [dict(r) for r in rows] for name, rows in tabs.items()}
        self._headers = headers or {}
        self.appended: list[tuple[str, dict]] = []
        self.fail_append = False

    def rows(self, sheet_id: str, tab: str) -> list[dict]:
        return [dict(r) for r in self.tabs[tab]]  # KeyError for a missing tab, like a renamed sheet

    def headers(self, sheet_id: str, tab: str, now: float | None = None) -> list[str]:
        if tab in self._headers:
            return self._headers[tab]
        return list(self.tabs[tab][0]) if self.tabs.get(tab) else []

    def append(self, sheet_id: str, tab: str, row: dict[str, str]) -> None:
        if self.fail_append:
            raise RuntimeError("Sheets is down")
        self.appended.append((tab, dict(row)))
        self.tabs.setdefault(tab, []).append(dict(row))

    def knowledge(self, sheet_id: str, tab: str, now: float | None = None) -> str:
        return "\n".join(" | ".join(f"{k}: {v}" for k, v in r.items()) for r in self.tabs.get(tab, []))


def bakery_sheets() -> FakeSheets:
    return FakeSheets(
        tabs={
            "Knowledge": [{"Question": "Delivery?", "Answer": "Free above Rs 3000"}],
            "Prices": [{"Item": "Chocolate cake", "Price": 2500}, {"Item": "Carrot cake", "Price": 2200}],
            "Orders": [
                {"Date": "2026-09-20", "Item": "Chocolate cake", "Qty": 1, "Name": "Ali", "Phone": "0300 1234567"},
                {"Date": "2026-09-21", "Item": "Carrot cake", "Qty": 2, "Name": "Sana", "Phone": "0321 7654321"},
            ],
            "Staff Notes": [{"Note": "Oven 2 is broken"}],
            "Expenses": [  # June total is 27300: one hand-typed date, one unreadable date, one blank amount
                {"Date": "2026-06-02", "Item": "Rent", "Amount": 25000, "Category": "Rent"},
                {"Date": "2026-06-15", "Item": "Petrol", "Amount": "Rs 1,500", "Category": "Transport"},
                {"Date": "15/06/2026", "Item": "Taxi", "Amount": 800, "Category": "Transport"},
                {"Date": "2026-07-01", "Item": "Petrol", "Amount": 1600, "Category": "Transport"},
                {"Date": "soon", "Item": "Boxes", "Amount": 300, "Category": "Supplies"},
                {"Date": "2026-06-20", "Item": "Tape", "Amount": "", "Category": "Supplies"},
            ],
            "Handoffs": [],
        },
        headers={"Handoffs": ["Time", "Name", "Phone", "Chat", "Question", "Reason"]},
    )


def say(text: str) -> ModelReply:
    return ModelReply(text=text, tool_calls=[], message={"role": "assistant", "content": text})


def call(name: str, **arguments) -> ModelReply:
    tool_call = ToolCall(id=f"call_{name}", name=name, arguments=arguments)
    message = {"role": "assistant", "content": None, "tool_calls": [
        {"id": tool_call.id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]}
    return ModelReply(text="", tool_calls=[tool_call], message=message)


class ScriptedLLM:
    """Plays back queued replies and records what the bot sent."""

    def __init__(self, *replies: ModelReply, transcript: str = "", fail: bool = False) -> None:
        self.replies = list(replies)
        self.transcript = transcript
        self.fail = fail
        self.calls: list[list] = []

    def complete(self, messages: list, tools: list[dict]) -> ModelReply:
        self.calls.append(list(messages))
        if self.fail:
            raise RuntimeError("model is down")
        return self.replies.pop(0)

    def transcribe(self, audio: bytes) -> str:
        return self.transcript


class FakeMeta:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str | None]] = []
        self.audio: dict[str, bytes] = {}
        self.fail: Exception | None = None

    def send_text(self, phone_number_id: str, to: str, text: str, reply_to: str | None = None) -> str:
        if self.fail:
            raise self.fail
        self.sent.append((to, text, reply_to))
        return f"wamid.out-{len(self.sent)}"

    def download(self, media_id: str) -> bytes:
        return self.audio[media_id]


class FakeWaha:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str | None]] = []
        self.audio: dict[str, bytes] = {}
        self.statuses: dict[str, str] = {}
        self.fail: Exception | None = None

    def send_text(self, session: str, chat_id: str, text: str, reply_to: str | None = None) -> str:
        if self.fail:
            raise self.fail
        self.sent.append((chat_id, text, reply_to))
        return f"waha-{len(self.sent)}"

    def download(self, url: str) -> bytes:
        return self.audio[url]

    def status(self, session: str) -> str:
        return self.statuses.get(session, "WORKING")


_ids = itertools.count(1)


def incoming(text: str = "hi", *, msg_id: str | None = None, group: str | None = None, mention: bool = False,
             phone: str | None = "923001234567", name: str = "Ali", kind: str = "text", audio: str | None = None,
             reply_to: str | None = None, channel: str = "meta") -> Incoming:
    """A message to the bot: Meta 1:1 by default, a WAHA group message when `group` is given."""
    msg_id = msg_id or f"msg-{next(_ids)}"
    common = dict(client_id="acme", msg_id=msg_id, sender_name=name, sender_phone=phone, kind=kind, text=text,
                  audio=audio, reply_to=reply_to)
    if group:
        return Incoming(channel="waha", chat_id=group, address=group, is_group=True,
                        sender_id=f"{phone or 'hidden'}@c.us", mentions_bot=mention, **common)
    if channel == "waha":
        chat = f"{phone}@c.us"
        return Incoming(channel="waha", chat_id=chat, address=chat, is_group=False, sender_id=chat, **common)
    user = f"user-{phone}"
    return Incoming(channel="meta", chat_id=user, address=phone or user, is_group=False, sender_id=user, **common)


def make_bot(*replies: ModelReply, clock=lambda: 1_790_000_000.0, **llm_options):
    client = make_client()
    llm = ScriptedLLM(*replies, **llm_options)
    bot = Bot(Store(":memory:"), bakery_sheets(), llm, FakeMeta(), FakeWaha(), {client.id: client}, clock=clock)
    return bot, llm


def texts(sender) -> list[str]:
    return [text for _, text, _ in sender.sent]


def acme_config() -> dict:
    """make_client()'s settings as the dashboard stores them."""
    return {
        "business": "Sweet Bakes", "bot_name": "Sara", "sheet_id": "sheet-1", "timezone": "Asia/Karachi",
        "instructions": "Orders need 24 hours notice.", "date_format": "%d/%m/%Y",
        "knowledge_tab": "Knowledge", "handoff_tab": "Handoffs",
        "tabs": {
            "Prices": {"customer": ["read"]},
            "Orders": {"customer": ["own", "append"], "owner_column": "Phone",
                       "fill": {"Name": "name", "Phone": "phone"}},
            "Staff Notes": {},
            "Expenses": {},
        },
        "staff_chats": ["staff@g.us"], "staff_numbers": ["923001111111"], "staff_alert_chat": "staff@g.us",
    }


def memory_registry(secret: str = "test-secret") -> Registry:
    return Registry(Db(":memory:"), Vault(secret))


def registry_with_acme(meta: bool = True) -> Registry:
    """A registry holding the acme bakery, its own Meta keys and its group number 'acme'."""
    registry = memory_registry()
    registry.create_business("acme", acme_config(), actor="test")
    if meta:
        registry.save_meta("acme", "106540352242922", "acme-token", "acme-secret", actor="test")
    registry.add_number("acme", "", actor="test")
    registry.assign_number("acme", "acme", actor="test")
    return registry
