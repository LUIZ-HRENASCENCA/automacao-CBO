"""Pasta onde o programa le/grava arquivos (config, banco, logs, .env).

Em desenvolvimento: a pasta do projeto. Empacotado (PyInstaller): a pasta do executavel
(NAO a pasta interna _internal, onde ficam os modulos).
"""
import sys
from pathlib import Path


def pasta_app():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent
