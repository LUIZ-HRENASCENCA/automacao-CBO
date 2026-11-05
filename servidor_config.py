"""Configuracao do servidor: bind, porta e token (gerado na primeira execucao).

Fica em servidor_config.json (no .gitignore). O token e a senha compartilhada que os paineis
cliente precisam informar; o painel do servidor o exibe para ser digitado nos clientes.
"""
import json
import secrets
import socket
from pathlib import Path

import config

ARQ = Path(__file__).resolve().parent / "servidor_config.json"
# sem caracteres ambiguos (0/O, 1/l/I) para ser facil de digitar
ALFABETO = "abcdefghjkmnpqrstuvwxyz23456789"


def gerar_token(tamanho=10):
    return "".join(secrets.choice(ALFABETO) for _ in range(tamanho))


def carregar(arq=None):
    arq = Path(arq or ARQ)
    cfg = {"bind": config.SERVIDOR_BIND, "porta": config.SERVIDOR_PORTA, "token": ""}
    try:
        dados = json.loads(arq.read_text(encoding="utf-8"))
        if isinstance(dados, dict):
            for k in cfg:
                if dados.get(k) not in (None, ""):
                    cfg[k] = dados[k]
    except (OSError, ValueError):
        pass
    try:
        cfg["porta"] = int(cfg["porta"])
    except (TypeError, ValueError):
        cfg["porta"] = config.SERVIDOR_PORTA
    if not cfg["token"]:
        cfg["token"] = gerar_token()
        arq.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


def ips_locais():
    """Enderecos IPv4 desta maquina (sem loopback), para informar aos clientes."""
    ips = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    if not ips:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("10.255.255.255", 1))
            ips.append(s.getsockname()[0])
            s.close()
        except OSError:
            pass
    return ips
