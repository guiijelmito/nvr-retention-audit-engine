from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# Configurações de Acesso e Variáveis de Produção do ticket.7LAN
from config import SENHA_7LAN as senha, URL_7LAN as url, USUARIO_7LAN as usuario
from config import (
    CLIENTE_7LAN as cliente,
    PASTA_EVIDENCIAS as pasta_destino,
    SOLICITANTE_7LAN as solicitante,
)

load_dotenv()

def criar_ticket_7lan(nome_escola):
  """Função principal de automação de tickets no 7LAN para auditoria NVR.

  Recebe o nome da escola/unidade auditada, realiza o fluxo completo de
  abertura,
  anexo de evidências, apontamentos e fechamento do chamado.
  """
  with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)  # Mude para True se preferir rodar em segundo plano no futuro
    context = browser.new_context()
    page = context.new_page()

    try:
      print(f"[PROD] Iniciando processo para a unidade: {nome_escola}")

      print("[DEBUG] 1. Acessando a URL de login...")
      page.goto(url)

      print("[DEBUG] 2. Preenchendo credenciais...")
      page.fill("#sign_in_form_user_email", usuario)
      page.fill("#sign_in_form_user_password", senha)

      print("[DEBUG] 3. Clicando no botão de login...")
      page.click("button:has-text('Acessar conta'):visible")

      print("[DEBUG] 4. Aguardando o botão 'Abrir novo ticket' carregar...")
      botao_novo_ticket = page.locator("button:has-text('Abrir novo ticket')")
      botao_novo_ticket.wait_for(state="visible", timeout=20000)

      print("[DEBUG] 5. Clicando em 'Abrir novo ticket'...")
      botao_novo_ticket.click()
      print("[DEBUG] 6. Navegação para novo ticket acionada com sucesso!")

      # --- CAMPOS DO FORMULÁRIO PRINCIPAL ---
      print("[DEBUG] 7. Preenchendo Cliente...")
      page.fill("#service_desk_ticket_client_id", cliente)
      page.wait_for_timeout(1000)
      page.press("#service_desk_ticket_client_id", "Enter")

      print("[DEBUG] 8. Preenchendo Grupo de Equipamento...")
      page.click("#equipment_group_selected")
      page.wait_for_timeout(1000)
      page.press("#equipment_group_selected", "ArrowDown")
      page.wait_for_timeout(1000)
      page.press("#equipment_group_selected", "Enter")

      print("[DEBUG] 9. Preenchendo Mesa/Desk ('Solicitações')...")
      page.fill("#service_desk_ticket_desk_id", "Solicitações")
      page.wait_for_timeout(1000)
      page.press("#service_desk_ticket_desk_id", "Enter")

      # --- POP-UP DO CATÁLOGO DE SERVIÇOS ---
      print("[DEBUG] 10. Abrindo o pop-up do Catálogo de Serviços...")
      page.click("#services_catalogs")
      page.wait_for_selector(".ant-modal-content")

      print("[DEBUG] 12. Preenchendo ID do Catálogo...")
      catalogo_alvo = "Serviços de Monitoramento e Prevenção"
      page.fill("#services_catalogs_id", catalogo_alvo)
      page.wait_for_timeout(1000)
      page.press("#services_catalogs_id", "Enter")

      print("[DEBUG] 13. Preenchendo Área do Catálogo...")
      area_alvo = "CFTV e Segurança Eletrônica"
      page.fill("#services_catalogs_area_id", area_alvo)
      page.wait_for_timeout(1000)
      page.press("#services_catalogs_area_id", "Enter")

      print("[DEBUG] 13.1. Aguardando o campo 'Item' ser destravado em cascata...")
      page.wait_for_selector(
          "#services_catalogs_item_id:not([disabled])", timeout=10000
      )

      print("[DEBUG] 14. Preenchendo Item do Catálogo...")
      item_alvo = "Controle de acesso"
      page.fill("#services_catalogs_item_id", item_alvo)
      page.wait_for_timeout(1000)
      page.press("#services_catalogs_item_id", "Enter")

      print("[DEBUG] 15. Salvando o pop-up do Catálogo...")
      page.click(".ant-modal-footer button.ant-btn-primary:has-text('Salvar')")

      # --- SOLICITANTE, TÍTULO E DESCRIÇÃO ---
      print("[DEBUG] 16. Preenchendo Solicitante...")
      page.fill("#service_desk_ticket_requestor_name:visible", solicitante)
      page.wait_for_timeout(1000)
      page.press("#service_desk_ticket_requestor_name:visible", "Enter")

      print("[DEBUG] 17. Preenchendo Título do Ticket...")
      titulo_ticket = f"Controle de gravação - {nome_escola}"
      page.fill("#service_desk_ticket_title", titulo_ticket)
      page.wait_for_timeout(1000)

      print("[DEBUG] 18. Injetando HTML na descrição (Jodit Editor)...")
      page.locator(".jodit-wysiwyg").evaluate("""
          (node) => {
              node.innerHTML = '<p>Verificação de gravação NVR realizada.</p>';
              node.dispatchEvent(new Event('input', { bubbles: true }));
              node.dispatchEvent(new Event('change', { bubbles: true }));
          }
      """)
      page.wait_for_timeout(1000)

      print("[DEBUG] 19. Salvando o ticket principal...")
      botao_salvar_ticket = page.locator(
          "button.ant-btn-primary.buttons-open-new-ticket"
      )
      botao_salvar_ticket.click()

      print(
          "[DEBUG] 20. Aguardando redirecionamento para a página de"
          " listagem/ticket..."
      )
      page.wait_for_url("**/tickets**")

      # --- EVIDÊNCIA E ANEXO ---
      print("[DEBUG] 21. Reconstruindo o caminho da evidência localmente...")
      data_hoje = datetime.now()
      data_str = data_hoje.strftime("%d-%m-%Y")
      nome_limpo = (
          nome_escola.replace(" ", "_")
          .replace(".", "")
          .replace("ª", "a")
          .replace("º", "o")
      )
      caminho_evidencia = os.path.join(
          pasta_destino, f"{nome_limpo}_{data_str}.png"
      )

      print(
          f"[DEBUG] 22. Verificando se o arquivo existe em: {caminho_evidencia}"
      )
      if os.path.exists(caminho_evidencia):
        print(
            "[DEBUG] 23. Arquivo encontrado. Acionando seletor de arquivos para"
            " anexo..."
        )
        with page.expect_file_chooser() as fc_info:
          page.click("button:has-text('Anexar arquivo')")
        fc_info.value.set_files(caminho_evidencia)
        print(f"[ANEXO] Evidência anexada com sucesso: {caminho_evidencia}")
      else:
        print(
            f"[AVISO] Nenhum print encontrado em '{caminho_evidencia}'. Ticket"
            f" criado sem anexo."
        )

      # --- ABA DE APONTAMENTOS ---
      print("[DEBUG] 24. Clicando na aba 'Apontamentos'...")
      aba_apontamentos = page.locator(".ant-tabs-tab:has-text('Apontamentos')")
      aba_apontamentos.wait_for(state="visible", timeout=10000)
      aba_apontamentos.click()

      print("[DEBUG] 25. Clicando no botão '+ Apontamento'...")
      btn_novo_apontamento = page.locator(
          "button.ant-btn-primary:has-text('Apontamento')"
      )
      btn_novo_apontamento.wait_for(state="visible", timeout=10000)
      btn_novo_apontamento.click()

      print("[DEBUG] 26. Selecionando a opção 'N1'...")
      btn_n1 = page.locator("button:has-text('N1')")
      btn_n1.wait_for(state="visible", timeout=10000)
      btn_n1.click()

      print("[DEBUG] Alterando estágio e assumindo o ticket...")
      botao_assumir = page.locator(
          "button.ant-btn-primary:has-text('Alterar estágio e assumir ticket')"
      )
      botao_assumir.wait_for(state="visible", timeout=10000)
      botao_assumir.click()
      page.wait_for_timeout(1000)

      print("[DEBUG] 27. Preenchendo Data e Horários do Apontamento...")
      data_atual = datetime.now().strftime("%d/%m/%Y")

      # Bula o 'readonly' do campo de data do Ant Design via JS
      page.locator("#newAppointment_open").evaluate(
          f"""(node) => {{
              node.value = '{data_atual}';
              node.dispatchEvent(new Event('input', {{ bubbles: true }}));
              node.dispatchEvent(new Event('change', {{ bubbles: true }}));
          }}"""
      )
      page.wait_for_timeout(500)

      agora = datetime.now()
      hora_inicio = agora.strftime("%H:%M")
      hora_fim = (agora + timedelta(minutes=2)).strftime("%H:%M")

      page.fill("#newAppointment_init_time", hora_inicio)
      page.fill("#newAppointment_end_time", hora_fim)
      page.wait_for_timeout(500)

      print("[DEBUG] 28. Preenchendo descrição do apontamento...")
      texto_apontamento = "Verificado a gravação das câmeras no NVR.\nOk."
      page.fill("#newAppointment_description", texto_apontamento)
      page.wait_for_timeout(500)

      print("[DEBUG] 29. Clicando em 'Salvar e fechar ticket'...")
      page.click("button:has-text('Salvar e fechar ticket')")

      print(
          f"\n[SUCESSO] OS aberta e concluída para a unidade: {nome_escola}!"
      )

    except Exception as e:
      print(f"\n[ERRO CRÍTICO] Falha capturada na execução para {nome_escola}!")
      print(f"Detalhes do Erro: {e}")

      caminho_erro_print = f"erro_snapshot_{nome_limpo}.png"
      page.screenshot(path=caminho_erro_print)
      print(f"[DEBUG] Screenshot de erro salvo em '{caminho_erro_print}'.\n")

    finally:
      print("[DEBUG] 30. Fechando navegador.")
      page.wait_for_timeout(3000)
      browser.close()


if __name__ == "__main__":
  # Exemplo de chamada direta para teste unitário do módulo de produção
  escola_teste_prod = "Escola Municipal Exemplo Produção"
  print(f"=== TESTANDO MÓDULO DE PRODUÇÃO PARA: {escola_teste_prod} ===\n")
  criar_ticket_7lan(escola_teste_prod)