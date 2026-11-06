import json
from datetime import datetime
from google.oauth2.service_account import Credentials
import gspread
from nvr_audit_engine.config import ARQUIVO_CREDENCIAIS, ESCOPOS, NOME_PLANILHA, NOME_ABA
from nvr_audit_engine.log import logger

COLUNAS_FIXAS = ["Escola", "IP do NVR", "Último dia de gravação"]


class CabecalhoInesperado(ValueError):
    """A aba tem dados, mas sem as colunas que identificam a escola."""


def _numero(valor):
    """Célula lida como texto ("40") volta como número; o resto fica igual."""
    if not isinstance(valor, str) or not valor.strip():
        return valor
    for tipo in (int, float):
        try:
            return tipo(valor)
        except ValueError:
            pass
    return valor


def montar_matriz(dados_atuais: list[list], dados_lista: list[dict], coluna_hoje: str) -> list[list]:
    """Matriz horizontal: uma linha por escola e uma coluna por data de auditoria.

    Mantém todas as linhas e colunas lidas, só acrescenta; por isso o update a
    partir de A1 sobrescreve a aba inteira sem precisar limpá-la antes.
    """
    if dados_atuais:
        cabecalho = list(dados_atuais[0])
        if "Escola" not in cabecalho or "IP do NVR" not in cabecalho:
            raise CabecalhoInesperado(cabecalho)
        registros = [
            dict(zip(cabecalho, linha + [""] * (len(cabecalho) - len(linha))))
            for linha in dados_atuais[1:]
        ]
    else:
        cabecalho, registros = list(COLUNAS_FIXAS), []

    for coluna in ("Último dia de gravação", coluna_hoje):
        if coluna not in cabecalho:
            cabecalho.append(coluna)

    for item in dados_lista:
        valores = {
            "IP do NVR": item["IP do NVR"],
            "Último dia de gravação": item["Gravação mais antiga"],
            coluna_hoje: item["Dias Contínuos Válidos"],
        }
        existentes = [r for r in registros if r.get("Escola") == item["Escola"]]
        for registro in existentes:
            registro.update(valores)
        if not existentes:
            registros.append({"Escola": item["Escola"], **valores})

    colunas_auditoria = [c for c in cabecalho if c not in COLUNAS_FIXAS]
    colunas = COLUNAS_FIXAS + colunas_auditoria
    return [colunas] + [
        [r.get(c, "") for c in COLUNAS_FIXAS] + [_numero(r.get(c, "")) for c in colunas_auditoria]
        for r in registros
    ]


def enviar_para_google_sheets(dados_lista):
    try:
        logger.info("[CLOUD] Autenticando com credenciais da service account...")
        credenciais = Credentials.from_service_account_file(
            ARQUIVO_CREDENCIAIS, scopes=ESCOPOS
        )
        cliente = gspread.authorize(credenciais)

        logger.info(f"[CLOUD] Abrindo planilha '{NOME_PLANILHA}' e aba '{NOME_ABA}'...")
        arquivo_planilha = cliente.open(NOME_PLANILHA)
        aba = arquivo_planilha.worksheet(NOME_ABA)

        logger.info("[CLOUD] Lendo dados atuais para estruturação em matriz horizontal...")
        dados_atuais = aba.get_all_values()

        data_atual_str = datetime.now().strftime("%d/%m/%Y")
        coluna_hoje = f"Dias Contínuos de Gravação: {data_atual_str}"

        try:
            payload = montar_matriz(dados_atuais, dados_lista, coluna_hoje)
        except CabecalhoInesperado as exc:
            # Recomeçar a matriz aqui apagaria o histórico de todas as quinzenas.
            logger.error(
                f"[ERRO] Cabeçalho inesperado na aba '{NOME_ABA}': {exc.args[0]}. "
                "A planilha não foi alterada; corrija as colunas 'Escola' e 'IP do NVR'."
            )
            return
        json.dumps(payload, allow_nan=False)

        logger.info("[CLOUD] Enviando matriz atualizada com a nova coluna...")
        resposta_update = aba.update(payload)

        logger.info(f"[CLOUD] Resposta bruta do Google Sheets: {resposta_update}")
        logger.info(f"[SUCESSO] Matriz quinzenal atualizada com sucesso ({coluna_hoje})!")

    except gspread.exceptions.WorksheetNotFound:
        logger.error(f"[ERRO] A aba '{NOME_ABA}' não foi encontrada na planilha '{NOME_PLANILHA}'.")
    except Exception as e:
        logger.error(f"[ERRO DETALHADO] Tipo: {type(e).__name__} | Mensagem: {str(e)}")
