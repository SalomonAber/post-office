from __future__ import annotations

import smtplib
from email.message import EmailMessage

from post_office.config import EmailConfig


class EmailSender:
    def __init__(self, config: EmailConfig) -> None:
        self.config = config

    def send(self, *, subject: str, body: str) -> None:
        if not self.config.enabled:
            return
        message = EmailMessage()
        message["From"] = self.config.from_address
        message["To"] = ", ".join(self.config.to_addresses)
        message["Subject"] = f"{self.config.subject_prefix}: {subject}"
        message.set_content(body)

        with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=30) as smtp:
            if self.config.smtp_starttls:
                smtp.starttls()
            if self.config.smtp_username:
                smtp.login(self.config.smtp_username, self.config.smtp_password or "")
            smtp.send_message(message)
