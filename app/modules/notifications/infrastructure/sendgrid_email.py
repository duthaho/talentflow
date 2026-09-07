from __future__ import annotations

import json
from collections.abc import Callable
from urllib.request import Request, urlopen

SendGridPost = Callable[[str, dict[str, object], dict[str, str]], None]


class SendGridEmailAdapter:
    def __init__(self, *, api_key: str, sender: str, post: SendGridPost | None = None):
        if not api_key:
            raise ValueError("SENDGRID_API_KEY is required")
        if not sender:
            raise ValueError("NOTIFICATION_FROM_EMAIL is required")
        self.api_key = api_key
        self.sender = sender
        self.post = post or self._post

    def send(self, *, recipient: str, subject: str, text: str) -> None:
        self.post(
            "https://api.sendgrid.com/v3/mail/send",
            {
                "personalizations": [{"to": [{"email": recipient}]}],
                "from": {"email": self.sender},
                "subject": subject,
                "content": [{"type": "text/plain", "value": text}],
            },
            {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )

    @staticmethod
    def _post(url: str, body: dict[str, object], headers: dict[str, str]) -> None:
        request = Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
        with urlopen(request, timeout=10) as response:
            if response.status not in {200, 202}:
                raise RuntimeError(f"SendGrid delivery failed with status {response.status}")
