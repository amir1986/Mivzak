"""Gmail SMTP delivery with the Word file attached."""

from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path


def required_secret(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if name == "GMAIL_APP_PASSWORD":
        value = value.replace(" ", "")
    if not value:
        raise RuntimeError(f"{name} is empty or unavailable")
    return value


def build_message(sender: str, recipient: str, subject: str, plain_body: str,
                  rich_body: str, attachment_path: Path | None) -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message["Content-Language"] = "he"
    message.set_content(plain_body, charset="utf-8")
    message.add_alternative(rich_body, subtype="html")
    if attachment_path is not None:
        attachment_path = Path(attachment_path)
        message.add_attachment(
            attachment_path.read_bytes(),
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=attachment_path.name,
        )
    return message


def send_message(sender: str, app_password: str, message: EmailMessage, timeout: float = 40) -> None:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=timeout) as smtp:
        smtp.login(sender, app_password)
        smtp.send_message(message)


def send_brief(*, sender: str, app_password: str, recipient: str, subject: str,
               plain_body: str, rich_body: str, attachment_path: Path) -> None:
    message = build_message(sender, recipient, subject, plain_body, rich_body, attachment_path)
    send_message(sender, app_password, message)
