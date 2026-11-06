"""Configuração lida do ambiente (.env) e caminhos do projeto.

Importar este módulo não cria pastas nem imprime nada; quem executa a
aplicação chama `preparar_pastas()`.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

# Pastas de armazenamento
LOGS_DIR = BASE_DIR / "logs"

# Configurações de Acesso

# user e password do NVR
USUARIO = os.getenv("NVR_USUARIO")
SENHA = os.getenv("NVR_SENHA")

# user, password, URL e cliente(ticket) do 7LAN
USUARIO_7LAN = os.getenv("LAN7_USER")
SENHA_7LAN = os.getenv("LAN7_PASS")
URL_7LAN = os.getenv("LAN7_URL")
CLIENTE_7LAN = os.getenv("LAN7_CLIENTE")
SOLICITANTE_7LAN = os.getenv("LAN7_SOLICITANTE")

_credenciais_google_configuradas = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
ARQUIVO_CREDENCIAIS = (
    Path(_credenciais_google_configuradas).expanduser()
    if _credenciais_google_configuradas
    else BASE_DIR / "credenciais.json"
)
NOME_PLANILHA = "Gravações escolas 2026"
NOME_ABA = "Gravações Quinzenais 2026"
# Sem PASTA_EVIDENCIAS no .env, a captura falhava em todas as escolas (os.makedirs(None)).
PASTA_EVIDENCIAS = os.getenv("PASTA_EVIDENCIAS") or str(BASE_DIR / "Evidencias_NVR_escolas")

ESCOPOS = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

ARQUIVO_ESCOLAS = BASE_DIR / "data" / "escolas.json"

# Navegador do print e do 7LAN: headless por padrão (servidor e Docker não têm janela).
# PLAYWRIGHT_HEADLESS=false abre o navegador; o devtools sempre abre.
HEADLESS = os.getenv("PLAYWRIGHT_HEADLESS", "true").strip().lower() not in {"0", "false", "no", "off"}


def preparar_pastas() -> None:
    """Garante que as pastas sejam criadas automaticamente se não existirem."""
    Path(PASTA_EVIDENCIAS).mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Pasta de Evidências: {PASTA_EVIDENCIAS}")
    print(f"Pasta de Logs: {LOGS_DIR}")
