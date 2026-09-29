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
    secret_key: str = ""  # required by the dashboard: encrypts Meta keys and TOTP secrets in the database
    public_url: str = ""  # e.g. https://bot.example.com; compose sets it from DOMAIN
    waha_webhook_url: str = "http://engine:8000/webhooks/waha"  # where WAHA sessions created by the dashboard post

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
    meta_access_token: str = field(default="", repr=False)  # this business's own Meta keys (from the dashboard)
    meta_app_secret: str = field(default="", repr=False)
    meta_verify_token: str = field(default="", repr=False)


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


def client_from_dict(client_id: str, c: dict) -> Client:
    """One client from a clients.yaml entry or a stored business config; raises ValueError saying what's wrong."""
    for key in ("business", "bot_name", "sheet_id"):
        if not str(c.get(key) or "").strip():
            raise ValueError(f"{client_id}: {key} is required")
    timezone = c.get("timezone") or "UTC"
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"{client_id}: unknown timezone {timezone!r}") from None
    try:
        retention_days = int(c.get("retention_days") or 90)
    except (TypeError, ValueError):
        raise ValueError(f"{client_id}: retention_days must be a whole number of days") from None
    if not 1 <= retention_days <= 3650:
        raise ValueError(f"{client_id}: retention_days must be between 1 and 3650")
    return Client(
        id=client_id,
        business=str(c["business"]),
        bot_name=str(c["bot_name"]),
        sheet_id=str(c["sheet_id"]),
        tabs={tab: _tab_rule(client_id, tab, rule or {}) for tab, rule in (c.get("tabs") or {}).items()},
        timezone=timezone,
        instructions=c.get("instructions") or "",
        knowledge_tab=c.get("knowledge_tab") or "Knowledge",
        handoff_tab=c.get("handoff_tab") or "Handoffs",
        meta_phone_number_id=str(c["meta_phone_number_id"]) if c.get("meta_phone_number_id") else None,
        waha_session=c.get("waha_session") or None,
        staff_chats=frozenset(c.get("staff_chats") or []),
        staff_numbers=frozenset(digits(str(n)) for n in c.get("staff_numbers") or []),
        staff_alert_chat=c.get("staff_alert_chat") or None,
        retention_days=retention_days,
        date_format=c.get("date_format") or None,
    )


def load_clients(path: str) -> dict[str, Client]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return {cid: client_from_dict(cid, c or {}) for cid, c in (raw.get("clients") or {}).items()}
