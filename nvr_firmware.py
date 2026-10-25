"""Inventário de firmware dos NVRs Dahua/Intelbras via CGI HTTP API.

Consulta cada NVR da lista de escolas (mesmo formato do escolas.json:
{"Nome da escola": "ip[:porta]"}
ou {"Nome da escola": {"ip": ..., ...}}) e reporta modelo, versão de firmware,
data de build e número de série. O resultado serve para agrupar os NVRs
por firmware e direcionar automações específicas para cada versão.

Uso:
    python nvr_firmware.py                      # usa data/escolas.json (ou escolas.json)
    python nvr_firmware.py --arquivo outra.json
    python nvr_firmware.py --ip 10.0.0.5 --ip 10.0.0.6
    python nvr_firmware.py --saida relatorio.csv --json relatorio.json

Credenciais vêm do .env (NVR_USUARIO / NVR_SENHA), igual ao restante do projeto.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth, HTTPDigestAuth

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

logger = logging.getLogger("VerthFirmware")

# Endpoints do magicBox.cgi presentes nos firmwares Dahua legados.
# Nem todo firmware responde a todos; os que falham ficam em branco.
CONSULTAS = {
    "versao_bruta": "getSoftwareVersion",
    "tipo_dispositivo": "getDeviceType",
    "versao_hardware": "getHardwareVersion",
    "numero_serie": "getSerialNo",
    "nome_maquina": "getMachineName",
    "fabricante": "getVendor",
    "info_sistema": "getSystemInfo",
}

COLUNAS_RELATORIO = [
    "escola", "ip", "status", "autenticacao", "modelo", "versao_firmware",
    "build_firmware", "versao_hardware", "numero_serie", "nome_maquina",
    "fabricante", "erro",
]


@dataclass
class ResultadoNVR:
    escola: str
    ip: str
    status: str = "pendente"          # online | offline | falha_autenticacao | erro
    autenticacao: str = ""            # digest | basic
    modelo: str = ""
    versao_firmware: str = ""
    build_firmware: str = ""
    versao_hardware: str = ""
    numero_serie: str = ""
    nome_maquina: str = ""
    fabricante: str = ""
    erro: str = ""
    bruto: dict = field(default_factory=dict)


def parse_chave_valor(texto: str) -> dict:
    """Converte a resposta 'chave=valor' (uma por linha) do CGI em dict."""
    dados = {}
    for linha in texto.replace("\x00", "").splitlines():
        if "=" in linha:
            chave, valor = linha.split("=", 1)
            dados[chave.strip()] = valor.strip()
    return dados


def montar_url_base(endereco: str, esquema: str = "http", porta: int | None = None) -> str:
    """Aceita 'ip', 'ip:porta' ou 'https://host[:porta]' e devolve 'esquema://host[:porta]'."""
    endereco = endereco.strip()
    if "://" in endereco:
        partes = urlsplit(endereco)
        esquema = partes.scheme
    else:
        partes = urlsplit(f"//{endereco}")
    if not partes.hostname:
        raise ValueError(f"Endereço inválido: {endereco!r}")
    porta_final = partes.port or porta
    return f"{esquema}://{partes.hostname}" + (f":{porta_final}" if porta_final else "")


def separar_versao_build(versao_bruta: str) -> tuple[str, str]:
    """'2.420.0000.0.R,build:2016-01-12' -> ('2.420.0000.0.R', '2016-01-12')."""
    if not versao_bruta:
        return "", ""
    match = re.match(r"\s*([^,]+?)\s*(?:,\s*build\s*:\s*(.+))?$", versao_bruta, re.IGNORECASE)
    if not match:
        return versao_bruta.strip(), ""
    return match.group(1).strip(), (match.group(2) or "").strip()


def criar_sessao(url_nvr: str, usuario: str, senha: str, timeout: float,
                 verificar_tls: bool = True) -> tuple[requests.Session, str]:
    """Abre sessão autenticada: tenta Digest e cai para Basic se o NVR pedir.

    Retorna (sessao, tipo_autenticacao). Lança PermissionError se nenhuma
    autenticação for aceita e ConnectionError se o NVR não responder.
    """
    url_teste = f"{url_nvr}/cgi-bin/magicBox.cgi?action=getSoftwareVersion"

    for nome, classe_auth in (("digest", HTTPDigestAuth), ("basic", HTTPBasicAuth)):
        sessao = requests.Session()
        sessao.auth = classe_auth(usuario, senha)
        sessao.verify = verificar_tls
        resp = sessao.get(url_teste, timeout=timeout)

        if resp.status_code == 200:
            return sessao, nome

        sessao.close()
        desafio = resp.headers.get("WWW-Authenticate", "").lower()
        # Só vale tentar Basic se o NVR anunciar Basic (ou não anunciar nada)
        if resp.status_code == 401 and nome == "digest" and ("basic" in desafio or not desafio):
            continue
        if resp.status_code == 401:
            break
        raise RuntimeError(f"HTTP {resp.status_code} em getSoftwareVersion")

    raise PermissionError("Usuário/senha recusados pelo NVR")


def consultar_nvr(escola: str, nvr_ip: str, usuario: str, senha: str, timeout: float = 8.0,
                  esquema: str = "http", porta: int | None = None,
                  verificar_tls: bool = True) -> ResultadoNVR:
    resultado = ResultadoNVR(escola=escola, ip=nvr_ip)

    try:
        url_nvr = montar_url_base(nvr_ip, esquema, porta)
        sessao, resultado.autenticacao = criar_sessao(url_nvr, usuario, senha, timeout, verificar_tls)
    except requests.exceptions.SSLError:
        resultado.status = "erro"
        resultado.erro = "Falha TLS/certificado (use --inseguro só em rede controlada)"
        return resultado
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        resultado.status = "offline"
        resultado.erro = "NVR inacessível na rede"
        return resultado
    except PermissionError as e:
        resultado.status = "falha_autenticacao"
        resultado.erro = str(e)
        return resultado
    except Exception as e:
        resultado.status = "erro"
        resultado.erro = str(e)
        return resultado

    url_base = f"{url_nvr}/cgi-bin/magicBox.cgi"
    try:
        for chave, acao in CONSULTAS.items():
            try:
                resp = sessao.get(f"{url_base}?action={acao}", timeout=timeout)
                if resp.status_code == 200 and "Error" not in resp.text[:20]:
                    resultado.bruto[chave] = resp.text.strip()
            except requests.exceptions.RequestException:
                pass
    finally:
        sessao.close()

    bruto = resultado.bruto
    info = parse_chave_valor(bruto.get("info_sistema", ""))

    versao = parse_chave_valor(bruto.get("versao_bruta", "")).get("version", "")
    resultado.versao_firmware, resultado.build_firmware = separar_versao_build(versao)
    resultado.modelo = (
        parse_chave_valor(bruto.get("tipo_dispositivo", "")).get("type")
        or info.get("deviceType")
        or info.get("updateSerial", "")
    )
    resultado.versao_hardware = (
        parse_chave_valor(bruto.get("versao_hardware", "")).get("version")
        or info.get("hardwareVersion", "")
    )
    resultado.numero_serie = (
        parse_chave_valor(bruto.get("numero_serie", "")).get("sn")
        or info.get("serialNumber", "")
    )
    resultado.nome_maquina = parse_chave_valor(bruto.get("nome_maquina", "")).get("name", "")
    resultado.fabricante = parse_chave_valor(bruto.get("fabricante", "")).get("vendor", "")

    if resultado.versao_firmware:
        resultado.status = "online"
    else:
        resultado.status = "erro"
        resultado.erro = "NVR respondeu, mas sem versão de firmware reconhecível"
    return resultado


def carregar_escolas(arquivo: Path | None) -> dict:
    """Lê {"escola": "ip"} ou o formato com estado {"escola": {"ip": ..., ...}}."""
    candidatos = [arquivo] if arquivo else [
        BASE_DIR / "data" / "escolas.json", BASE_DIR / "escolas.json", BASE_DIR / "escolas_teste.json",
    ]
    for caminho in candidatos:
        if caminho and caminho.exists():
            with open(caminho, "r", encoding="utf-8") as f:
                dados = json.load(f)
            escolas = {}
            for nome, item in dados.items():
                ip = (item.get("ip") or item.get("host")) if isinstance(item, dict) else item
                if isinstance(ip, str) and ip.strip():
                    escolas[nome] = ip.strip()
                else:
                    logger.warning(f"Unidade ignorada por não possuir IP válido: {nome}")
            logger.info(f"Lista de NVRs carregada de {caminho} ({len(escolas)} unidades)")
            return escolas
    raise FileNotFoundError(
        "Nenhuma lista de NVRs encontrada. Crie data/escolas.json ({\"Escola\": \"ip\"}) ou use --arquivo / --ip."
    )


def salvar_csv(resultados: list[ResultadoNVR], caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUNAS_RELATORIO, delimiter=";")
        escritor.writeheader()
        for r in resultados:
            linha = asdict(r)
            escritor.writerow({c: linha[c] for c in COLUNAS_RELATORIO})


def salvar_json(resultados: list[ResultadoNVR], caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in resultados], f, ensure_ascii=False, indent=2)


def imprimir_resumo(resultados: list[ResultadoNVR]) -> None:
    print()
    print(f"{'ESCOLA':<35} {'IP':<21} {'STATUS':<19} {'MODELO':<22} FIRMWARE")
    print("-" * 120)
    for r in resultados:
        firmware = f"{r.versao_firmware} ({r.build_firmware})" if r.build_firmware else (r.versao_firmware or r.erro)
        print(f"{r.escola[:34]:<35} {r.ip:<21} {r.status:<19} {r.modelo[:21]:<22} {firmware}")

    grupos = defaultdict(list)
    for r in resultados:
        if r.status == "online":
            grupos[(r.versao_firmware, r.build_firmware)].append(r.escola)

    if grupos:
        print("\nNVRs agrupados por firmware:")
        for (versao, build), escolas in sorted(grupos.items(), key=lambda g: -len(g[1])):
            rotulo = f"{versao} (build {build})" if build else versao
            print(f"  {rotulo}: {len(escolas)} NVR(s) -> {', '.join(escolas)}")

    sem_versao = [r for r in resultados if r.status != "online"]
    if sem_versao:
        print(f"\n{len(sem_versao)} NVR(s) sem versão: " + ", ".join(f"{r.escola} [{r.status}]" for r in sem_versao))
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Consulta a versão de firmware dos NVRs Dahua via CGI.")
    parser.add_argument("--arquivo", type=Path, help="JSON {escola: ip}. Padrão: data/escolas.json")
    parser.add_argument("--ip", action="append", help="Consulta um IP avulso (pode repetir); ignora o arquivo")
    parser.add_argument("--saida", type=Path, help="Caminho do CSV. Padrão: relatorios_firmware/firmware_nvrs_<data>.csv")
    parser.add_argument("--json", type=Path, dest="saida_json", help="Também salva o resultado completo em JSON")
    parser.add_argument("--timeout", type=float, default=8.0, help="Timeout por requisição em segundos (padrão 8)")
    parser.add_argument("--esquema", choices=("http", "https"), default=os.getenv("NVR_SCHEME", "http"),
                        help="Protocolo dos NVRs; padrão http (ou NVR_SCHEME no .env)")
    parser.add_argument("--porta", type=int, help="Porta aplicada aos endereços que não informam porta")
    parser.add_argument("--inseguro", action="store_true",
                        help="Não valida o certificado HTTPS (somente em rede controlada)")
    parser.add_argument("--paralelo", type=int, default=8, help="NVRs consultados ao mesmo tempo (padrão 8)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%d/%m/%Y %H:%M:%S")

    usuario, senha = os.getenv("NVR_USUARIO"), os.getenv("NVR_SENHA")
    if not usuario or not senha:
        logger.error("Defina NVR_USUARIO e NVR_SENHA no .env (veja .env.example).")
        return 2

    if args.ip:
        escolas = {ip: ip for ip in args.ip}
    else:
        try:
            escolas = carregar_escolas(args.arquivo)
        except FileNotFoundError as e:
            logger.error(str(e))
            return 2

    def tarefa(item):
        escola, nvr_ip = item
        r = consultar_nvr(escola, nvr_ip, usuario, senha, args.timeout,
                          args.esquema, args.porta, not args.inseguro)
        logger.info(f"[{r.status.upper()}] {escola} ({nvr_ip}) -> {r.versao_firmware or r.erro}")
        return r

    with ThreadPoolExecutor(max_workers=max(1, args.paralelo)) as executor:
        resultados = list(executor.map(tarefa, escolas.items()))

    imprimir_resumo(resultados)

    saida_csv = args.saida or BASE_DIR / "relatorios_firmware" / f"firmware_nvrs_{datetime.now():%Y-%m-%d_%H%M}.csv"
    salvar_csv(resultados, saida_csv)
    logger.info(f"Relatório CSV salvo em {saida_csv}")
    if args.saida_json:
        salvar_json(resultados, args.saida_json)
        logger.info(f"Relatório JSON salvo em {args.saida_json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
