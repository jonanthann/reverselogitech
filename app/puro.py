"""Lógica pura do app (sem GTK nem GLib): textos, layout do menu, notificações, arquivos .desktop."""
import os
import time

import caminhos

APP_ID = "io.github.jonanthann.myproX2"
ESTADOS_PT = {"descarregando": "descarregando", "carregando": "carregando",
              "carregando_devagar": "carregando devagar", "completa": "carga completa", "erro": "erro"}


def resumo_bateria(info):
    """Ex.: '57%, descarregando'."""
    if info is None:
        return "sem leitura"
    soc = f"{info['soc']}%" if info["soc"] is not None else info["nivel"]
    return f"{soc}, {ESTADOS_PT.get(info['estado_carga'], info['estado_carga'])}"


def texto_tooltip(info, conectado, ultima=None):
    """Devolve (título, descrição) do tooltip."""
    desc = resumo_bateria(info)
    if not conectado:
        hora = time.strftime("%H:%M", time.localtime(ultima)) if ultima else "--:--"
        desc += f"\núltima leitura {hora}" if info is not None else f"\ndesconectado, última leitura {hora}"
    return "myproX2", desc


def texto_item_bateria(info):
    if info is None:
        return "Bateria indisponível"
    soc = f"{info['soc']}%" if info["soc"] is not None else info["nivel"]
    return f"Bateria {soc} ({ESTADOS_PT.get(info['estado_carga'], info['estado_carga'])})"


def layout_menu(info, revisao=1):
    """Estrutura dbusmenu (revisão, (id, props, filhos)) para GetLayout."""
    def item(i, props):
        return (i, props, [])
    filhos = [
        item(1, {"label": texto_item_bateria(info), "enabled": False}),
        item(2, {"type": "separator"}),
        item(3, {"label": "Abrir myproX2"}),
        item(4, {"label": "Sair"}),
    ]
    return revisao, (0, {"children-display": "submenu"}, filhos)


def decidir_notificacoes(avisos):
    """Traduz a saída de Alertas.atualizar em (tipo, urgente) na ordem de exibição; só o mais grave de baixa/crítica."""
    if "critica" in avisos:
        avisos = [a for a in avisos if a != "baixa"]
    return [(a, a == "critica") for a in avisos]


def texto_notificacao(tipo, info):
    soc = f"{info['soc']}%" if info and info["soc"] is not None else ""
    if tipo == "critica":
        return "Bateria crítica", f"O mouse está com {soc}. Conecte o cabo agora.".replace("com .", "quase sem bateria.")
    if tipo == "baixa":
        return "Bateria baixa", f"O mouse está com {soc}. Considere carregar.".replace("com .", "com pouca bateria.")
    return "Bateria carregada", "O mouse terminou de carregar."


def escapar_exec(caminho):
    """Argumento do Exec entre aspas duplas, conforme a Desktop Entry Specification."""
    r = caminho.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
    return '"' + r.replace("%", "%%") + '"'


def conteudo_desktop(exec_cmd="myprox2 %U"):
    return (
        "[Desktop Entry]\nType=Application\nName=myproX2\n"
        "Comment=Bateria e configurações do mouse PRO X 2\n"
        f"Exec={exec_cmd}\nIcon={APP_ID}\nTerminal=false\n"
        "Categories=Settings;HardwareSettings;\nStartupNotify=true\n"
        "X-GNOME-UsesNotifications=true\n"
    )


def comando_app(raiz):
    """Comando do app: 'myprox2' se instalado pelo pacote, senão python3 com o myprox2.py da raiz."""
    if caminhos.instalado(raiz):
        return "myprox2"
    return f'python3 {escapar_exec(os.path.join(raiz, "myprox2.py"))}'


def conteudo_autostart(comando):
    return conteudo_desktop(f'{comando} --background').replace("StartupNotify=true\n", "") \
        + "X-GNOME-Autostart-enabled=true\n"


def pasta_dados_xdg():
    return os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")


def pasta_config_xdg():
    return os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")


def caminho_autostart(base=None):
    return os.path.join(base or pasta_config_xdg(), "autostart", APP_ID + ".desktop")


def autostart_ativo(base=None):
    return os.path.exists(caminho_autostart(base))


def definir_autostart(ativo, comando, base=None):
    c = caminho_autostart(base)
    if ativo:
        os.makedirs(os.path.dirname(c), exist_ok=True)
        with open(c, "w") as f:
            f.write(conteudo_autostart(comando))
    elif os.path.exists(c):
        os.remove(c)


def atualizar_autostart(comando, base=None):
    """Regrava o autostart ativo cujo Exec difere do comando atual. Devolve True se regravou."""
    c = caminho_autostart(base)
    if not os.path.exists(c):
        return False
    with open(c) as f:
        if f"Exec={comando} --background\n" in f.read():
            return False
    definir_autostart(True, comando, base)
    return True


def _destinos(base=None):
    b = base or pasta_dados_xdg()
    return (os.path.join(b, "applications", APP_ID + ".desktop"),
            os.path.join(b, "icons", "hicolor", "scalable", "apps", APP_ID + ".svg"))


def instalar_local(raiz, base=None):
    """Copia .desktop (Exec absoluto) e ícone. Devolve os caminhos gravados."""
    import shutil
    d, i = _destinos(base)
    os.makedirs(os.path.dirname(d), exist_ok=True)
    os.makedirs(os.path.dirname(i), exist_ok=True)
    with open(d, "w") as f:
        f.write(conteudo_desktop(f'{comando_app(raiz)} %U'))
    shutil.copyfile(os.path.join(raiz, "data", "icons", APP_ID + ".svg"), i)
    return d, i


def desinstalar_local(base=None):
    out = []
    for c in _destinos(base):
        if os.path.exists(c):
            os.remove(c)
            out.append(c)
    return out
