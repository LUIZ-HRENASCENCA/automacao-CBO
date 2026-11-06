"""Servidor da automacao de CBO: fila de contas, worker serial, push em tempo real e logs.

Sem interface propria: o painel_servidor.py cria e controla esta classe. Rede: asyncio TCP,
uma mensagem JSON por linha (ver protocolo.py). Logs: SQLite (fonte da verdade) + .txt por conta.
"""
import asyncio
import json
import threading
import time
from datetime import datetime
from pathlib import Path

import config
import porta
import protocolo
import servidor_config
from caminhos import pasta_app
from protocolo import legivel
from banco import Banco, agora

CAMPOS_FILA = ("id", "conta", "solicitante", "estado", "revisao", "salvou", "motivo",
               "criada", "inicio", "fim", "tempo", "modo")


class Servidor:
    def __init__(self, banco, obter_worker, on_log=None, bind=None, porta_tcp=None, pasta_logs=None,
                 token=None):
        cfg = servidor_config.carregar() if None in (bind, porta_tcp, token) else {}
        self.db = banco
        self.obter_worker = obter_worker      # callable -> worker atual (permite trocar o modo)
        self.on_log = on_log or (lambda *a: None)   # on_log(id, conta, nivel, hora, msg)
        self.bind = bind or cfg.get("bind")
        self.porta = porta_tcp or cfg.get("porta")
        self.token = token or cfg.get("token")
        self.pasta_logs = Path(pasta_logs or pasta_app() / config.PASTA_LOGS)
        self.clientes = {}
        self.pausada = False
        self.parar_atual = threading.Event()
        self.encerrar = False
        self.erro = ""
        self.atual = None
        self.loop = None
        self._pronto = threading.Event()

    # ------------------------------------------------------------ ciclo de vida
    def iniciar(self):
        for id_ in self.db.recuperar():
            self.db.evento(id_, "critico", "O servidor foi reiniciado durante o processamento.")
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self._rodar_loop, daemon=True).start()
        self._pronto.wait(10)
        if not self.erro:
            threading.Thread(target=self._worker, daemon=True).start()
        return not self.erro

    def _rodar_loop(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.srv = self.loop.run_until_complete(
                asyncio.start_server(self._cliente, self.bind, self.porta, limit=2 ** 24))
        except OSError as e:
            self.erro = f"Nao foi possivel abrir {self.bind}:{self.porta} - {e}"
            self._pronto.set()
            return
        self._pronto.set()
        self.loop.run_forever()

    def parar(self):
        self.encerrar = True
        self.parar_atual.set()
        if self.loop and self.loop.is_running():
            def _fechar():
                try:
                    self.srv.close()  # libera a porta para um novo servidor
                except Exception:
                    pass
                for w in list(self.clientes):
                    try:
                        w.close()
                    except Exception:
                        pass
                self.loop.stop()
            self.loop.call_soon_threadsafe(_fechar)

    def pausar(self, valor):
        self.pausada = bool(valor)
        self._bc_fila()

    def reiniciar_fila(self):
        """Recoloca na fila (na ordem original) todas as contas com FALHA_CRITICA e retoma a fila.

        Nao faz nada se houver conta em processamento. Devolve quantas contas voltaram."""
        if self.atual:
            return 0
        falhas = self.db.falhas_criticas()
        for c in falhas:
            self.db.reenfileirar(c["id"])
            self.db.evento(c["id"], "aviso", "Reenfileirada apos falha critica (fila reiniciada).")
            self.on_log(c["id"], c["conta"], "aviso", datetime.now().strftime("%H:%M:%S"),
                        "Reenfileirada apos falha critica (fila reiniciada).")
        self.pausada = False
        self._bc_fila()
        return len(falhas)

    def lista_clientes(self):
        """Clientes conectados agora (exclui testes de conexao)."""
        return [dict(i) for i in list(self.clientes.values()) if i.get("papel") != "teste"]

    @property
    def n_clientes(self):
        return len(self.lista_clientes())

    # ------------------------------------------------------------ rede
    async def _cliente(self, reader, writer):
        try:
            msg = await asyncio.wait_for(protocolo.ler(reader), 10)
            if not msg or msg.get("tipo") != "hello" or msg.get("token") != self.token:
                writer.write(protocolo.codificar({"tipo": "erro", "msg": "autenticacao recusada"}))
                await writer.drain()
                return
            info = {"usuario": str(msg.get("usuario", "?"))[:40], "papel": msg.get("papel", "ambos"),
                    "versao": str(msg.get("versao", "?"))[:30], "desde": agora()}
            self.clientes[writer] = info
            writer.write(protocolo.codificar({"tipo": "hello_ok", "servidor": "servidor_cbo"}))
            writer.write(protocolo.codificar(self._fila_msg()))
            while True:
                msg = await protocolo.ler(reader)
                if msg is None:
                    break
                self._tratar(msg, writer, info)
        except (asyncio.TimeoutError, ConnectionError, ValueError, OSError):
            pass
        finally:
            self.clientes.pop(writer, None)
            try:
                writer.close()
            except Exception:
                pass

    def _resp(self, writer, msg):
        try:
            writer.write(protocolo.codificar(msg))
        except Exception:
            pass

    def _tratar(self, msg, writer, info):
        tipo = msg.get("tipo")
        if tipo == "enviar_conta":
            conta = str(msg.get("conta", "")).strip()
            if not conta.isdigit() or not 1 <= len(conta) <= 12:
                return self._resp(writer, {"tipo": "resposta_envio", "aceita": False, "conta": conta,
                                           "motivo": "Numero de conta invalido (somente digitos)."})
            if self.db.ativa(conta):
                return self._resp(writer, {"tipo": "resposta_envio", "aceita": False, "conta": conta,
                                           "motivo": "A conta ja esta na fila ou em processamento."})
            id_ = self.db.criar(conta, info["usuario"])
            self.db.evento(id_, "info", f"Conta {conta} enfileirada por {info['usuario']}.")
            self._resp(writer, {"tipo": "resposta_envio", "aceita": True, "id": id_, "conta": conta,
                                "motivo": ""})
            self._bc_fila()
        elif tipo == "revisar":
            r = self.db.get(msg.get("id"))
            if r and r["estado"] not in ("ENFILEIRADA", "PROCESSANDO") and r["revisao"] != "REVISADA":
                self.db.atualizar(r["id"], revisao="REVISADA", revisada_por=info["usuario"],
                                  revisada_em=agora())
                self.db.evento(r["id"], "info", f"Revisada manualmente por {info['usuario']}.")
                self._bc({"tipo": "conta_revisada", "id": r["id"], "conta": r["conta"],
                          "por": info["usuario"]})
                self._bc_fila()
        elif tipo == "pedir_log":
            r = self.db.get(msg.get("id"))
            if r:
                self._resp(writer, {"tipo": "log_conta", "id": r["id"], "texto": self.montar_texto(r["id"])})
        elif tipo == "listar":
            self._resp(writer, self._fila_msg())

    def _fila_msg(self):
        contas = [{k: c.get(k) for k in CAMPOS_FILA} for c in self.db.listar(100)]
        return {"tipo": "fila", "contas": contas, "pausada": self.pausada}

    def _enviar_todos(self, data):
        for w in list(self.clientes):
            try:
                w.write(data)
            except Exception:
                pass

    def _bc(self, msg):
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self._enviar_todos, protocolo.codificar(msg))

    def _bc_fila(self):
        self._bc(self._fila_msg())

    # ------------------------------------------------------------ logs
    def montar_texto(self, id_):
        """Texto do log da conta (o MESMO conteudo vai para o .txt do servidor e para o cliente)."""
        r = self.db.get(id_)
        linhas = [f"CONTA {r['conta']}  |  solicitante: {r['solicitante']}  |  modo: {r['modo'] or '-'}",
                  f"Enfileirada: {r['criada']}  |  Inicio: {r['inicio'] or '-'}  |  Fim: {r['fim'] or '-'}",
                  ""]
        linhas += [f"[{e['hora']}] {e['msg']}" for e in self.db.eventos(id_)]
        if r["fim"]:
            linhas += ["", f"SITUACAO: {legivel(r['estado'])}  |  Salvou: {'SIM' if r['salvou'] else 'NAO'}  |  "
                           f"Tempo: {r['tempo']}",
                       f"Motivo: {r['motivo'] or '-'}",
                       "Revisao manual: PENDENTE (toda conta deve ser conferida pela secretaria)."]
        return "\n".join(linhas) + "\n"

    def _gravar_txt(self, id_):
        r = self.db.get(id_)
        self.pasta_logs.mkdir(exist_ok=True)
        arq = self.pasta_logs / f"conta_{r['conta']}_{datetime.now():%Y%m%d_%H%M%S}.txt"
        arq.write_text(self.montar_texto(id_), encoding="utf-8")
        return arq

    # ------------------------------------------------------------ worker (uma conta por vez)
    def _worker(self):
        while not self.encerrar:
            if self.pausada:
                time.sleep(0.4)
                continue
            row = self.db.proxima()
            if not row:
                time.sleep(0.4)
                continue
            try:
                self._processar(row)
            except Exception as e:  # nunca derrubar o worker
                self.db.atualizar(row["id"], estado="FALHA_CRITICA", fim=agora(),
                                  motivo=f"Erro no servidor: {type(e).__name__}: {e}")
                self.db.evento(row["id"], "critico", f"Erro no servidor: {type(e).__name__}: {e}")
                self.pausar(True)

    def _processar(self, row):
        id_, conta = row["id"], row["conta"]
        worker = self.obter_worker()
        self.parar_atual.clear()
        self.db.atualizar(id_, estado="PROCESSANDO", inicio=agora(), modo=worker.nome)
        self.atual = id_
        self._bc_fila()

        def log(nivel, msg):
            hora = datetime.now().strftime("%H:%M:%S")
            self.db.evento(id_, nivel, msg, hora)
            self.on_log(id_, conta, nivel, hora, msg)
            self._bc({"tipo": "log_linha", "id": id_, "conta": conta,
                      "solicitante": row["solicitante"], "nivel": nivel, "hora": hora,
                      "msg": f"[{hora}] {msg}"})

        log("info", f"Iniciando a conta {conta} (modo {worker.nome}).")
        t0 = time.time()
        try:
            res = worker.executar(conta, log, self.parar_atual)
        except Exception as e:
            msg = f"Erro no servidor/Salux: {type(e).__name__}: {e}"
            log("critico", f"ERRO CRITICO - {msg}")
            res = {"estado": "CRITICO", "mensagem": msg, "total": 0, "alvo": 0, "tratados": 0,
                   "preenchidos": 0, "ja": 0, "erros": [], "tempo": "-"}
        est, motivo, salvou, erro_salvar = res["estado"], res.get("mensagem", ""), False, False
        pausar = bool(getattr(worker, "pausar_apos", False))
        if est in ("CONCLUIDO", "CONCLUIDO_COM_ERROS"):
            ok, motivo, tol, prob = porta.avaliar(res["alvo"], res["tratados"], res["erros"])
            log("info" if ok else "aviso", f"Porta de salvamento: {'PODE SALVAR' if ok else 'NAO SALVAR'} - {motivo}")
            if ok:
                try:
                    salvou, m2 = worker.salvar(conta, log)
                except Exception as e:
                    salvou, m2, erro_salvar = False, f"Erro ao salvar: {type(e).__name__}: {e}", True
                    log("critico", f"ERRO CRITICO - {m2}")
                    pausar = True
                final = "FALHA_CRITICA" if erro_salvar else ("SALVA" if salvou else "NAO_SALVA")
                if not salvou:
                    motivo = m2
            else:
                final = "NAO_SALVA"
        elif est == "CONTA_INVALIDA":
            final = "CONTA_INVALIDA"
        elif est == "INTERROMPIDO":
            final, motivo = "NAO_SALVA", motivo or "Interrompida a pedido."
        else:
            final = "FALHA_CRITICA"
            pausar = True
        if final in ("NAO_SALVA", "FALHA_CRITICA") and getattr(worker, "deixa_aberta", False):
            pausar = True
            log("aviso", "A conta NAO foi salva e continua aberta no Salux: confira/feche e retome a fila.")
        resumo = {k: res.get(k) for k in ("total", "alvo", "tratados", "preenchidos", "ja")}
        resumo["erros"] = len(res.get("erros", []))
        resumo["toleradas"] = sum(1 for e in res.get("erros", []) if porta.eh_tolerado(e[1]))
        tempo = res.get("tempo") if res.get("tempo") not in (None, "-") else f"{int(time.time() - t0)}s"
        log("ok" if final == "SALVA" else "aviso" if final != "FALHA_CRITICA" else "critico",
            f"SITUACAO FINAL: {legivel(final)}" + (f" - {motivo}" if motivo else ""))
        self.db.atualizar(id_, estado=final, fim=agora(), salvou=1 if salvou else 0, motivo=motivo,
                          resumo=json.dumps(resumo), tempo=tempo, revisao="AGUARDANDO_REVISAO")
        arq = self._gravar_txt(id_)
        self.on_log(id_, conta, "info", datetime.now().strftime("%H:%M:%S"), f"Log salvo em {arq}")
        r = self.db.get(id_)
        self._bc({"tipo": "conta_concluida", "id": id_, "conta": conta, "solicitante": row["solicitante"],
                  "estado": final, "salvou": bool(salvou), "motivo": motivo, "resumo": resumo,
                  "texto": self.montar_texto(id_)})
        self.atual = None
        if pausar:
            self.pausar(True)
            hora = datetime.now().strftime("%H:%M:%S")
            self.on_log(id_, conta, "aviso", hora, "FILA PAUSADA: confira o Salux e clique em Retomar.")
        else:
            self._bc_fila()
