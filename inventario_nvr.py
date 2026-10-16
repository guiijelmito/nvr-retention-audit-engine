"""Inventaria modelo e firmware de NVRs Dahua usando a API HTTP CGI."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any
from urllib.parse import urlsplit

import requests
from requests.auth import HTTPDigestAuth


ENDPOINTS = {
    "system": "/cgi-bin/magicBox.cgi?action=getSystemInfo",
    "device_type": "/cgi-bin/magicBox.cgi?action=getDeviceType",
    "firmware": "/cgi-bin/magicBox.cgi?action=getSoftwareVersion",
    "hardware": "/cgi-bin/magicBox.cgi?action=getHardwareVersion",
}


def parse_cgi_response(body: str) -> dict[str, str]:
    """Converte respostas Dahua no formato key=value em dicionário."""
    parsed: dict[str, str] = {}
    for line in body.replace("\x00", "").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            parsed[key.strip()] = value.strip()
    return parsed


def normalize_host(value: Any, scheme: str, port: int | None) -> str:
    host = str(value).strip()
    if not host:
        raise ValueError("endereço vazio")
    if "://" in host:
        parts = urlsplit(host)
        if not parts.hostname:
            raise ValueError("URL sem hostname válido")
        netloc = parts.hostname
        if parts.port:
            netloc += f":{parts.port}"
        return f"{parts.scheme}://{netloc}"
    # Aceita também entradas host:porta no escolas.json.
    parts = urlsplit(f"//{host}")
    if not parts.hostname:
        raise ValueError("endereço inválido")
    netloc = parts.hostname
    if parts.port:
        netloc += f":{parts.port}"
    elif port:
        netloc += f":{port}"
    return f"{scheme}://{netloc}"


def request_fields(
    session: requests.Session,
    base_url: str,
    path: str,
    timeout: float,
    verify_tls: bool,
) -> dict[str, str]:
    response = session.get(
        base_url + path,
        timeout=timeout,
        verify=verify_tls,
        allow_redirects=False,
    )
    response.raise_for_status()
    return parse_cgi_response(response.text)


def inventory_one(
    school: str,
    address: Any,
    username: str,
    password: str,
    scheme: str,
    port: int | None,
    timeout: float,
    verify_tls: bool,
) -> dict[str, str]:
    result = {
        "school": school,
        "address": str(address),
        "model": "—",
        "firmware": "—",
        "hardware": "—",
        "status": "Não consultado",
    }
    try:
        base_url = normalize_host(address, scheme, port)
        with requests.Session() as session:
            session.auth = HTTPDigestAuth(username, password)
            system = request_fields(
                session, base_url, ENDPOINTS["system"], timeout, verify_tls
            )
            device = request_fields(
                session, base_url, ENDPOINTS["device_type"], timeout, verify_tls
            )
            firmware = request_fields(
                session, base_url, ENDPOINTS["firmware"], timeout, verify_tls
            )
            hardware = request_fields(
                session, base_url, ENDPOINTS["hardware"], timeout, verify_tls
            )

        result["model"] = (
            system.get("deviceType")
            or system.get("updateSerial")
            or device.get("type")
            or "Não informado pela CGI"
        )
        result["firmware"] = firmware.get("version", "Não informado pela CGI")
        result["hardware"] = (
            system.get("hardwareVersion")
            or hardware.get("version")
            or "Não informado pela CGI"
        )
        if result["model"] == "Não informado pela CGI" or result["firmware"] == "Não informado pela CGI":
            result["status"] = "Parcial: modelo ou firmware ausente"
        else:
            result["status"] = "OK"
    except requests.exceptions.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else "?"
        if code in (401, 403):
            result["status"] = f"Autenticação negada (HTTP {code})"
        else:
            result["status"] = f"HTTP {code}"
    except requests.exceptions.ConnectTimeout:
        result["status"] = "Tempo limite ao conectar"
    except requests.exceptions.ReadTimeout:
        result["status"] = "Tempo limite de resposta"
    except requests.exceptions.SSLError:
        result["status"] = "Falha TLS/certificado"
    except requests.exceptions.ConnectionError:
        result["status"] = "Sem conexão"
    except (requests.exceptions.RequestException, ValueError) as exc:
        result["status"] = f"Erro de consulta: {type(exc).__name__}"
    return result


def display_table(rows: list[dict[str, str]]) -> None:
    columns = [
        ("Escola / unidade", "school"),
        ("Endereço", "address"),
        ("Modelo", "model"),
        ("Firmware", "firmware"),
        ("Hardware", "hardware"),
        ("Resultado", "status"),
    ]
    widths = [
        min(max(len(header), *(len(row[key]) for row in rows)), 38)
        for header, key in columns
    ]

    def line(values: list[str]) -> str:
        return "| " + " | ".join(
            value[:width].ljust(width) for value, width in zip(values, widths)
        ) + " |"

    border = "+-" + "-+-".join("-" * width for width in widths) + "-+"
    print("\nINVENTÁRIO DE NVRs DAHUA")
    print(border)
    print(line([header for header, _ in columns]))
    print(border)
    for row in rows:
        print(line([row[key] for _, key in columns]))
    print(border)
    ok = sum(row["status"] == "OK" for row in rows)
    print(f"Consultas completas: {ok}/{len(rows)}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Consulta modelo e versões dos NVRs definidos em config.ESCOLAS."
    )
    parser.add_argument(
        "--scheme", choices=("http", "https"), default=os.getenv("NVR_SCHEME", "http"),
        help="Protocolo; padrão http (ou NVR_SCHEME)",
    )
    parser.add_argument(
        "--port", type=int, default=None,
        help="Porta opcional, aplicada aos endereços sem porta",
    )
    parser.add_argument("--timeout", type=float, default=8.0, help="Timeout por consulta (s)")
    parser.add_argument(
        "--insecure", action="store_true",
        help="Desativa validação do certificado HTTPS (somente se necessário em rede controlada)",
    )
    args = parser.parse_args()

    try:
        # Mantém escolas e credenciais alinhadas à configuração oficial do projeto.
        from config import ESCOLAS, SENHA, USUARIO
    except (ImportError, ModuleNotFoundError) as exc:
        print(f"Erro ao carregar config.py: {exc}", file=sys.stderr)
        return 2

    username = USUARIO
    password = SENHA
    if not username or not password:
        print("Erro: configure NVR_USUARIO e NVR_SENHA no .env.", file=sys.stderr)
        return 2
    if args.timeout <= 0 or (args.port is not None and not 1 <= args.port <= 65535):
        print("Erro: timeout e porta precisam estar dentro de valores válidos.", file=sys.stderr)
        return 2

    if not isinstance(ESCOLAS, dict) or not ESCOLAS:
        print("Erro: config.ESCOLAS está vazio ou não é um objeto válido.", file=sys.stderr)
        return 2

    rows = [
        inventory_one(
            school=str(name),
            address=(item.get("ip") or item.get("host")) if isinstance(item, dict) else item,
            username=username,
            password=password,
            scheme=args.scheme,
            port=args.port,
            timeout=args.timeout,
            verify_tls=not args.insecure,
        )
        for name, item in ESCOLAS.items()
    ]
    display_table(rows)
    return 0 if all(row["status"] == "OK" for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
