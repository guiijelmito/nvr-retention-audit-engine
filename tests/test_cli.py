"""Ponto de entrada único (python main.py [comando])."""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from nvr_audit_engine import cli, devtools
from nvr_audit_engine.auditoria import pipeline
from nvr_audit_engine.nvr import firmware

RAIZ = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def setUp(self):
        preparar = patch.object(cli, "_preparar_execucao")
        self.preparar = preparar.start()
        self.addCleanup(preparar.stop)

    def test_sem_comando_executa_a_auditoria(self):
        with patch.object(pipeline, "auditar_retencao_nvr_com_cloud") as auditar:
            self.assertEqual(cli.main([]), 0)

        self.preparar.assert_called_once()
        auditar.assert_called_once_with()

    def test_devtools_devolve_o_codigo_da_ferramenta(self):
        with patch.object(devtools, "main", return_value=130) as principal:
            self.assertEqual(cli.main(["devtools"]), 130)

        principal.assert_called_once_with()
        self.preparar.assert_called_once()

    def test_firmware_repassa_os_argumentos_sem_preparar_pastas(self):
        with patch.object(firmware, "main", return_value=0) as principal:
            self.assertEqual(cli.main(["firmware", "--ip", "10.0.0.5", "--json", "x.json"]), 0)

        principal.assert_called_once_with(["--ip", "10.0.0.5", "--json", "x.json"])
        self.preparar.assert_not_called()

    def test_comando_desconhecido_ou_argumento_sobrando_e_recusado(self):
        for argv in (["apagar"], ["auditar", "--ip", "1.2.3.4"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit) as erro:
                with patch("sys.stderr"):
                    cli.main(argv)
            self.assertEqual(erro.exception.code, 2)


class ImportSemEfeitoColateralTests(unittest.TestCase):
    def test_importar_os_modulos_nao_imprime_nem_configura_log(self):
        codigo = (
            "import logging, nvr_audit_engine.cli, nvr_audit_engine.devtools, "
            "nvr_audit_engine.auditoria.pipeline, nvr_audit_engine.nvr.firmware; "
            "print(len(logging.getLogger('VerthAudit').handlers))"
        )
        resultado = subprocess.run(
            [sys.executable, "-c", codigo], cwd=RAIZ, capture_output=True, text=True, check=True
        )

        self.assertEqual(resultado.stdout, "0\n")
        self.assertEqual(resultado.stderr, "")

    def test_main_py_responde_ajuda(self):
        resultado = subprocess.run(
            [sys.executable, "main.py", "--help"], cwd=RAIZ, capture_output=True, text=True
        )

        self.assertEqual(resultado.returncode, 0)
        for comando in ("auditar", "devtools", "firmware"):
            self.assertIn(comando, resultado.stdout)


if __name__ == "__main__":
    unittest.main()
