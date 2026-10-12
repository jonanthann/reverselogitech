"""Notificações de bateria: Gio.Notification, com fallback para org.freedesktop.Notifications."""
import os

from gi.repository import Gio, GLib

from app import puro


def _tem_desktop():
    return any(os.path.exists(os.path.join(d, "applications", puro.APP_ID + ".desktop"))
               for d in [puro.pasta_dados_xdg()] + (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":"))


class Notificador:
    def __init__(self, app):
        self.app = app

    def avisar(self, avisos, info):
        for tipo, urgente in puro.decidir_notificacoes(avisos):
            self._enviar(tipo, urgente, info)

    def _enviar(self, tipo, urgente, info):
        titulo, texto = puro.texto_notificacao(tipo, info)
        if _tem_desktop():
            n = Gio.Notification.new(titulo)
            n.set_body(texto)
            n.set_priority(Gio.NotificationPriority.URGENT if urgente else Gio.NotificationPriority.NORMAL)
            n.add_button("Abrir", "app.abrir")
            n.set_default_action("app.abrir")
            self.app.send_notification("bateria", n)
            return
        conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        dicas = {"urgency": GLib.Variant("y", 2 if urgente else 1), "desktop-entry": GLib.Variant("s", puro.APP_ID)}
        conn.call("org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications",
                  "Notify", GLib.Variant("(susssasa{sv}i)", ("myproX2", 0, puro.APP_ID, titulo, texto, [], dicas, -1)),
                  None, Gio.DBusCallFlags.NONE, -1, None, None, None)
