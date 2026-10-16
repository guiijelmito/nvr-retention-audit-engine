import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import Mock, patch

import requests

import nvr_audit

REQUESTS_SESSION = requests.Session


class FakeResponse:
    def __init__(self, text="", status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError(
                f"HTTP {self.status_code}", response=response
            )


def search_responses(result_text):
    return [
        FakeResponse("result=token-1\n"),
        FakeResponse("OK\n"),
        FakeResponse(result_text),
        FakeResponse("OK\n"),  # close do token
    ]


class NvrAuditRetryTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock(spec=requests.Session)
        self.base_url = "http://192.0.2.20/cgi-bin/mediaFileFind.cgi"

    @patch.object(nvr_audit.time, "sleep")
    def test_recovers_from_transient_connection_failure(self, sleep):
        self.session.get.side_effect = [
            requests.exceptions.ReadTimeout("NVR demorou"),
            *search_responses("found=1\nitems[0].StartTime=2026-01-01 00:00:00\n"),
        ]

        result = nvr_audit._consultar_dia(
            self.session, self.base_url, 1, "2026-01-01", "Escola A"
        )

        self.assertIs(result, True)
        sleep.assert_called_once_with(1)
        self.assertEqual(self.session.get.call_count, 5)

    @patch.object(nvr_audit.time, "sleep")
    def test_confirms_empty_only_after_two_valid_empty_responses(self, sleep):
        self.session.get.side_effect = [
            *search_responses("found=0\n"),
            *search_responses("found=0\n"),
        ]

        result = nvr_audit._consultar_dia(
            self.session, self.base_url, 1, "2026-01-01", "Escola A"
        )

        self.assertIs(result, False)
        sleep.assert_not_called()
        self.assertEqual(self.session.get.call_count, 8)

    @patch.object(nvr_audit.time, "sleep")
    def test_legacy_http400_search_is_empty_only_if_findnext_confirms_it(self, sleep):
        empty_search = [
            FakeResponse("result=token-1\n"),
            FakeResponse("Bad Request", status_code=400),
            FakeResponse("found=0\n"),
            FakeResponse("OK\n"),
        ]
        self.session.get.side_effect = [*empty_search, *empty_search]

        result = nvr_audit._consultar_dia(
            self.session, self.base_url, 1, "2026-01-01", "Escola antiga"
        )

        self.assertIs(result, False)
        sleep.assert_not_called()
        self.assertEqual(self.session.get.call_count, 8)

    @patch.object(nvr_audit.time, "sleep")
    def test_http400_with_invalid_findnext_does_not_become_empty(self, sleep):
        failed_search = [
            FakeResponse("result=token-1\n"),
            FakeResponse("Bad Request", status_code=400),
            FakeResponse("Error: invalid finder"),
            FakeResponse("OK\n"),
        ]
        self.session.get.side_effect = failed_search * nvr_audit.TENTATIVAS_API

        result = nvr_audit._consultar_dia(
            self.session, self.base_url, 1, "2026-01-01", "Escola antiga"
        )

        self.assertIsNone(result)
        self.assertEqual(self.session.get.call_count, 4 * nvr_audit.TENTATIVAS_API)
        self.assertEqual(sleep.call_count, nvr_audit.TENTATIVAS_API - 1)

    @patch.object(nvr_audit.time, "sleep")
    def test_confirmation_network_error_retries_pair_instead_of_counting_empty(self, sleep):
        self.session.get.side_effect = [
            *search_responses("found=0\n"),
            requests.exceptions.ConnectionError("queda durante confirmação"),
            *search_responses("found=1\nitems[0].StartTime=2026-01-01 00:00:00\n"),
        ]

        result = nvr_audit._consultar_dia(
            self.session, self.base_url, 1, "2026-01-01", "Escola A"
        )

        self.assertIs(result, True)
        sleep.assert_called_once_with(1)

    @patch.object(nvr_audit.time, "sleep")
    def test_persistent_network_failure_returns_inconclusive(self, sleep):
        self.session.get.side_effect = requests.exceptions.ConnectionError("sem rota")

        result = nvr_audit._consultar_dia(
            self.session, self.base_url, 1, "2026-01-01", "Escola A"
        )

        self.assertIsNone(result)
        self.assertEqual(self.session.get.call_count, nvr_audit.TENTATIVAS_API)
        self.assertEqual(sleep.call_count, nvr_audit.TENTATIVAS_API - 1)

    @patch.object(nvr_audit.time, "sleep")
    def test_authentication_error_is_not_retried_as_network_flakiness(self, sleep):
        self.session.get.return_value = FakeResponse("Unauthorized", status_code=401)

        result = nvr_audit._consultar_dia(
            self.session, self.base_url, 1, "2026-01-01", "Escola A"
        )

        self.assertIsNone(result)
        self.session.get.assert_called_once()
        sleep.assert_not_called()

    @patch.object(nvr_audit.time, "sleep")
    def test_transient_http_503_is_retried(self, sleep):
        self.session.get.side_effect = [
            FakeResponse("temporarily unavailable", status_code=503),
            *search_responses("found=1\nitems[0].StartTime=2026-01-01 00:00:00\n"),
        ]

        result = nvr_audit._consultar_dia(
            self.session, self.base_url, 1, "2026-01-01", "Escola A"
        )

        self.assertIs(result, True)
        sleep.assert_called_once_with(1)

    @patch.object(nvr_audit.time, "sleep")
    def test_malformed_api_response_is_retried_then_inconclusive(self, sleep):
        self.session.get.side_effect = [
            FakeResponse("not a Dahua result"),
            FakeResponse("still malformed"),
            FakeResponse("no result here"),
        ]

        result = nvr_audit._consultar_dia(
            self.session, self.base_url, 1, "2026-01-01", "Escola A"
        )

        self.assertIsNone(result)
        self.assertEqual(self.session.get.call_count, nvr_audit.TENTATIVAS_API)
        self.assertEqual(sleep.call_count, nvr_audit.TENTATIVAS_API - 1)

    @patch.object(nvr_audit, "capturar_print_nvr")
    @patch.object(nvr_audit, "criar_ticket_7lan")
    @patch.object(nvr_audit, "enviar_para_google_sheets")
    @patch.object(nvr_audit.requests, "Session")
    @patch.object(nvr_audit.time, "sleep")
    def test_incomplete_school_is_reported_and_never_creates_ticket(
        self, sleep, session_factory, send_sheet, create_ticket, capture
    ):
        session = Mock(spec=REQUESTS_SESSION)
        session.auth = None
        session.get.side_effect = [
            FakeResponse("result=probe-token\n"),
            FakeResponse("OK\n"),  # cleanup do token de preflight
            *search_responses("found=1\nitems[0].StartTime=2026-01-01 00:00:00\n"),
            requests.exceptions.ConnectionError("rede instável"),
            requests.exceptions.ConnectionError("rede instável"),
            requests.exceptions.ConnectionError("rede instável"),
        ]
        session_factory.return_value = session

        with (
            patch.dict(nvr_audit.ESCOLAS, {"Escola A": "192.0.2.20"}, clear=True),
            patch.object(nvr_audit, "LIMITE_DIAS", 2),
            redirect_stdout(StringIO()),
        ):
            nvr_audit.auditar_retencao_nvr_com_cloud()

        row = send_sheet.call_args.args[0][0]
        self.assertEqual(row["Dias Contínuos Válidos"], "Verificação incompleta (falha da API)")
        self.assertEqual(row["Gravação mais antiga"], "N/A")
        create_ticket.assert_not_called()
        capture.assert_not_called()
        session.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
