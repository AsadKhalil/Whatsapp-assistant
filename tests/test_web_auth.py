import re

from app.auth import Auth, totp
from app.cli import main as cli_main
from app.db import Db
from app.vault import Vault
from tests.webkit import NOW, PASSWORD, Site, csrf


def test_the_start_page_sends_people_to_the_right_place():
    site = Site()
    assert site.browser().get("/", follow_redirects=False).headers["location"] == "/login"
    assert site.business_user().get("/", follow_redirects=False).headers["location"] == "/app"


def test_login_page_and_security_headers():
    r = Site().browser().get("/login")
    assert r.status_code == 200 and 'name="password"' in r.text
    assert r.headers["x-frame-options"] == "DENY" and "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["referrer-policy"] == "same-origin"


def test_session_cookie_is_locked_down():
    site = Site()
    site.auth.accept_invite(site.auth.invite("o@example.com", "", "business", "acme"), PASSWORD)
    r = site.browser().post("/login", data={"email": "o@example.com", "password": PASSWORD}, follow_redirects=False)
    cookie = r.headers["set-cookie"].lower()
    assert r.headers["location"] == "/app"
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie and "max-age=604800" in cookie


def test_wrong_passwords_are_refused_then_paused():
    site = Site()
    site.auth.accept_invite(site.auth.invite("o@example.com", "", "business", "acme"), PASSWORD)
    http = site.browser()
    for _ in range(5):
        assert "Wrong email or password" in http.post("/login", data={"email": "o@example.com", "password": "x"}).text
    assert "Too many tries" in http.post("/login", data={"email": "o@example.com", "password": PASSWORD}).text


def test_invite_link_sets_a_password():
    site = Site()
    token = site.auth.invite("new@example.com", "New", "business", "acme")
    http = site.browser()
    assert "new@example.com" in http.get(f"/invite/{token}").text
    assert "don't match" in http.post(f"/invite/{token}", data={"password": PASSWORD, "confirm": "other one!!"}).text
    assert "Password set" in http.post(f"/invite/{token}", data={"password": PASSWORD, "confirm": PASSWORD}).text
    assert http.get(f"/invite/{token}").status_code == 404


def test_admins_set_up_and_pass_two_step_login():
    site = Site()
    site.auth.accept_invite(site.auth.invite("admin@example.com", "", "admin", None), PASSWORD)
    http = site.browser()
    r = http.post("/login", data={"email": "admin@example.com", "password": PASSWORD}, follow_redirects=False)
    assert r.headers["location"] == "/login/totp"
    page = http.get("/login/totp").text
    secret = re.search(r'id="totp-secret">([A-Z2-7]+)<', page).group(1)
    assert "otpauth://totp/" in page
    token = csrf(http, "/login/totp")
    assert "didn't match" in http.post("/login/totp", data={"csrf": token, "code": "000000"}).text
    r = http.post("/login/totp", data={"csrf": token, "code": totp(secret, NOW)}, follow_redirects=False)
    assert r.headers["location"] == "/admin"


def test_logout_needs_the_form_token_and_ends_the_session():
    site = Site()
    site.auth.accept_invite(site.auth.invite("admin@example.com", "", "admin", None), PASSWORD)
    http = site.browser()
    http.post("/login", data={"email": "admin@example.com", "password": PASSWORD})
    token = csrf(http, "/login/totp")
    assert http.post("/logout", data={}).status_code == 403
    assert http.post("/logout", data={"csrf": token}, follow_redirects=False).headers["location"] == "/login"
    assert http.get("/login/totp", follow_redirects=False).headers["location"] == "/login"


def test_create_admin_and_admin_link_print_working_invite_links(tmp_path, monkeypatch, capsys):
    db_path = str(tmp_path / "a.db")
    monkeypatch.setenv("DB_PATH", db_path)
    monkeypatch.setenv("SECRET_KEY", "cli-secret")
    monkeypatch.setenv("PUBLIC_URL", "https://bot.example.com")
    assert cli_main(["create-admin", "owner@example.com"]) == 0
    first = capsys.readouterr().out.strip()
    assert first.startswith("https://bot.example.com/invite/")
    assert cli_main(["admin-link", "owner@example.com"]) == 0
    second = capsys.readouterr().out.strip()
    auth = Auth(Db(db_path), Vault("cli-secret"))
    assert auth.invited_user(second.rsplit("/", 1)[1]).email == "owner@example.com"
    assert auth.invited_user(first.rsplit("/", 1)[1]) is None
    assert cli_main(["admin-link", "nobody@example.com"]) == 1
    assert cli_main(["bogus"]) == 2
