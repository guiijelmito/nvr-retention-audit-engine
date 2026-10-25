"""Inventário de firmware via magicBox.cgi."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from nvr_audit_engine.nvr import firmware


class FirmwareTests(unittest.TestCase):
    def test_funcoes_de_parse(self):
        self.assertEqual(
            firmware.parse_chave_valor("version=2.420\x00\nsn = ABC\nlixo\n"),
            {"version": "2.420", "sn": "ABC"},
        )
        self.assertEqual(
            firmware.separar_versao_build("2.420.0000.0.R,build:2016-01-12"),
            ("2.420.0000.0.R", "2016-01-12"),
        )
        self.assertEqual(firmware.separar_versao_build(""), ("", ""))
        self.assertEqual(firmware.montar_url_base("10.0.0.5"), "http://10.0.0.5")
        self.assertEqual(
            firmware.montar_url_base("10.0.0.5", "https", 8443), "https://10.0.0.5:8443"
        )
        self.assertEqual(
            firmware.montar_url_base("https://nvr.local:444", porta=80),
            "https://nvr.local:444",
        )
        with self.assertRaises(ValueError):
            firmware.montar_url_base("")

    def test_carregar_escolas_aceita_formatos_legado_e_com_estado(self):
        with tempfile.TemporaryDirectory() as tmp:
            arquivo = Path(tmp) / "escolas.json"
            arquivo.write_text(json.dumps({
                "A": "10.0.0.1",
                "B": {"ip": " 10.0.0.2 ", "status": "aprovada"},
                "C": {"host": "10.0.0.3"},
                "D": {"ip": ""},
            }), encoding="utf-8")

            escolas = firmware.carregar_escolas(arquivo)

        self.assertEqual(escolas, {"A": "10.0.0.1", "B": "10.0.0.2", "C": "10.0.0.3"})

    def test_consulta_cai_para_basic_quando_digest_e_recusado(self):
        def resposta(status, texto="", cabecalhos=None):
            r = Mock(status_code=status, text=texto, headers=cabecalhos or {})
            return r

        digest = Mock()
        digest.get.return_value = resposta(401, cabecalhos={"WWW-Authenticate": "Basic realm=x"})
        basic = Mock()
        basic.get.side_effect = [
            resposta(200, "version=2.420.0000.0.R,build:2016-01-12"),
            resposta(200, "version=2.420.0000.0.R,build:2016-01-12"),
            resposta(200, "type=NVR4104"),
            resposta(200, "version=1.00"),
            resposta(200, "sn=SERIE1"),
            resposta(200, "name=NVR"),
            resposta(200, "vendor=Intelbras"),
            resposta(200, "Error\r\nBad Request"),
        ]
        with patch.object(firmware.requests, "Session", side_effect=[digest, basic]):
            resultado = firmware.consultar_nvr("Escola A", "10.0.0.5", "u", "s")

        self.assertEqual(resultado.status, "online")
        self.assertEqual(resultado.autenticacao, "basic")
        self.assertEqual(resultado.modelo, "NVR4104")
        self.assertEqual(resultado.versao_firmware, "2.420.0000.0.R")
        self.assertEqual(resultado.build_firmware, "2016-01-12")
        self.assertEqual(resultado.numero_serie, "SERIE1")
        self.assertEqual(resultado.fabricante, "Intelbras")
        self.assertNotIn("info_sistema", resultado.bruto)

    def test_nvr_inacessivel_fica_offline(self):
        sessao = Mock()
        sessao.get.side_effect = requests.exceptions.ConnectTimeout("sem rota")
        with patch.object(firmware.requests, "Session", return_value=sessao):
            resultado = firmware.consultar_nvr("Escola A", "10.0.0.5", "u", "s")

        self.assertEqual((resultado.status, resultado.erro), ("offline", "NVR inacessível na rede"))


if __name__ == "__main__":
    unittest.main()
