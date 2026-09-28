from app.bot import FALLBACK
from app.whatsapp import SendError
from tests.fakes import call, incoming, make_bot, say, texts


def test_first_reply_in_a_chat_carries_the_ai_intro_once():
    bot, _ = make_bot(say("Hello Ali!"), say("Anything else?"))
    bot.handle(incoming("hi"))
    bot.handle(incoming("thanks"))
    assert texts(bot.meta) == ["Hi, I'm Sara, Sweet Bakes's AI assistant.\n\nHello Ali!", "Anything else?"]
    assert bot.meta.sent[0][0] == "923001234567"


def test_duplicate_delivery_is_answered_once():
    bot, llm = make_bot(say("Hello"))
    m = incoming("hi", msg_id="wamid.1")
    bot.handle(m)
    bot.handle(m)
    assert len(bot.meta.sent) == 1 and len(llm.calls) == 1


def test_group_message_is_stored_but_answered_only_when_mentioned():
    bot, llm = make_bot(say("Chocolate cake is Rs 2500."))
    bot.handle(incoming("anyone know the cake price?", group="fam@g.us", msg_id="g1"))
    assert bot.waha.sent == [] and llm.calls == []
    bot.handle(incoming("@Sara how much?", group="fam@g.us", mention=True, msg_id="g2"))
    chat, text, quoted = bot.waha.sent[0]
    assert chat == "fam@g.us" and quoted == "g2"
    assert text.endswith("Chocolate cake is Rs 2500.") and "@mention me" in text
    assert llm.calls[0][-2]["content"] == "Ali: anyone know the cake price?"
    assert llm.calls[0][-1]["content"] == "Ali: @Sara how much?"


def test_replying_to_the_bot_counts_as_addressing_it():
    bot, _ = make_bot(say("First"), say("Second"))
    bot.handle(incoming("@Sara hi", group="fam@g.us", mention=True, msg_id="g1"))
    bot.handle(incoming("and tomorrow?", group="fam@g.us", reply_to="waha-1", msg_id="g2"))
    assert texts(bot.waha)[-1] == "Second"


def test_joining_a_group_posts_the_intro_once():
    bot, _ = make_bot(say("Rs 2500"))
    bot.greet("acme", "fam@g.us")
    bot.greet("acme", "fam@g.us")
    assert texts(bot.waha) == ["Hi, I'm Sara, Sweet Bakes's AI assistant. "
                               "I read messages here so I can answer when you @mention me."]
    bot.handle(incoming("@Sara price?", group="fam@g.us", mention=True))
    assert texts(bot.waha)[-1] == "Rs 2500"


def test_own_messages_are_stored_not_answered():
    bot, llm = make_bot()
    m = incoming("typed on the bot's own phone", group="fam@g.us", mention=True)
    m.from_me = True
    bot.handle(m)
    assert llm.calls == [] and bot.waha.sent == []


def test_lookup_result_goes_back_to_the_model():
    bot, llm = make_bot(call("lookup_rows", tab="Prices", query="carrot"), say("Carrot cake is Rs 2200."))
    bot.handle(incoming("carrot cake price?"))
    tool_message = llm.calls[1][-1]
    assert tool_message["role"] == "tool" and tool_message["tool_call_id"] == "call_lookup_rows"
    assert "2200" in tool_message["content"]
    assert texts(bot.meta)[-1].endswith("Carrot cake is Rs 2200.")


def test_staff_member_in_a_customer_group_gets_customer_access():
    bot, llm = make_bot(call("lookup_rows", tab="Staff Notes", query=""), say("Sorry."))
    bot.handle(incoming("@Sara notes?", group="customers@g.us", mention=True, phone="923001111111"))
    assert "not available" in llm.calls[1][-1]["content"]


def test_staff_group_and_staff_numbers_can_read_the_staff_tab():
    bot, llm = make_bot(call("lookup_rows", tab="Staff Notes", query=""), say("Oven 2 is broken."),
                        call("lookup_rows", tab="Staff Notes", query=""), say("Still broken."))
    bot.handle(incoming("@Sara notes?", group="staff@g.us", mention=True))
    assert "Oven 2" in llm.calls[1][-1]["content"]
    bot.handle(incoming("notes?", channel="waha", phone="923001111111"))
    assert "Oven 2" in llm.calls[3][-1]["content"]


def test_system_prompt_has_knowledge_permitted_tabs_and_local_time():
    bot, llm = make_bot(say("ok"))
    bot.handle(incoming("hi"))
    system = llm.calls[0][0]["content"]
    assert "Free above Rs 3000" in system and "- Prices (columns: Item, Price): look up and total rows" in system
    assert "Staff Notes" not in system and "(Asia/Karachi)" in system and "a customer" in system
    assert "call total_rows" in system and "YYYY-MM-DD" in system


def test_totals_come_from_code_and_go_back_to_the_model():
    bot, llm = make_bot(call("total_rows", tab="Expenses", date_column="Date", from_date="2026-06-01",
                             to_date="2026-06-30", sum_column="Amount", group_by="Category", match=""),
                        say("June: Rs 27,300 over 3 entries."))
    bot.handle(incoming("@Sara expenses for June?", group="staff@g.us", mention=True))
    tool_message = llm.calls[1][-1]
    assert '"total": 27300' in tool_message["content"] and '"unreadable_date": 1' in tool_message["content"]
    assert texts(bot.waha)[-1].endswith("June: Rs 27,300 over 3 entries.")


def test_burst_limit_stops_runaway_replies():
    bot, _ = make_bot(*[say(f"r{i}") for i in range(10)])
    for i in range(8):
        bot.handle(incoming(f"m{i}", msg_id=f"b{i}"))
    assert len(bot.meta.sent) == 6


def test_exhausted_model_budget_falls_back():
    bot, _ = make_bot(*[call("lookup_rows", tab="Prices", query="x") for _ in range(4)])
    bot.handle(incoming("?"))
    assert texts(bot.meta)[-1].endswith(FALLBACK)


# Review focus: a reply longer than WhatsApp's limit must still be delivered.
def test_long_model_reply_is_cut_to_whatsapps_limit():
    bot, _ = make_bot(say("x" * 5000))
    bot.handle(incoming("tell me everything"))
    assert len(texts(bot.meta)[-1]) == 4000


# Review focus: Sheets down or a tab renamed must not silence the bot.
def test_sheet_failure_reaches_the_model_as_an_error():
    bot, llm = make_bot(call("lookup_rows", tab="Prices", query="cake"), say("I can't check prices right now."))
    del bot.sheets.tabs["Prices"]
    bot.handle(incoming("price?"))
    assert "couldn't be reached" in llm.calls[1][-1]["content"]
    assert texts(bot.meta)[-1].endswith("I can't check prices right now.")


# Review focus: a failed send must not crash the pipeline or be recorded as sent.
def test_failed_send_is_not_stored_and_the_next_message_still_works():
    bot, _ = make_bot(say("one"), say("two"))
    bot.meta.fail = SendError("meta status=400 code=131047")
    bot.handle(incoming("hi"))
    assert bot.meta.sent == [] and bot.store.bot_has_spoken("acme", "user-923001234567") is False
    bot.meta.fail = None
    bot.handle(incoming("hello again"))
    assert texts(bot.meta) == ["Hi, I'm Sara, Sweet Bakes's AI assistant.\n\ntwo"]
