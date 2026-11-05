"""Uso pelo terminal: python preencher_cbo.py [max_itens]

A logica esta em cbo_core.py; a interface para a secretaria e painel_cbo.py.
"""
import sys
from datetime import datetime

import cbo_core


def log(nivel, msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}")


if __name__ == "__main__":
    limite = int(sys.argv[1]) if len(sys.argv) > 1 else None
    res = cbo_core.executar(log, limite=limite)
    sys.exit(0 if res.estado in ("CONCLUIDO", "CONCLUIDO_COM_ERROS") else 1)
