"""Print do calendário de gravações pela interface web do NVR (Playwright).

Fluxo: login -> atalho Pesquisa/Playback -> calendário no mês pedido -> print
em PASTA_EVIDENCIAS. Devolve o caminho do arquivo ou None em caso de falha.
"""

import os
import re
from datetime import datetime

from playwright.sync_api import sync_playwright

from nvr_audit_engine.config import PASTA_EVIDENCIAS as pasta_destino
from nvr_audit_engine.config import SENHA, USUARIO
from nvr_audit_engine.evidencias import caminho_evidencia
from nvr_audit_engine.log import logger
from nvr_audit_engine.nvr.web.calendario import (
    candidatos_seletor_calendario,
    meses_possiveis,
    selecionar_calendario_extjs,
    selecionar_opcao,
)
from nvr_audit_engine.nvr.web.diagnostico import diagnosticar_tela
from nvr_audit_engine.nvr.web.localizadores import (
    ElementoNVRNaoEncontrado,
    aguardar_entrada_pesquisa,
    candidatos_pesquisa,
    candidatos_senha,
    candidatos_usuario,
    css,
    primeiro_visivel,
    role,
)


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

        campo_senha = primeiro_visivel(
            page,
            "campo de senha",
            candidatos_senha(),
            obrigatorio=False,
        )
        if campo_senha is not None:
            campo_usuario = primeiro_visivel(
                page, "campo de usuário", candidatos_usuario()
            )
            campo_usuario.fill(USUARIO)
            campo_senha.fill(SENHA)
            botao_entrar = primeiro_visivel(
                page,
                "botão de login",
                [
                    # Alguns firmwares expõem o ícone como alvo clicável;
                    # tentamos também o botão pai para evitar clicar só no ícone.
                    css("#loginButton"),
                    css('button:has(#loginButton-btnIconEl)'),
                    css("#loginButton-btnIconEl"),
                    role(
                        "botão Entrar/Login",
                        "button",
                        re.compile(
                            r"entrar|acessar|login|sign in|log in",
                            re.IGNORECASE,
                        ),
                    ),
                    css('button[type="submit"]'),
                    css('input[type="submit"]'),
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
        aguardar_entrada_pesquisa(page)

        logger.info("[PLAYWRIGHT] Localizando entrada para pesquisa de gravações...")
        botao_pesquisar = primeiro_visivel(
            page, "Pesquisa/Playback", candidatos_pesquisa()
        )
        botao_pesquisar.click()

        botao_abrir_calendario = primeiro_visivel(
            page,
            "botão para abrir calendário",
            [
                css('button:has(#splitbutton-1392-btnInnerEl)'),
                css("#splitbutton-1392-btnInnerEl"),
            ],
            obrigatorio=False,
        )
        if botao_abrir_calendario is not None:
            logger.info("[PLAYWRIGHT] Abrindo calendário pelo botão ExtJS identificado.")
            botao_abrir_calendario.click()

        if selecionar_calendario_extjs(page, ano_alvo, mes_num):
            logger.info(
                "[PLAYWRIGHT] Calendário ExtJS selecionado e confirmado: %02d/%s.",
                mes_num,
                ano_alvo,
            )
        else:
            logger.info("[PLAYWRIGHT] Localizando seletor de ano...")
            controle_ano = primeiro_visivel(
                page, "seletor de ano", candidatos_seletor_calendario("ano", 0)
            )
            selecionar_opcao(
                page,
                controle_ano,
                str(ano_alvo),
                [str(ano_alvo)],
                "ano",
            )

            logger.info("[PLAYWRIGHT] Localizando seletor do mês %s...", mes_num)
            controle_mes = primeiro_visivel(
                page, "seletor de mês", candidatos_seletor_calendario("mês", 1)
            )
            selecionar_opcao(
                page,
                controle_mes,
                str(mes_num),
                meses_possiveis(mes_num),
                "mês",
            )

        os.makedirs(pasta_destino, exist_ok=True)
        nome_arquivo = caminho_evidencia(pasta_destino, nome_escola, datetime.now())
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
            diagnosticar_tela(page, nome_escola, ip_nvr)
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
