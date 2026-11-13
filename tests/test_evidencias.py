"""Nome do print de evidência compartilhado entre captura e ticket."""

import os
import unittest
from datetime import datetime

from nvr_audit_engine.evidencias import caminho_evidencia, nome_seguro


class EvidenciasTests(unittest.TestCase):
    def test_nome_seguro_remove_espacos_pontos_e_ordinais(self):
        self.assertEqual(nome_seguro("E.M. Profª João 1º"), "EM_Profa_João_1o")

    def test_caminho_usa_data_dd_mm_aaaa(self):
        self.assertEqual(
            caminho_evidencia("evidencias", "Escola A", datetime(2026, 10, 5, 23, 59)),
            os.path.join("evidencias", "Escola_A_05-10-2026.png"),
        )


if __name__ == "__main__":
    unittest.main()
