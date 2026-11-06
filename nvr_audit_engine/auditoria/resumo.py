"""Resumo de uma execução: resumo.csv, resumo.json e resumo.md na pasta do log.

Gerado só a partir dos resultados da execução, do relatório de firmware mais
recente (se existir) e do resumo.json da execução anterior.
"""

import csv
import json
from collections import Counter
from pathlib import Path

COLUNAS = [
    "escola", "ip", "firmware", "resultado", "dias_continuos", "gravacao_mais_antiga",
    "print_ok", "os_criada", "os_fechada", "motivo_falha", "tentativas", "duracao_s",
]

TOTAIS = {
    "aprovada": "Aprovadas",
    "sem_rede": "Sem rede",
    "verificar_no_local": "Verificar no local",
    "incompleta": "Incompletas",
    "falha_print": "Falha de print",
    "falha_os": "Falha de OS",
}


def firmware_por_ip(pasta_relatorios: Path) -> dict[str, str]:
    """{ip: versão} do CSV mais recente de `python main.py firmware`."""
    relatorios = sorted(pasta_relatorios.glob("firmware_nvrs_*.csv"))
    if not relatorios:
        return {}
    with open(relatorios[-1], encoding="utf-8-sig", newline="") as arquivo:
        return {
            linha["ip"]: linha["versao_firmware"]
            for linha in csv.DictReader(arquivo, delimiter=";")
            if linha.get("versao_firmware")
        }


def resumo_anterior(pasta_logs: Path, pasta_atual: Path) -> dict | None:
    """resumo.json da execução mais recente antes da atual, se houver."""
    anteriores = sorted(
        p for p in pasta_logs.glob("*/resumo.json") if p.parent.name < pasta_atual.name
    )
    if not anteriores:
        return None
    return json.loads(anteriores[-1].read_text(encoding="utf-8"))


def montar_resumo(
    linhas: list[dict], anterior: dict | None, offline_persistentes: dict[str, int]
) -> dict:
    """Totais, mudanças desde a execução anterior e NVRs offline persistentes."""
    contagem = Counter(linha["resultado"] for linha in linhas)
    totais = {rotulo: contagem.pop(chave, 0) for chave, rotulo in TOTAIS.items()}
    totais["Outros"] = sum(contagem.values())

    antes = {e["escola"]: e["resultado"] for e in (anterior or {}).get("escolas", [])}
    mudancas = [
        {"escola": linha["escola"], "antes": antes[linha["escola"]], "agora": linha["resultado"]}
        for linha in linhas
        if linha["escola"] in antes and antes[linha["escola"]] != linha["resultado"]
    ]
    return {
        "totais": totais,
        "mudancas": mudancas if anterior else None,
        "offline_persistentes": offline_persistentes,
        "escolas": linhas,
        "observacoes": None,  # reservado para um resumo em texto livre
    }


def gravar_resumo(pasta: Path, resumo: dict) -> None:
    resumo = {"execucao": pasta.name, **resumo}
    with open(pasta / "resumo.csv", "w", encoding="utf-8-sig", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=COLUNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(resumo["escolas"])
    (pasta / "resumo.json").write_text(
        json.dumps(resumo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (pasta / "resumo.md").write_text(_markdown(resumo), encoding="utf-8")


def _markdown(resumo: dict) -> str:
    partes = [f"# Resumo da execução {resumo.get('execucao', '')}".rstrip(), "", "## Totais", ""]
    partes += [f"- {rotulo}: {qtd}" for rotulo, qtd in resumo["totais"].items()]

    partes += ["", "## Mudanças desde a execução anterior", ""]
    if resumo["mudancas"] is None:
        partes.append("Sem execução anterior para comparar.")
    elif not resumo["mudancas"]:
        partes.append("Nenhuma escola mudou de resultado.")
    else:
        partes += [f"- {m['escola']}: {m['antes']} → {m['agora']}" for m in resumo["mudancas"]]

    if resumo["offline_persistentes"]:
        partes += ["", "## Offline persistente (acionar a rede)", ""]
        partes += [
            f"- {nome}: {vezes} execuções seguidas sem rede"
            for nome, vezes in resumo["offline_persistentes"].items()
        ]

    partes += ["", "## Escolas", "", "| " + " | ".join(COLUNAS) + " |",
               "|" + "---|" * len(COLUNAS)]
    for linha in resumo["escolas"]:
        valores = ("" if linha[c] is None else str(linha[c]) for c in COLUNAS)
        partes.append("| " + " | ".join(v.replace("|", "/") for v in valores) + " |")
    return "\n".join(partes) + "\n"
