# NVR Retention & Continuous Recording Audit Engine

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Playwright](https://img.shields.io/badge/Playwright-Automation-green.svg)](https://playwright.dev/python/)
[![Status](https://img.shields.io/badge/Status-In%20Development-yellow.svg)]()

Automated enterprise-grade solution engineered to audit multi-channel Network Video Recorders (NVRs) across educational facilities, ensuring strict compliance with non-stop (continuous) recording policies, hardware degradation detection, and automated cloud reporting.

---

## Key Features

- **Pre-Flight Connectivity Check:** Fast-fails unreachable NVR units via lightweight HTTP tests before executing heavy historical scans.
- **Strict Daily Sequential Non-Stop Verification:** Iterates linearly up to 730 days backwards with multi-layered validations to eliminate false positives commonly introduced by wide-block heuristics.
- **Session & Token Leak Mitigation:** Implements rigorous `try...finally` blocks ensuring immediate token closure (`action=close`) on proprietary NVR firmware APIs, protecting device resources.
- **Automated Visual Evidence Capture:** Uses Playwright in headless mode to securely interact with NVR web GUIs, automate authentication, navigate search menus, select historical calendar periods, and snapshot full-page compliance proofs.
- **Cloud Integration & Matrix Sync:** Dynamically structures audit outputs into horizontal matrices and syncs compliance data with Google Sheets via `gspread` and a service account.
- **Automated Ticket Creation:** Opens, documents, and closes service tickets on the 7LAN helpdesk for each audited unit via Playwright automation.
- **Environment-Driven Configuration:** Decouples environment secrets using `python-dotenv` while externalizing unit topologies and authentication credentials.

---

## Tech Stack

- **Language:** Python 3.10+
- **Automation:** Playwright for Python
- **HTTP / Auth:** `requests` with HTTP Digest Authentication (NVR proprietary APIs)
- **Cloud Sync:** `gspread`, `google-auth` (Google Sheets)
- **Data Handling:** `pandas`
- **Environment Management:** `python-dotenv`

---

## Installation & Setup

### 1. Clone the repository

```bash
git clone <repository-url>
cd <repository-name>
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 4. Configure environment variables

Create a `.env` file in the root directory based on `.env.example`:

```env
NVR_USUARIO=
NVR_SENHA=
LAN7_USER=
LAN7_PASS=
LAN7_URL=
LAN7_CLIENTE=
LAN7_SOLICITANTE=
PASTA_EVIDENCIAS=
```

### 5. Arquivos locais de configuração

Mantenha os seguintes arquivos no projeto:

- `data/escolas.json` — mapa das unidades, IPs dos NVRs e estado persistido da auditoria.
- `credenciais.json` — credenciais da conta de serviço Google, ignoradas pelo Git.

---

## Usage

Run the full audit pipeline:

```bash
python main.py
```

## Executar com Docker (Windows)

Docker empacota Python, bibliotecas e Chromium para que a aplicação não dependa de uma instalação local de Python. **O PC ainda precisa de um runtime Docker instalado e iniciado.** No Windows, Docker Desktop normalmente usa WSL 2; habilitar esse recurso pela primeira vez pode exigir privilégios administrativos e reinicialização. Portanto, Docker não elimina essa necessidade no PC da GCM que está sem WSL e não pode reiniciar agora. Consulte os requisitos atuais na [documentação do Docker Desktop para Windows](https://docs.docker.com/desktop/setup/install/windows-install/).

### Preparar o computador

Instale e inicie o Docker Desktop em um computador Windows compatível. Abra o PowerShell na pasta do projeto e confirme que o mecanismo está ativo:

```powershell
docker version
docker compose version
```

Se o comando `docker version` mostrar apenas a parte Client e erro na parte Server, o Docker Desktop ainda não está iniciado ou o mecanismo não está disponível.

### Preparar os arquivos locais

O container não inclui dados locais nem segredos na imagem. Antes de executar, mantenha na raiz do projeto:

- `.env` com credenciais dos NVRs, 7LAN e demais integrações;
- `data/escolas.json` com o mapa, IPs e estado das unidades;
- `credenciais.json` com a conta de serviço do Google Sheets, se a sincronização estiver habilitada.

O Python local procura `credenciais.json` na raiz do projeto. No Docker Compose, ele é montado em `/app/credenciais.json`. Se a chave estiver em outro local, configure `GOOGLE_APPLICATION_CREDENTIALS` com o caminho absoluto do arquivo.

Crie as pastas `data`, `logs` e `Evidencias_NVR_escolas` se ainda não existirem. O Compose monta as credenciais como somente leitura e persiste o estado, os logs e as evidências no computador host.

### Construir e executar

Na primeira execução, o Docker baixa a imagem Python e instala as dependências do Chromium; isso exige acesso à internet e pode levar alguns minutos. Depois, execute:

```powershell
docker compose run --build --rm auditor
```

`run` executa a auditoria uma vez, `--rm` remove o container ao final e `--build` reconstrói a imagem quando necessário. Os resultados ficam em `logs` e `Evidencias_NVR_escolas` no host. O container usa Chromium headless para a automação do 7LAN.

Uma unidade aprovada é pulada até sua próxima data de auditoria, registrada em `data/escolas.json`. A aprovação exige conectividade do NVR, print capturado e ticket confirmado no 7LAN; a janela padrão de nova auditoria é de 15 dias. Consulte `diario.md` para o formato e o fluxo de estado.

Para apenas reconstruir sem iniciar uma auditoria:

```powershell
docker compose build
```

Para inventariar modelos e firmwares:

```powershell
docker compose run --build --rm auditor python inventario_nvr.py
```

### Manutenção da imagem

- Ao mudar dependências, atualize `requirements.txt` e reconstrua com `docker compose build --no-cache`.
- Ao atualizar Playwright, mantenha a versão em `Dockerfile`/`compose.yaml` alinhada e reconstrua. A versão do Playwright deve combinar com os binários de navegador instalados na imagem, conforme a [documentação do Playwright para Docker](https://playwright.dev/python/docs/docker).
- Mudanças no código Python entram na imagem na próxima construção; use `docker compose run --build --rm auditor` para executar a versão atual.
- Para inspecionar logs: `Get-Content .\logs\auditoria_NVR_escolas.log -Tail 100`.
- Para remover containers parados: `docker compose down`. Para também apagar resultados locais, remova manualmente as pastas de logs/evidências depois de guardar o que precisar.

### Levar a imagem para outro computador

É possível construir em uma máquina com internet e transferir a imagem:

```powershell
docker compose build
docker save -o verth-nvr-audit.tar verth-nvr-audit:local
```

Copie `verth-nvr-audit.tar` para o computador de destino e, nele, carregue e execute:

```powershell
docker load -i verth-nvr-audit.tar
docker compose run --no-build --rm auditor
```

O computador de destino ainda precisa do Docker Engine/Desktop, dos arquivos locais de configuração e acesso de rede aos NVRs. Para a estação da GCM sem Docker/WSL e sem possibilidade de reinicialização, use temporariamente outra máquina já preparada ou aguarde a instalação do runtime; a imagem sozinha não roda diretamente no Windows.

---

## Project Structure

```
├── main.py                # Application entry point
├── nvr_audit.py            # Core audit engine: connectivity checks and daily non-stop verification
├── nvr_capture.py           # Playwright module for GUI interaction and evidence screenshots
├── cloud_sync.py             # Google Sheets synchronization and report updating
├── ticket_automation.py       # 7LAN service desk ticket automation
├── inventario_nvr.py          # Inventário de modelo e firmware Dahua
├── Dockerfile                 # Imagem portátil da aplicação e do Chromium
├── compose.yaml               # Execução com configuração e dados persistidos
├── .dockerignore              # Evita enviar segredos/dados locais ao build
├── config.py                   # Environment loading, path resolution, and logging setup
├── data/escolas.json            # School units, NVR IPs, and persisted audit state
├── credenciais.json              # Google service account credentials (git-ignored)
├── requirements.txt               # Explicit dependencies manifest
├── .env                             # Sensitive credentials (git-ignored)
├── .env.example                      # Template for environment variables
├── .gitignore                         # Excludes venv, .env, credentials, and local data files
└── README.md                           # Project documentation
```

---

## License

This project is proprietary software developed for **Verth Tecnologia**.
