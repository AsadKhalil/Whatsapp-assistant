"""Sends one plain-text email through Gmail's SMTP server with an app password (standard library only)."""
from __future__ import annotations

import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

GMAIL_HOST, GMAIL_PORT = "smtp.gmail.com", 587
# ASCII only: a look-alike letter (say, a Cyrillic one that looks like "a") or a hidden control character could
# make an address read one way in the preview and deliver another way.
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")


def is_email(text: str) -> bool:
    """Exactly one plain ASCII address like name@example.com: no lists, display names, spaces or look-alikes."""
    return len(text) <= 254 and _EMAIL.fullmatch(text) is not None


class MailError(Exception):
    """Sending failed. The message says why in words a person can act on; `kind` is safe to log."""

    def __init__(self, message: str, kind: str) -> None:
        super().__init__(message)
        self.kind = kind  # auth | recipient | network | message


class Mailer:
    def __init__(self, smtp=smtplib.SMTP, host: str = GMAIL_HOST, port: int = GMAIL_PORT,
                 timeout: float = 30) -> None:
        self._smtp, self._host, self._port, self._timeout = smtp, host, port, timeout

    def send(self, address: str, app_password: str, sender_name: str, to: str, subject: str, body: str) -> None:
        try:
            message = EmailMessage()
            message["From"] = formataddr((sender_name, address))
            message["To"] = to
            message["Subject"] = subject
            message.set_content(body)
        except ValueError:  # e.g. a line break in a header
            raise MailError("The address or subject has characters an email can't carry", "message") from None
        try:
            with self._smtp(self._host, self._port, timeout=self._timeout) as smtp:
                smtp.starttls(context=ssl.create_default_context())  # checks Gmail's certificate
                smtp.login(address, "".join(app_password.split()))
                smtp.send_message(message)
        except (smtplib.SMTPAuthenticationError, UnicodeError):  # Gmail logins are ASCII only
            raise MailError("Gmail refused the email address or app password (check the business's Email page)",
                            "auth") from None
        except smtplib.SMTPRecipientsRefused:
            raise MailError(f"Gmail refused the address {to}", "recipient") from None
        except (smtplib.SMTPException, OSError):
            raise MailError("Gmail couldn't be reached right now", "network") from None
