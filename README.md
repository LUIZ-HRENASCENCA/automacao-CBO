# Automação de preenchimento de CBO no Salux

Preenche o campo **CBOS** da aba **Origem** da tela *Manutenção da Conta Paciente* (Salux · Faturamento) para os itens de procedimento de uma conta.

Existem dois modos de uso:

1. **Modo local (v1.0)** — um painel único que preenche a conta aberta na máquina (`painel_cbo.py`).
2. **Modo cliente/servidor (branch `dev`)** — um **servidor** com o Salux logado processa uma **fila de contas**; **painéis cliente** (operador e secretárias) enviam contas e recebem o resultado em tempo real. Já funciona completo em **simulação**; com o **Salux real** ainda **não salva** (ver "Estado atual").

> A automação preenche; **toda conta passa por revisão manual**, mesmo quando salva.

---

## Fluxo cliente/servidor

```
painel_cliente.py  (operador / secretárias)  <--TCP, JSON por linha, token-->  servidor_cbo.py
                                                                                 ├─ fila + logs (SQLite fila.db)
                                                                                 └─ worker (1 conta por vez)
                                                                                      ├─ WorkerSimulado (sem Salux)
                                                                                      └─ WorkerSalux (Salux real)
```

1. O **operador** digita o número da conta no painel cliente e envia.
2. O **servidor** valida (só dígitos, sem duplicata na fila/em processamento) e enfileira.
3. O **worker** pega uma conta por vez: (login + Faturamento, se preciso) → abre a conta pela consulta do Salux → filtra *Tipo de Item = Procedimento* → preenche os CBOs → **porta de salvamento** → salva ou não.
4. A cada linha, o servidor envia o log **em tempo real** aos painéis; ao concluir, avisa com o resumo.
5. A **secretária** confere a conta e clica em **Marcar como REVISADA** (fica registrado quem e quando).

### Como rodar (simulação na mesma máquina)

```bash
pip install -r requirements.txt
```

```bash
python painel_servidor.py
```

```bash
python painel_cliente.py
```

(ou `iniciar_servidor.bat` / `iniciar_cliente.bat`). O cliente aceita `--papel operador|secretaria|ambos`, `--usuario NOME` e `--servidor HOST`. Para simular duas pessoas, abra dois clientes com `--usuario` diferentes.

**Modo do worker** (escolhido no painel do servidor, lido a cada conta):
- **Simulado** (padrão): sem Salux. O **último dígito da conta** escolhe o cenário: `0` conta não encontrada · `9` erro crítico · `8` 50% ou mais de itens com problema · `7` só erros tolerados · demais: sucesso.
- **Salux real (não salva)**: faz login (`.env`), abre o Faturamento e processa de verdade. Como o salvamento ainda não está mapeado, **nunca salva**, deixa a conta aberta e **pausa a fila** depois de cada conta: confira/feche a conta no Salux e clique em **Retomar fila**.

### Painel do servidor
Fila com estados, log ao vivo, clientes conectados. Botões: **Pausar/Retomar fila**, **Parar conta atual**, **Reiniciar fila** (reenfileira todas as contas com falha crítica e retoma). O servidor mostra "PROCESSANDO — NÃO MEXA NA TELA".

### Painel do cliente
Campo da conta + **Enviar para a fila**, lista da fila, log em tempo real (o mesmo do servidor), aviso ao concluir cada conta, **Marcar como REVISADA**, duplo clique para abrir o log completo da conta. Reconecta sozinho se o servidor cair.

### Estados
**Conta:** `ENFILEIRADA` · `PROCESSANDO` · `SALVA` · `NAO SALVA` · `CONTA INVALIDA` · `FALHA CRITICA`.
**Revisão:** `AGUARDANDO REVISAO` (padrão, inclusive nas salvas) · `REVISADA`.
(Na tela os nomes aparecem sem underline; no banco continuam `NAO_SALVA` etc.)

### Porta de salvamento (`porta.py`)
- **Não salva** se: 50% ou mais dos itens tiverem problema **não tolerado**; processamento incompleto; erro crítico; erro no Salux ou no servidor.
- **Tolerados** (não impedem salvar, mas ficam registrados): campo CBO vazio/sem opção na lista e Prof = 1 (Hospital Renascença). *Ler a coluna Prof ainda não foi provado*: por ora todo "Campo CBO sem especialidade" é tolerado.
- Falha crítica **pausa a fila** (use **Reiniciar fila** depois de resolver a causa).

### Logs
- **Servidor:** SQLite `fila.db` (fonte da verdade: contas e eventos) + `logs/conta_<n>_<data>.txt` por conta.
- **Cliente que pediu a conta:** `logs_cliente/conta_<n>_<data>.txt` com **conteúdo idêntico** ao do servidor.
- Modo local (v1.0): `logs/execucao_<data>.txt`, `log_cbo.txt`, `log_cbo_resumo_<data>.txt`.

---

## Login automático e abertura do Faturamento (`salux_sessao.py`)

- `garantir_faturamento()` usa o Faturamento já aberto ou sobe `portal.exe` → login → azulejo **Faturamento**.
- O login lê **`USERNAME` e `SENHA` do arquivo `.env`** (lido direto do arquivo, pois `USERNAME` existe no Windows). Os valores **nunca são impressos nem gravados em log**. O `.env` está no `.gitignore`; restrinja a permissão dele ao usuário do Windows que roda a automação (em produção, o ideal é o Gerenciador de Credenciais do Windows).
- Sem `SENHA` no `.env` (ou com `--espera-login`), o script espera uma pessoa digitar o login.
- As posições dos campos de login e dos cliques do portal vêm do mapeamento da tela e dependem da escala/resolução (ver `config.py` e `salux_sessao.py`).

## Abrir a conta pelo número e filtrar procedimentos (`cbo_core.py`)

- **Abrir conta:** menu *Movimento → Manutenção da Conta Paciente (direto)* → botão de consulta (clique real) → *Cta = FIA*, *Sit. Cta = Aberta*, digita o número → botão executar a consulta. Confere que a conta carregou; avisos do Salux (conta não encontrada, em uso por outro usuário…) viram `CONTA INVALIDA`.
- **Filtro:** botão direito na grade de itens → *Filtrar* → *Tipo de Item = Procedimento* → OK; depois segue o fluxo de preenchimento.
- **Conta bloqueada:** se uma execução for interrompida com a conta aberta, o Salux mantém o bloqueio ("Informação está sendo atualizada pelo usuário…"). Sempre feche a conta ao terminar.

## Modo local (v1.0)

```bash
python painel_cbo.py
```
O painel agora tem campo **Nº da conta**, **Máx. itens (teste)** e a opção de **entrar no Salux automaticamente** (login do `.env`). Sem número de conta, usa a conta já aberta na aba Itens. Pelo terminal: `python preencher_cbo.py [--login | --espera-login] [--conta N] [max_itens]`. **Não salva nada.**

### Regras de preenchimento
- CBOS **já preenchido** → pula. CBOS vazio → clica na seta e escolhe a **primeira opção**.
- Lista sem opções (sem Prof ou profissional sem CBO vinculado) → `ERRO linha N: Campo CBO sem especialidade para preencher` e segue.
- Se o Salux recusar o CBO ("Código CBO inválido [2]…"), ele limpa o campo; o erro é registrado com a linha.
- **Erros críticos (a automação para):** Salux fechou/travou, aviso com termos de banco/rede/internet/DataWindow/SQL/sessão (`config.PALAVRAS_CRITICAS`), quantidade de itens mudou no meio, exceção inesperada.

---

## Arquivos

| Arquivo | Função |
|---|---|
| `cbo_core.py` | Núcleo: abrir conta, filtro, navegação, preenchimento, classificação de erros |
| `salux_sessao.py` | Portal, login (`.env`) e abertura do Faturamento |
| `servidor_cbo.py` | Servidor: rede, fila, worker serial, logs, reiniciar fila |
| `workers.py` | `WorkerSimulado` e `WorkerSalux` |
| `porta.py` | Regra de salvamento (tolerados vs. problemas, limite de 50%) |
| `banco.py` | SQLite: contas e eventos |
| `protocolo.py` | Mensagens JSON por linha e nomes legíveis de estado |
| `cliente_rede.py` | Conexão do cliente com reconexão automática |
| `painel_servidor.py` / `painel_cliente.py` | Painéis tkinter do servidor e do cliente |
| `painel_cbo.py` / `preencher_cbo.py` | Modo local (painel e terminal) |
| `mapear_tela.py` | Mapeador somente-leitura de telas do Salux (`observar` / `snap`) |
| `teste_fluxo_simulado.py` | Teste automático do fluxo cliente/servidor (sem Salux) |
| `config.py` | Parâmetros: janela, posições, portal, servidor/porta/token |
| `iniciar_*.bat` | Atalhos |

Teste automático (sem Salux nem interface): `python teste_fluxo_simulado.py` (fila, duplicatas, token, cenários, pausa em falha crítica, reiniciar fila, revisão e log idêntico nos dois lados).

## Mudanças nesta versão (branch `dev`, desde a v1.0)

- Abrir a conta pelo número (consulta do Salux) e filtrar procedimentos.
- Login automático e abertura do Faturamento pelo portal; `.env` (credenciais) fora do git.
- Painel local com nº da conta, limite de itens e login automático.
- **Arquitetura cliente/servidor:** fila em SQLite, worker serial, push em tempo real, painéis do servidor e do cliente, revisão manual, logs idênticos no servidor e no cliente, **Reiniciar fila**.
- Porta de salvamento e estados de conta/revisão; worker simulado para testar o fluxo inteiro.
- Mapeador de telas (`mapear_tela.py`).

## Estado atual e limitações

- **Salvar no Salux não está implementado.** Modo Salux real: a conta fica aberta e a fila pausa a cada conta. Falta mapear o botão de salvar e o fechamento da conta (o Salux pergunta algo ao fechar com alterações) para processar várias contas seguidas.
- O **login automático** foi corrigido (posições dos campos) mas **ainda não foi validado de ponta a ponta**.
- **Prof = 1** ainda não é lido (coluna Prof); por ora, todo CBO sem opção é tolerado.
- Servidor: **token fixo** em `config.py` e rede só local (`127.0.0.1`). Antes de produção: trocar o token, liberar o bind na rede interna, usuário dedicado no Salux, sessão do Windows interativa e desbloqueada (logon automático, resolução e escala fixas; não roda como serviço nem com RDP desconectado).
- Posições de cliques dependem de escala de tela/layout; uma atualização do Salux pode exigir recalibrar.
- Confira sempre a aba Origem: o texto lido do editor pode ser enganoso.

## Histórico técnico (v1.0)

1. **Mapeamento.** O Salux é **PowerBuilder 32 bits**; só o backend `win32` do pywinauto enxerga a tela. As abas Itens/Origem ficam em `PBTabControl32_100`; a coluna **CBOS** é célula de DataWindow (só a célula ativa expõe um `Edit`).
2. **Navegação.** Cliques na grade não trocam de linha, mas as **setas ↑/↓ na aba Itens** sim; o rótulo "Item N de M" informa a linha. O editor do CBOS é achado pela **largura**.
3. **Escolha do CBO.** A tecla ↓ era instável; funciona **clique real** na seta do dropdown e na primeira opção. (Um filtro de altura errado fazia listas com várias opções parecerem vazias — corrigido.)
4. **Armadilhas.** **Tab** na última célula cria item em branco (o script nunca avança além do CBOS); o Salux valida o CBO ao **sair da célula** (aviso atribuído à linha anterior); teclas dependem de foco real; leitura do editor pode vir de outra linha (travas de linha ativa e total de itens).
5. **Testes reais (nada salvo pela automação).** Contas de 152 e 101 itens (8 min 10 s) sem CBO inválido; itens já preenchidos preservados.
