"""Testes de caracterização: fixam o comportamento atual antes da reorganização."""

import json
import math
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

import requests

import cloud_sync
import nvr_audit
import nvr_firmware


class DataFixa(datetime):
    """`datetime.now()` congelado em 25/10/2026 10:00 (horário local)."""

    @classmethod
    def now(cls, tz=None):
        base = cls(2026, 10, 25, 10, 0, 0)
        return base if tz is None else base.replace(tzinfo=tz)


def dias_atras(n: int) -> str:
    return (datetime(2026, 10, 25) - timedelta(days=n)).strftime("%Y-%m-%d")


class AuditoriaCaracterizacaoTests(unittest.TestCase):
    """Contagem de dias contínuos, evidência, ticket, estado e planilha."""

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
        escolas: dict | None = None,
        api_ok: bool = True,
        captura: str | None = "existente",
        ticket=True,
        limite_dias: int = 730,
    ):
        escolas = {"Escola A": "192.0.2.20"} if escolas is None else escolas
        dados = dict(escolas) if dados is None else dados
        caminho = str(self.evidencia) if captura == "existente" else captura
        consultas = []

        def consultar_dia(sessao, url_base, canal, data_str, escola):
            consultas.append((url_base, canal, data_str, escola))
            for n, resultado in dias.items():
                if dias_atras(n) == data_str:
                    return resultado
            return False

        capturar = Mock(return_value=caminho)
        criar_ticket = Mock(return_value=ticket)
        enviar = Mock()
        sessao = Mock(spec=requests.Session)
        with (
            patch.object(nvr_audit, "datetime", DataFixa),
            patch.dict(nvr_audit.ESCOLAS, escolas, clear=True),
            patch.dict(nvr_audit.DADOS_ESCOLAS, dados, clear=True),
            patch.object(nvr_audit, "ARQUIVO_ESCOLAS", self.arquivo_escolas),
            patch.object(nvr_audit, "LIMITE_DIAS", limite_dias),
            patch.object(nvr_audit, "_consultar_dia", side_effect=consultar_dia),
            patch.object(nvr_audit, "_verificar_api", return_value=api_ok),
            patch.object(nvr_audit.requests, "Session", return_value=sessao),
            patch.object(nvr_audit, "capturar_print_nvr", capturar),
            patch.object(nvr_audit, "criar_ticket_7lan", criar_ticket),
            patch.object(nvr_audit, "enviar_para_google_sheets", enviar),
            redirect_stdout(StringIO()),
        ):
            nvr_audit.auditar_retencao_nvr_com_cloud()
            estado = dict(nvr_audit.DADOS_ESCOLAS)
        linhas = enviar.call_args.args[0] if enviar.called else None
        return linhas, capturar, criar_ticket, consultas, estado, sessao

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
            escolas={"Escola A": "192.0.2.20", "Escola B": "192.0.2.21"},
        )

        self.assertEqual([linha["Escola"] for linha in linhas], ["Escola B"])
        self.assertEqual({c[3] for c in consultas}, {"Escola B"})

    def test_nenhuma_escola_processada_nao_envia_planilha(self):
        linhas, *_ = self.executar({}, escolas={}, dados={})

        self.assertIsNone(linhas)


class AgendaCaracterizacaoTests(unittest.TestCase):
    def proxima(self, registro):
        with (
            patch.object(nvr_audit, "datetime", DataFixa),
            patch.dict(nvr_audit.DADOS_ESCOLAS, {"Escola A": registro}, clear=True),
        ):
            return nvr_audit._proxima_auditoria_agendada("Escola A")

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


class PlanilhaCaracterizacaoTests(unittest.TestCase):
    def enviar(self, valores_atuais, resultados):
        aba = Mock()
        aba.get_all_values.return_value = valores_atuais
        cliente = Mock()
        cliente.open.return_value.worksheet.return_value = aba
        with (
            patch.object(cloud_sync, "datetime", DataFixa),
            patch.object(cloud_sync.Credentials, "from_service_account_file"),
            patch.object(cloud_sync.gspread, "authorize", return_value=cliente),
        ):
            cloud_sync.enviar_para_google_sheets(resultados)
        return cliente, aba

    def test_atualiza_escola_existente_e_acrescenta_nova_na_coluna_do_dia(self):
        atuais = [
            ["Escola", "IP do NVR", "Último dia de gravação", "Dias Contínuos de Gravação: 10/10/2026"],
            ["Escola A", "10.0.0.1", "01/09/2026", "40"],
            ["Escola C", "10.0.0.3", "02/09/2026", "38"],
        ]
        resultados = [
            {"Escola": "Escola A", "IP do NVR": "10.0.0.9", "Dias Contínuos Válidos": 45,
             "Gravação mais antiga": "10/09/2026"},
            {"Escola": "Escola B", "IP do NVR": "10.0.0.2",
             "Dias Contínuos Válidos": "Verificar no local", "Gravação mais antiga": "25/10/2026"},
        ]

        cliente, aba = self.enviar(atuais, resultados)

        cliente.open.assert_called_once_with("Gravações escolas 2026")
        cliente.open.return_value.worksheet.assert_called_once_with("Gravações Quinzenais 2026")
        aba.clear.assert_called_once()
        payload = aba.update.call_args.args[0]
        self.assertEqual(payload[0], [
            "Escola", "IP do NVR", "Último dia de gravação",
            "Dias Contínuos de Gravação: 10/10/2026",
            "Dias Contínuos de Gravação: 25/10/2026",
        ])
        self.assertEqual(payload[1], ["Escola A", "10.0.0.9", "10/09/2026", 40, 45])
        self.assertEqual(payload[2], ["Escola C", "10.0.0.3", "02/09/2026", 38, ""])
        self.assertEqual(payload[3][:3], ["Escola B", "10.0.0.2", "25/10/2026"])
        self.assertEqual(payload[3][4], "Verificar no local")
        # Comportamento atual (bug conhecido): escola nova recebe NaN nas colunas
        # antigas; o requests recusa NaN em JSON e o update falha depois do clear().
        self.assertTrue(math.isnan(payload[3][3]))

    def test_planilha_vazia_recebe_cabecalho_fixo(self):
        _, aba = self.enviar([], [
            {"Escola": "Escola A", "IP do NVR": "10.0.0.1", "Dias Contínuos Válidos": 12,
             "Gravação mais antiga": "13/10/2026"},
        ])

        payload = aba.update.call_args.args[0]
        self.assertEqual(payload, [
            ["Escola", "IP do NVR", "Último dia de gravação",
             "Dias Contínuos de Gravação: 25/10/2026"],
            ["Escola A", "10.0.0.1", "13/10/2026", 12],
        ])

    def test_erro_da_api_do_google_e_registrado_sem_propagar(self):
        with patch.object(
            cloud_sync.Credentials, "from_service_account_file",
            side_effect=FileNotFoundError("credenciais.json"),
        ):
            cloud_sync.enviar_para_google_sheets([])


class FirmwareCaracterizacaoTests(unittest.TestCase):
    def test_funcoes_de_parse(self):
        self.assertEqual(
            nvr_firmware.parse_chave_valor("version=2.420\x00\nsn = ABC\nlixo\n"),
            {"version": "2.420", "sn": "ABC"},
        )
        self.assertEqual(
            nvr_firmware.separar_versao_build("2.420.0000.0.R,build:2016-01-12"),
            ("2.420.0000.0.R", "2016-01-12"),
        )
        self.assertEqual(nvr_firmware.separar_versao_build(""), ("", ""))
        self.assertEqual(nvr_firmware.montar_url_base("10.0.0.5"), "http://10.0.0.5")
        self.assertEqual(
            nvr_firmware.montar_url_base("10.0.0.5", "https", 8443), "https://10.0.0.5:8443"
        )
        self.assertEqual(
            nvr_firmware.montar_url_base("https://nvr.local:444", porta=80),
            "https://nvr.local:444",
        )
        with self.assertRaises(ValueError):
            nvr_firmware.montar_url_base("")

    def test_carregar_escolas_aceita_formatos_legado_e_com_estado(self):
        with tempfile.TemporaryDirectory() as tmp:
            arquivo = Path(tmp) / "escolas.json"
            arquivo.write_text(json.dumps({
                "A": "10.0.0.1",
                "B": {"ip": " 10.0.0.2 ", "status": "aprovada"},
                "C": {"host": "10.0.0.3"},
                "D": {"ip": ""},
            }), encoding="utf-8")

            escolas = nvr_firmware.carregar_escolas(arquivo)

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
        with patch.object(nvr_firmware.requests, "Session", side_effect=[digest, basic]):
            resultado = nvr_firmware.consultar_nvr("Escola A", "10.0.0.5", "u", "s")

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
        with patch.object(nvr_firmware.requests, "Session", return_value=sessao):
            resultado = nvr_firmware.consultar_nvr("Escola A", "10.0.0.5", "u", "s")

        self.assertEqual((resultado.status, resultado.erro), ("offline", "NVR inacessível na rede"))


if __name__ == "__main__":
    unittest.main()
