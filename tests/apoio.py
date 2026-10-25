"""Utilitários compartilhados pelos testes."""

from datetime import datetime

import requests

REQUESTS_SESSION = requests.Session


class DataFixa(datetime):
    """`datetime.now()` congelado em 25/10/2026 10:00 (horário local)."""

    @classmethod
    def now(cls, tz=None):
        base = cls(2026, 10, 25, 10, 0, 0)
        return base if tz is None else base.replace(tzinfo=tz)


class FakeResponse:
    def __init__(self, text="", status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError(f"HTTP {self.status_code}", response=response)


def search_responses(result_text):
    """Sequência factory.create -> findFile -> findNextFile -> close."""
    return [
        FakeResponse("result=token-1\n"),
        FakeResponse("OK\n"),
        FakeResponse(result_text),
        FakeResponse("OK\n"),  # close do token
    ]
