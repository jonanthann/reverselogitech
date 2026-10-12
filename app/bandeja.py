"""StatusNotifierItem + com.canonical.dbusmenu via Gio.DBus."""
import os

from gi.repository import Gio, GLib

import bateria as bat
from app import puro

SNI_XML = """<node><interface name="org.kde.StatusNotifierItem">
<property name="Category" type="s" access="read"/><property name="Id" type="s" access="read"/>
<property name="Title" type="s" access="read"/><property name="Status" type="s" access="read"/>
<property name="WindowId" type="i" access="read"/><property name="IconName" type="s" access="read"/>
<property name="IconPixmap" type="a(iiay)" access="read"/><property name="OverlayIconName" type="s" access="read"/>
<property name="AttentionIconName" type="s" access="read"/>
<property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
<property name="ItemIsMenu" type="b" access="read"/><property name="Menu" type="o" access="read"/>
<method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="Scroll"><arg type="i" direction="in"/><arg type="s" direction="in"/></method>
<signal name="NewIcon"/><signal name="NewToolTip"/><signal name="NewStatus"><arg type="s"/></signal>
</interface></node>"""

MENU_XML = """<node><interface name="com.canonical.dbusmenu">
<property name="Version" type="u" access="read"/><property name="TextDirection" type="s" access="read"/>
<property name="Status" type="s" access="read"/><property name="IconThemePath" type="as" access="read"/>
<method name="GetLayout"><arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="as" direction="in"/>
<arg type="u" direction="out"/><arg type="(ia{sv}av)" direction="out"/></method>
<method name="GetGroupProperties"><arg type="ai" direction="in"/><arg type="as" direction="in"/>
<arg type="a(ia{sv})" direction="out"/></method>
<method name="GetProperty"><arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/></method>
<method name="Event"><arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="in"/><arg type="u" direction="in"/></method>
<method name="EventGroup"><arg type="a(isvu)" direction="in"/><arg type="ai" direction="out"/></method>
<method name="AboutToShow"><arg type="i" direction="in"/><arg type="b" direction="out"/></method>
<method name="AboutToShowGroup"><arg type="ai" direction="in"/><arg type="ai" direction="out"/><arg type="ai" direction="out"/></method>
<signal name="ItemsPropertiesUpdated"><arg type="a(ia{sv})"/><arg type="a(ia{sv})"/></signal>
<signal name="LayoutUpdated"><arg type="u"/><arg type="i"/></signal>
</interface></node>"""

CAM_ITEM, CAM_MENU = "/StatusNotifierItem", "/MenuBar"


def _v(props):
    return {k: (GLib.Variant("b", v) if isinstance(v, bool) else GLib.Variant("s", v)) for k, v in props.items()}


class Bandeja:
    def __init__(self, app, servico):
        self.app, self.servico = app, servico
        self.rev = 1
        self.conn = None
        self._id_nome = 0
        self._id_watch = 0
        self.nome = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        servico.ao_mudar(self._mudou)

    def iniciar(self):
        self._id_nome = Gio.bus_own_name(Gio.BusType.SESSION, self.nome, Gio.BusNameOwnerFlags.NONE,
                                         self._barramento, self._nome_obtido, None)

    def parar(self):
        if self._id_watch:
            Gio.bus_unwatch_name(self._id_watch)
            self._id_watch = 0
        if self._id_nome:
            Gio.bus_unown_name(self._id_nome)
            self._id_nome = 0

    def _barramento(self, conn, nome):
        self.conn = conn
        sni = Gio.DBusNodeInfo.new_for_xml(SNI_XML).interfaces[0]
        menu = Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0]
        conn.register_object(CAM_ITEM, sni, self._chamada_sni, self._prop_sni, None)
        conn.register_object(CAM_MENU, menu, self._chamada_menu, self._prop_menu, None)

    def _nome_obtido(self, conn, nome):
        # só registra no watcher depois de ter o nome no barramento
        self._id_watch = Gio.bus_watch_name_on_connection(
            conn, "org.kde.StatusNotifierWatcher", Gio.BusNameWatcherFlags.NONE, self._registrar, None)

    def _registrar(self, conn, nome, dono):
        conn.call("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher", "org.kde.StatusNotifierWatcher",
                  "RegisterStatusNotifierItem", GLib.Variant("(s)", (self.nome,)), None,
                  Gio.DBusCallFlags.NONE, -1, None, None, None)

    def _prop_sni(self, conn, remetente, caminho, iface, prop):
        s = self.servico
        if prop == "Category":
            return GLib.Variant("s", "Hardware")
        if prop == "Id":
            return GLib.Variant("s", "myproX2")
        if prop == "Title":
            return GLib.Variant("s", "myproX2")
        if prop == "Status":
            return GLib.Variant("s", "Active")
        if prop == "WindowId":
            return GLib.Variant("i", 0)
        if prop == "IconName":
            return GLib.Variant("s", bat.nome_icone(s.info))
        if prop in ("OverlayIconName", "AttentionIconName"):
            return GLib.Variant("s", "")
        if prop == "IconPixmap":
            return GLib.Variant("a(iiay)", [])
        if prop == "ToolTip":
            t, d = puro.texto_tooltip(s.info, s.conectado, s.ultima)
            return GLib.Variant("(sa(iiay)ss)", (bat.nome_icone(s.info), [], t, d))
        if prop == "ItemIsMenu":
            return GLib.Variant("b", False)
        if prop == "Menu":
            return GLib.Variant("o", CAM_MENU)
        return None

    def _chamada_sni(self, conn, remetente, caminho, iface, metodo, params, inv):
        if metodo in ("Activate", "SecondaryActivate"):
            GLib.idle_add(self.app.activate)
        inv.return_value(None)

    def _prop_menu(self, conn, remetente, caminho, iface, prop):
        return {"Version": GLib.Variant("u", 3), "TextDirection": GLib.Variant("s", "ltr"),
                "Status": GLib.Variant("s", "normal"), "IconThemePath": GLib.Variant("as", [])}.get(prop)

    def _chamada_menu(self, conn, remetente, caminho, iface, metodo, params, inv):
        if metodo == "GetLayout":
            rev, raiz = puro.layout_menu(self.servico.info, self.rev)
            inv.return_value(GLib.Variant("(u(ia{sv}av))", (rev, self._tupla(raiz))))
        elif metodo == "GetGroupProperties":
            _, raiz = puro.layout_menu(self.servico.info, self.rev)
            ids = params.unpack()[0]
            itens = [(i, _v(p)) for i, p, _f in [raiz] + raiz[2] if not ids or i in ids]
            inv.return_value(GLib.Variant("(a(ia{sv}))", (itens,)))
        elif metodo == "GetProperty":
            inv.return_value(GLib.Variant("(v)", (GLib.Variant("s", ""),)))
        elif metodo in ("Event", "EventGroup"):
            eventos = [params.unpack()[:2]] if metodo == "Event" else [e[:2] for e in params.unpack()[0]]
            for i, tipo in eventos:
                if tipo == "clicked":
                    if i == 3:
                        GLib.idle_add(self.app.activate)
                    elif i == 4:
                        GLib.idle_add(self.app.quit)
            inv.return_value(None if metodo == "Event" else GLib.Variant("(ai)", ([],)))
        elif metodo == "AboutToShow":
            inv.return_value(GLib.Variant("(b)", (False,)))
        elif metodo == "AboutToShowGroup":
            inv.return_value(GLib.Variant("(aiai)", ([], [])))
        else:
            inv.return_value(None)

    def _tupla(self, item):
        i, props, filhos = item
        return (i, _v(props), [GLib.Variant("(ia{sv}av)", self._tupla(f)) for f in filhos])

    def _mudou(self, servico, avisos):
        if self.conn is None:
            return
        self.rev += 1
        self.conn.emit_signal(None, CAM_ITEM, "org.kde.StatusNotifierItem", "NewIcon", None)
        self.conn.emit_signal(None, CAM_ITEM, "org.kde.StatusNotifierItem", "NewToolTip", None)
        self.conn.emit_signal(None, CAM_MENU, "com.canonical.dbusmenu", "LayoutUpdated",
                              GLib.Variant("(ui)", (self.rev, 0)))
