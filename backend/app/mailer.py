# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""Outgoing mail: SMTP delivery with a plain-text and HTML body.

Mail is optional. When no SMTP server is configured the caller decides what to
do — the password reset endpoint stays deliberately silent about it so an
attacker cannot use the response to learn whether the instance has a mailer.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage

from . import runtime

logger = logging.getLogger(__name__)


class MailError(RuntimeError):
    """Raised when the SMTP transaction fails."""


@dataclass(frozen=True)
class Message:
    to: str
    subject: str
    text: str
    html: str = ""


def is_configured() -> bool:
    return runtime.mail_config().configured


def send(message: Message, *, timeout: int | None = None) -> None:
    """Send one message synchronously. Raises :class:`MailError` on failure."""
    config = runtime.mail_config()
    if not config.configured:
        raise MailError("No SMTP server is configured.")

    sender = config.from_address
    email = EmailMessage()
    email["From"] = f"{config.from_name} <{sender}>" if config.from_name else sender
    email["To"] = message.to
    email["Subject"] = message.subject
    email.set_content(message.text)
    if message.html:
        email.add_alternative(message.html, subtype="html")

    context = ssl.create_default_context()
    timeout = timeout or 15
    try:
        if config.ssl:
            with smtplib.SMTP_SSL(config.host, config.port, timeout=timeout, context=context) as server:
                if config.username:
                    server.login(config.username, config.password)
                server.send_message(email)
        else:
            with smtplib.SMTP(config.host, config.port, timeout=timeout) as server:
                server.ehlo()
                if config.starttls:
                    server.starttls(context=context)
                    server.ehlo()
                if config.username:
                    server.login(config.username, config.password)
                server.send_message(email)
    except (OSError, smtplib.SMTPException) as exc:
        raise MailError(str(exc)) from exc


def send_safely(message: Message) -> bool:
    """Best-effort send used by request paths that must not fail on SMTP."""
    if not is_configured():
        logger.info("Mail skipped (no SMTP server): %s", message.subject)
        return False
    try:
        send(message)
        return True
    except MailError as exc:
        logger.warning("Mail delivery failed: %s", exc)
        return False


# --------------------------------------------------------------------------- #
# Templates (English on purpose: transactional mail is not part of the i18n
# surface, and a half-translated reset mail is worse than a plain one).


def password_reset_message(*, to: str, link: str, minutes: int, instance: str) -> Message:
    text = (
        f"Someone asked to reset the password of your {instance} account.\n\n"
        f"Choose a new password here: {link}\n\n"
        f"This link expires in {minutes} minutes and can be used once. "
        "If you did not ask for it, ignore this message: your password stays unchanged.\n"
    )
    html = f"""\
<div style="font-family:system-ui,-apple-system,'Segoe UI',sans-serif;font-size:15px;color:#1b1d21;line-height:1.55">
  <p>Someone asked to reset the password of your <strong>{instance}</strong> account.</p>
  <p><a href="{link}" style="display:inline-block;padding:10px 18px;background:#2b5cff;color:#fff;border-radius:8px;text-decoration:none">Choose a new password</a></p>
  <p style="color:#5b6270">Or paste this link in your browser:<br><span style="word-break:break-all">{link}</span></p>
  <p style="color:#5b6270">This link expires in {minutes} minutes and can be used once.
  If you did not ask for it, ignore this message: your password stays unchanged.</p>
</div>"""
    return Message(to=to, subject=f"Reset your {instance} password", text=text, html=html)


def test_message(*, to: str, instance: str) -> Message:
    return Message(
        to=to,
        subject=f"{instance}: test message",
        text=f"This is a test message sent from the {instance} administration page. Delivery works.\n",
        html=(
            '<div style="font-family:system-ui,sans-serif;font-size:15px">'
            f"<p>This is a test message sent from the <strong>{instance}</strong> administration page.</p>"
            "<p>Delivery works.</p></div>"
        ),
    )
