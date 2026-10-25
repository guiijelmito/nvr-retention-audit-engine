"""Seleção de ano e mês no calendário de gravações (ExtJS, Ant Design ou <select>)."""

import re

from nvr_audit_engine.log import logger
from nvr_audit_engine.nvr.web.localizadores import (
    ElementoNVRNaoEncontrado,
    css,
    primeiro_visivel,
)


def candidatos_seletor_calendario(tipo: str, indice: int):
    if tipo == "ano":
        codigo_antigo = "#rc_select_2"
        termos = ("year", "ano")
        regex = r"ano|year"
    else:
        codigo_antigo = "#rc_select_3"
        termos = ("month", "mês", "mes")
        regex = r"mês|mes|month"

    acessivel = re.compile(regex, re.IGNORECASE)
    candidatos = [
        # Variante ExtJS observada no HTML enviado; os IDs numéricos podem variar.
        css(
            "#monthpicker-1397-yearEl"
            if tipo == "ano"
            else "#monthpicker-1397-monthEl"
        ),
        css(".x-monthpicker-years" if tipo == "ano" else ".x-monthpicker-months"),
        (f"combobox acessível de {tipo}",
         lambda page: page.get_by_role("combobox", name=acessivel)),
        (f"botão acessível de {tipo}",
         lambda page: page.get_by_role("button", name=acessivel)),
        (f"label de {tipo}", lambda page: page.get_by_label(acessivel)),
        css(codigo_antigo),
        (f"combobox número {indice + 1}",
         lambda page: page.get_by_role("combobox").nth(indice)),
        (f"seletor Ant Design número {indice + 1}",
         lambda page: page.locator(".ant-select input").nth(indice)),
        (f"select HTML número {indice + 1}",
         lambda page: page.locator("select").nth(indice)),
    ]
    for termo in termos:
        candidatos.insert(2, css(f'input[aria-label*="{termo}" i]'))
        candidatos.insert(3, css(f'input[placeholder*="{termo}" i]'))
        candidatos.insert(4, css(f'select[name*="{termo}" i]'))
        candidatos.insert(5, css(f'[aria-label*="{termo}" i]'))
        candidatos.insert(6, css(f'[title*="{termo}" i]'))
        candidatos.insert(7, css(f'button:has-text("{termo}")'))
    return candidatos


def selecionar_calendario_extjs(page, ano_alvo: int, mes_num: int) -> bool:
    """Seleciona ano/mês no monthpicker ExtJS e confirma em OK."""
    meses = primeiro_visivel(
        page,
        "box de mês ExtJS",
        candidatos_seletor_calendario("mês", 1),
        obrigatorio=False,
    )
    anos = primeiro_visivel(
        page,
        "box de ano ExtJS",
        candidatos_seletor_calendario("ano", 0),
        obrigatorio=False,
    )
    if meses is None or anos is None:
        return False

    opcoes_ano = anos.locator(".x-monthpicker-year a")
    opcoes_mes = meses.locator(".x-monthpicker-month a")
    if not opcoes_ano.count() or not opcoes_mes.count():
        return False
    alvo_ano = str(ano_alvo)

    # O widget mostra uma janela de anos; navega em blocos até o ano solicitado.
    for _ in range(40):
        anos_visiveis = [texto.strip() for texto in opcoes_ano.all_text_contents()]
        if alvo_ano in anos_visiveis:
            break
        anos_validos = [int(texto) for texto in anos_visiveis if texto.isdigit()]
        if not anos_validos:
            raise ElementoNVRNaoEncontrado(
                "O monthpicker ExtJS não apresentou opções de ano."
            )
        seletor_navegacao = (
            ".x-monthpicker-yearnav-prev"
            if ano_alvo < min(anos_validos)
            else ".x-monthpicker-yearnav-next"
        )
        navegacao = page.locator(seletor_navegacao)
        if not navegacao.count() or not navegacao.first.is_visible():
            raise ElementoNVRNaoEncontrado(
                f"Não consegui navegar até o ano {ano_alvo} no monthpicker ExtJS."
            )
        navegacao.first.click()
    else:
        raise ElementoNVRNaoEncontrado(
            f"O ano {ano_alvo} não apareceu após navegar no monthpicker ExtJS."
        )

    alvo_ano_locator = opcoes_ano.filter(
        has_text=re.compile(rf"^\s*{re.escape(alvo_ano)}\s*$")
    )
    alvo_ano_locator.first.click()

    alternativas_mes = meses_possiveis(mes_num)
    textos_mes = [texto.strip().casefold() for texto in opcoes_mes.all_text_contents()]
    for alternativa in alternativas_mes:
        if alternativa.casefold() in textos_mes:
            opcoes_mes.filter(
                has_text=re.compile(rf"^\s*{re.escape(alternativa)}\s*$", re.I)
            ).first.click()
            break
    else:
        raise ElementoNVRNaoEncontrado(
            f"Não encontrei o mês {mes_num} no monthpicker ExtJS."
        )

    botao_ok = primeiro_visivel(
        page,
        "confirmação OK do calendário ExtJS",
        [
            css('button:has(#button-1398-btnIconEl)'),
            css("#button-1398-btnIconEl"),
            ("botão OK acessível", lambda pagina: pagina.get_by_role(
                "button", name=re.compile(r"^\s*ok\s*$", re.I)
            )),
        ],
        obrigatorio=False,
    )
    if botao_ok is None:
        raise ElementoNVRNaoEncontrado(
            "Selecionei ano e mês no monthpicker ExtJS, mas não encontrei o botão OK."
        )
    botao_ok.click()
    return True


def selecionar_opcao(page, controle, valor: str, alternativas: list[str], descricao: str):
    tag = controle.evaluate("element => element.tagName.toLowerCase()")
    if tag == "select":
        opcoes = controle.locator("option").all_text_contents()
        normalizadas = {texto.strip().casefold(): texto.strip() for texto in opcoes}
        for alternativa in alternativas:
            encontrada = normalizadas.get(alternativa.casefold())
            if encontrada is not None:
                controle.select_option(label=encontrada)
                return
        raise ElementoNVRNaoEncontrado(
            f"A lista HTML de {descricao} não contém {valor}; opções: {opcoes}"
        )

    alvo_clique = controle
    classes = controle.get_attribute("class") or ""
    if tag == "input" and "ant-select-selection-search-input" in classes:
        # O input do Ant Design fica sob o item selecionado (ex.: ano 2026),
        # que intercepta o clique. Clicar no container abre o dropdown sem
        # forçar a interação no input encoberto.
        seletor_ant = controle.locator(
            "xpath=ancestor::div[contains(@class, 'ant-select-selector')][1]"
        )
        if seletor_ant.count():
            alvo_clique = seletor_ant.first
        else:
            logger.warning(
                "[PLAYWRIGHT] Container ant-select-selector não encontrado para %s; "
                "usando clique forçado no input conhecido.",
                descricao,
            )
            controle.click(force=True)
    if alvo_clique is not controle:
        alvo_clique.click()
    elif not (tag == "input" and "ant-select-selection-search-input" in classes):
        controle.click()
    for alternativa in alternativas:
        nome_exato = re.compile(rf"^\s*{re.escape(alternativa)}\s*$", re.IGNORECASE)
        candidatos = [
            (f"opção acessível {alternativa}",
             lambda pagina, padrao=nome_exato: pagina.get_by_role("option", name=padrao)),
            (f"opção Ant Design {alternativa}",
             lambda pagina, texto=alternativa: pagina.locator(
                 f'.ant-select-item-option-content:text-is("{texto}")'
             )),
            (f"texto da opção {alternativa}",
             lambda pagina, padrao=nome_exato: pagina.get_by_text(padrao)),
        ]
        try:
            opcao = primeiro_visivel(
                page,
                f"opção {descricao}={alternativa}",
                candidatos,
                obrigatorio=False,
            )
        except Exception:
            opcao = None
        if opcao is not None:
            opcao.click()
            return

    raise ElementoNVRNaoEncontrado(
        f"Abri o seletor de {descricao}, mas não encontrei {valor}; "
        f"opções tentadas: {alternativas}"
    )


def meses_possiveis(mes_num: int) -> list[str]:
    meses = {
        1: ["Jan", "January", "Janeiro", "1", "01"],
        2: ["Feb", "February", "Fev", "Fevereiro", "2", "02"],
        3: ["Mar", "March", "Março", "Marco", "3", "03"],
        4: ["Apr", "April", "Abr", "Abril", "4", "04"],
        5: ["May", "Mai", "Maio", "5", "05"],
        6: ["Jun", "June", "Junho", "6", "06"],
        7: ["Jul", "July", "Julho", "7", "07"],
        8: ["Aug", "August", "Ago", "Agosto", "8", "08"],
        9: ["Sep", "September", "Set", "Setembro", "9", "09"],
        10: ["Oct", "October", "Out", "Outubro", "10"],
        11: ["Nov", "November", "Novembro", "11"],
        12: ["Dec", "December", "Dez", "Dezembro", "12"],
    }
    return meses[mes_num]
