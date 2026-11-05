"""Conexao do painel cliente com o servidor: thread com reconexao automatica.

Entrega as mensagens do servidor numa queue.Queue (a interface le de la).
Mensagens internas: {"tipo": "_conectado"} e {"tipo": "_desconectado"}.
"""
import json
import socket
import threading
import time

import protocolo


class Conexao:
    def __init__(self, host, porta, token, usuario, papel, entrada):
        self.host, self.porta, self.token = host, porta, token
        self.usuario, self.papel = usuario, papel
        self.entrada = entrada
        self.sock = None
        self.lock = threading.Lock()
        self.encerrar = False

    def iniciar(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def fechar(self):
        self.encerrar = True
        try:
            self.sock.close()
        except Exception:
            pass

    def enviar(self, msg):
        with self.lock:
            try:
                self.sock.sendall(protocolo.codificar(msg))
                return True
            except Exception:
                return False

    def _loop(self):
        while not self.encerrar:
            try:
                self.sock = socket.create_connection((self.host, self.porta), timeout=5)
                self.sock.settimeout(None)
                self.enviar({"tipo": "hello", "token": self.token, "usuario": self.usuario,
                             "papel": self.papel})
                self.entrada.put({"tipo": "_conectado"})
                with self.sock.makefile("rb") as f:
                    for linha in f:
                        self.entrada.put(json.loads(linha.decode("utf-8")))
            except Exception:
                pass
            if self.encerrar:
                break
            self.entrada.put({"tipo": "_desconectado"})
            time.sleep(2)
