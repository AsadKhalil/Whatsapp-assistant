import json

from app.llm import ModelReply, ToolCall
from tests.fakes import call, incoming, make_bot, say, texts

ORDER = [{"column": "Item", "value": "Carrot cake"}, {"column": "Qty", "value": "2"}]


def two_proposals(*rows: tuple[str, list]) -> ModelReply:
    """One model reply with a propose_row tool call per (tab, values) pair, mirroring tests.fakes.call."""
    tool_calls = [ToolCall(id=f"call_{i}", name="propose_row", arguments={"tab": tab, "values": values})
                 for i, (tab, values) in enumerate(rows)]
    message = {"role": "assistant", "content": None, "tool_calls": [
        {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
        for tc in tool_calls]}
    return ModelReply(text="", tool_calls=tool_calls, message=message)


def test_proposal_is_composed_by_code_and_saved_only_after_yes():
    bot, llm = make_bot(call("propose_row", tab="Orders", values=ORDER))
    bot.handle(incoming("2 carrot cakes please"))
    assert texts(bot.meta)[-1].endswith(
        "Add to Orders:\n• Item: Carrot cake\n• Qty: 2\n• Name: Ali\n• Phone: 923001234567"
        "\n\nReply YES to confirm or NO to cancel.")
    assert bot.sheets.appended == []
    bot.handle(incoming("Yes!"))
    assert bot.sheets.appended == [("Orders", {"Item": "Carrot cake", "Qty": "2", "Name": "Ali",
                                               "Phone": "923001234567"})]
    assert texts(bot.meta)[-1] == "✅ Added to Orders."
    assert len(llm.calls) == 1  # the YES was handled by code, never by the model


def test_no_cancels_and_a_later_yes_goes_to_the_model():
    bot, _ = make_bot(call("propose_row", tab="Orders", values=ORDER), say("Yes to what?"))
    bot.handle(incoming("cake"))
    bot.handle(incoming("no"))
    assert texts(bot.meta)[-1] == "Cancelled, nothing was saved."
    bot.handle(incoming("yes"))
    assert bot.sheets.appended == [] and texts(bot.meta)[-1] == "Yes to what?"


def test_yes_while_the_burst_limit_is_closed_does_not_save_or_confirm():
    now = [1_000.0]
    bot, _ = make_bot(call("propose_row", tab="Orders", values=ORDER), clock=lambda: now[0])
    bot.handle(incoming("cake"))
    chat_id = "user-923001234567"
    for i in range(6):
        bot.store.save_message("acme", "meta", f"burst-{i}", chat_id, "bot", "Sara", "x", True, now[0])
    bot.handle(incoming("yes"))
    assert bot.sheets.appended == []
    assert bot.store.get_pending("acme", chat_id, chat_id, now[0]) is not None


def test_pending_proposal_is_flagged_in_the_system_prompt():
    bot, llm = make_bot(call("propose_row", tab="Orders", values=ORDER), say("Anything else?"))
    bot.handle(incoming("cake"))
    bot.handle(incoming("what's your address"))
    system = llm.calls[1][0]["content"]
    assert "unconfirmed proposal for Orders" in system


def test_expired_proposal_is_not_saved():
    now = [1_000.0]
    bot, llm = make_bot(call("propose_row", tab="Orders", values=ORDER), say("What would you like?"),
                        clock=lambda: now[0])
    bot.handle(incoming("cake"))
    now[0] += 601
    bot.handle(incoming("yes"))
    assert bot.sheets.appended == [] and len(llm.calls) == 2


def test_staff_rows_are_saved_at_once_and_the_reply_shows_them():
    expense = [{"column": "Date", "value": "2026-09-23"}, {"column": "Item", "value": "Petrol"},
               {"column": "Amount", "value": "1500"}]
    bot, _ = make_bot(call("propose_row", tab="Expenses", values=expense))
    bot.handle(incoming("spent 1500 on petrol today", channel="waha", phone="923001111111"))
    assert bot.sheets.appended == [("Expenses", {"Date": "2026-09-23", "Item": "Petrol", "Amount": "1500"})]
    assert texts(bot.waha)[-1].endswith("✅ Saved to Expenses:\n• Date: 2026-09-23\n• Item: Petrol\n• Amount: 1500")
    assert bot.store.get_pending("acme", "923001111111@c.us", "923001111111@c.us", now=0.0) is None


def test_staff_two_propose_row_calls_both_save_and_both_appear_in_the_reply():
    reply = two_proposals(("Expenses", [{"column": "Item", "value": "Petrol"}]),
                          ("Expenses", [{"column": "Item", "value": "Taxi"}]))
    bot, _ = make_bot(reply)
    bot.handle(incoming("spent on petrol and taxi today", channel="waha", phone="923001111111"))
    assert bot.sheets.appended == [("Expenses", {"Item": "Petrol"}), ("Expenses", {"Item": "Taxi"})]
    assert texts(bot.waha)[-1].count("✅ Saved to Expenses") == 2


def test_staff_one_good_and_one_bad_propose_row_saves_the_good_one():
    reply = two_proposals(("Expenses", [{"column": "Item", "value": "Petrol"}]),
                          ("Expenses", [{"column": "Colour", "value": "red"}]))
    bot, _ = make_bot(reply)
    bot.handle(incoming("log petrol and the van colour", channel="waha", phone="923001111111"))
    assert bot.sheets.appended == [("Expenses", {"Item": "Petrol"})]
    text = texts(bot.waha)[-1]
    assert "✅ Saved to Expenses" in text and "⚠️ Not saved: Unknown column" in text


def test_customer_two_propose_row_calls_only_the_first_becomes_pending():
    reply = two_proposals(("Orders", [{"column": "Item", "value": "Chocolate cake"}]),
                          ("Orders", [{"column": "Item", "value": "Carrot cake"}]))
    bot, _ = make_bot(reply)
    bot.handle(incoming("2 cakes please"))
    assert bot.sheets.appended == []
    pending = bot.store.get_pending("acme", "user-923001234567", "user-923001234567", now=0.0)
    assert pending == ("Orders", {"Item": "Chocolate cake", "Name": "Ali", "Phone": "923001234567"})
    assert texts(bot.meta)[-1].count("Add to Orders:") == 1


def test_staff_save_failure_goes_back_to_the_model_instead_of_claiming_success():
    bot, llm = make_bot(call("propose_row", tab="Expenses", values=[{"column": "Item", "value": "Tape"}]),
                        say("I couldn't save that, the sheet is down."))
    bot.sheets.fail_append = True
    bot.handle(incoming("@Sara log tape", group="staff@g.us", mention=True))
    assert "couldn't be reached" in llm.calls[1][-1]["content"] and bot.sheets.appended == []
    assert "Saved" not in texts(bot.waha)[-1]


def test_failed_append_keeps_the_proposal_for_a_retry():
    bot, _ = make_bot(call("propose_row", tab="Orders", values=ORDER))
    bot.handle(incoming("cake"))
    bot.sheets.fail_append = True
    bot.handle(incoming("yes"))
    assert texts(bot.meta)[-1] == "Couldn't save that, reply YES to try again."
    bot.sheets.fail_append = False
    bot.handle(incoming("yes"))
    assert texts(bot.meta)[-1] == "✅ Added to Orders."


def test_invalid_proposal_goes_back_to_the_model():
    bot, llm = make_bot(call("propose_row", tab="Prices", values=[{"column": "Item", "value": "x"}]),
                        say("I can't change prices."))
    bot.handle(incoming("set the cake price to 1"))
    assert "can't be added" in llm.calls[1][-1]["content"]
    assert texts(bot.meta)[-1].endswith("I can't change prices.")


# Review focus: cheaper models send malformed arguments; the bot must recover, not crash.
def test_malformed_tool_arguments_become_an_error_for_the_model():
    bot, llm = make_bot(call("propose_row", tab="Orders", values="two carrot cakes"), say("How many cakes?"))
    bot.handle(incoming("cakes"))
    assert "No values" in llm.calls[1][-1]["content"]
    assert texts(bot.meta)[-1].endswith("How many cakes?")
