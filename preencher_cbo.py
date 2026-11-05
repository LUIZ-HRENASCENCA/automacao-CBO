"""Uso pelo terminal: python preencher_cbo.py [--conta NUMERO] [max_itens]

A logica esta em cbo_core.py; a interface para a secretaria e painel_cbo.py.
"""
import sys
from datetime import datetime

import cbo_core


def log(nivel, msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}")


if __name__ == "__main__":
    args = sys.argv[1:]
    conta = None
    if "--conta" in args:
        i = args.index("--conta")
        conta = args[i + 1]
        del args[i:i + 2]
    manual = "--espera-login" in args  # uma pessoa digita o login; o script espera
    if manual:
        args.remove("--espera-login")
    if "--login" in args or manual:  # sobe portal, login (.env ou manual) e abre o Faturamento
        if "--login" in args:
            args.remove("--login")
        import salux_sessao
        salux_sessao.garantir_faturamento(lambda m: log("INFO", m), login_manual=manual)
    limite = int(args[0]) if args else None
    res = cbo_core.executar(log, limite=limite, conta=conta)
    sys.exit(0 if res.estado in ("CONCLUIDO", "CONCLUIDO_COM_ERROS") else 1)
