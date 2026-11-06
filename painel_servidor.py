"""Painel do SERVIDOR: monitora a fila, o log ao vivo e escolhe o modo do worker.

Uso: python painel_servidor.py   (ou iniciar_servidor.bat)
Modo Simulado: sem Salux (ultimo digito da conta escolhe o cenario). Modo Salux real: faz login
(.env), abre o Faturamento e processa de verdade; o salvamento ainda NAO existe, entao a conta
fica aberta e a fila pausa depois de cada conta.
"""
import queue
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

import servidor_config
from protocolo import legivel
from banco import Banco
from servidor_cbo import Servidor
from workers import WorkerSalux, WorkerSimulado

CORES = {"info": "#555555", "ok": "#1b7f2a", "aviso": "#b36b00", "erro": "#c62828", "critico": "#c62828"}
COR_ESTADO = {"SALVA": "#1b7f2a", "NAO_SALVA": "#b36b00", "CONTA_INVALIDA": "#b36b00",
              "FALHA_CRITICA": "#c62828", "PROCESSANDO": "#1565c0"}


class PainelServidor:
    def __init__(self, raiz):
        self.raiz = raiz
        self.fila_log = queue.Queue()
        self.banco = Banco()
        raiz.title("Servidor CBO - fila de contas")
        raiz.geometry("900x680+30+30")
        raiz.configure(bg="#f4f4f4")

        self.faixa = tk.Label(raiz, text="", font=("Segoe UI", 11, "bold"), pady=6)
        self.faixa.pack(fill="x")
        self.info = tk.Frame(raiz, bg="#e3f2fd")
        self.info.pack(fill="x", padx=12, pady=(6, 0))
        self.l_info = tk.Label(self.info, text="", bg="#e3f2fd", fg="#0d47a1", font=("Segoe UI", 10, "bold"),
                               anchor="w", justify="left")
        self.l_info.pack(side="left", padx=8, pady=6)
        tk.Button(self.info, text="Copiar token", command=self.copiar_token).pack(side="right", padx=8)
        topo = tk.Frame(raiz, bg="#f4f4f4")
        topo.pack(fill="x", padx=12, pady=6)
        tk.Label(topo, text="Modo do worker:", bg="#f4f4f4").pack(side="left")
        self.modo = tk.StringVar(value="simulado")
        tk.Radiobutton(topo, text="Simulado", variable=self.modo, value="simulado", bg="#f4f4f4").pack(side="left", padx=6)
        tk.Radiobutton(topo, text="Salux real (salva e fecha a conta)", variable=self.modo, value="salux", bg="#f4f4f4").pack(side="left")
        tk.Label(topo, text="máx. itens:", bg="#f4f4f4").pack(side="left", padx=(12, 2))
        self.v_limite = tk.StringVar()
        tk.Entry(topo, textvariable=self.v_limite, width=4).pack(side="left")
        self.b_pausa = tk.Button(topo, text="Pausar fila", width=12, command=self.alternar_pausa)
        self.b_pausa.pack(side="right", padx=4)
        tk.Button(topo, text="Parar conta atual", command=self.parar_atual).pack(side="right", padx=4)
        tk.Button(topo, text="Reiniciar fila", bg="#e65100", fg="white", command=self.reiniciar).pack(side="right", padx=4)

        cols = ("id", "conta", "solicitante", "estado", "revisao", "salvou", "tempo")
        self.arvore = ttk.Treeview(raiz, columns=cols, show="headings", height=9)
        for c, t, w in (("id", "#", 40), ("conta", "Conta", 90), ("solicitante", "Solicitante", 130),
                        ("estado", "Estado", 130), ("revisao", "Revisão", 150), ("salvou", "Salvou", 60),
                        ("tempo", "Tempo", 80)):
            self.arvore.heading(c, text=t)
            self.arvore.column(c, width=w, anchor="w")
        for e, cor in COR_ESTADO.items():
            self.arvore.tag_configure(e, foreground=cor)
        self.arvore.pack(fill="x", padx=12)

        self.log = scrolledtext.ScrolledText(raiz, height=20, font=("Consolas", 9), state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True, padx=12, pady=8)
        for n, c in CORES.items():
            self.log.tag_config(n, foreground=c)
        self.status = tk.Label(raiz, text="", anchor="w", bg="#e8e8e8", padx=8)
        self.status.pack(fill="x", side="bottom")

        self.srv = Servidor(self.banco, self.obter_worker, on_log=lambda *a: self.fila_log.put(a))
        if not self.srv.iniciar():
            messagebox.showerror("Servidor", self.srv.erro)
            raiz.destroy()
            return
        ips = servidor_config.ips_locais() if self.srv.bind in ("0.0.0.0", "") else [self.srv.bind]
        ender = " ou ".join(f"{ip}:{self.srv.porta}" for ip in ips) or f"<IP desta máquina>:{self.srv.porta}"
        self.l_info.config(text=f"Informe aos clientes →  Servidor: {ender}     Token: {self.srv.token}")
        self.escrever("info", f"Servidor escutando em {self.srv.bind}:{self.srv.porta}. "
                              f"Clientes devem usar: {ender} (token no topo da janela).")
        raiz.protocol("WM_DELETE_WINDOW", self.fechar)
        self.raiz.after(200, self.ciclo)

    def obter_worker(self):
        if self.modo.get() == "salux":
            lim = self.v_limite.get().strip()
            return WorkerSalux(limite=int(lim) if lim.isdigit() else None)
        return WorkerSimulado()

    def copiar_token(self):
        self.raiz.clipboard_clear()
        self.raiz.clipboard_append(self.srv.token)
        self.escrever("info", "Token copiado para a área de transferência.")

    def alternar_pausa(self):
        self.srv.pausar(not self.srv.pausada)

    def reiniciar(self):
        if self.srv.atual:
            messagebox.showinfo("Reiniciar fila", "Há uma conta em processamento. Aguarde terminar.")
            return
        falhas = self.banco.falhas_criticas()
        if not falhas:
            if self.srv.pausada and messagebox.askyesno(
                    "Reiniciar fila", "Nenhuma conta com falha crítica. Apenas retomar a fila?"):
                self.srv.pausar(False)
                self.escrever("info", "Fila retomada.")
            elif not self.srv.pausada:
                messagebox.showinfo("Reiniciar fila", "Nenhuma conta com falha crítica para reenfileirar.")
            return
        contas = ", ".join(c["conta"] for c in falhas)
        if messagebox.askyesno("Reiniciar fila",
                               f"Reenfileirar {len(falhas)} conta(s) com falha crítica e retomar a fila?\n\n{contas}\n\n"
                               "Confira antes se o Salux está normal e sem conta aberta."):
            n = self.srv.reiniciar_fila()
            self.escrever("aviso", f"Fila reiniciada: {n} conta(s) com falha crítica reenfileirada(s).")

    def parar_atual(self):
        self.srv.parar_atual.set()

    def escrever(self, nivel, msg, conta=None, hora=None):
        from datetime import datetime
        h = hora or datetime.now().strftime("%H:%M:%S")
        pre = f"[{conta}] " if conta else ""
        self.log.config(state="normal")
        self.log.insert("end", f"[{h}] {pre}{msg}\n", nivel)
        self.log.see("end")
        self.log.config(state="disabled")

    def ciclo(self):
        try:
            while True:
                id_, conta, nivel, hora, msg = self.fila_log.get_nowait()
                self.escrever(nivel, msg, conta, hora)
        except queue.Empty:
            pass
        sel = self.arvore.selection()
        self.arvore.delete(*self.arvore.get_children())
        for c in reversed(self.banco.listar(60)):
            self.arvore.insert("", "end", iid=str(c["id"]), tags=(c["estado"],),
                               values=(c["id"], c["conta"], c["solicitante"], legivel(c["estado"]), legivel(c["revisao"]),
                                       "sim" if c["salvou"] else "não", c["tempo"] or ""))
        if self.srv.pausada:
            self.faixa.config(text="FILA PAUSADA — nenhuma conta nova será processada", bg="#fff3e0", fg="#e65100")
            self.b_pausa.config(text="Retomar fila")
        elif self.srv.atual:
            self.faixa.config(text="PROCESSANDO — NÃO MEXA NA TELA DO SERVIDOR", bg="#ffebee", fg="#b71c1c")
            self.b_pausa.config(text="Pausar fila")
        else:
            self.faixa.config(text="Aguardando contas", bg="#e8f5e9", fg="#1b5e20")
            self.b_pausa.config(text="Pausar fila")
        cl = self.srv.lista_clientes()
        nomes = ", ".join(f"{c['usuario']} ({c['papel']}, v{c['versao']})" for c in cl) or "nenhum"
        self.status.config(text=f"Clientes conectados: {len(cl)} — {nomes}   ·   "
                                f"Escutando em {self.srv.bind}:{self.srv.porta}")
        self.raiz.after(500, self.ciclo)

    def fechar(self):
        if self.srv.atual and not messagebox.askyesno("Servidor", "Há uma conta em processamento. Sair mesmo assim?"):
            return
        self.srv.parar()
        self.raiz.destroy()


def main():
    raiz = tk.Tk()
    PainelServidor(raiz)
    raiz.mainloop()


if __name__ == "__main__":
    main()
