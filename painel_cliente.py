"""Painel do CLIENTE (operador e/ou secretarias).

Uso: python painel_cliente.py [--papel operador|secretaria|ambos] [--usuario NOME] [--servidor HOST]
                              [--porta N] [--token TOKEN]
O servidor, a porta, o token, o usuario e o papel ficam em cliente_config.json (ao lado do
executavel) e sao editados em "Configurar servidor"; os argumentos acima sobrepoem o arquivo.
  operador   : digita o numero da conta e envia para a fila do servidor.
  secretaria : recebe o aviso quando cada conta termina, confere e marca como REVISADA.
  ambos      : os dois.
O log mostrado e o MESMO do servidor (linha a linha, em tempo real); ao concluir, o texto completo
e gravado em logs_cliente/ para quem solicitou a conta. Duplo clique em uma conta abre o log completo.
"""
import argparse
import queue
import sys
import threading
import tkinter as tk
import traceback
from datetime import datetime
from tkinter import messagebox, scrolledtext, ttk

import cliente_config
from cliente_rede import Conexao, testar_conexao
from protocolo import legivel
from versao import VERSAO

CORES = {"info": "#555555", "ok": "#1b7f2a", "aviso": "#b36b00", "erro": "#c62828", "critico": "#c62828"}
COR_ESTADO = {"SALVA": "#1b7f2a", "NAO_SALVA": "#b36b00", "CONTA_INVALIDA": "#b36b00",
              "FALHA_CRITICA": "#c62828", "PROCESSANDO": "#1565c0"}
PASTA_CLIENTE = cliente_config.pasta_app() / "logs_cliente"


class PainelCliente:
    def __init__(self, raiz, cfg, primeira_execucao=False):
        self.raiz, self.cfg = raiz, cfg
        self.papel, self.usuario = cfg["papel"], cfg["usuario"]
        papel = self.papel
        self.entrada = queue.Queue()
        self.contas = {}
        self.conectado = False
        raiz.geometry("900x700+960+30")
        raiz.configure(bg="#f4f4f4")
        self.titulo()

        topo = tk.Frame(raiz, bg="#f4f4f4")
        topo.pack(fill="x")
        tk.Button(topo, text="⚙ Configurar servidor", command=self.abrir_config).pack(side="right", padx=8, pady=6)
        self.faixa = tk.Label(topo, text="Conectando ao servidor...", font=("Segoe UI", 11, "bold"), pady=6,
                              bg="#fff3e0", fg="#e65100")
        self.faixa.pack(side="left", fill="x", expand=True)

        if papel in ("operador", "ambos"):
            env = tk.Frame(raiz, bg="#f4f4f4")
            env.pack(fill="x", padx=12, pady=8)
            tk.Label(env, text="Nº da conta:", bg="#f4f4f4", font=("Segoe UI", 11)).pack(side="left")
            self.v_conta = tk.StringVar()
            e = tk.Entry(env, textvariable=self.v_conta, width=14, font=("Segoe UI", 12))
            e.pack(side="left", padx=8)
            e.bind("<Return>", lambda _e: self.enviar())
            self.b_enviar = tk.Button(env, text="Enviar para a fila", font=("Segoe UI", 10, "bold"),
                                      bg="#1565c0", fg="white", padx=12, command=self.enviar)
            self.b_enviar.pack(side="left")
            self.retorno = tk.Label(env, text="", bg="#f4f4f4", font=("Segoe UI", 9))
            self.retorno.pack(side="left", padx=12)

        cols = ("id", "conta", "solicitante", "estado", "revisao", "salvou")
        self.arvore = ttk.Treeview(raiz, columns=cols, show="headings", height=9)
        for c, t, w in (("id", "#", 40), ("conta", "Conta", 90), ("solicitante", "Solicitante", 130),
                        ("estado", "Estado", 130), ("revisao", "Revisão", 160), ("salvou", "Salvou", 60)):
            self.arvore.heading(c, text=t)
            self.arvore.column(c, width=w, anchor="w")
        for est, cor in COR_ESTADO.items():
            self.arvore.tag_configure(est, foreground=cor)
        self.arvore.pack(fill="x", padx=12)
        self.arvore.bind("<Double-1>", lambda _e: self.abrir_log())

        barra = tk.Frame(raiz, bg="#f4f4f4")
        barra.pack(fill="x", padx=12, pady=4)
        tk.Button(barra, text="Ver log completo da conta selecionada", command=self.abrir_log).pack(side="left")
        if papel in ("secretaria", "ambos"):
            tk.Button(barra, text="Marcar como REVISADA", bg="#2e7d32", fg="white", font=("Segoe UI", 9, "bold"),
                      command=self.revisar).pack(side="right")

        self.log = scrolledtext.ScrolledText(raiz, height=20, font=("Consolas", 9), state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True, padx=12, pady=8)
        for n, c in CORES.items():
            self.log.tag_config(n, foreground=c)
        self.status = tk.Label(raiz, text="", anchor="w", bg="#e8e8e8", padx=8)
        self.status.pack(fill="x", side="bottom")

        self.net = Conexao(cfg["servidor"], cfg["porta"], cfg["token"], cfg["usuario"], cfg["papel"], self.entrada)
        self.net.iniciar()
        raiz.protocol("WM_DELETE_WINDOW", self.fechar)
        raiz.after(200, self.ciclo)
        if primeira_execucao or not cfg["token"]:
            raiz.after(400, lambda: self.abrir_config(primeira=True))

    def titulo(self):
        c = self.cfg
        self.raiz.title(f"Cliente CBO {VERSAO} - {c['usuario']} ({c['papel']}) → {c['servidor']}:{c['porta']}")

    # ------------------------------------------------------------ configuracao do servidor
    def abrir_config(self, primeira=False):
        if getattr(self, "dlg_config", None) is not None:
            try:
                self.dlg_config.lift()
                return
            except tk.TclError:
                self.dlg_config = None
        d = self.dlg_config = tk.Toplevel(self.raiz)
        d.title("Configurar servidor")
        d.transient(self.raiz)
        d.resizable(False, False)
        d.configure(bg="white", padx=18, pady=14)
        tk.Label(d, text="Servidor da automação de CBO", font=("Segoe UI", 12, "bold"), bg="white").grid(
            row=0, column=0, columnspan=2, sticky="w")
        tk.Label(d, text=("Primeira configuração: informe o IP e o token exibidos no painel do servidor."
                          if primeira else "Altere os dados e use 'Testar conexão' antes de salvar."),
                 font=("Segoe UI", 9), bg="white", fg="#666").grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 8))
        v = {k: tk.StringVar(value=str(self.cfg[k])) for k in ("servidor", "porta", "token", "usuario", "papel")}
        linhas = (("Endereço/IP do servidor:", "servidor"), ("Porta:", "porta"), ("Token:", "token"),
                  ("Seu nome de usuário:", "usuario"), ("Papel:", "papel"))
        for i, (rot, k) in enumerate(linhas, start=2):
            tk.Label(d, text=rot, bg="white", font=("Segoe UI", 10)).grid(row=i, column=0, sticky="w", pady=3)
            if k == "papel":
                w = ttk.Combobox(d, textvariable=v[k], values=cliente_config.PAPEIS, state="readonly", width=24)
            else:
                w = tk.Entry(d, textvariable=v[k], width=27, font=("Segoe UI", 10), show="•" if k == "token" else "")
            w.grid(row=i, column=1, sticky="w", padx=(10, 0), pady=3)
        ver = tk.IntVar(value=0)
        tk.Checkbutton(d, text="Mostrar o token", variable=ver, bg="white", font=("Segoe UI", 9),
                       command=lambda: [w.config(show="" if ver.get() else "•")
                                        for w in d.grid_slaves(row=4, column=1)]).grid(
            row=7, column=1, sticky="w", padx=(10, 0))
        res = tk.Label(d, text="", bg="white", font=("Segoe UI", 9), wraplength=360, justify="left")
        res.grid(row=8, column=0, columnspan=2, sticky="w", pady=8)
        rq = queue.Queue()

        def coletar():
            c = {k: v[k].get().strip() for k in v}
            c["porta"] = c["porta"]
            return c

        def checar():
            c = coletar()
            erro = cliente_config.validar(c)
            if erro:
                res.config(text=erro, fg="#c62828")
                return None
            c["porta"] = int(c["porta"])
            return c

        def testar():
            c = checar()
            if not c:
                return
            res.config(text="Testando a conexão...", fg="#555")
            b_testar.config(state="disabled")
            threading.Thread(target=lambda: rq.put(testar_conexao(c["servidor"], c["porta"], c["token"],
                                                                  c["usuario"])), daemon=True).start()
            sondar()

        def sondar():
            try:
                ok, msg = rq.get_nowait()
            except queue.Empty:
                if d.winfo_exists():
                    d.after(150, sondar)
                return
            if d.winfo_exists():
                b_testar.config(state="normal")
                res.config(text=("✔ " if ok else "✖ ") + msg, fg="#1b7f2a" if ok else "#c62828")

        def salvar():
            c = checar()
            if not c:
                return
            papel_mudou = c["papel"] != self.cfg["papel"]
            try:
                cliente_config.salvar(c)
            except OSError as e:
                res.config(text=f"Não foi possível salvar o arquivo de configuração: {e}", fg="#c62828")
                return
            self.cfg = c
            self.usuario = c["usuario"]
            self.net.reconfigurar(c["servidor"], c["porta"], c["token"], c["usuario"], c["papel"])
            self.titulo()
            self.faixa.config(text="Conectando ao servidor...", bg="#fff3e0", fg="#e65100")
            fechar_dlg()
            if papel_mudou:
                messagebox.showinfo("Papel alterado", "Feche e abra o painel para aplicar o novo papel.",
                                    parent=self.raiz)

        def fechar_dlg():
            self.dlg_config = None
            d.destroy()

        rod = tk.Frame(d, bg="white")
        rod.grid(row=9, column=0, columnspan=2, sticky="e", pady=(4, 0))
        b_testar = tk.Button(rod, text="Testar conexão", command=testar, padx=8)
        b_testar.pack(side="left", padx=4)
        tk.Button(rod, text="Salvar e conectar", bg="#1565c0", fg="white", font=("Segoe UI", 9, "bold"),
                  command=salvar, padx=8).pack(side="left", padx=4)
        tk.Button(rod, text="Cancelar", command=fechar_dlg, padx=8).pack(side="left", padx=4)
        d.protocol("WM_DELETE_WINDOW", fechar_dlg)
        d.update_idletasks()
        x = self.raiz.winfo_x() + max(0, (self.raiz.winfo_width() - d.winfo_width()) // 2)
        d.geometry(f"+{x}+{self.raiz.winfo_y() + 80}")

    # ------------------------------------------------------------ acoes
    def enviar(self):
        conta = self.v_conta.get().strip()
        if not conta.isdigit():
            self.retorno.config(text="Digite só números.", fg="#c62828")
            return
        if not self.net.enviar({"tipo": "enviar_conta", "conta": conta}):
            self.retorno.config(text="Sem conexão com o servidor.", fg="#c62828")
            return
        self.v_conta.set("")

    def selecionada(self):
        sel = self.arvore.selection()
        return int(sel[0]) if sel else None

    def abrir_log(self):
        id_ = self.selecionada()
        if id_ is None:
            messagebox.showinfo("Log", "Selecione uma conta na lista.", parent=self.raiz)
            return
        self.net.enviar({"tipo": "pedir_log", "id": id_})

    def revisar(self):
        id_ = self.selecionada()
        c = self.contas.get(id_)
        if not c:
            messagebox.showinfo("Revisão", "Selecione uma conta na lista.", parent=self.raiz)
            return
        if c["estado"] in ("ENFILEIRADA", "PROCESSANDO"):
            messagebox.showinfo("Revisão", "A conta ainda não foi processada.", parent=self.raiz)
            return
        self.net.enviar({"tipo": "revisar", "id": id_})

    # ------------------------------------------------------------ mensagens do servidor
    def escrever(self, nivel, texto):
        self.log.config(state="normal")
        self.log.insert("end", texto + "\n", nivel)
        self.log.see("end")
        self.log.config(state="disabled")

    def ciclo(self):
        if self.net.encerrar:
            return
        try:
            while True:
                self.tratar(self.entrada.get_nowait())
        except queue.Empty:
            pass
        self.raiz.after(200, self.ciclo)

    def tratar(self, m):
        t = m.get("tipo")
        if t == "hello_ok":  # o servidor aceitou o token
            self.conectado = True
            self.recusado = False
            self.faixa.config(text="Conectado ao servidor", bg="#e8f5e9", fg="#1b5e20")
        elif t == "_conectado":
            pass  # socket aberto; a faixa so muda quando o servidor aceita (hello_ok) ou recusa (erro)
        elif t == "_desconectado":
            self.conectado = False
            if getattr(self, "recusado", False):
                return  # mantem o aviso de recusa em vez de piscar "sem conexao"
            self.faixa.config(text="SEM CONEXÃO com o servidor — tentando reconectar (veja ⚙ Configurar servidor)",
                              bg="#ffebee", fg="#b71c1c")
        elif t == "erro":
            self.recusado = True
            self.faixa.config(text="O servidor RECUSOU a conexão (token incorreto?) — corrija em ⚙ Configurar servidor",
                              bg="#ffebee", fg="#b71c1c")
        elif t == "fila":
            self.atualizar_fila(m["contas"], m.get("pausada"))
        elif t == "resposta_envio":
            if hasattr(self, "retorno"):
                if m["aceita"]:
                    self.retorno.config(text=f"Conta {m['conta']} entrou na fila.", fg="#1b7f2a")
                else:
                    self.retorno.config(text=f"Conta {m['conta']} recusada: {m['motivo']}", fg="#c62828")
        elif t == "log_linha":
            self.escrever(m["nivel"], f"[{m['conta']}] {m['msg']}")
        elif t == "conta_concluida":
            self.concluida(m)
        elif t == "conta_revisada":
            self.escrever("info", f"[{m['conta']}] Conta revisada por {m['por']}.")
        elif t == "log_conta":
            self.mostrar_log(m)

    def atualizar_fila(self, contas, pausada):
        self.contas = {c["id"]: c for c in contas}
        sel = self.arvore.selection()
        self.arvore.delete(*self.arvore.get_children())
        for c in reversed(contas):
            self.arvore.insert("", "end", iid=str(c["id"]), tags=(c["estado"],),
                               values=(c["id"], c["conta"], c["solicitante"], legivel(c["estado"]), legivel(c["revisao"]),
                                       "sim" if c["salvou"] else "não"))
        for s in sel:
            if self.arvore.exists(s):
                self.arvore.selection_set(s)
        pend = sum(1 for c in contas if c["estado"] in ("ENFILEIRADA", "PROCESSANDO"))
        rev = sum(1 for c in contas if c["estado"] not in ("ENFILEIRADA", "PROCESSANDO")
                  and c["revisao"] == "AGUARDANDO_REVISAO")
        self.status.config(text=f"Na fila/processando: {pend}   ·   Aguardando revisão: {rev}"
                                + ("   ·   FILA PAUSADA no servidor" if pausada else ""))

    def concluida(self, m):
        if m["solicitante"] == self.usuario:  # log do cliente que pediu: identico ao do servidor
            PASTA_CLIENTE.mkdir(exist_ok=True)
            arq = PASTA_CLIENTE / f"conta_{m['conta']}_{datetime.now():%Y%m%d_%H%M%S}.txt"
            arq.write_text(m["texto"], encoding="utf-8")
            self.escrever("info", f"[{m['conta']}] Log salvo em {arq}")
        r = m["resumo"]
        det = (f"Itens: {r.get('tratados')} de {r.get('total')}\nCBO incluído: {r.get('preenchidos')}\n"
               f"Já tinham CBO: {r.get('ja')}\nErros: {r.get('erros')} (toleradas: {r.get('toleradas')})")
        est = m["estado"]
        msg = f"Conta {m['conta']} (solicitante: {m['solicitante']})\n\n{det}\n\nMotivo: {m['motivo'] or '-'}\n\n" \
              "TODA conta precisa de REVISÃO MANUAL."
        if est == "SALVA":
            messagebox.showinfo("Conta salva - revisar", "Conta SALVA pela automação.\n\n" + msg, parent=self.raiz)
        elif est == "FALHA_CRITICA":
            messagebox.showerror("Falha crítica", "A automação PAROU por erro crítico.\n\n" + msg, parent=self.raiz)
        else:
            messagebox.showwarning("Conta NÃO salva - revisar", f"Situação: {legivel(est)}\nNada foi salvo.\n\n" + msg,
                                   parent=self.raiz)

    def mostrar_log(self, m):
        j = tk.Toplevel(self.raiz)
        j.title(f"Log da conta (id {m['id']})")
        j.geometry("760x520")
        t = scrolledtext.ScrolledText(j, font=("Consolas", 9), wrap="word")
        t.pack(fill="both", expand=True)
        t.insert("end", m["texto"])
        t.config(state="disabled")

    def fechar(self):
        self.net.fechar()
        self.raiz.destroy()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--papel", choices=cliente_config.PAPEIS)
    ap.add_argument("--usuario")
    ap.add_argument("--servidor")
    ap.add_argument("--porta", type=int)
    ap.add_argument("--token")
    a = ap.parse_args()
    cfg = cliente_config.carregar()
    primeira = not cliente_config.existe()
    for k in ("papel", "usuario", "servidor", "porta", "token"):
        if getattr(a, k):
            cfg[k] = getattr(a, k)
            primeira = False
    raiz = tk.Tk()
    PainelCliente(raiz, cfg, primeira)
    raiz.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:  # no .exe (sem console) o erro precisa ficar visivel
        txt = traceback.format_exc()
        try:
            (cliente_config.pasta_app() / "erro_cliente.txt").write_text(txt, encoding="utf-8")
            messagebox.showerror("Erro no painel cliente",
                                 "O painel encontrou um erro e precisa fechar.\nDetalhes em erro_cliente.txt.\n\n"
                                 + txt.splitlines()[-1])
        except Exception:
            pass
        sys.exit(1)
