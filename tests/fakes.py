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
