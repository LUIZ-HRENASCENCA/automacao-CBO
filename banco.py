"""Banco SQLite do servidor: fila de contas e eventos de log (fonte da verdade dos logs)."""
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from caminhos import pasta_app

ARQ = pasta_app() / "fila.db"
ATIVAS = ("ENFILEIRADA", "PROCESSANDO")

SQL = """
CREATE TABLE IF NOT EXISTS contas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conta TEXT NOT NULL,
    solicitante TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'ENFILEIRADA',
    revisao TEXT NOT NULL DEFAULT 'AGUARDANDO_REVISAO',
    salvou INTEGER NOT NULL DEFAULT 0,
    motivo TEXT DEFAULT '',
    resumo TEXT DEFAULT '',
    modo TEXT DEFAULT '',
    tempo TEXT DEFAULT '',
    criada TEXT, inicio TEXT, fim TEXT,
    revisada_por TEXT, revisada_em TEXT
);
CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conta_id INTEGER NOT NULL,
    hora TEXT, nivel TEXT, msg TEXT
);
CREATE INDEX IF NOT EXISTS ix_eventos_conta ON eventos(conta_id);
"""


def agora():
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


class Banco:
    def __init__(self, arq=ARQ):
        self.c = sqlite3.connect(str(arq), check_same_thread=False)
        self.c.row_factory = sqlite3.Row
        self.l = threading.RLock()
        with self.l:
            self.c.executescript(SQL)
            self.c.commit()

    def criar(self, conta, solicitante):
        with self.l:
            cur = self.c.execute("INSERT INTO contas(conta, solicitante, criada) VALUES (?,?,?)",
                                 (conta, solicitante, agora()))
            self.c.commit()
            return cur.lastrowid

    def ativa(self, conta):
        with self.l:
            r = self.c.execute("SELECT id FROM contas WHERE conta=? AND estado IN ('ENFILEIRADA','PROCESSANDO')",
                               (conta,)).fetchone()
            return r is not None

    def proxima(self):
        with self.l:
            r = self.c.execute("SELECT * FROM contas WHERE estado='ENFILEIRADA' ORDER BY id LIMIT 1").fetchone()
            return dict(r) if r else None

    def get(self, id_):
        with self.l:
            r = self.c.execute("SELECT * FROM contas WHERE id=?", (id_,)).fetchone()
            return dict(r) if r else None

    def atualizar(self, id_, **campos):
        if not campos:
            return
        cols = ", ".join(f"{k}=?" for k in campos)
        with self.l:
            self.c.execute(f"UPDATE contas SET {cols} WHERE id=?", (*campos.values(), id_))
            self.c.commit()

    def evento(self, id_, nivel, msg, hora=None):
        with self.l:
            self.c.execute("INSERT INTO eventos(conta_id, hora, nivel, msg) VALUES (?,?,?,?)",
                           (id_, hora or datetime.now().strftime("%H:%M:%S"), nivel, msg))
            self.c.commit()

    def eventos(self, id_):
        with self.l:
            return [dict(r) for r in self.c.execute(
                "SELECT hora, nivel, msg FROM eventos WHERE conta_id=? ORDER BY id", (id_,))]

    def listar(self, limite=200):
        with self.l:
            return [dict(r) for r in self.c.execute(
                "SELECT * FROM contas ORDER BY id DESC LIMIT ?", (limite,))][::-1]

    def falhas_criticas(self):
        """Contas em FALHA_CRITICA que nao tem outra tentativa ativa com o mesmo numero."""
        with self.l:
            return [dict(r) for r in self.c.execute(
                "SELECT * FROM contas f WHERE f.estado='FALHA_CRITICA' AND NOT EXISTS ("
                "SELECT 1 FROM contas a WHERE a.conta=f.conta AND a.estado IN ('ENFILEIRADA','PROCESSANDO')) "
                "ORDER BY f.id")]

    def reenfileirar(self, id_):
        with self.l:
            self.c.execute("UPDATE contas SET estado='ENFILEIRADA', revisao='AGUARDANDO_REVISAO', salvou=0, "
                           "motivo='', resumo='', tempo='', inicio=NULL, fim=NULL, revisada_por=NULL, "
                           "revisada_em=NULL WHERE id=? AND estado='FALHA_CRITICA'", (id_,))
            self.c.commit()

    def recuperar(self):
        """Apos reinicio do servidor: conta que estava PROCESSANDO nao sera retomada sozinha."""
        with self.l:
            ids = [r["id"] for r in self.c.execute("SELECT id FROM contas WHERE estado='PROCESSANDO'")]
            self.c.execute("UPDATE contas SET estado='FALHA_CRITICA', fim=?, "
                           "motivo='O servidor foi reiniciado durante o processamento.' "
                           "WHERE estado='PROCESSANDO'", (agora(),))
            self.c.commit()
            return ids
