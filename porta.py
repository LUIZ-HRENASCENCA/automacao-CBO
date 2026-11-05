"""Porta de salvamento: decide se o servidor pode salvar a conta apos o preenchimento.

Regras acordadas:
  * NAO salva se >= 50% dos itens tiverem problema NAO tolerado;
  * NAO salva se o processamento foi incompleto (menos itens tratados que o alvo);
  * erro critico / erro de Salux ou servidor: NAO salva (decidido por quem chama).
  * Tolerados (nao impedem salvar, mas continuam registrados): campo CBO vazio / sem opcao
    na lista e Prof = 1 (Hospital Renascenca). Ler a coluna Prof ainda nao foi provado:
    por enquanto todo "Campo CBO sem especialidade" e tratado como tolerado.
Toda conta, salva ou nao, segue para revisao manual.
"""
LIMITE_PROBLEMAS = 0.5
TOLERADOS = ("Campo CBO sem especialidade",)


def eh_tolerado(msg):
    return any(t.lower() in msg.lower() for t in TOLERADOS)


def avaliar(alvo, tratados, erros):
    """erros: lista de (linha, mensagem). Devolve (pode_salvar, motivo, n_toleradas, n_problemas)."""
    tol = [e for e in erros if eh_tolerado(e[1])]
    prob = [e for e in erros if not eh_tolerado(e[1])]
    if tratados < alvo:
        return False, f"Processamento incompleto: {tratados} de {alvo} itens.", len(tol), len(prob)
    if alvo and len(prob) / alvo >= LIMITE_PROBLEMAS:
        return (False, f"{len(prob)} de {alvo} itens com problema (limite de 50% atingido).",
                len(tol), len(prob))
    return (True, f"{len(tol)} item(ns) tolerado(s) e {len(prob)} com problema (abaixo de 50%).",
            len(tol), len(prob))
