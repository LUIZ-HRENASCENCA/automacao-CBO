"""Mapeador das telas do Salux (fase de descoberta do fluxo de busca/abertura de conta).

Somente LEITURA: nao clica, nao digita, nao altera nada no Salux.

Modos:
  python mapear_tela.py observar [exe]  fica rodando e grava um instantaneo em mapa/ a cada
                                   mudanca de tela (janelas novas/fechadas, controles que
                                   aparecem/somem). Pare com Ctrl+C ou criando mapa/PARAR.
  python mapear_tela.py snap NOME [exe]  grava um instantaneo manual agora (mapa/NNN_NOME.*)
  [exe] = programa a observar (padrao faturam.exe; use portal.exe para o login/portal).

O texto de campos de digitacao (Edit/PBEDIT) e MASCARADO ("<N car>") para nao gravar
usuario, senha nem outros dados digitados. Use --mostrar-campos para desligar (nao use
na tela de login).

Cada instantaneo gera mapa/NNN_<hora>_<motivo>.txt (janelas, mudancas desde o anterior,
menus, controles visiveis com classe/texto/posicao) e .png (captura da janela).
mapa/ pode conter dados de paciente: esta no .gitignore.
"""
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from pywinauto import Application

import config

MAPA = Path(__file__).resolve().parent / "mapa"
PARAR = MAPA / "PARAR"
MAX_CONTROLES = 600
EXE = config.EXE
MASCARAR = True


def conectar():
    app = Application(backend="win32").connect(path=EXE, timeout=5)
    return app


def texto_seguro(c):
    t = re.sub(r"\s+", " ", c.window_text())[:80]
    if MASCARAR and t and c.class_name() in ("Edit", "PBEDIT", "ComboBox", "ComboLBox"):
        return f"<{len(t)} car>"
    return t


def estado(app):
    """Foto leve do que existe agora: janelas do processo e controles visiveis."""
    janelas = []
    for w in app.windows(visible_only=False):
        try:
            r = w.rectangle()
            janelas.append({
                "h": w.handle, "classe": w.class_name(), "titulo": w.window_text(),
                "visivel": w.is_visible(), "rect": (r.left, r.top, r.right, r.bottom),
                "w": w,
            })
        except Exception:
            continue
    controles = {}
    for j in janelas:
        if not j["visivel"]:
            continue
        try:
            for c in j["w"].descendants():
                if not c.is_visible():
                    continue
                r = c.rectangle()
                if r.width() < 2 or r.height() < 2:
                    continue
                chave = (j["h"], c.handle)
                controles[chave] = (
                    j["classe"], c.class_name(), texto_seguro(c),
                    (r.left, r.top, r.right, r.bottom),
                )
                if len(controles) > MAX_CONTROLES * 4:
                    break
        except Exception:
            continue
    return janelas, controles


def assinatura(janelas, controles):
    js = tuple(sorted((j["h"], j["classe"], j["titulo"], j["visivel"]) for j in janelas))
    cs = tuple(sorted((c[1], c[2]) for c in controles.values()))
    return hash((js, cs))


def menus(janelas):
    out = []
    for j in janelas:
        if not j["visivel"]:
            continue
        try:
            itens = j["w"].menu_items()
            if itens:
                out.append((j["titulo"], [i.get("text", "") for i in itens]))
        except Exception:
            pass
    return out


def gravar(seq, motivo, janelas, controles, anterior):
    MAPA.mkdir(exist_ok=True)
    base = MAPA / f"{seq:03d}_{datetime.now():%H%M%S}_{re.sub(r'[^A-Za-z0-9_-]', '_', motivo)[:30]}"
    linhas = [f"Instantaneo {seq} - {datetime.now():%d/%m/%Y %H:%M:%S} - {motivo}", ""]
    linhas.append("JANELAS DO PROCESSO (handle | classe | visivel | retangulo | titulo)")
    for j in janelas:
        linhas.append(f"  {j['h']:>8} | {j['classe']:<22} | {'S' if j['visivel'] else 'n'} | "
                      f"{j['rect']} | {j['titulo']!r}")
    if anterior is not None:
        ja, cant = anterior
        antes = {(j["h"], j["classe"], j["titulo"]) for j in ja}
        agora = {(j["h"], j["classe"], j["titulo"]) for j in janelas}
        linhas += ["", "JANELAS NOVAS: " + (", ".join(f"{c} {t!r}" for _, c, t in sorted(agora - antes)) or "-"),
                   "JANELAS QUE SUMIRAM: " + (", ".join(f"{c} {t!r}" for _, c, t in sorted(antes - agora)) or "-")]
        novos = {v for k, v in controles.items() if k not in cant}
        sumiu = {v for k, v in cant.items() if k not in controles}
        linhas += ["", f"CONTROLES NOVOS ({len(novos)}):"]
        linhas += [f"  {c[1]:<18} {c[2]!r:<45} {c[3]}   [em {c[0]}]" for c in sorted(novos, key=lambda x: (x[3][1], x[3][0]))[:150]]
        linhas += ["", f"CONTROLES QUE SUMIRAM ({len(sumiu)}):"]
        linhas += [f"  {c[1]:<18} {c[2]!r:<45} {c[3]}   [em {c[0]}]" for c in sorted(sumiu, key=lambda x: (x[3][1], x[3][0]))[:80]]
    ms = menus(janelas)
    linhas += ["", "MENUS (nativos):"]
    linhas += [f"  [{t!r}] " + " | ".join(i) for t, i in ms] or ["  -"]
    linhas += ["", f"CONTROLES VISIVEIS COM TEXTO (ate {MAX_CONTROLES}):"]
    com_texto = [v for v in controles.values() if v[2]]
    for c in sorted(com_texto, key=lambda x: (x[0], x[3][1], x[3][0]))[:MAX_CONTROLES]:
        linhas.append(f"  [{c[0]}] {c[1]:<20} {c[2]!r:<48} {c[3]}")
    base.with_suffix(".txt").write_text("\n".join(linhas), encoding="utf-8")
    try:  # captura da janela principal (e das janelas pequenas, como avisos)
        from PIL import ImageGrab
        vis = [j for j in janelas if j["visivel"] and (j["rect"][2] - j["rect"][0]) > 50]
        if vis:
            x0 = min(j["rect"][0] for j in vis)
            y0 = min(j["rect"][1] for j in vis)
            x1 = max(j["rect"][2] for j in vis)
            y1 = max(j["rect"][3] for j in vis)
            ImageGrab.grab(bbox=(max(0, x0), max(0, y0), x1, y1)).save(base.with_suffix(".png"))
    except Exception:
        pass
    return base.name


def observar():
    app = conectar()
    MAPA.mkdir(exist_ok=True)
    PARAR.unlink(missing_ok=True)
    seq = 0
    janelas, controles = estado(app)
    seq += 1
    print("gravado:", gravar(seq, "inicio", janelas, controles, None), flush=True)
    anterior = (janelas, controles)
    ultima = assinatura(janelas, controles)
    pendente, desde = None, 0.0
    while not PARAR.exists():
        time.sleep(0.4)
        try:
            j2, c2 = estado(app)
        except Exception as e:  # Salux fechado ou travado
            print("erro ao ler o Salux:", e, flush=True)
            time.sleep(2)
            continue
        a = assinatura(j2, c2)
        if a == ultima:
            pendente = None
            continue
        if a != pendente:  # espera a tela estabilizar (0,6 s sem mudar)
            pendente, desde = a, time.time()
            continue
        if time.time() - desde < 0.6:
            continue
        seq += 1
        nova = [j["classe"] for j in j2 if (j["h"],) not in {(x["h"],) for x in anterior[0]}]
        motivo = ("janela_" + nova[0].replace("#", "")) if nova else "mudanca"
        print("gravado:", gravar(seq, motivo, j2, c2, anterior), flush=True)
        anterior, ultima, pendente = (j2, c2), a, None
    PARAR.unlink(missing_ok=True)
    print("observador encerrado", flush=True)


def snap(nome):
    app = conectar()
    janelas, controles = estado(app)
    print("gravado:", gravar(0, nome, janelas, controles, None))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--mostrar-campos" in sys.argv:
        MASCARAR = False
    modo = args[0] if args else "observar"
    if modo == "snap":
        if len(args) > 2:
            EXE = args[2]
        snap(args[1] if len(args) > 1 else "manual")
    else:
        if len(args) > 1:
            EXE = args[1]
        try:
            observar()
        except KeyboardInterrupt:
            print("observador encerrado")
