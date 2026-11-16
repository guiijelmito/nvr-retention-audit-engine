# Diário de compatibilidade da API dos NVRs

Este arquivo registra comportamentos observados e limites conhecidos para orientar futuras alterações. Um comportamento que já funciona nos NVRs instalados deve ser tratado como contrato de compatibilidade até haver evidência para mudá-lo.

## Regras antes de alterar comunicação

- Comparar com a versão que estava funcionando e identificar a menor mudança necessária.
- Não alterar autenticação Digest, endpoints, parâmetros, codificação da URL, timeouts ou interpretação de respostas sem evidência do equipamento.
- Não tratar todo status HTTP diferente de 2xx como falha fatal: firmwares antigos podem divergir do comportamento esperado pela documentação.
- Uma resposta vazia só pode ser confirmada por uma resposta CGI válida. Timeout, erro HTTP, corpo desconhecido ou interrupção são estado inconclusivo, nunca “sem gravação”.
- Antes de publicar uma mudança de comunicação, reproduzir a resposta observada em teste automatizado e validar em pelo menos um modelo/firmware representativo quando possível.
- Não executar a auditoria completa em produção para depurar sem considerar que o fluxo pode sincronizar planilhas e criar tickets.

## Fluxo Dahua conhecido

O caminho atualmente usado pela auditoria é:

1. `factory.create` cria um token de busca.
2. `findFile` inicia a busca com canal, intervalo de data e tipo `dav`.
3. `findNextFile` retorna `found=0` ou os itens localizados.
4. `close` encerra o token.

A sessão usa autenticação HTTP Digest. O parâmetro `condition.Types[0]=dav` e o formato dos horários fazem parte da consulta existente; não simplificar nem reformatar sem teste de compatibilidade com os gravadores antigos.

## Incidente de 16/10/2026

- A alteração `f813473` adicionou validação estrita de status HTTP em todos os passos CGI.
- No PC da GCM, dois NVRs antigos responderam HTTP 400 no passo `findFile` em datas diferentes. A execução anterior não interrompia nessa resposta: continuava para `findNextFile`.
- Causa provável: compatibilidade do firmware no início de uma busca sem resultado. Isso é uma inferência baseada no ponto da falha e no comportamento anterior; o corpo HTTP 400 não foi registrado, então o motivo ainda não está comprovado em campo.
- A alteração `7452c67` passou a permitir HTTP 400 somente em `findFile`, e exige que `findNextFile` retorne um corpo CGI reconhecível. O dia vazio continua dependendo de duas buscas válidas confirmando `found=0`.
- Os testes dessa compatibilidade usam respostas simuladas. Ainda falta executar uma verificação controlada com os modelos/firmwares reais das escolas e observar a resposta completa de `findFile` e `findNextFile`.
- O traceback da terceira unidade terminou em `KeyboardInterrupt` durante a conexão TCP; o log indica interrupção manual, não uma resposta funcional da API.

## Estado atual da tolerância a falhas

- Timeouts, desconexões, respostas truncadas, corpos CGI inválidos e HTTP 408/425/429/5xx têm até três tentativas com espera de 1 e 2 segundos.
- Erros permanentes, como HTTP 401, não são repetidos como se fossem oscilação de rede.
- Se a consulta de um dia continuar inconclusiva após as tentativas, a escola é registrada como auditoria incompleta; o dia não é contado como vazio e não são gerados evidência ou ticket para aquele resultado parcial.
- A rotina registra o tipo da falha no log. Nunca gravar senhas, tokens ou cabeçalhos de autenticação.

## Próxima validação de campo

Em uma janela autorizada, validar primeiro um NVR por vez e comparar:

- status e corpo de `factory.create`;
- status e corpo de `findFile` tanto em data com gravação quanto em data sem gravação;
- status e corpo de `findNextFile` nos mesmos casos;
- comportamento de `close`;
- versão/modelo do NVR e data testada.

Registrar os corpos CGI sem credenciais e, se houver identificadores ou caminhos sensíveis, sanitizá-los antes de anexar ao diário. Não alterar a interpretação até confirmar o padrão dos firmwares envolvidos.
