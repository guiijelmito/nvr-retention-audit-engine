"""Fluxo completo da auditoria: contagem, evidência, ticket, estado e planilha."""

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from nvr_audit_engine import config, escolas
from nvr_audit_engine.auditoria import pipeline, retencao
from nvr_audit_engine.auditoria.pipeline import Integracoes
from nvr_audit_engine.escolas import RegistroEscolas
from nvr_audit_engine.nvr import busca_gravacoes
from tests.apoio import REQUESTS_SESSION, DataFixa, FakeResponse, search_responses


def dias_atras(n: int) -> str:
    return (datetime(2026, 10, 25) - timedelta(days=n)).strftime("%Y-%m-%d")


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.arquivo_escolas = Path(self.tmp.name) / "escolas.json"
        self.evidencia = Path(self.tmp.name) / "print.png"
        self.evidencia.write_bytes(b"png")

    def executar(
        self,
        dias: dict[int, bool | None],
        *,
        dados: dict | None = None,
        unidades: dict | None = None,
        api_ok: bool = True,
        captura: str | None = "existente",
        ticket=True,
        limite_dias: int = 730,
    ):
        unidades = {"Escola A": "192.0.2.20"} if unidades is None else unidades
        dados = dict(unidades) if dados is None else dados
        caminho = str(self.evidencia) if captura == "existente" else captura
        consultas = []

        def consultar_dia(sessao, url_base, canal, data_str, escola):
            consultas.append((url_base, canal, data_str, escola))
            for n, resultado in dias.items():
                if dias_atras(n) == data_str:
                    return resultado
            return False

        integracoes = Integracoes(
            capturar_print=Mock(return_value=caminho),
            criar_ticket=Mock(return_value=ticket),
            enviar_planilha=Mock(),
        )
        registro = RegistroEscolas(self.arquivo_escolas, dados)
        sessao = Mock(spec=requests.Session)
        with (
            patch.object(retencao, "datetime", DataFixa),
            patch.object(escolas, "datetime", DataFixa),
            patch.object(retencao, "LIMITE_DIAS", limite_dias),
            patch.object(pipeline, "consultar_dia", side_effect=consultar_dia),
            patch.object(pipeline, "verificar_api", return_value=api_ok),
            patch.object(pipeline.requests, "Session", return_value=sessao),
            redirect_stdout(StringIO()),
        ):
            pipeline.auditar_retencao_nvr_com_cloud(
                registro=registro, escolas=unidades, integracoes=integracoes
            )
        enviar = integracoes.enviar_planilha
        linhas = enviar.call_args.args[0] if enviar.called else None
        return (
            linhas, integracoes.capturar_print, integracoes.criar_ticket,
            consultas, registro.dados, sessao,
        )

    def test_contagem_tolera_ate_dois_vazios_e_para_no_terceiro(self):
        linhas, capturar, criar_ticket, consultas, estado, _ = self.executar(
            {1: True, 2: True, 3: False, 4: True, 5: False, 6: False, 7: False}
        )

        self.assertEqual(linhas, [{
            "Escola": "Escola A",
            "IP do NVR": "192.0.2.20",
            "Dias Contínuos Válidos": 3,
            "Gravação mais antiga": "21/10/2026",
        }])
        self.assertEqual([c[2] for c in consultas], [dias_atras(n) for n in range(1, 8)])
        self.assertEqual(
            consultas[0][:2], ("http://192.0.2.20/cgi-bin/mediaFileFind.cgi", 1)
        )
        capturar.assert_called_once_with("192.0.2.20", "Escola A", "2026", 10)
        criar_ticket.assert_called_once_with("Escola A")
        self.assertEqual(estado["Escola A"]["status"], "aprovada")

    def test_tres_vazios_iniciais_resultam_em_verificar_no_local(self):
        linhas, capturar, criar_ticket, consultas, estado, _ = self.executar(
            {1: False, 2: False, 3: False}
        )

        self.assertEqual(linhas[0]["Dias Contínuos Válidos"], "Verificar no local")
        self.assertEqual(linhas[0]["Gravação mais antiga"], "25/10/2026")
        self.assertEqual(len(consultas), 3)
        capturar.assert_not_called()
        criar_ticket.assert_not_called()
        self.assertEqual(estado["Escola A"], "192.0.2.20")

    def test_limite_de_dias_sem_buraco_conta_tudo_sem_evidencia(self):
        linhas, capturar, criar_ticket, consultas, _, _ = self.executar(
            {n: True for n in range(1, 6)}, limite_dias=5
        )

        self.assertEqual(linhas[0]["Dias Contínuos Válidos"], 5)
        self.assertEqual(linhas[0]["Gravação mais antiga"], "N/A")
        self.assertEqual(len(consultas), 5)
        capturar.assert_not_called()
        criar_ticket.assert_not_called()

    def test_dia_inconclusivo_interrompe_sem_evidencia(self):
        linhas, capturar, criar_ticket, consultas, _, sessao = self.executar(
            {1: True, 2: None, 3: True}
        )

        self.assertEqual(
            linhas[0]["Dias Contínuos Válidos"], "Verificação incompleta (falha da API)"
        )
        self.assertEqual(linhas[0]["Gravação mais antiga"], "N/A")
        self.assertEqual(len(consultas), 2)
        capturar.assert_not_called()
        criar_ticket.assert_not_called()
        sessao.close.assert_called_once()

    def test_api_indisponivel_nao_consulta_dias(self):
        linhas, capturar, _, consultas, _, sessao = self.executar({}, api_ok=False)

        self.assertEqual(linhas, [{
            "Escola": "Escola A",
            "IP do NVR": "192.0.2.20",
            "Dias Contínuos Válidos": "Verificação incompleta (API indisponível)",
            "Gravação mais antiga": "N/A",
        }])
        self.assertEqual(consultas, [])
        capturar.assert_not_called()
        sessao.close.assert_called_once()

    def test_aprovacao_grava_estado_atomico_com_intervalo_de_15_dias(self):
        dados = {"Escola A": {"ip": "192.0.2.20", "status": "pendente", "extra": 1}}
        linhas, _, _, _, estado, _ = self.executar(
            {1: True, 2: False, 3: False, 4: False}, dados=dados
        )

        registro = estado["Escola A"]
        self.assertEqual(registro["status"], "aprovada")
        self.assertEqual(registro["extra"], 1)
        concluida = datetime.fromisoformat(registro["concluida_em"])
        proxima = datetime.fromisoformat(registro["proxima_auditoria_em"])
        self.assertEqual(concluida.replace(tzinfo=None), datetime(2026, 10, 25, 10))
        self.assertEqual(proxima - concluida, timedelta(days=15))
        self.assertEqual(json.loads(self.arquivo_escolas.read_text("utf-8")), estado)
        self.assertTrue(self.arquivo_escolas.read_text("utf-8").endswith("}\n"))
        self.assertFalse(self.arquivo_escolas.with_name("escolas.json.tmp").exists())
        self.assertEqual(linhas[0]["Dias Contínuos Válidos"], 1)

    def test_sem_print_nao_abre_ticket_nem_aprova(self):
        _, capturar, criar_ticket, _, estado, _ = self.executar(
            {1: True, 2: False, 3: False, 4: False}, captura=None
        )

        capturar.assert_called_once()
        criar_ticket.assert_not_called()
        self.assertEqual(estado["Escola A"], "192.0.2.20")
        self.assertFalse(self.arquivo_escolas.exists())

    def test_print_inexistente_no_disco_nao_abre_ticket(self):
        _, _, criar_ticket, _, estado, _ = self.executar(
            {1: True, 2: False, 3: False, 4: False},
            captura=str(Path(self.tmp.name) / "nao_existe.png"),
        )

        criar_ticket.assert_not_called()
        self.assertEqual(estado["Escola A"], "192.0.2.20")

    def test_ticket_nao_confirmado_nao_aprova(self):
        _, _, criar_ticket, _, estado, _ = self.executar(
            {1: True, 2: False, 3: False, 4: False}, ticket=False
        )

        criar_ticket.assert_called_once_with("Escola A")
        self.assertEqual(estado["Escola A"], "192.0.2.20")
        self.assertFalse(self.arquivo_escolas.exists())

    def test_escola_aprovada_dentro_da_janela_e_pulada(self):
        dados = {
            "Escola A": {
                "ip": "192.0.2.20",
                "status": "aprovada",
                "concluida_em": "2026-10-20T10:00:00+00:00",
                "proxima_auditoria_em": "2026-11-04T10:00:00+00:00",
            },
            "Escola B": "192.0.2.21",
        }
        linhas, _, _, consultas, _, _ = self.executar(
            {1: True, 2: False, 3: False, 4: False},
            dados=dados,
            unidades={"Escola A": "192.0.2.20", "Escola B": "192.0.2.21"},
        )

        self.assertEqual([linha["Escola"] for linha in linhas], ["Escola B"])
        self.assertEqual({c[3] for c in consultas}, {"Escola B"})

    def test_nenhuma_escola_processada_nao_envia_planilha(self):
        linhas, *_ = self.executar({}, unidades={}, dados={})

        self.assertIsNone(linhas)

    def test_sem_argumentos_le_data_escolas_json(self):
        self.arquivo_escolas.write_text(json.dumps({
            "Escola A": "192.0.2.20",
            "Escola B": {"ip": "192.0.2.21", "status": "pendente"},
            "Sem IP": {"ip": ""},
        }), encoding="utf-8")
        auditadas = []

        def consultar_dia(sessao, url_base, canal, data_str, escola):
            auditadas.append(escola)
            return False

        with (
            patch.object(config, "ARQUIVO_ESCOLAS", self.arquivo_escolas),
            patch.object(pipeline, "consultar_dia", side_effect=consultar_dia),
            patch.object(pipeline, "verificar_api", return_value=True),
            patch.object(pipeline.requests, "Session"),
            patch.object(pipeline, "Integracoes") as fabrica_integracoes,
            redirect_stdout(StringIO()),
            self.assertLogs("VerthAudit", "WARNING") as logs,
        ):
            pipeline.auditar_retencao_nvr_com_cloud()

        self.assertEqual(sorted(set(auditadas)), ["Escola A", "Escola B"])
        self.assertIn("Unidade ignorada por não possuir IP válido: Sem IP", "\n".join(logs.output))
        fabrica_integracoes.return_value.enviar_planilha.assert_called_once()


class PipelineComCGISimuladaTests(unittest.TestCase):
    @patch.object(pipeline.requests, "Session")
    @patch.object(busca_gravacoes.time, "sleep")
    def test_incomplete_school_is_reported_and_never_creates_ticket(
        self, sleep, session_factory
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
        integracoes = Integracoes(
            capturar_print=Mock(), criar_ticket=Mock(), enviar_planilha=Mock()
        )

        with (
            patch.object(retencao, "LIMITE_DIAS", 2),
            redirect_stdout(StringIO()),
        ):
            pipeline.auditar_retencao_nvr_com_cloud(
                registro=RegistroEscolas(Path("nao-usado.json"), {}),
                escolas={"Escola A": "192.0.2.20"},
                integracoes=integracoes,
            )

        row = integracoes.enviar_planilha.call_args.args[0][0]
        self.assertEqual(row["Dias Contínuos Válidos"], "Verificação incompleta (falha da API)")
        self.assertEqual(row["Gravação mais antiga"], "N/A")
        integracoes.criar_ticket.assert_not_called()
        integracoes.capturar_print.assert_not_called()
        session.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
