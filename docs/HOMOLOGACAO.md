# Roteiro de homologação (2 máquinas)

**Servidor** = a máquina com o Salux (roda a partir do código Python).
**Cliente** = outra máquina, instalada com o executável `PainelCliente` (sem Python).
As duas estão no mesmo domínio e a comunicação já é liberada (sem abrir portas). Porta padrão: **8765**.

## 0. Gerar o pacote do cliente (na máquina de desenvolvimento)

```bash
python empacotar_cliente.py
```
(ou `empacotar_cliente.bat`). Resultado: `dist\PainelCliente_<versao>.zip` (~11 MB). O pacote **não** leva token, `.env`, pywinauto nem código do Salux. Copie o zip para a máquina cliente.

## 1. Servidor (esta máquina)

1. Sessão do Windows **desbloqueada**, Salux fechado ou na tela inicial do Faturamento, resolução/escala como nos testes.
2. Abra o painel:
   ```bash
   python painel_servidor.py
   ```
3. No topo aparece **"Informe aos clientes → Servidor: `<IP>:8765`  Token: `<token>`"**. O token é gerado na primeira execução e guardado em `servidor_config.json` (não vai para o git). Use **Copiar token** para enviar ao cliente.
4. Deixe em **Simulado** no primeiro teste.
5. **IP:** recomenda-se IP fixo/reserva DHCP para esta máquina (hoje `10.10.10.249`). Se mudar, basta trocar o endereço na tela de configuração do cliente (ou usar o nome da máquina).

## 2. Cliente (outra máquina)

1. Extraia o zip **inteiro** em uma pasta com permissão de escrita, ex.: `C:\CBO\PainelCliente`.
2. Abra `PainelCliente.exe`. Na primeira vez abre **Configurar servidor**: IP/endereço (padrão `10.10.10.249`), porta (`8765`), **token**, seu usuário e papel.
3. **Testar conexão** → deve mostrar "Conexão OK". Depois **Salvar e conectar**: faixa verde "Conectado ao servidor".
4. No servidor, a barra de baixo passa a listar o cliente (usuário, papel, versão).

## 3. Testes

**Etapa A — Simulado (sem tocar no Salux).** No cliente, envie contas e confira fila, log em tempo real, aviso ao concluir e `logs_cliente\`:

| Conta | Resultado esperado |
|---|---|
| `11111` | Sucesso → SALVA (simulado) |
| `11117` | Só erros tolerados → SALVA |
| `11118` | 50% ou mais com problema → NAO SALVA |
| `11110` | Conta não encontrada → CONTA INVALIDA |
| `11119` | Erro crítico → FALHA CRITICA e a fila **pausa** (no servidor: **Reiniciar fila**) |

Confira também: conta duplicada é recusada; **Marcar como REVISADA** funciona; o log do cliente (`logs_cliente\`) é idêntico ao do servidor (`logs\`); fechar e reabrir o cliente reconecta sozinho.

**Etapa B1 — Salux real, sem salvar (uma conta).** No servidor marque **"Salux real (salva e fecha a conta)"** e preencha **máx. itens = 5**: com limite de itens o servidor **nunca salva** (conta parcial). Envie **uma** conta de teste (Sit. Cta = Aberta, sem bloqueio de outro usuário). O servidor faz login (`.env`), abre o Faturamento, a conta e o filtro e preenche os CBOs; a conta fica aberta e a fila pausa. Confira a aba Origem, feche a conta no Salux e use **Retomar fila**.

**Etapa B2 — Salux real, salvando.** **Somente com uma conta de teste/paciente de teste** (isto grava em produção). Deixe **máx. itens vazio**. O servidor salva, responde *Sim* ao aviso de valores zerados e fecha a tela da conta; a fila segue sozinha. Confira a conta depois no Salux (revisão manual).
Durante o processamento **não mexa na tela do servidor**.

## 4. Problemas comuns

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| "O servidor RECUSOU a conexão" | Token incorreto | Copiar o token do painel do servidor em **Configurar servidor** |
| "SEM CONEXÃO" / "Sem resposta do servidor" | Painel do servidor fechado, IP mudou, bloqueio de rede | **Testar conexão**; conferir IP/porta; abrir o painel do servidor |
| "Conexão recusada" | Servidor não está escutando essa porta | Conferir a porta no painel do servidor |
| Antivírus/SmartScreen bloqueia o `.exe` | Executável sem assinatura digital | Pedir à TI para liberar a pasta do cliente |
| Painel fecha sozinho | Erro inesperado | Enviar `erro_cliente.txt` (ao lado do `.exe`) |
| Conta processada mas a fila não anda | Fila **pausada** (falha crítica ou modo Salux real) | No servidor: **Retomar fila** / **Reiniciar fila** |
| Conta "em uso" no Salux | Bloqueio de concorrência de execução anterior | Fechar a conta no Salux; se persistir, pedir à TI a limpeza do controle de concorrência |

## 5. Limitações desta homologação
- O **salvamento no Salux foi implementado mas ainda não validado de ponta a ponta**: use só conta de teste na Etapa B2. **Descartar** uma conta não salva (responder *Não* ao fechar) ainda não está mapeado: nesses casos a conta fica aberta e a fila pausa.
- Token em arquivo (texto) e tráfego **sem criptografia**: apenas rede interna.
- O servidor exige sessão do Windows interativa e desbloqueada enquanto processa.
