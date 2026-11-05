"""Protocolo cliente-servidor: uma mensagem JSON por linha (UTF-8) sobre TCP.

Cliente -> servidor:
  hello         {token, usuario, papel}            (obrigatorio, primeira mensagem)
  enviar_conta  {conta}
  revisar       {id}
  pedir_log     {id}
  listar        {}
Servidor -> cliente:
  hello_ok      {servidor}
  erro          {msg}
  resposta_envio {aceita, id, conta, motivo}
  fila          {contas: [...], pausada}
  log_linha     {id, conta, solicitante, nivel, hora, msg}
  conta_concluida {id, conta, solicitante, estado, salvou, motivo, resumo, texto}
  conta_revisada  {id, conta, por}
  log_conta     {id, texto}
"""
import json


def legivel(s):
    """Nome de estado para exibir (sem underline): NAO_SALVA -> NAO SALVA."""
    return str(s or "").replace("_", " ")


def codificar(msg):
    return (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")


def decodificar(linha):
    return json.loads(linha.decode("utf-8"))


async def ler(reader):
    """asyncio: proxima mensagem ou None se a conexao fechou."""
    linha = await reader.readline()
    if not linha:
        return None
    return decodificar(linha)
