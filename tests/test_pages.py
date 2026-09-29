from tests.fakes import acme_config
from tests.webkit import NOW, Site, csrf

SETTINGS_FORM = {"business": "Sweet Bakes", "bot_name": "Zara", "instructions": "Be brief.",
                 "timezone": "Asia/Karachi", "date_format": "%d/%m/%Y", "retention_days": "5"}


def test_signed_out_visitors_are_sent_to_login():
    r = Site().browser().get("/app/settings", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_business_home_shows_numbers_replies_and_handoffs():
    site = Site()
    store = site.bot.store
    store.save_message("acme", "meta", "b1", "user-1", "bot", "Sara", "hi", True, NOW - 60)
    store.save_message("acme", "waha", "b2", "g@g.us", "bot", "Sara", "hi", True, NOW - 60)
    store.save_message("acme", "waha", "b3", "g@g.us", "bot", "Sara", "old", True, NOW - 40 * 86_400)
    site.bot.sheets.tabs["Handoffs"].append({"Time": "2026-09-21 10:00", "Name": "Ali", "Phone": "923001234567",
                                             "Chat": "user-1", "Question": "wedding cake", "Reason": "custom"})
    page = site.business_user().get("/app").text
    assert "Sweet Bakes" in page and "wedding cake" in page and "WORKING" in page
    assert 'id="meta-replies">1<' in page and 'id="group-replies">1<' in page


def test_settings_save_reaches_the_bot_at_once_and_is_audited():
    site = Site()
    http = site.business_user()
    r = http.post("/app/settings", data={**SETTINGS_FORM, "csrf": csrf(http, "/app/settings")})
    assert "Saved." in r.text
    client = site.bot.clients["acme"]
    assert client.bot_name == "Zara" and client.instructions == "Be brief."
    assert client.retention_days == 90  # only admins change how long chats are kept
    assert site.registry.audit_log("acme")[0]["action"] == "settings.save"


def test_invalid_settings_are_refused_with_a_message():
    site = Site()
    http = site.business_user()
    token = csrf(http, "/app/settings")
    r = http.post("/app/settings", data={**SETTINGS_FORM, "timezone": "Mars/Base", "csrf": token})
    assert "unknown timezone" in r.text and site.bot.clients["acme"].bot_name == "Sara"
    r = http.post("/app/settings", data={**SETTINGS_FORM, "date_format": "%Q", "csrf": token})
    assert "Pick a date format" in r.text


def test_posts_without_the_form_token_are_refused():
    http = Site().business_user()
    assert http.post("/app/settings", data=SETTINGS_FORM).status_code == 403


def test_chats_stay_inside_the_business():
    site = Site()
    site.registry.create_business("other", {**acme_config(), "business": "Other Co"}, actor="t")
    store = site.bot.store
    store.save_message("acme", "meta", "m1", "user-ali", "user-ali", "Ali", "Do you deliver?", False, NOW - 30)
    store.save_message("acme", "meta", "m2", "user-ali", "bot", "Sara", "Yes, free above Rs 3000.", True, NOW - 20)
    store.save_message("other", "meta", "m3", "user-zed", "user-zed", "Zed", "secret order", False, NOW - 10)
    http = site.business_user()
    listing = http.get("/app/chats").text
    assert "Ali" in listing and "Zed" not in listing
    chat = http.get("/app/chat", params={"id": "user-ali"}).text
    assert "Do you deliver?" in chat and "free above Rs 3000" in chat
    assert http.get("/app/chat", params={"id": "user-zed"}).status_code == 404


def test_business_users_cannot_open_admin_screens_and_admins_can_open_any_business():
    site = Site()
    assert site.business_user().get("/admin/b/acme/settings").status_code == 403
    admin = site.admin()
    page = admin.get("/admin/b/acme/settings")
    assert page.status_code == 200 and "Keep chat history for" in page.text
    assert admin.get("/app/settings").status_code == 403
    assert admin.get("/admin/b/nope/settings").status_code == 404
    token = csrf(admin, "/admin/b/acme/settings")
    admin.post("/admin/b/acme/settings", data={**SETTINGS_FORM, "retention_days": "30", "csrf": token})
    assert site.bot.clients["acme"].retention_days == 30
