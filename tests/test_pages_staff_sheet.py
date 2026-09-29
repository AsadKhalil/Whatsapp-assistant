import gspread

from app.whatsapp import SendError
from tests.fakes import registry_with_acme
from tests.webkit import Site, csrf


def indexes(site) -> dict[str, int]:
    """Each tab's position on the Sheet screen, which names its form fields (use0, read0, ...)."""
    return {tab: i for i, tab in enumerate(site.bot.sheets.tab_headers("sheet-1"))}


def test_staff_numbers_need_a_country_code_and_reach_the_bot():
    site = Site()
    http = site.business_user()
    token = csrf(http, "/app/staff")
    bad = http.post("/app/staff", data={"csrf": token, "staff_numbers": "+92 300 1111111\n0300 2222222"})
    assert "starting with +" in bad.text and site.bot.clients["acme"].staff_numbers == {"923001111111"}
    ok = http.post("/app/staff", data={"csrf": token, "staff_numbers": "+92 300 1111111\n+92 321 2222222"})
    assert "Saved." in ok.text
    assert site.bot.clients["acme"].staff_numbers == {"923001111111", "923212222222"}


def test_staff_groups_come_from_the_group_numbers_own_list():
    site = Site()
    site.bot.waha.group_list["acme"] = [{"id": "staff@g.us", "name": "Bakery team"},
                                        {"id": "fans@g.us", "name": "Cake fans"}]
    http = site.business_user()
    page = http.get("/app/staff").text
    assert "Bakery team" in page and "Cake fans" in page
    http.post("/app/staff", data={"csrf": csrf(http, "/app/staff"), "staff_numbers": "+92 300 1111111",
                                  "groups_listed": "1", "staff_chats": ["staff@g.us", "fans@g.us", "evil@g.us"],
                                  "alert": "fans@g.us"})
    client = site.bot.clients["acme"]
    assert client.staff_chats == {"staff@g.us", "fans@g.us"} and client.staff_alert_chat == "fans@g.us"


def test_staff_page_keeps_saved_groups_when_waha_is_down():
    site = Site()
    site.bot.waha.manage_fail = SendError("waha unreachable: ConnectError")
    http = site.business_user()
    assert "read the group number" in http.get("/app/staff").text
    http.post("/app/staff", data={"csrf": csrf(http, "/app/staff"), "staff_numbers": "+92 300 1111111"})
    assert site.bot.clients["acme"].staff_chats == {"staff@g.us"}


def test_staff_page_asks_to_link_a_group_number_first():
    registry = registry_with_acme()
    registry.assign_number("acme", None, actor="t")
    assert "Link a group number first" in Site(registry=registry).business_user().get("/app/staff").text


def test_sheet_page_lists_tabs_and_explains_sharing_problems():
    site = Site()
    http = site.business_user()
    page = http.get("/app/sheet").text
    assert "Prices" in page and "Expenses" in page and "Item, Price" in page
    site.bot.sheets.fail_tabs = gspread.exceptions.SpreadsheetNotFound()
    assert "No Sheet with that id" in http.get("/app/sheet").text


def test_permissions_save_from_the_real_sheet_tabs():
    site = Site()
    http = site.business_user()
    i = indexes(site)
    data = {"csrf": csrf(http, "/app/sheet"), "action": "save", "tabs_listed": "1", "knowledge_tab": "Knowledge",
            "handoff_tab": "Handoffs",
            f"use{i['Prices']}": "on", f"read{i['Prices']}": "on",
            f"use{i['Orders']}": "on", f"own{i['Orders']}": "on", f"owner{i['Orders']}": "Phone",
            f"append{i['Orders']}": "on", f"fill_name{i['Orders']}": "Name", f"fill_phone{i['Orders']}": "Phone",
            f"use{i['Expenses']}": "on"}
    assert "Saved." in http.post("/app/sheet", data=data).text
    tabs = site.bot.clients["acme"].tabs
    assert set(tabs) == {"Prices", "Orders", "Expenses"}  # Staff Notes unticked: hidden from the bot
    assert tabs["Orders"].customer == {"own", "append"} and tabs["Orders"].owner_column == "Phone"
    assert tabs["Orders"].fill == {"Name": "name", "Phone": "phone"} and tabs["Expenses"].customer == frozenset()


def test_read_all_on_a_tab_with_contact_columns_needs_an_extra_tick():
    site = Site()
    http = site.business_user()
    i = indexes(site)["Orders"]
    data = {"csrf": csrf(http, "/app/sheet"), "action": "save", "tabs_listed": "1", f"use{i}": "on", f"read{i}": "on"}
    refused = http.post("/app/sheet", data=data).text
    assert "every customer would see Phone" in refused
    assert "read" not in site.bot.clients["acme"].tabs["Orders"].customer
    assert "Saved." in http.post("/app/sheet", data={**data, f"confirm{i}": "on"}).text
    assert site.bot.clients["acme"].tabs["Orders"].customer == {"read"}


def test_own_rows_need_an_owner_column():
    site = Site()
    http = site.business_user()
    i = indexes(site)["Orders"]
    r = http.post("/app/sheet", data={"csrf": csrf(http, "/app/sheet"), "action": "save", "tabs_listed": "1",
                                      f"use{i}": "on", f"own{i}": "on", f"owner{i}": ""})
    assert "pick which column holds" in r.text


def test_preview_shows_what_a_sample_customer_would_see_without_saving():
    site = Site()
    http = site.business_user()
    i = indexes(site)["Orders"]
    r = http.post("/app/sheet", data={"csrf": csrf(http, "/app/sheet"), "action": "preview:Orders",
                                      "tabs_listed": "1", f"use{i}": "on", f"own{i}": "on", f"owner{i}": "Phone"})
    assert "Chocolate cake" in r.text and "Carrot cake" not in r.text  # only the first row's customer, Ali
    assert site.bot.clients["acme"].tabs["Orders"].customer == {"own", "append"}  # nothing was saved


def test_permissions_are_not_wiped_when_the_sheet_cant_be_read():
    site = Site()
    http = site.business_user()
    token = csrf(http, "/app/sheet")
    site.bot.sheets.fail_tabs = RuntimeError("Google is down")
    r = http.post("/app/sheet", data={"csrf": token, "action": "save", "tabs_listed": "1"})
    assert "Google Sheets couldn" in r.text
    assert set(site.bot.clients["acme"].tabs) == {"Prices", "Orders", "Staff Notes", "Expenses"}


def test_only_admins_change_the_sheet_id():
    site = Site()
    http = site.business_user()
    assert http.post("/app/sheet", data={"csrf": csrf(http, "/app/sheet"), "action": "sheet_id",
                                         "sheet_id": "someone-elses"}).status_code == 403
    admin = site.admin()
    admin.post("/admin/b/acme/sheet", data={"csrf": csrf(admin, "/admin/b/acme/sheet"), "action": "sheet_id",
                                            "sheet_id": "sheet-2"})
    assert site.bot.clients["acme"].sheet_id == "sheet-2"
