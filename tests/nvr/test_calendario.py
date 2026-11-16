import unittest
from unittest.mock import MagicMock

from nvr_audit_engine.nvr.web.calendario import selecionar_calendario_antd
from nvr_audit_engine.nvr.web.localizadores import (
    ElementoNVRLocalizado,
    ElementoNVRNaoEncontrado,
)


class PaginaFalsa:
    """Página com os seletores informados; registra os cliques."""

    def __init__(self, presentes, opcoes_visiveis=()):
        self.presentes = set(presentes)
        self.opcoes_visiveis = set(opcoes_visiveis)
        self.cliques = []

    def locator(self, seletor):
        item = MagicMock()
        item.count.return_value = 1 if seletor in self.presentes else 0
        item.is_visible.return_value = any(f'"{t}"' in seletor for t in self.opcoes_visiveis)
        item.click.side_effect = lambda **_: self.cliques.append(seletor)
        return item

    def wait_for_timeout(self, _ms):
        pass


class CalendarioAntdTests(unittest.TestCase):
    def test_sem_seletores_ant_design_nao_toca_na_tela(self):
        pagina = PaginaFalsa(presentes=[])

        self.assertFalse(selecionar_calendario_antd(pagina, "2026", 6))
        self.assertEqual(pagina.cliques, [])

    def test_seleciona_ano_e_mes_em_portugues_ou_ingles(self):
        pagina = PaginaFalsa(["#rc_select_2", "#rc_select_3"], opcoes_visiveis=["Sep"])

        self.assertTrue(selecionar_calendario_antd(pagina, "2026", 9))
        self.assertEqual(
            pagina.cliques,
            [
                "#rc_select_2",
                '.ant-select-item-option-content:text-is("2026")',
                "#rc_select_3",
                '.ant-select-item-option-content:text-is("Sep")',
            ],
        )

    def test_mes_ausente_levanta_erro_sem_clicar_de_novo(self):
        pagina = PaginaFalsa(["#rc_select_2", "#rc_select_3"])

        with self.assertRaises(ElementoNVRNaoEncontrado):
            selecionar_calendario_antd(pagina, "2026", 9)
        self.assertNotIn('.ant-select-item-option-content:text-is("Set")', pagina.cliques)


class ElementoLocalizadoTests(unittest.TestCase):
    def test_metodo_locator_do_playwright_continua_acessivel(self):
        alvo = MagicMock()
        elemento = ElementoNVRLocalizado(alvo, contexto=None)

        elemento.locator(".x-monthpicker-year a")

        alvo.locator.assert_called_once_with(".x-monthpicker-year a")
