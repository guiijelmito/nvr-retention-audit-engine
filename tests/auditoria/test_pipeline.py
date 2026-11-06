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
from nvr_audit_engine.integracoes.lan7 import ResultadoTicket
from tests.apoio import (
    OS_CONCLUIDA,
    REQUESTS_SESSION,
    DataFixa,
    FakeResponse,
    search_responses,
)


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
        api_ok: bool | list[bool] = True,
        motivo_api: str = "ConnectTimeout",
        captura: str | None = "existente",
        ticket=OS_CONCLUIDA,
        limite_dias: int = 730,
    ):
        unidades = {"Escola A": "192.0.2.20"} if unidades is None else unidades
        dados = dict(unidades) if dados is None else dados
        caminho = str(self.evidencia) if captura == "existente" else captura
        consultas = []

        def consultar_dia(sessao, url_base, canal, data_str, escola, **_):
            consultas.append((url_base, canal, data_str, escola))
            for n, resultado in dias.items():
                if dias_atras(n) == data_str:
                    return resultado
            return False

        # api_ok: um valor para todas as chamadas ou uma lista, uma resposta por chamada.
        respostas_api = list(api_ok) if isinstance(api_ok, list) else None

        def verificar_api(sessao, url_base, escola, falha=None):
            ok = respostas_api.pop(0) if respostas_api is not None else api_ok
            if not ok and falha is not None:
                falha.motivo = motivo_api
            return ok

        integracoes = Integracoes(
            capturar_print=Mock(return_value=caminho),
            criar_ticket=Mock(side_effect=ticket if isinstance(ticket, list) else [ticket]),
            enviar_planilha=Mock(),
        )
        registro = RegistroEscolas(self.arquivo_escolas, dados)
        sessao = Mock(spec=requests.Session)
        with (
            patch.object(retencao, "datetime", DataFixa),
            patch.object(escolas, "datetime", DataFixa),
            patch.object(retencao, "LIMITE_DIAS", limite_dias),
            patch.object(pipeline, "consultar_dia", side_effect=consultar_dia),
            patch.object(pipeline, "verificar_api", side_effect=verificar_api),
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
        criar_ticket.assert_called_once_with("Escola A", str(self.evidencia))
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
        self.assertEqual(estado["Escola A"]["ultimo_resultado"], "verificar_no_local")
        self.assertNotIn("status", estado["Escola A"])

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
        # ConnectTimeout é falha de rede: a escola é tentada de novo na segunda passada.
        self.assertEqual(sessao.close.call_count, 2)

    def test_segunda_passada_recupera_nvr_que_oscilou(self):
        linhas, _, criar_ticket, _, estado, _ = self.executar(
            {1: True, 2: False, 3: False, 4: False}, api_ok=[False, True]
        )

        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0]["Dias Contínuos Válidos"], 1)
        self.assertNotIn("Motivo da falha", linhas[0])
        criar_ticket.assert_called_once()
        self.assertEqual(estado["Escola A"]["status"], "aprovada")

    def test_falha_que_nao_e_de_rede_nao_entra_na_segunda_passada(self):
        _, _, _, _, _, sessao = self.executar({}, api_ok=False, motivo_api="401")

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
        self.assertEqual(estado["Escola A"]["ultimo_resultado"], "falha_print")
        self.assertNotIn("status", estado["Escola A"])

    def test_print_inexistente_no_disco_nao_abre_ticket(self):
        _, _, criar_ticket, _, estado, _ = self.executar(
            {1: True, 2: False, 3: False, 4: False},
            captura=str(Path(self.tmp.name) / "nao_existe.png"),
        )

        criar_ticket.assert_not_called()
        self.assertEqual(estado["Escola A"]["ultimo_resultado"], "falha_print")
        self.assertNotIn("status", estado["Escola A"])

    def test_ticket_recebe_o_print_capturado_mesmo_depois_da_meia_noite(self):
        # A captura gravou o print com a data de ontem; o 7LAN não pode recalcular o nome.
        print_de_ontem = self.evidencia.with_name("Escola_A_24-10-2026.png")
        print_de_ontem.write_bytes(b"png")

        _, _, criar_ticket, _, _, _ = self.executar(
            {1: True, 2: False, 3: False, 4: False}, captura=str(print_de_ontem)
        )

        criar_ticket.assert_called_once_with("Escola A", str(print_de_ontem))

    def test_os_aberta_sem_fechamento_nao_aprova_nem_recria(self):
        # CEAPI em 30/10: OS criada, timeout no apontamento, escola aprovada com OS aberta.
        os_aberta = ResultadoTicket(salvar_clicado=True, criada=True, anexada=True,
                                    erro="Locator.evaluate: Timeout 30000ms exceeded.")
        _, _, criar_ticket, _, estado, _ = self.executar(
            {1: True, 2: False, 3: False, 4: False}, ticket=os_aberta
        )

        criar_ticket.assert_called_once()
        self.assertEqual(estado["Escola A"]["ultimo_resultado"], "falha_os")
        self.assertNotIn("status", estado["Escola A"])

    def test_falha_antes_de_salvar_repete_a_os_uma_vez(self):
        falhou_no_formulario = ResultadoTicket(erro="Timeout no campo Cliente")
        _, _, criar_ticket, _, estado, _ = self.executar(
            {1: True, 2: False, 3: False, 4: False},
            ticket=[falhou_no_formulario, OS_CONCLUIDA],
        )

        self.assertEqual(criar_ticket.call_count, 2)
        self.assertEqual(estado["Escola A"]["status"], "aprovada")

    def test_duas_falhas_antes_de_salvar_nao_aprovam(self):
        falhou = ResultadoTicket(erro="Timeout no login")
        _, _, criar_ticket, _, estado, _ = self.executar(
            {1: True, 2: False, 3: False, 4: False}, ticket=[falhou, falhou]
        )

        self.assertEqual(criar_ticket.call_count, 2)
        self.assertEqual(estado["Escola A"]["ultimo_resultado"], "falha_os")
        self.assertNotIn("status", estado["Escola A"])

    def test_ticket_nao_confirmado_nao_aprova(self):
        _, _, criar_ticket, _, estado, _ = self.executar(
            {1: True, 2: False, 3: False, 4: False},
            ticket=ResultadoTicket(salvar_clicado=True),
        )

        criar_ticket.assert_called_once_with("Escola A", str(self.evidencia))
        self.assertEqual(estado["Escola A"]["ultimo_resultado"], "falha_os")
        self.assertNotIn("status", estado["Escola A"])

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

        def consultar_dia(sessao, url_base, canal, data_str, escola, **_):
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
        respostas = iter([
            FakeResponse("result=probe-token\n"),
            FakeResponse("OK\n"),  # cleanup do token de preflight
            *search_responses("found=1\nitems[0].StartTime=2026-01-01 00:00:00\n"),
        ])

        def get(*_, **__):
            resposta = next(respostas, None)
            if resposta is None:  # dali em diante a rede não volta
                raise requests.exceptions.ConnectionError("rede instável")
            return resposta

        session.get.side_effect = get
        session_factory.return_value = session
        integracoes = Integracoes(
            capturar_print=Mock(), criar_ticket=Mock(), enviar_planilha=Mock()
        )

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        registro = RegistroEscolas(Path(tmp.name) / "escolas.json", {})

        with (
            patch.object(retencao, "LIMITE_DIAS", 2),
            redirect_stdout(StringIO()),
        ):
            pipeline.auditar_retencao_nvr_com_cloud(
                registro=registro,
                escolas={"Escola A": "192.0.2.20"},
                integracoes=integracoes,
            )

        linhas = integracoes.enviar_planilha.call_args.args[0]
        self.assertEqual(len(linhas), 1)
        row = linhas[0]
        # A linha final é a da segunda passada, em que a rede já não respondia.
        self.assertEqual(row["Dias Contínuos Válidos"], "Verificação incompleta (API indisponível)")
        self.assertEqual(row["Gravação mais antiga"], "N/A")
        estado = registro.dados["Escola A"]
        self.assertEqual(estado["ultimo_resultado"], "sem_rede")
        self.assertEqual(estado["motivo_falha"], "conexao_caiu")
        self.assertEqual(estado["tentativas"], 1)  # as duas passadas contam como uma execução
        integracoes.criar_ticket.assert_not_called()
        integracoes.capturar_print.assert_not_called()
        # Queda de conexão no meio da contagem: a segunda passada tenta de novo e falha também.
        self.assertEqual(session.close.call_count, 2)


if __name__ == "__main__":
    unittest.main()
