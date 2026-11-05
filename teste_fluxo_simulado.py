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
import config
from servidor_cbo import Servidor
from workers import WorkerSimulado

falhas = []


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


def main():
    teste_porta()
    tmp = Path(tempfile.mkdtemp(prefix="cbo_teste_"))
    banco = Banco(tmp / "fila.db")
    srv = Servidor(banco, lambda: WorkerSimulado(velocidade=0.01), bind="127.0.0.1", porta_tcp=8799,
                   pasta_logs=tmp / "logs")
    conferir(srv.iniciar(), f"servidor iniciou ({srv.erro or 'ok'})")
    q = queue.Queue()
    cli = Conexao("127.0.0.1", 8799, config.TOKEN, "tester", "ambos", q)
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
