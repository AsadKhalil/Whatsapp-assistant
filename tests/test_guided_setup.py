import pytest

from app.guided_setup import (AI_DOWN, DRAFT_NOW, MADE_DRAFT, REMINDER, Applied, SetupError, apply_sheet,
                              check_draft, draft_from_args, replace_ticks, setup_changes, summary, tab_plan,
                              take_turn)
from tests.fakes import SETUP_ARGS, FakeSheets, ScriptedLLM, acme_config, bakery_sheets, call, say

# A proposal that always fails the checks: a new tab whose name Google refuses.
BAD_ARGS = {**SETUP_ARGS, "tabs": [{**SETUP_ARGS["tabs"][0], "name": "Bookings/2026"}]}
BAD_PROBLEM = ("tab0", "Bookings/2026: a tab name can't contain [ ] * ? / \\ or :.")
TICKED = {"bot_name": True, "personality": True, "instructions": True}


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
    assert {where for where, _ in check_draft(d, sheet_tabs(), acme_config())} == {"row0"}  # Bot name: not replaced


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
                                 instructions="x" * 4001, replace=TICKED), sheet_tabs(), acme_config())
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


class Budget:
    """spend() for take_turn: allows `left` AI calls."""

    def __init__(self, left: int = 60) -> None:
        self.left, self.used = left, 0

    def __call__(self) -> bool:
        if self.used >= self.left:
            return False
        self.used += 1
        return True


def turn(llm, budget=None, current=None, text="We bake cakes", want_draft=False):
    return take_turn(llm, budget or Budget(), "acme", acme_config(), sheet_tabs(), [], current, text, want_draft)


def test_a_plain_answer_is_the_next_question_and_the_prompt_builds_on_the_sheet():
    llm = ScriptedLLM(say("What do customers ask about most?"))
    t = turn(llm)
    assert t.messages == [{"role": "user", "content": "We bake cakes"},
                          {"role": "assistant", "content": "What do customers ask about most?"}] and t.draft is None
    system = llm.calls[0][0]["content"]
    assert "- Orders: Date, Item, Qty, Name, Phone (permissions already set)" in system
    assert "Sweet Bakes" in system and "- Bot name: Sara" in system and "one short question at a time" in system
    assert llm.tools == [["propose_setup"]]


def test_a_proposal_is_checked_and_becomes_the_draft():
    t = turn(ScriptedLLM(call("propose_setup", **SETUP_ARGS)))
    assert t.messages[-1] == {"role": "assistant", "content": MADE_DRAFT}
    assert t.draft["bot_name"] == "Mia" and t.problems == []


def test_a_failing_draft_goes_back_once_then_is_shown_with_its_problems():
    llm, budget = ScriptedLLM(call("propose_setup", **BAD_ARGS), call("propose_setup", **BAD_ARGS)), Budget()
    t = turn(llm, budget)
    feedback = llm.calls[1][-1]
    assert feedback["role"] == "tool" and "a tab name can't contain" in feedback["content"]
    assert budget.used == 2 and t.draft["tabs"][0]["name"] == "Bookings/2026" and t.problems == [BAD_PROBLEM]
    fixed = turn(ScriptedLLM(call("propose_setup", **BAD_ARGS), call("propose_setup", **SETUP_ARGS)))
    assert fixed.problems == [] and fixed.draft["tabs"][0]["name"] == "Bookings"


def test_a_draft_request_answered_in_text_gets_one_reminder():
    llm = ScriptedLLM(say("Sure! What are your hours?"), call("propose_setup", **SETUP_ARGS))
    t = turn(llm, text=DRAFT_NOW, want_draft=True)
    assert llm.calls[1][-1] == {"role": "user", "content": REMINDER} and t.draft is not None
    stubborn = turn(ScriptedLLM(say("First, your hours?"), say("I still need your hours.")), want_draft=True)
    assert stubborn.draft is None and stubborn.messages[-1]["content"] == "I still need your hours."


def test_the_current_draft_and_its_problems_go_to_the_ai():
    current = draft(tabs=[a_tab("Bad/Name")])
    llm = ScriptedLLM(call("propose_setup", **SETUP_ARGS))
    turn(llm, current=current, text="Make it formal", want_draft=True)
    system = llm.calls[0][0]["content"]
    assert '"name": "Bad/Name"' in system and "Bad/Name: a tab name can't contain" in system
    assert '"basis"' not in system  # the saved settings are listed once, above


def test_ai_errors_and_the_daily_cap_change_nothing():
    budget = Budget()
    with pytest.raises(SetupError, match=AI_DOWN):
        turn(ScriptedLLM(fail=True), budget)
    assert budget.used == 1  # a failed call counts too
    with pytest.raises(SetupError, match="limit for today"):  # the retry is the second call
        turn(ScriptedLLM(call("propose_setup", **BAD_ARGS), call("propose_setup", **SETUP_ARGS)), Budget(left=1))


def test_persona_is_checked_only_where_replace_is_ticked():
    unticked = draft(bot_name="", instructions="x" * 4001)  # acme has both saved: Replace unticked
    assert check_draft(unticked, sheet_tabs(), acme_config()) == []
    ticked = {**unticked, "replace": TICKED}
    assert [where for where, _ in check_draft(ticked, sheet_tabs(), acme_config())] == ["persona", "persona"]


def test_a_replace_tick_made_against_other_saved_text_is_reset():
    d = draft_from_args(SETUP_ARGS, acme_config())  # Personality empty then: ticked
    assert d["basis"]["personality"] == "" and d["replace"]["personality"]
    now = {**acme_config(), "personality": "Formal and brief."}
    assert replace_ticks(d, now)["personality"] is False
    assert "personality" not in setup_changes(d, sheet_tabs(), now)
    seen = {**d, "basis": {**d["basis"], "personality": "Formal  and brief.\r\n"}}  # what the page showed
    assert replace_ticks(seen, now)["personality"] is True  # a tick made while seeing it stands


def test_existing_tabs_and_columns_are_not_held_to_the_rules_for_new_ones():
    long = "Customer delivery address and landmark notes"  # 45 characters
    tabs = {**sheet_tabs(), "Sales 2025/26": [f"C{i}" for i in range(24)] + [long]}
    relisted = a_tab("Sales 2025/26", columns=[*tabs["Sales 2025/26"], "Status"])
    assert check_draft(draft(tabs=[relisted]), tabs, acme_config()) == []
    new = a_tab("Sales 2026/27", columns=relisted["columns"])
    assert {where for where, _ in check_draft(draft(tabs=[new]), tabs, acme_config())} == {"tab0"}


def test_a_contact_column_added_to_a_tab_customers_read_needs_the_tick():
    prices = a_tab("Prices", columns=["Item", "Price", "Supplier phone"])  # acme's customers read Prices
    refused = check_draft(draft(tabs=[prices]), sheet_tabs(), acme_config())
    assert [where for where, _ in refused] == ["tab0"] and "Supplier phone" in refused[0][1]
    assert check_draft(draft(tabs=[{**prices, "confirmed": True}]), sheet_tabs(), acme_config()) == []
    orders = a_tab("Orders", columns=["Supplier phone"])  # customers see only their own Orders rows
    assert check_draft(draft(tabs=[orders]), sheet_tabs(), acme_config()) == []


def test_summary_claims_only_persona_that_actually_changed():
    assert summary(Applied(), {"bot_name": "Mia"}, {"bot_name": "Mia"}) == []
    assert summary(Applied(), {"bot_name": "Mia"}, {"bot_name": "Sara"}) == ["Saved Bot name."]


def test_apply_adds_only_what_is_missing_and_skips_known_questions():
    sheets = bakery_sheets()
    d = draft()
    d["knowledge"].append({"question": "WHAT are  your hours?", "answer": "Twice", "keep": True})  # repeated
    done = apply_sheet(sheets, "acme", acme_config(), d, sheets.tab_headers("sheet-1"), "")
    assert done.error == "" and sheets.written == [
        ("add_tab", "Bookings", ["Date", "Name", "Phone", "Guests"]),
        ("add_columns", "Orders", ["Status"]),
        ("append_rows", "Knowledge", [{"Question": "What are your hours?", "Answer": "Tue-Sun 10am-8pm"}])]
    assert summary(done, {"personality": "x"}, acme_config()) == [
        "Added tab Bookings.", "Added column Status to Orders.", "Added 1 Knowledge row.", "Saved Personality."]


def test_a_new_sheet_gets_the_knowledge_and_handoffs_tabs_first():
    sheets = FakeSheets({})
    done = apply_sheet(sheets, "acme", acme_config(), draft(tabs=[]), {}, "")
    assert [w[:2] for w in sheets.written] == [("add_tab", "Knowledge"), ("add_tab", "Handoffs"),
                                               ("append_rows", "Knowledge")]
    assert sheets.headers("sheet-1", "Handoffs") == ["Time", "Name", "Phone", "Chat", "Question", "Reason"]
    assert done.created == ["Knowledge", "Handoffs"] and done.rows == 2
    changes = {"tabs": {**acme_config()["tabs"], "Leads": {"customer": []}}, "bot_name": "Mia", "personality": "x"}
    assert summary(done, changes, acme_config())[-2:] == ["Saved permissions for Leads.",
                                                          "Saved Bot name and Personality."]


def test_a_failed_step_stops_and_running_again_finishes_without_repeating():
    sheets = bakery_sheets()
    sheets.fail_writes = {"Knowledge"}
    first = apply_sheet(sheets, "acme", acme_config(), draft(), sheets.tab_headers("sheet-1"),
                        "bot@x.iam.gserviceaccount.com")
    assert first.created == ["Bookings"] and first.columns == {"Orders": ["Status"]} and first.rows == 0
    assert first.error == "Share the Sheet with bot@x.iam.gserviceaccount.com as Editor."
    sheets.fail_writes = set()
    second = apply_sheet(sheets, "acme", acme_config(), draft(), sheets.tab_headers("sheet-1"), "")
    assert second.created == [] and second.columns == {} and second.rows == 1 and second.error == ""
