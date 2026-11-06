import json
from datetime import datetime
import pandas as pd
from google.oauth2.service_account import Credentials
import gspread
from nvr_audit_engine.config import ARQUIVO_CREDENCIAIS, ESCOPOS, NOME_PLANILHA, NOME_ABA
from nvr_audit_engine.log import logger

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

        if len(dados_atuais) > 0:
            cabecalho = dados_atuais[0]
            if "Escola" not in cabecalho or "IP do NVR" not in cabecalho:
                # Recomeçar a matriz aqui apagaria o histórico de todas as quinzenas.
                logger.error(
                    f"[ERRO] Cabeçalho inesperado na aba '{NOME_ABA}': {cabecalho}. "
                    "A planilha não foi alterada; corrija as colunas 'Escola' e 'IP do NVR'."
                )
                return
            linhas = dados_atuais[1:] if len(dados_atuais) > 1 else []
            df = pd.DataFrame(linhas, columns=cabecalho)
        else:
            df = pd.DataFrame(columns=["Escola", "IP do NVR", "Último dia de gravação"])

        if "Último dia de gravação" not in df.columns:
            df["Último dia de gravação"] = ""

        if coluna_hoje not in df.columns:
            df[coluna_hoje] = ""
        
        df[coluna_hoje] = df[coluna_hoje].astype(object)

        for item in dados_lista:
            nome_escola = item["Escola"]
            ip_nvr = item["IP do NVR"]
            data_fim_hd = item["Gravação mais antiga"]
            dias_vistos = item['Dias Contínuos Válidos']

            if not df.empty and nome_escola in df["Escola"].values:
                df.loc[df["Escola"] == nome_escola, coluna_hoje] = dias_vistos
                df.loc[df["Escola"] == nome_escola, "IP do NVR"] = ip_nvr
                df.loc[df["Escola"] == nome_escola, "Último dia de gravação"] = data_fim_hd
            else:
                nova_linha = {
                    "Escola": nome_escola,
                    "IP do NVR": ip_nvr,
                    "Último dia de gravação": data_fim_hd,
                    coluna_hoje: dias_vistos,
                }
                df = pd.concat([df, pd.DataFrame([nova_linha])], ignore_index=True)

        colunas_fixas = ["Escola", "IP do NVR", "Último dia de gravação"]
        colunas_auditoria = [
            c for c in df.columns 
            if c not in colunas_fixas
        ]
        df = df[colunas_fixas + colunas_auditoria]

        for col in colunas_auditoria:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(df[col])

        # Escola nova fica com NaN nas colunas de datas anteriores; NaN não é JSON válido.
        df = df.astype(object).where(df.notna(), "")
        payload = [df.columns.values.tolist()] + df.values.tolist()
        json.dumps(payload, allow_nan=False)

        # Sem clear(): a matriz contém tudo o que foi lido e só cresce, então o
        # update a partir de A1 sobrescreve a aba; uma falha nele não a deixa vazia.
        logger.info("[CLOUD] Enviando matriz atualizada com a nova coluna...")
        resposta_update = aba.update(payload)

        logger.info(f"[CLOUD] Resposta bruta do Google Sheets: {resposta_update}")
        logger.info(f"[SUCESSO] Matriz quinzenal atualizada com sucesso ({coluna_hoje})!")

    except gspread.exceptions.WorksheetNotFound:
        logger.error(f"[ERRO] A aba '{NOME_ABA}' não foi encontrada na planilha '{NOME_PLANILHA}'.")
    except Exception as e:
        logger.error(f"[ERRO DETALHADO] Tipo: {type(e).__name__} | Mensagem: {str(e)}")