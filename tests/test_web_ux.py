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
