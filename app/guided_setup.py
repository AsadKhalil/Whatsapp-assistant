"""Guided setup: an AI interview drafts the Sheet tabs, Knowledge rows, permissions and persona; Apply adds them.

The AI only drafts. Apply is plain code that adds tabs, columns and Knowledge rows and saves settings. It never
deletes, renames or moves anything, so pressing it again finishes a job that stopped part-way.
"""
from __future__ import annotations

from app.config import FILL_SOURCES, client_from_dict
from app.sheet_rules import tab_problems

MAX_TABS, MAX_COLUMNS, MAX_ROWS = 10, 20, 60
LIMITS = {"bot_name": 40, "personality": 1500, "instructions": 4000}
LABELS = {"bot_name": "Bot name", "personality": "Personality", "instructions": "Instructions"}
PERSONA = tuple(LABELS)
KNOWLEDGE_COLUMNS = ["Question", "Answer"]
HANDOFF_COLUMNS = ["Time", "Name", "Phone", "Chat", "Question", "Reason"]  # what Bot._handoff writes
BAD_NAME_CHARACTERS = set("[]*?/\\:")  # Google refuses these in tab names

PROPOSE_SETUP_SPEC: dict = {"type": "function", "function": {
    "name": "propose_setup",
    "description": "Propose the whole setup for the owner to review: the bot's persona, the Sheet tabs with their "
                   "columns and what customers may do on each, and Knowledge questions with answers. Nothing "
                   "changes until the owner applies it.",
    "parameters": {"type": "object", "properties": {
        "bot_name": {"type": "string", "description": "The assistant's name, at most 40 characters."},
        "personality": {"type": "string", "description": "How the bot sounds: tone, emoji, formality, greetings. "
                                                         "At most 1,500 characters."},
        "instructions": {"type": "string", "description": "Rules the bot follows: hours, delivery, policies. "
                                                          "At most 4,000 characters."},
        "tabs": {"type": "array", "description": "At most 10 tabs, not counting the Knowledge and Handoffs tabs.",
                 "items": {"type": "object", "properties": {
                     "name": {"type": "string", "description": "A short tab name, e.g. Orders."},
                     "purpose": {"type": "string", "description": "One line: what the tab is for."},
                     "columns": {"type": "array", "items": {"type": "string"},
                                 "description": "Column names, at most 20, each at most 40 characters."},
                     "customer": {"type": "array", "items": {"type": "string", "enum": ["read", "own", "append"]},
                                  "description": "What customers may do: read all rows, see only their own rows "
                                                 "(own), add rows (append). Empty for staff only."},
                     "owner_column": {"type": "string",
                                      "description": "With own: the column holding the customer's phone number."},
                     "name_column": {"type": "string", "description": "With append: the column the system fills "
                                                                      "with the customer's WhatsApp name."},
                     "phone_column": {"type": "string", "description": "With append: the column the system fills "
                                                                       "with the customer's phone number."},
                 }, "required": ["name", "purpose", "columns", "customer"]}},
        "knowledge": {"type": "array", "description": "At most 60 questions customers ask, with the answers. Never "
                                                      "private information: anyone who messages the bot sees it.",
                      "items": {"type": "object", "properties": {
                          "question": {"type": "string"}, "answer": {"type": "string"}},
                          "required": ["question", "answer"]}},
    }, "required": ["bot_name", "personality", "instructions", "tabs", "knowledge"]},
}}


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def split_columns(value) -> list[str]:
    """Column names from a list or a comma-separated string. Commas always separate: the form edits them so."""
    items = value if isinstance(value, list) else [value]
    return [c.strip() for item in items if isinstance(item, str) for c in item.split(",") if c.strip()]


def find_tab(name: str, names) -> str | None:
    """The tab called `name` ignoring case (Google treats such names as the same tab), or None."""
    return next((t for t in names if t.casefold() == name.casefold()), None)


def has_permissions(name: str, config: dict) -> bool:
    """Whether the tab already has saved permissions; setup never changes those."""
    return find_tab(name, config.get("tabs") or {}) is not None


def _spelled(name: str, columns: list[str]) -> str:
    """`name` spelled like the matching column, so the column pickers show it."""
    return find_tab(name, columns) or name


def draft_from_args(args: dict, config: dict) -> dict:
    """propose_setup's arguments as a draft: every tab used, every row kept, Replace ticked where nothing is saved."""
    tabs = []
    for raw in args.get("tabs") if isinstance(args.get("tabs"), list) else []:
        if not isinstance(raw, dict):
            continue
        columns = split_columns(raw.get("columns"))
        fill = {}
        if isinstance(raw.get("fill"), dict):
            fill = {_text(k): v for k, v in raw["fill"].items() if isinstance(v, str) and v in FILL_SOURCES}
        for source in ("name", "phone"):
            if _text(raw.get(f"{source}_column")):
                fill[_text(raw.get(f"{source}_column"))] = source
        customer = raw.get("customer") if isinstance(raw.get("customer"), list) else []
        tabs.append({"name": _text(raw.get("name")), "purpose": _text(raw.get("purpose")), "columns": columns,
                     "customer": [access for access in ("read", "own", "append") if access in customer],
                     "owner_column": _spelled(_text(raw.get("owner_column")), columns),
                     "fill": {_spelled(column, columns): source for column, source in fill.items() if column},
                     "use": True, "confirmed": False})
    knowledge = [{"question": _text(row.get("question")), "answer": _text(row.get("answer")), "keep": True}
                 for row in (args.get("knowledge") if isinstance(args.get("knowledge"), list) else [])
                 if isinstance(row, dict)]
    return {**{key: _text(args.get(key)) for key in PERSONA},
            "replace": {key: not str(config.get(key) or "").strip() for key in PERSONA},
            "tabs": tabs, "knowledge": [row for row in knowledge if row["question"] or row["answer"]]}


def system_tabs(config: dict) -> list[tuple[str, list[str]]]:
    """The Knowledge and Handoffs tabs, under the business's names for them, with the columns the bot uses."""
    return [(config.get("knowledge_tab") or "Knowledge", KNOWLEDGE_COLUMNS),
            (config.get("handoff_tab") or "Handoffs", HANDOFF_COLUMNS)]


def tab_plan(name: str, columns: list[str], sheet_tabs: dict[str, list[str]]) -> dict:
    """How a drafted tab meets the Sheet: the existing tab's title (or None), the columns to add, the final headers."""
    existing = find_tab(name, sheet_tabs)
    current = sheet_tabs[existing] if existing else []
    have = {h.casefold() for h in current}
    add = [c for c in columns if c.casefold() not in have]
    return {"existing": existing, "add": add, "headers": current + add}


def rule_of(tab: dict) -> dict:
    """A drafted tab's permissions as the Sheet page saves them."""
    rule: dict = {"customer": list(tab["customer"])}
    if "own" in tab["customer"]:
        rule["owner_column"] = tab["owner_column"]
    if "append" in tab["customer"]:
        rule["fill"] = dict(tab["fill"])
    return rule


def setup_changes(draft: dict, sheet_tabs: dict[str, list[str]], config: dict) -> dict:
    """The settings Apply saves: permissions for used tabs that have none yet, and each persona field ticked Replace."""
    saved = dict(config.get("tabs") or {})
    added = {}
    for tab in draft["tabs"]:
        name = find_tab(tab["name"], sheet_tabs) or tab["name"]
        if tab["use"] and not has_permissions(name, config):
            added[name] = rule_of(tab)
    changes: dict = {key: draft[key] for key in PERSONA if draft["replace"].get(key)}
    if added:
        changes["tabs"] = {**saved, **added}
    return changes


def check_draft(draft: dict, sheet_tabs: dict[str, list[str]], config: dict) -> list[tuple[str, str]]:
    """What stops a draft being applied, as (where, message): where is "persona", "tab{i}", "row{i}" or ""."""
    problems: list[tuple[str, str]] = []
    if not 1 <= len(draft["bot_name"]) <= LIMITS["bot_name"]:
        problems.append(("persona", f"Bot name: 1 to {LIMITS['bot_name']} characters."))
    for key in ("personality", "instructions"):
        if len(draft[key]) > LIMITS[key]:
            problems.append(("persona", f"{LABELS[key]}: at most {LIMITS[key]:,} characters."))
    used = [(i, tab) for i, tab in enumerate(draft["tabs"]) if tab["use"]]
    if len(used) > MAX_TABS:
        problems.append(("", f"At most {MAX_TABS} tabs: untick some."))
    reserved = {name.casefold() for name, _ in system_tabs(config)}
    seen: set[str] = set()
    for i, tab in used:
        name, columns, where = tab["name"], tab["columns"], f"tab{i}"
        label = name or f"Tab {i + 1}"
        if not 1 <= len(name) <= 100:
            problems.append((where, f"{label}: a tab name is 1 to 100 characters."))
        if BAD_NAME_CHARACTERS & set(name):
            problems.append((where, f"{label}: a tab name can't contain [ ] * ? / \\ or :."))
        if name.casefold() in reserved:
            problems.append((where, f"{label}: that's the Knowledge or Handoffs tab, which setup adds by itself."))
        if name.casefold() in seen:
            problems.append((where, f"{label}: two tabs have this name."))
        seen.add(name.casefold())
        if len(columns) > MAX_COLUMNS:
            problems.append((where, f"{label}: at most {MAX_COLUMNS} columns."))
        long = [c for c in columns if len(c) > 40]
        if long:
            problems.append((where, f"{label}: column names are at most 40 characters ({', '.join(long)})."))
        if len({c.casefold() for c in columns}) < len(columns):
            problems.append((where, f"{label}: two columns have the same name."))
        plan = tab_plan(name, columns, sheet_tabs)
        if plan["existing"] is None and not columns:
            problems.append((where, f"{label}: a new tab needs at least one column."))
        if not has_permissions(plan["existing"] or name, config):
            problems += [(where, p) for p in tab_problems(plan["existing"] or name, rule_of(tab), plan["headers"],
                                                          confirmed=tab["confirmed"])]
    kept = [(i, row) for i, row in enumerate(draft["knowledge"]) if row["keep"]]
    if len(kept) > MAX_ROWS:
        problems.append(("", f"At most {MAX_ROWS} Knowledge rows: remove some."))
    for i, row in kept:
        if not row["question"] or not row["answer"]:
            problems.append((f"row{i}", f"Knowledge row {i + 1}: it needs a question and an answer."))
        if len(row["question"]) > 200 or len(row["answer"]) > 1000:
            problems.append((f"row{i}", f"Knowledge row {i + 1}: a question is at most 200 characters, an answer "
                                        "at most 1,000."))
    if not problems:  # last, exactly as any settings save would check it
        try:
            client_from_dict("setup", {**config, **setup_changes(draft, sheet_tabs, config)})
        except ValueError as e:
            problems.append(("", str(e)))
    return problems
