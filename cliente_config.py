"""Configuracao do painel cliente: servidor, porta, token, usuario e papel.

Fica em cliente_config.json AO LADO do executavel (ou da pasta do projeto, em desenvolvimento).
O token nunca vem embutido no pacote: e digitado na primeira execucao.
"""
import getpass
import json
import sys
from pathlib import Path

import config

PAPEIS = ("operador", "secretaria", "ambos")


def pasta_app():
    """Pasta do executavel (PyInstaller) ou do projeto."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


ARQ = pasta_app() / "cliente_config.json"


def padrao():
    return {"servidor": config.SERVIDOR_HOST, "porta": config.SERVIDOR_PORTA, "token": "",
            "usuario": getpass.getuser(), "papel": "ambos"}


def existe(arq=None):
    return Path(arq or ARQ).exists()


def carregar(arq=None):
    """Padroes + o que estiver no arquivo (valores invalidos sao ignorados)."""
    cfg = padrao()
    try:
        dados = json.loads(Path(arq or ARQ).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return cfg
    if not isinstance(dados, dict):
        return cfg
    for k in cfg:
        if k in dados and dados[k] not in (None, ""):
            cfg[k] = dados[k]
    try:
        cfg["porta"] = int(cfg["porta"])
    except (TypeError, ValueError):
        cfg["porta"] = config.SERVIDOR_PORTA
    if cfg["papel"] not in PAPEIS:
        cfg["papel"] = "ambos"
    return cfg


def salvar(cfg, arq=None):
    dados = {k: cfg[k] for k in padrao()}
    Path(arq or ARQ).write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def validar(cfg):
    """Mensagem de erro (texto) ou '' se a configuracao estiver completa."""
    srv = str(cfg.get("servidor", "")).strip()
    if not srv or " " in srv:
        return "Informe o endereço (IP ou nome) do servidor, sem espaços."
    try:
        porta = int(cfg.get("porta"))
        if not 1 <= porta <= 65535:
            raise ValueError
    except (TypeError, ValueError):
        return "A porta deve ser um número entre 1 e 65535."
    if not str(cfg.get("token", "")).strip():
        return "Informe o token (aparece no painel do servidor)."
    if not str(cfg.get("usuario", "")).strip():
        return "Informe o nome do usuário."
    if cfg.get("papel") not in PAPEIS:
        return "Papel inválido."
    return ""
