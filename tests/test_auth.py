import pytest

from app.auth import Auth, AuthError, hash_password, new_totp_secret, totp, totp_ok, verify_password
from tests.fakes import registry_with_acme

NOW = 1_790_000_000.0
RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # base32 of "12345678901234567890", RFC 6238's SHA-1 key
PASSWORD = "correct horse battery"


def make_auth():
    registry = registry_with_acme()
    clock = [NOW]
    return Auth(registry.db, registry.vault, clock=lambda: clock[0]), clock


def test_passwords_are_salted_scrypt_hashes():
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
