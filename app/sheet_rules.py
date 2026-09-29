"""Guardrails for the Sheet permissions screen: what a wrong tick could expose to customers."""
from __future__ import annotations

CONTACT_WORDS = ("phone", "mobile", "whatsapp", "number", "contact", "email", "cnic")


def sensitive_columns(headers: list[str]) -> list[str]:
    """Columns whose names suggest personal contact details."""
    return [h for h in headers if any(word in h.lower() for word in CONTACT_WORDS)]


def tab_problems(tab: str, rule: dict, headers: list[str], confirmed: bool) -> list[str]:
    """Why this tab's ticked permissions can't be saved; empty when they can."""
    problems = []
    customer = set(rule.get("customer") or [])
    if "own" in customer and rule.get("owner_column") not in headers:
        problems.append(f"{tab}: pick which column holds the customer's phone number.")
    for column in rule.get("fill") or {}:
        if column not in headers:
            problems.append(f"{tab}: column {column!r} is not in the tab.")
    exposed = sensitive_columns(headers)
    if "read" in customer and exposed and not confirmed:
        problems.append(f"{tab}: every customer would see {', '.join(exposed)}. Tick “I understand every customer "
                        "can see these columns” to allow it.")
    return problems
