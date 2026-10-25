"""Regra de dias contínuos isolada da comunicação com o NVR."""

import unittest
from unittest.mock import patch

from nvr_audit_engine.auditoria import retencao
from nvr_audit_engine.auditoria.retencao import ResultadoRetencao, contar_dias_continuos
from tests.apoio import DataFixa


def respostas(*dias):
    """Responde na ordem ontem, anteontem, ...; depois disso, dia vazio."""
    fila = list(dias)
    consultadas = []

    def consultar(data_str):
        consultadas.append(data_str)
        return fila.pop(0) if fila else False

    return consultar, consultadas


class ContagemTests(unittest.TestCase):
    def contar(self, *dias, **kwargs):
        consultar, consultadas = respostas(*dias)
        with patch.object(retencao, "datetime", DataFixa):
            return contar_dias_continuos(consultar, **kwargs), consultadas

    def test_conta_de_ontem_para_tras(self):
        resultado, consultadas = self.contar(True, True)

        self.assertEqual(consultadas[:2], ["2026-10-24", "2026-10-23"])
        self.assertEqual(resultado, ResultadoRetencao(2, "23/10/2026"))
        self.assertTrue(resultado.completa)

    def test_um_ou_dois_vazios_sao_tolerados(self):
        resultado, _ = self.contar(True, False, False, True, False, False, False)

        self.assertEqual(resultado.dias_continuos, 2)
        self.assertEqual(resultado.gravacao_mais_antiga, "21/10/2026")

    def test_tres_vazios_seguidos_encerram(self):
        resultado, consultadas = self.contar(False, False, False, True)

        self.assertEqual(len(consultadas), 3)
        self.assertEqual(resultado.dias_continuos, 0)

    def test_inconclusivo_interrompe_sem_virar_vazio(self):
        resultado, consultadas = self.contar(True, None, True)

        self.assertEqual(len(consultadas), 2)
        self.assertFalse(resultado.completa)
        self.assertEqual(resultado.data_inconclusiva, "2026-10-23")
        self.assertEqual(resultado.gravacao_mais_antiga, "N/A")

    def test_limites_configuraveis(self):
        resultado, consultadas = self.contar(True, True, True, limite_dias=3)

        self.assertEqual(len(consultadas), 3)
        self.assertEqual(resultado, ResultadoRetencao(3, "N/A"))

        resultado, _ = self.contar(True, False, True, limite_buraco=1)
        self.assertEqual(resultado, ResultadoRetencao(1, "24/10/2026"))


if __name__ == "__main__":
    unittest.main()
