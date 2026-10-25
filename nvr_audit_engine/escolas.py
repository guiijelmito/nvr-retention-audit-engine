"""Lista de escolas e estado persistido da auditoria (data/escolas.json).

Aceita o formato legado {"Escola": "ip"} e o formato com estado
{"Escola": {"ip": ..., "status": ..., "concluida_em": ..., "proxima_auditoria_em": ...}}.
O fluxo de estado está descrito em docs/DIARIO_ESTADO_ESCOLAS.md.
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from nvr_audit_engine.log import logger

INTERVALO_AUDITORIA_DIAS = 15


class RegistroEscolas:
    """Mapa de escolas lido de um JSON, com a regra de agenda e a aprovação."""

    def __init__(self, arquivo: Path, dados: dict):
        self.arquivo = arquivo
        self.dados = dados

    @classmethod
    def carregar(cls, arquivo: Path) -> "RegistroEscolas":
        if arquivo.exists():
            with open(arquivo, "r", encoding="utf-8") as f:
                dados = json.load(f)
        else:
            dados = {}
        return cls(arquivo, dados)

    def unidades_com_ip(self) -> dict[str, str]:
        """Devolve {escola: ip} das unidades com IP válido; as demais geram aviso."""
        escolas = {}
        for nome_escola, dados_escola in self.dados.items():
            ip_nvr = dados_escola.get("ip") if isinstance(dados_escola, dict) else dados_escola
            if isinstance(ip_nvr, str) and ip_nvr.strip():
                escolas[nome_escola] = ip_nvr
            else:
                logger.warning("[CONFIG] Unidade ignorada por não possuir IP válido: %s", nome_escola)
        return escolas

    def proxima_auditoria_agendada(self, nome_escola: str) -> datetime | None:
        """Data de liberação se a escola está aprovada e ainda dentro da janela."""
        dados_escola = self.dados.get(nome_escola)
        if not isinstance(dados_escola, dict) or dados_escola.get("status") != "aprovada":
            return None

        data_liberacao = dados_escola.get("proxima_auditoria_em")
        if not isinstance(data_liberacao, str):
            return None

        try:
            proxima = datetime.fromisoformat(data_liberacao)
            if proxima.tzinfo is None:
                proxima = proxima.astimezone()
        except ValueError:
            logger.warning(
                "[ESTADO] Data de próxima auditoria inválida para %s; unidade será reavaliada.",
                nome_escola,
            )
            return None

        return proxima if datetime.now().astimezone() < proxima else None

    def marcar_aprovada(self, nome_escola: str, nvr_ip: str) -> tuple[str, str]:
        """Persiste o sucesso em JSON de forma atômica após os três critérios."""
        agora = datetime.now().astimezone()
        concluida_em = agora.isoformat(timespec="seconds")
        proxima_auditoria_em = (
            agora + timedelta(days=INTERVALO_AUDITORIA_DIAS)
        ).isoformat(timespec="seconds")

        dados_originais = self.dados.get(nome_escola, nvr_ip)
        if isinstance(dados_originais, dict):
            registro = dict(dados_originais)
            registro["ip"] = nvr_ip
        else:
            registro = {"ip": nvr_ip}

        registro.update({
            "status": "aprovada",
            "concluida_em": concluida_em,
            "proxima_auditoria_em": proxima_auditoria_em,
        })
        self.dados[nome_escola] = registro

        arquivo_temporario = self.arquivo.with_name(f"{self.arquivo.name}.tmp")
        try:
            with arquivo_temporario.open("w", encoding="utf-8", newline="\n") as arquivo:
                json.dump(self.dados, arquivo, ensure_ascii=False, indent=2)
                arquivo.write("\n")
            os.replace(arquivo_temporario, self.arquivo)
        except Exception:
            self.dados[nome_escola] = dados_originais
            try:
                arquivo_temporario.unlink(missing_ok=True)
            except OSError:
                pass
            raise

        return concluida_em, proxima_auditoria_em
