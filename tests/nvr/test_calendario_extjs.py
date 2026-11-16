"""Seletores ExtJS (firmware 4.002) contra o HTML real do CAIC NVR1, num Chromium de verdade."""

import unittest

from nvr_audit_engine.nvr.web.calendario import (
    candidatos_botao_calendario_extjs,
    selecionar_calendario_extjs,
)
from nvr_audit_engine.nvr.web.localizadores import primeiro_visivel

MESES = ["Jan", "Jul", "Fev", "Ago", "Mar", "Set", "Abr", "Out", "Mai", "Nov", "Jun", "Dez"]

# Botão, meses e OK copiados do NVR 172.16.4.2 (ids diferentes dos de outro NVR).
# A coluna de anos não veio no HTML; usa a marcação padrão do ExtJS.
HTML = """
<script>window.Map = function () {{}};  // como o ExtJS do 4.002 faz</script>
<a class="x-btn x-btn-split"><span id="splitbutton-1215-btnInnerEl"
  class="x-btn-inner x-btn-inner-center">Nov 2026</span></a>
<div class="x-monthpicker">
  <div id="monthpicker-1220-monthEl" class="x-monthpicker-months">{meses}</div>
  <div id="monthpicker-1220-yearEl" class="x-monthpicker-years">
    <div class="x-monthpicker-yearnav">
      <a class="x-monthpicker-yearnav-prev" href="#"></a>
      <a class="x-monthpicker-yearnav-next" href="#"></a>
    </div>
    {anos}
  </div>
  <div class="x-monthpicker-buttons">
    <a class="x-btn" href="#"><span role="img" id="button-1221-btnIconEl" class="x-btn-icon-el">OK</span></a>
    <a class="x-btn" href="#"><span class="x-btn-inner">Cancelar</span></a>
  </div>
</div>
<script>
  // Guarda os cliques no DOM: com window.Map trocado, page.evaluate não devolve valores.
  document.addEventListener("click", e => {{
    e.preventDefault();
    const b = document.body.dataset;
    const texto = e.target.closest("a").textContent.trim();
    b.cliques = (b.cliques ? b.cliques + "|" : "") + texto;
    if (texto === "OK") setTimeout(() => {{
      document.querySelector(".x-monthpicker").style.display = "none";
    }}, 300);
  }});
</script>
""".format(
    meses="".join(
        f'<div class="x-monthpicker-item x-monthpicker-month">'
        f'<a class="x-monthpicker-item-inner" href="#">{m}</a></div>'
        for m in MESES
    ),
    anos="".join(
        f'<div class="x-monthpicker-item x-monthpicker-year">'
        f'<a class="x-monthpicker-item-inner" href="#">{a}</a></div>'
        for a in range(2021, 2031)
    ),
)


class CalendarioExtjsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright

            cls._pw = sync_playwright().start()
            cls._browser = cls._pw.chromium.launch()
        except Exception as exc:
            if getattr(cls, "_pw", None):
                cls._pw.stop()
            raise unittest.SkipTest(f"Chromium do Playwright indisponível: {exc}") from exc

    @classmethod
    def tearDownClass(cls):
        cls._browser.close()
        cls._pw.stop()

    def setUp(self):
        self.page = self._browser.new_page()
        self.page.set_content(HTML)

    def tearDown(self):
        self.page.close()

    def test_acha_botao_mes_ano_sem_depender_do_id(self):
        botao = primeiro_visivel(self.page, "botão", candidatos_botao_calendario_extjs())
        self.assertEqual(botao.text_content().strip(), "Nov 2026")

    def test_seleciona_setembro_pelo_texto_e_confirma_em_ok(self):
        self.assertTrue(selecionar_calendario_extjs(self.page, 2026, 9))
        # A ordem no DOM é em colunas (Jan, Jul, Fev...): o mês tem de sair pelo texto.
        self.assertEqual(self.page.locator("body").get_attribute("data-cliques").split("|"), ["2026", "Set", "OK"])

    def test_espera_a_coluna_de_meses_aparecer(self):
        # No Alex Honório (16/11) a coluna de meses ficou visível depois da de anos.
        self.page.evaluate("""() => {
            const meses = document.querySelector('.x-monthpicker-months');
            meses.style.display = 'none';
            setTimeout(() => { meses.style.display = ''; }, 800);
        }""")

        self.assertTrue(selecionar_calendario_extjs(self.page, 2026, 10))
        self.assertEqual(self.page.locator("body").get_attribute("data-cliques").split("|"), ["2026", "Out", "OK"])


if __name__ == "__main__":
    unittest.main()
