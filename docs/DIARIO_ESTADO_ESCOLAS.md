# Diário de desenvolvimento do motor de auditoria

## Controle de estado das unidades

O arquivo `data/escolas.json` é a fonte da lista de unidades e do estado da última auditoria aprovada. Cada entrada contém o IP e os campos `status`, `concluida_em` e `proxima_auditoria_em`. Na migração inicial, as 46 unidades foram marcadas como `pendente`, com as datas nulas. O carregador ainda aceita o formato legado em que o valor da unidade era diretamente uma string com o IP.

Uma unidade só recebe `status: "aprovada"` depois de cumprir, na mesma execução, os três requisitos:

1. A API CGI do NVR responde à verificação de conectividade.
2. A captura do calendário retorna o caminho do print e o arquivo existe.
3. A automação do 7LAN conclui a OS: criada (redirecionamento para a listagem), print anexado e OS fechada. Uma OS criada e deixada aberta não aprova a escola (caso do CEAPI em 30/10/2026).

Sem qualquer um desses resultados, a execução não registra uma nova aprovação. Se a captura falhar, o ticket nem é iniciado. Se a OS não for concluída, a unidade continua apta para nova tentativa. Falha antes do clique em salvar a OS é repetida uma vez na mesma execução; depois do clique, a OS nunca é recriada automaticamente, para não duplicá-la, e o log indica que ela deve ser verificada e fechada no 7LAN.

## Datas e regra de liberação

- `concluida_em` registra a data e hora local com fuso no formato ISO 8601, no momento em que os três requisitos foram satisfeitos.
- `proxima_auditoria_em` recebe a mesma data e hora acrescida de 15 dias. O intervalo de 15 dias segue a cadência quinzenal já descrita pela sincronização da planilha.
- A unidade é pulada somente quando está aprovada e o instante atual é anterior a `proxima_auditoria_em`. Na data/hora de liberação ou depois dela, a unidade volta a ser auditada.
- Datas ausentes ou inválidas não bloqueiam a unidade: ela é processada novamente.

## Fluxo de execução e persistência

O motor avalia a elegibilidade antes de abrir uma sessão com o NVR. Unidades dentro da janela de espera são registradas no log como `[PULADA]`, não geram novo ticket e não entram nos resultados da execução enviados à planilha. Unidades elegíveis seguem a auditoria normal. Resultados incompletos da API e resultados `Verificar no local` não passam pelos três critérios e não recebem aprovação.

Ao concluir os três passos, o estado da unidade é atualizado em memória e escrito em `data/escolas.json` com substituição atômica por arquivo temporário, reduzindo o risco de corromper o mapa caso a execução seja interrompida durante a gravação. O Compose monta a pasta `data` como diretório gravável para que a substituição atômica funcione e o estado sobreviva ao encerramento do container.

## Resultado de cada tentativa

No fim de cada execução, depois da segunda passada, toda escola processada recebe no mesmo registro:

- `ultimo_resultado`: `aprovada`, `sem_rede`, `incompleta`, `verificar_no_local`, `falha_print`, `falha_os`, `falha_evidencia`, `falha_estado` ou `sem_data_para_print`.
- `motivo_falha`: rótulo da falha (por exemplo `ConnectTimeout`, `401`, `print não capturado`), ou `null` quando aprovada.
- `tentativas`: execuções seguidas sem aprovação; volta a 0 quando a escola é aprovada.
- `falhas_rede_seguidas`: execuções seguidas em que o NVR não respondeu por rede; volta a 0 quando o NVR responde.
- `ultima_tentativa_em`: data e hora local com fuso, em ISO 8601.

A segunda passada da mesma execução não conta como outra tentativa. Esses campos não mudam `status`, `concluida_em` nem `proxima_auditoria_em`, que continuam sendo a única regra para pular uma escola.

Este diário cobre persistência e controle de fluxo. Regras de compatibilidade dos endpoints CGI Dahua permanecem em `DIARIO_COMPATIBILIDADE_NVR.md`.
