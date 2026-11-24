from email.message import EmailMessage
from smtplib import SMTP


class SmtpEmailAdapter:
    def __init__(self, *, host: str, port: int, sender: str):
        if not host:
            raise ValueError("NOTIFICATION_SMTP_HOST is required")
        if not 1 <= port <= 65535:
            raise ValueError("NOTIFICATION_SMTP_PORT must be between 1 and 65535")
        if not sender:
            raise ValueError("NOTIFICATION_FROM_EMAIL is required")
        self.host = host
        self.port = port
        self.sender = sender

    def send(self, *, recipient: str, subject: str, text: str) -> None:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(text)
        with SMTP(self.host, self.port, timeout=10) as smtp:
            smtp.send_message(message)
