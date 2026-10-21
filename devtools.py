"""Pipeline interativo para validar escolas específicas em ambiente controlado.

Executa a mesma auditoria da produção, mas com navegador visível e lento,
confirmações antes de criar/fechar tickets e sem alterar o estado oficial por
padrão. Execute apenas em uma máquina com acesso de rede aos IPs selecionados.
"""

from __future__ import annotations

import ipaddress
import json
import sys
from contextlib import contextmanager
from datetime import datetime
from functools import wraps
from pathlib import Path

from config import ESCOLAS, logger
from nvr_capture import capturar_print_nvr


BASE_DIR = Path(__file__).resolve().parent
ARQUIVO_ESTADO_DEV = BASE_DIR / "data" / "devtools_escolas.json"
ARQUIVO_PARA_RETESTE = BASE_DIR / "escolas_para_reteste.json"
ARQUIVO_RETESTE_ANTIGO = BASE_DIR / "escolas_falha.json"
PLAYWRIGHT_SLOW_MO_MS = 0


@contextmanager
def _passo_a_passo_playwright():
    """Pede Enter antes das ações e neutraliza esperas fixas do Playwright."""
    from playwright.sync_api import Browser, BrowserContext, FileChooser, Locator, Page

    classes_metodos = {
        Browser: ("new_context", "new_page"),
        BrowserContext: ("new_page",),
        FileChooser: ("set_files",),
        Page: (
            "goto", "go_back", "go_forward", "reload", "click", "dblclick",
            "fill", "type", "press", "select_option", "check", "uncheck",
            "set_input_files", "wait_for_selector", "wait_for_function", "wait_for_load_state",
            "wait_for_url", "screenshot", "close",
        ),
        Locator: (
            "click", "dblclick", "fill", "type", "press", "select_option",
            "check", "uncheck", "set_input_files", "wait_for", "screenshot",
            "focus", "hover", "evaluate", "is_visible",
        ),
    }
    originais = []

    def criar_wrapper(metodo_original, classe, nome_metodo):
        @wraps(metodo_original)
        def wrapper(self, *args, **kwargs):
            if nome_metodo == "wait_for_timeout":
                return None
            try:
                resposta = input(
                    f"\n[PLAYWRIGHT] {classe}.{nome_metodo} — "
                    "pressione Enter para continuar (q para interromper)..."
                )
            except EOFError as exc:
                raise KeyboardInterrupt from exc
            if resposta.strip().casefold() in {"q", "sair", "cancelar"}:
                raise KeyboardInterrupt
            return metodo_original(self, *args, **kwargs)

        return wrapper

    try:
        for classe, metodos in classes_metodos.items():
            for nome_metodo in metodos:
                metodo_original = getattr(classe, nome_metodo, None)
                if metodo_original is None:
                    continue
                originais.append((classe, nome_metodo, metodo_original))
                setattr(
                    classe,
                    nome_metodo,
                    criar_wrapper(metodo_original, classe.__name__, nome_metodo),
                )

        # Métodos de espera fixa nos módulos de produção tornam-se no-op apenas
        # enquanto esta ferramenta está em modo passo a passo.
        metodo_timeout = getattr(Page, "wait_for_timeout", None)
        if metodo_timeout is not None:
            originais.append((Page, "wait_for_timeout", metodo_timeout))
            setattr(Page, "wait_for_timeout", lambda self, timeout: None)
        yield
    finally:
        for classe, nome_metodo, metodo_original in reversed(originais):
            setattr(classe, nome_metodo, metodo_original)


def _confirmar(pergunta: str) -> bool:
    """Só aceita confirmação afirmativa explícita."""
    while True:
        resposta = input(f"\n{pergunta} [s/N]: ").strip().casefold()
        if resposta in {"s", "sim"}:
            return True
        if resposta in {"", "n", "nao", "não"}:
            return False
        print("Responda 's' para confirmar ou 'n' para cancelar.")


def _validar_ip(ip: str) -> str:
    try:
        return str(ipaddress.IPv4Address(ip.strip()))
    except ipaddress.AddressValueError as exc:
        raise ValueError(f"IP inválido: {ip!r}.") from exc


def _nome_da_unidade(ip: str) -> str:
    for nome, ip_configurado in ESCOLAS.items():
        if ip_configurado == ip:
            return nome
    nome = input(f"IP {ip} não está no inventário. Nome da escola: ").strip()
    if not nome:
        raise ValueError(f"É necessário informar um nome para {ip}.")
    return nome


def _carregar_json_unidades(caminho: Path) -> dict[str, str]:
    try:
        with caminho.open("r", encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Não foi possível ler o JSON {caminho}: {exc}") from exc

    if not isinstance(dados, dict):
        raise ValueError("O JSON precisa ter um objeto com nome de escola e IP.")

    unidades: dict[str, str] = {}
    for nome, registro in dados.items():
        ip = registro.get("ip") if isinstance(registro, dict) else registro
        if not isinstance(nome, str) or not nome.strip() or not isinstance(ip, str):
            raise ValueError(f"Registro inválido no JSON para {nome!r}.")
        unidades[nome.strip()] = _validar_ip(ip)

    if not unidades:
        raise ValueError(f"O JSON {caminho} não contém escolas.")
    return unidades


def _selecionar_unidades() -> dict[str, str]:
    print("\nQuais unidades deseja executar?")
    print("  1. Todas as unidades do inventário")
    print("  2. Uma unidade específica (por IP)")
    print("  3. Unidades de um JSON de reteste")
    escolha = input("Escolha [1/2/3]: ").strip()

    if escolha == "1":
        if not ESCOLAS:
            raise ValueError("O inventário não contém unidades com IP válido.")
        return dict(ESCOLAS)

    if escolha == "2":
        ip = _validar_ip(input("IP da unidade: "))
        nome = _nome_da_unidade(ip)
        print(f"Unidade selecionada: {nome} ({ip})")
        return {nome: ip}

    if escolha == "3":
        padrao = ARQUIVO_PARA_RETESTE
        if not padrao.exists() and ARQUIVO_RETESTE_ANTIGO.exists():
            padrao = ARQUIVO_RETESTE_ANTIGO
        caminho_informado = input(
            f"Caminho do JSON [{padrao.name}]: "
        ).strip()
        caminho = Path(caminho_informado) if caminho_informado else padrao
        if not caminho.is_absolute():
            caminho = BASE_DIR / caminho
        unidades = _carregar_json_unidades(caminho)
        print(f"Carregadas {len(unidades)} unidade(s) de {caminho.name}.")
        return unidades

    raise ValueError("Escolha inválida; informe 1, 2 ou 3.")


def _confirmar_sincronizacao(resultados: list[dict]) -> None:
    print("\nResultados preparados para o Google Sheets:")
    for resultado in resultados:
        print(
            "  {Escola}: {Dias Contínuos Válidos} dia(s); gravação mais antiga: "
            "{Gravação mais antiga}".format(**resultado)
        )
    if _confirmar("Enviar esses resultados ao Google Sheets?"):
        import cloud_sync

        cloud_sync.enviar_para_google_sheets(resultados)
    else:
        logger.info("[DEVTOOLS] Sincronização com Google Sheets cancelada.")


def _criar_relatorio(unidades: dict[str, str]) -> dict[str, dict[str, str]]:
    return {
        nome: {
            "ip": ip,
            "auditoria": "Aguardando",
            "print": "Aguardando",
        }
        for nome, ip in unidades.items()
    }


def _imprimir_tabela_devtools(relatorio: dict[str, dict[str, str]]) -> None:
    if not relatorio:
        return

    for dados in relatorio.values():
        for chave in ("auditoria", "print"):
            if dados[chave] == "Aguardando":
                dados[chave] = "Sem resultado"

    cabecalhos = ("Unidade", "IP", "Auditoria de dias", "Print")
    linhas = [
        (nome, dados["ip"], dados["auditoria"], dados["print"])
        for nome, dados in relatorio.items()
    ]
    larguras = [
        max(len(cabecalho), *(len(linha[indice]) for linha in linhas))
        for indice, cabecalho in enumerate(cabecalhos)
    ]
    separador = "+-" + "-+-".join("-" * largura for largura in larguras) + "-+"

    def formatar(linha: tuple[str, ...]) -> str:
        return "| " + " | ".join(
            valor.ljust(larguras[indice]) for indice, valor in enumerate(linha)
        ) + " |"

    print("\nTABELA DEVTOOLS — RESULTADO POR UNIDADE")
    print(separador)
    print(formatar(cabecalhos))
    print(separador)
    for linha in linhas:
        print(formatar(linha))
    print(separador)


def _selecionar_modo() -> str:
    print("\nO que deseja testar?")
    print("  1. Auditoria completa (consulta dias, print e fluxo de ticket)")
    print("  2. Somente captura do calendário (sem auditoria de dias/ticket/Sheets)")
    while True:
        escolha = input("Escolha [1/2]: ").strip()
        if escolha in {"1", "2"}:
            return escolha
        print("Escolha 1 ou 2.")


def _ler_ano_mes() -> tuple[int, int]:
    agora = datetime.now()
    try:
        ano_texto = input(f"Ano do calendário [{agora.year}]: ").strip()
        mes_texto = input(f"Mês do calendário [{agora.month}]: ").strip()
        ano = int(ano_texto) if ano_texto else agora.year
        mes = int(mes_texto) if mes_texto else agora.month
    except ValueError as exc:
        raise ValueError("Ano e mês precisam ser números inteiros.") from exc

    if not 2000 <= ano <= 2100:
        raise ValueError("Ano fora do intervalo permitido (2000–2100).")
    if not 1 <= mes <= 12:
        raise ValueError("Mês precisa estar entre 1 e 12.")
    return ano, mes


def _executar_captura_direta(
    selecionadas: dict[str, str],
    relatorio: dict[str, dict[str, str]],
) -> int:
    for dados in relatorio.values():
        dados["auditoria"] = "Não executada (captura direta)"
        dados["print"] = "Não executado"
    try:
        ano, mes = _ler_ano_mes()
    except (EOFError, KeyboardInterrupt):
        print("\nTeste de captura cancelado.")
        return 130
    except ValueError as exc:
        print(f"Entrada inválida: {exc}")
        return 2

    print("\nModo: captura direta; não haverá consulta de retenção, ticket ou Sheets.")
    print(f"Calendário a capturar: {mes:02d}/{ano}")
    for nome, ip in selecionadas.items():
        print(f"  {nome}: {ip}")
    if not _confirmar("Abrir os NVRs selecionados e capturar os calendários?"):
        print("Teste de captura cancelado pelo operador.")
        return 0

    falhas = []
    for nome, ip in selecionadas.items():
        relatorio[nome]["print"] = "Aguardando"
        logger.info("[DEVTOOLS] Captura direta do NVR %s (%s), calendário %02d/%d.",
                    nome, ip, mes, ano)
        try:
            with _passo_a_passo_playwright():
                caminho = capturar_print_nvr(
                    ip,
                    nome,
                    ano,
                    mes,
                    headless=False,
                    slow_mo_ms=PLAYWRIGHT_SLOW_MO_MS,
                    aguardar_em_erro=True,
                )
        except Exception:
            logger.exception("[DEVTOOLS] Captura direta falhou para %s.", nome)
            caminho = None

        if caminho:
            relatorio[nome]["print"] = "OK"
            print(f"Print capturado: {caminho}")
        else:
            relatorio[nome]["print"] = "Falhou"
            print(f"Falha na captura: {nome} ({ip})")
            falhas.append(nome)

    return 1 if falhas else 0


def main() -> int:
    try:
        selecionadas = _selecionar_unidades()
        modo = _selecionar_modo()
    except (EOFError, KeyboardInterrupt):
        print("\nExecução cancelada.")
        return 130
    except ValueError as exc:
        print(f"Entrada inválida: {exc}")
        return 2

    relatorio = _criar_relatorio(selecionadas)
    print("\nResumo da execução de desenvolvimento:")
    for nome, ip in selecionadas.items():
        print(f"  {nome}: {ip}")
    print("  Playwright: navegador visível, passo manual com Enter")
    if modo == "2":
        try:
            return _executar_captura_direta(selecionadas, relatorio)
        except KeyboardInterrupt:
            print("\nTeste interrompido pelo operador.")
            return 130
        finally:
            _imprimir_tabela_devtools(relatorio)

    print(f"  Estado: {ARQUIVO_ESTADO_DEV}")
    print("  Google Sheets e gravação/fechamento de tickets exigem confirmação.")

    if not _confirmar("Iniciar a auditoria desses IPs na rede da GCM?"):
        print("Execução cancelada pelo operador.")
        return 0

    ARQUIVO_ESTADO_DEV.parent.mkdir(parents=True, exist_ok=True)
    if ARQUIVO_ESTADO_DEV.exists():
        try:
            with ARQUIVO_ESTADO_DEV.open("r", encoding="utf-8") as arquivo:
                estado_dev = json.load(arquivo)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Não foi possível ler o estado de desenvolvimento: {exc}")
            return 1
        if not isinstance(estado_dev, dict):
            print("O arquivo de estado de desenvolvimento precisa conter um objeto JSON.")
            return 1
    else:
        estado_dev = {}

    # Reutiliza apenas o estado de desenvolvimento. Se a unidade já foi
    # aprovada, força uma nova rodada somente com confirmação contra duplicidade.
    import nvr_audit

    for nome, ip in selecionadas.items():
        registro = estado_dev.get(nome)
        if not isinstance(registro, dict) or registro.get("ip") != ip:
            estado_dev[nome] = {
                "ip": ip,
                "status": "pendente",
                "concluida_em": None,
                "proxima_auditoria_em": None,
            }
            continue

        nvr_audit.DADOS_ESCOLAS = estado_dev
        liberacao = nvr_audit._proxima_auditoria_agendada(nome)
        if liberacao is not None and not _confirmar(
            f"{nome} já foi testada e aprovada em dev. Forçar nova auditoria "
            "(pode criar um ticket duplicado)?"
        ):
            print(f"{nome} permanecerá na lista e será pulada pelo estado salvo.")
            continue
        if liberacao is not None:
            estado_dev[nome] = {
                "ip": ip,
                "status": "pendente",
                "concluida_em": None,
                "proxima_auditoria_em": None,
            }

    # Mantém a execução limitada aos IPs escolhidos e nunca altera o arquivo
    # oficial data/escolas.json.
    nvr_audit.ESCOLAS = selecionadas
    nvr_audit.DADOS_ESCOLAS = estado_dev
    nvr_audit.ARQUIVO_ESCOLAS = ARQUIVO_ESTADO_DEV

    # O módulo de auditoria recebe as variantes visuais somente nesta execução.
    def capturar_print_dev(ip: str, nome: str, ano: int, mes: int):
        try:
            caminho = capturar_print_nvr(
                ip,
                nome,
                ano,
                mes,
                headless=False,
                slow_mo_ms=PLAYWRIGHT_SLOW_MO_MS,
                aguardar_em_erro=True,
            )
        except Exception:
            relatorio[nome]["print"] = "Falhou"
            raise
        relatorio[nome]["print"] = (
            "OK" if caminho and Path(caminho).is_file() else "Falhou"
        )
        return caminho

    nvr_audit.capturar_print_nvr = capturar_print_dev
    ordem_teste = {
        nome: indice
        for indice, nome in enumerate(selecionadas, start=1)
    }
    from ticket_automation import criar_ticket_7lan

    def criar_ticket_dev(nome: str) -> bool:
        data_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        titulo = (
            f"[TESTE DEV {ordem_teste[nome]:02d}] Controle de gravação - "
            f"{nome} - {data_hora}"
        )
        logger.info("[DEVTOOLS] Título do ticket: %s", titulo)
        return criar_ticket_7lan(
            nome,
            headless=False,
            slow_mo_ms=PLAYWRIGHT_SLOW_MO_MS,
            confirmar=_confirmar,
            titulo_customizado=titulo,
        )

    nvr_audit.criar_ticket_7lan = criar_ticket_dev

    proxima_auditoria_original = nvr_audit._proxima_auditoria_agendada

    def proxima_auditoria_dev(nome: str):
        proxima = proxima_auditoria_original(nome)
        if proxima is not None:
            relatorio[nome]["auditoria"] = "Pulado (estado aprovado)"
            relatorio[nome]["print"] = "Não executado"
        return proxima

    nvr_audit._proxima_auditoria_agendada = proxima_auditoria_dev

    def sincronizar_dev(resultados: list[dict]) -> None:
        for resultado in resultados:
            nome = resultado["Escola"]
            dias = resultado["Dias Contínuos Válidos"]
            if isinstance(dias, str) and dias.startswith("Verificação incompleta"):
                relatorio[nome]["auditoria"] = "Falhou/incompleta"
                relatorio[nome]["print"] = "Não executado"
            elif dias == "Verificar no local":
                relatorio[nome]["auditoria"] = "Concluída (sem dias)"
                if relatorio[nome]["print"] == "Aguardando":
                    relatorio[nome]["print"] = "Não aplicável"
            else:
                relatorio[nome]["auditoria"] = f"Concluída ({dias} dias)"
                if relatorio[nome]["print"] == "Aguardando":
                    relatorio[nome]["print"] = "Não gerado"
        _confirmar_sincronizacao(resultados)

    nvr_audit.enviar_para_google_sheets = sincronizar_dev

    codigo_saida = 0
    try:
        with _passo_a_passo_playwright():
            nvr_audit.auditar_retencao_nvr_com_cloud()
    except KeyboardInterrupt:
        logger.warning("[DEVTOOLS] Execução interrompida pelo operador.")
        codigo_saida = 130
    except Exception:
        logger.exception("[DEVTOOLS] Falha inesperada na pipeline de desenvolvimento.")
        codigo_saida = 1
    finally:
        _imprimir_tabela_devtools(relatorio)
    return codigo_saida


if __name__ == "__main__":
    sys.exit(main())
