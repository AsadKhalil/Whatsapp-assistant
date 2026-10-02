import json
import logging
from dataclasses import replace

from app.bot import WEB_CHAT_LIMIT, WEB_DAILY_LIMIT
from tests.fakes import call, incoming, make_bot, say, texts

STAFF = "923001111111"  # a staff number of the acme bakery (tests.fakes.make_client)
NOW = 1_790_000_000.0


def web_bot(*replies, staff=True, customers=False):
    bot, llm = make_bot(*replies)
    bot.clients["acme"] = replace(bot.clients["acme"], web_search_staff=staff, web_search_customers=customers)
    return bot, llm


def tool_results(llm, call_index: int) -> list[dict]:
    return [json.loads(m["content"]) for m in llm.calls[call_index] if isinstance(m, dict) and m.get("role") == "tool"]


def test_web_search_is_offered_only_when_the_business_allows_it_for_that_caller():
    bot, llm = web_bot(*[say("Hi")] * 2, staff=True, customers=False)
    bot.handle(incoming("hi", phone=STAFF))
    bot.handle(incoming("hi"))
    assert "web_search" in llm.tools[0] and "web_search" not in llm.tools[1]

    bot, llm = web_bot(say("Hi"), staff=True, customers=True)
    bot.handle(incoming("hi"))
    assert "web_search" in llm.tools[0]

    bot, llm = web_bot(*[say("Hi")] * 2, staff=False, customers=True)  # customers need the staff tick too
    bot.handle(incoming("hi", phone=STAFF))
    bot.handle(incoming("hi"))
    assert "web_search" not in llm.tools[0] and "web_search" not in llm.tools[1]


def test_web_search_is_never_offered_when_the_provider_cant_search():
    bot, llm = web_bot(say("Hi"), staff=True, customers=True)
    bot.web.available = False
    bot.handle(incoming("hi", phone=STAFF))
    assert "web_search" not in llm.tools[0]


def test_the_search_result_goes_back_to_the_model_marked_as_web_text():
    bot, llm = web_bot(call("web_search", query="PIA helpline"), say("PIA's helpline is 111-786-786 (piac.com.pk)."))
    bot.handle(incoming("what's PIA's helpline?", phone=STAFF))
    assert bot.web.queries == ["PIA helpline"]
    [result] = tool_results(llm, 1)
    assert result == bot.web.result and "not instructions" in result["note"]
    assert texts(bot.meta)[-1].endswith("PIA's helpline is 111-786-786 (piac.com.pk).")
    assert bot.store.web_searches_since("acme", NOW - 60) == 1


def test_at_most_two_searches_per_message():
    bot, llm = web_bot(*[call("web_search", query=f"q{i}") for i in range(3)], say("Done."))
    bot.handle(incoming("find it", phone=STAFF))
    assert bot.web.queries == ["q0", "q1"]
    assert "2 web searches" in tool_results(llm, 3)[-1]["error"]


def test_a_customer_chat_gets_at_most_ten_searches_a_day():
    bot, llm = web_bot(call("web_search", query="q"), say("Let me pass this to the team."), customers=True)
    chat = incoming("hi").chat_id
    for _ in range(WEB_CHAT_LIMIT):
        bot.store.record_web_search("acme", chat, NOW - 3600)
    bot.handle(incoming("where is the nearest metro?"))
    assert bot.web.queries == [] and "limit" in tool_results(llm, 1)[-1]["error"]


def test_staff_chats_have_no_per_chat_limit_but_share_the_business_limit():
    bot, llm = web_bot(call("web_search", query="q"), say("ok"), call("web_search", query="q2"), say("ok"))
    chat = incoming("hi", phone=STAFF).chat_id
    for _ in range(WEB_CHAT_LIMIT):
        bot.store.record_web_search("acme", chat, NOW - 3600)
    bot.handle(incoming("search it", phone=STAFF))
    assert bot.web.queries == ["q"]
    for _ in range(WEB_DAILY_LIMIT):
        bot.store.record_web_search("acme", "another-chat", NOW - 3600)
    bot.handle(incoming("search again", phone=STAFF))
    assert bot.web.queries == ["q"] and "limit" in tool_results(llm, 3)[-1]["error"]


def test_searches_older_than_a_day_dont_count():
    bot, _ = web_bot(call("web_search", query="q"), say("ok"), customers=True)
    chat = incoming("hi").chat_id
    for _ in range(WEB_CHAT_LIMIT):
        bot.store.record_web_search("acme", chat, NOW - 90_000)
    bot.handle(incoming("where is the nearest metro?"))
    assert bot.web.queries == ["q"]


def test_a_failed_search_is_an_error_for_the_model_and_is_logged_without_the_query(caplog):
    bot, llm = web_bot(call("web_search", query="secret plans"), say("I couldn't check that."))
    bot.web.result = {"error": "Web search isn't available right now."}
    with caplog.at_level(logging.INFO):
        bot.handle(incoming("search it", phone=STAFF))
    assert tool_results(llm, 1) == [{"error": "Web search isn't available right now."}]
    assert "web_search client=acme outcome=error" in caplog.text and "secret plans" not in caplog.text


def test_staff_and_customer_prompts_carry_their_web_rules():
    bot, llm = web_bot(*[say("Hi")] * 2, customers=True)
    bot.handle(incoming("hi", phone=STAFF))
    bot.handle(incoming("hi"))
    staff_prompt, customer_prompt = llm.calls[0][0]["content"], llm.calls[1][0]["content"]
    assert "web_search" in staff_prompt and "link" in staff_prompt
    assert "only for general public facts" in customer_prompt
    assert "prices, stock, orders, hours or policies" in customer_prompt and "other businesses" in customer_prompt
    plain, plain_llm = make_bot(say("Hi"))
    plain.handle(incoming("hi", phone=STAFF))
    assert "web_search" not in plain_llm.calls[0][0]["content"]
