"""Regra de contagem de dias contínuos de gravação.

Conta de ontem para trás. Dias vazios não somam, e a contagem só termina
depois de LIMITE_BURACO dias vazios seguidos: tolerar 1 ou 2 dias vazios é
uma salvaguarda proposital contra falso dia vazio quando uma resposta HTTP
se perde. Não é bug e não deve ser removida.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

LIMITE_DIAS = 730
LIMITE_BURACO = 3

SEM_DATA = "N/A"


@dataclass(frozen=True)
class ResultadoRetencao:
    dias_continuos: int
    gravacao_mais_antiga: str  # "dd/mm/aaaa" ou SEM_DATA
    data_inconclusiva: str | None = None  # "aaaa-mm-dd" do dia que interrompeu a auditoria

    @property
    def completa(self) -> bool:
        return self.data_inconclusiva is None


def contar_dias_continuos(
    consultar_dia: Callable[[str], bool | None],
    *,
    limite_dias: int | None = None,
    limite_buraco: int | None = None,
) -> ResultadoRetencao:
    """Percorre os dias com `consultar_dia("aaaa-mm-dd")`.

    `consultar_dia` devolve True (há gravação), False (vazio confirmado) ou
    None (inconclusivo). Um dia inconclusivo interrompe a contagem: o
    resultado fica incompleto e nunca é tratado como dia vazio.
    """
    limite_dias = LIMITE_DIAS if limite_dias is None else limite_dias
    limite_buraco = LIMITE_BURACO if limite_buraco is None else limite_buraco

    dias_continuos = 0
    dias_vazios_consecutivos = 0
    data_fim_hd = SEM_DATA

    for dias_atras in range(1, limite_dias + 1):
        data_alvo = datetime.now() - timedelta(days=dias_atras)
        data_str = data_alvo.strftime("%Y-%m-%d")
        encontrou_arquivo = consultar_dia(data_str)

        if encontrou_arquivo is None:
            return ResultadoRetencao(dias_continuos, SEM_DATA, data_inconclusiva=data_str)

        if encontrou_arquivo:
            dias_vazios_consecutivos = 0
            dias_continuos += 1
            continue

        dias_vazios_consecutivos += 1
        if dias_vazios_consecutivos >= limite_buraco:
            data_objeto = datetime.now() - timedelta(
                days=dias_atras - dias_vazios_consecutivos
            )
            data_fim_hd = data_objeto.strftime("%d/%m/%Y")
            break

    return ResultadoRetencao(dias_continuos, data_fim_hd)
