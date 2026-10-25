"""Matriz quinzenal enviada ao Google Sheets."""

import math
import unittest
from unittest.mock import Mock, patch

from nvr_audit_engine.integracoes import sheets
from tests.apoio import DataFixa


class PlanilhaTests(unittest.TestCase):
    def enviar(self, valores_atuais, resultados):
        aba = Mock()
        aba.get_all_values.return_value = valores_atuais
        cliente = Mock()
        cliente.open.return_value.worksheet.return_value = aba
        with (
            patch.object(sheets, "datetime", DataFixa),
            patch.object(sheets.Credentials, "from_service_account_file"),
            patch.object(sheets.gspread, "authorize", return_value=cliente),
        ):
            sheets.enviar_para_google_sheets(resultados)
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
            sheets.Credentials, "from_service_account_file",
            side_effect=FileNotFoundError("credenciais.json"),
        ):
            sheets.enviar_para_google_sheets([])


if __name__ == "__main__":
    unittest.main()
