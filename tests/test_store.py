from app.store import Store


def save(store, msg_id, text="hi", chat="c1", sender="u1", from_bot=False, now=100.0, channel="meta"):
    return store.save_message("acme", channel, msg_id, chat, sender, "Ali", text, from_bot, now)


def test_duplicate_deliveries_are_dropped_per_channel():
    s = Store(":memory:")
    assert save(s, "m1") is True
    assert save(s, "m1") is False
    assert save(s, "m1", channel="waha") is True


def test_the_same_message_id_can_belong_to_two_clients():
    s = Store(":memory:")
    assert save(s, "m1") is True
    assert s.save_message("other", "meta", "m1", "c1", "u1", "Ali", "hi", False, 100.0) is True


def test_history_is_oldest_first_limited_and_updatable():
    s = Store(":memory:")
    for i in range(5):
        save(s, f"m{i}", text=f"t{i}", now=100.0 + i)
    s.set_text("acme", "meta", "m4", "transcript")
    rows = s.history("acme", "c1", limit=3)
    assert [r["text"] for r in rows] == ["t2", "t3", "transcript"]
    assert rows[0]["sender_name"] == "Ali" and rows[0]["from_bot"] == 0


def test_bot_message_lookups():
    s = Store(":memory:")
    save(s, "u1", now=1.0)
    assert s.bot_has_spoken("acme", "c1") is False
    save(s, "b1", sender="bot", from_bot=True, now=2.0)
    assert s.bot_has_spoken("acme", "c1") is True
    assert s.is_bot_message("acme", "meta", "b1") is True
    assert s.is_bot_message("acme", "meta", "u1") is False
    assert s.bot_replies_since("acme", "c1", since=1.5) == 1
    assert s.bot_replies_since("acme", "c1", since=2.5) == 0


def test_pending_write_round_trip_replace_and_expiry():
    s = Store(":memory:")
    s.put_pending("acme", "c1", "u1", "Orders", {"Item": "کیک"}, expires_at=200.0)
    assert s.get_pending("acme", "c1", "u1", now=150.0) == ("Orders", {"Item": "کیک"})
    s.put_pending("acme", "c1", "u1", "Leads", {"Name": "Ali"}, expires_at=300.0)
    assert s.get_pending("acme", "c1", "u1", now=150.0) == ("Leads", {"Name": "Ali"})
    assert s.get_pending("acme", "c1", "u1", now=300.0) is None
    assert s.get_pending("acme", "c1", "u1", now=0.0) is None  # the expired row was deleted
    s.put_pending("acme", "c1", "u1", "Orders", {"Item": "x"}, expires_at=900.0)
    assert s.purge_expired_pending(1000.0) == 1
    s.put_pending("acme", "c1", "u1", "Orders", {"Item": "x"}, expires_at=900.0)
    s.drop_pending("acme", "c1", "u1")
    assert s.get_pending("acme", "c1", "u1", now=0.0) is None


def test_retention_backup_and_health(tmp_path):
    s = Store(str(tmp_path / "data" / "a.db"))
    save(s, "old", text="old", now=10.0)
    save(s, "new", text="new", now=1000.0)
    assert s.delete_older_than("acme", cutoff=500.0) == 1
    assert [r["text"] for r in s.history("acme", "c1", 10)] == ["new"]
    dest = tmp_path / "backups" / "b.db"
    s.backup(str(dest))
    s.backup(str(dest))  # a second backup on the same day overwrites
    assert dest.exists()
    assert s.writable() is True
