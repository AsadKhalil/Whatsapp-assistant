import json

import pytest

from app.config import Settings
from app.registry import Registry
from app.vault import Vault
from tests.fakes import acme_config, memory_registry, registry_with_acme


def test_a_new_business_becomes_an_engine_client():
    client = registry_with_acme().clients()["acme"]
    assert client.bot_name == "Sara" and client.waha_session == "acme"
    assert client.meta_phone_number_id == "106540352242922"
    assert client.meta_access_token == "acme-token" and client.meta_app_secret == "acme-secret"
    assert client.tabs["Orders"].owner_column == "Phone" and client.staff_numbers == {"923001111111"}
    assert len(client.meta_verify_token) >= 30


@pytest.mark.parametrize("business_id, change, message", [
    ("Sweet_Bakes", {}, "web id"),
    ("acme", {"timezone": "Mars/Base"}, "timezone"),
    ("acme", {"colour": "red"}, "Unknown settings"),
])
def test_invalid_businesses_are_refused(business_id, change, message):
    with pytest.raises(ValueError, match=message):
        memory_registry().create_business(business_id, {**acme_config(), **change}, actor="t")


def test_duplicate_business_ids_are_refused():
    with pytest.raises(ValueError, match="already exists"):
        registry_with_acme().create_business("acme", acme_config(), actor="t")


def test_saving_settings_merges_validates_and_audits_only_what_changed():
    registry = registry_with_acme()
    registry.save_config("acme", {"bot_name": "Zara", "business": "Sweet Bakes"}, actor="7")
    assert registry.clients()["acme"].bot_name == "Zara"
    entry = registry.audit_log("acme")[0]
    assert entry["action"] == "settings.save" and entry["actor"] == "7"
    assert json.loads(entry["detail"]) == {"bot_name": "Zara"}
    with pytest.raises(ValueError, match="timezone"):
        registry.save_config("acme", {"timezone": "Mars/Base"}, actor="7")
    assert registry.clients()["acme"].timezone == "Asia/Karachi"


def test_meta_keys_are_sealed_kept_when_blank_and_never_audited():
    registry = registry_with_acme()
    row = registry.db.one("SELECT * FROM businesses WHERE id = 'acme'")
    assert "acme-token" not in row["meta_access_token"] and "acme-secret" not in row["meta_app_secret"]
    registry.save_meta("acme", "106540352242922", "", "", actor="7")  # blank = keep what is saved
    business = registry.business("acme")
    assert business.has_meta_token and business.has_meta_secret and business.meta_token_hint == "oken"
    assert registry.clients()["acme"].meta_access_token == "acme-token"
    assert all("acme-token" not in e["detail"] and "acme-secret" not in e["detail"] for e in registry.audit_log())
    with pytest.raises(ValueError, match="digits"):
        registry.save_meta("acme", "not-a-number", "", "", actor="7")


def test_a_phone_number_id_belongs_to_one_business():
    registry = registry_with_acme()
    registry.create_business("other", acme_config(), actor="t")
    with pytest.raises(ValueError, match="Another business"):
        registry.save_meta("other", "106540352242922", "t", "s", actor="t")


def test_keys_sealed_with_another_secret_key_need_re_entering():
    registry = registry_with_acme()
    other = Registry(registry.db, Vault("a-different-key"))
    assert other.business("acme").keys_unreadable is True
    client = other.clients()["acme"]
    assert client.meta_access_token == "" and client.bot_name == "Sara"
    assert client.meta_app_secret not in ("", "acme-secret")  # no webhook signature matches it: fails closed


def test_paused_businesses_leave_the_engine():
    registry = registry_with_acme()
    registry.set_active("acme", False, actor="7")
    assert "acme" not in registry.clients() and registry.business("acme").active is False
    registry.set_active("acme", True, actor="7")
    assert "acme" in registry.clients()
    assert [e["action"] for e in registry.audit_log("acme")][:2] == ["business.resume", "business.pause"]


def test_numbers_are_assigned_one_per_business_and_deleted_only_when_free():
    registry = registry_with_acme()
    registry.add_number("spare-1", "Jazz SIM, Rs 500", actor="7")
    registry.assign_number("spare-1", "acme", actor="7")  # moves acme off its old number
    assert registry.number("acme").business_id is None
    assert registry.clients()["acme"].waha_session == "spare-1"
    with pytest.raises(ValueError, match="Unassign"):
        registry.delete_number("spare-1", actor="7")
    registry.delete_number("acme", actor="7")
    assert [n.session for n in registry.numbers()] == ["spare-1"]
    registry.save_number_notes("spare-1", "Jazz SIM, renew 1 Nov", actor="7")
    assert registry.number("spare-1").notes == "Jazz SIM, renew 1 Nov"
    with pytest.raises(ValueError, match="already exists"):
        registry.add_number("spare-1", "", actor="7")
    with pytest.raises(ValueError, match="session name"):
        registry.add_number("Bad Name", "", actor="7")


def test_clients_yaml_is_imported_with_the_env_meta_keys():
    registry = memory_registry()
    settings = Settings(meta_access_token="EAAG-pilot", meta_app_secret="pilot-secret", meta_verify_token="verify-me")
    assert registry.import_yaml("clients.example.yaml", settings) == 1
    client = registry.clients()["sweetbakes"]
    assert client.waha_session == "sweetbakes" and client.meta_phone_number_id == "106540352242922"
    assert client.meta_access_token == "EAAG-pilot" and client.meta_verify_token == "verify-me"
    assert client.tabs["Orders"].fill == {"Name": "name", "Phone": "phone"}
    assert registry.audit_log("sweetbakes")[-1]["action"] == "business.import"


def test_an_invalid_clients_yaml_imports_nothing(tmp_path):
    path = tmp_path / "clients.yaml"
    path.write_text("clients:\n  good:\n    business: B\n    bot_name: S\n    sheet_id: s\n"
                    "  bad:\n    business: B\n    bot_name: S\n    sheet_id: s\n    timezone: Mars/Base\n",
                    encoding="utf-8")
    registry = memory_registry()
    with pytest.raises(ValueError, match="timezone"):
        registry.import_yaml(str(path), Settings())
    assert registry.is_empty()


@pytest.mark.parametrize("extras, message", [
    (["waha_session: SweetBakes"], "waha_session 'SweetBakes' must be"),
    (["waha_session: shared", "waha_session: shared"], "waha_session 'shared'"),
    (["meta_phone_number_id: '1065-4035'"], "meta_phone_number_id must be digits"),
    (["meta_phone_number_id: '106'", "meta_phone_number_id: '106'"], "meta_phone_number_id '106'"),
])
def test_a_bad_or_repeated_number_imports_nothing(tmp_path, extras, message):
    entries = "".join(f"  shop{i}:\n    business: B\n    bot_name: S\n    sheet_id: s\n    {extra}\n"
                      for i, extra in enumerate(extras))  # one valid entry per extra setting: shop0, shop1, ...
    path = tmp_path / "clients.yaml"
    path.write_text("clients:\n" + entries, encoding="utf-8")
    registry = memory_registry()
    with pytest.raises(ValueError, match=message):
        registry.import_yaml(str(path), Settings())
    assert registry.is_empty()


def test_email_settings_are_sealed_audited_without_the_password_and_reach_the_client():
    registry = registry_with_acme()
    registry.save_email("acme", " shop@gmail.com ", "abcd efgh ijkl mnop", actor="t")
    stored = registry.db.one("SELECT * FROM email_accounts WHERE business_id = 'acme'")
    assert "abcd" not in stored["app_password"]
    client = registry.clients()["acme"]
    assert client.email_address == "shop@gmail.com" and client.email_app_password == "abcdefghijklmnop"
    assert "abcdefghijklmnop" not in repr(client)
    business = registry.business("acme")
    assert business.email_address == "shop@gmail.com" and business.has_email_password
    assert not business.email_unreadable
    entry = registry.audit_log("acme")[0]
    assert entry["action"] == "email.save" and "abcd" not in entry["detail"] and "(changed)" in entry["detail"]
    registry.save_email("acme", "orders@gmail.com", "", actor="t")  # empty keeps the saved password
    assert registry.clients()["acme"].email_app_password == "abcdefghijklmnop"
    assert registry.clients()["acme"].email_address == "orders@gmail.com"
    registry.remove_email("acme", actor="t")
    assert registry.clients()["acme"].email_address == ""
    assert registry.audit_log("acme")[0]["action"] == "email.remove"


@pytest.mark.parametrize("address, password, message", [
    ("not-an-email", "abcdefghijklmnop", "Gmail address"),
    ("a@gmail.com, b@gmail.com", "abcdefghijklmnop", "Gmail address"),
    ("shop@gmail.com", "hunter2hunter2", "16 letters"),
    ("shop@gmail.com", "", "app password too"),
])
def test_bad_email_settings_are_refused(address, password, message):
    with pytest.raises(ValueError, match=message):
        registry_with_acme().save_email("acme", address, password, actor="t")


def test_an_unreadable_app_password_switches_email_off():
    registry = registry_with_acme()
    registry.save_email("acme", "shop@gmail.com", "abcdefghijklmnop", actor="t")
    reopened = Registry(registry.db, Vault("another-key"))
    assert reopened.clients()["acme"].email_address == ""
    assert reopened.business("acme").email_unreadable
