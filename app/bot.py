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

from app.config import Client, digits
from app.tools import (TOOL_SPECS, TOTAL_ARGS, Caller, build_row, describe_tabs, lookup_rows, proposal_text,
                       saved_text, total_rows)
from app.whatsapp import Incoming, SendError

log = logging.getLogger("bot")

MAX_MODEL_CALLS = 4
HISTORY = 50
BURST_LIMIT, BURST_WINDOW = 6, 600  # at most 6 bot replies per chat per 10 minutes (loop breaker)
MAX_TEXT = 4000  # WhatsApp rejects text bodies over 4096 characters
FALLBACK = "Sorry, I'm having trouble right now. The team will get back to you."
PENDING_TTL = 600  # seconds a proposed Sheet row waits for YES
# "ok"/"okay" are deliberately absent: people say them as acknowledgement, not confirmation.
YES = {"yes", "y", "yep", "yes please", "confirm", "haan", "han", "ji", "jee", "ہاں", "جی", "نعم", "👍"}
NO = {"no", "n", "nope", "cancel", "nahi", "nahin", "نہیں", "لا", "👎"}
MAX_AUDIO_BYTES = 1_000_000  # about 5 minutes of WhatsApp voice note
UNSUPPORTED = "I can read text and voice notes for now. Could you type that for me?"
TOO_LONG = "That voice note is too long for me. Could you send a shorter one or type it?"
UNHEARD = "Sorry, I couldn't make out that voice note. Could you type it?"


def normalize(text: str) -> str:
    return text.strip().lower().strip(" .!?,")


@dataclass
class Final:
    """A reply composed by code; it ends the model turn."""
    text: str


def role_for(client: Client, m: Incoming) -> str:
    if m.chat_id in client.staff_chats:
        return "staff"
    # In groups only the group decides, so a staff member can't pull private rows into a customer group.
    if not m.is_group and digits(m.sender_phone) in client.staff_numbers:
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
        # Voice media is fetched before the chat lock because WAHA deletes downloaded media after
        # WHATSAPP_FILES_LIFETIME (180 s by default), so waiting behind a slow model call could lose it.
        if m.kind == "audio" and m.audio:
            try:
                m.audio_bytes = self.meta.download(m.audio) if m.channel == "meta" else self.waha.download(m.audio)
            except Exception:
                log.exception("audio_download_failed client=%s chat=%s", m.client_id, self._h(m.chat_id))
        # ponytail: one message per chat at a time and no debounce; 3 quick messages get 3 replies.
        # Each waiting message holds one of the 40 worker threads, so a long model outage in a busy
        # chat can stall others; add a queue if that bites.
        with self._chat_locks[f"{m.client_id}:{m.chat_id}"]:
            try:
                self._handle(m)
            except Exception:
                log.exception("handle_failed client=%s chat=%s", m.client_id, self._h(m.chat_id))

    def greet(self, client_id: str, chat_id: str) -> None:
        """Introduce the bot when it joins a group, so members know an AI reads the chat."""
        with self._chat_locks[f"{client_id}:{chat_id}"]:
            try:
                client = self.clients[client_id]
                if not self.store.bot_has_spoken(client.id, chat_id):
                    self._deliver(client, "waha", chat_id, chat_id, intro(client, is_group=True))
            except Exception:
                log.exception("greet_failed client=%s chat=%s", client_id, self._h(chat_id))

    def _handle(self, m: Incoming) -> None:
        client = self.clients[m.client_id]
        now = self.clock()
        if not self.store.save_message(client.id, m.channel, m.msg_id, m.chat_id, m.sender_id,
                                       m.sender_name, m.text, m.from_me, now):
            return  # WhatsApp delivered this message before
        if m.from_me:
            return
        if m.kind == "audio":
            problem = self._transcribe(m)  # every note, so group history stays complete
            if problem:
                if self._addressed(m):
                    self._send(client, m, problem)  # _send applies the loop breaker
                return
        if self._answer_pending(client, m, now):
            return
        if not self._addressed(m):
            return
        if not self._reply_allowed(client, m, now):  # don't pay for a reply that can't be sent
            return
        if m.kind == "unsupported":
            self._send(client, m, UNSUPPORTED)
            return
        self._send(client, m, self._think(client, m, self._caller(client, m), now))

    def _reply_allowed(self, client: Client, m: Incoming, now: float) -> bool:
        """The loop breaker: at most BURST_LIMIT bot replies per chat per BURST_WINDOW."""
        if self.store.bot_replies_since(client.id, m.chat_id, now - BURST_WINDOW) >= BURST_LIMIT:
            log.warning("burst_limit client=%s chat=%s", client.id, self._h(m.chat_id))
            return False
        return True

    def _answer_pending(self, client: Client, m: Incoming, now: float) -> bool:
        """YES saves the sender's proposed row and NO drops it; only the customer who proposed it can answer."""
        word = normalize(m.text)
        if word not in YES and word not in NO:
            return False
        pending = self.store.get_pending(client.id, m.chat_id, m.sender_id, now)
        if pending is None:
            return False
        if not self._reply_allowed(client, m, now):
            return True  # can't confirm it, so don't act on it yet
        if word in NO:
            self.store.drop_pending(client.id, m.chat_id, m.sender_id)
            self._send(client, m, "Cancelled, nothing was saved.")
            return True
        tab, row = pending
        try:
            self.sheets.append(client.sheet_id, tab, row)
        except Exception:
            log.exception("append_failed client=%s tab=%s", client.id, tab)
            self._send(client, m, "Couldn't save that, reply YES to try again.")
            return True
        self.store.drop_pending(client.id, m.chat_id, m.sender_id)
        self._send(client, m, f"✅ Added to {tab}.")
        return True

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
            try:
                reply = self.llm.complete(messages, TOOL_SPECS)
            except Exception:
                log.exception("model_failed client=%s", client.id)
                self._handoff(client, m, "The assistant had an error.", now)
                return FALLBACK
            if not reply.tool_calls:
                if reply.text:
                    return reply.text
                self._handoff(client, m, "The assistant gave an empty answer.", now)
                return FALLBACK
            messages.append(reply.message)
            finals, results = [], []
            for tool_call in reply.tool_calls:
                result = self._run_tool(client, m, caller, tool_call.name, tool_call.arguments, now)
                if isinstance(result, Final):
                    finals.append(result.text)
                    if caller.role != "staff":
                        break  # one proposal per customer turn: a second would replace the pending one
                else:
                    results.append((tool_call, result))
            if finals:  # a code-composed reply ends the turn; failed staff saves are listed, never dropped
                failed = [r["error"] for c, r in results if c.name == "propose_row" and "error" in r]
                return "\n\n".join(finals + [f"⚠️ Not saved: {error}" for error in failed])
            for tool_call, result in results:
                messages.append({"role": "tool", "tool_call_id": tool_call.id,
                                 "content": json.dumps(result, ensure_ascii=False, default=str)})
        log.warning("model_budget_exhausted client=%s", client.id)
        self._handoff(client, m, "The assistant ran out of steps.", now)
        return FALLBACK

    def _run_tool(self, client: Client, m: Incoming, caller: Caller, name: str, args: dict,
                  now: float) -> dict | Final:
        tab = str(args.get("tab") or "")
        tab = next((t for t in client.tabs if t.lower() == tab.lower()), tab)
        try:
            if name == "lookup_rows":
                return lookup_rows(self.sheets, client, caller, tab, str(args.get("query") or ""))
            if name == "total_rows":
                return total_rows(self.sheets, client, caller, tab, **{k: str(args.get(k) or "") for k in TOTAL_ARGS})
            if name == "propose_row":
                values = args.get("values")
                result = build_row(self.sheets, client, caller, tab, values if isinstance(values, list) else [])
                if "error" in result:
                    return result
                if caller.role == "staff":  # staff rows save at once; the reply shows exactly what was saved
                    self.sheets.append(client.sheet_id, tab, result["row"])
                    return Final(saved_text(tab, result["row"]))
                self.store.put_pending(client.id, m.chat_id, m.sender_id, tab, result["row"], now + PENDING_TTL)
                return Final(proposal_text(tab, result["row"]))
            if name == "handoff":
                return self._handoff(client, m, str(args.get("reason") or ""), now)
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
        pending = self.store.get_pending(client.id, m.chat_id, m.sender_id, now)
        pending_rule = ""
        if pending:
            tab, _ = pending
            pending_rule = (f"- This customer has an unconfirmed proposal for {tab}. Their YES or NO confirms "
                            "or cancels it, so don't ask other yes/no questions; to change it, call propose_row "
                            "again with the whole row.\n")
        return (
            f"You are {client.bot_name}, the AI assistant of {client.business}, chatting in {where}. "
            f"You are talking to {who}.\n"
            "Rules:\n"
            f"- Only help with {client.business}. Politely decline anything unrelated.\n"
            "- If asked, say plainly that you are an AI assistant.\n"
            "- Reply in the user's language, briefly, like a WhatsApp message.\n"
            "- Never invent prices, stock, orders or policies. Use the knowledge below or look it up with "
            "lookup_rows. If you can't find it, say so and offer to pass it to the team with handoff.\n"
            "- If you asked for a contact number and the user sends one, call handoff again with that "
            "number in the reason.\n"
            "- For any total or count (spending in June, items sold this month), call total_rows and report "
            "its numbers, including skipped rows. Never add numbers up yourself.\n"
            "- To save an order, lead, booking or expense, call propose_row. Never say anything is saved; "
            "the system confirms it.\n"
            f"{pending_rule}"
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
        """Every user-facing reply goes through here, so the loop breaker gates them all."""
        if not self._reply_allowed(client, m, self.clock()):
            return
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

    def _transcribe(self, m: Incoming) -> str | None:
        """Fill m.text from the voice note. Returns a reply for the user when that isn't possible."""
        if m.audio_bytes is None:
            return UNHEARD  # the download failed before the chat lock was taken
        if len(m.audio_bytes) > MAX_AUDIO_BYTES:
            return TOO_LONG
        try:
            m.text = self.llm.transcribe(m.audio_bytes)
        except Exception:
            log.exception("transcribe_failed client=%s", m.client_id)
            return UNHEARD
        if not m.text:
            return UNHEARD
        self.store.set_text(m.client_id, m.channel, m.msg_id, m.text)
        return None

    def _handoff(self, client: Client, m: Incoming, reason: str, now: float) -> Final:
        local = datetime.fromtimestamp(now, ZoneInfo(client.timezone))
        row = {"Time": f"{local:%Y-%m-%d %H:%M}", "Name": m.sender_name, "Phone": m.sender_phone or "",
               "Chat": m.chat_id, "Question": m.text, "Reason": reason}
        try:
            self.sheets.append(client.sheet_id, client.handoff_tab, row)
        except Exception:
            log.exception("handoff_row_failed client=%s", client.id)
        if client.staff_alert_chat and client.waha_session:
            who = f"{m.sender_name or 'A customer'} ({m.sender_phone or 'number hidden'})"
            self._deliver(client, "waha", client.staff_alert_chat, client.staff_alert_chat,
                          f"🙋 {who} needs a person: {m.text[:300]}")
        ack = "I've passed this to the team. Someone will get back to you soon."
        if m.sender_phone or len(digits(m.text)) >= 9:
            return Final(ack)
        return Final(f"{ack} What's the best number to reach you on?")
