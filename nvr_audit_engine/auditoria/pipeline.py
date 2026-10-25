from datetime import datetime, timedelta
import json
import os

import requests
from requests.auth import HTTPDigestAuth

from nvr_audit_engine.config import ARQUIVO_ESCOLAS, DADOS_ESCOLAS, ESCOLAS, SENHA, USUARIO, logger
from nvr_audit_engine.nvr.busca_gravacoes import consultar_dia, verificar_api
from nvr_audit_engine.nvr.web.captura import capturar_print_nvr
from nvr_audit_engine.integracoes.sheets import enviar_para_google_sheets
from nvr_audit_engine.integracoes.lan7 import criar_ticket_7lan


LIMITE_DIAS = 730
LIMITE_BURACO = 3
INTERVALO_AUDITORIA_DIAS = 15


def _proxima_auditoria_agendada(nome_escola: str) -> datetime | None:
    dados_escola = DADOS_ESCOLAS.get(nome_escola)
    if not isinstance(dados_escola, dict) or dados_escola.get("status") != "aprovada":
        return None

    data_liberacao = dados_escola.get("proxima_auditoria_em")
    if not isinstance(data_liberacao, str):
        return None

    try:
        proxima = datetime.fromisoformat(data_liberacao)
        if proxima.tzinfo is None:
            proxima = proxima.astimezone()
    except ValueError:
        logger.warning(
            "[ESTADO] Data de próxima auditoria inválida para %s; unidade será reavaliada.",
            nome_escola,
        )
        return None

    return proxima if datetime.now().astimezone() < proxima else None


def _marcar_escola_aprovada(nome_escola: str, nvr_ip: str) -> tuple[str, str]:
    """Persiste o sucesso em JSON de forma atômica após os três critérios."""
    agora = datetime.now().astimezone()
    concluida_em = agora.isoformat(timespec="seconds")
    proxima_auditoria_em = (
        agora + timedelta(days=INTERVALO_AUDITORIA_DIAS)
    ).isoformat(timespec="seconds")

    dados_originais = DADOS_ESCOLAS.get(nome_escola, nvr_ip)
    if isinstance(dados_originais, dict):
        registro = dict(dados_originais)
        registro["ip"] = nvr_ip
    else:
        registro = {"ip": nvr_ip}

    registro.update({
        "status": "aprovada",
        "concluida_em": concluida_em,
        "proxima_auditoria_em": proxima_auditoria_em,
    })
    DADOS_ESCOLAS[nome_escola] = registro

    arquivo_temporario = ARQUIVO_ESCOLAS.with_name(f"{ARQUIVO_ESCOLAS.name}.tmp")
    try:
        with arquivo_temporario.open("w", encoding="utf-8", newline="\n") as arquivo:
            json.dump(DADOS_ESCOLAS, arquivo, ensure_ascii=False, indent=2)
            arquivo.write("\n")
        os.replace(arquivo_temporario, ARQUIVO_ESCOLAS)
    except Exception:
        if isinstance(dados_originais, dict):
            DADOS_ESCOLAS[nome_escola] = dados_originais
        else:
            DADOS_ESCOLAS[nome_escola] = dados_originais
        try:
            arquivo_temporario.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    return concluida_em, proxima_auditoria_em


def auditar_retencao_nvr_com_cloud():
    try:
        largura_terminal = os.get_terminal_size().columns
    except (OSError, AttributeError):
        largura_terminal = 120

    titulo = " AUDITORIA INTELIGENTE DE GRAVAÇÕES ESCOLARES - VERTH TECNOLOGIAS "
    print("\n" + titulo.center(largura_terminal, "="))

    resultados_para_planilha = []

    for nome_escola, nvr_ip in ESCOLAS.items():
        proxima_auditoria = _proxima_auditoria_agendada(nome_escola)
        if proxima_auditoria is not None:
            logger.info(
                "[PULADA] %s aprovada; próxima auditoria liberada em %s.",
                nome_escola,
                proxima_auditoria.isoformat(timespec="seconds"),
            )
            continue

        logger.info("[UNIDADE] Processando unidade: %s - Endereço IP: (%s)", nome_escola, nvr_ip)
        url_base = f"http://{nvr_ip}/cgi-bin/mediaFileFind.cgi"
        sessao = requests.Session()
        sessao.auth = HTTPDigestAuth(USUARIO, SENHA)

        if not verificar_api(sessao, url_base, nome_escola):
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
                encontrou_arquivo = consultar_dia(
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
                    caminho_evidencia = capturar_print_nvr(
                        nvr_ip, nome_escola, ano_str, mes_num
                    )
                    if not caminho_evidencia or not os.path.isfile(caminho_evidencia):
                        logger.warning(
                            "[ESTADO] %s não aprovada: evidência não foi capturada.",
                            nome_escola,
                        )
                        continue

                    ticket_criado = criar_ticket_7lan(nome_escola)
                    if ticket_criado is not True:
                        logger.warning(
                            "[ESTADO] %s não aprovada: criação do ticket não foi confirmada.",
                            nome_escola,
                        )
                        continue

                    try:
                        concluida_em, proxima_auditoria_em = _marcar_escola_aprovada(
                            nome_escola, nvr_ip
                        )
                        logger.info(
                            "[ESTADO] %s aprovada em %s; próxima auditoria em %s.",
                            nome_escola,
                            concluida_em,
                            proxima_auditoria_em,
                        )
                    except OSError as exc:
                        logger.error(
                            "[ESTADO] Não foi possível persistir aprovação de %s: %s",
                            nome_escola,
                            exc,
                        )
                except Exception as exc:
                    logger.error("[ERRO EVIDÊNCIA] Falha ao processar evidências: %s", exc)
        else:
            logger.warning("[ALERTA] %s: %s", nome_escola, valor_dias_celula)

        print("=" * largura_terminal + "\n")

    if resultados_para_planilha:
        enviar_para_google_sheets(resultados_para_planilha)
