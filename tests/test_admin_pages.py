import re

from app.whatsapp import SendError
from tests.fakes import acme_config
from tests.webkit import NOW, PASSWORD, Site, csrf


def test_overview_shows_every_business_with_number_status_and_replies():
    site = Site()
    site.registry.create_business("other", {**acme_config(), "business": "Other Co"}, actor="t")
    site.bot.clients = site.registry.clients()
    site.bot.waha.statuses["acme"] = "SCAN_QR_CODE"
    site.bot.store.save_message("acme", "meta", "b1", "c", "bot", "Sara", "hi", True, NOW - 60)
    page = site.admin().get("/admin").text
    assert "Sweet Bakes" in page and "Other Co" in page and "SCAN_QR_CODE" in page and "not linked" in page
    biz = site.business_user()
    assert biz.get("/admin").status_code == 403 and biz.get("/admin/admins").status_code == 403


def test_admins_must_finish_two_step_login_first():
    site = Site()
    site.auth.accept_invite(site.auth.invite("a@example.com", "", "admin", None), PASSWORD)
    http = site.browser()
    http.post("/login", data={"email": "a@example.com", "password": PASSWORD})
    assert http.get("/admin", follow_redirects=False).headers["location"] == "/login/totp"


def test_adding_a_business_checks_the_sheet_and_goes_live_at_once():
    site = Site()
    admin = site.admin()
    form = {"csrf": csrf(admin, "/admin/new"), "id": "bakehouse", "business": "Bake House", "bot_name": "Noor",
            "timezone": "Asia/Karachi", "sheet_id": "sheet-1", "instructions": "Be kind."}
    check = admin.post("/admin/new", data={**form, "action": "check"}).text
    assert "The Sheet is readable" in check and "Prices" in check
    assert 'value="bake-house"' in admin.post("/admin/new", data={**form, "id": "", "action": "check"}).text
    bad = admin.post("/admin/new", data={**form, "id": "Bake House", "action": "create"}).text
    assert "web id" in bad and "bakehouse" not in site.bot.clients
    created = admin.post("/admin/new", data={**form, "action": "create"})
    assert "Business created." in created.text and site.bot.clients["bakehouse"].bot_name == "Noor"
    assert "already exists" in admin.post("/admin/new", data={**form, "action": "create"}).text
    assert re.search(r'<input name="id"[^>]*required', admin.get("/admin/new").text) is None


def test_meta_keys_are_write_only_and_reach_the_bot():
    site = Site()
    admin = site.admin()
    token = csrf(admin, "/admin/b/acme/meta")
    r = admin.post("/admin/b/acme/meta", data={"csrf": token, "action": "save", "phone_number_id": "106540352242922",
                                               "access_token": "EAAG-new-token-9876", "app_secret": ""})
    assert "Saved." in r.text and "EAAG-new-token-9876" not in r.text and "9876" in r.text
    client = site.bot.clients["acme"]
    assert client.meta_access_token == "EAAG-new-token-9876" and client.meta_app_secret == "acme-secret"
    page = admin.get("/admin/b/acme/meta").text
    assert "https://bot.example.com/webhooks/meta/acme" in page and client.meta_verify_token in page
    assert "acme-secret" not in page and "EAAG-new-token-9876" not in page


def test_test_connection_shows_metas_answer():
    site = Site()
    admin = site.admin()
    token = csrf(admin, "/admin/b/acme/meta")
    ok = admin.post("/admin/b/acme/meta", data={"csrf": token, "action": "test"}).text
    assert "+1 555 0100" in ok and "Sweet Bakes" in ok
    site.bot.meta.info = SendError("meta status=401 code=190 Error validating access token")
    assert "Error validating access token" in admin.post("/admin/b/acme/meta",
                                                         data={"csrf": token, "action": "test"}).text


def test_assigning_a_group_number_moves_the_bot_to_it():
    site = Site()
    site.registry.add_number("spare-1", "", actor="t")
    admin = site.admin()
    token = csrf(admin, "/admin/b/acme/number")
    admin.post("/admin/b/acme/number", data={"csrf": token, "session": "spare-1"})
    assert site.bot.clients["acme"].waha_session == "spare-1"
    admin.post("/admin/b/acme/number", data={"csrf": token, "session": ""})
    assert site.bot.clients["acme"].waha_session is None


def test_business_logins_invite_new_link_and_disable():
    site = Site()
    site.registry.create_business("other", {**acme_config(), "business": "Other Co"}, actor="t")
    stranger = site.auth.invite("zed@other.co", "", "business", "other")
    admin = site.admin()
    token = csrf(admin, "/admin/b/acme/logins")
    page = admin.post("/admin/b/acme/logins", data={"csrf": token, "action": "invite", "email": "mgr@sweetbakes.pk",
                                                    "name": "Manager"}).text
    link = re.search(r"https://bot\.example\.com(/invite/[\w-]+)", page).group(1)
    browser = site.browser()
    browser.post(link, data={"password": PASSWORD, "confirm": PASSWORD})
    browser.post("/login", data={"email": "mgr@sweetbakes.pk", "password": PASSWORD})
    assert browser.get("/app").status_code == 200
    user = site.auth.by_email("mgr@sweetbakes.pk")
    admin.post("/admin/b/acme/logins", data={"csrf": token, "action": "disable", "user_id": str(user.id)})
    assert browser.get("/app", follow_redirects=False).headers["location"] == "/login"
    assert "user.disable" in [e["action"] for e in site.registry.audit_log("acme")]
    other_user = site.auth.invited_user(stranger)
    assert admin.post("/admin/b/acme/logins", data={"csrf": token, "action": "link",
                                                    "user_id": str(other_user.id)}).status_code == 404


def test_pausing_a_business_stops_its_bot_and_shows_a_banner():
    site = Site()
    admin = site.admin()
    token = csrf(admin, "/admin/b/acme")
    r = admin.post("/admin/b/acme/pause", data={"csrf": token, "active": "0"})
    assert "Business paused" in r.text and "acme" not in site.bot.clients
    assert "is paused" in site.business_user().get("/app").text
    admin.post("/admin/b/acme/pause", data={"csrf": token, "active": "1"})
    assert "acme" in site.bot.clients


def test_audit_log_names_who_changed_what_without_secrets():
    site = Site()
    admin = site.admin()
    admin.post("/admin/b/acme/settings", data={"csrf": csrf(admin, "/admin/b/acme/settings"), "business": "Sweet Bakes",
                                               "bot_name": "Zara", "instructions": "", "timezone": "Asia/Karachi",
                                               "date_format": "", "retention_days": "90"})
    page = admin.get("/admin/b/acme/audit").text
    assert "settings.save" in page and "admin@example.com" in page
    assert "acme-token" not in page and "acme-secret" not in page


def test_admins_can_invite_admins_but_not_disable_themselves():
    site = Site()
    admin = site.admin()
    token = csrf(admin, "/admin/admins")
    page = admin.post("/admin/admins", data={"csrf": token, "action": "invite", "email": "helper@example.com"}).text
    assert "/invite/" in page and "helper@example.com" in page
    me = site.auth.by_email("admin@example.com")
    assert "your own login" in admin.post("/admin/admins", data={"csrf": token, "action": "disable",
                                                                 "user_id": str(me.id)}).text
