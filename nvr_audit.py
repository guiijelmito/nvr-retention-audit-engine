from datetime import datetime, timedelta
import os
import re
import time
from collections.abc import Callable
from typing import TypeVar

import requests
from requests.auth import HTTPDigestAuth

from config import ESCOLAS, SENHA, USUARIO, logger
from nvr_capture import capturar_print_nvr
from cloud_sync import enviar_para_google_sheets
from ticket_automation import criar_ticket_7lan


T = TypeVar("T")

LIMITE_DIAS = 730
LIMITE_BURACO = 3
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


def _get_cgi(sessao: requests.Session, url: str):
    resposta = sessao.get(url, timeout=TIMEOUT_API)
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
        _get_cgi(sessao, url_buscar)
        resposta = _get_cgi(
            sessao,
            f"{url_base}?action=findNextFile&object={token}&count=1",
        )
        return _resultado_busca(resposta.text)
    finally:
        _fechar_token(sessao, url_base, token)


def _consultar_dia(
    sessao: requests.Session,
    url_base: str,
    canal: int,
    data_str: str,
    escola: str,
) -> bool | None:
    """Retorna True (há gravação), False (vazio confirmado), None (inconclusivo)."""
    def consultar_e_confirmar() -> bool:
        primeira_consulta = _consultar_dia_uma_vez(sessao, url_base, canal, data_str)
        if primeira_consulta:
            return True

        # Só confirma ausência quando uma segunda consulta completa também responde vazio.
        segunda_consulta = _consultar_dia_uma_vez(sessao, url_base, canal, data_str)
        return primeira_consulta or segunda_consulta

    return _com_retentativas(
        consultar_e_confirmar,
        f"{escola}, canal {canal}, data {data_str}",
    )


def _verificar_api(sessao: requests.Session, url_base: str, escola: str) -> bool:
    def verificar() -> bool:
        token = _criar_token(sessao, url_base)
        _fechar_token(sessao, url_base, token)
        return True

    return _com_retentativas(verificar, f"conectividade CGI de {escola}") is True


def auditar_retencao_nvr_com_cloud():
    try:
        largura_terminal = os.get_terminal_size().columns
    except (OSError, AttributeError):
        largura_terminal = 120

    titulo = " AUDITORIA INTELIGENTE DE GRAVAÇÕES ESCOLARES - VERTH TECNOLOGIAS "
    print("\n" + titulo.center(largura_terminal, "="))

    resultados_para_planilha = []

    for nome_escola, nvr_ip in ESCOLAS.items():
        logger.info("[UNIDADE] Processando unidade: %s - Endereço IP: (%s)", nome_escola, nvr_ip)
        url_base = f"http://{nvr_ip}/cgi-bin/mediaFileFind.cgi"
        sessao = requests.Session()
        sessao.auth = HTTPDigestAuth(USUARIO, SENHA)

        if not _verificar_api(sessao, url_base, nome_escola):
            logger.warning("[ALERTA] %s: API do NVR indisponível; resultado marcado como inconclusivo.", nome_escola)
            resultados_para_planilha.append({
                "Escola": nome_escola,
                "IP do NVR": nvr_ip,
                "Dias Contínuos Válidos": "Verificação incompleta (API indisponível)",
                "Gravação mais antiga": "N/A",
            })
            sessao.close()
            continue

        dias_continuos = 0
        dias_vazios_consecutivos = 0
        fim_do_hd = False
        auditoria_completa = True
        data_fim_hd = "N/A"

        try:
            for dias_atras in range(1, LIMITE_DIAS + 1):
                if fim_do_hd:
                    break

                data_alvo = datetime.now() - timedelta(days=dias_atras)
                data_str = data_alvo.strftime("%Y-%m-%d")
                encontrou_arquivo = _consultar_dia(
                    sessao, url_base, 1, data_str, nome_escola
                )

                if encontrou_arquivo is None:
                    auditoria_completa = False
                    logger.error(
                        "[INCOMPLETO] %s: não foi possível validar %s após as tentativas; "
                        "a escola não será registrada como resultado completo.",
                        nome_escola,
                        data_str,
                    )
                    break

                if encontrou_arquivo:
                    dias_vazios_consecutivos = 0
                    dias_continuos += 1
                    continue

                dias_vazios_consecutivos += 1
                if dias_vazios_consecutivos >= LIMITE_BURACO:
                    data_objeto = datetime.now() - timedelta(
                        days=dias_atras - dias_vazios_consecutivos
                    )
                    data_fim_hd = data_objeto.strftime("%d/%m/%Y")
                    fim_do_hd = True
        finally:
            sessao.close()

        if not auditoria_completa:
            valor_dias_celula = "Verificação incompleta (falha da API)"
        else:
            valor_dias_celula = "Verificar no local" if dias_continuos == 0 else dias_continuos

        resultados_para_planilha.append({
            "Escola": nome_escola,
            "IP do NVR": nvr_ip,
            "Dias Contínuos Válidos": valor_dias_celula,
            "Gravação mais antiga": data_fim_hd,
        })

        if not auditoria_completa:
            logger.warning("[ALERTA] %s: auditoria incompleta; evidência e ticket não serão gerados.", nome_escola)
        elif isinstance(valor_dias_celula, int):
            logger.info(
                "[OK] %s: %s dias contínuos computados. (Último dia válido: %s)",
                nome_escola,
                valor_dias_celula,
                data_fim_hd,
            )
            if data_fim_hd != "N/A":
                try:
                    dt_fim = datetime.strptime(data_fim_hd, "%d/%m/%Y")
                    ano_str = dt_fim.strftime("%Y")
                    mes_num = dt_fim.month
                    logger.info(
                        "[EVIDÊNCIA] Gerando print do calendário para %s (Mês %s/%s)...",
                        nome_escola,
                        mes_num,
                        ano_str,
                    )
                    capturar_print_nvr(nvr_ip, nome_escola, ano_str, mes_num)
                    criar_ticket_7lan(nome_escola)
                except Exception as exc:
                    logger.error("[ERRO EVIDÊNCIA] Falha ao processar evidências: %s", exc)
        else:
            logger.warning("[ALERTA] %s: %s", nome_escola, valor_dias_celula)

        print("=" * largura_terminal + "\n")

    if resultados_para_planilha:
        enviar_para_google_sheets(resultados_para_planilha)
