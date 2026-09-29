from app.whatsapp import SendError
from tests.webkit import Site, csrf


def test_adding_a_number_creates_its_waha_session_and_opens_the_qr_page():
    site = Site()
    admin = site.admin()
    token = csrf(admin, "/admin/numbers")
    r = admin.post("/admin/numbers", data={"csrf": token, "session": "shop-2", "notes": "Zong SIM"})
    assert site.bot.waha.created == [("shop-2", "http://engine:8000/webhooks/waha", "hook-secret")]
    assert 'src="/admin/numbers/shop-2/qr.png' in r.text and 'http-equiv="refresh"' in r.text
    png = admin.get("/admin/numbers/shop-2/qr.png")
    assert png.headers["content-type"] == "image/png" and png.content.startswith(b"\x89PNG")
    assert "already exists" in admin.post("/admin/numbers", data={"csrf": token, "session": "shop-2"}).text
    assert "session name" in admin.post("/admin/numbers", data={"csrf": token, "session": "Shop 2"}).text


def test_a_linked_number_saves_its_phone_and_stops_refreshing():
    site = Site()
    site.registry.add_number("shop-2", "", actor="t")
    site.bot.waha.statuses["shop-2"] = "WORKING"
    site.bot.waha.phones["shop-2"] = "923330000000@c.us"
    page = site.admin().get("/admin/numbers/shop-2").text
    assert "+923330000000" in page and "http-equiv" not in page
    assert site.registry.number("shop-2").phone == "923330000000"


def test_relink_creates_a_missing_session_or_starts_a_stopped_one():
    site = Site()
    site.registry.add_number("shop-2", "", actor="t")
    admin = site.admin()
    token = csrf(admin, "/admin/numbers/shop-2")
    assert "NOT CREATED" in admin.get("/admin/numbers/shop-2").text
    admin.post("/admin/numbers/shop-2/relink", data={"csrf": token})
    assert ("create", "shop-2") in site.bot.waha.calls
    site.bot.waha.statuses["shop-2"] = "STOPPED"
    admin.post("/admin/numbers/shop-2/relink", data={"csrf": token})
    assert ("start", "shop-2") in site.bot.waha.calls


def test_assigning_from_the_number_page_and_deleting_only_free_numbers():
    site = Site()
    site.registry.add_number("shop-2", "", actor="t")
    admin = site.admin()
    token = csrf(admin, "/admin/numbers/shop-2")
    admin.post("/admin/numbers/shop-2/assign", data={"csrf": token, "business_id": "acme"})
    assert site.bot.clients["acme"].waha_session == "shop-2"
    assert "Unassign" in admin.post("/admin/numbers/shop-2/delete", data={"csrf": token}).text
    admin.post("/admin/numbers/shop-2/assign", data={"csrf": token, "business_id": ""})
    admin.post("/admin/numbers/shop-2/notes", data={"csrf": token, "notes": "spare, Jazz"})
    assert site.registry.number("shop-2").notes == "spare, Jazz"
    r = admin.post("/admin/numbers/shop-2/delete", data={"csrf": token})
    assert "Number deleted." in r.text and site.registry.number("shop-2") is None
    assert ("delete", "shop-2") in site.bot.waha.calls


def test_numbers_page_survives_waha_being_down():
    site = Site()
    site.bot.waha.statuses["acme"] = "UNREACHABLE"
    site.bot.waha.manage_fail = SendError("waha unreachable: ConnectError")
    admin = site.admin()
    assert "UNREACHABLE" in admin.get("/admin/numbers").text
    assert "UNREACHABLE" in admin.get("/admin/numbers/acme").text
    token = csrf(admin, "/admin/numbers/acme")
    assert "unreachable" in admin.post("/admin/numbers/acme/logout", data={"csrf": token}).text


def test_business_users_cannot_manage_numbers():
    http = Site().business_user()
    assert http.get("/admin/numbers").status_code == 403
    assert http.get("/admin/numbers/acme/qr.png").status_code == 403
