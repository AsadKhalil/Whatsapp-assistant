from app.mailer import MailError
from tests.fakes import acme_config
from tests.webkit import Site, csrf

APP_PASSWORD = "abcd efgh ijkl mnop"


def test_a_business_sets_up_email_and_the_password_is_never_shown():
    site = Site()
    http = site.business_user()
    r = http.post("/app/email", data={"csrf": csrf(http, "/app/email"), "action": "save",
                                      "address": "shop@gmail.com", "app_password": APP_PASSWORD})
    assert "Saved." in r.text and "abcd" not in r.text and "abcdefghijklmnop" not in r.text
    client = site.bot.clients["acme"]
    assert client.email_address == "shop@gmail.com" and client.email_app_password == "abcdefghijklmnop"
    assert 'value="shop@gmail.com"' in r.text and "Send a test email" in r.text


def test_the_test_button_sends_to_the_gmail_address_and_shows_gmails_answer():
    site = Site()
    site.registry.save_email("acme", "shop@gmail.com", APP_PASSWORD, actor="t")
    admin = site.admin()
    token = csrf(admin, "/admin/b/acme/email")
    ok = admin.post("/admin/b/acme/email", data={"csrf": token, "action": "test"}).text
    assert "Check the inbox of shop@gmail.com" in ok and site.bot.mailer.sent[0]["to"] == "shop@gmail.com"
    site.bot.mailer.fail = MailError("Gmail refused the email address or app password (check the business's "
                                     "Email page)", "auth")
    bad = admin.post("/admin/b/acme/email", data={"csrf": token, "action": "test"}).text
    assert "Gmail refused the email address or app password" in bad


def test_bad_settings_are_refused_and_remove_switches_email_off():
    site = Site()
    http = site.business_user()
    token = csrf(http, "/app/email")
    bad = http.post("/app/email", data={"csrf": token, "action": "save", "address": "shop@gmail.com",
                                        "app_password": "hunter2hunter2"}).text
    assert "16 letters" in bad and site.bot.clients["acme"].email_address == ""
    http.post("/app/email", data={"csrf": token, "action": "save", "address": "shop@gmail.com",
                                  "app_password": APP_PASSWORD})
    assert 'data-confirm="Remove email for Sweet Bakes?' in http.get("/app/email").text
    http.post("/app/email", data={"csrf": token, "action": "remove"})
    assert site.bot.clients["acme"].email_address == ""
    assert [e["action"] for e in site.registry.audit_log("acme")][:2] == ["email.remove", "email.save"]


def test_email_pages_stay_inside_the_business_and_need_the_form_token():
    site = Site()
    site.registry.create_business("other", {**acme_config(), "business": "Other Co"}, actor="t")
    http = site.business_user()
    assert http.get("/admin/b/other/email").status_code == 403
    assert http.post("/app/email", data={"action": "remove"}).status_code == 403  # no form token
    assert 'href="/app/email"' in http.get("/app").text  # the tab is in the business navigation
