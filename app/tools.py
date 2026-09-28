"""Model-facing tools and the permission rules behind them. The rules live here, never in the prompt."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from app.config import Client, same_phone

Role = Literal["staff", "customer"]
MAX_ROWS = 20
MAX_GROUPS = 30
TOTAL_ARGS = ("date_column", "from_date", "to_date", "sum_column", "group_by", "match")
NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


@dataclass(frozen=True)
class Caller:
    """Who is asking; decides which tabs and rows the tools touch."""
    role: Role
    in_group: bool
    name: str
    phone: str | None  # digits only; None when WhatsApp hides the number


TOOL_SPECS: list[dict] = [
    {"type": "function", "function": {
        "name": "lookup_rows",
        "description": "Search one tab of the business's Google Sheet. Returns up to 20 rows that contain "
                       "every word of the query. An empty query returns the first rows.",
        "parameters": {"type": "object", "properties": {
            "tab": {"type": "string", "description": "Tab name exactly as listed in your instructions."},
            "query": {"type": "string", "description": "Words to look for, e.g. a product name. May be empty."},
        }, "required": ["tab", "query"]},
    }},
    {"type": "function", "function": {
        "name": "total_rows",
        "description": "Count rows in one tab and add up a number column, optionally between two dates, only for "
                       "rows containing some words, and split by a column. Use it for every total or count, e.g. "
                       "'expenses in June' or 'perfumes sold this month'. Never add numbers up yourself.",
        "parameters": {"type": "object", "properties": {
            "tab": {"type": "string", "description": "Tab name exactly as listed in your instructions."},
            "date_column": {"type": "string", "description": "Column with each row's date, e.g. Date. Empty to ignore dates."},
            "from_date": {"type": "string", "description": "First day to include, YYYY-MM-DD. Empty for no start."},
            "to_date": {"type": "string", "description": "Last day to include, YYYY-MM-DD. Empty for no end."},
            "sum_column": {"type": "string", "description": "Number column to add up, e.g. Amount or Qty. Empty to only count."},
            "group_by": {"type": "string", "description": "Column to split the totals by, e.g. Category. May be empty."},
            "match": {"type": "string", "description": "Words every counted row must contain, e.g. perfume. May be empty."},
        }, "required": ["tab", *TOTAL_ARGS]},
    }},
    {"type": "function", "function": {
        "name": "propose_row",
        "description": "Add one row to a tab (an order, a lead, a booking, an expense). The system then either asks "
                       "the user to confirm or saves it and tells them; never say it is saved yourself.",
        "parameters": {"type": "object", "properties": {
            "tab": {"type": "string", "description": "Tab name exactly as listed in your instructions."},
            "values": {"type": "array", "description": "One entry per column to fill, using the tab's column names.",
                       "items": {"type": "object", "properties": {
                           "column": {"type": "string"}, "value": {"type": "string"}},
                           "required": ["column", "value"]}},
        }, "required": ["tab", "values"]},
    }},
    {"type": "function", "function": {
        "name": "handoff",
        "description": "Pass the conversation to a person at the business when the user asks for a human, "
                       "is upset, or you cannot help.",
        "parameters": {"type": "object", "properties": {
            "reason": {"type": "string", "description": "One short sentence for the staff."},
        }, "required": ["reason"]},
    }},
]


def can(client: Client, caller: Caller, tab: str, action: str) -> bool:
    """action is "read" (all rows), "own" (the caller's rows) or "append" (propose a new row)."""
    rule = client.tabs.get(tab)
    if rule is None:
        return False
    if caller.role == "staff":
        return action in ("read", "append")
    if caller.in_group and action != "read":
        return False  # a customer's own rows and new rows stay in private chats
    return action in rule.customer


def describe_tabs(client: Client, caller: Caller, sheets) -> str:
    """One line per tab this caller may use, with its columns, for the system prompt."""
    labels = {"read": "look up and total rows", "own": "look up and total this customer's own rows",
              "append": "add rows" if caller.role == "staff" else "propose new rows"}
    lines = []
    for tab in client.tabs:
        actions = [label for action, label in labels.items() if can(client, caller, tab, action)]
        if not actions:
            continue
        try:
            columns = f" (columns: {', '.join(sheets.headers(client.sheet_id, tab))})"
        except Exception:
            columns = ""
        lines.append(f"- {tab}{columns}: {', '.join(actions)}")
    return "\n".join(lines)


def _visible_rows(sheets, client: Client, caller: Caller, tab: str) -> list[dict] | dict:
    """The rows this caller may see in a tab, or {"error": ...}. Lookups and totals both go through here."""
    if tab not in client.tabs:
        return {"error": f"Unknown tab {tab!r}."}
    own_only = not can(client, caller, tab, "read")
    if own_only and not can(client, caller, tab, "own"):
        if caller.in_group and client.tabs[tab].customer:
            return {"error": "That is only shared in a private chat with the business."}
        return {"error": f"Tab {tab!r} is not available in this chat."}
    if own_only and not caller.phone:
        return {"error": "This customer's phone number is hidden, so their rows can't be found. "
                         "Offer a handoff."}
    rows = sheets.rows(client.sheet_id, tab)
    if own_only:
        owner = client.tabs[tab].owner_column
        rows = [r for r in rows if same_phone(str(r.get(owner, "")), caller.phone)]
    return rows


def _matching(rows: list[dict], words: str) -> list[dict]:
    wanted = words.lower().split()
    return [r for r in rows if all(w in " ".join(str(v) for v in r.values()).lower() for w in wanted)]


def lookup_rows(sheets, client: Client, caller: Caller, tab: str, query: str) -> dict:
    rows = _visible_rows(sheets, client, caller, tab)
    if isinstance(rows, dict):
        return rows
    rows = _matching(rows, query)
    return {"tab": tab, "rows": rows[:MAX_ROWS], "more": max(0, len(rows) - MAX_ROWS)}


def parse_date(value: object, date_format: str | None) -> date | None:
    """ISO dates (what the bot writes), else the client's format for dates typed into the Sheet by hand."""
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    if date_format:
        try:
            return datetime.strptime(text, date_format).date()
        except ValueError:
            pass
    return None


def parse_number(value: object) -> float | None:
    """1500, 1500.5, 'Rs. 1,500', '2,000/-' -> the number; blanks and words -> None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    found = NUMBER.search(str(value))
    return float(found.group().replace(",", "")) if found else None


def _num(x: float) -> int | float:
    return int(x) if x == int(x) else round(x, 2)


def total_rows(sheets, client: Client, caller: Caller, tab: str, date_column: str = "", from_date: str = "",
               to_date: str = "", sum_column: str = "", group_by: str = "", match: str = "") -> dict:
    """Count and add up rows in code, so a total never depends on the model's arithmetic."""
    rows = _visible_rows(sheets, client, caller, tab)
    if isinstance(rows, dict):
        return rows
    columns = list(rows[0]) if rows else []
    for column in (date_column, sum_column, group_by):
        if column and columns and column not in columns:
            return {"error": f"Unknown column {column!r}. Columns: {', '.join(columns)}."}
    try:
        start = date.fromisoformat(from_date) if from_date else None
        end = date.fromisoformat(to_date) if to_date else None
    except ValueError:
        return {"error": "Dates must look like 2026-06-30."}
    if (start or end) and not date_column:
        return {"error": "Give date_column to count by date."}
    counted, total, groups = 0, 0.0, {}
    skipped = {"unreadable_date": 0, "unreadable_number": 0}
    for row in _matching(rows, match):
        if start or end:
            day = parse_date(row.get(date_column, ""), client.date_format)
            if day is None:
                skipped["unreadable_date"] += 1
                continue
            if (start and day < start) or (end and day > end):
                continue
        amount = parse_number(row.get(sum_column, "")) if sum_column else 0.0
        if amount is None:
            skipped["unreadable_number"] += 1
            continue
        counted += 1
        total += amount
        if group_by:
            group = groups.setdefault(str(row.get(group_by, "")).strip() or "(blank)", [0, 0.0])
            group[0] += 1
            group[1] += amount
    result: dict = {"tab": tab, "rows_counted": counted, "skipped": skipped}
    if sum_column:
        result["total"] = _num(total)
    if group_by:
        ranked = sorted(groups.items(), key=lambda kv: (-kv[1][1], -kv[1][0]))
        result["by"] = {name: {"rows": n, **({"total": _num(t)} if sum_column else {})}
                        for name, (n, t) in ranked[:MAX_GROUPS]}
        if len(ranked) > MAX_GROUPS:
            result["more_groups"] = len(ranked) - MAX_GROUPS
    return result


def build_row(sheets, client: Client, caller: Caller, tab: str, values: list) -> dict:
    """Validate a proposed row: {"row": {...}} to show for confirmation, or {"error": ...} for the model."""
    if tab not in client.tabs:
        return {"error": f"Unknown tab {tab!r}."}
    if not can(client, caller, tab, "append"):
        if caller.in_group and "append" in client.tabs[tab].customer:
            return {"error": "New rows can only be added in a private chat with the business."}
        return {"error": f"Rows can't be added to {tab!r} from this chat."}
    headers = sheets.headers(client.sheet_id, tab)
    row: dict[str, str] = {}
    for pair in values:
        if not isinstance(pair, dict):
            continue
        column, value = str(pair.get("column", "")).strip(), str(pair.get("value", "")).strip()
        if column not in headers:
            return {"error": f"Unknown column {column!r}. Columns: {', '.join(headers)}."}
        if value:
            row[column] = value
    if not row:
        return {"error": "No values given."}
    if caller.role == "customer":
        for column, source in client.tabs[tab].fill.items():
            if source == "name" and caller.name:
                row[column] = caller.name
            elif source == "phone" and caller.phone:
                row[column] = caller.phone
            elif source == "phone" and not row.get(column):
                return {"error": "This customer's phone number is hidden. Ask for a contact number, "
                                 "then propose the row again with it."}
    return {"row": row}


def _bullets(row: dict[str, str]) -> str:
    return "\n".join(f"• {column}: {value}" for column, value in row.items())


def proposal_text(tab: str, row: dict[str, str]) -> str:
    return f"Add to {tab}:\n{_bullets(row)}\n\nReply YES to confirm or NO to cancel."


def saved_text(tab: str, row: dict[str, str]) -> str:
    return f"✅ Saved to {tab}:\n{_bullets(row)}"
