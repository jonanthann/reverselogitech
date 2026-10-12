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
    tmp = destino + ".tmp"
    shutil.copy2(origem, tmp)
    os.rename(tmp, destino)
    return True


def instalado(raiz):
    """Verdadeiro quando o código está instalado no sistema (ex.: /usr/share/prox2)."""
    return os.path.abspath(raiz).startswith("/usr/")


def arquivo_backup():
    return os.path.join(pasta_dados(), "prox2_backup_perfis.json")


def pasta_painel():
    return os.path.join(pasta_dados(), "painel_dados")


def migrar(raiz):
    """Copia backup e painel_dados antigos (ao lado do código) para a pasta de dados. Não roda se instalado."""
    if instalado(raiz):
        return
    migrar_backup(os.path.join(raiz, "prox2_backup_perfis.json"), arquivo_backup())
    antigo, novo = os.path.join(raiz, "painel_dados"), pasta_painel()
    if os.path.isdir(antigo) and not os.path.exists(novo):
        os.makedirs(os.path.dirname(novo), exist_ok=True)
        tmp = novo + ".tmp"
        if os.path.exists(tmp):
            shutil.rmtree(tmp)
        shutil.copytree(antigo, tmp)
        os.rename(tmp, novo)
