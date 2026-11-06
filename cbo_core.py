"""Nucleo da automacao do CBO no Salux (Faturamento). NAO salva nada no Salux.

O Salux e PowerBuilder: a grade (DataWindow) so expoe um 'Edit' para a celula ativa.
Fluxo por linha:
  1. aba Itens: setas cima/baixo ate a linha (rotulo "Item N de M" mostra a atual)
  2. aba Origem: a mesma linha fica ativa; acha o editor do CBOS pela largura
  3. se o CBOS esta vazio, clica na seta do dropdown e na 1a opcao da lista
O Salux valida o CBO ao sair da celula; os avisos sao lidos, classificados e fechados.

Erros por linha sao registrados e a execucao segue. Erros criticos (Salux caiu/travou,
aviso de banco/rede/DataWindow, excecao inesperada) levantam ErroCritico e param tudo.
"""
import ctypes
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from pywinauto import Application, mouse

import config

from caminhos import pasta_app

PASTA = pasta_app()


class ErroCritico(Exception):
    """Erro que obriga a parar a automacao."""


class Interrompido(Exception):
    """Parada pedida pelo operador."""


@dataclass
class Resultado:
    estado: str = "CONCLUIDO"  # CONCLUIDO | CONCLUIDO_COM_ERROS | INTERROMPIDO | CRITICO
    mensagem: str = ""
    total: int = 0
    tratados: int = 0
    preenchidos: int = 0
    ja_preenchidos: int = 0
    erros: list = field(default_factory=list)  # (linha, mensagem)
    tempo: str = "00:00:00"
    linhas_log: list = field(default_factory=list)  # formato legado "Item N: STATUS - detalhe"
    arquivos: list = field(default_factory=list)


# ---------------------------------------------------------------- classificacao


def classificar_aviso(texto):
    """'cbo_invalido' | 'critico' | 'outro' a partir do texto do aviso do Salux."""
    t = texto.lower()
    if "cbo" in t and "inv" in t:
        return "cbo_invalido"
    for palavra in config.PALAVRAS_CRITICAS:
        if re.search(r"\b" + re.escape(palavra), t):
            return "critico"
    return "outro"


def faixas(numeros):
    """[1,2,3,7] -> '1-3, 7'."""
    if not numeros:
        return "-"
    numeros = sorted(numeros)
    out, ini, prev = [], numeros[0], numeros[0]
    for n in numeros[1:]:
        if n == prev + 1:
            prev = n
        else:
            out.append((ini, prev))
            ini = prev = n
    out.append((ini, prev))
    return ", ".join(f"{a}" if a == b else f"{a}-{b}" for a, b in out)


# ---------------------------------------------------------------- acesso a tela


def visiveis(janela, classe):
    return [c for c in janela.descendants(class_name=classe) if c.is_visible()]


def grade(janela):
    return [g for g in visiveis(janela, "pbdw")
            if g.rectangle().top > 400 and g.rectangle().width() > 700][0]


def editor_ativo(janela):
    eds = [e for e in visiveis(janela, "Edit")
           if e.rectangle().width() > 8 and e.parent().class_name() == "pbdw"]
    return eds[0] if eds else None


def posicao(janela):
    """(linha atual, total) a partir do rotulo 'Item N de M'."""
    for b in visiveis(janela, "Button"):
        m = re.match(r"Item (\d+) de (\d+)", b.window_text())
        if m:
            return int(m.group(1)), int(m.group(2))
    return 0, 0


def _janelas(app):
    """app.windows() tolerante: janelas temporarias (dicas) podem sumir durante a listagem."""
    for _ in range(4):
        try:
            return app.windows()
        except Exception:
            time.sleep(0.2)
    return []


def ler_avisos(app):
    """Le e fecha os avisos do Salux (#32770). Devolve [(texto, classe)].

    Aviso critico NAO e fechado: a automacao para e o operador decide.
    """
    achados = []
    for _ in range(5):
        dlgs = [w for w in _janelas(app) if w.class_name().startswith("#32770")]
        if not dlgs:
            break
        d = dlgs[0]
        msg = " ".join(c.window_text().replace("\n", " ") for c in d.children()
                       if c.class_name() == "Static" and c.window_text().strip())
        classe = classificar_aviso(msg)
        achados.append((msg[:200], classe))
        if classe == "critico":
            break
        for c in d.children():
            if c.window_text() == "OK":
                c.click()
        time.sleep(0.8)
    return achados


def verificar_salux(app, janela):
    """Levanta ErroCritico se o Salux fechou, caiu ou parou de responder."""
    try:
        rodando = app.is_process_running()
        existe = bool(ctypes.windll.user32.IsWindow(janela.handle))
    except Exception:
        rodando = existe = False
    if not rodando or not existe:
        raise ErroCritico("O Salux foi fechado ou caiu durante a automacao.")
    for _ in range(3):
        if not ctypes.windll.user32.IsHungAppWindow(janela.handle):
            return
        time.sleep(3)
    raise ErroCritico("O Salux parou de responder (travado ou sem conexao).")


def ir_para_linha(janela, alvo):
    g = grade(janela)
    # uma tecla por vez: varias seguidas (ex.: {UP}{UP}) nao chegam todas na grade
    for _ in range(2 * posicao(janela)[1] + 2):
        atual = posicao(janela)[0]
        if atual == alvo:
            return True
        g.type_keys("{UP}" if atual > alvo else "{DOWN}")  # com foco: o editor da Origem ainda guarda o teclado
        time.sleep(0.5)
    return posicao(janela)[0] == alvo


def eh_cbos(ed):
    return ed is not None and abs(ed.rectangle().width() - config.CBOS_LARGURA) <= 3


def ir_para_cbos(janela, linha):
    """Acha o editor do CBOS (pela largura, pois a grade pode estar rolada).

    Fase 1: Shift+Tab a partir da celula atual. Se isso cair na linha anterior,
    Fase 2: Tab para frente (o CBOS vem antes do fim da linha, entao nunca
    passamos da ultima celula da ultima linha, o que criaria um item novo).
    """
    total = posicao(janela)[1]
    for _ in range(12):
        ed = editor_ativo(janela)
        if eh_cbos(ed):
            return ed
        (ed or grade(janela)).type_keys("+{TAB}")
        time.sleep(0.4)
        if posicao(janela)[0] != linha:
            break
    for _ in range(14):
        atual, tot = posicao(janela)
        if tot != total or atual > linha:
            return None
        ed = editor_ativo(janela)
        if atual == linha and eh_cbos(ed):
            return ed
        (ed or grade(janela)).type_keys("{TAB}")
        time.sleep(0.4)
    return None


def _popups(app, topo):
    return [w for w in _janelas(app)
            if w.class_name() == "pbdw" and w.is_visible()
            and w.rectangle().height() < 400 and w.rectangle().top > topo]


def escolher_primeira(app, janela, ed):
    """Clica na seta do dropdown do CBOS e na 1a opcao da lista (mouse real: a
    tecla seta-para-baixo so funciona as vezes). Devolve o texto escolhido."""
    r = ed.rectangle()
    y = (r.top + r.bottom) // 2
    janela.set_focus()
    time.sleep(0.4)
    mouse.move(coords=(r.right + 11, y))
    time.sleep(0.2)
    mouse.click(coords=(r.right + 11, y))
    time.sleep(1.0)
    pops = _popups(app, r.top)
    if not pops:
        return ""
    p = pops[0].rectangle()
    mouse.move(coords=(p.left + 120, p.top + 11))
    time.sleep(0.2)
    mouse.click(coords=(p.left + 120, p.top + 11))
    time.sleep(1.0)
    if _popups(app, r.top):  # lista continua aberta (sem opcoes): fecha sem escolher
        janela.type_keys("{ESC}")
        time.sleep(0.4)
    e = editor_ativo(janela)
    return e.window_text().strip() if e else ""


# ---------------------------------------------------------------- abrir/fechar conta


class ContaInvalida(Exception):
    """Conta nao encontrada, bloqueada, em uso ou diferente da pedida (nao e erro critico)."""


TITULO_CONTA = "Manutenção da Conta Paciente"


def janela_conta(janela):
    """Janela filha 'Manutencao da Conta Paciente' visivel, ou None."""
    for w in janela.descendants(class_name="FNWND3"):
        if w.is_visible() and w.window_text() == TITULO_CONTA:
            return w
    return None


def _campo_numero(conta):
    """PBEDIT 'Numero da Conta' (mapeado: topo da janela da conta, ~90 px de largura)."""
    topo = conta.rectangle().top
    cands = [e for e in conta.descendants(class_name="PBEDIT")
             if e.is_visible() and 25 < e.rectangle().top - topo < 60
             and 70 <= e.rectangle().width() <= 110]
    return min(cands, key=lambda e: e.rectangle().left) if cands else None


def _conta_carregada(janela):
    """Com a conta carregada o botao CpCusto fica habilitado (em consulta fica cinza)."""
    for b in janela.descendants(class_name="Button"):
        if b.is_visible() and b.window_text() == "CpCusto":
            return b.is_enabled()
    return False


def abrir_conta(app, janela, numero, espera=20):
    """Abre a conta pelo modo consulta do Salux. Nao altera nada na conta.

    Fluxo mapeado: Movimento > 'Manutencao da Conta Paciente (direto)' (a janela abre
    JA em modo consulta, com o foco no Numero da Conta) -> digita o numero -> Tab:
    Cta, digitar 'F' (FIA) -> Tab, Tab: Sit. Cta, digitar 'Aberta' -> CLIQUE REAL no
    botao 'Executar consulta' da barra (clique por mensagem nao executa).
    Nunca executa a consulta sem o numero conferido (consulta em branco abre a 1a conta).
    """
    numero = str(numero).strip()
    if not numero.isdigit():
        raise ContaInvalida(f"Numero de conta invalido: {numero!r}")
    if janela_conta(janela) is not None:
        raise ErroCritico("Ja existe uma conta aberta no Salux; feche-a antes de abrir outra.")
    janela.set_focus()
    time.sleep(0.4)
    janela.menu_select("Movimento->Manutenção da Conta Paciente (direto)")
    conta, fim = None, time.time() + espera
    while time.time() < fim and conta is None:
        time.sleep(0.5)
        conta = janela_conta(janela)
    if conta is None:
        raise ErroCritico("A tela 'Manutencao da Conta Paciente' nao abriu pelo menu.")
    campo, fim = None, time.time() + espera
    while time.time() < fim and campo is None:
        time.sleep(0.5)
        campo = _campo_numero(conta)
    if campo is None:
        raise ErroCritico("Campo 'Numero da Conta' nao encontrado na tela da conta.")
    time.sleep(0.8)
    janela.set_focus()
    campo.type_keys(numero, with_spaces=False)
    time.sleep(0.4)
    digitado = re.sub(r"\D", "", campo.window_text())
    if digitado != numero:  # nunca executar a consulta com o numero errado ou em branco
        raise ErroCritico(f"Numero digitado no Salux ({digitado or 'vazio'}) difere do pedido ({numero}).")
    janela.type_keys("{TAB}F{TAB}{TAB}Aberta", with_spaces=False)  # Cta=FIA, Sit. Cta=Aberta
    time.sleep(0.6)
    barra = [c for c in visiveis(janela, "FNFIXEDBAR")][0]
    janela.set_focus()
    time.sleep(0.4)
    barra.click_input(coords=config.POS_BOTAO_CONSULTA)  # executar consulta (clique real)
    fim = time.time() + espera
    while time.time() < fim:
        time.sleep(0.6)
        for texto, classe in ler_avisos(app):
            if classe == "critico":
                raise ErroCritico(f"Aviso critico do Salux ao abrir a conta: {texto}")
            raise ContaInvalida(f"Salux avisou ao abrir a conta {numero}: {texto}")
        verificar_salux(app, janela)
        if _conta_carregada(janela):
            return conta
    raise ContaInvalida(f"A conta {numero} nao carregou em {espera}s (inexistente, bloqueada ou nao esta Aberta/FIA).")


def _menu_contexto(app):
    return [w for w in _janelas(app) if w.class_name() == "#32768" and w.is_visible()]


def _tela_filtro(app):
    for w in _janelas(app):
        if w.class_name() == "FNWNS3" and w.window_text() == "Tela de Filtro" and w.is_visible():
            return w
    return None


def filtrar_procedimentos(app, janela, espera=12):
    """Aba Itens > botao direito na grade > Filtrar > Tipo de Item = Procedimento > OK.

    Mapeado: o menu de contexto tem 'Ordenar' e 'Filtrar'; a 'Tela de Filtro' tem o
    checkbox 'Tipo de Item' (habilita o dropdown), dropdown com Diaria / Kit Faturamento /
    Procedimento / Produto e o botao OK. So envia a tecla de atalho do menu ('f') quando
    o menu de contexto esta realmente aberto (senao digitaria numa celula de item).
    Devolve (itens_antes, itens_depois).
    """
    antes = posicao(janela)[1]
    g = grade(janela)
    r = g.rectangle()
    x, y = r.left + 300, r.top + 60  # area das linhas de itens
    menu = []
    for _ in range(3):
        janela.set_focus()
        time.sleep(0.4)
        mouse.move(coords=(x, y))
        time.sleep(0.2)
        mouse.right_click(coords=(x, y))
        time.sleep(1.0)
        menu = _menu_contexto(app)
        if menu:
            break
    if not menu:
        raise ErroCritico("O menu de contexto (Ordenar/Filtrar) nao abriu na grade de itens.")
    janela.type_keys("f")  # atalho de '&Filtrar'
    dlg, fim = None, time.time() + espera
    while time.time() < fim and dlg is None:
        time.sleep(0.5)
        dlg = _tela_filtro(app)
    if dlg is None:
        raise ErroCritico("A 'Tela de Filtro' nao abriu.")
    chk = [c for c in dlg.children(class_name="Button") if c.window_text() == "Tipo de Item"][0]
    combo = dlg.children(class_name="ComboBox")[0]
    if chk.get_check_state() == 0:
        chk.click()
        time.sleep(0.6)
    if not combo.is_enabled():
        raise ErroCritico("O filtro 'Tipo de Item' nao foi marcado.")
    combo.select("Procedimento")
    time.sleep(0.5)
    if combo.selected_text() != "Procedimento":
        raise ErroCritico(f"Filtro de tipo ficou em {combo.selected_text()!r}, esperado 'Procedimento'.")
    [c for c in dlg.children(class_name="Button") if c.window_text() == "&OK"][0].click()
    fim = time.time() + espera
    while time.time() < fim and _tela_filtro(app) is not None:
        time.sleep(0.5)
    if _tela_filtro(app) is not None:
        raise ErroCritico("A 'Tela de Filtro' nao fechou apos o OK.")
    time.sleep(1.5)
    for texto, classe in ler_avisos(app):
        if classe == "critico":
            raise ErroCritico(f"Aviso critico do Salux ao filtrar: {texto}")
        raise ContaInvalida(f"Salux avisou ao filtrar os itens: {texto}")
    return antes, posicao(janela)[1]


def fechar_conta(app, janela, espera=15, estavel=3.0, tentativas=3):
    """Fecha a janela da conta (WM_CLOSE; nunca o botao 'Fechar Conta', que fecha a conta de faturamento).

    So considera fechada quando a janela fica ausente por `estavel` segundos (apos salvar ela pode
    reaparecer durante a atualizacao); tenta de novo se voltar. Se o Salux perguntar algo
    (ex.: salvar alteracoes), NAO responde: levanta ErroCritico.
    """
    for _ in range(tentativas):
        conta = janela_conta(janela)
        if conta is not None:
            conta.close()
        fim = time.time() + espera
        sumiu_desde = None
        while time.time() < fim:
            time.sleep(0.5)
            avisos = ler_avisos(app)
            if avisos:
                raise ErroCritico(f"O Salux perguntou algo ao fechar a conta: {avisos[0][0]}")
            if janela_conta(janela) is None:
                sumiu_desde = sumiu_desde or time.time()
                if time.time() - sumiu_desde >= estavel:
                    return
            elif sumiu_desde is not None:
                break  # reapareceu: fecha de novo
    raise ErroCritico("A tela da conta nao fechou (ou reabriu) apos varias tentativas.")


# ---------------------------------------------------------------- salvar e fechar a conta


def decidir_dialogo(texto, botoes):
    """O que fazer com um aviso do Salux durante o SALVAMENTO.

    Devolve ('sim', motivo) so para a pergunta mapeada 'Existem valores zerados. Deseja salvar
    mesmo assim?'; ('ok', texto) para avisos informativos so com OK; ('erro', motivo) para
    qualquer outra coisa (a automacao NAO responde perguntas desconhecidas).
    """
    t = (texto or "").lower()
    nomes = [b.replace("&", "").strip().lower() for b in botoes]
    if "valores zerados" in t and "salvar" in t and "sim" in nomes:
        return "sim", "valores zerados: salvar mesmo assim"
    if classificar_aviso(texto) == "critico":
        return "erro", f"aviso critico do Salux ao salvar: {texto}"
    if nomes and all(n == "ok" for n in nomes) and classificar_aviso(texto) != "cbo_invalido":
        return "ok", texto
    return "erro", f"o Salux perguntou/avisou algo inesperado ao salvar: {texto}"


def _dialogo(app):
    for w in _janelas(app):
        try:
            if w.class_name().startswith("#32770") and w.is_visible():
                return w
        except Exception:
            continue
    return None


def salvar_conta(app, janela, log=None, espera=40):
    """Clica em Salvar (barra de ferramentas) e responde SIM a 'Existem valores zerados...'.

    Qualquer outro aviso/pergunta e ErroCritico (nao e respondido e fica na tela). Termina
    quando nao aparece mais nenhum aviso por alguns segundos; a confirmacao final de que
    salvou e o fechamento da conta sem o Salux perguntar nada (ver fechar_conta).
    """
    log = log or (lambda nivel, msg: None)
    if janela_conta(janela) is None:
        raise ErroCritico("A tela da conta nao esta aberta para salvar.")
    verificar_salux(app, janela)
    janela.set_focus()
    time.sleep(0.4)
    barra = list(visiveis(janela, "FNFIXEDBAR"))
    if not barra:
        raise ErroCritico("Barra de ferramentas do Salux nao encontrada (botao Salvar).")
    barra[0].click_input(coords=config.POS_BOTAO_SALVAR)  # clique real no check (Salvar)
    respondeu = False
    fim = time.time() + espera
    quieto_desde = time.time()
    while time.time() < fim:
        time.sleep(0.6)
        verificar_salux(app, janela)
        d = _dialogo(app)
        if d is None:
            if time.time() - quieto_desde >= (3.0 if respondeu else 2.5):
                return
            continue
        quieto_desde = time.time()
        texto = " ".join(c.window_text().replace("\n", " ") for c in d.children()
                         if c.class_name() == "Static" and c.window_text().strip())
        botoes = [c for c in d.children() if c.class_name() == "Button" and c.window_text().strip()]
        acao, motivo = decidir_dialogo(texto, [b.window_text() for b in botoes])
        if acao == "erro":
            raise ErroCritico(motivo)
        alvo = "sim" if acao == "sim" else "ok"
        for b in botoes:
            if b.window_text().replace("&", "").strip().lower() == alvo:
                log("info" if acao == "ok" else "aviso", f"Aviso do Salux ao salvar: {texto} -> {alvo.upper()}")
                b.click()
                respondeu = respondeu or acao == "sim"
                break
        else:
            raise ErroCritico(f"Botao '{alvo}' nao encontrado no aviso do Salux: {texto}")
        time.sleep(1.0)
    raise ErroCritico(f"O Salux nao terminou de salvar em {espera}s (aviso pendente ou travado).")


def _conectar_salux():
    try:
        app = Application(backend=config.BACKEND).connect(path=config.EXE, timeout=5)
        janela = app.window(title_re=config.TITULO_APP).wrapper_object()
    except Exception:
        raise ErroCritico("Salux (faturam.exe) nao encontrado para salvar a conta.")
    return app, janela


def salvar_e_fechar(log):
    """Salva a conta aberta e fecha a tela de Manutencao da Conta (deixa o Faturamento livre)."""
    app, janela = _conectar_salux()
    log("info", "Salvando a conta (botao Salvar)...")
    salvar_conta(app, janela, log)
    log("ok", "Conta salva.")
    time.sleep(2.0)  # deixa o Salux terminar de atualizar a tela antes de fechar
    fechar_conta(app, janela)
    log("ok", "Tela da conta fechada.")


# ---------------------------------------------------------------- logs em arquivo


def gravar_resumos(res):
    """Grava log_cbo.txt (formato por item) e log_cbo_resumo_<data>.txt (por faixas)."""
    agora = datetime.now()
    leg = PASTA / "log_cbo.txt"
    with open(leg, "w", encoding="utf-8") as f:
        f.write(f"Execucao {agora:%d/%m/%Y %H:%M:%S} - {res.tratados} de {res.total} itens"
                f" - {res.estado}\n")
        f.write("\n".join(res.linhas_log) + "\n")
        f.write(f"Resumo: {resumo_contagem(res)}\nTempo decorrido: {res.tempo}\n")

    def itens(padrao):
        return [int(m.group(1)) for x in res.linhas_log
                if (m := re.match(r"Item\s+(\d+): " + padrao, x))]

    resumo = PASTA / f"log_cbo_resumo_{agora:%Y%m%d_%H%M%S}.txt"
    with open(resumo, "w", encoding="utf-8") as f:
        f.write(f"CBO - execucao de {agora:%d/%m/%Y %H:%M:%S}\n")
        f.write("Nada foi salvo no Salux; o salvamento e manual.\n")
        f.write("Itens identificados pelo numero da linha (a automacao nao le a descricao).\n\n")
        f.write(f"Situacao: {res.estado}" + (f" - {res.mensagem}" if res.mensagem else "") + "\n")
        f.write(f"Itens tratados: {res.tratados} de {res.total}\n")
        f.write(f"Tempo decorrido: {res.tempo}\n\n")
        pre = itens("PREENCHIDO")
        f.write(f"CBO INCLUIDO - {len(pre)} itens:\n{faixas(pre)}\n\n")
        ja = itens(r"PULADO \(CBO ja")
        f.write(f"JA TINHAM CBO, NAO ALTERADOS - {len(ja)} itens:\n{faixas(ja)}\n\n")
        sem = itens(r"PULADO \(sem")
        f.write(f"CAMPO CBO SEM ESPECIALIDADE/OPCAO (sem Prof ou sem CBO vinculado) - {len(sem)} itens:\n{faixas(sem)}\n\n")
        inv = itens("CBO INVALIDO")
        f.write(f"CBO INVALIDO (Salux recusou) - {len(inv)} itens:\n{faixas(inv)}\n\n")
        npr = itens("NAO PROCESSADO")
        f.write(f"NAO PROCESSADOS - {len(npr)} itens:\n{faixas(npr)}\n")
        if res.erros:
            f.write("\nERROS POR LINHA:\n")
            for linha, msg in res.erros:
                f.write(f"  linha {linha}: {msg}\n")
    res.arquivos = [str(leg), str(resumo)]


def resumo_contagem(res):
    return {k: sum(1 for x in res.linhas_log if f": {k}" in x)
            for k in ("PREENCHIDO", "PULADO", "CBO INVALIDO", "NAO PROCESSADO")}


# ---------------------------------------------------------------- execucao


def executar(log, parar=None, limite=None, conta=None, msg_final="nada foi salvo; salve manualmente."):
    """Percorre os itens da conta aberta e preenche o CBOS.

    log(nivel, msg): nivel em info | ok | aviso | erro | critico.
    parar: threading.Event; se acionado, termina apos a linha atual.
    limite: maximo de itens (None = todos).
    conta: numero da conta a abrir pela consulta do Salux (None = usa a conta ja aberta).
    Nao salva nem fecha a conta (quem decide e salvar_e_fechar). msg_final: texto ao fim do resumo.
    """
    parar = parar or threading.Event()
    res = Resultado()
    inicio = time.time()
    n = 0

    def erro_linha(linha, msg):
        txt = f"ERRO linha {linha}: {msg}"
        res.erros.append((linha, msg))
        log("erro", txt)

    def tratar_avisos(app, anterior, linha_atual):
        """Fecha avisos pendentes; atribui CBO invalido a linha anterior."""
        for texto, classe in ler_avisos(app):
            if classe == "critico":
                raise ErroCritico(f"Aviso critico do Salux: {texto}")
            if classe == "cbo_invalido" and anterior:
                l, i = anterior
                res.linhas_log[i] = f"Item {l:>3}: CBO INVALIDO (Salux limpou o campo) - {texto}"
                erro_linha(l, "CBO invalido para a especialidade do profissional "
                              f"(o Salux limpou o campo). {texto}")
                anterior = None
            else:
                log("aviso", f"AVISO do Salux (perto da linha {linha_atual}): {texto}")
        return anterior

    def registra(linha, status, detalhe="", nivel="info"):
        txt = f"Item {linha:>3}: {status}" + (f" - {detalhe}" if detalhe else "")
        res.linhas_log.append(txt)
        log(nivel, txt)

    app = janela = None
    try:
        try:
            app = Application(backend=config.BACKEND).connect(path=config.EXE, timeout=5)
            janela = app.window(title_re=config.TITULO_APP).wrapper_object()
        except Exception:
            raise ErroCritico("Salux (faturam.exe) nao encontrado. Abra o Faturamento.")
        janela.set_focus()
        time.sleep(0.4)
        tratar_avisos(app, None, 0)
        if conta:
            log("info", f"Abrindo a conta {conta} pela consulta do Salux (Cta=FIA, Sit. Cta=Aberta)...")
            abrir_conta(app, janela, conta)
            log("ok", f"Conta {conta} aberta.")
        abas = visiveis(janela, config.CLASSE_ABAS)
        if not abas:
            raise ErroCritico("A tela 'Manutencao da Conta Paciente' nao esta aberta.")
        abas = abas[0]
        abas.click(coords=config.POS_ABA_ITENS)
        time.sleep(1.0)
        if posicao(janela)[1] == 0:
            raise ErroCritico("Nenhum item encontrado na conta aberta (confira se esta na aba Itens).")
        log("info", "Filtrando os itens: Tipo de Item = Procedimento...")
        antes_f, total = filtrar_procedimentos(app, janela)
        log("ok", f"Filtro aplicado: {antes_f} itens na conta, {total} procedimentos.")
        if total == 0:
            raise ContaInvalida("A conta nao tem itens do tipo Procedimento.")
        res.total = total
        n = min(total, limite) if limite else total
        log("info", f"Conta com {total} itens; tratando {n}.")

        anterior = None  # (linha, indice no log) cujo aviso de validacao ainda pode chegar
        for linha in range(1, n + 1):
            if parar.is_set():
                raise Interrompido()
            try:
                verificar_salux(app, janela)
                abas.click(coords=config.POS_ABA_ITENS)  # sair da celula dispara a validacao do Salux
                time.sleep(0.8)
                anterior = tratar_avisos(app, anterior, linha)
                if posicao(janela)[1] != total:
                    raise ErroCritico("A quantidade de itens da conta mudou durante a automacao "
                                      "(possivel item novo criado).")
                res.tratados = linha - 1
                if not ir_para_linha(janela, linha):
                    registra(linha, "NAO PROCESSADO", "nao consegui selecionar a linha", "erro")
                    res.erros.append((linha, "nao consegui selecionar a linha"))
                    continue
                abas.click(coords=config.POS_ABA_ORIGEM)
                time.sleep(1.0)
                if posicao(janela)[0] != linha:
                    registra(linha, "NAO PROCESSADO", "linha ativa mudou ao abrir a Origem", "erro")
                    res.erros.append((linha, "linha ativa mudou ao abrir a Origem"))
                    continue
                ed = ir_para_cbos(janela, linha)
                if ed is None or posicao(janela)[0] != linha:
                    registra(linha, "NAO PROCESSADO", "celula CBOS nao encontrada", "erro")
                    res.erros.append((linha, "celula CBOS nao encontrada"))
                    continue
                atual = ed.window_text().strip()
                if atual:
                    registra(linha, "PULADO (CBO ja preenchido)", atual)
                    res.ja_preenchidos += 1
                    continue
                novo = escolher_primeira(app, janela, ed)
                if not novo:
                    registra(linha, "PULADO (sem Prof / sem opcoes de CBO)")
                    erro_linha(linha, "Campo CBO sem especialidade para preencher "
                                      "(sem Prof ou profissional sem CBO vinculado)")
                    continue
                registra(linha, "PREENCHIDO", novo, "ok")
                res.preenchidos += 1
                anterior = (linha, len(res.linhas_log) - 1)
            except (ErroCritico, Interrompido):
                raise
            except Exception as e:  # excecao inesperada: Salux caiu? senao, critico mesmo assim
                verificar_salux(app, janela)
                raise ErroCritico(f"Erro inesperado na linha {linha}: {type(e).__name__}: {e}")
        res.tratados = n
        # a ultima linha so e validada ao sair da celula
        abas.click(coords=config.POS_ABA_ITENS)
        time.sleep(0.8)
        tratar_avisos(app, anterior, n)
        abas.click(coords=config.POS_ABA_ORIGEM)
        res.estado = "CONCLUIDO_COM_ERROS" if res.erros else "CONCLUIDO"
    except ContaInvalida as e:
        res.estado = "CONTA_INVALIDA"
        res.mensagem = str(e)
        log("erro", f"ERRO: conta nao aberta - {e}")
    except Interrompido:
        res.estado = "INTERROMPIDO"
        res.mensagem = "Interrompido pelo operador."
        log("aviso", res.mensagem)
    except ErroCritico as e:
        res.estado = "CRITICO"
        res.mensagem = str(e)
        log("critico", f"ERRO CRITICO - automacao interrompida: {e}")
    except Exception as e:
        res.estado = "CRITICO"
        res.mensagem = f"{type(e).__name__}: {e}"
        log("critico", f"ERRO CRITICO - automacao interrompida: {res.mensagem}")
    finally:
        seg = int(time.time() - inicio)
        res.tempo = f"{seg // 3600:02d}:{seg % 3600 // 60:02d}:{seg % 60:02d}"
        try:
            gravar_resumos(res)
        except Exception as e:  # nunca esconder o resultado por falha de log
            log("erro", f"Falha ao gravar os logs em texto: {e}")
    log("info", f"Resumo: {resumo_contagem(res)}" + (f" - {msg_final}" if msg_final else ""))
    log("info", f"Tempo decorrido: {res.tempo}")
    return res
