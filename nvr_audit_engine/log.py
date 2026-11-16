"""Logger da aplicação. Os handlers só são ligados por quem executa (CLI)."""

import logging
from datetime import datetime
from pathlib import Path

NOME_LOGGER = "VerthAudit"
NOME_ARQUIVO_LOG = "execucao.log"

logger = logging.getLogger(NOME_LOGGER)
logger.setLevel(logging.INFO)


def configurar_logging(pasta_logs: Path) -> Path:
    """Cria <pasta_logs>/AAAA-MM-DD_HHMMSS/execucao.log e mostra no console.

    Devolve a pasta da execução, onde também ficam o resumo e os prints de erro.
    """
    if logger.handlers:
        return pasta_execucao()

    pasta = pasta_logs / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    pasta.mkdir(parents=True, exist_ok=True)

    # Formato padrão para o log (Data/Hora, Nível, Mensagem)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%d/%m/%Y %H:%M:%S"
    )

    # Handler para gravação persistente em arquivo
    file_handler = logging.FileHandler(pasta / NOME_ARQUIVO_LOG, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Handler para exibição simultânea no console
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    return pasta


def pasta_execucao() -> Path | None:
    """Pasta da execução atual, ou None quando o log em arquivo não foi ligado."""
    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler):
            return Path(handler.baseFilename).parent
    return None
