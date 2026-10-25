import unittest
from unittest.mock import Mock, patch

import requests

from nvr_audit_engine.nvr import busca_gravacoes
from tests.apoio import FakeResponse, search_responses


class BuscaGravacoesRetryTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock(spec=requests.Session)
        self.base_url = "http://192.0.2.20/cgi-bin/mediaFileFind.cgi"

    @patch.object(busca_gravacoes.time, "sleep")
    def test_recovers_from_transient_connection_failure(self, sleep):
        self.session.get.side_effect = [
            requests.exceptions.ReadTimeout("NVR demorou"),
            *search_responses("found=1\nitems[0].StartTime=2026-01-01 00:00:00\n"),
        ]

        result = busca_gravacoes.consultar_dia(
            self.session, self.base_url, 1, "2026-01-01", "Escola A"
        )

        self.assertIs(result, True)
        sleep.assert_called_once_with(1)
        self.assertEqual(self.session.get.call_count, 5)

    @patch.object(busca_gravacoes.time, "sleep")
    def test_confirms_empty_only_after_two_valid_empty_responses(self, sleep):
        self.session.get.side_effect = [
            *search_responses("found=0\n"),
            *search_responses("found=0\n"),
        ]

        result = busca_gravacoes.consultar_dia(
            self.session, self.base_url, 1, "2026-01-01", "Escola A"
        )

        self.assertIs(result, False)
        sleep.assert_not_called()
        self.assertEqual(self.session.get.call_count, 8)

    @patch.object(busca_gravacoes.time, "sleep")
    def test_legacy_http400_search_is_empty_only_if_findnext_confirms_it(self, sleep):
        empty_search = [
            FakeResponse("result=token-1\n"),
            FakeResponse("Bad Request", status_code=400),
            FakeResponse("found=0\n"),
            FakeResponse("OK\n"),
        ]
        self.session.get.side_effect = [*empty_search, *empty_search]

        result = busca_gravacoes.consultar_dia(
            self.session, self.base_url, 1, "2026-01-01", "Escola antiga"
        )

        self.assertIs(result, False)
        sleep.assert_not_called()
        self.assertEqual(self.session.get.call_count, 8)

    @patch.object(busca_gravacoes.time, "sleep")
    def test_http400_with_invalid_findnext_does_not_become_empty(self, sleep):
        failed_search = [
            FakeResponse("result=token-1\n"),
            FakeResponse("Bad Request", status_code=400),
            FakeResponse("Error: invalid finder"),
            FakeResponse("OK\n"),
        ]
        self.session.get.side_effect = failed_search * busca_gravacoes.TENTATIVAS_API

        result = busca_gravacoes.consultar_dia(
            self.session, self.base_url, 1, "2026-01-01", "Escola antiga"
        )

        self.assertIsNone(result)
        self.assertEqual(self.session.get.call_count, 4 * busca_gravacoes.TENTATIVAS_API)
        self.assertEqual(sleep.call_count, busca_gravacoes.TENTATIVAS_API - 1)

    @patch.object(busca_gravacoes.time, "sleep")
    def test_confirmation_network_error_retries_pair_instead_of_counting_empty(self, sleep):
        self.session.get.side_effect = [
            *search_responses("found=0\n"),
            requests.exceptions.ConnectionError("queda durante confirmação"),
            *search_responses("found=1\nitems[0].StartTime=2026-01-01 00:00:00\n"),
        ]

        result = busca_gravacoes.consultar_dia(
            self.session, self.base_url, 1, "2026-01-01", "Escola A"
        )

        self.assertIs(result, True)
        sleep.assert_called_once_with(1)

    @patch.object(busca_gravacoes.time, "sleep")
    def test_persistent_network_failure_returns_inconclusive(self, sleep):
        self.session.get.side_effect = requests.exceptions.ConnectionError("sem rota")

        result = busca_gravacoes.consultar_dia(
            self.session, self.base_url, 1, "2026-01-01", "Escola A"
        )

        self.assertIsNone(result)
        self.assertEqual(self.session.get.call_count, busca_gravacoes.TENTATIVAS_API)
        self.assertEqual(sleep.call_count, busca_gravacoes.TENTATIVAS_API - 1)

    @patch.object(busca_gravacoes.time, "sleep")
    def test_authentication_error_is_not_retried_as_network_flakiness(self, sleep):
        self.session.get.return_value = FakeResponse("Unauthorized", status_code=401)

        result = busca_gravacoes.consultar_dia(
            self.session, self.base_url, 1, "2026-01-01", "Escola A"
        )

        self.assertIsNone(result)
        self.session.get.assert_called_once()
        sleep.assert_not_called()

    @patch.object(busca_gravacoes.time, "sleep")
    def test_transient_http_503_is_retried(self, sleep):
        self.session.get.side_effect = [
            FakeResponse("temporarily unavailable", status_code=503),
            *search_responses("found=1\nitems[0].StartTime=2026-01-01 00:00:00\n"),
        ]

        result = busca_gravacoes.consultar_dia(
            self.session, self.base_url, 1, "2026-01-01", "Escola A"
        )

        self.assertIs(result, True)
        sleep.assert_called_once_with(1)

    @patch.object(busca_gravacoes.time, "sleep")
    def test_malformed_api_response_is_retried_then_inconclusive(self, sleep):
        self.session.get.side_effect = [
            FakeResponse("not a Dahua result"),
            FakeResponse("still malformed"),
            FakeResponse("no result here"),
        ]

        result = busca_gravacoes.consultar_dia(
            self.session, self.base_url, 1, "2026-01-01", "Escola A"
        )

        self.assertIsNone(result)
        self.assertEqual(self.session.get.call_count, busca_gravacoes.TENTATIVAS_API)
        self.assertEqual(sleep.call_count, busca_gravacoes.TENTATIVAS_API - 1)


if __name__ == "__main__":
    unittest.main()
