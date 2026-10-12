"""Pastas de dados e configuração do myproX2 (XDG)."""
import os
import shutil

NOME = "myproX2"


def pasta_dados():
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, NOME)


def pasta_config():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, NOME)


def migrar_backup(origem, destino):
    """Copia origem para destino se o destino não existir. Nunca move nem apaga. Devolve True se copiou."""
    if os.path.exists(destino) or not os.path.isfile(origem):
        return False
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    shutil.copy2(origem, destino)
    return True
