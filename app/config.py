"""Settings from the environment, client settings from clients.yaml, phone helpers."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, fields
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

ACCESS = {"read", "own", "append"}
FILL_SOURCES = {"name", "phone"}


@dataclass(frozen=True)
class Settings:
    db_path: str = "data/assistant.db"
    backup_dir: str = "backups"
    clients_file: str = "clients.yaml"
    log_hash_key: str = "change-me"
    meta_app_secret: str = ""
    meta_verify_token: str = ""
    meta_access_token: str = ""
    meta_graph_version: str = "v26.0"
    waha_url: str = "http://localhost:3000"
    waha_api_key: str = ""
    waha_webhook_secret: str = ""
    llm_base_url: str = ""  # empty = OpenAI
    llm_api_key: str = ""
    llm_model: str = "gpt-6-luna"
    llm_reasoning_effort: str = ""  # empty = "none" on OpenAI, omitted elsewhere
    stt_base_url: str = ""  # empty = OpenAI
    stt_api_key: str = ""  # empty = reuse llm_api_key
    stt_model: str = "gpt-transcribe"
    google_service_account_file: str = "secrets/google-service-account.json"

    @classmethod
    def from_env(cls, **overrides: str) -> "Settings":
        values = {f.name: os.environ[f.name.upper()] for f in fields(cls) if os.environ.get(f.name.upper())}
        return cls(**{**values, **overrides})


def digits(phone: str | None) -> str:
    return re.sub(r"\D", "", phone or "")


def same_phone(a: str | None, b: str | None) -> bool:
    """Match on the last 9 digits, so '0300 1234567' matches '923001234567'."""
    # ponytail: suffix match; parse to E.164 (phonenumbers) once clients serve several countries.
    da, db = digits(a), digits(b)
    return len(da) >= 9 and len(db) >= 9 and da[-9:] == db[-9:]


@dataclass(frozen=True)
class TabRule:
    customer: frozenset[str] = frozenset()
    owner_column: str | None = None
    fill: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Client:
    id: str
    business: str
    bot_name: str
    sheet_id: str
    tabs: dict[str, TabRule]
    timezone: str = "UTC"
    instructions: str = ""
    knowledge_tab: str = "Knowledge"
    handoff_tab: str = "Handoffs"
    meta_phone_number_id: str | None = None
    waha_session: str | None = None
    staff_chats: frozenset[str] = frozenset()
    staff_numbers: frozenset[str] = frozenset()
    staff_alert_chat: str | None = None
    retention_days: int = 90
    date_format: str | None = None  # strptime pattern for dates typed into the Sheet by hand


def _tab_rule(client_id: str, tab: str, raw: dict) -> TabRule:
    customer = frozenset(raw.get("customer") or [])
    fill = {str(k): str(v) for k, v in (raw.get("fill") or {}).items()}
    if not customer <= ACCESS:
        raise ValueError(f"{client_id}.{tab}: customer access must be from {sorted(ACCESS)}")
    if "own" in customer and not raw.get("owner_column"):
        raise ValueError(f"{client_id}.{tab}: 'own' needs owner_column")
    if not set(fill.values()) <= FILL_SOURCES:
        raise ValueError(f"{client_id}.{tab}: fill values must be 'name' or 'phone'")
    return TabRule(customer=customer, owner_column=raw.get("owner_column"), fill=fill)


def load_clients(path: str) -> dict[str, Client]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    clients = {}
    for cid, c in (raw.get("clients") or {}).items():
        timezone = c.get("timezone", "UTC")
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"{cid}: unknown timezone {timezone!r}") from None
        clients[cid] = Client(
            id=cid,
            business=c["business"],
            bot_name=c["bot_name"],
            sheet_id=c["sheet_id"],
            tabs={tab: _tab_rule(cid, tab, rule or {}) for tab, rule in (c.get("tabs") or {}).items()},
            timezone=timezone,
            instructions=c.get("instructions", ""),
            knowledge_tab=c.get("knowledge_tab", "Knowledge"),
            handoff_tab=c.get("handoff_tab", "Handoffs"),
            meta_phone_number_id=str(c["meta_phone_number_id"]) if c.get("meta_phone_number_id") else None,
            waha_session=c.get("waha_session"),
            staff_chats=frozenset(c.get("staff_chats") or []),
            staff_numbers=frozenset(digits(str(n)) for n in c.get("staff_numbers") or []),
            staff_alert_chat=c.get("staff_alert_chat"),
            retention_days=int(c.get("retention_days", 90)),
            date_format=c.get("date_format"),
        )
    return clients
