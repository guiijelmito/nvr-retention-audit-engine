# NVR Retention & Continuous Recording Audit Engine

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
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

- **Language:** Python 3.11+
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

Para desenvolver (testes e lint), use `pip install -r requirements-dev.txt`.

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

Todos os comandos passam por `main.py`:

```bash
python main.py              # auditoria completa (NVR, print, ticket 7LAN, estado e planilha)
python main.py devtools     # validação interativa de escolas selecionadas, com confirmações
python main.py firmware     # inventário de modelo e firmware dos NVRs (somente leitura)
python main.py --help
```

`python -m nvr_audit_engine` é equivalente a `python main.py`.

### Testes

```bash
python -m pytest
ruff check .
```

Os testes não acessam NVR, 7LAN nem Google: as respostas são simuladas. O GitHub Actions roda os dois comandos a cada push.

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

Uma unidade aprovada é pulada até sua próxima data de auditoria, registrada em `data/escolas.json`. A aprovação exige conectividade do NVR, print capturado e ticket confirmado no 7LAN; a janela padrão de nova auditoria é de 15 dias. Consulte `docs/DIARIO_ESTADO_ESCOLAS.md` para o formato e o fluxo de estado.

Para apenas reconstruir sem iniciar uma auditoria:

```powershell
docker compose build
```

Para inventariar modelos e firmwares:

```powershell
docker compose run --build --rm auditor python main.py firmware
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

### Firmware inventory

Query every NVR in `data/escolas.json` over the Dahua CGI API (`magicBox.cgi`, Digest auth with Basic fallback) and report model, firmware version and build date, grouped by firmware:

```bash
python main.py firmware                    # data/escolas.json
python main.py firmware --ip 10.0.0.5      # single NVR
python main.py firmware --json firmware.json
```

The CSV report is written to `relatorios_firmware/` (git-ignored). It falls back to Basic auth on older firmware, queries NVRs in parallel and groups the output by firmware version to target automations. Options: `--esquema https` (or `NVR_SCHEME`), `--porta`, `--inseguro` for self-signed certificates.

---

## Project Structure

```
├── main.py                         # Ponto de entrada: python main.py [auditar|devtools|firmware]
├── nvr_audit_engine/
│   ├── cli.py                      # Comandos e preparação (pastas, log)
│   ├── config.py                   # .env, caminhos e nomes da planilha (sem efeitos no import)
│   ├── log.py                      # Logger da aplicação
│   ├── escolas.py                  # data/escolas.json: lista, agenda de 15 dias e aprovação
│   ├── evidencias.py               # Nome do print de evidência
│   ├── devtools.py                 # Validação interativa em ambiente controlado
│   ├── auditoria/
│   │   ├── retencao.py             # Regra de dias contínuos (tolerância de 3 dias vazios)
│   │   └── pipeline.py             # Orquestração: NVR → contagem → print → ticket → estado → planilha
│   ├── nvr/
│   │   ├── busca_gravacoes.py      # API CGI mediaFileFind (contrato de compatibilidade)
│   │   ├── firmware.py             # Inventário via magicBox.cgi
│   │   └── web/                    # Interface web do NVR via Playwright
│   │       ├── captura.py          # Fluxo do print do calendário
│   │       ├── calendario.py       # Seleção de ano/mês
│   │       ├── localizadores.py    # Variantes de seletores por firmware
│   │       └── diagnostico.py      # Diagnóstico de tela em falhas
│   └── integracoes/
│       ├── lan7.py                 # Chamado no helpdesk 7LAN
│       └── sheets.py               # Google Sheets
├── tests/                          # Espelha o pacote (tests/nvr, tests/auditoria, ...)
├── docs/
│   ├── ARQUITETURA.md              # Camadas, fluxo e onde colocar código novo
│   ├── DIARIO_COMPATIBILIDADE_NVR.md
│   └── DIARIO_ESTADO_ESCOLAS.md
├── data/escolas.json               # Escolas, IPs e estado da auditoria (git-ignored)
├── credenciais.json                # Conta de serviço Google (git-ignored)
├── .env / .env.example             # Credenciais (git-ignored) / modelo
├── pyproject.toml                  # Metadados, pytest e ruff
├── requirements.txt                # Dependências fixas (usadas pelo Docker)
├── requirements-dev.txt            # pytest e ruff
├── Dockerfile / compose.yaml       # Imagem portátil e execução com dados persistidos
└── .github/workflows/testes.yml    # CI: ruff + pytest
```

Consulte `docs/ARQUITETURA.md` antes de adicionar um módulo novo.

---

## License

This project is proprietary software developed for **Verth Tecnologia**.
