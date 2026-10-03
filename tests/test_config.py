from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from app.config import Settings, client_from_dict, load_clients, same_phone
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


def test_client_from_dict_matches_the_yaml_loader_and_hides_secrets():
    raw = yaml.safe_load(Path("clients.example.yaml").read_text(encoding="utf-8"))["clients"]["sweetbakes"]
    assert client_from_dict("sweetbakes", raw) == load_clients("clients.example.yaml")["sweetbakes"]
    secret = replace(make_client(), meta_access_token="EAAG-token", meta_app_secret="app-secret",
                     meta_verify_token="verify")
    assert "EAAG-token" not in repr(secret) and "app-secret" not in repr(secret) and "verify" not in repr(secret)


@pytest.mark.parametrize("change, message", [
    ({"business": ""}, "business is required"),
    ({"bot_name": None}, "bot_name is required"),
    ({"retention_days": 5000}, "between 1 and 3650"),
    ({"retention_days": "abc"}, "whole number"),
    ({"retention_days": 90.5}, "whole number"),
    ({"retention_days": 0}, "between 1 and 3650"),
])
def test_client_from_dict_explains_what_is_wrong(change, message):
    raw = {"business": "B", "bot_name": "S", "sheet_id": "s", **change}
    with pytest.raises(ValueError, match=message):
        client_from_dict("x", raw)


def test_new_settings_have_safe_defaults():
    s = Settings()
    assert s.secret_key == "" and s.public_url == ""
    assert s.waha_webhook_url == "http://engine:8000/webhooks/waha"


def test_personality_is_optional_and_read_from_settings():
    raw = {"business": "B", "bot_name": "S", "sheet_id": "s"}
    assert client_from_dict("x", raw).personality == ""
    assert client_from_dict("x", {**raw, "personality": "Warm."}).personality == "Warm."


def test_web_search_switches_default_off_and_are_read_from_settings():
    base = {"business": "B", "bot_name": "Sara", "sheet_id": "s"}
    off = client_from_dict("b", base)
    assert off.web_search_staff is False and off.web_search_customers is False
    on = client_from_dict("b", {**base, "web_search_staff": True, "web_search_customers": True})
    assert on.web_search_staff is True and on.web_search_customers is True
