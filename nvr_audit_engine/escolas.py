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
# A partir de 2 execuções seguidas sem rede, é link/VPN/energia parado, não oscilação.
LIMITE_OFFLINE_PERSISTENTE = 2


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

        self._atualizar(nome_escola, nvr_ip, {
            "status": "aprovada",
            "concluida_em": concluida_em,
            "proxima_auditoria_em": proxima_auditoria_em,
        })
        return concluida_em, proxima_auditoria_em

    def registrar_tentativa(
        self, nome_escola: str, nvr_ip: str, resultado: str, motivo: str | None, de_rede: bool
    ) -> None:
        """Guarda o resultado da execução para a próxima priorizar as que falharam.

        `tentativas` conta execuções seguidas sem aprovação; `falhas_rede_seguidas`
        conta execuções seguidas em que o NVR não respondeu por rede.
        """
        anterior = self.dados.get(nome_escola)
        anterior = anterior if isinstance(anterior, dict) else {}
        aprovada = resultado == "aprovada"
        self._atualizar(nome_escola, nvr_ip, {
            "ultimo_resultado": resultado,
            "motivo_falha": None if aprovada else motivo,
            "tentativas": 0 if aprovada else anterior.get("tentativas", 0) + 1,
            "falhas_rede_seguidas": anterior.get("falhas_rede_seguidas", 0) + 1 if de_rede else 0,
            "ultima_tentativa_em": datetime.now().astimezone().isoformat(timespec="seconds"),
        })

    def pendentes(self) -> set[str]:
        """Escolas cuja última tentativa registrada não foi aprovada."""
        return {
            nome for nome, dados in self.dados.items()
            if isinstance(dados, dict)
            and dados.get("ultimo_resultado") not in (None, "aprovada")
        }

    def offline_persistentes(self, limite: int = LIMITE_OFFLINE_PERSISTENTE) -> dict[str, int]:
        """{escola: execuções seguidas sem rede} das que chegaram a `limite`."""
        return {
            nome: dados["falhas_rede_seguidas"]
            for nome, dados in self.dados.items()
            if isinstance(dados, dict) and dados.get("falhas_rede_seguidas", 0) >= limite
        }

    def _atualizar(self, nome_escola: str, nvr_ip: str, campos: dict) -> None:
        """Mescla `campos` no registro da escola e grava o JSON de forma atômica."""
        dados_originais = self.dados.get(nome_escola, nvr_ip)
        if isinstance(dados_originais, dict):
            registro = dict(dados_originais)
            registro["ip"] = nvr_ip
        else:
            registro = {"ip": nvr_ip}

        registro.update(campos)
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
