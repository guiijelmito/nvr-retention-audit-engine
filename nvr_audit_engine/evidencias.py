"""Nome e caminho dos prints de evidência (<escola>_<dd-mm-aaaa>.png).

Compartilhado pela captura do calendário e pelo anexo do ticket, que
precisam chegar ao mesmo arquivo.
"""

import os
from datetime import datetime


def nome_seguro(nome_escola: str) -> str:
    return (
        nome_escola.replace(" ", "_")
        .replace(".", "")
        .replace("ª", "a")
        .replace("º", "o")
    )


def caminho_evidencia(pasta: str, nome_escola: str, data: datetime) -> str:
    return os.path.join(pasta, f"{nome_seguro(nome_escola)}_{data.strftime('%d-%m-%Y')}.png")
