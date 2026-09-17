from datetime import datetime, timedelta
import os
import time
from requests.auth import HTTPDigestAuth
import requests
from config import USUARIO, SENHA, ESCOLAS_TESTE, logger
from nvr_capture import capturar_print_nvr
from cloud_sync import enviar_para_google_sheets
from ticket_automation import criar_ticket_7lan

def auditar_retencao_nvr_com_cloud():
    LIMITE_DIAS = 730
    
    try:
        largura_terminal = os.get_terminal_size().columns
    except (OSError, AttributeError):
        largura_terminal = 120

    titulo = " AUDITORIA INTELIGENTE DE GRAVAÇÕES ESCOLARES - VERTH TECNOLOGIAS "
    print("\n" + titulo.center(largura_terminal, "="))

    qtd_canais = 1
    resultados_para_planilha = []

    for nome_escola, nvr_ip in ESCOLAS_TESTE.items():
        logger.info(f"[UNIDADE] Processando unidade: {nome_escola} - Endereço IP: ({nvr_ip})")
        total_dias_escola = 0

        # **1. Pre-flight check**: Valida conectividade real antes de varrer o histórico
        nvr_offline = False
        sessao_teste = requests.Session()
        sessao_teste.auth = HTTPDigestAuth(USUARIO, SENHA)

        for tentativa_conexao in range(1, 3):
            try:
                resp_teste = sessao_teste.get(f"http://{nvr_ip}/cgi-bin/mediaFileFind.cgi?action=factory.create", timeout=8)
                break
            except (requests.exceptions.ConnectionError, requests.exceptions.ConnectTimeout):
                if tentativa_conexao == 2:
                    nvr_offline = True
                else:
                    time.sleep(2)
            except Exception:
                if tentativa_conexao == 2:
                    nvr_offline = True
                else:
                    time.sleep(2)
        sessao_teste.close()

        if nvr_offline:
            logger.warning(f"  [ALERTA] {nome_escola} ({nvr_ip}): NVR inacessível na rede. Marcando 'Verificar no local'.")
            resultados_para_planilha.append({
                "Escola": nome_escola,
                "IP do NVR": nvr_ip,
                "Dias Contínuos Válidos": "Verificar no local",
                "Gravação mais antiga": "N/A",
            })
            continue

        for canal in range(1, qtd_canais + 1):
            dias_continuos = 0
            dias_vazios_consecutivos = 0
            LIMITE_BURACO = 3
            fim_do_hd = False
            data_fim_hd = "N/A"

            sessao = requests.Session()
            sessao.auth = HTTPDigestAuth(USUARIO, SENHA)
            url_base = f"http://{nvr_ip}/cgi-bin/mediaFileFind.cgi"
            falhas_consecutivas_token = 0

            # **Varredura Sequencial Rigorosa Dia a Dia** (Garantia absoluta de Non-Stop)
            for dias_atras in range(1, LIMITE_DIAS + 1):
                if fim_do_hd:
                    break

                data_alvo = datetime.now() - timedelta(days=dias_atras)
                data_str = data_alvo.strftime("%Y-%m-%d")
                sucesso_requisicao = False
                encontrou_arquivo = False

                for tentativa in range(1, 4):
                    token = None
                    try:
                        resp_criar = sessao.get(f"{url_base}?action=factory.create", timeout=12)
                        if "result=" not in resp_criar.text:
                            time.sleep(1.0)
                            continue

                        token = resp_criar.text.split("result=")[1].strip()
                        
                        url_buscar = (
                            f"{url_base}?action=findFile&object={token}"
                            f"&condition.Channel={canal}"
                            f"&condition.StartTime={data_str}%2000:00:00"
                            f"&condition.EndTime={data_str}%2023:59:59"
                            f"&condition.Types[0]=dav"
                        )
                        sessao.get(url_buscar, timeout=12)

                        url_proximo = f"{url_base}?action=findNextFile&object={token}&count=1"
                        resp_proximo = sessao.get(url_proximo, timeout=12)

                        sucesso_requisicao = True
                        if "found=0" not in resp_proximo.text and (
                            "items[0]" in resp_proximo.text or "file" in resp_proximo.text.lower()
                        ):
                            encontrou_arquivo = True
                        break
                    except Exception:
                        time.sleep(1.5)
                    finally:
                        if token:
                            try:
                                sessao.get(f"{url_base}?action=close&object={token}", timeout=10)
                            except Exception:
                                pass

                if not sucesso_requisicao:
                    falhas_consecutivas_token += 1
                    if falhas_consecutivas_token > 10:
                        logger.warning(f"  [ALERTA] {nome_escola}: Muitas falhas consecutivas de API. Abortando unidade.")
                        break
                    continue
                else:
                    falhas_consecutivas_token = 0

                # Validação de Falso Vazio (Garante robustez caso o arquivo esteja fragmentado)
                if not encontrou_arquivo:
                    falso_vazio_detectado = False
                    token_c2 = None
                    try:
                        resp_c2 = sessao.get(f"{url_base}?action=factory.create", timeout=12)
                        if "result=" in resp_c2.text:
                            token_c2 = resp_c2.text.split("result=")[1].strip()
                            url_b2 = (
                                f"{url_base}?action=findFile&object={token_c2}"
                                f"&condition.Channel={canal}"
                                f"&condition.StartTime={data_str}%2000:00:00"
                                f"&condition.EndTime={data_str}%2023:59:59"
                                f"&condition.Types[0]=dav"
                            )
                            sessao.get(url_b2, timeout=12)
                            resp_p2 = sessao.get(f"{url_base}?action=findNextFile&object={token_c2}&count=1", timeout=12)

                            if "found=0" not in resp_p2.text and (
                                "items[0]" in resp_p2.text or "file" in resp_p2.text.lower()
                            ):
                                falso_vazio_detectado = True
                    except Exception:
                        pass
                    finally:
                        if token_c2:
                            try:
                                sessao.get(f"{url_base}?action=close&object={token_c2}", timeout=10)
                            except Exception:
                                pass

                    if falso_vazio_detectado:
                        dias_vazios_consecutivos = 0
                        dias_continuos += 1
                    else:
                        dias_vazios_consecutivos += 1
                        if dias_vazios_consecutivos >= LIMITE_BURACO:
                            # Ajustado para refletir o último dia contínuo correto sem erros de tipo
                            data_objeto = datetime.now() - timedelta(days=(dias_atras - dias_vazios_consecutivos))
                            data_fim_hd = data_objeto.strftime("%d/%m/%Y")
                            fim_do_hd = True
                            break
                else:
                    dias_vazios_consecutivos = 0
                    dias_continuos += 1

            sessao.close()
            total_dias_escola += dias_continuos

        valor_dias_celula = "Verificar no local" if total_dias_escola == 0 else total_dias_escola

        resultados_para_planilha.append({
            "Escola": nome_escola,
            "IP do NVR": nvr_ip,
            "Dias Contínuos Válidos": valor_dias_celula,
            "Gravação mais antiga": data_fim_hd,
        })

        if isinstance(valor_dias_celula, int):
            logger.info(f"  [OK] {nome_escola}: {valor_dias_celula} dias contínuos computados. (Último dia válido: {data_fim_hd})")
            
            try:
                dt_fim = datetime.strptime(data_fim_hd, "%d/%m/%Y")
                ano_str = dt_fim.strftime("%Y")
                mes_num = dt_fim.month
                    
                logger.info(f"  [EVIDÊNCIA] Gerando print do calendário para {nome_escola} (Mês {mes_num}/{ano_str})...")
                
                capturar_print_nvr(nvr_ip, nome_escola, ano_str, mes_num)
                criar_ticket_7lan(nome_escola)
            except Exception as e:
                logger.error(f"[ERRO EVIDÊNCIA] Falha ao processar datas para o print: {e}")
        else:
            logger.warning(f"  [ALERTA] {nome_escola}: {valor_dias_celula}")

        print("=" * largura_terminal + "\n")

    if resultados_para_planilha:
        enviar_para_google_sheets(resultados_para_planilha)