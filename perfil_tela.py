"""Perfil de tela esperado pelo servidor (resolucao em que a automacao foi calibrada/testada).

O pacote do servidor pode trazer perfil_tela.json ao lado do executavel, ex.: {"largura": 1600,
"altura": 900}. Se a tela atual for diferente, o painel e o log avisam (a automacao depende de
posicoes dentro das telas do Salux).
"""
import ctypes
import json

from caminhos import pasta_app

ARQ = pasta_app() / "perfil_tela.json"


def esperado():
    try:
        d = json.loads(ARQ.read_text(encoding="utf-8"))
        return int(d["largura"]), int(d["altura"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def tela_atual():
    """Tamanho da tela no mesmo espaco de coordenadas que o pywinauto usa neste processo."""
    try:
        u = ctypes.windll.user32
        return int(u.GetSystemMetrics(0)), int(u.GetSystemMetrics(1))
    except Exception:
        return None


def aviso():
    """Texto de aviso se a tela atual difere do perfil esperado ('' se ok ou sem perfil)."""
    esp, atual = esperado(), tela_atual()
    if not esp or not atual or esp == atual:
        return ""
    return (f"ATENCAO: a tela e {atual[0]}x{atual[1]}, mas este pacote foi preparado para "
            f"{esp[0]}x{esp[1]} (100% de escala). A automacao pode clicar no lugar errado.")
