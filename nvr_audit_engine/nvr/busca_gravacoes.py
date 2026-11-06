"""Busca de gravações nos NVRs Dahua legados via mediaFileFind.cgi.

Contrato de compatibilidade: endpoints, parâmetros, formato de data,
codificação da URL, autenticação e timeouts não mudam sem evidência em
equipamento real e teste automatizado (docs/DIARIO_COMPATIBILIDADE_NVR.md).
"""

import re
import time
from collections.abc import Callable
from typing import TypeVar

import requests
from requests.auth import HTTPDigestAuth

from nvr_audit_engine.log import logger


T = TypeVar("T")

TENTATIVAS_API = 3
TIMEOUT_API = (5, 20)  # timeout de conexão e timeout de leitura
HTTP_TRANSITORIOS = {408, 425, 429, 500, 502, 503, 504}


class RespostaCGIInvalida(Exception):
    """A CGI respondeu, mas o corpo não representa um resultado reconhecido."""


def _repetivel(exc: Exception) -> bool:
    if isinstance(exc, RespostaCGIInvalida):
        return True
    if isinstance(exc, requests.exceptions.HTTPError):
        response = exc.response
        return response is not None and response.status_code in HTTP_TRANSITORIOS
    return isinstance(
        exc,
        (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
            requests.exceptions.ContentDecodingError,
        ),
    )


def _com_retentativas(acao: Callable[[], T], contexto: str) -> T | None:
    """Executa uma operação CGI com até três tentativas e espera crescente."""
    for tentativa in range(1, TENTATIVAS_API + 1):
        try:
            return acao()
        except (requests.exceptions.RequestException, RespostaCGIInvalida) as exc:
            repetivel = _repetivel(exc)
            if not repetivel or tentativa == TENTATIVAS_API:
                logger.error(
                    "[API NVR] %s falhou na tentativa %d/%d (%s): %s",
                    contexto,
                    tentativa,
                    TENTATIVAS_API,
                    type(exc).__name__,
                    exc,
                )
                return None

            espera = tentativa  # 1s, depois 2s; limitado para não travar a auditoria.
            logger.warning(
                "[API NVR] %s falhou na tentativa %d/%d (%s). Nova tentativa em %ss.",
                contexto,
                tentativa,
                TENTATIVAS_API,
                type(exc).__name__,
                espera,
            )
            time.sleep(espera)
    return None


def _get_cgi(
    sessao: requests.Session,
    url: str,
    *,
    aceitar_http_400: bool = False,
):
    resposta = sessao.get(url, timeout=TIMEOUT_API)
    # Firmwares Dahua antigos podem responder HTTP 400 ao iniciar uma busca
    # sem correspondências. Nesses casos, findNextFile em um token novo é a
    # fonte autoritativa: só um corpo válido `found=0` pode confirmar dia vazio.
    if not (aceitar_http_400 and resposta.status_code == 400):
        resposta.raise_for_status()
    return resposta


def _extrair_token(texto: str) -> str:
    for linha in texto.splitlines():
        chave, separador, valor = linha.partition("=")
        if separador and chave.strip().lower() == "result" and valor.strip():
            return valor.strip()
    raise RespostaCGIInvalida("factory.create não retornou um token result")


def _criar_token(sessao: requests.Session, url_base: str) -> str:
    resposta = _get_cgi(sessao, f"{url_base}?action=factory.create")
    return _extrair_token(resposta.text)


def _fechar_token(sessao: requests.Session, url_base: str, token: str) -> None:
    try:
        _get_cgi(sessao, f"{url_base}?action=close&object={token}")
    except requests.exceptions.RequestException as exc:
        # A pesquisa já foi concluída; falha de limpeza não altera o resultado do dia.
        logger.warning("[API NVR] Não foi possível fechar token de pesquisa (%s).", type(exc).__name__)


def _resultado_busca(texto: str) -> bool:
    """Retorna True/False somente para respostas de busca reconhecíveis."""
    encontrado = re.search(r"(?im)^\s*found\s*=\s*(\d+)\s*$", texto)
    if encontrado:
        return int(encontrado.group(1)) > 0
    if re.search(r"(?im)^\s*items\[\d+\]\.", texto):
        return True
    raise RespostaCGIInvalida("findNextFile não retornou found= ou items[n]")


def _consultar_dia_uma_vez(
    sessao: requests.Session,
    url_base: str,
    canal: int,
    data_str: str,
) -> bool:
    token = _criar_token(sessao, url_base)
    try:
        url_buscar = (
            f"{url_base}?action=findFile&object={token}"
            f"&condition.Channel={canal}"
            f"&condition.StartTime={data_str}%2000:00:00"
            f"&condition.EndTime={data_str}%2023:59:59"
            "&condition.Types[0]=dav"
        )
        _get_cgi(sessao, url_buscar, aceitar_http_400=True)
        resposta = _get_cgi(
            sessao,
            f"{url_base}?action=findNextFile&object={token}&count=1",
        )
        return _resultado_busca(resposta.text)
    finally:
        _fechar_token(sessao, url_base, token)


def _nao_autorizado(exc: requests.exceptions.HTTPError) -> bool:
    return exc.response is not None and exc.response.status_code == 401


def _renovar_sessao(sessao: requests.Session) -> None:
    """Descarta conexões e o estado Digest para o NVR emitir um nonce novo."""
    credenciais = sessao.auth
    sessao.close()
    sessao.cookies.clear()
    sessao.auth = HTTPDigestAuth(credenciais.username, credenciais.password)


def consultar_dia(
    sessao: requests.Session,
    url_base: str,
    canal: int,
    data_str: str,
    escola: str,
) -> bool | None:
    """Retorna True (há gravação), False (vazio confirmado), None (inconclusivo)."""
    def consultar_e_confirmar() -> bool:
        if _consultar_dia_uma_vez(sessao, url_base, canal, data_str):
            return True

        # Só confirma ausência quando uma segunda consulta completa também responde vazio.
        return _consultar_dia_uma_vez(sessao, url_base, canal, data_str)

    def consultar_com_reautenticacao() -> bool:
        try:
            return consultar_e_confirmar()
        except requests.exceptions.HTTPError as exc:
            if not _nao_autorizado(exc):
                raise
        # A senha já foi aceita em verificar_api: um 401 no meio da contagem vem
        # da sessão Digest expirada (~1 min em alguns firmwares). Renova e repete
        # o dia uma vez; um segundo 401 deixa o dia inconclusivo.
        logger.warning(
            "[API NVR] %s, canal %s, data %s: NVR recusou a sessão (401); "
            "renovando a autenticação e repetindo o dia.",
            escola,
            canal,
            data_str,
        )
        _renovar_sessao(sessao)
        return consultar_e_confirmar()

    return _com_retentativas(
        consultar_com_reautenticacao,
        f"{escola}, canal {canal}, data {data_str}",
    )


def verificar_api(sessao: requests.Session, url_base: str, escola: str) -> bool:
    def verificar() -> bool:
        token = _criar_token(sessao, url_base)
        _fechar_token(sessao, url_base, token)
        return True

    return _com_retentativas(verificar, f"conectividade CGI de {escola}") is True
