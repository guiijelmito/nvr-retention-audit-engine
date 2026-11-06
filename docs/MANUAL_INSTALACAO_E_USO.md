# Manual de instalação e uso do NVR audit engine

Guia para instalar, atualizar e rodar a auditoria de retenção dos NVRs num PC Windows (por exemplo, o PC da GCM).

Branch em uso: **`fix/print-calendario`**
Repositório: `https://github.com/guiijelmito/nvr-retention-audit-engine`

---

## 1. Programas necessários

Só são necessários **Git** e **Python 3.12**. O resto o próprio projeto instala.

### Opção rápida: winget (Windows 10/11)

Abra o PowerShell e rode:

```powershell
winget install --id Git.Git -e --source winget
winget install --id Python.Python.3.12 -e --source winget
```

**Feche e abra o PowerShell de novo** e confira:

```powershell
git --version
python --version
```

### Opção manual (se o winget estiver bloqueado)

- **Git:** https://git-scm.com/download/win. Use o instalador 64-bit e aceite as opções padrão ("Next" em tudo).
- **Python 3.12:** https://www.python.org/downloads/windows/. Escolha a versão 3.12 mais recente, "Windows installer (64-bit)". Na primeira tela, marque **"Add python.exe to PATH"**.

Se a instalação pedir senha de administrador e você não tiver, é preciso uma alternativa sem admin.

---

## 2. Primeira instalação do projeto (uma vez só)

No PowerShell:

```powershell
cd "C:\Users\<usuário>\Desktop"
git clone https://github.com/guiijelmito/nvr-retention-audit-engine.git auditoria_NVR_escolas
cd auditoria_NVR_escolas
git checkout fix/print-calendario
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium
```

- No primeiro `git clone` ou `git pull`, o Git abre a tela de login do GitHub no navegador. Depois de logar uma vez, ele não pergunta mais.
- O `python -m playwright install chromium` baixa o navegador usado para o print do calendário e para o 7LAN. Sem ele, a captura falha.

### Arquivos que não vêm pelo GitHub

Copie do PC atual para a pasta do projeto:

| Arquivo | Para que serve |
|---|---|
| `.env` | Usuário e senha dos NVRs e do 7LAN, e pasta de evidências |
| `credenciais.json` | Conta de serviço do Google Sheets |
| `data\escolas.json` | Lista das escolas, IPs e estado das auditorias |

No `.env`, use **caminho absoluto** para as evidências, por exemplo:

```
PASTA_EVIDENCIAS=C:\Users\<usuário>\Pictures\Evidencias_NVR_escolas
```

### Rede

O PC precisa estar na mesma rede ou VPN que alcança os NVRs (`172.16.x.x`).

---

## 3. Ativar o ambiente virtual (venv)

Toda vez que abrir um PowerShell novo para rodar o projeto:

```powershell
cd "C:\Users\<usuário>\Desktop\auditoria_NVR_escolas"
.\.venv\Scripts\Activate.ps1
```

Quando estiver ativo, aparece `(.venv)` no começo da linha. Para sair do venv, rode `deactivate`.

Se aparecer erro de "execução de scripts desabilitada", libere uma vez:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

> No PC atual (`HP 800 G3`), o venv fica **uma pasta acima** do projeto:
> ```powershell
> cd "C:\Users\HP 800 G3\Desktop\auditoria_NVR_escolas"
> .\.venv\Scripts\Activate.ps1
> cd .\auditoria_NVR_escolas
> ```

---

## 4. Trazer as atualizações (pull)

### Pelo PowerShell

```powershell
git status
git stash
git fetch origin
git checkout fix/print-calendario
git pull origin fix/print-calendario
git log --oneline -4
```

- `git status`: mostra se há alterações locais. Se aparecer "nothing to commit", pode pular o `git stash`.
- `git log --oneline -4`: confere se os commits mais recentes chegaram.
- Para voltar para a branch principal depois: `git checkout feat/otimizacao-auditoria-nvr`. Se você usou o stash, rode `git stash pop` em seguida.

### Atalho de dois cliques (recomendado)

Crie o arquivo `atualizar_auditoria.bat` na área de trabalho com este conteúdo, ajustando o caminho:

```bat
@echo off
cd /d "C:\Users\<usuário>\Desktop\auditoria_NVR_escolas"
git fetch origin
git checkout fix/print-calendario
git pull origin fix/print-calendario
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
git log --oneline -3
pause
```

- Se o venv ficar uma pasta acima do projeto (como no PC atual), troque `.venv` por `..\.venv`.
- O `pip install` só demora quando alguma dependência mudou.
- O pull só falha se houver alteração local em arquivos do projeto. `.env`, `credenciais.json` e `data\escolas.json` não contam, porque não são versionados.

---

## 5. Rodar a auditoria

Com o venv ativo, na pasta do projeto:

```powershell
python main.py
```

A auditoria completa consulta os NVRs, tira o print do calendário, abre e fecha a OS no 7LAN, atualiza `data\escolas.json` e envia os resultados para a planilha "Gravações escolas 2026".

Cuidados:
- Rode de dia, longe da meia-noite (a data do print e a do anexo precisam ser a mesma).
- Antes de uma execução grande, vale fazer uma cópia da aba "Gravações Quinzenais 2026".
- Uma escola pode levar alguns minutos, principalmente com rede instável. Antes de interromper com Ctrl+C, espere pelo menos 2 minutos sem log novo.
- Escolas aprovadas ficam **puladas por 15 dias** (`[PULADA]` no log).

O log fica em `logs\auditoria_NVR_escolas.log`.

---

## 6. Testar uma escola pelo devtools

Para validar uma escola sem afetar a auditoria normal:

```powershell
python devtools.py
```

1. Em "Quais unidades deseja executar?", escolha **2** (uma unidade por IP) e digite o IP, por exemplo `172.16.11.2`.
2. Em "O que deseja testar?":
   - **1**: auditoria completa (dias, print e fluxo da OS);
   - **2**: só o print do calendário (pede ano e mês).
3. Quando ele perguntar se quer criar ou fechar a OS, responda **n** para só testar. Responda **s** para gerar a OS de verdade.

O devtools salva o estado em `data\devtools_escolas.json`, separado da execução normal. Uma escola testada por ele não fica aprovada nem pulada na auditoria normal.

---

## 7. Problemas comuns

| Sintoma | O que fazer |
|---|---|
| `Executable doesn't exist` no Playwright | `python -m playwright install chromium` |
| "API do NVR indisponível" / `ConnectTimeout` | Rede: `ping <ip>` e `Test-NetConnection <ip> -Port 80` |
| "Verificar no local" | O NVR respondeu que não há gravação no canal 1 nos últimos 3 dias. Confira o calendário no NVR. |
| `401` no meio da contagem | O script já renova a sessão e repete o dia uma vez. Se persistir, teste a escola pelo devtools. |
| Erro de "execução de scripts desabilitada" | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `git pull` recusado por alteração local | `git stash` e depois o pull de novo |
