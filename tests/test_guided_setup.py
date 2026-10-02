from app.guided_setup import check_draft, draft_from_args, setup_changes, tab_plan
from tests.fakes import SETUP_ARGS, acme_config, bakery_sheets


def sheet_tabs() -> dict[str, list[str]]:
    return bakery_sheets().tab_headers("sheet-1")


def draft(**changes) -> dict:
    return {**draft_from_args(SETUP_ARGS, acme_config()), **changes}


def a_tab(name: str, **changes) -> dict:
    return {"name": name, "purpose": "", "columns": ["Date"], "customer": [], "owner_column": "", "fill": {},
            "use": True, "confirmed": False, **changes}


def test_a_proposal_becomes_a_draft_with_replace_ticked_only_where_nothing_is_saved():
    d = draft_from_args(SETUP_ARGS, acme_config())
    assert d["replace"] == {"bot_name": False, "personality": True, "instructions": False}
    bookings = d["tabs"][0]
    assert bookings["fill"] == {"Name": "name", "Phone": "phone"} and bookings["use"] and not bookings["confirmed"]
    assert d["knowledge"][1] == {"question": "delivery?", "answer": "Free above Rs 3000", "keep": True}
    assert check_draft(d, sheet_tabs(), acme_config()) == []


def test_malformed_proposals_are_tidied_not_crashed_on():
    d = draft_from_args({"bot_name": 7, "tabs": [{"name": "Leads", "columns": "Name, phone ,", "customer": "read",
                                                    "fill": {"Phone": ["phone"]}, "owner_column": "PHONE"}, "junk"],
                         "knowledge": [{"question": "", "answer": ""}, "x", {"question": "Q?"}]}, acme_config())
    assert d["bot_name"] == "" and d["tabs"] == [{"name": "Leads", "purpose": "", "columns": ["Name", "phone"],
                                                  "customer": [], "owner_column": "phone", "fill": {},
                                                  "use": True, "confirmed": False}]
    assert d["knowledge"] == [{"question": "Q?", "answer": "", "keep": True}]
    assert {where for where, _ in check_draft(d, sheet_tabs(), acme_config())} == {"persona", "row0"}


def test_tab_names_follow_googles_rules_and_leave_out_the_knowledge_and_handoffs_tabs():
    tabs = [a_tab(name) for name in ("Orders/2026", "knowledge", "Leads", "LEADS", "", "x" * 101)]
    tabs.append(a_tab("Skipped/", use=False))  # unticked tabs aren't checked
    problems = check_draft(draft(tabs=tabs), sheet_tabs(), acme_config())
    assert [where for where, _ in problems] == ["tab0", "tab1", "tab3", "tab4", "tab5"]
    text = " ".join(message for _, message in problems)
    assert "can't contain" in text and "Knowledge or Handoffs" in text and "two tabs have this name" in text


def test_caps_on_tabs_columns_rows_and_text():
    tabs = [a_tab(f"T{i}", columns=["A"]) for i in range(11)]
    tabs[0]["columns"] = [f"C{i}" for i in range(21)]
    tabs[1]["columns"] = ["A", "a", "x" * 41]
    rows = [{"question": f"Q{i}?", "answer": "A", "keep": True} for i in range(61)]
    rows[0]["answer"] = "x" * 1001
    problems = check_draft(draft(tabs=tabs, knowledge=rows, bot_name="x" * 41, personality="x" * 1501,
                                 instructions="x" * 4001), sheet_tabs(), acme_config())
    text = " ".join(message for _, message in problems)
    for expected in ("At most 10 tabs", "at most 20 columns", "at most 40 characters", "same name",
                     "At most 60 Knowledge rows", "at most 1,000", "Bot name: 1 to 40",
                     "Personality: at most 1,500", "Instructions: at most 4,000"):
        assert expected in text, expected


def test_a_tab_matching_an_existing_one_ignoring_case_adds_only_missing_columns():
    assert tab_plan("orders", ["date", "Status"], sheet_tabs()) == {
        "existing": "Orders", "add": ["Status"], "headers": ["Date", "Item", "Qty", "Name", "Phone", "Status"]}
    assert tab_plan("Bookings", ["Date"], sheet_tabs()) == {"existing": None, "add": ["Date"], "headers": ["Date"]}
    assert "new tab needs at least one column" in check_draft(draft(tabs=[a_tab("Empty", columns=[])]),
                                                              sheet_tabs(), acme_config())[0][1]


def test_permissions_pass_the_sheet_pages_checks_on_the_final_headers():
    config = {**acme_config(), "tabs": {}}  # no tab has permissions yet
    orders = a_tab("orders", columns=["Status"], customer=["read"])
    refused = check_draft(draft(tabs=[orders]), sheet_tabs(), config)
    assert [where for where, _ in refused] == ["tab0"] and "every customer would see Phone" in refused[0][1]
    assert check_draft(draft(tabs=[{**orders, "confirmed": True}]), sheet_tabs(), config) == []
    own = {**orders, "customer": ["own", "append"], "owner_column": "Mobile",
           "fill": {"Status": "name", "Nope": "phone"}}
    text = " ".join(message for _, message in check_draft(draft(tabs=[own]), sheet_tabs(), config))
    assert "pick which column holds" in text and "'Nope' is not in the tab" in text and "'Status'" not in text


def test_saved_permissions_are_kept_and_persona_follows_the_replace_ticks():
    d = draft()
    d["replace"] = {"bot_name": False, "personality": True, "instructions": False}
    changes = setup_changes(d, sheet_tabs(), acme_config())
    assert changes["personality"] == SETUP_ARGS["personality"] and "bot_name" not in changes
    assert "instructions" not in changes
    assert changes["tabs"]["Orders"] == acme_config()["tabs"]["Orders"]  # already set: untouched
    assert changes["tabs"]["Bookings"] == {"customer": ["own", "append"], "owner_column": "Phone",
                                          "fill": {"Name": "name", "Phone": "phone"}}
    d["tabs"][0]["use"] = False
    assert "tabs" not in setup_changes(d, sheet_tabs(), acme_config())
