import smtplib
import ssl

import pytest

from app.mailer import Mailer, MailError, is_email


def smtp_factory(error=None, at="send"):
    """A stand-in for smtplib.SMTP that records the conversation and can fail at one step."""
    made = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            self.args, self.calls = (host, port, timeout), []
            made.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self, context=None):
            verified = context is not None and context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
            self.calls.append(("starttls", verified))

        def login(self, user, password):
            self.calls.append(("login", user, password))
            if error is not None and at == "login":
                raise error

        def send_message(self, message):
            self.calls.append(("send", message))
            if error is not None and at == "send":
                raise error

    return FakeSMTP, made


def test_sends_one_plain_text_email_over_verified_starttls():
    smtp, made = smtp_factory()
    Mailer(smtp=smtp).send("shop@gmail.com", "abcd efgh ijkl mnop", "Sweet Bakes", "acc@example.com",
                           "September", "Total: Rs 27,300")
    conn = made[0]
    assert conn.args == ("smtp.gmail.com", 587, 30)
    assert conn.calls[0] == ("starttls", True)
    assert conn.calls[1] == ("login", "shop@gmail.com", "abcdefghijklmnop")
    message = conn.calls[2][1]
    assert message["From"] == "Sweet Bakes <shop@gmail.com>" and message["To"] == "acc@example.com"
    assert message["Subject"] == "September" and message.get_content().strip() == "Total: Rs 27,300"


@pytest.mark.parametrize("error, at, kind, reason", [
    (smtplib.SMTPAuthenticationError(535, b"bad credentials"), "login", "auth", "app password"),
    (smtplib.SMTPRecipientsRefused({"acc@example.com": (550, b"no such user")}), "send", "recipient",
     "refused the address acc@example.com"),
    (TimeoutError("slow"), "login", "network", "couldn't be reached"),
    (smtplib.SMTPServerDisconnected("bye"), "send", "network", "couldn't be reached"),
])
def test_gmail_errors_become_one_readable_reason(error, at, kind, reason):
    smtp, _ = smtp_factory(error, at)
    with pytest.raises(MailError, match=reason) as caught:
        Mailer(smtp=smtp).send("shop@gmail.com", "secretpassword12", "Sweet Bakes", "acc@example.com", "Hi", "Text")
    assert caught.value.kind == kind and "secretpassword12" not in str(caught.value)


def test_a_line_break_in_the_subject_is_refused_not_sent():
    smtp, made = smtp_factory()
    with pytest.raises(MailError) as caught:
        Mailer(smtp=smtp).send("shop@gmail.com", "pw", "Sweet Bakes", "acc@example.com", "Hi\nBcc: x@y.com", "Text")
    assert caught.value.kind == "message" and made == []


@pytest.mark.parametrize("text, ok", [
    ("acc@example.com", True), ("first.last@mail.example.co.uk", True),
    ("acc@example", False), ("not an address", False), ("a@example.com, b@example.com", False),
    ("a@example.com;b@example.com", False), ("<a@example.com>", False), ("x" * 250 + "@example.com", False),
])
def test_is_email_accepts_exactly_one_plain_address(text, ok):
    assert is_email(text) is ok
