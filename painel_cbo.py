"""Painel para executar a automacao do CBO no Salux (um botao).

Uso: python painel_cbo.py   (ou duplo clique em iniciar_painel.bat)
A automacao roda numa thread; o painel so mostra o log e nao mexe no Salux.
"""
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, scrolledtext

import cbo_core
import config

ORIENTACAO = (
    "ANTES DE INICIAR\n\n"
    "  •  Deixe a conta aberta no Salux, na aba ITENS.\n\n"
    "NÃO MEXA NA TELA após iniciar:\n"
    "  •  Não use o mouse nem o teclado.\n"
    "  •  Não clique no Salux nem em outras janelas.\n"
    "  •  Não minimize nem feche o Salux.\n\n"
    "O painel avisará quando terminar e a tela estiver liberada.\n"
    "A automação NÃO salva nada: confira e salve manualmente."
)

CORES = {"info": "#555555", "ok": "#1b7f2a", "aviso": "#b36b00",
         "erro": "#c62828", "critico": "#c62828"}


class Painel:
    def __init__(self, raiz):
        self.raiz = raiz
        self.fila = queue.Queue()
        self.parar = threading.Event()
        self.thread = None
        self.arq = None
        self.inicio = 0.0
        self.rodando = False
        self.tem_erro = False

        raiz.title("Automação CBO - Salux")
        largura, altura = 600, 620
        sw = raiz.winfo_screenwidth()
        # canto direito: o Salux fica a esquerda (cerca de 860 px)
        raiz.geometry(f"{largura}x{altura}+{max(880, sw - largura - 20)}+20")
        raiz.configure(bg="#f4f4f4")

        tk.Label(raiz, text="Preenchimento automático de CBO", font=("Segoe UI", 14, "bold"),
                 bg="#f4f4f4").pack(pady=(12, 2))
        tk.Label(raiz, text="Aba Origem do Salux · não salva nada", font=("Segoe UI", 9),
                 bg="#f4f4f4", fg="#666").pack()

        self.faixa = tk.Label(raiz, text="", font=("Segoe UI", 11, "bold"), pady=6)
        self.faixa.pack(fill="x", pady=8)

        botoes = tk.Frame(raiz, bg="#f4f4f4")
        botoes.pack()
        self.b_iniciar = tk.Button(botoes, text="Iniciar automação", font=("Segoe UI", 12, "bold"),
                                   bg="#1565c0", fg="white", padx=18, pady=6,
                                   command=self.clicou_iniciar)
        self.b_iniciar.pack(side="left", padx=6)
        self.b_parar = tk.Button(botoes, text="Parar", font=("Segoe UI", 10), padx=10, pady=6,
                                 state="disabled", command=self.clicou_parar)
        self.b_parar.pack(side="left", padx=6)

        self.log = scrolledtext.ScrolledText(raiz, height=22, font=("Consolas", 9),
                                             state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True, padx=12, pady=8)
        for nivel, cor in CORES.items():
            self.log.tag_config(nivel, foreground=cor)
        self.log.tag_config("critico", foreground="#c62828", font=("Consolas", 9, "bold"))

        self.status = tk.Label(raiz, text="Pronto.", anchor="w", bg="#e8e8e8", padx=8)
        self.status.pack(fill="x", side="bottom")
        self.mostrar_faixa("pronto")
        self.raiz.after(150, self.consumir)

    # ------------------------------------------------------------ interface
    def mostrar_faixa(self, modo):
        textos = {"pronto": ("Pronto para iniciar", "#e3f2fd", "#0d47a1"),
                  "rodando": ("AUTOMAÇÃO EM EXECUÇÃO — NÃO MEXA NA TELA", "#ffebee", "#b71c1c"),
                  "liberado": ("Tela liberada — você já pode usar o Salux", "#e8f5e9", "#1b5e20")}
        t, bg, fg = textos[modo]
        self.faixa.config(text=t, bg=bg, fg=fg)

    def escrever(self, nivel, msg):
        linha = f"[{datetime.now():%H:%M:%S}] {msg}"
        self.log.config(state="normal")
        self.log.insert("end", linha + "\n", nivel)
        self.log.see("end")
        self.log.config(state="disabled")
        if self.arq:
            self.arq.write(linha + "\n")
            self.arq.flush()

    def consumir(self):
        try:
            while True:
                item = self.fila.get_nowait()
                if item[0] == "fim":
                    self.terminou(item[1])
                else:
                    self.escrever(item[0], item[1])
                    if item[0] in ("erro", "critico"):
                        self.tem_erro = True
        except queue.Empty:
            pass
        if self.rodando:
            seg = int(time.time() - self.inicio)
            self.status.config(text=f"Em execução · tempo {seg // 60:02d}:{seg % 60:02d}")
        self.raiz.after(300, self.consumir)

    # ------------------------------------------------------------ acoes
    def clicou_iniciar(self):
        if self.rodando:
            return
        if not self.confirmar():
            return
        pasta = Path(__file__).resolve().parent / config.PASTA_LOGS
        pasta.mkdir(exist_ok=True)
        caminho = pasta / f"execucao_{datetime.now():%Y%m%d_%H%M%S}.txt"
        self.arq = open(caminho, "w", encoding="utf-8")
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")
        self.escrever("info", f"Iniciando. Log em texto: {caminho}")
        self.parar.clear()
        self.tem_erro = False
        self.rodando = True
        self.inicio = time.time()
        self.b_iniciar.config(state="disabled")
        self.b_parar.config(state="normal")
        self.mostrar_faixa("rodando")
        self.thread = threading.Thread(target=self.trabalho, daemon=True)
        self.thread.start()

    def clicou_parar(self):
        self.parar.set()
        self.b_parar.config(state="disabled")
        self.escrever("aviso", "Parada solicitada: termina ao fim da linha atual...")

    def confirmar(self):
        """Caixa de orientacoes com Iniciar / Cancelar."""
        dlg = tk.Toplevel(self.raiz)
        dlg.title("Orientações")
        dlg.transient(self.raiz)
        dlg.configure(bg="white")
        dlg.resizable(False, False)
        tk.Label(dlg, text="⚠  Leia antes de iniciar", font=("Segoe UI", 13, "bold"),
                 bg="white", fg="#b71c1c").pack(padx=20, pady=(16, 6), anchor="w")
        tk.Label(dlg, text=ORIENTACAO, font=("Segoe UI", 10), bg="white", justify="left"
                 ).pack(padx=20, pady=6, anchor="w")
        resp = {"ok": False}
        rod = tk.Frame(dlg, bg="white")
        rod.pack(pady=14)

        def fechar(v):
            resp["ok"] = v
            dlg.destroy()

        tk.Button(rod, text="Iniciar", font=("Segoe UI", 11, "bold"), bg="#1565c0", fg="white",
                  padx=20, command=lambda: fechar(True)).pack(side="left", padx=8)
        tk.Button(rod, text="Cancelar", font=("Segoe UI", 11), padx=14,
                  command=lambda: fechar(False)).pack(side="left", padx=8)
        dlg.protocol("WM_DELETE_WINDOW", lambda: fechar(False))
        dlg.update_idletasks()
        x = self.raiz.winfo_x() + (self.raiz.winfo_width() - dlg.winfo_width()) // 2
        y = self.raiz.winfo_y() + 60
        dlg.geometry(f"+{x}+{y}")
        dlg.grab_set()
        self.raiz.wait_window(dlg)
        return resp["ok"]

    # ------------------------------------------------------------ thread
    def trabalho(self):
        def log(nivel, msg):
            self.fila.put((nivel, msg))
        try:
            res = cbo_core.executar(log, self.parar)
        except Exception as e:  # nao deveria ocorrer: executar trata tudo
            log("critico", f"ERRO CRITICO inesperado: {type(e).__name__}: {e}")
            res = cbo_core.Resultado(estado="CRITICO", mensagem=str(e))
        self.fila.put(("fim", res))

    def terminou(self, res):
        self.rodando = False
        if self.arq:
            self.arq.close()
            self.arq = None
        self.b_iniciar.config(state="normal")
        self.b_parar.config(state="disabled")
        self.mostrar_faixa("liberado")
        self.status.config(text=f"{res.estado} · tempo {res.tempo}")
        # traz o painel para frente
        self.raiz.deiconify()
        self.raiz.lift()
        self.raiz.attributes("-topmost", True)
        self.raiz.after(500, lambda: self.raiz.attributes("-topmost", False))
        self.raiz.focus_force()

        resumo = (f"Itens tratados: {res.tratados} de {res.total}\n"
                  f"CBO incluído: {res.preenchidos}\n"
                  f"Já tinham CBO: {res.ja_preenchidos}\n"
                  f"Tempo: {res.tempo}")
        liberacao = "\n\nTELA LIBERADA: você já pode usar o mouse, o teclado e o Salux."
        nao_salvou = "\nNada foi salvo: confira a aba Origem e salve manualmente."
        if res.estado == "CONCLUIDO":
            messagebox.showinfo("Concluído", "Automação concluída com sucesso.\n\n" + resumo
                                + nao_salvou + liberacao, parent=self.raiz)
        elif res.estado == "CONCLUIDO_COM_ERROS":
            linhas = ", ".join(str(l) for l, _ in res.erros[:25])
            mais = " ..." if len(res.erros) > 25 else ""
            messagebox.showwarning(
                "Concluído com avisos",
                "Automação concluída, mas houve erros em algumas linhas.\n\n" + resumo
                + f"\n\nLinhas com erro ({len(res.erros)}): {linhas}{mais}\n"
                "Detalhes no log do painel e em logs/." + nao_salvou + liberacao,
                parent=self.raiz)
        elif res.estado == "INTERROMPIDO":
            messagebox.showwarning("Interrompido", "Automação interrompida a pedido.\n\n" + resumo
                                   + nao_salvou + liberacao, parent=self.raiz)
        else:
            messagebox.showerror(
                "Automação interrompida (erro crítico)",
                f"{res.mensagem}\n\nA automação foi parada.\n\n" + resumo + nao_salvou
                + "\nDetalhes no log do painel e em logs/." + liberacao, parent=self.raiz)


def main():
    raiz = tk.Tk()
    Painel(raiz)
    raiz.mainloop()


if __name__ == "__main__":
    main()
