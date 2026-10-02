import json

import app.guided_setup
from app.guided_setup import draft_from_args
from tests.fakes import SETUP_ARGS, acme_config, call, make_bot, registry_with_acme, say
from tests.webkit import Site, csrf


def site_with(*replies, tabs=None, **llm_options) -> Site:
    registry = registry_with_acme()
    if tabs is not None:
        registry.save_config("acme", {"tabs": tabs}, actor="t")
    return Site(registry=registry, bot=make_bot(*replies, **llm_options)[0])


def stored_draft(site: Site) -> dict:
    draft = draft_from_args(SETUP_ARGS, acme_config())
    site.registry.save_setup("acme", [], draft)
    return draft


def posted(draft: dict, token: str, action: str, **extra) -> dict:
    """The fields the draft screen posts for `draft`, as a browser sends them."""
    data = {"csrf": token, "action": action, "tab_count": str(len(draft["tabs"])),
            "row_count": str(len(draft["knowledge"])),
            **{key: draft[key] for key in ("bot_name", "personality", "instructions")},
            **{f"replace_{key}": "on" for key, ticked in draft["replace"].items() if ticked}}
    for i, tab in enumerate(draft["tabs"]):
        data.update({f"name{i}": tab["name"], f"purpose{i}": tab["purpose"], f"columns{i}": ", ".join(tab["columns"]),
                     f"owner{i}": tab["owner_column"], **{f"{access}{i}": "on" for access in tab["customer"]},
                     **{f"fill_{source}{i}": column for column, source in tab["fill"].items()}})
        data.update({f"use{i}": "on"} if tab["use"] else {})
        data.update({f"confirm{i}": "on"} if tab["confirmed"] else {})
    for i, row in enumerate(draft["knowledge"]):
        data.update({f"question{i}": row["question"], f"answer{i}": row["answer"]})
        data.update({} if row["keep"] else {f"remove{i}": "on"})
    return {**data, **extra}


def test_the_interview_asks_one_question_at_a_time_then_shows_the_draft():
    site = site_with(say("What do customers ask about most?"), call("propose_setup", **SETUP_ARGS))
    http = site.business_user()
    assert "quick questions about Sweet Bakes" in http.get("/app/setup").text
    token = csrf(http, "/app/setup")
    page = http.post("/app/setup", data={"csrf": token, "action": "send", "text": "We bake cakes"}).text
    assert "We bake cakes" in page and "What do customers ask about most?" in page
    page = http.post("/app/setup", data={"csrf": token, "action": "send", "text": "Prices and delivery"}).text
    assert "Bookings" in page and "New tab" in page and "Exists: adds columns Status" in page
    assert "already in your Sheet" in page
    assert site.bot.sheets.written == [] and site.bot.clients["acme"].personality == ""  # nothing applied yet
    assert [m["role"] for m in site.registry.setup("acme")["messages"]] == ["user", "assistant", "user", "assistant"]


def test_apply_adds_only_and_saves_only_the_ticked_settings():
    site = site_with()
    draft = stored_draft(site)
    http = site.business_user()
    page = http.post("/app/setup", data=posted(draft, csrf(http, "/app/setup"), "apply")).text
    for line in ("Added tab Bookings.", "Added column Status to Orders.", "Added 1 Knowledge row.",
                 "Saved permissions for Bookings.", "Saved Personality."):
        assert line in page, line
    client = site.bot.clients["acme"]
    assert client.personality == SETUP_ARGS["personality"] and client.bot_name == "Sara"  # Replace unticked
    assert client.tabs["Bookings"].customer == {"own", "append"}
    assert client.tabs["Orders"].customer == {"own", "append"}  # had permissions: untouched by the draft's read
    entry = site.registry.audit_log("acme")[0]
    assert entry["action"] == "setup.apply" and json.loads(entry["detail"]) == {
        "tabs_created": ["Bookings"], "columns_added": {"Orders": ["Status"]}, "knowledge_rows": 1}
    assert site.registry.setup("acme")["applied_at"] is not None


def test_a_sheet_failure_stops_before_the_settings_and_a_second_apply_finishes():
    site = site_with()
    draft = stored_draft(site)
    site.bot.sheets.fail_writes = {"Knowledge"}
    http = site.business_user()
    token = csrf(http, "/app/setup")
    page = http.post("/app/setup", data=posted(draft, token, "apply")).text
    assert "Added tab Bookings." in page and "Share the Sheet with" in page and "Nothing in the settings changed" in page
    assert site.bot.clients["acme"].personality == "" and "Bookings" not in site.bot.clients["acme"].tabs
    assert site.registry.audit_log("acme")[0]["action"] != "setup.apply"
    site.bot.sheets.fail_writes = set()
    page = http.post("/app/setup", data=posted(draft, token, "apply")).text
    assert "Added 1 Knowledge row." in page and "Added tab" not in page and "Saved Personality." in page
    assert [w[0] for w in site.bot.sheets.written] == ["add_tab", "add_columns", "append_rows"]


def test_problems_block_apply_and_show_at_the_tab():
    site = site_with()
    draft = stored_draft(site)
    http = site.business_user()
    page = http.post("/app/setup", data=posted(draft, csrf(http, "/app/setup"), "apply", name0="Bookings/2026")).text
    assert "Fix the problems marked below" in page
    card = page.split('id="tab-0"', 1)[1].split("</article>", 1)[0]
    assert 'class="field-error"' in card and "a tab name can" in card
    assert site.bot.sheets.written == [] and site.registry.setup("acme")["draft"]["tabs"][0]["name"] == "Bookings/2026"


def test_asking_for_a_change_sends_the_hand_edited_draft_and_back_to_chat_keeps_edits():
    site = site_with(call("propose_setup", **{**SETUP_ARGS, "bot_name": "Zoe"}))
    draft = stored_draft(site)
    http = site.business_user()
    token = csrf(http, "/app/setup")
    page = http.post("/app/setup", data=posted(draft, token, "change", bot_name="Zed", text="Make it formal")).text
    system, *rest = site.bot.llm.calls[0]
    assert '"bot_name": "Zed"' in system["content"] and rest[-1] == {"role": "user", "content": "Make it formal"}
    assert site.registry.setup("acme")["draft"]["bot_name"] == "Zoe" and 'value="Zoe"' in page
    r = http.post("/app/setup", data=posted(draft, token, "back", bot_name="Kept"), follow_redirects=False)
    assert r.headers["location"] == "/app/setup?view=chat#reply"
    assert site.registry.setup("acme")["draft"]["bot_name"] == "Kept"


def test_the_daily_cap_counts_retries_and_start_over_doesnt_reset_it(monkeypatch):
    monkeypatch.setattr(app.guided_setup, "DAILY_CALLS", 2)
    bad = {**SETUP_ARGS, "bot_name": ""}
    site = site_with(call("propose_setup", **bad), call("propose_setup", **bad))
    http = site.business_user()
    token = csrf(http, "/app/setup")
    http.post("/app/setup", data={"csrf": token, "action": "draft_now"})  # a failing draft and its retry: 2 calls
    assert site.registry.setup("acme")["draft"]["bot_name"] == ""  # shown with its problems
    http.post("/app/setup", data={"csrf": token, "action": "start_over"})
    page = http.post("/app/setup", data={"csrf": token, "action": "send", "text": "We bake cakes"}).text
    assert "the limit for today" in page and ">We bake cakes</textarea>" in page
    assert site.registry.setup("acme") == {"messages": [], "draft": None, "applied_at": None}


def test_an_ai_error_keeps_the_owners_text_and_the_conversation():
    site = site_with(fail=True)
    http = site.business_user()
    page = http.post("/app/setup", data={"csrf": csrf(http, "/app/setup"), "action": "send",
                                         "text": "We bake cakes"}).text
    assert "answer right now" in page and ">We bake cakes</textarea>" in page
    assert site.registry.setup("acme")["messages"] == []


def test_thirty_answers_leave_only_make_the_draft_now():
    site = site_with()
    site.registry.save_setup("acme", [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}] * 30,
                             None)
    http = site.business_user()
    page = http.get("/app/setup").text
    assert 'name="text"' not in page and 'value="draft_now"' in page
    r = http.post("/app/setup", data={"csrf": csrf(http, "/app/setup"), "action": "send", "text": "one more"})
    assert "most answers for one interview" in r.text and site.bot.llm.calls == []


def test_setup_is_per_business_and_open_to_admins_even_when_paused():
    site = site_with()
    site.registry.save_setup("acme", [{"role": "user", "content": "Our secret recipe"}], None)
    site.registry.create_business("other", {**acme_config(), "business": "Other Co"}, actor="t")
    assert "Our secret recipe" not in site.business_user("owner@other.pk", "other").get("/app/setup").text
    assert site.business_user().get("/admin/b/acme/setup").status_code == 403
    site.registry.set_active("acme", False, actor="t")
    assert "Our secret recipe" in site.admin().get("/admin/b/acme/setup").text


def test_a_bogus_posted_draft_is_bounded_and_an_unreadable_sheet_blocks_apply():
    site = site_with()
    http = site.business_user()
    token = csrf(http, "/app/setup")
    r = http.post("/app/setup", data={"csrf": token, "action": "save", "tab_count": "999999999", "row_count": "-1"})
    assert r.status_code == 200 and len(site.registry.setup("acme")["draft"]["tabs"]) == 100
    site.bot.sheets.fail_tabs = RuntimeError("Google is down")
    page = http.post("/app/setup", data={"csrf": token, "action": "apply", "tab_count": "0", "row_count": "0"}).text
    assert "Google Sheets couldn" in page and site.bot.sheets.written == []


def test_home_shows_the_setup_card_until_set_up_and_settings_links_to_it():
    site = site_with(tabs={})
    http = site.business_user()
    assert "Set up your assistant" in http.get("/app").text
    assert "Guided setup" in http.get("/app/settings").text
    site.registry.save_setup("acme", [], None)
    site.registry.setup_applied("acme", actor="t", detail={})
    assert "Set up your assistant" not in http.get("/app").text
    assert "Set up your assistant" not in site_with().business_user().get("/app").text  # set up by hand: tabs saved
