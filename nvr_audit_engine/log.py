"""Logger da aplicação. Os handlers só são ligados por quem executa (CLI)."""

import logging
from pathlib import Path

NOME_LOGGER = "VerthAudit"
NOME_ARQUIVO_LOG = "auditoria_NVR_escolas.log"

logger = logging.getLogger(NOME_LOGGER)
logger.setLevel(logging.INFO)


def configurar_logging(pasta_logs: Path) -> None:
    """Grava em <pasta_logs>/auditoria_NVR_escolas.log e mostra no console."""
    if logger.handlers:
        return

    # Formato padrão para o log (Data/Hora, Nível, Mensagem)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%d/%m/%Y %H:%M:%S"
    )

    # Handler para gravação persistente em arquivo
    file_handler = logging.FileHandler(pasta_logs / NOME_ARQUIVO_LOG, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Handler para exibição simultânea no console
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
