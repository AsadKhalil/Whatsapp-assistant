"""The message pipeline: store, decide, think with tools, reply."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import Client, same_phone
from app.tools import TOOL_SPECS, TOTAL_ARGS, Caller, describe_tabs, lookup_rows, total_rows
from app.whatsapp import Incoming, SendError

log = logging.getLogger("bot")

MAX_MODEL_CALLS = 4
HISTORY = 50
BURST_LIMIT, BURST_WINDOW = 6, 600  # at most 6 bot replies per chat per 10 minutes (loop breaker)
MAX_TEXT = 4000  # WhatsApp rejects text bodies over 4096 characters
FALLBACK = "Sorry, I'm having trouble right now. The team will get back to you."


@dataclass
class Final:
    """A reply composed by code; it ends the model turn."""
    text: str


def role_for(client: Client, m: Incoming) -> str:
    if m.chat_id in client.staff_chats:
        return "staff"
    # In groups only the group decides, so a staff member can't pull private rows into a customer group.
    if not m.is_group and m.sender_phone and any(same_phone(m.sender_phone, n) for n in client.staff_numbers):
        return "staff"
    return "customer"


def intro(client: Client, is_group: bool) -> str:
    text = f"Hi, I'm {client.bot_name}, {client.business}'s AI assistant."
    return text + (" I read messages here so I can answer when you @mention me." if is_group else "")


class Bot:
    def __init__(self, store, sheets, llm, meta, waha, clients: dict[str, Client], log_key: str = "",
                 clock=time.time) -> None:
        self.store, self.sheets, self.llm, self.meta, self.waha = store, sheets, llm, meta, waha
        self.clients = clients
        self.clock = clock
        self._log_key = log_key.encode()
        self._chat_locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)

    def _h(self, value: str) -> str:
        """Short keyed hash so logs can follow a chat without holding the number."""
        return hmac.new(self._log_key, value.encode(), hashlib.sha256).hexdigest()[:12]

    def handle(self, m: Incoming) -> None:
        # ponytail: one message per chat at a time and no debounce; 3 quick messages get 3 replies.
        with self._chat_locks[f"{m.client_id}:{m.chat_id}"]:
            try:
                self._handle(m)
            except Exception:
                log.exception("handle_failed client=%s chat=%s", m.client_id, self._h(m.chat_id))

    def greet(self, client_id: str, chat_id: str) -> None:
        """Introduce the bot when it joins a group, so members know an AI reads the chat."""
        client = self.clients[client_id]
        with self._chat_locks[f"{client_id}:{chat_id}"]:
            if not self.store.bot_has_spoken(client.id, chat_id):
                self._deliver(client, "waha", chat_id, chat_id, intro(client, is_group=True))

    def _handle(self, m: Incoming) -> None:
        client = self.clients[m.client_id]
        now = self.clock()
        if not self.store.save_message(client.id, m.channel, m.msg_id, m.chat_id, m.sender_id,
                                       m.sender_name, m.text, m.from_me, now):
            return  # WhatsApp delivered this message before
        if m.from_me or not self._addressed(m):
            return
        if self.store.bot_replies_since(client.id, m.chat_id, now - BURST_WINDOW) >= BURST_LIMIT:
            log.warning("burst_limit client=%s chat=%s", client.id, self._h(m.chat_id))
            return
        self._send(client, m, self._think(client, m, self._caller(client, m), now))

    def _caller(self, client: Client, m: Incoming) -> Caller:
        return Caller(role_for(client, m), m.is_group, m.sender_name, m.sender_phone)

    def _addressed(self, m: Incoming) -> bool:
        if not m.is_group:
            return True
        return m.mentions_bot or (m.reply_to is not None
                                  and self.store.is_bot_message(m.client_id, m.channel, m.reply_to))

    def _think(self, client: Client, m: Incoming, caller: Caller, now: float) -> str:
        messages = [{"role": "system", "content": self._system_prompt(client, m, caller, now)},
                    *self._history(client, m)]
        for _ in range(MAX_MODEL_CALLS):
            reply = self.llm.complete(messages, TOOL_SPECS)
            if not reply.tool_calls:
                return reply.text or FALLBACK
            messages.append(reply.message)
            for tool_call in reply.tool_calls:
                result = self._run_tool(client, m, caller, tool_call.name, tool_call.arguments, now)
                if isinstance(result, Final):
                    return result.text
                messages.append({"role": "tool", "tool_call_id": tool_call.id,
                                 "content": json.dumps(result, ensure_ascii=False, default=str)})
        log.warning("model_budget_exhausted client=%s", client.id)
        return FALLBACK

    def _run_tool(self, client: Client, m: Incoming, caller: Caller, name: str, args: dict,
                  now: float) -> dict | Final:
        tab = str(args.get("tab", ""))
        try:
            if name == "lookup_rows":
                return lookup_rows(self.sheets, client, caller, tab, str(args.get("query", "")))
            if name == "total_rows":
                return total_rows(self.sheets, client, caller, tab, **{k: str(args.get(k, "")) for k in TOTAL_ARGS})
        except Exception:
            log.exception("tool_failed tool=%s client=%s", name, client.id)
            return {"error": "The sheet couldn't be reached right now."}
        return {"error": f"Unknown tool {name!r}."}

    def _system_prompt(self, client: Client, m: Incoming, caller: Caller, now: float) -> str:
        try:
            knowledge = self.sheets.knowledge(client.sheet_id, client.knowledge_tab, now)
        except Exception:
            log.exception("knowledge_failed client=%s", client.id)
            knowledge = ""
        local = datetime.fromtimestamp(now, ZoneInfo(client.timezone))
        who = "a staff member of the business" if caller.role == "staff" else "a customer"
        where = ("a WhatsApp group; each message starts with the sender's name" if m.is_group
                 else "a private WhatsApp chat")
        return (
            f"You are {client.bot_name}, the AI assistant of {client.business}, chatting in {where}. "
            f"You are talking to {who}.\n"
            "Rules:\n"
            f"- Only help with {client.business}. Politely decline anything unrelated.\n"
            "- If asked, say plainly that you are an AI assistant.\n"
            "- Reply in the user's language, briefly, like a WhatsApp message.\n"
            "- Never invent prices, stock, orders or policies. Use the knowledge below or look it up with "
            "lookup_rows. If you can't find it, say so and offer to pass it to the team with handoff.\n"
            "- For any total or count (spending in June, items sold this month), call total_rows and report "
            "its numbers, including skipped rows. Never add numbers up yourself.\n"
            "- To save an order, lead, booking or expense, call propose_row. Never say anything is saved; "
            "the system confirms it.\n"
            "- Write dates as YYYY-MM-DD.\n"
            f"- Current time: {local:%A %d %B %Y %H:%M} ({client.timezone}).\n\n"
            f"Sheet tabs you can use:\n{describe_tabs(client, caller, self.sheets) or '(none)'}\n\n"
            f"Business instructions:\n{client.instructions.strip() or '(none)'}\n\n"
            f"Business knowledge:\n{knowledge or '(none)'}"
        )

    def _history(self, client: Client, m: Incoming) -> list[dict]:
        out = []
        for row in self.store.history(client.id, m.chat_id, HISTORY):
            if not row["text"]:
                continue
            if row["from_bot"]:
                out.append({"role": "assistant", "content": row["text"]})
            elif m.is_group:
                out.append({"role": "user", "content": f"{row['sender_name'] or 'Someone'}: {row['text']}"})
            else:
                out.append({"role": "user", "content": row["text"]})
        return out

    def _send(self, client: Client, m: Incoming, text: str) -> None:
        if not self.store.bot_has_spoken(client.id, m.chat_id):
            text = f"{intro(client, m.is_group)}\n\n{text}"
        self._deliver(client, m.channel, m.chat_id, m.address, text, reply_to=m.msg_id if m.is_group else None)

    def _deliver(self, client: Client, channel: str, chat_id: str, address: str, text: str,
                 reply_to: str | None = None) -> None:
        text = text[:MAX_TEXT]
        try:
            if channel == "meta":
                msg_id = self.meta.send_text(client.meta_phone_number_id, address, text)
            else:
                msg_id = self.waha.send_text(client.waha_session, address, text, reply_to=reply_to)
        except SendError as e:
            log.warning("send_failed client=%s chat=%s error=%s", client.id, self._h(chat_id), e)
            return
        self.store.save_message(client.id, channel, msg_id or f"local-{uuid.uuid4().hex}", chat_id,
                                "bot", client.bot_name, text, True, self.clock())
