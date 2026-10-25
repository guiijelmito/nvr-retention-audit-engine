# Regras do projeto

Fonte única das regras de negócio, de execução e de lógica do motor de auditoria. Quando uma regra mudar, atualize este arquivo no mesmo commit que muda o código. Cada regra indica de onde vem: **Decisão** (definida pelo Gui), **Código** (comportamento atual implementado) ou **Compatibilidade** (imposta pelos NVRs legados).

Detalhes técnicos de compatibilidade ficam em `DIARIO_COMPATIBILIDADE_NVR.md`; o fluxo de estado das escolas está explicado em `diario.md`.

## 1. Contagem de dias contínuos de gravação

1.1. **Decisão.** O resultado da auditoria é a quantidade de dias contínuos com gravação, contados de ontem para trás. O dia de hoje não entra.

1.2. **Decisão.** Um dia sem gravação interrompe a continuidade: se quinta tem gravação, sexta não e sábado tem, a gravação contínua termina na quinta.

1.3. **Decisão.** A contagem só é encerrada depois de **3 dias vazios seguidos** (`LIMITE_BURACO = 3`). A tolerância de 1 ou 2 dias vazios é uma salvaguarda proposital contra falso dia vazio, quando uma resposta HTTP se perde e o NVR parece não ter arquivo. Não é bug e não deve ser removida.

1.4. **Código.** Dias vazios não somam na contagem. A data da gravação mais antiga é o último dia com gravação antes dos 3 dias vazios seguidos.

1.5. **Código.** A busca vai até 730 dias para trás (`LIMITE_DIAS = 730`).

1.6. **Código.** Só o canal 1 de cada NVR é auditado hoje.

1.7. **Código.** Um dia tem gravação quando a busca de arquivos `dav` entre 00:00:00 e 23:59:59 daquele dia retorna pelo menos um arquivo.

## 2. Dia vazio, falha e resultado inconclusivo

2.1. **Compatibilidade.** Um dia só é considerado vazio quando **duas buscas completas e válidas** respondem `found=0`. Uma busca só não basta.

2.2. **Compatibilidade.** Timeout, queda de conexão, erro HTTP inesperado, resposta truncada ou corpo que não seja `found=N` / `items[n].` **nunca** contam como dia vazio. O dia fica inconclusivo.

2.3. **Código.** Falhas temporárias (timeout, conexão, HTTP 408/425/429/5xx, resposta CGI inválida) são repetidas até 3 vezes, com espera de 1 s e depois 2 s.

2.4. **Código.** Senha recusada (HTTP 401) não é repetida como se fosse instabilidade de rede.

2.5. **Código.** Se um dia continua inconclusivo depois das tentativas, a auditoria daquela escola para e o resultado é "Verificação incompleta (falha da API)". Não há print, nem chamado, nem aprovação.

2.6. **Código.** Se a API do NVR não responde no início, o resultado é "Verificação incompleta (API indisponível)".

2.7. **Código.** Se o primeiro trecho já tem 3 dias vazios seguidos (zero dias contínuos), o resultado é "Verificar no local".

## 3. Comunicação com os NVRs

3.1. **Compatibilidade.** NVRs Dahua legados, acessados pela API CGI HTTP com autenticação Digest.

3.2. **Compatibilidade.** O fluxo de busca é `factory.create` → `findFile` → `findNextFile` → `close`, e o token sempre é fechado, mesmo em caso de erro.

3.3. **Compatibilidade.** HTTP 400 é aceito **somente** no passo `findFile` (firmwares antigos respondem assim em busca sem resultado). Quem decide se o dia está vazio é o `findNextFile`.

3.4. **Compatibilidade.** Não alterar endpoints, parâmetros, formato de data, codificação da URL, autenticação ou timeouts sem evidência em equipamento real e teste automatizado reproduzindo a resposta.

3.5. **Código.** Timeout de 5 s para conectar e 20 s para ler cada resposta.

3.6. **Regra de segurança.** Nunca registrar senhas, tokens ou cabeçalhos de autenticação em log, relatório ou repositório.

## 4. Evidência, chamado e aprovação da escola

4.1. **Código.** Para uma escola ser **aprovada**, os três passos precisam dar certo na mesma execução:
   1. a API do NVR respondeu e a auditoria ficou completa;
   2. o print do calendário do mês da gravação mais antiga foi salvo e o arquivo existe;
   3. o chamado no 7LAN foi criado (confirmado pelo redirecionamento para a lista de tickets).

4.2. **Código.** Se o print falhar, o chamado não é aberto. Se o chamado não for confirmado, a escola não é aprovada e entra de novo na próxima execução.

4.3. **Código.** O chamado se chama "Controle de gravação - <escola>", recebe o print como anexo e um apontamento de 2 minutos com o texto "Verificado a gravação das câmeras no NVR. Ok.", e é fechado.

4.4. **Código.** O print é salvo como `<escola>_<dd-mm-aaaa>.png` na pasta de evidências (`PASTA_EVIDENCIAS`).

4.5. **Código.** Escola aprovada recebe `status: "aprovada"`, `concluida_em` e `proxima_auditoria_em` em `data/escolas.json`. A gravação do arquivo é atômica (arquivo temporário + substituição).

4.6. **Decisão pendente.** Hoje a escola é aprovada assim que o chamado é criado, mesmo se o anexo ou o fechamento falharem depois. Avaliar se a aprovação deve exigir o chamado fechado.

## 5. Agenda das auditorias

5.1. **Decisão.** A cadência é quinzenal: uma escola aprovada só é auditada de novo **15 dias** depois da aprovação (`INTERVALO_AUDITORIA_DIAS = 15`).

5.2. **Código.** Escola dentro da janela de 15 dias aparece no log como `[PULADA]`, não gera chamado e não vai para a planilha naquela execução.

5.3. **Código.** Data ausente ou inválida não bloqueia a escola: ela é auditada.

## 6. Planilha (Google Sheets)

6.1. **Código.** Planilha "Gravações escolas 2026", aba "Gravações Quinzenais 2026".

6.2. **Código.** Colunas fixas: "Escola", "IP do NVR" e "Último dia de gravação". Cada execução cria (ou atualiza) a coluna "Dias Contínuos de Gravação: dd/mm/aaaa" com o resultado do dia.

6.3. **Código.** Só as escolas processadas naquela execução são atualizadas. As outras mantêm os valores anteriores.

## 7. Lista de escolas e configuração

7.1. **Código.** A lista oficial fica em `data/escolas.json` (46 unidades). Aceita o formato antigo `{"Escola": "ip"}` e o formato com estado `{"Escola": {"ip": ..., "status": ..., ...}}`. Unidade sem IP válido é ignorada com aviso no log.

7.2. **Regra de segurança.** Credenciais ficam só no `.env` (NVR, 7LAN) e em `credenciais.json` (Google). Nenhum desses arquivos, nem `data/escolas.json`, vai para o repositório.

## 8. Firmware dos NVRs

8.1. **Decisão.** O firmware de cada NVR é inventariado para personalizar e direcionar as automações por versão de firmware.

8.2. **Código.** O inventário (`nvr_firmware.py`) consulta o `magicBox.cgi` e registra modelo, versão, build, hardware e número de série. Tenta Digest e, se o NVR só aceitar Basic, usa Basic.

8.3. **Código.** O relatório do inventário vai para `relatorios_firmware/`, que não é versionado.

8.4. **Regra de segurança.** O inventário só lê informações. Atualizar firmware ou mudar configuração do NVR só com autorização explícita e em janela combinada.

## 9. Testes e ambiente de desenvolvimento

9.1. **Compatibilidade.** Toda mudança na comunicação com o NVR precisa de teste automatizado reproduzindo a resposta observada e, quando possível, validação em um NVR real de cada modelo/firmware afetado.

9.2. **Regra de execução.** A auditoria completa cria chamados e escreve na planilha. Para depurar, usar o `devtools.py`, que usa estado separado (`data/devtools_escolas.json`) e pede confirmação antes de criar ou fechar chamado.

9.3. **Regra de execução.** Validações em campo devem ser feitas um NVR por vez.
