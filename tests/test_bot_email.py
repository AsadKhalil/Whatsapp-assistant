import logging
from dataclasses import replace

import pytest

from app.bot import EMAIL_DAILY_LIMIT
from app.mailer import MailError
from tests.fakes import call, incoming, make_bot, say, texts

STAFF = "923001111111"  # a staff number of the acme bakery (tests.fakes.make_client)
NOW = 1_790_000_000.0
EMAIL = {"to": "acc@example.com", "subject": "September expenses", "body": "Total: Rs 27,300.\n\nSweet Bakes"}


def email_bot(*replies, **options):
    """The acme bot with its Gmail set up."""
    bot, llm = make_bot(*replies, **options)
    bot.clients["acme"] = replace(bot.clients["acme"], email_address="shop@gmail.com",
                                  email_app_password="abcdefghijklmnop")
    return bot, llm


def test_only_staff_of_a_business_with_email_are_offered_send_email():
    bot, llm = email_bot(say("Hi"), say("Hi"))
    bot.handle(incoming("hi", phone=STAFF))
    bot.handle(incoming("hi"))  # a customer
    assert "send_email" in llm.tools[0] and "send_email" not in llm.tools[1]
    assert "can't send email" in llm.calls[1][0]["content"]
    plain, plain_llm = make_bot(say("Hi"))  # no Gmail set up
    plain.handle(incoming("hi", phone=STAFF))
    assert "send_email" not in plain_llm.tools[0]


def test_staff_email_is_previewed_then_sent_on_yes():
    bot, _ = email_bot(call("send_email", **EMAIL))
    bot.handle(incoming("email the accountant september expenses", phone=STAFF))
    preview = texts(bot.meta)[-1]
    assert "To: acc@example.com" in preview and "Subject: September expenses" in preview
    assert "Total: Rs 27,300." in preview and "Reply YES to send" in preview
    assert bot.mailer.sent == []
    bot.handle(incoming("yes", phone=STAFF))
    assert bot.mailer.sent == [{"address": "shop@gmail.com", "app_password": "abcdefghijklmnop",
                                "sender_name": "Sweet Bakes", "to": "acc@example.com",
                                "subject": "September expenses", "body": EMAIL["body"]}]
    assert texts(bot.meta)[-1] == "✅ Email sent to acc@example.com."


def test_no_cancels_the_email():
    bot, _ = email_bot(call("send_email", **EMAIL))
    bot.handle(incoming("email it", phone=STAFF))
    bot.handle(incoming("no", phone=STAFF))
    assert bot.mailer.sent == [] and texts(bot.meta)[-1] == "Cancelled, nothing was sent."


def test_only_the_staff_member_who_asked_can_confirm():
    bot, _ = email_bot(call("send_email", **EMAIL))
    bot.handle(incoming("@Sara email the accountant", group="staff@g.us", mention=True, phone=STAFF))
    bot.handle(incoming("yes", group="staff@g.us", phone="923009999999"))  # another member of the staff group
    assert bot.mailer.sent == []
    bot.handle(incoming("yes", group="staff@g.us", phone=STAFF))
    assert len(bot.mailer.sent) == 1


def test_a_failed_send_keeps_the_email_for_another_yes():
    bot, _ = email_bot(call("send_email", **EMAIL))
    bot.handle(incoming("email it", phone=STAFF))
    bot.mailer.fail = MailError("Gmail couldn't be reached right now", "network")
    bot.handle(incoming("yes", phone=STAFF))
    assert "Couldn't send the email: Gmail couldn't be reached right now" in texts(bot.meta)[-1]
    bot.mailer.fail = None
    bot.handle(incoming("yes", phone=STAFF))
    assert len(bot.mailer.sent) == 1


def test_an_email_waits_ten_minutes_for_yes():
    now = [NOW]
    bot, _ = email_bot(call("send_email", **EMAIL), say("Hello!"), clock=lambda: now[0])
    bot.handle(incoming("email it", phone=STAFF))
    now[0] += 601
    bot.handle(incoming("yes", phone=STAFF))  # too late: now it's an ordinary message
    assert bot.mailer.sent == [] and texts(bot.meta)[-1] == "Hello!"


@pytest.mark.parametrize("change", [{"to": "a@example.com, b@example.com"}, {"to": "not an address"},
                                    {"subject": "x" * 201}, {"body": ""}, {"body": "x" * 3501}])
def test_bad_emails_go_back_to_the_model_without_a_preview(change):
    bot, llm = email_bot(call("send_email", **{**EMAIL, **change}), say("Which address?"))
    bot.handle(incoming("email it", phone=STAFF))
    assert "error" in llm.calls[1][-1]["content"] and texts(bot.meta)[-1].endswith("Which address?")
    assert bot.store.get_pending_email("acme", f"user-{STAFF}", f"user-{STAFF}", NOW) is None


def test_the_51st_email_in_a_day_is_refused():
    bot, llm = email_bot(call("send_email", **EMAIL), say("That's the limit for today."))
    for _ in range(EMAIL_DAILY_LIMIT):
        bot.store.record_email_sent("acme", NOW - 60)
    bot.handle(incoming("email it", phone=STAFF))
    assert "50 emails" in llm.calls[1][-1]["content"] and bot.mailer.sent == []


def test_a_customer_cant_send_email_even_if_the_model_tries():
    bot, llm = email_bot(call("send_email", **EMAIL), say("I can't send email."))
    bot.handle(incoming("email my order to me"))
    assert "isn't available" in llm.calls[1][-1]["content"] and bot.mailer.sent == []


def test_logs_never_hold_the_email(caplog):
    caplog.set_level(logging.DEBUG)
    bot, _ = email_bot(call("send_email", **EMAIL))
    bot.handle(incoming("email it", phone=STAFF))
    bot.handle(incoming("yes", phone=STAFF))
    assert "email_sent client=acme" in caplog.text
    for secret in ("acc@example.com", "September", "27,300", "abcdefghijklmnop", "shop@gmail.com"):
        assert secret not in caplog.text
