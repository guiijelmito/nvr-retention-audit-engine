from datetime import datetime
import os
from playwright.sync_api import sync_playwright
from config import USUARIO, SENHA, logger, PASTA_EVIDENCIAS as pasta_destino
from ticket_automation import criar_ticket_7lan

def capturar_print_nvr(ip_nvr, nome_escola, ano_alvo, mes_num):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        try:
            logger.info(f"[PLAYWRIGHT] Acessando http://{ip_nvr}...")
            page.goto(f"http://{ip_nvr}", timeout=60000)
            
            page.wait_for_selector('input.ant-input', timeout=40000)
            page.wait_for_timeout(2000)
            
            page.locator('input.ant-input').nth(0).fill(USUARIO)
            password_input = page.locator('input.ant-input').nth(1)
            password_input.fill(SENHA)
            password_input.press("Enter")
            
            logger.info("[PLAYWRIGHT] Aguardando carregamento da dashboard...")
            
            botao_pesquisar = page.locator('.ViewItem-CardItem-Title:has-text("PESQUISAR"), .ViewItem-CardItem-Title:has-text("SEARCH")')
            botao_pesquisar.wait_for(state="visible", timeout=20000)
            
            logger.info("[PLAYWRIGHT] Navegando para a aba de pesquisa...")
            botao_pesquisar.click()
            page.wait_for_timeout(3000)
            
            logger.info(f"[PLAYWRIGHT] Selecionando o ano {ano_alvo}...")
            page.locator('#rc_select_2').click(force=True)
            page.wait_for_timeout(1000)
            page.locator(f'.ant-select-item-option-content:text-is("{ano_alvo}")').click()
            page.wait_for_timeout(1500)
            
            meses_possiveis = {
                1: ["Jan"], 
                2: ["Fev", "Feb"], 
                3: ["Mar"], 
                4: ["Abr", "Apr"], 
                5: ["Mai", "May"], 
                6: ["Jun"], 
                7: ["Jul"], 
                8: ["Ago", "Aug"], 
                9: ["Set", "Sep"], 
                10: ["Out", "Oct"], 
                11: ["Nov"], 
                12: ["Dez", "Dec"]
            }
            
            candidatos = meses_possiveis.get(mes_num, ["Jan"])
            logger.info(f"[PLAYWRIGHT] Selecionando o mês correspondente (tentando: {candidatos})...")
            
            page.locator('#rc_select_3').click(force=True)
            page.wait_for_timeout(1000)
            
            clicou_mes = False
            for mes_txt in candidatos:
                try:
                    opt = page.locator(f'.ant-select-item-option-content:text-is("{mes_txt}")')
                    if opt.is_visible(timeout=1500):
                        opt.click()
                        clicou_mes = True
                        break
                except:
                    continue
            
            if not clicou_mes:
                page.locator(f'.ant-select-item-option-content:text-is("{candidatos[0]}")').click()
                
            page.wait_for_timeout(2000)
            
            os.makedirs(pasta_destino, exist_ok=True)

            data_hoje = datetime.now()
            data_str = data_hoje.strftime("%d-%m-%Y")

            nome_limpo = nome_escola.replace(" ", "_").replace(".", "").replace("ª", "a").replace("º", "o")
            nome_arquivo = os.path.join(pasta_destino, f"{nome_limpo}_{data_str}.png")
            page.screenshot(path=nome_arquivo, full_page=True)
            logger.info(f"[PLAYWRIGHT] Print do calendário mensal capturado com sucesso: {nome_arquivo}")
            
        except Exception as e:
            logger.error(f"[PLAYWRIGHT ERRO] Erro ao automatizar o NVR {ip_nvr}: {str(e)}")
            return None  # <--- Retorna None caso dê erro de acesso/timeout
        finally:
            browser.close()