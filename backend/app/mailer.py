# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
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
from html import escape as escape_html

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


def email_verification_message(*, to: str, link: str, hours: int, instance: str, name: str = "") -> Message:
    # Two renderings, two escaping rules: the plain-text part keeps the raw
    # characters, the HTML part escapes them. Mixing the two once put `&amp;`
    # in front of a reader who would have read "&".
    raw_link = link
    raw_hello = f"Hello {name}," if name else "Hello,"
    hello = f"Hello {escape_html(name)}," if name else "Hello,"
    link = escape_html(link, quote=True)
    text = (
        f"{raw_hello}\n\n"
        f"Confirm the address of your {instance} account by opening this link:\n{raw_link}\n\n"
        f"The link works for {hours} hours and only once. If you did not create an account, "
        "ignore this message: nothing happens without the link.\n"
    )
    html = f"""\
<div style="font-family:system-ui,-apple-system,'Segoe UI',sans-serif;font-size:15px;color:#1b1d21;line-height:1.55">
  <p>{hello}</p>
  <p>Confirm the address of your <strong>{instance}</strong> account.</p>
  <p><a href="{link}" style="display:inline-block;padding:10px 18px;background:#2b5cff;color:#fff;border-radius:8px;text-decoration:none">Confirm my address</a></p>
  <p style="color:#5b6270">Or paste this link in your browser:<br><span style="word-break:break-all">{link}</span></p>
  <p style="color:#5b6270">The link works for {hours} hours and only once. If you did not create
  an account, ignore this message: nothing happens without the link.</p>
</div>"""
    return Message(to=to, subject=f"Confirm your {instance} address", text=text, html=html)


def publication_approved_message(
    *, to: str, title: str, kind: str, link: str, instance: str, note: str = "", name: str = ""
) -> Message:
    """Told to an author whose queued content just became public."""
    raw_title, raw_note, raw_link = title, note, link
    hello = f"Hello {name}," if name else "Hello,"
    title = escape_html(title)
    note = escape_html(note)
    link = escape_html(link, quote=True)
    what = "wiki" if kind == "wiki" else "quiz"
    text = (
        f"{hello}\n\n"
        f"Your {what} \"{raw_title}\" is now public on {instance}.\n\n"
        f"Read it here: {raw_link}\n"
    )
    if raw_note:
        text += f"\nNote from the moderator: {raw_note}\n"
    text += "\nYou are receiving this message because you submitted it for publication.\n"
    html = f"""\
<div style="font-family:system-ui,-apple-system,'Segoe UI',sans-serif;font-size:15px;color:#1b1d21;line-height:1.55">
  <p>{hello}</p>
  <p>Your {what} <strong>{title}</strong> is now public on <strong>{instance}</strong>.</p>
  <p><a href="{link}" style="display:inline-block;padding:10px 18px;background:#2b5cff;color:#fff;border-radius:8px;text-decoration:none">Read it</a></p>
  {'<p style="color:#5b6270">Note from the moderator: ' + note + '</p>' if note else ''}
  <p style="color:#5b6270">You are receiving this message because you submitted it for publication.</p>
</div>"""
    return Message(to=to, subject=f"Your {what} is public on {instance}", text=text, html=html)


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
