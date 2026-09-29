import threading

import pytest

import app.auth
from app.auth import Auth, AuthError, RateLimit, hash_password, new_totp_secret, totp, totp_ok, verify_password
from app.vault import Vault
from tests.fakes import registry_with_acme

NOW = 1_790_000_000.0
RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # base32 of "12345678901234567890", RFC 6238's SHA-1 key
PASSWORD = "correct horse battery"


def make_auth():
    registry = registry_with_acme()
    clock = [NOW]
    return Auth(registry.db, registry.vault, clock=lambda: clock[0]), clock


def test_passwords_are_salted_scrypt_hashes(monkeypatch):
    monkeypatch.setattr(app.auth, "SCRYPT_N", 2**14)  # the production cost (tests/conftest.py lowers it)
    stored = hash_password(PASSWORD)
    assert stored.startswith("scrypt$16384$8$1$") and "horse" not in stored
    assert stored != hash_password(PASSWORD)
    assert verify_password(PASSWORD, stored) and not verify_password("wrong", stored)
    assert not verify_password("anything", None) and not verify_password("anything", "garbage")


@pytest.mark.parametrize("at, code", [(59, "287082"), (1111111109, "081804"), (1111111111, "050471"),
                                      (1234567890, "005924"), (2000000000, "279037")])
def test_totp_matches_rfc_6238(at, code):
    assert totp(RFC_SECRET, at) == code


def test_totp_allows_one_step_of_clock_drift():
    secret = new_totp_secret()
    assert totp_ok(secret, totp(secret, NOW - 30), NOW) and totp_ok(secret, totp(secret, NOW + 30), NOW)
    assert not totp_ok(secret, totp(secret, NOW - 90), NOW)


def test_invite_accept_login_and_session():
    auth, clock = make_auth()
    token = auth.invite("Owner@SweetBakes.pk", "Owner", "business", "acme")
    assert auth.invited_user(token).email == "Owner@SweetBakes.pk"
    with pytest.raises(AuthError, match="10 characters"):
        auth.accept_invite(token, "short")
    auth.accept_invite(token, PASSWORD)
    with pytest.raises(AuthError, match="expired or was already used"):
        auth.accept_invite(token, PASSWORD)
    cookie, user = auth.login("owner@sweetbakes.pk", PASSWORD)  # emails match whatever the case
    session = auth.session(cookie)
    assert user.business_id == "acme" and session.mfa_ok is True and len(session.csrf) > 20
    clock[0] += 7 * 86_400
    assert auth.session(cookie) is None


def test_invites_expire_after_seven_days():
    auth, clock = make_auth()
    token = auth.invite("late@example.com", "", "business", "acme")
    clock[0] += 7 * 86_400 + 1
    assert auth.invited_user(token) is None


def test_bad_invites_are_refused():
    auth, _ = make_auth()
    auth.invite("a@example.com", "", "admin", None)
    with pytest.raises(AuthError, match="already has a login"):
        auth.invite("A@example.com", "", "admin", None)
    with pytest.raises(AuthError, match="needs a business"):
        auth.invite("b@example.com", "", "business", None)
    with pytest.raises(AuthError, match="No such business"):
        auth.invite("c@example.com", "", "business", "nope")
    with pytest.raises(AuthError, match="valid email"):
        auth.invite("not-an-email", "", "admin", None)


def test_five_wrong_passwords_pause_the_email_for_15_minutes():
    auth, clock = make_auth()
    auth.accept_invite(auth.invite("a@example.com", "", "admin", None), PASSWORD)
    for _ in range(5):
        with pytest.raises(AuthError, match="Wrong email or password"):
            auth.login("a@example.com", "nope")
    with pytest.raises(AuthError, match="Too many tries"):
        auth.login("A@example.com", PASSWORD)
    clock[0] += 15 * 60 + 1
    assert auth.login("a@example.com", PASSWORD)[1].role == "admin"


def test_admin_sessions_need_the_second_step_and_last_12_hours():
    auth, clock = make_auth()
    auth.accept_invite(auth.invite("a@example.com", "", "admin", None), PASSWORD)
    cookie, _ = auth.login("a@example.com", PASSWORD)
    assert auth.session(cookie).mfa_ok is False
    secret = auth.totp_setup_secret(cookie)
    assert auth.totp_setup_secret(cookie) == secret  # stable until confirmed
    assert auth.pass_totp(cookie, "000000") is False
    assert auth.pass_totp(cookie, totp(secret, NOW)) is True
    assert auth.session(cookie).mfa_ok is True and auth.by_email("a@example.com").has_totp
    stored = auth.db.one("SELECT totp_secret FROM users WHERE email = 'a@example.com'")["totp_secret"]
    assert secret not in stored  # sealed
    clock[0] += 12 * 3600
    assert auth.session(cookie) is None
    second, _ = auth.login("a@example.com", PASSWORD)
    assert auth.pass_totp(second, totp(secret, clock[0])) is True  # the saved secret, not a new one


def test_wrong_codes_are_rate_limited():
    auth, _ = make_auth()
    auth.accept_invite(auth.invite("a@example.com", "", "admin", None), PASSWORD)
    cookie, _ = auth.login("a@example.com", PASSWORD)
    auth.totp_setup_secret(cookie)
    for _ in range(5):
        assert auth.pass_totp(cookie, "000000") is False
    with pytest.raises(AuthError, match="Too many wrong codes"):
        auth.pass_totp(cookie, "000000")


def test_a_changed_secret_key_sends_admins_to_admin_link():
    auth, _ = make_auth()
    auth.accept_invite(auth.invite("a@example.com", "", "admin", None), PASSWORD)
    cookie, _ = auth.login("a@example.com", PASSWORD)
    secret = auth.totp_setup_secret(cookie)
    assert auth.pass_totp(cookie, totp(secret, NOW)) is True
    moved = Auth(auth.db, Vault("a-different-key"), clock=auth.clock)
    cookie, _ = moved.login("a@example.com", PASSWORD)  # the password still works
    with pytest.raises(AuthError, match="admin-link"):
        moved.pass_totp(cookie, totp(secret, NOW))


def test_an_unfinished_two_step_setup_starts_again_after_a_secret_key_change():
    auth, _ = make_auth()
    auth.accept_invite(auth.invite("a@example.com", "", "admin", None), PASSWORD)
    cookie, _ = auth.login("a@example.com", PASSWORD)
    old = auth.totp_setup_secret(cookie)
    moved = Auth(auth.db, Vault("a-different-key"), clock=auth.clock)
    fresh = moved.totp_setup_secret(cookie)
    assert fresh != old and moved.pass_totp(cookie, totp(fresh, NOW)) is True


def test_new_links_and_disabling_end_every_session():
    auth, _ = make_auth()
    auth.accept_invite(auth.invite("o@example.com", "", "business", "acme"), PASSWORD)
    cookie, user = auth.login("o@example.com", PASSWORD)
    auth.set_disabled(user.id, True)
    assert auth.session(cookie) is None
    with pytest.raises(AuthError, match="Wrong email or password"):
        auth.login("o@example.com", PASSWORD)
    auth.set_disabled(user.id, False)
    cookie, _ = auth.login("o@example.com", PASSWORD)
    link = auth.new_link(user.id)
    assert auth.session(cookie) is None and auth.invited_user(link).id == user.id
    with pytest.raises(AuthError):
        auth.login("o@example.com", PASSWORD)  # the old password stopped working


def test_logout_ends_the_session():
    auth, _ = make_auth()
    auth.accept_invite(auth.invite("o@example.com", "", "business", "acme"), PASSWORD)
    cookie, _ = auth.login("o@example.com", PASSWORD)
    auth.logout(cookie)
    assert auth.session(cookie) is None


def test_rate_limit_allows_five_tries_then_pauses():
    limits = RateLimit()
    assert [limits.attempt("k", 0.0) for _ in range(7)] == [True] * 5 + [False, False]


def test_rate_limit_forgets_expired_keys():
    limits = RateLimit()
    assert limits.attempt("old", 0.0)
    assert limits.attempt("new", 15 * 60 + 61)  # a minute has passed, so this attempt sweeps first
    assert "old" not in limits._tries and "new" in limits._tries


def test_rate_limit_is_safe_under_concurrent_attempts():
    limits = RateLimit()
    barrier = threading.Barrier(20)
    results = [None] * 20

    def go(i):
        barrier.wait()
        results[i] = limits.attempt("k", 0.0)

    threads = [threading.Thread(target=go, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 5


def test_a_reset_during_login_wins(monkeypatch):
    auth, _ = make_auth()
    user = auth.accept_invite(auth.invite("o@example.com", "", "business", "acme"), PASSWORD)
    real_verify = app.auth.verify_password

    def racing_verify(password, stored):
        ok = real_verify(password, stored)
        auth.new_link(user.id)  # a reset lands between the password check and the session insert
        return ok

    monkeypatch.setattr(app.auth, "verify_password", racing_verify)
    with pytest.raises(AuthError, match="Wrong email or password"):
        auth.login("o@example.com", PASSWORD)
    assert auth.db.all("SELECT * FROM sessions") == []


def test_totp_codes_are_single_use():
    auth, clock = make_auth()
    auth.accept_invite(auth.invite("a@example.com", "", "admin", None), PASSWORD)
    first, _ = auth.login("a@example.com", PASSWORD)
    secret = auth.totp_setup_secret(first)
    code = totp(secret, clock[0])
    assert auth.pass_totp(first, code) is True
    second, _ = auth.login("a@example.com", PASSWORD)
    assert auth.pass_totp(second, code) is False  # already used, in a different session too
    assert auth.pass_totp(second, "１２３４５６") is False  # full-width digits: refused, not a crash


def test_login_limiter_keys_are_hashed_not_raw_emails():
    auth, _ = make_auth()
    with pytest.raises(AuthError, match="Wrong email or password"):
        auth.login("x" * 1000 + "@example.com", "bad")
    assert all(len(key) < 100 for key in auth.limits._tries)
