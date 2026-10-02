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
from app.whatsapp import Incoming, SendError


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


class Forbidden(Exception):
    """What Google raises when the Sheet is no longer shared with the robot account."""
    code = 403


class FakeSheets:
    def __init__(self, tabs: dict[str, list[dict]], headers: dict[str, list[str]] | None = None) -> None:
        self.tabs = {name: [dict(r) for r in rows] for name, rows in tabs.items()}
        self._headers = headers or {}
        self.appended: list[tuple[str, dict]] = []
        self.fail_append = False
        self.fail_tabs: Exception | None = None  # raised by tab_headers, like an unshared or deleted Sheet
        self.written: list[tuple] = []  # add_tab / add_columns / append_rows calls, in order
        self.fail_writes: set[str] = set()  # tabs whose writes raise Forbidden
        self.tab_reads = 0  # tab_headers calls: each costs Google one read per tab

    def rows(self, sheet_id: str, tab: str) -> list[dict]:
        return [dict(r) for r in self.tabs[tab]]  # KeyError for a missing tab, like a renamed sheet

    def headers(self, sheet_id: str, tab: str, now: float | None = None) -> list[str]:
        if tab in self._headers:
            return self._headers[tab]
        return list(self.tabs[tab][0]) if self.tabs.get(tab) else []

    def tab_headers(self, sheet_id: str) -> dict[str, list[str]]:
        self.tab_reads += 1
        if self.fail_tabs:
            raise self.fail_tabs
        return {name: self.headers(sheet_id, name) for name in self.tabs}

    def append(self, sheet_id: str, tab: str, row: dict[str, str]) -> None:
        if self.fail_append:
            raise RuntimeError("Sheets is down")
        self.appended.append((tab, dict(row)))
        self.tabs.setdefault(tab, []).append(dict(row))

    def _write(self, kind: str, tab: str, value) -> None:
        if tab in self.fail_writes:
            raise Forbidden(tab)
        self.written.append((kind, tab, value))

    def add_tab(self, sheet_id: str, tab: str, headers: list[str]) -> None:
        self._write("add_tab", tab, list(headers))
        self.tabs[tab] = []
        self._headers[tab] = list(headers)

    def add_columns(self, sheet_id: str, tab: str, columns: list[str]) -> None:
        self._write("add_columns", tab, list(columns))
        self._headers[tab] = self.headers(sheet_id, tab) + list(columns)

    def append_rows(self, sheet_id: str, tab: str, rows: list[dict[str, str]]) -> None:
        self._write("append_rows", tab, [dict(r) for r in rows])
        self.tabs[tab].extend(dict(r) for r in rows)

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
        self.tools: list[list[str]] = []  # the tool names offered on each call

    def complete(self, messages: list, tools: list[dict]) -> ModelReply:
        self.tools.append([t["function"]["name"] for t in tools])
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
        self.tokens: list[str | None] = []  # the token of every send and download
        self.info: dict | Exception = {"display_phone_number": "+1 555 0100", "verified_name": "Sweet Bakes"}

    def send_text(self, phone_number_id: str, to: str, text: str, reply_to: str | None = None,
                  token: str | None = None) -> str:
        if self.fail:
            raise self.fail
        self.tokens.append(token)
        self.sent.append((to, text, reply_to))
        return f"wamid.out-{len(self.sent)}"

    def download(self, media_id: str, token: str | None = None) -> bytes:
        self.tokens.append(token)
        return self.audio[media_id]

    def number_info(self, phone_number_id: str, token: str | None = None) -> dict:
        if isinstance(self.info, Exception):
            raise self.info
        return self.info


class FakeWaha:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str | None]] = []
        self.audio: dict[str, bytes] = {}
        self.statuses: dict[str, str] = {}
        self.fail: Exception | None = None
        self.created: list[tuple[str, str, str]] = []  # sessions the dashboard created: (name, url, secret)
        self.calls: list[tuple[str, str]] = []  # (action, session) for create/start/logout/delete/qr
        self.phones: dict[str, str] = {}  # session -> linked jid, reported once WORKING
        self.group_list: dict[str, list[dict]] = {}
        self.manage_fail: Exception | None = None

    def send_text(self, session: str, chat_id: str, text: str, reply_to: str | None = None) -> str:
        if self.fail:
            raise self.fail
        self.sent.append((chat_id, text, reply_to))
        return f"waha-{len(self.sent)}"

    def download(self, url: str) -> bytes:
        return self.audio[url]

    def status(self, session: str) -> str:
        return self.statuses.get(session, "WORKING")

    def _manage(self, action: str, name: str) -> None:
        if self.manage_fail:
            raise self.manage_fail
        self.calls.append((action, name))

    def create_session(self, name: str, webhook_url: str, webhook_secret: str) -> None:
        self._manage("create", name)
        self.created.append((name, webhook_url, webhook_secret))
        self.statuses[name] = "SCAN_QR_CODE"

    def start(self, name: str) -> None:
        self._manage("start", name)
        self.statuses[name] = "SCAN_QR_CODE"

    def logout(self, name: str) -> None:
        self._manage("logout", name)
        self.statuses[name] = "STOPPED"

    def delete(self, name: str) -> None:
        self._manage("delete", name)
        self.statuses.pop(name, None)

    def session_info(self, name: str) -> dict:
        if self.manage_fail:
            raise self.manage_fail
        if name not in self.statuses:
            raise SendError("waha status=404")
        info: dict = {"name": name, "status": self.statuses[name]}
        if name in self.phones:
            info["me"] = {"id": self.phones[name]}
        return info

    def qr_png(self, name: str) -> bytes:
        self._manage("qr", name)
        return b"\x89PNG fake qr"

    def groups(self, name: str) -> list[dict]:
        if self.manage_fail:
            raise self.manage_fail
        return self.group_list.get(name, [])


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
    bot = Bot(Store(":memory:"), bakery_sheets(), llm, FakeMeta(), FakeWaha(), {client.id: client}, clock=clock,
              mailer=FakeMailer())
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


# A valid propose_setup call for the bakery: one new tab, one existing tab named in another case, two questions
# (the second is already in bakery_sheets()'s Knowledge tab, spelled differently).
SETUP_ARGS = {
    "bot_name": "Mia", "personality": "Warm and casual. One emoji at most.",
    "instructions": "We deliver within Lahore only.",
    "tabs": [{"name": "Bookings", "purpose": "Table bookings", "columns": ["Date", "Name", "Phone", "Guests"],
              "customer": ["own", "append"], "owner_column": "Phone", "name_column": "Name",
              "phone_column": "Phone"},
             {"name": "orders", "purpose": "Cake orders", "columns": ["Date", "Item", "Status"],
              "customer": ["read"]}],
    "knowledge": [{"question": "What are your hours?", "answer": "Tue-Sun 10am-8pm"},
                  {"question": " delivery? ", "answer": "Free above Rs 3000"}],
}


class FakeMailer:
    """Records emails instead of sending them; set `fail` to a MailError to make sending fail."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.fail: Exception | None = None

    def send(self, address: str, app_password: str, sender_name: str, to: str, subject: str, body: str) -> None:
        if self.fail is not None:
            raise self.fail
        self.sent.append({"address": address, "app_password": app_password, "sender_name": sender_name,
                          "to": to, "subject": subject, "body": body})
