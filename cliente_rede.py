"""Conexao do painel cliente com o servidor: thread com reconexao automatica.

Entrega as mensagens do servidor numa queue.Queue (a interface le de la).
Mensagens internas: {"tipo": "_conectado"} e {"tipo": "_desconectado"}.
"""
import json
import socket
import threading
import time

import protocolo
from versao import VERSAO


def testar_conexao(host, porta, token, usuario="teste", timeout=4.0):
    """Tenta conectar e autenticar. Devolve (ok, mensagem em portugues)."""
    sock = None
    try:
        sock = socket.create_connection((host, int(porta)), timeout=timeout)
        sock.settimeout(timeout)
        sock.sendall(protocolo.codificar({"tipo": "hello", "token": token, "usuario": usuario,
                                          "papel": "teste", "versao": VERSAO}))
        buf = b""
        while b"\n" not in buf:
            dados = sock.recv(4096)
            if not dados:
                return False, "O servidor fechou a conexão sem responder."
            buf += dados
        resp = protocolo.decodificar(buf.split(b"\n", 1)[0])
        if resp.get("tipo") == "hello_ok":
            return True, "Conexão OK: servidor encontrado e token aceito."
        if resp.get("tipo") == "erro":
            return False, "O servidor recusou: token incorreto (confira o token exibido no painel do servidor)."
        return False, "Resposta inesperada do servidor."
    except socket.gaierror:
        return False, "Endereço não encontrado: confira o nome/IP do servidor."
    except socket.timeout:
        return False, ("Sem resposta do servidor (tempo esgotado). Confira o IP, a porta e se o "
                       "painel do servidor está aberto.")
    except ConnectionRefusedError:
        return False, "Conexão recusada: o servidor não está aberto nessa porta."
    except (OSError, ValueError) as e:
        return False, f"Não foi possível conectar: {e}"
    finally:
        if sock:
            try:
                sock.close()
            except OSError:
                pass


class Conexao:
    def __init__(self, host, porta, token, usuario, papel, entrada):
        self.host, self.porta, self.token = host, porta, token
        self.usuario, self.papel = usuario, papel
        self.entrada = entrada
        self.sock = None
        self.lock = threading.Lock()
        self.encerrar = False
        self.gen = 0  # identifica a thread de conexao atual (reconfigurar invalida as antigas)

    def iniciar(self):
        self.gen += 1
        threading.Thread(target=self._loop, args=(self.gen,), daemon=True).start()

    def _derrubar(self):
        """Fecha de verdade o socket atual (shutdown interrompe a leitura da thread da conexao)."""
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass

    def fechar(self):
        self.encerrar = True
        self._derrubar()

    def reconfigurar(self, host, porta, token, usuario, papel):
        """Troca o servidor/token/usuario sem reiniciar o painel."""
        self.gen += 1          # a thread antiga sai ao perceber a troca
        self._derrubar()
        self.host, self.porta, self.token = host, porta, token
        self.usuario, self.papel = usuario, papel
        self.encerrar = False
        self.entrada.put({"tipo": "_desconectado"})
        self.iniciar()

    def enviar(self, msg):
        with self.lock:
            try:
                self.sock.sendall(protocolo.codificar(msg))
                return True
            except Exception:
                return False

    def _loop(self, gen):
        while not self.encerrar and gen == self.gen:
            try:
                sock = socket.create_connection((self.host, int(self.porta)), timeout=5)
                sock.settimeout(None)
                if gen != self.gen:
                    sock.close()
                    break
                self.sock = sock
                self.enviar({"tipo": "hello", "token": self.token, "usuario": self.usuario,
                             "papel": self.papel, "versao": VERSAO})
                self.entrada.put({"tipo": "_conectado"})
                with sock.makefile("rb") as f:
                    for linha in f:
                        self.entrada.put(json.loads(linha.decode("utf-8")))
            except Exception:
                pass
            if self.encerrar or gen != self.gen:
                break
            self.entrada.put({"tipo": "_desconectado"})
            time.sleep(2)
