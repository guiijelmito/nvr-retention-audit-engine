from datetime import datetime
import os
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from nvr_audit_engine.config import LOGS_DIR, USUARIO, SENHA, logger, PASTA_EVIDENCIAS as pasta_destino


class ElementoNVRNaoEncontrado(RuntimeError):
    """Nenhum dos seletores conhecidos localizou o controle esperado."""


class ElementoNVRLocalizado:
    """Encapsula o locator e o frame em que ele foi encontrado."""

    def __init__(self, locator, contexto):
        self.locator = locator
        self.contexto = contexto

    def __getattr__(self, nome):
        return getattr(self.locator, nome)


def _css(seletor: str):
    return seletor, lambda page: page.locator(seletor)


def _role(descricao: str, papel: str, nome: re.Pattern):
    return descricao, lambda page: page.get_by_role(papel, name=nome)


def _primeiro_visivel(page, descricao: str, candidatos, *, obrigatorio=True):
    tentados = []
    if hasattr(page, "main_frame") and hasattr(page, "frames"):
        quadro_principal = page.main_frame
        quadros = [
            quadro_principal,
            *(frame for frame in page.frames if frame != quadro_principal),
        ]
    else:
        quadros = [page]
    for nome, construir in candidatos:
        tentados.append(nome)
        for quadro in quadros:
            try:
                locator = construir(quadro)
                total = locator.count()
                for indice in range(total):
                    item = locator.nth(indice)
                    if item.is_visible():
                        logger.info(
                            "[PLAYWRIGHT] Controle '%s' localizado pela variante: %s "
                            "(frame: %s)",
                            descricao,
                            nome,
                            quadro.url or "principal",
                        )
                        return ElementoNVRLocalizado(item, quadro)
            except Exception as exc:
                logger.debug(
                    "[PLAYWRIGHT] Variante '%s' indisponível para '%s' no frame %s (%s).",
                    nome,
                    descricao,
                    quadro.url or "principal",
                    type(exc).__name__,
                )

    if obrigatorio:
        raise ElementoNVRNaoEncontrado(
            f"Não encontrei '{descricao}'. Variantes tentadas: {', '.join(tentados)}"
        )
    return None


def _candidatos_usuario():
    nome = re.compile(r"usuário|usuario|user|login|e-mail|email", re.IGNORECASE)
    return [
        # Variante identificada manualmente em NVRs usados pelas escolas.
        _css("#loginUsername-inputEl"),
        _role("textbox nome de usuário", "textbox", nome),
        _css('input[autocomplete="username"]'),
        _css('input[aria-label*="user" i]'),
        _css('input[placeholder*="user" i]'),
        _css('input[name*="user" i]'),
        _css('input[id*="user" i]'),
        _css('input[type="email"]'),
        _css("input.ant-input"),
        _css('input[type="text"]'),
        _css("input:not([type='password'])"),
        _css('[role="textbox"]'),
        _css('[contenteditable="true"]'),
    ]


def _candidatos_senha():
    nome = re.compile(r"senha|password", re.IGNORECASE)
    return [
        # Variante identificada manualmente em NVRs usados pelas escolas.
        _css("#loginPassword-inputEl"),
        _role("textbox nome de senha", "textbox", nome),
        _css('input[type="password"]'),
        _css('input[autocomplete*="password" i]'),
        _css('input[name*="pass" i]'),
        _css('input[id*="pass" i]'),
    ]


def _candidatos_pesquisa():
    nome = re.compile(r"pesquisar|search|playback|gravações|gravacoes", re.IGNORECASE)
    return [
        # O ícone e a chave de tradução juntos identificam especificamente o atalho.
        _css(
            '.ux_desktop_shortcut_box:has(img[src*="desktop-playback.png"]):'
            'has(.ux_desktop_app_name > span[t="com.SearchTitle"])'
        ),
        # Fallback para versões do firmware que não renderizam o ícone esperado.
        _css(
            '.ux_desktop_shortcut_box:has('
            '.ux_desktop_app_name span[t="com.SearchTitle"])'
        ),
        _css('.ux_desktop_shortcut_box:has-text("PESQUISAR")'),
        _role("botão Pesquisar/Search", "button", nome),
        _role("link Pesquisar/Search", "link", nome),
        _role("item de menu Pesquisa/Playback", "menuitem", nome),
        _css(
            '.ViewItem-CardItem-Title:has-text("PESQUISAR"), '
            '.ViewItem-CardItem-Title:has-text("SEARCH")'
        ),
        ("texto Pesquisar/Search/Playback", lambda page: page.get_by_text(nome)),
        _css('[aria-label*="search" i]'),
        _css('[title*="search" i]'),
    ]


def _aguardar_entrada_pesquisa(page, timeout_ms: int = 30000) -> None:
    """Aguarda o atalho aparecer na página principal ou em um frame filho."""
    detector = """() => {
        const raizes = [document];
        for (let indice = 0; indice < raizes.length; indice++) {
            const elementos = raizes[indice].querySelectorAll('*');
            for (const elemento of elementos) {
                if (elemento.shadowRoot) raizes.push(elemento.shadowRoot);
            }
        }
        const consultar = seletor => raizes.flatMap(raiz =>
            [...raiz.querySelectorAll(seletor)]
        );
        const visivel = elemento => {
            const estilo = getComputedStyle(elemento);
            return elemento.getClientRects().length > 0 &&
                estilo.display !== 'none' && estilo.visibility !== 'hidden';
        };
        const atalhos = consultar('.ux_desktop_shortcut_box');
        if (atalhos.some(elemento => visivel(elemento) && (
            elemento.querySelector('span[t="com.SearchTitle"]') ||
            elemento.querySelector('img[src*="desktop-playback.png"]') ||
            /pesquisar/i.test(elemento.innerText || '')
        ))) return true;
        const titulos = consultar('.ViewItem-CardItem-Title');
        if (titulos.some(elemento => visivel(elemento) &&
            /pesquisar|search/i.test(elemento.innerText || ''))) return true;
        const marcados = consultar('[aria-label], [title]');
        if (marcados.some(elemento => visivel(elemento) &&
            /pesquisar|search|playback/i.test(
                `${elemento.getAttribute('aria-label') || ''} ${elemento.title || ''}`
            ))) return true;
        const interativos = consultar(
            'button, a, [role="button"], [role="link"], [role="menuitem"]'
        );
        return interativos.some(elemento => visivel(elemento) &&
            /pesquisar|search|playback|gravações|gravacoes/i.test(elemento.innerText || ''));
    }"""

    prazo = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < prazo:
        for quadro in page.frames:
            try:
                if quadro.evaluate(detector):
                    logger.info(
                        "[PLAYWRIGHT] Atalho Pesquisa/Playback detectado no frame: %s",
                        quadro.url or "principal",
                    )
                    return
            except Exception as exc:
                logger.debug(
                    "[PLAYWRIGHT] Ainda não consegui inspecionar o frame %s (%s).",
                    quadro.url or "principal",
                    type(exc).__name__,
                )
        time.sleep(0.25)

    raise ElementoNVRNaoEncontrado(
        "A interface não exibiu o atalho Pesquisa/Playback em "
        f"{timeout_ms // 1000} segundos em nenhum frame após a transição de login. "
        "Verifique se o NVR terminou de carregar ou se a sessão foi aceita."
    )


def _candidatos_seletor_calendario(tipo: str, indice: int):
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
        _css(
            "#monthpicker-1397-yearEl"
            if tipo == "ano"
            else "#monthpicker-1397-monthEl"
        ),
        _css(".x-monthpicker-years" if tipo == "ano" else ".x-monthpicker-months"),
        (f"combobox acessível de {tipo}",
         lambda page: page.get_by_role("combobox", name=acessivel)),
        (f"botão acessível de {tipo}",
         lambda page: page.get_by_role("button", name=acessivel)),
        (f"label de {tipo}", lambda page: page.get_by_label(acessivel)),
        _css(codigo_antigo),
        (f"combobox número {indice + 1}",
         lambda page: page.get_by_role("combobox").nth(indice)),
        (f"seletor Ant Design número {indice + 1}",
         lambda page: page.locator(".ant-select input").nth(indice)),
        (f"select HTML número {indice + 1}",
         lambda page: page.locator("select").nth(indice)),
    ]
    for termo in termos:
        candidatos.insert(2, _css(f'input[aria-label*="{termo}" i]'))
        candidatos.insert(3, _css(f'input[placeholder*="{termo}" i]'))
        candidatos.insert(4, _css(f'select[name*="{termo}" i]'))
        candidatos.insert(5, _css(f'[aria-label*="{termo}" i]'))
        candidatos.insert(6, _css(f'[title*="{termo}" i]'))
        candidatos.insert(7, _css(f'button:has-text("{termo}")'))
    return candidatos


def _selecionar_calendario_extjs(page, ano_alvo: int, mes_num: int) -> bool:
    """Seleciona ano/mês no monthpicker ExtJS e confirma em OK."""
    meses = _primeiro_visivel(
        page,
        "box de mês ExtJS",
        _candidatos_seletor_calendario("mês", 1),
        obrigatorio=False,
    )
    anos = _primeiro_visivel(
        page,
        "box de ano ExtJS",
        _candidatos_seletor_calendario("ano", 0),
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

    alternativas_mes = _meses_possiveis(mes_num)
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

    botao_ok = _primeiro_visivel(
        page,
        "confirmação OK do calendário ExtJS",
        [
            _css('button:has(#button-1398-btnIconEl)'),
            _css("#button-1398-btnIconEl"),
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


def _selecionar_opcao(page, controle, valor: str, alternativas: list[str], descricao: str):
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
            opcao = _primeiro_visivel(
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


def _meses_possiveis(mes_num: int) -> list[str]:
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


def _confirmar_login_concluido(campo_senha, nome_escola: str, ip_nvr: str) -> None:
    """Espera a tela de login sair e diferencia falha de autenticação da busca."""
    try:
        campo_senha.wait_for(state="hidden", timeout=15000)
        return
    except Exception:
        if not campo_senha.is_visible():
            return

    raise ElementoNVRNaoEncontrado(
        f"O login de {nome_escola} ({ip_nvr}) não avançou: a tela de autenticação "
        "continua visível após clicar em Entrar. A tela também apresenta o campo "
        "loginNetSelect-inputEl; verifique se ele exige selecionar uma "
        "rede/dispositivo e se o NVR mostrou mensagem de credenciais inválidas."
    )


def _diagnosticar_tela(page, nome_escola: str, ip_nvr: str) -> None:
    if page is None:
        return
    try:
        seletores = (
            "input, button, [role='button'], [role='menuitem'], "
            "[role='combobox'], [aria-haspopup], select, "
            "div.ux_desktop_shortcut_box, span[t='com.SearchTitle']"
        )
        frames = []
        for quadro in page.frames:
            try:
                controles = quadro.locator(seletores).evaluate_all(
                    """elements => elements
                        .filter(el => el.getClientRects().length)
                        .slice(0, 80)
                        .map(el => ({
                            tag: el.tagName.toLowerCase(),
                            type: el.getAttribute('type'),
                            id: el.id || null,
                            name: el.getAttribute('name'),
                            class: el.className || null,
                            placeholder: el.getAttribute('placeholder'),
                            role: el.getAttribute('role'),
                            ariaLabel: el.getAttribute('aria-label'),
                            title: el.getAttribute('title'),
                            texto: ['INPUT', 'SELECT'].includes(el.tagName)
                                ? null : (el.innerText || '').trim().slice(0, 80)
                        }))"""
                )
                frames.append({"url": quadro.url, "controles_visiveis": controles})
            except Exception as exc:
                frames.append(
                    {"url": quadro.url, "erro_inspecao": type(exc).__name__}
                )
        logger.error(
            "[PLAYWRIGHT DIAGNÓSTICO] Frames e controles visíveis: %s",
            frames,
        )
    except Exception as exc:
        logger.warning(
            "[PLAYWRIGHT DIAGNÓSTICO] Não consegui ler os controles da tela (%s).",
            type(exc).__name__,
        )

    try:
        logger.error(
            "[PLAYWRIGHT DIAGNÓSTICO] Página principal em %s",
            page.url,
        )
    except Exception as exc:
        logger.warning(
            "[PLAYWRIGHT DIAGNÓSTICO] Não consegui ler os controles da tela (%s).",
            type(exc).__name__,
        )

    try:
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", nome_escola).strip("_")[:50]
        horario = datetime.now().strftime("%Y%m%d_%H%M%S")
        caminho = Path(LOGS_DIR) / f"nvr_ui_{slug}_{horario}.png"
        page.screenshot(path=str(caminho), full_page=True)
        logger.error("[PLAYWRIGHT DIAGNÓSTICO] Screenshot da falha salvo em %s", caminho)
    except Exception as exc:
        logger.warning(
            "[PLAYWRIGHT DIAGNÓSTICO] Não consegui salvar screenshot (%s).",
            type(exc).__name__,
        )


def capturar_print_nvr(
    ip_nvr,
    nome_escola,
    ano_alvo,
    mes_num,
    *,
    headless=True,
    slow_mo_ms=0,
    aguardar_em_erro=False,
):
    browser = None
    page = None
    playwright = None
    try:
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=headless, slow_mo=slow_mo_ms)
        page = browser.new_page()

        logger.info("[PLAYWRIGHT] Acessando http://%s...", ip_nvr)
        page.goto(f"http://{ip_nvr}", timeout=60000)

        try:
            page.wait_for_selector(
                "input, [role='textbox'], [contenteditable='true']",
                state="visible",
                timeout=40000,
            )
        except Exception:
            logger.info(
                "[PLAYWRIGHT] Formulário de login padrão não apareceu; "
                "verificando acesso direto à interface."
            )

        campo_senha = _primeiro_visivel(
            page,
            "campo de senha",
            _candidatos_senha(),
            obrigatorio=False,
        )
        if campo_senha is not None:
            campo_usuario = _primeiro_visivel(
                page, "campo de usuário", _candidatos_usuario()
            )
            campo_usuario.fill(USUARIO)
            campo_senha.fill(SENHA)
            botao_entrar = _primeiro_visivel(
                page,
                "botão de login",
                [
                    # Alguns firmwares expõem o ícone como alvo clicável;
                    # tentamos também o botão pai para evitar clicar só no ícone.
                    _css("#loginButton"),
                    _css('button:has(#loginButton-btnIconEl)'),
                    _css("#loginButton-btnIconEl"),
                    _role(
                        "botão Entrar/Login",
                        "button",
                        re.compile(
                            r"entrar|acessar|login|sign in|log in",
                            re.IGNORECASE,
                        ),
                    ),
                    _css('button[type="submit"]'),
                    _css('input[type="submit"]'),
                ],
                obrigatorio=False,
            )
            if botao_entrar is not None:
                botao_entrar.click()
            else:
                campo_senha.press("Enter")
            _confirmar_login_concluido(campo_senha, nome_escola, ip_nvr)
        else:
            logger.info(
                "[PLAYWRIGHT] Campo de senha não encontrado; "
                "prosseguindo como interface sem login ou já autenticada."
            )

        logger.info(
            "[PLAYWRIGHT] Aguardando a interface Pesquisa/Playback carregar..."
        )
        _aguardar_entrada_pesquisa(page)

        logger.info("[PLAYWRIGHT] Localizando entrada para pesquisa de gravações...")
        botao_pesquisar = _primeiro_visivel(
            page, "Pesquisa/Playback", _candidatos_pesquisa()
        )
        botao_pesquisar.click()

        botao_abrir_calendario = _primeiro_visivel(
            page,
            "botão para abrir calendário",
            [
                _css('button:has(#splitbutton-1392-btnInnerEl)'),
                _css("#splitbutton-1392-btnInnerEl"),
            ],
            obrigatorio=False,
        )
        if botao_abrir_calendario is not None:
            logger.info("[PLAYWRIGHT] Abrindo calendário pelo botão ExtJS identificado.")
            botao_abrir_calendario.click()

        if _selecionar_calendario_extjs(page, ano_alvo, mes_num):
            logger.info(
                "[PLAYWRIGHT] Calendário ExtJS selecionado e confirmado: %02d/%s.",
                mes_num,
                ano_alvo,
            )
        else:
            logger.info("[PLAYWRIGHT] Localizando seletor de ano...")
            controle_ano = _primeiro_visivel(
                page, "seletor de ano", _candidatos_seletor_calendario("ano", 0)
            )
            _selecionar_opcao(
                page,
                controle_ano,
                str(ano_alvo),
                [str(ano_alvo)],
                "ano",
            )

            logger.info("[PLAYWRIGHT] Localizando seletor do mês %s...", mes_num)
            controle_mes = _primeiro_visivel(
                page, "seletor de mês", _candidatos_seletor_calendario("mês", 1)
            )
            _selecionar_opcao(
                page,
                controle_mes,
                str(mes_num),
                _meses_possiveis(mes_num),
                "mês",
            )

        os.makedirs(pasta_destino, exist_ok=True)
        data_str = datetime.now().strftime("%d-%m-%Y")
        nome_limpo = (
            nome_escola.replace(" ", "_")
            .replace(".", "")
            .replace("ª", "a")
            .replace("º", "o")
        )
        nome_arquivo = os.path.join(
            pasta_destino,
            f"{nome_limpo}_{data_str}.png",
        )
        page.screenshot(path=nome_arquivo, full_page=True)
        logger.info(
            "[PLAYWRIGHT] Print do calendário mensal capturado: %s",
            nome_arquivo,
        )
        return nome_arquivo
    except Exception as exc:
        logger.error(
            "[PLAYWRIGHT ERRO] Captura falhou no NVR %s (%s): %s",
            nome_escola,
            ip_nvr,
            exc,
        )
        if not headless:
            _diagnosticar_tela(page, nome_escola, ip_nvr)
        if aguardar_em_erro and browser is not None and browser.is_connected():
            print(
                f"\n[DEVTOOLS] Falha em {nome_escola} ({ip_nvr}). "
                "O navegador ficará aberto para inspeção; pressione Enter "
                "quando terminar de verificar a tela."
            )
            try:
                input()
            except (EOFError, KeyboardInterrupt):
                pass
        return None
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception as exc:
                logger.debug(
                    "[PLAYWRIGHT] Falha ao encerrar navegador de %s (%s).",
                    nome_escola,
                    type(exc).__name__,
                )
        if playwright is not None:
            try:
                playwright.stop()
            except Exception as exc:
                logger.debug(
                    "[PLAYWRIGHT] Falha ao encerrar Playwright de %s (%s).",
                    nome_escola,
                    type(exc).__name__,
                )

