"""In-memory stand-ins shared by the tests and the eval runner. Later tasks append to this file."""
from __future__ import annotations

from app.config import Client, TabRule


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
