import pytest

from app.config import Settings, load_clients, same_phone
from tests.fakes import make_client


def test_settings_come_from_env_with_defaults_and_overrides(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "gemini-3.8-flash")
    monkeypatch.setenv("DB_PATH", "")
    s = Settings.from_env(waha_url="http://waha:3000")
    assert s.llm_model == "gemini-3.8-flash"
    assert s.db_path == "data/assistant.db"  # empty variable = default
    assert s.waha_url == "http://waha:3000"
    assert s.meta_graph_version == "v26.0" and s.stt_model == "gpt-transcribe"


def test_example_clients_file_loads():
    c = load_clients("clients.example.yaml")["sweetbakes"]
    assert c.bot_name == "Sara" and c.meta_phone_number_id == "106540352242922"
    assert c.tabs["Orders"].customer == {"own", "append"} and c.tabs["Orders"].owner_column == "Phone"
    assert c.tabs["Orders"].fill == {"Name": "name", "Phone": "phone"}
    assert c.tabs["Handoffs"].customer == frozenset() and c.tabs["Expenses"].customer == frozenset()
    assert c.staff_numbers == {"923001111111"}  # stored as digits
    assert c.date_format == "%d/%m/%Y"


@pytest.mark.parametrize("tab_yaml, message", [
    ("Orders: {customer: [write]}", "customer access"),
    ("Orders: {customer: [own]}", "owner_column"),
    ("Orders: {customer: [append], fill: {Phone: email}}", "fill"),
])
def test_bad_tab_rules_are_rejected(tmp_path, tab_yaml, message):
    f = tmp_path / "clients.yaml"
    f.write_text("clients:\n  x:\n    business: B\n    bot_name: S\n    sheet_id: s\n    tabs:\n      "
                 + tab_yaml + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_clients(str(f))


def test_bad_timezone_is_rejected(tmp_path):
    f = tmp_path / "clients.yaml"
    f.write_text("clients:\n  x:\n    business: B\n    bot_name: S\n    sheet_id: s\n    timezone: Mars/Base\n",
                 encoding="utf-8")
    with pytest.raises(ValueError, match="timezone"):
        load_clients(str(f))


def test_phone_matching_ignores_format_and_country_prefix():
    assert same_phone("0300 1234567", "923001234567")
    assert same_phone("+92-300-1234567", "0300-1234567")
    assert not same_phone("0300 1234567", "0300 7654321")
    assert not same_phone("", "923001234567") and not same_phone(None, "923001234567")


def test_fake_client_matches_the_real_shape():
    assert make_client(bot_name="Zara").bot_name == "Zara"
