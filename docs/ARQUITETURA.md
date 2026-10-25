# Arquitetura

Mapa do código e regras para crescer sem voltar à bagunça. Regras de negócio e de compatibilidade continuam nos diários desta pasta.

## Camadas

```
cli.py ──► auditoria/pipeline.py ──► auditoria/retencao.py      (regra pura)
   │              │
   │              ├──► nvr/busca_gravacoes.py                     (API CGI do NVR)
   │              ├──► escolas.py                                 (data/escolas.json)
   │              └──► Integracoes ──► nvr/web/captura.py         (print do calendário)
   │                               ├──► integracoes/lan7.py       (chamado)
   │                               └──► integracoes/sheets.py     (planilha)
   ├──► devtools.py   (mesma pipeline, com Integracoes e estado de teste)
   └──► nvr/firmware.py
```

| Pasta/módulo | Responsabilidade | Pode importar |
|---|---|---|
| `auditoria/retencao.py` | Regra de dias contínuos. Não faz rede nem disco. | só a biblioteca padrão |
| `auditoria/pipeline.py` | Ordem dos passos e critérios de aprovação. | tudo abaixo |
| `escolas.py` | Ler/gravar `data/escolas.json`, agenda de 15 dias. | `config`, `log` |
| `nvr/` | Tudo que conversa com o NVR (CGI e interface web). | `config`, `log`, `evidencias` |
| `integracoes/` | Sistemas de terceiros (7LAN, Google). | `config`, `log`, `evidencias` |
| `config.py`, `log.py`, `evidencias.py` | Base compartilhada, sem efeitos colaterais no import. | biblioteca padrão |
| `cli.py`, `devtools.py` | Entrada do usuário; únicos que criam pastas e ligam o log. | tudo |

`nvr/` e `integracoes/` não importam `auditoria/`. Assim a regra de negócio pode mudar sem tocar na comunicação, e a comunicação pode ganhar um novo firmware sem tocar na regra.

## Fluxo de uma auditoria

1. `cli.py` cria `logs/` e a pasta de evidências e liga o log.
2. `pipeline.py` carrega `data/escolas.json` (`RegistroEscolas`) e pula escolas aprovadas há menos de 15 dias.
3. Para cada escola: `busca_gravacoes.verificar_api`, depois `retencao.contar_dias_continuos`, que consulta dia a dia via `busca_gravacoes.consultar_dia`.
4. Resultado completo com dias > 0 e data da gravação mais antiga: print do calendário, chamado no 7LAN e, só com os dois confirmados, `RegistroEscolas.marcar_aprovada`.
5. No fim, uma única chamada à planilha com as escolas processadas.

## Onde colocar código novo

- **Outro modelo/firmware de NVR:** variantes de seletor em `nvr/web/localizadores.py`; respostas CGI diferentes em `nvr/busca_gravacoes.py`, sempre com teste em `tests/nvr/` reproduzindo a resposta observada.
- **Outro helpdesk ou destino de relatório:** novo módulo em `integracoes/` com a mesma assinatura usada por `Integracoes` (`criar_ticket(nome) -> bool`, `enviar_planilha(linhas)`).
- **OS a partir de foto enviada por WhatsApp:** um subpacote próprio, por exemplo `nvr_audit_engine/whatsapp/` (webhook, fila e confirmação do técnico), reaproveitando `escolas.py`, `evidencias.py` e `integracoes/lan7.py`. Um comando novo entra em `cli.py`.
- **Consultas somente leitura para outros sistemas** (servidor de API, painel): também um subpacote próprio que lê `escolas.py` e os relatórios, sem importar `pipeline.py`.
- **Execução por cliente (multi-cliente):** caminhos e nomes da planilha saem de `config.py` para um arquivo por cliente; o resto do código já recebe registro e integrações por parâmetro.

## Testes

`tests/` espelha o pacote. Nenhum teste acessa rede, NVR, 7LAN ou Google: use `tests/apoio.py` (`DataFixa`, `FakeResponse`, `search_responses`) e passe `Integracoes` com `Mock`. Rode `python -m pytest` e `ruff check .` antes de cada commit; o GitHub Actions roda os mesmos comandos.
