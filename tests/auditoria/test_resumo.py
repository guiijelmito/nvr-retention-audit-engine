"""Resumo por execução (resumo.csv, resumo.json, resumo.md)."""

import csv
import json
import tempfile
import unittest
from pathlib import Path

from nvr_audit_engine.auditoria import resumo


def linha(escola, resultado, **extra):
    base = {coluna: "" for coluna in resumo.COLUNAS}
    base.update(escola=escola, resultado=resultado, **extra)
    return base


class ResumoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)

    def test_totais_e_mudancas_desde_a_execucao_anterior(self):
        anterior = {"escolas": [
            {"escola": "Padre Donato", "resultado": "sem_rede"},
            {"escola": "CEAPI", "resultado": "aprovada"},
        ]}
        linhas = [
            linha("Padre Donato", "aprovada"),
            linha("CEAPI", "aprovada"),
            linha("Isaura", "sem_rede"),
            linha("Alex Honório", "falha_print"),
            linha("Sem mês", "sem_data_para_print"),
        ]

        r = resumo.montar_resumo(linhas, anterior, {"Isaura": 2})

        self.assertEqual(r["totais"], {
            "Aprovadas": 2, "Sem rede": 1, "Verificar no local": 0, "Incompletas": 0,
            "Falha de print": 1, "Falha de OS": 0, "Outros": 1,
        })
        self.assertEqual(
            r["mudancas"], [{"escola": "Padre Donato", "antes": "sem_rede", "agora": "aprovada"}]
        )
        self.assertIsNone(r["observacoes"])

    def test_sem_execucao_anterior_nao_inventa_mudancas(self):
        r = resumo.montar_resumo([linha("A", "aprovada")], None, {})

        self.assertIsNone(r["mudancas"])
        self.assertIn("Sem execução anterior", resumo._markdown(r))

    def test_grava_csv_json_e_md(self):
        pasta = self.raiz / "2026-11-06_090000"
        pasta.mkdir()
        r = resumo.montar_resumo(
            [linha("Escola | A", "falha_os", motivo_falha="OS criada mas não concluída")],
            None,
            {"Isaura": 3},
        )

        resumo.gravar_resumo(pasta, r)

        with open(pasta / "resumo.csv", encoding="utf-8-sig", newline="") as arquivo:
            linhas_csv = list(csv.DictReader(arquivo, delimiter=";"))
        self.assertEqual(linhas_csv[0]["escola"], "Escola | A")
        self.assertEqual(linhas_csv[0]["resultado"], "falha_os")
        gravado = json.loads((pasta / "resumo.json").read_text(encoding="utf-8"))
        self.assertEqual(gravado["execucao"], "2026-11-06_090000")
        md = (pasta / "resumo.md").read_text(encoding="utf-8")
        self.assertIn("- Falha de OS: 1", md)
        self.assertIn("- Isaura: 3 execuções seguidas sem rede", md)
        self.assertIn("| Escola / A | ", md)  # a barra não quebra a tabela

    def test_md_agrupa_resultados_por_firmware(self):
        r = resumo.montar_resumo([
            linha("Alex Honório", "falha_print", firmware="4.002.0000000.3.R"),
            linha("CAIC NVR2", "falha_print", firmware="4.002.0000000.3.R"),
            linha("Geralda", "aprovada", firmware="4.003.0000000.1.R"),
            linha("Isaura", "sem_rede"),
        ], None, {})

        md = resumo._markdown(r)

        self.assertIn("- 4.002.0000000.3.R: falha_print 2", md)
        self.assertIn("- 4.003.0000000.1.R: aprovada 1", md)
        self.assertIn("- desconhecido: sem_rede 1", md)

    def test_sem_relatorio_de_firmware_nao_mostra_agrupamento(self):
        md = resumo._markdown(resumo.montar_resumo([linha("A", "aprovada")], None, {}))

        self.assertNotIn("por firmware", md)

    def test_resumo_anterior_e_o_mais_recente_antes_da_execucao_atual(self):
        for nome, resultado in [("2026-10-19_112900", "a"), ("2026-10-30_092200", "b"),
                                ("2026-11-07_080000", "futuro")]:
            (self.raiz / nome).mkdir()
            (self.raiz / nome / "resumo.json").write_text(
                json.dumps({"escolas": [], "marca": resultado}), encoding="utf-8"
            )
        atual = self.raiz / "2026-11-06_090000"
        atual.mkdir()

        self.assertEqual(resumo.resumo_anterior(self.raiz, atual)["marca"], "b")

    def test_firmware_vem_do_relatorio_mais_recente(self):
        pasta = self.raiz / "relatorios_firmware"
        pasta.mkdir()
        cabecalho = "escola;ip;status;versao_firmware\n"
        (pasta / "firmware_nvrs_2026-10-01_1000.csv").write_text(
            cabecalho + "CAIC;172.16.4.2;online;4.001\n", encoding="utf-8-sig"
        )
        (pasta / "firmware_nvrs_2026-11-06_1000.csv").write_text(
            cabecalho + "CAIC;172.16.4.2;online;4.002.0000000.3.R\n"
            "Isaura;172.16.8.3;offline;\n",
            encoding="utf-8-sig",
        )

        self.assertEqual(
            resumo.firmware_por_ip(pasta), {"172.16.4.2": "4.002.0000000.3.R"}
        )
        self.assertEqual(resumo.firmware_por_ip(self.raiz / "nao_existe"), {})


if __name__ == "__main__":
    unittest.main()
