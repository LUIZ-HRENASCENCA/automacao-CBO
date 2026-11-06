"""Teste automatico do fluxo cliente-servidor com o worker simulado (sem Salux, sem interface).

Uso: python teste_fluxo_simulado.py
Usa banco e pasta de logs temporarios e a porta 8799.
"""
import queue
import sys
import tempfile
import time
from pathlib import Path

import porta
from banco import Banco
from cliente_rede import Conexao
import cbo_core
import cliente_config
import servidor_config
from cliente_rede import testar_conexao
from servidor_cbo import Servidor
from workers import WorkerSimulado

falhas = []
TOKEN = "tk-teste-123"


def conferir(cond, msg):
    print(("OK    " if cond else "FALHA ") + msg)
    if not cond:
        falhas.append(msg)


def esperar(cond, seg=30):
    fim = time.time() + seg
    while time.time() < fim:
        if cond():
            return True
        time.sleep(0.1)
    return False


def teste_porta():
    erros_tol = [(i, "Campo CBO sem especialidade para preencher (x)") for i in range(1, 5)]
    conferir(porta.avaliar(10, 10, erros_tol)[0], "porta: so tolerados (4 de 10) salva")
    erros_prob = [(i, "CBO invalido") for i in range(1, 6)]
    conferir(not porta.avaliar(10, 10, erros_prob)[0], "porta: 5 de 10 com problema nao salva (>=50%)")
    conferir(porta.avaliar(10, 10, erros_prob[:4])[0], "porta: 4 de 10 com problema salva")
    conferir(not porta.avaliar(10, 7, [])[0], "porta: processamento incompleto nao salva")


def teste_dialogos():
    d = cbo_core.decidir_dialogo
    conferir(d("Existem valores zerados. Deseja salvar mesmo assim?", ["&Sim", "&Não"])[0] == "sim",
             "salvar: 'valores zerados' -> responde SIM")
    conferir(d("Existem valores zerados. Deseja salvar mesmo assim?", ["OK"])[0] != "sim",
             "salvar: sem botao Sim nao responde sim")
    conferir(d("Deseja apagar o item?", ["&Sim", "&Não"])[0] == "erro",
             "salvar: pergunta desconhecida -> erro (nao responde)")
    conferir(d("Conta gravada com sucesso.", ["OK"])[0] == "ok", "salvar: aviso informativo -> OK")
    conferir(d("Erro de conexao com o banco de dados.", ["OK"])[0] == "erro", "salvar: aviso critico -> erro")
    conferir(d("Codigo CBO invalido.[2]", ["OK"])[0] == "erro", "salvar: CBO invalido ao salvar -> erro")


class WorkerSalvaFalha(WorkerSimulado):
    nome = "Simulado-falha-ao-salvar"
    deixa_aberta = True

    def salvar(self, conta, log):
        raise RuntimeError("O Salux perguntou algo inesperado ao salvar")


class WorkerNaoSalvaAberta(WorkerSimulado):
    nome = "Simulado-nao-salva"
    deixa_aberta = True

    def salvar(self, conta, log):
        return False, "modo de teste: conta parcial nao salva"


def teste_salvamento_servidor(tmp):
    for cls, esperado, motivo in ((WorkerSalvaFalha, "FALHA_CRITICA", "falha ao salvar vira FALHA_CRITICA"),
                                  (WorkerNaoSalvaAberta, "NAO_SALVA", "nao salvou com conta aberta")):
        b = Banco(tmp / f"fila_{cls.__name__}.db")
        s = Servidor(b, lambda c=cls: c(velocidade=0.01), bind="127.0.0.1", porta_tcp=8795,
                     pasta_logs=tmp / "logs_s", token="x")
        s.iniciar()
        id_ = b.criar("40111", "tester")
        esperar(lambda: b.get(id_)["estado"] not in ("ENFILEIRADA", "PROCESSANDO"), 20)
        time.sleep(0.4)
        conferir(b.get(id_)["estado"] == esperado and s.pausada, f"servidor: {motivo} e a fila pausa")
        s.parar()
        time.sleep(0.3)
    b = Banco(tmp / "fila_ok.db")  # worker que fecha a conta ao salvar (nao deixa aberta): fila segue
    s = Servidor(b, lambda: WorkerSimulado(velocidade=0.01), bind="127.0.0.1", porta_tcp=8795,
                 pasta_logs=tmp / "logs_s2", token="x")
    s.iniciar()
    i1, i2 = b.criar("40111", "t"), b.criar("40112", "t")
    esperar(lambda: all(b.get(i)["estado"] not in ("ENFILEIRADA", "PROCESSANDO") for i in (i1, i2)), 30)
    conferir(b.get(i1)["estado"] == "SALVA" and b.get(i2)["estado"] == "SALVA" and not s.pausada,
             "servidor: contas salvas e fechadas -> fila segue sem pausar")
    s.parar()
    time.sleep(0.3)


def teste_fluxo_principal():
    """salvar_se_liberado (usado pelo painel local e pelo terminal) com salvar_e_fechar simulado."""
    chamadas, original = [], cbo_core.salvar_e_fechar
    cbo_core.salvar_e_fechar = lambda log: chamadas.append(1)
    try:
        def res(estado="CONCLUIDO", total=10, tratados=10, erros=()):
            return cbo_core.Resultado(estado=estado, total=total, tratados=tratados, erros=list(erros))

        nulo = lambda n, m: None
        r = res()
        cbo_core.salvar_se_liberado(r, nulo)
        conferir(r.salvou and len(chamadas) == 1, "principal: execucao ok -> salva e fecha")
        tol = [(i, "Campo CBO sem especialidade para preencher") for i in range(1, 6)]
        r = res("CONCLUIDO_COM_ERROS", erros=tol)
        cbo_core.salvar_se_liberado(r, nulo)
        conferir(r.salvou and len(chamadas) == 2, "principal: so erros tolerados -> salva e fecha")
        r = res("CONCLUIDO_COM_ERROS", erros=[(i, "CBO invalido") for i in range(1, 7)])
        cbo_core.salvar_se_liberado(r, nulo)
        conferir(not r.salvou and len(chamadas) == 2 and "50%" in r.nota_salvar, "principal: >=50% problemas -> nao salva")
        r = res()
        cbo_core.salvar_se_liberado(r, nulo, limite=5)
        conferir(not r.salvou and len(chamadas) == 2, "principal: com limite de itens -> nao salva")
        for est in ("CRITICO", "INTERROMPIDO", "CONTA_INVALIDA"):
            r = res(est)
            cbo_core.salvar_se_liberado(r, nulo)
            conferir(not r.salvou and len(chamadas) == 2, f"principal: estado {est} -> nao salva")

        def falha(log):
            raise cbo_core.ErroCritico("o Salux perguntou algo inesperado")

        cbo_core.salvar_e_fechar = falha
        r = res()
        cbo_core.salvar_se_liberado(r, nulo)
        conferir(r.estado == "CRITICO" and not r.salvou and "inesperado" in r.mensagem,
                 "principal: erro ao salvar -> estado CRITICO")
    finally:
        cbo_core.salvar_e_fechar = original


def teste_configs(tmp):
    arq = tmp / "cliente_config.json"
    conferir(not cliente_config.existe(arq), "cliente_config: sem arquivo = primeira execucao")
    cfg = cliente_config.carregar(arq)
    conferir(cfg["servidor"] == "10.10.10.249" and cfg["porta"] == 8765 and cfg["token"] == "",
             "cliente_config: padrao 10.10.10.249:8765 e token vazio")
    conferir(cliente_config.validar(cfg) != "", "cliente_config: sem token nao valida")
    cfg.update(token="abc", servidor="10.1.1.5", porta="9000", usuario="maria", papel="operador")
    conferir(cliente_config.validar(cfg) == "", "cliente_config: configuracao completa valida")
    cliente_config.salvar(cfg, arq)
    c2 = cliente_config.carregar(arq)
    conferir(c2["servidor"] == "10.1.1.5" and c2["porta"] == 9000 and c2["papel"] == "operador",
             "cliente_config: salvar e carregar")
    conferir(cliente_config.validar({**c2, "porta": "99999"}) != "", "cliente_config: porta invalida recusada")
    conferir(cliente_config.validar({**c2, "servidor": "a b"}) != "", "cliente_config: endereco com espaco recusado")
    sarq = tmp / "servidor_config.json"
    s1 = servidor_config.carregar(sarq)
    s2 = servidor_config.carregar(sarq)
    conferir(len(s1["token"]) == 10 and s1["token"] == s2["token"], "servidor_config: token gerado e persistido")
    conferir(s1["bind"] == "0.0.0.0" and s1["porta"] == 8765, "servidor_config: bind 0.0.0.0 e porta 8765")


def teste_conexao_e_reconfigurar(srv_a, banco_b, tmp):
    ok, msg = testar_conexao("127.0.0.1", 8799, TOKEN)
    conferir(ok, f"testar_conexao: OK ({msg})")
    ok, msg = testar_conexao("127.0.0.1", 8799, "errado")
    conferir(not ok and "token" in msg.lower(), f"testar_conexao: token errado ({msg})")
    ok, msg = testar_conexao("127.0.0.1", 8797, TOKEN, timeout=2)
    conferir(not ok and ("recusada" in msg.lower() or "sem resposta" in msg.lower()),
             f"testar_conexao: porta fechada ({msg})")
    ok, msg = testar_conexao("host-que-nao-existe.invalid", 8799, TOKEN, timeout=2)
    conferir(not ok, f"testar_conexao: endereco inexistente ({msg})")
    conferir(srv_a.n_clientes >= 0 and all(c["papel"] != "teste" for c in srv_a.lista_clientes()),
             "servidor nao lista conexoes de teste como clientes")
    # reconfigurar: o mesmo painel passa de um servidor para outro sem reiniciar
    srv_b = Servidor(banco_b, lambda: WorkerSimulado(velocidade=0.01), bind="127.0.0.1", porta_tcp=8798,
                     pasta_logs=tmp / "logs_b", token="outro-token")
    conferir(srv_b.iniciar(), "servidor B iniciou")
    q = queue.Queue()
    cli = Conexao("127.0.0.1", 8799, TOKEN, "viajante", "ambos", q)
    cli.iniciar()
    conferir(esperar(lambda: any(c["usuario"] == "viajante" for c in srv_a.lista_clientes()), 10),
             "cliente conectou no servidor A (lista mostra usuario e versao)")
    info = next(c for c in srv_a.lista_clientes() if c["usuario"] == "viajante")
    conferir(info["versao"] != "?", f"versao do cliente informada ({info['versao']})")
    cli.reconfigurar("127.0.0.1", 8798, "outro-token", "viajante", "ambos")
    conferir(esperar(lambda: any(c["usuario"] == "viajante" for c in srv_b.lista_clientes()), 10),
             "reconfigurar: cliente passou para o servidor B")
    conferir(esperar(lambda: not any(c["usuario"] == "viajante" for c in srv_a.lista_clientes()), 10),
             "reconfigurar: saiu do servidor A")
    cli.fechar()
    srv_b.parar()


def main():
    teste_porta()
    teste_dialogos()
    teste_fluxo_principal()
    tmp = Path(tempfile.mkdtemp(prefix="cbo_teste_"))
    banco = Banco(tmp / "fila.db")
    srv = Servidor(banco, lambda: WorkerSimulado(velocidade=0.01), bind="127.0.0.1", porta_tcp=8799,
                   pasta_logs=tmp / "logs", token=TOKEN)
    conferir(srv.iniciar(), f"servidor iniciou ({srv.erro or 'ok'})")
    teste_configs(tmp)
    teste_salvamento_servidor(tmp)
    teste_conexao_e_reconfigurar(srv, Banco(tmp / "fila_b.db"), tmp)
    q = queue.Queue()
    cli = Conexao("127.0.0.1", 8799, TOKEN, "tester", "ambos", q)
    cli.iniciar()
    msgs = []

    def drena():
        while True:
            try:
                msgs.append(q.get_nowait())
            except queue.Empty:
                return

    conferir(esperar(lambda: (drena(), any(m["tipo"] == "hello_ok" for m in msgs))[1]), "cliente autenticou")
    # token errado deve ser recusado
    q2 = queue.Queue()
    ruim = Conexao("127.0.0.1", 8799, "token-errado", "intruso", "ambos", q2)
    ruim.iniciar()
    time.sleep(1.5)
    erros = []
    while not q2.empty():
        erros.append(q2.get_nowait())
    conferir(any(m["tipo"] == "erro" for m in erros), "token errado recusado")
    ruim.fechar()

    srv.pausar(True)  # enfileira tudo antes de comecar
    for c in ("12345", "12345", "12340", "12347", "12348", "12349", "12341", "abc"):
        cli.enviar({"tipo": "enviar_conta", "conta": c})
    time.sleep(1.0)
    drena()
    resp = [m for m in msgs if m["tipo"] == "resposta_envio"]
    aceitas = [m["conta"] for m in resp if m["aceita"]]
    conferir(aceitas == ["12345", "12340", "12347", "12348", "12349", "12341"],
             f"fila aceitou so as validas e sem duplicata: {aceitas}")
    conferir(sum(1 for m in resp if not m["aceita"]) == 2, "recusou duplicada e 'abc'")

    srv.pausar(False)
    # roda ate a falha critica (12349), que deve pausar a fila antes da 12341
    esperar(lambda: banco.listar() and any(c["conta"] == "12349" and c["estado"] not in
                                           ("ENFILEIRADA", "PROCESSANDO") for c in banco.listar()), 60)
    time.sleep(0.5)
    est = {c["conta"]: c["estado"] for c in banco.listar()}
    print("estados:", est)
    conferir(est["12345"] in ("SALVA", "NAO_SALVA"), f"12345 processada ({est['12345']})")
    conferir(est["12340"] == "CONTA_INVALIDA", "12340 -> CONTA_INVALIDA")
    conferir(est["12347"] == "SALVA", "12347 (so tolerados) -> SALVA")
    conferir(est["12348"] == "NAO_SALVA", "12348 (>=50% problemas) -> NAO_SALVA")
    conferir(est["12349"] == "FALHA_CRITICA", "12349 -> FALHA_CRITICA")
    conferir(srv.pausada and est["12341"] == "ENFILEIRADA", "fila pausou apos o erro critico; 12341 aguarda")

    srv.pausar(False)
    esperar(lambda: all(c["estado"] not in ("ENFILEIRADA", "PROCESSANDO") for c in banco.listar()), 30)
    conferir({c["conta"]: c["estado"] for c in banco.listar()}["12341"] in ("SALVA", "NAO_SALVA"),
             "apos Retomar, 12341 foi processada")

    # reiniciar fila: reenfileira as falhas criticas e retoma (12349 falha de novo, de forma deterministica)
    n = srv.reiniciar_fila()
    conferir(n == 1, f"reiniciar_fila reenfileirou {n} conta com falha critica")
    esperar(lambda: {c["conta"]: c["estado"] for c in banco.listar()}["12349"] == "FALHA_CRITICA" and srv.pausada, 30)
    conferir({c["conta"]: c["estado"] for c in banco.listar()}["12349"] == "FALHA_CRITICA" and srv.pausada,
             "12349 reprocessada e voltou a falhar (fila pausou de novo)")
    conferir(any("Reenfileirada" in e["msg"] for c in banco.listar() if c["conta"] == "12349"
                 for e in banco.eventos(c["id"])), "evento de reenfileiramento registrado no log")

    # logs identicos: texto recebido pelo cliente == txt do servidor
    drena()
    conc = {m["conta"]: m for m in msgs if m["tipo"] == "conta_concluida"}
    txt = {p.name.split("_")[1]: p.read_text(encoding="utf-8") for p in (tmp / "logs").glob("conta_*.txt")}
    conferir(set(conc) == set(txt) and len(conc) == 6, f"6 contas concluidas e 6 txt no servidor ({sorted(conc)})")
    conferir(all(conc[c]["texto"] == txt[c] for c in conc if c in txt), "log do cliente identico ao txt do servidor")
    linhas_cli = [m for m in msgs if m["tipo"] == "log_linha" and m["conta"] == "12347"]
    conferir(all(m["msg"] in txt["12347"] for m in linhas_cli) and linhas_cli,
             "log_linha em tempo real aparece no txt do servidor")

    # revisao
    id_ = next(c["id"] for c in banco.listar() if c["conta"] == "12347")
    cli.enviar({"tipo": "revisar", "id": id_})
    time.sleep(0.8)
    drena()
    conferir(banco.get(id_)["revisao"] == "REVISADA" and any(m["tipo"] == "conta_revisada" for m in msgs),
             "revisao manual registrada e notificada")

    cli.fechar()
    srv.parar()
    print("\nRESULTADO:", "TUDO OK" if not falhas else f"{len(falhas)} FALHA(S)")
    sys.exit(1 if falhas else 0)


if __name__ == "__main__":
    main()
