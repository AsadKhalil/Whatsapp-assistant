from evals.run import check, run_case
from tests.fakes import ScriptedLLM, bakery_sheets, call, say


def test_passing_and_failing_cases_are_told_apart():
    case = {"name": "price", "say": ["price?"], "reply_has": ["2500"]}
    assert run_case(case, ScriptedLLM(say("It's Rs 2500")))["failures"] == []
    assert run_case(case, ScriptedLLM(say("No idea")))["failures"] == ["missing '2500'"]


def test_proposal_and_save_checks_follow_the_real_confirmation_path():
    case = {"name": "order", "say": ["2 carrot cakes", "yes"], "saves_to": "Orders"}
    llm = ScriptedLLM(call("propose_row", tab="Orders", values=[{"column": "Item", "value": "Carrot cake"}]))
    assert run_case(case, llm)["failures"] == []
    proposal = {"name": "p", "say": ["2 carrot cakes"], "proposes": {"tab": "Orders", "has": "carrot"}}
    llm = ScriptedLLM(call("propose_row", tab="Orders", values=[{"column": "Item", "value": "Carrot cake"}]))
    assert run_case(proposal, llm)["failures"] == []


def test_group_cases_read_the_group_reply_and_regex_guards_work():
    case = {"name": "g", "group": "staff@g.us", "say": ["@Sara orders?"], "reply_has": ["Ali"]}
    assert run_case(case, ScriptedLLM(say("Ali and Sana")))["failures"] == []
    assert check({"reply_lacks_regex": r"pineapple[^.\n]*\d"}, "Pineapple cake is Rs 1800.", bakery_sheets()) != []
    assert check({"reply_has_any": ["AI", "bot"]}, "I'm an AI assistant", bakery_sheets()) == []
