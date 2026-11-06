"""Gera o pacote do SERVIDOR: dist/PainelServidor_<versao>.zip (PyInstaller, pasta, sem console).

Uso: python empacotar_servidor.py   (ou empacotar_servidor.bat)
O pacote leva o painel do servidor + pywinauto (controle do Salux). NAO leva .env, token nem banco:
o .env e criado na maquina do servidor a partir de .env.exemplo; o token e gerado na 1a execucao.
"""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from versao import VERSAO

RAIZ = Path(__file__).resolve().parent
DIST, BUILD = RAIZ / "dist", RAIZ / "build"
PKG = BUILD / "pkg"   # monta fora de dist: nao conflita com um .exe em uso em dist
PASTA = PKG / "PainelServidor"
PROIBIDOS = ("servidor_config.json", "cliente_config.json", "fila.db", "logs_cliente", "mapa/")


def main():
    DIST.mkdir(exist_ok=True)
    shutil.rmtree(PASTA, ignore_errors=True)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
                    "--name", "PainelServidor", "--distpath", str(PKG), "--workpath", str(BUILD),
                    "--specpath", str(BUILD), "--collect-submodules", "pywinauto",
                    "--hidden-import", "comtypes", "--hidden-import", "win32timezone",
                    "painel_servidor.py"], check=True, cwd=RAIZ)
    for arq in (RAIZ / "pacote_servidor").iterdir():
        shutil.copy2(arq, PASTA / arq.name)
    zip_path = DIST / f"PainelServidor_{VERSAO}.zip"
    zip_path.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for arq in sorted(PASTA.rglob("*")):
            if arq.is_file():
                z.write(arq, Path("PainelServidor") / arq.relative_to(PASTA))
    nomes = zipfile.ZipFile(zip_path).namelist()
    ruins = [n for n in nomes if any(p in n.lower() for p in PROIBIDOS)
             or Path(n).name == ".env"]  # so .env.exemplo pode ir
    if ruins:
        zip_path.unlink()
        raise SystemExit(f"ERRO: o pacote contem arquivos que nao devem ir: {ruins[:5]}")
    print(f"\nPacote gerado: {zip_path}  ({zip_path.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
