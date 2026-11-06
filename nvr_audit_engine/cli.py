"""Ponto de entrada único: `python main.py [comando]`.

    python main.py                 # auditoria completa (padrão)
    python main.py auditar --pendentes   # só as escolas que falharam na última tentativa
    python main.py devtools        # validação interativa em ambiente controlado
    python main.py firmware --ip 10.0.0.5   # inventário de firmware (aceita --help)
"""

import argparse
import sys
from pathlib import Path

from nvr_audit_engine import config
from nvr_audit_engine.log import configurar_logging

COMANDOS = {
    "auditar": "auditoria completa: NVR, print, ticket 7LAN, estado e planilha (padrão);"
               " --pendentes roda só as que falharam na última tentativa",
    "devtools": "validação interativa de escolas selecionadas, com confirmações",
    "firmware": "inventário de modelo e firmware dos NVRs (somente leitura)",
}


def _preparar_execucao() -> Path:
    """Cria as pastas e liga o log; devolve logs/AAAA-MM-DD_HHMMSS/ da execução."""
    config.preparar_pastas()
    return configurar_logging(config.LOGS_DIR)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description="Motor de auditoria de retenção de gravação dos NVRs.",
        epilog="\n".join(f"  {nome:<9} {ajuda}" for nome, ajuda in COMANDOS.items()),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("comando", nargs="?", default="auditar", choices=COMANDOS)
    parser.add_argument("argumentos", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if args.comando == "firmware":
        from nvr_audit_engine.nvr import firmware

        return firmware.main(args.argumentos)

    somente_pendentes = args.comando == "auditar" and args.argumentos == ["--pendentes"]
    if args.argumentos and not somente_pendentes:
        parser.error(f"o comando '{args.comando}' não aceita argumentos: {args.argumentos}")

    pasta_execucao = _preparar_execucao()
    if args.comando == "devtools":
        from nvr_audit_engine import devtools

        return devtools.main()

    from nvr_audit_engine.auditoria.pipeline import auditar_retencao_nvr_com_cloud

    auditar_retencao_nvr_com_cloud(
        somente_pendentes=somente_pendentes, pasta_execucao=pasta_execucao
    )
    return 0
