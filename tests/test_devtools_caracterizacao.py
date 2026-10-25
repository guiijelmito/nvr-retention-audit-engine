"""Caracterização do devtools: estado separado, confirmações e chamadas de produção."""

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from nvr_audit_engine.integracoes import sheets as cloud_sync
from nvr_audit_engine import devtools
from nvr_audit_engine.auditoria import pipeline as nvr_audit
from nvr_audit_engine.integracoes import lan7 as ticket_automation

ATRIBUTOS_AUDITORIA = (
    "ESCOLAS", "DADOS_ESCOLAS", "ARQUIVO_ESCOLAS", "capturar_print_nvr",
    "criar_ticket_7lan", "_proxima_auditoria_agendada", "enviar_para_google_sheets",
)


class DataFixa(datetime):
    @classmethod
    def now(cls, tz=None):
        base = cls(2026, 10, 25, 10, 0, 0)
        return base if tz is None else base.replace(tzinfo=tz)


class DevtoolsCaracterizacaoTests(unittest.TestCase):
    def setUp(self):
        originais = {nome: getattr(nvr_audit, nome) for nome in ATRIBUTOS_AUDITORIA}
        self.addCleanup(lambda: [setattr(nvr_audit, n, v) for n, v in originais.items()])
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.pasta = Path(tmp.name)
        self.estado_dev = self.pasta / "devtools_escolas.json"
        self.oficial = self.pasta / "escolas.json"
        self.evidencia = self.pasta / "print.png"
        self.evidencia.write_bytes(b"png")
        self.ultimo_dia = (datetime(2026, 10, 25) - timedelta(days=1)).strftime("%Y-%m-%d")

    def executar(self, respostas, *, captura=None, ticket=True):
        captura = Mock(return_value=str(self.evidencia)) if captura is None else captura
        criar_ticket = Mock(return_value=ticket)
        enviar = Mock()
        saida = StringIO()

        def consultar_dia(sessao, url_base, canal, data_str, escola):
            return data_str == self.ultimo_dia

        with (
            patch("builtins.input", side_effect=respostas),
            patch.object(devtools, "ESCOLAS", {"Escola X": "192.0.2.30"}),
            patch.object(devtools, "ARQUIVO_ESTADO_DEV", self.estado_dev),
            patch.object(devtools, "datetime", DataFixa),
            patch.object(devtools, "capturar_print_nvr", captura),
            patch.object(nvr_audit, "ARQUIVO_ESCOLAS", self.oficial),
            patch.object(nvr_audit, "datetime", DataFixa),
            patch.object(nvr_audit, "verificar_api", return_value=True),
            patch.object(nvr_audit, "consultar_dia", side_effect=consultar_dia),
            patch.object(nvr_audit.requests, "Session"),
            patch.object(ticket_automation, "criar_ticket_7lan", criar_ticket),
            patch.object(cloud_sync, "enviar_para_google_sheets", enviar),
            redirect_stdout(saida),
        ):
            codigo = devtools.main()
        return codigo, captura, criar_ticket, enviar, saida.getvalue()

    def test_auditoria_completa_usa_estado_de_dev_e_titulo_de_teste(self):
        codigo, captura, criar_ticket, enviar, saida = self.executar(
            ["2", "192.0.2.30", "1", "s", "s"]
        )

        self.assertEqual(codigo, 0)
        captura.assert_called_once_with(
            "192.0.2.30", "Escola X", "2026", 10,
            headless=False, slow_mo_ms=0, aguardar_em_erro=True,
        )
        criar_ticket.assert_called_once_with(
            "Escola X",
            headless=False,
            slow_mo_ms=0,
            confirmar=devtools._confirmar,
            titulo_customizado=(
                "[TESTE DEV 01] Controle de gravação - Escola X - 2026-10-25 10:00:00"
            ),
        )
        enviar.assert_called_once_with([{
            "Escola": "Escola X",
            "IP do NVR": "192.0.2.30",
            "Dias Contínuos Válidos": 1,
            "Gravação mais antiga": "24/10/2026",
        }])
        estado = json.loads(self.estado_dev.read_text("utf-8"))
        self.assertEqual(estado["Escola X"]["status"], "aprovada")
        self.assertFalse(self.oficial.exists())
        self.assertIn("| Escola X | 192.0.2.30 | Concluída (1 dias) | OK    |", saida)

    def test_sincronizacao_recusada_nao_envia_planilha(self):
        codigo, _, _, enviar, _ = self.executar(["2", "192.0.2.30", "1", "s", "n"])

        self.assertEqual(codigo, 0)
        enviar.assert_not_called()

    def test_unidade_ja_aprovada_em_dev_e_pulada_sem_confirmacao(self):
        self.estado_dev.write_text(json.dumps({
            "Escola X": {
                "ip": "192.0.2.30",
                "status": "aprovada",
                "concluida_em": "2026-10-24T10:00:00+00:00",
                "proxima_auditoria_em": "2099-01-01T00:00:00+00:00",
            }
        }), encoding="utf-8")

        codigo, captura, criar_ticket, enviar, saida = self.executar(
            ["2", "192.0.2.30", "1", "s", "n"]
        )

        self.assertEqual(codigo, 0)
        captura.assert_not_called()
        criar_ticket.assert_not_called()
        enviar.assert_not_called()
        self.assertIn("Pulado (estado aprovado)", saida)

    def test_unidade_aprovada_pode_ser_forcada(self):
        self.estado_dev.write_text(json.dumps({
            "Escola X": {
                "ip": "192.0.2.30",
                "status": "aprovada",
                "concluida_em": "2026-10-24T10:00:00+00:00",
                "proxima_auditoria_em": "2099-01-01T00:00:00+00:00",
            }
        }), encoding="utf-8")

        codigo, _, criar_ticket, _, _ = self.executar(
            ["2", "192.0.2.30", "1", "s", "s", "s"]
        )

        self.assertEqual(codigo, 0)
        criar_ticket.assert_called_once()

    def test_falha_no_print_nao_abre_ticket(self):
        codigo, _, criar_ticket, _, saida = self.executar(
            ["2", "192.0.2.30", "1", "s", "n"], captura=Mock(return_value=None)
        )

        self.assertEqual(codigo, 0)
        criar_ticket.assert_not_called()
        self.assertIn("| Falhou |", saida)

    def test_captura_direta_nao_audita_dias(self):
        codigo, captura, criar_ticket, enviar, saida = self.executar(
            ["2", "192.0.2.30", "2", "2025", "9", "s"]
        )

        self.assertEqual(codigo, 0)
        captura.assert_called_once_with(
            "192.0.2.30", "Escola X", 2025, 9,
            headless=False, slow_mo_ms=0, aguardar_em_erro=True,
        )
        criar_ticket.assert_not_called()
        enviar.assert_not_called()
        self.assertIn("Não executada (captura direta)", saida)

    def test_entrada_invalida_retorna_codigo_2(self):
        codigo, *_ = self.executar(["9"])

        self.assertEqual(codigo, 2)


if __name__ == "__main__":
    unittest.main()
