import sqlite3

import pytest

from app.db import Db
from app.vault import Vault, VaultError


def test_db_reads_writes_and_rolls_back_a_failed_transaction():
    db = Db(":memory:")
    db.script("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)")
    assert db.insert("INSERT INTO t (name) VALUES (?)", ("a",)) == 1
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction():
            db.write("INSERT INTO t (name) VALUES (?)", ("b",))
            db.write("INSERT INTO t (name) VALUES (?)", ("a",))  # duplicate: the whole transaction rolls back
    assert [r["name"] for r in db.all("SELECT name FROM t ORDER BY id")] == ["a"]
    assert db.one("SELECT name FROM t WHERE name = ?", ("zzz",)) is None
    assert db.write("UPDATE t SET name = ? WHERE name = ?", ("c", "a")) == 1


def test_db_enforces_foreign_keys(tmp_path):
    db = Db(str(tmp_path / "data" / "x.db"))
    db.script("CREATE TABLE p (id TEXT PRIMARY KEY); CREATE TABLE c (p TEXT REFERENCES p(id));")
    with pytest.raises(sqlite3.IntegrityError):
        db.write("INSERT INTO c (p) VALUES ('missing')")


def test_vault_round_trip_and_wrong_key():
    sealed = Vault("key-one").seal("EAAG-secret-token")
    assert "EAAG" not in sealed
    assert Vault("key-one").open(sealed) == "EAAG-secret-token"
    with pytest.raises(VaultError, match="SECRET_KEY"):
        Vault("key-two").open(sealed)
    with pytest.raises(ValueError):
        Vault("")
