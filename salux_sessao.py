"""Sessao do Salux: iniciar o portal, aguardar o login e abrir o modulo Faturamento.

Mapeado:
  * portal.exe e iniciado SEM argumentos; ele abre a tela de login. Depois do login mostra o
    Portal (titulo termina em 'Portal Salux SX <versao>') com menu a esquerda (grupos) e,
    ao lado, azulejos dos modulos. O faturam.exe NAO e iniciado direto: e filho do portal
    e recebe argumentos dele; por isso o Faturamento e aberto clicando no azulejo.
  * Menu e azulejos sao DataWindow (pbdw): precisam de clique real do mouse; as posicoes
    abaixo sao relativas ao DataWindow correspondente (dependem da escala de tela).

Credenciais: lidas do arquivo .env (USERNAME e SENHA; fora do git) por fazer_login. Nunca sao
impressas nem gravadas em log. Sem SENHA no .env, aguardar_login espera uma pessoa entrar.
No servidor, restrinja a permissao do .env ao usuario do Windows que roda a automacao.
"""
import subprocess
import time
from pathlib import Path

from pywinauto import Application, mouse

import config
from caminhos import pasta_app

TITULO_PORTAL = "Portal Salux SX"


def _janelas(app):
    for _ in range(4):
        try:
            return app.windows()
        except Exception:
            time.sleep(0.2)
    return []


def _conectar(exe, timeout=3):
    try:
        return Application(backend=config.BACKEND).connect(path=exe, timeout=timeout)
    except Exception:
        return None


def janela_portal(app):
    """Janela principal do portal ja logado (titulo termina com 'Portal Salux SX <versao>')."""
    for w in _janelas(app):
        if w.class_name() == "FNWND3" and TITULO_PORTAL in w.window_text():
            return w
    return None


def faturamento_aberto():
    app = _conectar(config.EXE, timeout=2)
    if app is None:
        return False
    return any(w.class_name() == "FNWND3" and "Faturamento" in w.window_text() for w in _janelas(app))


def iniciar_portal():
    """Inicia o portal.exe (tela de login). Nao faz nada se ele ja estiver rodando."""
    app = _conectar(config.PORTAL_EXE, timeout=1)
    if app is not None:
        return app
    subprocess.Popen([config.PORTAL_EXE], cwd=config.PORTAL_EXE.rsplit("\\", 1)[0])
    fim = time.time() + 30
    while time.time() < fim:
        time.sleep(1.0)
        app = _conectar(config.PORTAL_EXE, timeout=1)
        if app is not None:
            return app
    raise RuntimeError("O portal.exe nao iniciou em 30 s.")


def aguardar_login(app, log=print, espera=300):
    """Espera uma PESSOA fazer o login no portal. Devolve a janela do portal logado."""
    inicio = time.time()
    avisou = False
    while time.time() - inicio < espera:
        w = janela_portal(app)
        if w is not None:
            return w
        if not avisou:
            log("Aguardando o login no Salux (digite usuario e senha na tela de login)...")
            avisou = True
        time.sleep(1.5)
    raise RuntimeError(f"Login nao concluido em {espera} s.")


ARQ_ENV = pasta_app() / ".env"
# posicoes (x, y) relativas a janela de login (FNWNS3): campos Usuario, Senha e botao Entrar
LOGIN_POS_USUARIO = (687, 208)
LOGIN_POS_SENHA = (687, 298)
LOGIN_POS_ENTRAR = (687, 481)


def _ler_env():
    """Le USERNAME e SENHA do .env (direto do arquivo: USERNAME existe no Windows e confundiria
    os.environ). Nunca registra nem imprime os valores."""
    vals = {}
    if ARQ_ENV.exists():
        for linha in ARQ_ENV.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if linha and not linha.startswith("#") and "=" in linha:
                k, v = linha.split("=", 1)
                vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals.get("USERNAME", ""), vals.get("SENHA", "")


def _escapar(txt):
    return "".join("{" + c + "}" if c in "{}+^%~()[]" else c for c in txt)


def janela_login(app):
    for w in _janelas(app):
        if w.class_name() == "FNWNS3" and w.is_visible():
            return w
    return None


def fazer_login(app, log=print, espera=60):
    """Preenche usuario/senha do .env na tela de login e clica em Entrar. Aguarda o portal."""
    usuario, senha = _ler_env()
    if not senha:
        raise RuntimeError("SENHA nao encontrada no .env.")
    from pywinauto import keyboard
    fim = time.time() + 20
    login = janela_login(app)
    while login is None and time.time() < fim:
        time.sleep(0.5)
        login = janela_login(app)
    if login is None:
        raise RuntimeError("Tela de login nao encontrada.")
    login.set_focus()
    time.sleep(0.5)
    r = login.rectangle()

    def campo(pos, texto):
        mouse.click(coords=(r.left + pos[0], r.top + pos[1]))
        time.sleep(0.3)
        keyboard.send_keys("^a{BACKSPACE}", pause=0.03)
        keyboard.send_keys(_escapar(texto), pause=0.03, with_spaces=True)

    if usuario:
        campo(LOGIN_POS_USUARIO, usuario)
    campo(LOGIN_POS_SENHA, senha)
    time.sleep(0.3)
    mouse.click(coords=(r.left + LOGIN_POS_ENTRAR[0], r.top + LOGIN_POS_ENTRAR[1]))
    log("Login enviado, aguardando o portal...")
    fim = time.time() + espera
    while time.time() < fim:
        w = janela_portal(app)
        if w is not None:
            return w
        time.sleep(1.0)
    raise RuntimeError("Login nao concluido (confira usuario/senha no .env; tela de login ainda aberta?).")


def _pbdw_visiveis(w):
    return [c for c in w.descendants(class_name="pbdw") if c.is_visible() and c.rectangle().width() > 100]


def abrir_faturamento(portal, espera=60, log=print):
    """No portal logado: grupo 'Faturamento' (menu esquerdo) > azulejo 'Faturamento'."""
    if faturamento_aberto():
        return
    if portal.is_minimized():
        portal.restore()
        time.sleep(1.0)
    portal.maximize()  # as posicoes mapeadas valem com o portal maximizado
    time.sleep(1.2)
    portal.set_focus()
    time.sleep(0.8)
    grades = sorted(_pbdw_visiveis(portal), key=lambda c: c.rectangle().left)
    # menu a esquerda: DataWindow que comeca na borda esquerda (left < 100) e e alto;
    # azulejos: DataWindow mais a direita (left > 150) e largo
    menu = [c for c in grades if c.rectangle().left < 100 and c.rectangle().height() > 600]
    tiles = [c for c in grades if c.rectangle().left > 150 and c.rectangle().width() > 1000
             and c.rectangle().height() > 600]
    if not menu or not tiles:
        raise RuntimeError("Menu ou area de modulos do portal nao encontrados.")
    m, t = menu[0].rectangle(), tiles[0].rectangle()
    mouse.click(coords=(m.left + config.PORTAL_MENU_FATURAMENTO[0], m.top + config.PORTAL_MENU_FATURAMENTO[1]))
    time.sleep(1.2)
    mouse.click(coords=(t.left + config.PORTAL_TILE_FATURAMENTO[0], t.top + config.PORTAL_TILE_FATURAMENTO[1]))
    log("Abrindo o modulo Faturamento...")
    fim = time.time() + espera
    while time.time() < fim:
        time.sleep(1.0)
        if faturamento_aberto():
            time.sleep(3.0)  # deixa a tela principal terminar de carregar
            return
    raise RuntimeError("O modulo Faturamento nao abriu em %d s." % espera)


def garantir_faturamento(log=print, login_manual=False):
    """Deixa o Faturamento aberto: usa o que ja existe ou sobe portal > login > modulo."""
    if faturamento_aberto():
        return
    app = iniciar_portal()
    portal = janela_portal(app)
    if portal is None:
        senha = "" if login_manual else _ler_env()[1]
        portal = fazer_login(app, log) if senha else aguardar_login(app, log)
    abrir_faturamento(portal, log=log)
