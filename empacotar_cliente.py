"""Gera o pacote do cliente: dist/PainelCliente_<versao>.zip (PyInstaller, pasta, sem console).

Uso: python empacotar_cliente.py   (ou empacotar_cliente.bat)
O pacote leva so o painel cliente (sem pywinauto, .env nem codigo do Salux) e NAO leva token.
"""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from versao import VERSAO

RAIZ = Path(__file__).resolve().parent
DIST, BUILD = RAIZ / "dist", RAIZ / "build"
PASTA = DIST / "PainelCliente"
PROIBIDOS = (".env", "servidor_config", "cliente_config.json", "fila.db", "pywinauto", "salux_sessao",
             "cbo_core", "logs_cliente")


def main():
    shutil.rmtree(PASTA, ignore_errors=True)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
                    "--name", "PainelCliente", "--distpath", str(DIST), "--workpath", str(BUILD),
                    "--specpath", str(BUILD), "--exclude-module", "pywinauto", "painel_cliente.py"],
                   check=True, cwd=RAIZ)
    for arq in (RAIZ / "pacote_cliente").iterdir():
        shutil.copy2(arq, PASTA / arq.name)
    zip_path = DIST / f"PainelCliente_{VERSAO}.zip"
    zip_path.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for arq in sorted(PASTA.rglob("*")):
            if arq.is_file():
                z.write(arq, Path("PainelCliente") / arq.relative_to(PASTA))
    ruins = [n for n in zipfile.ZipFile(zip_path).namelist()
             if any(p in n.lower() for p in PROIBIDOS) and not n.endswith(".exemplo")]
    if ruins:
        zip_path.unlink()
        raise SystemExit(f"ERRO: o pacote contem arquivos que nao devem ir: {ruins[:5]}")
    print(f"\nPacote gerado: {zip_path}  ({zip_path.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
