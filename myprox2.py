#!/usr/bin/env python3
"""Inicia o app myproX2. Opções: --background, --simular-bateria N, --simular-carga, --falso (mouse em memória, sem hardware); comandos instalar-local/desinstalar-local."""
import os
import shutil
import sys

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)


def _servico_falso(simular, carga):
    """Mouse em memória com os setores do backup (macros vazias); dados e backup vão para uma pasta temporária."""
    import json
    import tempfile
    from app.servico import Servico
    from tests.mouse_falso import MouseFalso
    with open(os.path.join(RAIZ, "prox2_backup_perfis.json")) as f:
        setores = {int(k, 16): bytes.fromhex(v) for k, v in json.load(f).items()}
    setores.update({n: b"\xff" * 255 for n in range(6, 16)})
    tmp = tempfile.mkdtemp(prefix="myprox2-falso-")
    return Servico(simular, carga, MouseFalso(setores, em_uso=1), os.path.join(tmp, "dados"), os.path.join(tmp, "backup.json"))


def main(argv):
    from app import puro
    if "instalar-local" in argv:
        for c in puro.instalar_local(RAIZ):
            print("Gravado:", c)
        return 0
    if "desinstalar-local" in argv:
        for c in puro.desinstalar_local():
            print("Removido:", c)
        return 0
    simular, carga, falso, resto, i = None, False, False, [argv[0]], 1
    while i < len(argv):
        if argv[i] == "--simular-bateria" and i + 1 < len(argv):
            simular = int(argv[i + 1])
            i += 1
        elif argv[i] == "--simular-carga":
            carga = True
            simular = 50 if simular is None else simular
        elif argv[i] == "--falso":
            falso = True
            simular = 80 if simular is None else simular
        else:
            resto.append(argv[i])
        i += 1
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from app.aplicacao import Aplicacao
    servico = None
    if falso:
        servico = _servico_falso(simular, carga)
    try:
        return Aplicacao(simular, carga, servico).run(resto)
    finally:
        if servico is not None:
            shutil.rmtree(os.path.dirname(servico.pasta_dados), ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
