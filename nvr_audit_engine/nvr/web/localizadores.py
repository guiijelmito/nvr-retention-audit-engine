"""Localização tolerante de controles na interface web dos NVRs.

Cada controle tem uma lista de variantes de seletor (firmwares diferentes
renderizam telas diferentes); a primeira visível em qualquer frame vence.
"""

import re
import time

from nvr_audit_engine.log import logger


class ElementoNVRNaoEncontrado(RuntimeError):
    """Nenhum dos seletores conhecidos localizou o controle esperado."""


class ElementoNVRLocalizado:
    """Encapsula o locator e o frame em que ele foi encontrado."""

    def __init__(self, locator, contexto):
        self.locator = locator
        self.contexto = contexto

    def __getattr__(self, nome):
        return getattr(self.locator, nome)


def css(seletor: str):
    return seletor, lambda page: page.locator(seletor)


def role(descricao: str, papel: str, nome: re.Pattern):
    return descricao, lambda page: page.get_by_role(papel, name=nome)


def primeiro_visivel(page, descricao: str, candidatos, *, obrigatorio=True):
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


def candidatos_usuario():
    nome = re.compile(r"usuário|usuario|user|login|e-mail|email", re.IGNORECASE)
    return [
        # Variante identificada manualmente em NVRs usados pelas escolas.
        css("#loginUsername-inputEl"),
        role("textbox nome de usuário", "textbox", nome),
        css('input[autocomplete="username"]'),
        css('input[aria-label*="user" i]'),
        css('input[placeholder*="user" i]'),
        css('input[name*="user" i]'),
        css('input[id*="user" i]'),
        css('input[type="email"]'),
        css("input.ant-input"),
        css('input[type="text"]'),
        css("input:not([type='password'])"),
        css('[role="textbox"]'),
        css('[contenteditable="true"]'),
    ]


def candidatos_senha():
    nome = re.compile(r"senha|password", re.IGNORECASE)
    return [
        # Variante identificada manualmente em NVRs usados pelas escolas.
        css("#loginPassword-inputEl"),
        role("textbox nome de senha", "textbox", nome),
        css('input[type="password"]'),
        css('input[autocomplete*="password" i]'),
        css('input[name*="pass" i]'),
        css('input[id*="pass" i]'),
    ]


def candidatos_pesquisa():
    nome = re.compile(r"pesquisar|search|playback|gravações|gravacoes", re.IGNORECASE)
    return [
        # O ícone e a chave de tradução juntos identificam especificamente o atalho.
        css(
            '.ux_desktop_shortcut_box:has(img[src*="desktop-playback.png"]):'
            'has(.ux_desktop_app_name > span[t="com.SearchTitle"])'
        ),
        # Fallback para versões do firmware que não renderizam o ícone esperado.
        css(
            '.ux_desktop_shortcut_box:has('
            '.ux_desktop_app_name span[t="com.SearchTitle"])'
        ),
        css('.ux_desktop_shortcut_box:has-text("PESQUISAR")'),
        role("botão Pesquisar/Search", "button", nome),
        role("link Pesquisar/Search", "link", nome),
        role("item de menu Pesquisa/Playback", "menuitem", nome),
        css(
            '.ViewItem-CardItem-Title:has-text("PESQUISAR"), '
            '.ViewItem-CardItem-Title:has-text("SEARCH")'
        ),
        ("texto Pesquisar/Search/Playback", lambda page: page.get_by_text(nome)),
        css('[aria-label*="search" i]'),
        css('[title*="search" i]'),
    ]


def aguardar_entrada_pesquisa(page, timeout_ms: int = 30000) -> None:
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
