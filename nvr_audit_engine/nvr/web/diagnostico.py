"""Diagnóstico da tela do NVR quando a captura falha em modo visível."""

import re
from datetime import datetime
from pathlib import Path

from nvr_audit_engine.config import LOGS_DIR
from nvr_audit_engine.log import logger


def diagnosticar_tela(page, nome_escola: str, ip_nvr: str) -> None:
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
