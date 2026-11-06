"""Rótulos de falha usados no log, no resumo e na segunda passada (Dor 1)."""

import unittest

import requests
from urllib3.exceptions import NewConnectionError

from nvr_audit_engine.nvr.busca_gravacoes import (
    MOTIVOS_REDE,
    RespostaCGIInvalida,
    classificar_falha,
)


def erro_http(codigo):
    resposta = requests.Response()
    resposta.status_code = codigo
    return requests.HTTPError(f"{codigo} Client Error", response=resposta)


def conexao_recusada():
    # Como o requests embrulha um "connection refused" do urllib3.
    causa = NewConnectionError(None, "[WinError 10061] Nenhuma conexão pôde ser feita")
    return requests.exceptions.ConnectionError(causa)


class ClassificarFalhaTests(unittest.TestCase):
    def test_rotulos(self):
        casos = [
            # ConnectTimeout também é ConnectionError: precisa vencer a regra genérica.
            (requests.exceptions.ConnectTimeout("connect timeout=5"), "ConnectTimeout"),
            (requests.exceptions.ReadTimeout("read timeout=20"), "ReadTimeout"),
            (conexao_recusada(), "conexao_recusada"),
            (requests.exceptions.ConnectionError("Connection aborted."), "conexao_caiu"),
            (erro_http(401), "401"),
            (erro_http(503), "http_503"),
            (requests.exceptions.ChunkedEncodingError("Connection broken"), "resposta_truncada"),
            (RespostaCGIInvalida("findNextFile não retornou found="), "resposta_invalida"),
        ]
        for exc, esperado in casos:
            with self.subTest(exc=type(exc).__name__, esperado=esperado):
                self.assertEqual(classificar_falha(exc), esperado)

    def test_so_falhas_de_rede_entram_na_segunda_passada(self):
        self.assertIn(classificar_falha(requests.exceptions.ConnectTimeout()), MOTIVOS_REDE)
        self.assertNotIn(classificar_falha(erro_http(401)), MOTIVOS_REDE)
        self.assertNotIn(classificar_falha(RespostaCGIInvalida("x")), MOTIVOS_REDE)


if __name__ == "__main__":
    unittest.main()
