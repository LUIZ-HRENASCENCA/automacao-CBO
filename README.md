# Automação de preenchimento de CBO no Salux (v1.0)

Preenche o campo **CBOS** da aba **Origem** da tela *Manutenção da Conta Paciente* (Salux · Faturamento) para todos os itens de uma conta aberta. **Não salva nada**: a conferência e o salvamento continuam manuais.

## Como usar

Requisitos: Windows, Python 3.12, Salux (`faturam.exe`) aberto e logado.

```bash
pip install -r requirements.txt
```

1. No Salux, abra a conta e deixe-a na aba **Itens**.
2. Dê duplo clique em `iniciar_painel.bat` (ou `python painel_cbo.py`).
3. Clique em **Iniciar automação**, leia as orientações e confirme.
4. **Não use mouse nem teclado** até o painel avisar que a tela está liberada.
5. Confira a aba Origem e salve manualmente no Salux.

Pelo terminal (sem painel): `python preencher_cbo.py [max_itens]`.

### Regras de preenchimento
- CBOS **já preenchido** → pula.
- CBOS vazio → clica na seta do dropdown e escolhe a **primeira opção** da lista.
- Lista sem opções (sem Prof ou profissional sem CBO vinculado) → registra `ERRO linha N: Campo CBO sem especialidade para preencher` e segue.
- Se o Salux recusar o CBO ("Código CBO inválido [2]…"), ele limpa o campo; o erro é registrado com a linha.

### Erros críticos (a automação para)
O Salux fechou/travou, aviso do Salux com termos de banco/rede/internet/DataWindow/SQL/sessão (lista em `config.py` → `PALAVRAS_CRITICAS`), quantidade de itens mudou no meio da execução, ou exceção inesperada. O aviso crítico fica aberto na tela, sem a automação clicar nele.

### Logs
- Painel: log ao vivo com cores (info, sucesso, aviso, erro, crítico).
- `logs/execucao_<data>.txt`: todas as mensagens do painel.
- `log_cbo.txt`: uma linha por item (`PREENCHIDO`, `PULADO…`) + resumo + tempo.
- `log_cbo_resumo_<data>.txt`: resumo por faixas de itens (incluídos, já tinham, sem opção, inválidos, não processados) + erros por linha.
- Os itens são identificados pelo **número da linha** (a descrição do procedimento não é legível pela automação).

## Arquivos

| Arquivo | Função |
|---|---|
| `cbo_core.py` | Núcleo: navegação no Salux, classificação de erros, logs |
| `painel_cbo.py` | Painel (tkinter) com botão, orientações, log e aviso de conclusão |
| `preencher_cbo.py` | Uso pelo terminal (chama o núcleo) |
| `config.py` | Parâmetros: janela, posições das abas, largura da coluna CBOS, palavras de erro crítico |
| `iniciar_painel.bat` | Atalho para abrir o painel |

## Histórico do que foi feito até a v1.0

1. **Mapeamento da tela.** O Salux é **PowerBuilder 32 bits**. Só o backend `win32` do pywinauto enxerga a tela (UIA vê quase nada). As abas Itens/Origem são painéis dentro do controle `PBTabControl32_100`. A coluna **CBOS** é uma célula de **DataWindow**: o Windows só expõe um `Edit` temporário para a célula ativa.
2. **Navegação.** Cliques do mouse na grade não trocam de linha, mas as **setas ↑/↓ na aba Itens** sim; o rótulo "Item N de M" informa a linha ativa. A mesma linha fica ativa ao abrir a aba Origem. O editor do CBOS é achado pela **largura** (a grade pode estar rolada na horizontal).
3. **Escolha do CBO.** A tecla ↓ só funcionava às vezes (e já gerou leitura enganosa). O que funciona de forma repetível é **clicar com o mouse real** na seta do dropdown e na primeira opção da lista. A lista com mais de uma opção é mais alta; um filtro de altura que só aceitava uma linha fazia o script achar que não havia opções (corrigido).
4. **Armadilhas encontradas.**
   - **Tab** na última célula da última linha **cria um item novo em branco**; o script nunca avança além do CBOS.
   - O Salux valida o CBO **ao sair da célula** (aviso "Código CBO inválido [2]" e limpeza do campo); o aviso é atribuído à linha anterior.
   - Teclas enviadas à grade dependem de **foco real**; o editor da Origem guarda o teclado mesmo com a aba trocada.
   - Leitura do texto do editor pode vir de outra linha: há travas (linha ativa, total de itens).
5. **Resultados dos testes (contas reais, nada salvo pela automação).** Conta com 152 itens e conta com 101 itens (**8 min 10 s**) processadas sem aviso de CBO inválido; itens já preenchidos foram preservados.
6. **Painel + tratamento de erros (v1.0).** Interface de um botão com orientação "não mexer na tela", log ao vivo, erros por linha, parada em erro crítico, logs em texto e aviso de conclusão com liberação da tela. Testado sem tocar no Salux: classificação de avisos, erro crítico simulado e painel com automação falsa. **A execução completa do painel contra o Salux ainda precisa ser validada.**

## Limitações conhecidas
- Depende de **sessão de Windows interativa e desbloqueada** (controla mouse e teclado reais; não roda como serviço nem com RDP desconectado).
- Posições das abas, largura da coluna CBOS e cliques relativos dependem de **escala de tela/fonte/layout**; uma atualização do Salux pode quebrar a automação (recalibrar em `config.py`).
- Não distingue "Prof vazio" de "Prof sem CBO vinculado" (ambos viram erro de linha).
- A conta precisa estar **aberta na aba Itens**; abrir a conta pelo número não está implementado.
- Texto lido do editor pode ser enganoso; **confira a aba Origem antes de salvar**.

## Próximos passos (ideias)
- Rodar numa máquina servidora com usuário/permissões dedicados no Salux (checklist: sessão interativa com logon automático, resolução e escala fixas, piloto com conferência de todas as linhas).
- Reduzir a dependência de pixels (seleção de aba por mensagem, coluna CBOS pelo cabeçalho, autoteste de layout ao iniciar).
- Avaliar com o fornecedor do Salux preenchimento automático do CBO, API ou importação em lote.
