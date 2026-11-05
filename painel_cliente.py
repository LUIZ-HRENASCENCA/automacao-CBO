"""Painel do CLIENTE (operador e/ou secretarias).

Uso: python painel_cliente.py [--papel operador|secretaria|ambos] [--usuario NOME] [--servidor HOST]
  operador   : digita o numero da conta e envia para a fila do servidor.
  secretaria : recebe o aviso quando cada conta termina, confere e marca como REVISADA.
  ambos      : os dois (padrao, para simulacao na mesma maquina).
O log mostrado e o MESMO do servidor (linha a linha, em tempo real); ao concluir, o texto completo
e gravado em logs_cliente/ para quem solicitou a conta. Duplo clique em uma conta abre o log completo.
"""
import argparse
import getpass
import queue
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

import config
from cliente_rede import Conexao
from protocolo import legivel

CORES = {"info": "#555555", "ok": "#1b7f2a", "aviso": "#b36b00", "erro": "#c62828", "critico": "#c62828"}
COR_ESTADO = {"SALVA": "#1b7f2a", "NAO_SALVA": "#b36b00", "CONTA_INVALIDA": "#b36b00",
              "FALHA_CRITICA": "#c62828", "PROCESSANDO": "#1565c0"}
PASTA_CLIENTE = Path(__file__).resolve().parent / "logs_cliente"


class PainelCliente:
    def __init__(self, raiz, papel, usuario, host):
        self.raiz, self.papel, self.usuario = raiz, papel, usuario
        self.entrada = queue.Queue()
        self.contas = {}
        self.conectado = False
        raiz.title(f"Cliente CBO - {usuario} ({papel})")
        raiz.geometry("900x700+960+30")
        raiz.configure(bg="#f4f4f4")

        self.faixa = tk.Label(raiz, text="Conectando ao servidor...", font=("Segoe UI", 11, "bold"), pady=6,
                              bg="#fff3e0", fg="#e65100")
        self.faixa.pack(fill="x")

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

        self.net = Conexao(host, config.SERVIDOR_PORTA, config.TOKEN, usuario, papel, self.entrada)
        self.net.iniciar()
        raiz.protocol("WM_DELETE_WINDOW", self.fechar)
        raiz.after(200, self.ciclo)

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
        if t == "_conectado":
            self.conectado = True
            self.faixa.config(text="Conectado ao servidor", bg="#e8f5e9", fg="#1b5e20")
        elif t == "_desconectado":
            self.conectado = False
            self.faixa.config(text="SEM CONEXÃO com o servidor — tentando reconectar...", bg="#ffebee", fg="#b71c1c")
        elif t == "erro":
            self.faixa.config(text=f"Servidor recusou: {m.get('msg')}", bg="#ffebee", fg="#b71c1c")
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
    ap.add_argument("--papel", default="ambos", choices=["operador", "secretaria", "ambos"])
    ap.add_argument("--usuario", default=getpass.getuser())
    ap.add_argument("--servidor", default=config.SERVIDOR_HOST)
    a = ap.parse_args()
    raiz = tk.Tk()
    PainelCliente(raiz, a.papel, a.usuario, a.servidor)
    raiz.mainloop()


if __name__ == "__main__":
    main()
