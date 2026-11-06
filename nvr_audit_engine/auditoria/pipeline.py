"""Orquestração da auditoria: NVR -> contagem -> evidência -> ticket -> estado -> planilha.

Uma escola só é aprovada quando, na mesma execução, a auditoria fica
completa, o print do calendário existe em disco e o ticket do 7LAN é
confirmado. As integrações externas entram por `Integracoes`, o que permite
ao devtools e aos testes trocá-las sem alterar este módulo.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import requests
from requests.auth import HTTPDigestAuth

from nvr_audit_engine import config
from nvr_audit_engine.auditoria.retencao import SEM_DATA, contar_dias_continuos
from nvr_audit_engine.log import logger
from nvr_audit_engine.escolas import RegistroEscolas
from nvr_audit_engine.integracoes.lan7 import ResultadoTicket, criar_ticket_7lan
from nvr_audit_engine.integracoes.sheets import enviar_para_google_sheets
from nvr_audit_engine.nvr.busca_gravacoes import (
    MOTIVOS_REDE,
    FalhaCGI,
    consultar_dia,
    verificar_api,
)
from nvr_audit_engine.nvr.web.captura import capturar_print_nvr

CANAL_AUDITADO = 1


@dataclass
class Integracoes:
    """Efeitos externos da auditoria; os padrões são os de produção."""

    capturar_print: Callable[[str, str, str, int], str | None] = capturar_print_nvr
    criar_ticket: Callable[[str, str], ResultadoTicket] = criar_ticket_7lan
    enviar_planilha: Callable[[list[dict]], None] = enviar_para_google_sheets


@dataclass
class ResultadoEscola:
    """Desfecho de uma escola na execução; `linha` é o que vai para a planilha."""

    linha: dict
    resultado: str  # aprovada, sem_rede, incompleta, verificar_no_local, falha_print, ...
    motivo: str | None = None

    @property
    def de_rede(self) -> bool:
        return self.motivo in MOTIVOS_REDE


def auditar_retencao_nvr_com_cloud(
    registro: RegistroEscolas | None = None,
    escolas: dict[str, str] | None = None,
    integracoes: Integracoes | None = None,
    somente_pendentes: bool = False,
):
    """Audita as escolas elegíveis e envia os resultados à planilha.

    Sem argumentos usa data/escolas.json e as integrações de produção.
    `escolas` restringe a execução a um subconjunto {nome: ip}.
    As escolas que falharam na última tentativa vêm primeiro; com
    `somente_pendentes`, só elas são auditadas.
    """
    if registro is None:
        registro = RegistroEscolas.carregar(config.ARQUIVO_ESCOLAS)
    if escolas is None:
        escolas = registro.unidades_com_ip()
    if integracoes is None:
        integracoes = Integracoes()

    pendentes = registro.pendentes()
    if somente_pendentes:
        escolas = {nome: ip for nome, ip in escolas.items() if nome in pendentes}
        logger.info("[PENDENTES] %d escola(s) com falha na última tentativa.", len(escolas))
    else:
        # sorted é estável: dentro de cada grupo a ordem do escolas.json é mantida.
        escolas = dict(sorted(escolas.items(), key=lambda item: item[0] not in pendentes))

    try:
        largura_terminal = os.get_terminal_size().columns
    except (OSError, AttributeError):
        largura_terminal = 120

    titulo = " AUDITORIA INTELIGENTE DE GRAVAÇÕES ESCOLARES - VERTH TECNOLOGIAS "
    print("\n" + titulo.center(largura_terminal, "="))

    resultados: dict[str, ResultadoEscola] = {}

    for nome_escola, nvr_ip in escolas.items():
        proxima_auditoria = registro.proxima_auditoria_agendada(nome_escola)
        if proxima_auditoria is not None:
            logger.info(
                "[PULADA] %s aprovada; próxima auditoria liberada em %s.",
                nome_escola,
                proxima_auditoria.isoformat(timespec="seconds"),
            )
            continue

        resultados[nome_escola] = _auditar_escola(registro, integracoes, nome_escola, nvr_ip)
        print("=" * largura_terminal + "\n")

    # NVRs oscilam entre execuções (Padre Donato e Santo Agostinho falharam em 19/10
    # e passaram em 30/10): falhas de rede ganham mais uma chance no fim.
    falhas_de_rede = [nome for nome, r in resultados.items() if r.de_rede]
    if falhas_de_rede:
        logger.info(
            "[SEGUNDA PASSADA] Repetindo %d escola(s) que falharam por rede: %s",
            len(falhas_de_rede),
            ", ".join(falhas_de_rede),
        )
    for nome_escola in falhas_de_rede:
        resultados[nome_escola] = _auditar_escola(
            registro, integracoes, nome_escola, escolas[nome_escola]
        )
        print("=" * largura_terminal + "\n")

    # Registrado depois das duas passadas, para a segunda não contar como outra tentativa.
    for nome_escola, r in resultados.items():
        try:
            registro.registrar_tentativa(
                nome_escola, escolas[nome_escola], r.resultado, r.motivo, r.de_rede
            )
        except OSError as exc:
            logger.error("[ESTADO] Não foi possível registrar a tentativa de %s: %s", nome_escola, exc)

    offline = {
        nome: vezes for nome, vezes in registro.offline_persistentes().items()
        if nome in resultados
    }
    if offline:
        logger.warning(
            "[OFFLINE PERSISTENTE] %d NVR(s) sem rede em execuções seguidas; acionar a rede: %s",
            len(offline),
            "; ".join(f"{nome} ({escolas[nome]}): {vezes}x" for nome, vezes in offline.items()),
        )

    if resultados:
        integracoes.enviar_planilha([r.linha for r in resultados.values()])


def _auditar_escola(
    registro: RegistroEscolas,
    integracoes: Integracoes,
    nome_escola: str,
    nvr_ip: str,
) -> ResultadoEscola:
    """Conectividade -> contagem -> evidência/OS de uma escola."""
    logger.info("[UNIDADE] Processando unidade: %s - Endereço IP: (%s)", nome_escola, nvr_ip)
    url_base = f"http://{nvr_ip}/cgi-bin/mediaFileFind.cgi"
    sessao = requests.Session()
    sessao.auth = HTTPDigestAuth(config.USUARIO, config.SENHA)
    falha = FalhaCGI()

    if not verificar_api(sessao, url_base, nome_escola, falha=falha):
        logger.warning(
            "[ALERTA] %s: API do NVR indisponível (%s); resultado marcado como inconclusivo.",
            nome_escola,
            falha.motivo,
        )
        sessao.close()
        linha = {
            "Escola": nome_escola,
            "IP do NVR": nvr_ip,
            "Dias Contínuos Válidos": "Verificação incompleta (API indisponível)",
            "Gravação mais antiga": SEM_DATA,
        }
        return _falha_de_comunicacao(linha, falha.motivo)

    try:
        retencao = contar_dias_continuos(
            lambda data_str: consultar_dia(
                sessao, url_base, CANAL_AUDITADO, data_str, nome_escola, falha=falha
            )
        )
    finally:
        sessao.close()

    if not retencao.completa:
        logger.error(
            "[INCOMPLETO] %s: não foi possível validar %s após as tentativas (%s); "
            "a escola não será registrada como resultado completo.",
            nome_escola,
            retencao.data_inconclusiva,
            falha.motivo,
        )

    data_fim_hd = retencao.gravacao_mais_antiga
    if not retencao.completa:
        valor_dias_celula = "Verificação incompleta (falha da API)"
    elif retencao.dias_continuos == 0:
        valor_dias_celula = "Verificar no local"
    else:
        valor_dias_celula = retencao.dias_continuos

    linha = {
        "Escola": nome_escola,
        "IP do NVR": nvr_ip,
        "Dias Contínuos Válidos": valor_dias_celula,
        "Gravação mais antiga": data_fim_hd,
    }

    if not retencao.completa:
        logger.warning("[ALERTA] %s: auditoria incompleta; evidência e ticket não serão gerados.", nome_escola)
        return _falha_de_comunicacao(linha, falha.motivo)

    if not isinstance(valor_dias_celula, int):
        logger.warning("[ALERTA] %s: %s", nome_escola, valor_dias_celula)
        return ResultadoEscola(linha, "verificar_no_local")

    logger.info(
        "[OK] %s: %s dias contínuos computados. (Último dia válido: %s)",
        nome_escola,
        valor_dias_celula,
        data_fim_hd,
    )
    if data_fim_hd == SEM_DATA:
        # Nenhum buraco em LIMITE_DIAS: sem mês para o print, sem OS.
        return ResultadoEscola(linha, "sem_data_para_print", "sem buraco no limite de dias")
    try:
        resultado, motivo = _gerar_evidencia_e_aprovar(
            registro, integracoes, nome_escola, nvr_ip, data_fim_hd
        )
    except Exception as exc:
        logger.error("[ERRO EVIDÊNCIA] Falha ao processar evidências: %s", exc)
        resultado, motivo = "falha_evidencia", str(exc)
    return ResultadoEscola(linha, resultado, motivo)


def _falha_de_comunicacao(linha: dict, motivo: str | None) -> ResultadoEscola:
    resultado = "sem_rede" if motivo in MOTIVOS_REDE else "incompleta"
    return ResultadoEscola(linha, resultado, motivo)


def _gerar_evidencia_e_aprovar(
    registro: RegistroEscolas,
    integracoes: Integracoes,
    nome_escola: str,
    nvr_ip: str,
    data_fim_hd: str,
) -> tuple[str, str | None]:
    """Print do mês da gravação mais antiga -> ticket -> aprovação persistida.

    Devolve (resultado, motivo): aprovada, falha_print, falha_os ou falha_estado.
    """
    dt_fim = datetime.strptime(data_fim_hd, "%d/%m/%Y")
    ano_str = dt_fim.strftime("%Y")
    mes_num = dt_fim.month
    logger.info(
        "[EVIDÊNCIA] Gerando print do calendário para %s (Mês %s/%s)...",
        nome_escola,
        mes_num,
        ano_str,
    )
    caminho_evidencia = integracoes.capturar_print(nvr_ip, nome_escola, ano_str, mes_num)
    if not caminho_evidencia or not os.path.isfile(caminho_evidencia):
        logger.warning(
            "[ESTADO] %s não aprovada: evidência não foi capturada.",
            nome_escola,
        )
        return "falha_print", "print não capturado"

    resultado = integracoes.criar_ticket(nome_escola, caminho_evidencia)
    if not resultado.concluida and not resultado.salvar_clicado:
        # Nada foi gravado no 7LAN antes do clique em salvar: repetir não duplica a OS.
        logger.warning("[TICKET] %s: falha antes de salvar a OS; nova tentativa.", nome_escola)
        resultado = integracoes.criar_ticket(nome_escola, caminho_evidencia)
    if not resultado.concluida:
        situacao = (
            "OS criada mas não concluída (verificar e fechar no 7LAN)"
            if resultado.criada or resultado.salvar_clicado
            else "OS não foi criada"
        )
        logger.warning(
            "[ESTADO] %s não aprovada: %s; anexada=%s, fechada=%s, erro: %s",
            nome_escola,
            situacao,
            resultado.anexada,
            resultado.fechada,
            resultado.erro,
        )
        return "falha_os", f"{situacao}: {resultado.erro}" if resultado.erro else situacao

    try:
        concluida_em, proxima_auditoria_em = registro.marcar_aprovada(nome_escola, nvr_ip)
    except OSError as exc:
        logger.error(
            "[ESTADO] Não foi possível persistir aprovação de %s: %s",
            nome_escola,
            exc,
        )
        return "falha_estado", str(exc)
    logger.info(
        "[ESTADO] %s aprovada em %s; próxima auditoria em %s.",
        nome_escola,
        concluida_em,
        proxima_auditoria_em,
    )
    return "aprovada", None
