# NVR Retention & Continuous Recording Audit Engine (English Version)

Automated enterprise-grade solution engineered to audit multi-channel Network Video Recorders (NVRs) across educational facilities, ensuring strict compliance with non-stop (continuous) recording policies, hardware degradation detection, and automated cloud reporting.

## **Core Architecture & Engineering Highlights**

* **Pre-Flight Connectivity Check**: Fast-fails unreachable NVR units via lightweight socket and HTTP tests before executing heavy historical scans.
* **Strict Daily Sequential Non-Stop Verification**: Iterates linearly up to 730 days backwards with multi-layered validations to eliminate false positives commonly introduced by wide-block heuristics.
* **Session & Token Leak Mitigation**: Implements rigorous `try...finally` blocks ensuring immediate token closure (`action=close`) on proprietary NVR firmware APIs, protecting device resources.
* **Automated Visual Evidence Capture**: Utilizes **Playwright** in headless mode to securely interact with NVR web GUIs, automate authentication, navigate search menus, select historical calendar periods, and snapshot full-page compliance proofs.
* **Cloud Integration & Matrix Sync**: Dynamically structures audit outputs into horizontal matrices and syncs compliance data with **Google Sheets** via `gspread` and service accounts.
* **Environment-Driven Configuration**: Decouples environment secrets using `python-dotenv` while externalizing unit topologies and authentication credentials.

## **Project Structure & Component Files**

* `main.py`: Clean application entry point.
* `nvr_audit.py`: Core audit engine handling digest authentication sessions, HTTP requests, and daily non-stop algorithms.
* `nvr_capture.py`: Browser automation module for GUI interaction and visual proof generation.
* `cloud_sync.py`: Google Sheets synchronization, DataFrame manipulation, and report updating.
* `config.py`: Centralized environment loading, path resolution, and persistent dual-handler logging setup.
* `escolas.json`: External mapping file containing the dictionary of school units and their respective IP addresses, allowing dynamic updates to the audit scope without modifying core logic.
* `credenciais.json`: Google Cloud Service Account credentials file required for secure authentication and automated synchronization with Google Sheets.
* `requirements.txt`: Explicit dependencies manifest.

## **Getting Started & Setup**

1. **Prerequisites**: Ensure Python 3.10+ is installed and fetch Playwright binaries using `playwright install`.
2. **Installation**: Clone the repository and install required packages via `pip install -r requirements.txt`.
3. **Environment Configuration**: Create a `.env` file in the root directory based on `.env.example` containing your `NVR_USUARIO` and `NVR_SENHA`[cite: 5, 6]. Place your `escolas.json` and `credenciais.json` in the root directory.
4. **Execution**: Run the pipeline directly via `python main.py`.

---
---

# NVR Retention & Continuous Recording Audit Engine

Solução automatizada de nível corporativo projetada para auditar Gravadores de Vídeo em Rede (NVRs) multi-canal em unidades educacionais, garantindo conformidade estrita com políticas de gravação contínua (*non-stop*), detecção de degradação de hardware e relatórios automatizados em nuvem.

---

## **Destaques de Arquitetura & Engenharia**

* **Verificação de Conectividade Pré-Voo (*Pre-Flight Check*)**: Interrompe rapidamente unidades NVR inacessíveis por meio de testes leves de socket e HTTP antes de executar varreduras históricas pesadas.
* **Verificação Estrita Sequencial Diária Non-Stop**: Itera linearmente até 730 dias para o passado com validações em múltiplas camadas para eliminar falsos positivos comumente introduzidos por heurísticas de blocos amplos.
* **Mitigação de Vazamento de Sessão e Tokens**: Implementa blocos `try...finally` rigorosos que garantem o fechamento imediato de tokens (`action=close`) nas APIs proprietárias de firmware do NVR, protegendo os recursos do dispositivo.
* **Captura Automatizada de Evidências Visuais**: Utiliza o **Playwright** em modo *headless* para interagir de forma segura com as GUIs web dos NVRs, automatizar a autenticação, navegar pelos menus de pesquisa, selecionar períodos históricos no calendário e capturar provas de conformidade em tela cheia.
* **Integração em Nuvem e Sincronização de Matrizes**: Estrutura dinamicamente os resultados da auditoria em matrizes horizontais e sincroniza os dados de conformidade com o **Google Sheets** via `gspread` e contas de serviço.
* **Configuração Baseada em Ambiente**: Desacopla segredos de ambiente usando `python-dotenv` enquanto externaliza topologias de unidades e credenciais de autenticação.

## **Estrutura do Projeto & Componentes**

* `main.py`: Ponto de entrada limpo da aplicação.
* `nvr_audit.py`: Motor principal de auditoria que gerencia sessões de autenticação Digest, requisições HTTP e algoritmos diários *non-stop*.
* `nvr_capture.py`: Módulo de automação de navegador para interação com a GUI e geração de provas visuais.
* `cloud_sync.py`: Sincronização com o Google Sheets, manipulação de DataFrame e atualização de relatórios.
* `config.py`: Carregamento centralizado de ambiente, resolução de caminhos e configuração persistente de logs com múltiplos *handlers*.
* `escolas.json`: Arquivo de mapeamento externo contendo o dicionário de unidades escolares e seus respectivos endereços IP, permitindo atualizações dinâmicas no escopo da auditoria sem modificar a lógica principal.
* `credenciais.json`: Arquivo de credenciais da Conta de Serviço do Google Cloud necessário para autenticação segura e sincronização automatizada com o Google Sheets.
* `requirements.txt`: Manifesto explícito de dependências.

## **Guia de Configuração e Execução**

1. **Pré-requisitos**: Certifique-se de que o Python 3.10+ está instalado e obtenha os binários do Playwright executando `playwright install`.
2. **Instalação**: Clone o repositório e instale os pacotes necessários via `pip install -r requirements.txt`.
3. **Configuração de Ambiente**: Crie um arquivo `.env` no diretório raiz baseado no `.env.example` contendo seu `NVR_USUARIO` e `NVR_SENHA`. Posicione seus arquivos `escolas.json` e `credenciais.json` no diretório raiz.
4. **Execução**: Execute o pipeline diretamente via `python main.py`.




