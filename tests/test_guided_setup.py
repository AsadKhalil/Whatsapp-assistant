import pytest

from app.guided_setup import (AI_DOWN, DRAFT_NOW, MADE_DRAFT, REMINDER, SetupError, check_draft, draft_from_args,
                              setup_changes, tab_plan, take_turn)
from tests.fakes import SETUP_ARGS, ScriptedLLM, acme_config, bakery_sheets, call, say


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
    bad = {**SETUP_ARGS, "bot_name": ""}
    llm, budget = ScriptedLLM(call("propose_setup", **bad), call("propose_setup", **bad)), Budget()
    t = turn(llm, budget)
    feedback = llm.calls[1][-1]
    assert feedback["role"] == "tool" and "Bot name: 1 to 40" in feedback["content"]
    assert budget.used == 2 and t.draft["bot_name"] == ""
    assert t.problems == [("persona", "Bot name: 1 to 40 characters.")]
    fixed = turn(ScriptedLLM(call("propose_setup", **bad), call("propose_setup", **SETUP_ARGS)))
    assert fixed.problems == [] and fixed.draft["bot_name"] == "Mia"


def test_a_draft_request_answered_in_text_gets_one_reminder():
    llm = ScriptedLLM(say("Sure! What are your hours?"), call("propose_setup", **SETUP_ARGS))
    t = turn(llm, text=DRAFT_NOW, want_draft=True)
    assert llm.calls[1][-1] == {"role": "user", "content": REMINDER} and t.draft is not None
    stubborn = turn(ScriptedLLM(say("First, your hours?"), say("I still need your hours.")), want_draft=True)
    assert stubborn.draft is None and stubborn.messages[-1]["content"] == "I still need your hours."


def test_the_current_draft_and_its_problems_go_to_the_ai():
    current = draft(bot_name="")
    llm = ScriptedLLM(call("propose_setup", **SETUP_ARGS))
    turn(llm, current=current, text="Make it formal", want_draft=True)
    system = llm.calls[0][0]["content"]
    assert '"bot_name": ""' in system and "Bot name: 1 to 40 characters." in system


def test_ai_errors_and_the_daily_cap_change_nothing():
    budget = Budget()
    with pytest.raises(SetupError, match=AI_DOWN):
        turn(ScriptedLLM(fail=True), budget)
    assert budget.used == 1  # a failed call counts too
    bad = {**SETUP_ARGS, "bot_name": ""}
    with pytest.raises(SetupError, match="limit for today"):  # the retry is the second call
        turn(ScriptedLLM(call("propose_setup", **bad), call("propose_setup", **SETUP_ARGS)), Budget(left=1))
