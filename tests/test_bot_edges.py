from app.bot import FALLBACK, TOO_LONG, UNHEARD, UNSUPPORTED
from tests.fakes import call, incoming, make_bot, say, texts


def test_voice_note_is_transcribed_and_answered():
    bot, llm = make_bot(say("Chocolate cake is Rs 2500."), transcript="how much is the chocolate cake")
    bot.meta.audio["media-1"] = b"OggS voice"
    bot.handle(incoming("", kind="audio", audio="media-1"))
    assert llm.calls[0][-1] == {"role": "user", "content": "how much is the chocolate cake"}
    assert texts(bot.meta)[-1].endswith("Chocolate cake is Rs 2500.")


def test_group_voice_notes_become_context_even_when_not_addressed():
    url = "http://waha:3000/api/files/acme/v1.oga"
    bot, llm = make_bot(say("Friday: 20 cupcakes."), transcript="let's bake 20 cupcakes on friday")
    bot.waha.audio[url] = b"OggS"
    bot.handle(incoming("", kind="audio", audio=url, group="staff@g.us", msg_id="v1"))
    assert bot.waha.sent == []
    bot.handle(incoming("@Sara what did we plan?", group="staff@g.us", mention=True, msg_id="v2"))
    assert "Ali: let's bake 20 cupcakes on friday" in [message["content"] for message in llm.calls[0]]


def test_a_voice_note_saying_yes_confirms_a_proposal():
    bot, _ = make_bot(call("propose_row", tab="Orders", values=[{"column": "Item", "value": "Cake"}]),
                      transcript="Yes.")
    bot.handle(incoming("cake"))
    bot.meta.audio["m"] = b"OggS"
    bot.handle(incoming("", kind="audio", audio="m"))
    assert bot.sheets.appended and texts(bot.meta)[-1] == "✅ Added to Orders."


def test_long_or_unclear_voice_notes_get_a_polite_reply():
    bot, llm = make_bot(transcript="")
    bot.meta.audio["big"] = b"x" * 1_000_001
    bot.meta.audio["silent"] = b"OggS"
    bot.handle(incoming("", kind="audio", audio="big"))
    assert texts(bot.meta)[-1].endswith(TOO_LONG)
    bot.handle(incoming("", kind="audio", audio="silent"))
    assert texts(bot.meta)[-1] == UNHEARD
    assert llm.calls == []


# Review focus: code-composed replies must obey the loop breaker too.
def test_voice_note_failures_obey_the_burst_limit():
    bot, _ = make_bot()
    for i in range(8):
        bot.meta.audio[f"v{i}"] = b"x" * 1_000_001
        bot.handle(incoming("", kind="audio", audio=f"v{i}", msg_id=f"v{i}"))
    assert len(bot.meta.sent) == 6


def test_images_get_a_text_only_reply():
    bot, llm = make_bot()
    bot.handle(incoming("", kind="unsupported"))
    assert texts(bot.meta)[-1].endswith(UNSUPPORTED) and llm.calls == []


def test_handoff_writes_a_row_alerts_staff_and_acknowledges():
    bot, _ = make_bot(call("handoff", reason="Wants a custom wedding cake"))
    bot.handle(incoming("I need to talk to someone about a wedding cake"))
    tab, row = bot.sheets.appended[0]
    assert tab == "Handoffs" and row["Reason"] == "Wants a custom wedding cake"
    assert row["Phone"] == "923001234567" and row["Question"] == "I need to talk to someone about a wedding cake"
    chat, alert, _ = bot.waha.sent[0]
    assert chat == "staff@g.us" and "wedding cake" in alert and "923001234567" in alert
    assert texts(bot.meta)[-1].endswith("Someone will get back to you soon.")


def test_handoff_asks_for_a_number_when_it_is_hidden():
    bot, _ = make_bot(call("handoff", reason="Question"))
    bot.handle(incoming("a person please", phone=None))
    assert texts(bot.meta)[-1].endswith("What's the best number to reach you on?")


def test_hidden_phone_customer_can_give_a_number_after_being_asked():
    bot, _ = make_bot(call("handoff", reason="Question"),
                      call("handoff", reason="Call back on 0300 1234567"))
    bot.handle(incoming("a person please", phone=None))
    assert texts(bot.meta)[-1].endswith("What's the best number to reach you on?")
    bot.handle(incoming("0300 1234567", phone=None))
    rows = [row for tab, row in bot.sheets.appended if tab == "Handoffs"]
    assert len(rows) == 2
    assert rows[1]["Question"] == "0300 1234567" and rows[1]["Reason"] == "Call back on 0300 1234567"
    assert not texts(bot.meta)[-1].endswith("number to reach you on?")


def test_model_failure_sends_the_fallback_and_hands_off():
    bot, _ = make_bot(fail=True)
    bot.handle(incoming("hi"))
    assert texts(bot.meta)[-1].endswith(FALLBACK)
    assert bot.sheets.appended[0][0] == "Handoffs"


def test_empty_model_reply_sends_the_fallback_and_hands_off():
    bot, _ = make_bot(say(""))
    bot.handle(incoming("hi"))
    assert texts(bot.meta)[-1].endswith(FALLBACK)
    assert bot.sheets.appended[0][0] == "Handoffs"


def test_exhausted_budget_sends_the_fallback_and_hands_off():
    bot, _ = make_bot(*[call("lookup_rows", tab="Prices", query="x") for _ in range(4)])
    bot.handle(incoming("?"))
    assert texts(bot.meta)[-1].endswith(FALLBACK)
    assert bot.sheets.appended[0][0] == "Handoffs"
