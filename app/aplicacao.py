"""Adw.Application do myproX2: instância única, serviço em segundo plano e bandeja."""
import signal

from gi.repository import Adw, Gio, GLib

from app import puro
from app.bandeja import Bandeja
from app.janela import Janela
from app.notificacoes import Notificador
from app.servico import Servico


class Aplicacao(Adw.Application):
    def __init__(self, simular=None, simular_carga=False, servico=None):
        super().__init__(application_id=puro.APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.add_main_option("background", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE, "Sem janela", None)
        # As três abaixo são tratadas no main() de myprox2.py; ficam aqui só para aparecer no --help
        self.add_main_option("simular-bateria", 0, GLib.OptionFlags.NONE, GLib.OptionArg.INT, "Bateria simulada em N%", "N")
        self.add_main_option("simular-carga", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE, "Simula o mouse carregando", None)
        self.add_main_option("falso", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE, "Mouse em memória, sem tocar no hardware", None)
        self.servico = servico or Servico(simular, simular_carga)
        self.janela = None
        self._iniciado = False
        self._segurando = False

    def do_command_line(self, cl):
        opts = cl.get_options_dict()
        self.hold_se_segundo_plano(opts.contains("background"))
        self.activate_if(not opts.contains("background"))
        return 0

    def hold_se_segundo_plano(self, bg):
        if not self._segurando:
            self._segurando = True
            self.hold()

    def activate_if(self, abrir):
        self._garantir()
        if abrir:
            self.do_activate()

    def _garantir(self):
        if self._iniciado:
            return
        self._iniciado = True
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        for nome, fn in (("sair", lambda *a: self.quit()), ("abrir", lambda *a: self.do_activate())):
            acao = Gio.SimpleAction.new(nome, None)
            acao.connect("activate", fn)
            self.add_action(acao)
        # Ctrl+C, kill e fechamento do terminal encerram o app pelo caminho normal
        # Ctrl+Z deixaria o app parado e surdo ao kill, segurando o mouse; ignora
        signal.signal(signal.SIGTSTP, signal.SIG_IGN)
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, self._ao_sinal)
        self.notificador = Notificador(self)
        self.servico.ao_mudar(lambda s, avisos: self.notificador.avisar(avisos, s.info))
        self.bandeja = Bandeja(self, self.servico)
        self.bandeja.iniciar()
        self.servico.iniciar()

    def _ao_sinal(self, *a):
        self.quit()
        return GLib.SOURCE_REMOVE

    def do_activate(self):
        self._garantir()
        if self.janela is None:
            self.janela = Janela(self, self.servico)
            self.janela.connect("close-request", lambda j: j.hide() or True)
        self.janela.present()

    def do_shutdown(self):
        if self._iniciado:
            self.bandeja.parar()
            self.servico.parar()
        Adw.Application.do_shutdown(self)
