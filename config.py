from pathlib import Path
import json
import os
import logging
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Pastas de armazenamento
EVIDENCIAS_DIR = BASE_DIR / "Evidencias_NVR_escolas"
LOGS_DIR = BASE_DIR / "logs"

# Garante que as pastas sejam criadas automaticamente se não existirem
EVIDENCIAS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

print(f"Pasta de Evidências: {EVIDENCIAS_DIR}")
print(f"Pasta de Logs: {LOGS_DIR}")

# Configuração do Sistema de Logs Persistentes
LOG_FILE = LOGS_DIR / "auditoria_NVR_escolas.log"
logger = logging.getLogger("VerthAudit")
logger.setLevel(logging.INFO)

if not logger.handlers:
    # Formato padrão para o log (Data/Hora, Nível, Mensagem)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%d/%m/%Y %H:%M:%S")
    
    # Handler para gravação persistente em arquivo
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Handler para exibição simultânea no console
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

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
PASTA_EVIDENCIAS = os.getenv("PASTA_EVIDENCIAS")

ESCOPOS = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

ARQUIVO_ESCOLAS = BASE_DIR / "data" / "escolas.json"
if ARQUIVO_ESCOLAS.exists():
    with open(ARQUIVO_ESCOLAS, "r", encoding="utf-8") as f:
        DADOS_ESCOLAS = json.load(f)
else:
    DADOS_ESCOLAS = {}

# Mantém compatibilidade com o formato legado {"nome": "ip"} e também lê
# unidades com estado persistido no formato {"nome": {"ip": ..., ...}}.
ESCOLAS = {}
for nome_escola, dados_escola in DADOS_ESCOLAS.items():
    ip_nvr = dados_escola.get("ip") if isinstance(dados_escola, dict) else dados_escola
    if isinstance(ip_nvr, str) and ip_nvr.strip():
        ESCOLAS[nome_escola] = ip_nvr
    else:
        logger.warning("[CONFIG] Unidade ignorada por não possuir IP válido: %s", nome_escola)
