"""Workers do servidor: quem de fato processa uma conta.

Interface:
  executar(conta, log, parar) -> dict(estado, mensagem, total, alvo, tratados, preenchidos,
                                      ja, erros[(linha,msg)], tempo)
      estado: CONCLUIDO | CONCLUIDO_COM_ERROS | CONTA_INVALIDA | CRITICO | INTERROMPIDO
  salvar(conta, log) -> (salvou: bool, motivo: str)
  pausar_apos: se True o servidor pausa a fila depois de cada conta.

WorkerSimulado: sem Salux, para testar fila, painéis e logs. O ULTIMO DIGITO da conta escolhe o cenario:
  0 conta nao encontrada | 9 erro critico (queda de conexao) | 8 >=50% de itens com problema
  7 so erros tolerados (campo CBO vazio) - salva | demais: sucesso
WorkerSalux: usa o Salux de verdade (login, Faturamento, cbo_core.executar). Se a porta de
  salvamento liberar: clica Salvar (responde SIM a "Existem valores zerados...") e fecha a tela da
  conta. Com "max. itens" definido (teste) nao salva. Se nao salvar, a conta fica aberta e a fila pausa.
"""
import random
import threading
import time


def _vazio(estado, mensagem=""):
    return {"estado": estado, "mensagem": mensagem, "total": 0, "alvo": 0, "tratados": 0,
            "preenchidos": 0, "ja": 0, "erros": [], "tempo": "00:00:00"}


def _tempo(t0):
    s = int(time.time() - t0)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


class WorkerSimulado:
    nome = "Simulado"
    pausar_apos = False

    def __init__(self, velocidade=1.0):
        self.v = velocidade  # 1.0 = ritmo normal; 0.01 = quase instantaneo (testes)

    def _dorme(self, s):
        time.sleep(s * self.v)

    def executar(self, conta, log, parar):
        t0 = time.time()
        ult = conta[-1]
        rnd = random.Random(int(conta))
        log("info", f"Abrindo a conta {conta} pela consulta do Salux (Cta=FIA, Sit. Cta=Aberta)...")
        self._dorme(1.5)
        if ult == "0":
            log("erro", "ERRO: conta nao aberta - Conta nao encontrada com Sit. Cta=Aberta.")
            r = _vazio("CONTA_INVALIDA", "Conta nao encontrada com Sit. Cta=Aberta.")
            r["tempo"] = _tempo(t0)
            return r
        log("ok", f"Conta {conta} aberta.")
        total = 8 + int(conta) % 13
        log("info", "Filtrando os itens: Tipo de Item = Procedimento...")
        self._dorme(1.0)
        log("ok", f"Filtro aplicado: {total + 12} itens na conta, {total} procedimentos.")
        log("info", f"Conta com {total} itens; tratando {total}.")
        r = _vazio("CONCLUIDO")
        r["total"] = r["alvo"] = total
        for linha in range(1, total + 1):
            if parar.is_set():
                r["estado"], r["mensagem"] = "INTERROMPIDO", "Interrompido pelo operador."
                log("aviso", r["mensagem"])
                r["tempo"] = _tempo(t0)
                return r
            self._dorme(0.35)
            if ult == "9" and linha == total // 2:
                msg = "Conexao com o banco de dados perdida (simulado)."
                log("critico", f"ERRO CRITICO - automacao interrompida: {msg}")
                r["estado"], r["mensagem"] = "CRITICO", msg
                r["tempo"] = _tempo(t0)
                return r
            sorte = rnd.random()
            if ult == "8" and sorte < 0.7:
                log("erro", f"Item {linha:>3}: CBO INVALIDO (Salux limpou o campo) - Codigo CBO invalido.[2]")
                msg = "CBO invalido para a especialidade do profissional (o Salux limpou o campo)."
                r["erros"].append((linha, msg))
                log("erro", f"ERRO linha {linha}: {msg}")
            elif (ult == "7" and sorte < 0.35) or (sorte < 0.08):
                log("info", f"Item {linha:>3}: PULADO (sem Prof / sem opcoes de CBO)")
                msg = ("Campo CBO sem especialidade para preencher "
                       "(sem Prof ou profissional sem CBO vinculado)")
                r["erros"].append((linha, msg))
                log("erro", f"ERRO linha {linha}: {msg}")
            elif sorte > 0.9:
                log("info", f"Item {linha:>3}: PULADO (CBO ja preenchido) - 225125")
                r["ja"] += 1
            else:
                log("ok", f"Item {linha:>3}: PREENCHIDO - {rnd.choice(['225125', '225120', '225250'])}")
                r["preenchidos"] += 1
            r["tratados"] = linha
        r["estado"] = "CONCLUIDO_COM_ERROS" if r["erros"] else "CONCLUIDO"
        r["tempo"] = _tempo(t0)
        log("info", f"Resumo: {r['preenchidos']} preenchidos, {r['ja']} ja tinham CBO, "
                    f"{len(r['erros'])} com erro.")
        log("info", f"Tempo decorrido: {r['tempo']}")
        return r

    def salvar(self, conta, log):
        log("info", "Salvando a conta (simulado)...")
        self._dorme(1.0)
        log("ok", "Conta salva (simulado).")
        return True, ""


class WorkerSalux:
    nome = "Salux real"
    pausar_apos = False
    deixa_aberta = True  # se NAO salvar, a conta continua aberta no Salux: o servidor pausa a fila

    def __init__(self, limite=None):
        self.limite = limite

    def executar(self, conta, log, parar):
        import cbo_core
        import salux_sessao
        import perfil_tela
        t0 = time.time()
        aviso_tela = perfil_tela.aviso()
        if aviso_tela:
            log("aviso", aviso_tela)
        try:
            log("info", "Preparando o Salux (portal, login e Faturamento)...")
            salux_sessao.garantir_faturamento(lambda m: log("info", m))
        except Exception as e:
            log("critico", f"ERRO CRITICO ao entrar no Salux: {e}")
            r = _vazio("CRITICO", f"Falha ao entrar no Salux: {e}")
            r["tempo"] = _tempo(t0)
            return r
        res = cbo_core.executar(log, parar, limite=self.limite, conta=conta,
                                msg_final="o servidor decide agora se salva.")
        alvo = min(res.total, self.limite) if self.limite else res.total
        return {"estado": res.estado, "mensagem": res.mensagem, "total": res.total, "alvo": alvo,
                "tratados": res.tratados, "preenchidos": res.preenchidos, "ja": res.ja_preenchidos,
                "erros": list(res.erros), "tempo": res.tempo}

    def salvar(self, conta, log):
        import cbo_core
        if self.limite:  # teste com poucos itens: nunca salvar conta parcialmente preenchida
            log("aviso", f"Modo de teste (max. itens = {self.limite}): conta parcial NAO sera salva; "
                         "continua aberta no Salux.")
            return False, f"Modo de teste (max. itens = {self.limite}): conta parcial nao salva."
        cbo_core.salvar_e_fechar(log)  # ErroCritico se o Salux perguntar algo inesperado
        return True, ""
