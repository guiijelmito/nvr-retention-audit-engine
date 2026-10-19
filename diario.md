# Diário de desenvolvimento do motor de auditoria

## Controle de estado das unidades

O arquivo `data/escolas.json` é a fonte da lista de unidades e do estado da última auditoria aprovada. Cada entrada contém o IP e os campos `status`, `concluida_em` e `proxima_auditoria_em`. Na migração inicial, as 46 unidades foram marcadas como `pendente`, com as datas nulas. O carregador ainda aceita o formato legado em que o valor da unidade era diretamente uma string com o IP.

Uma unidade só recebe `status: "aprovada"` depois de cumprir, na mesma execução, os três requisitos:

1. A API CGI do NVR responde à verificação de conectividade.
2. A captura do calendário retorna o caminho do print e o arquivo existe.
3. A automação do 7LAN confirma a criação do ticket após o redirecionamento para a listagem de tickets.

Sem qualquer um desses resultados, a execução não registra uma nova aprovação. Se a captura falhar, o ticket nem é iniciado. Se a criação do ticket não puder ser confirmada, a unidade continua apta para nova tentativa.

## Datas e regra de liberação

- `concluida_em` registra a data e hora local com fuso no formato ISO 8601, no momento em que os três requisitos foram satisfeitos.
- `proxima_auditoria_em` recebe a mesma data e hora acrescida de 15 dias. O intervalo de 15 dias segue a cadência quinzenal já descrita pela sincronização da planilha.
- A unidade é pulada somente quando está aprovada e o instante atual é anterior a `proxima_auditoria_em`. Na data/hora de liberação ou depois dela, a unidade volta a ser auditada.
- Datas ausentes ou inválidas não bloqueiam a unidade: ela é processada novamente.

## Fluxo de execução e persistência

O motor avalia a elegibilidade antes de abrir uma sessão com o NVR. Unidades dentro da janela de espera são registradas no log como `[PULADA]`, não geram novo ticket e não entram nos resultados da execução enviados à planilha. Unidades elegíveis seguem a auditoria normal. Resultados incompletos da API e resultados `Verificar no local` não passam pelos três critérios e não recebem aprovação.

Ao concluir os três passos, o estado da unidade é atualizado em memória e escrito em `data/escolas.json` com substituição atômica por arquivo temporário, reduzindo o risco de corromper o mapa caso a execução seja interrompida durante a gravação. O Compose monta a pasta `data` como diretório gravável para que a substituição atômica funcione e o estado sobreviva ao encerramento do container.

Este diário cobre persistência e controle de fluxo. Regras de compatibilidade dos endpoints CGI Dahua permanecem em `DIARIO_COMPATIBILIDADE_NVR.md`.
