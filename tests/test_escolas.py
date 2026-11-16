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


class TentativasTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.arquivo = Path(self.tmp.name) / "escolas.json"

    def registrar(self, registro, resultado, motivo=None, de_rede=False):
        with patch.object(escolas, "datetime", DataFixa):
            registro.registrar_tentativa("Escola A", "192.0.2.20", resultado, motivo, de_rede)
        return registro.dados["Escola A"]

    def test_falhas_seguidas_somam_e_aprovacao_zera(self):
        registro = RegistroEscolas(self.arquivo, {"Escola A": "192.0.2.20"})

        self.registrar(registro, "sem_rede", "ConnectTimeout", de_rede=True)
        dados = self.registrar(registro, "sem_rede", "ConnectTimeout", de_rede=True)
        self.assertEqual(dados["tentativas"], 2)
        self.assertEqual(dados["falhas_rede_seguidas"], 2)
        self.assertEqual(dados["motivo_falha"], "ConnectTimeout")
        # Com fuso local, como concluida_em; o fuso depende da máquina.
        self.assertTrue(dados["ultima_tentativa_em"].startswith("2026-10-25T10:00:00"))

        dados = self.registrar(registro, "falha_print", "print não capturado")
        self.assertEqual(dados["tentativas"], 3)
        self.assertEqual(dados["falhas_rede_seguidas"], 0)  # o NVR respondeu

        dados = self.registrar(registro, "aprovada")
        self.assertEqual(dados["tentativas"], 0)
        self.assertIsNone(dados["motivo_falha"])

    def test_grava_no_arquivo_sem_perder_campos_de_aprovacao(self):
        registro = RegistroEscolas(self.arquivo, {
            "Escola A": {"ip": "192.0.2.20", "status": "aprovada", "concluida_em": "x"},
        })

        self.registrar(registro, "incompleta", "401")

        gravado = json.loads(self.arquivo.read_text(encoding="utf-8"))["Escola A"]
        self.assertEqual(gravado["status"], "aprovada")
        self.assertEqual(gravado["concluida_em"], "x")
        self.assertEqual(gravado["ultimo_resultado"], "incompleta")

    def test_pendentes_sao_as_que_falharam_na_ultima_tentativa(self):
        registro = RegistroEscolas(self.arquivo, {
            "Falhou": {"ip": "1", "ultimo_resultado": "falha_os"},
            "Aprovada": {"ip": "2", "ultimo_resultado": "aprovada"},
            "Nunca tentada": {"ip": "3", "status": "pendente"},
            "Legado": "4",
        })

        self.assertEqual(registro.pendentes(), {"Falhou"})


if __name__ == "__main__":
    unittest.main()
