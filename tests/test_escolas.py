"""Lista de escolas, agenda quinzenal e aprovação persistida."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nvr_audit_engine import escolas
from nvr_audit_engine.escolas import RegistroEscolas
from tests.apoio import DataFixa


class AgendaTests(unittest.TestCase):
    def proxima(self, registro):
        with patch.object(escolas, "datetime", DataFixa):
            return RegistroEscolas(Path("escolas.json"), {"Escola A": registro}) \
                .proxima_auditoria_agendada("Escola A")

    def test_aprovada_com_data_futura_fica_bloqueada(self):
        resultado = self.proxima({
            "ip": "192.0.2.20",
            "status": "aprovada",
            "proxima_auditoria_em": "2099-01-01T00:00:00+00:00",
        })

        self.assertEqual(resultado.year, 2099)

    def test_data_passada_ausente_invalida_ou_pendente_libera(self):
        casos = [
            {"status": "aprovada", "proxima_auditoria_em": "2000-01-01T00:00:00+00:00"},
            {"status": "aprovada", "proxima_auditoria_em": None},
            {"status": "aprovada", "proxima_auditoria_em": "amanhã"},
            {"status": "pendente", "proxima_auditoria_em": "2099-01-01T00:00:00+00:00"},
            "192.0.2.20",
        ]
        for registro in casos:
            with self.subTest(registro=registro):
                self.assertIsNone(self.proxima(registro))

    def test_data_sem_fuso_e_interpretada_no_horario_local(self):
        resultado = self.proxima({
            "status": "aprovada", "proxima_auditoria_em": "2099-01-01T00:00:00",
        })

        self.assertIsNotNone(resultado.tzinfo)


class RegistroEscolasTests(unittest.TestCase):
    def test_carregar_aceita_formato_legado_e_com_estado(self):
        with tempfile.TemporaryDirectory() as tmp:
            arquivo = Path(tmp) / "escolas.json"
            arquivo.write_text(json.dumps({
                "A": "10.0.0.1",
                "B": {"ip": "10.0.0.2", "status": "aprovada"},
                "C": {"ip": "  "},
                "D": None,
            }), encoding="utf-8")

            with self.assertLogs("VerthAudit", "WARNING") as logs:
                unidades = RegistroEscolas.carregar(arquivo).unidades_com_ip()

        self.assertEqual(unidades, {"A": "10.0.0.1", "B": "10.0.0.2"})
        self.assertEqual(len(logs.output), 2)

    def test_arquivo_ausente_resulta_em_lista_vazia(self):
        registro = RegistroEscolas.carregar(Path("/nao/existe/escolas.json"))

        self.assertEqual(registro.dados, {})
        self.assertEqual(registro.unidades_com_ip(), {})

    def test_falha_ao_gravar_restaura_o_registro_em_memoria(self):
        with tempfile.TemporaryDirectory() as tmp:
            arquivo = Path(tmp) / "inexistente" / "escolas.json"
            registro = RegistroEscolas(arquivo, {"A": {"ip": "10.0.0.1", "status": "pendente"}})

            with self.assertRaises(OSError):
                registro.marcar_aprovada("A", "10.0.0.1")

        self.assertEqual(registro.dados, {"A": {"ip": "10.0.0.1", "status": "pendente"}})


if __name__ == "__main__":
    unittest.main()
