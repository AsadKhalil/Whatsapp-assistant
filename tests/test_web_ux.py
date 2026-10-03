import re
from pathlib import Path

from tests.webkit import Site, csrf


def test_templates_have_no_inline_styles_or_handlers():
    """The Content-Security-Policy blocks inline styles and handlers, so they would silently do nothing."""
    for path in Path("app/templates").glob("*.html"):
        text = path.read_text(encoding="utf-8")
        assert ' style="' not in text and " onclick=" not in text and " onsubmit=" not in text, path.name


def test_pages_have_a_skip_link_and_errors_are_announced():
    site = Site()
    http = site.business_user()
    page = http.post("/app/settings", data={"csrf": csrf(http, "/app/settings"), "business": "Sweet Bakes",
                                            "bot_name": "Sara", "instructions": "", "timezone": "Mars/Base",
                                            "date_format": ""}).text
    assert 'href="#main"' in page and 'id="main"' in page
    assert 'id="page-error"' in page and 'role="alert"' in page


def test_pause_lives_on_the_business_home_with_a_confirmation_not_in_the_tabs():
    site = Site()
    admin = site.admin()
    home = admin.get("/admin/b/acme").text
    assert 'data-confirm="Pause Sweet Bakes?' in home and 'class="danger"' in home
    assert "Pause business" not in admin.get("/admin/b/acme/settings").text
    assert "Pause business" not in site.business_user().get("/app").text


def test_destructive_buttons_ask_first():
    site = Site()
    site.registry.add_number("spare-1", "", actor="t")
    site.auth.invite("mgr@sweetbakes.pk", "", "business", "acme")
    admin = site.admin()
    number = admin.get("/admin/numbers/spare-1").text
    assert 'data-confirm="Log out spare-1?' in number and 'data-confirm="Delete spare-1?' in number
    logins = admin.get("/admin/b/acme/logins").text
    assert 'data-confirm="Disable mgr@sweetbakes.pk?' in logins
    assert 'data-confirm="Make a new link for mgr@sweetbakes.pk?' in logins


def test_invite_and_number_forms_have_visible_labels():
    site = Site()
    site.registry.add_number("spare-1", "", actor="t")
    admin = site.admin()
    logins = admin.get("/admin/b/acme/logins").text
    assert 'aria-label="Email"' not in logins and "<label>Email" in logins
    number = admin.get("/admin/numbers/spare-1").text
    assert 'aria-label="Notes"' not in number and 'aria-label="Business"' not in number
    assert "<label>Answers for" in number


def test_staff_table_controls_are_named_for_screen_readers():
    site = Site()
    site.bot.waha.group_list["acme"] = [{"id": "staff@g.us", "name": "Kitchen staff"}]
    page = site.business_user().get("/app/staff").text
    assert 'aria-label="Kitchen staff: staff group"' in page and 'aria-label="Kitchen staff: gets alerts"' in page
    assert 'aria-label="No alerts"' in page


def test_the_google_sheet_opens_from_the_nav_and_the_sheet_page():
    site = Site()
    user = site.business_user()
    url = "https://docs.google.com/spreadsheets/d/sheet-1/edit"
    assert f'class="ext" href="{url}"' in user.get("/app").text
    sheet = user.get("/app/sheet").text
    assert f'class="h1-ext" href="{url}"' in sheet and "Open Google Sheet" in sheet


def test_sheet_preview_returns_to_its_tab_and_problems_show_at_the_tab():
    site = Site()
    http = site.business_user()
    i = list(site.bot.sheets.tab_headers("sheet-1")).index("Orders")
    page = http.get("/app/sheet").text
    assert f'id="tab-{i}"' in page and f'formaction="/app/sheet#tab-{i}"' in page
    r = http.post("/app/sheet", data={"csrf": csrf(http, "/app/sheet"), "action": "save", "tabs_listed": "1",
                                      f"use{i}": "on", f"own{i}": "on", f"owner{i}": ""})
    card = r.text.split(f'id="tab-{i}"', 1)[1].split("</article>", 1)[0]
    assert 'class="field-error"' in card and "pick which column holds" in card


def test_the_skip_link_shows_above_the_sticky_top_bar():
    css = Path("app/static/app.css").read_text(encoding="utf-8")

    def z_index(selector: str) -> int:
        return int(re.search(re.escape(selector) + r" \{[^}]*z-index: (\d+)", css).group(1))

    assert z_index(".skip-link") > z_index(".topbar")
