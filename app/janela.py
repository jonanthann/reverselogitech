"""Janela principal: vagas do mouse (cartões e editor), com abas reservadas para Botões e Macros (fase 4b)."""
import os
import threading
import traceback

from gi.repository import Adw, Gio, GLib, Gtk

import prox2
from app import formulario, puro
from painel_core import ErroPainel, Painel

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LODS = ["baixo", "médio", "alto"]
ERROS = (ErroPainel, OSError, prox2.ErroMouse, ValueError)


def carregar_css():
    from gi.repository import Gdk
    css = Gtk.CssProvider()
    css.load_from_path(os.path.join(RAIZ, "app", "estilo.css"))
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def rotulo(texto, *classes, xalign=0.0, **kw):
    r = Gtk.Label(label=texto, xalign=xalign, **kw)
    for c in classes:
        r.add_css_class(c)
    return r


def botao(texto, *classes):
    b = Gtk.Button(label=texto)
    b.add_css_class("acao")
    for c in classes:
        b.add_css_class(c)
    return b


class Janela(Adw.ApplicationWindow):
    def __init__(self, app, servico):
        super().__init__(application=app, title="myproX2", default_width=520, default_height=720)
        self.set_size_request(340, 400)
        self.add_css_class("myprox")
        carregar_css()
        self.servico = servico
        self.painel = None
        self.mouse_do_painel = None
        self.dados = None
        self.sel = None
        self.inicial = None
        self.ocupado = False
        self.recarregar = False
        self._pulso = 0
        self._montando = False
        self.linhas = []
        self.taxas = []

        self.toasts = Adw.ToastOverlay()
        self.pilha = Adw.ViewStack()
        self.pilha.add_titled_with_icon(self._pagina_vagas(), "vagas", "Vagas", "view-list-symbolic")
        self.pilha.add_titled_with_icon(self._pagina_vazia("Os botões ficam aqui na próxima fase."), "botoes",
                                        "Botões", "input-mouse-symbolic")
        self.pilha.add_titled_with_icon(self._pagina_vazia("As macros ficam aqui na próxima fase."), "macros",
                                        "Macros", "media-record-symbolic")
        self.toasts.set_child(self.pilha)

        self.progresso = Gtk.ProgressBar()
        self.progresso.add_css_class("osd")
        self.progresso.set_opacity(0)
        barra = Adw.ViewSwitcherBar(stack=self.pilha, reveal=True)
        vista = Adw.ToolbarView()
        vista.add_top_bar(self._cabecalho())
        vista.add_top_bar(self.progresso)
        vista.add_bottom_bar(barra)
        vista.set_content(self.toasts)
        self.set_content(vista)
        servico.ao_mudar(self._mudou)
        self._mudou(servico, [])

    # construção

    def _cabecalho(self):
        h = Adw.HeaderBar()
        h.set_title_widget(Gtk.Label(label="myproX2", css_classes=["heading"]))
        bat = Gtk.Box(spacing=6)
        self.icone_bat = Gtk.Image.new_from_icon_name("battery-missing-symbolic")
        self.txt_bat = Gtk.Label()
        self.estado = Gtk.Label(css_classes=["suave"])
        bat.append(self.icone_bat)
        bat.append(self.txt_bat)
        bat.append(self.estado)
        h.pack_start(bat)
        menu = Gio.Menu()
        menu.append("Iniciar com a sessão", "win.autostart")
        menu.append("Sair", "app.sair")
        h.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, primary=True))
        acao = Gio.SimpleAction.new_stateful("autostart", None, GLib.Variant.new_boolean(puro.autostart_ativo()))
        acao.connect("activate", self._auto)
        self.add_action(acao)
        return h

    def _pagina_vazia(self, texto):
        return Adw.StatusPage(title=texto, icon_name="document-edit-symbolic")

    def _pagina_vagas(self):
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin_top=14, margin_bottom=14,
                      margin_start=12, margin_end=12)
        self.faixa = rotulo("", "faixa-aviso", wrap=True, visible=False)
        col.append(self.faixa)
        self.cartoes = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, min_children_per_line=1,
                                   max_children_per_line=5, column_spacing=10, row_spacing=10, homogeneous=True)
        col.append(self.cartoes)
        self.vazio = rotulo("Mouse desconectado. Conecte para editar as vagas.", "vazio", wrap=True)
        col.append(self.vazio)
        self.editor = self._editor()
        col.append(self.editor)
        clamp = Adw.Clamp(maximum_size=960, child=col)
        sc = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        sc.set_child(clamp)
        return sc

    def _editor(self):
        e = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, visible=False)
        e.add_css_class("vidro")
        self.titulo = rotulo("", "titulo-vaga", wrap=True)
        self.aviso = rotulo("", "aviso-vaga", wrap=True, visible=False)
        e.append(self.titulo)
        e.append(self.aviso)
        e.append(rotulo("Níveis de DPI", "suave", margin_top=8))
        self.caixa_niveis = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        e.append(self.caixa_niveis)
        self.btn_add = botao("Adicionar nível")
        self.btn_add.set_halign(Gtk.Align.START)
        self.btn_add.connect("clicked", self._add_nivel)
        e.append(self.btn_add)
        e.append(rotulo("Polling", "suave", margin_top=8))
        self.polling = Gtk.DropDown(model=Gtk.StringList(), halign=Gtk.Align.START)
        e.append(self.polling)
        e.append(rotulo("LOD (distância de elevação)", "suave", margin_top=8))
        self.lod = Gtk.DropDown(model=Gtk.StringList.new(LODS), halign=Gtk.Align.START)
        e.append(self.lod)
        e.append(rotulo("Nome (até 24 caracteres)", "suave", margin_top=8))
        self.nome = Gtk.Entry(max_length=formulario.MAX_NOME, placeholder_text="Sem nome")
        e.append(self.nome)
        linha = Gtk.Box(spacing=10, margin_top=10)
        linha.append(rotulo("Vaga ativa", hexpand=True))
        self.ativa = Gtk.Switch(valign=Gtk.Align.CENTER)
        linha.append(self.ativa)
        e.append(linha)
        self.acoes = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, min_children_per_line=1,
                                 max_children_per_line=3, column_spacing=8, row_spacing=8, margin_top=14)
        self.b_gravar = botao("Gravar no mouse", "prim")
        self.b_usar = botao("Usar agora")
        self.b_rest = botao("Restaurar", "perigo")
        self.b_gravar.connect("clicked", self._gravar)
        self.b_usar.connect("clicked", self._usar)
        self.b_rest.connect("clicked", self._restaurar)
        for b in (self.b_gravar, self.b_usar, self.b_rest):
            self.acoes.append(b)
        e.append(self.acoes)
        return e

    # estado do serviço

    def _auto(self, acao, _p):
        novo = not acao.get_state().get_boolean()
        try:
            puro.definir_autostart(novo, os.path.join(RAIZ, "myprox2.py"))
        except OSError as e:
            self._toast(f"Não foi possível alterar a inicialização automática: {e}")
            return
        acao.set_state(GLib.Variant.new_boolean(novo))

    def _mudou(self, servico, _avisos):
        i = servico.info
        if i and i["soc"] is not None:
            n = min(100, max(0, round(i["soc"] / 10) * 10))
            carga = "-charging" if i.get("carregando") else ""
            self.icone_bat.set_from_icon_name(f"battery-level-{n}{carga}-symbolic")
            self.txt_bat.set_label(f"{i['soc']}%")
        else:
            self.icone_bat.set_from_icon_name("battery-missing-symbolic")
            self.txt_bat.set_label("--")
        self.estado.set_label("Conectado" if servico.conectado else "Desconectado")
        m = servico.mouse
        if m is None:
            self.painel = self.mouse_do_painel = None
        elif m is not self.mouse_do_painel:
            if self._alterado():
                self._toast("Mouse reconectado: as alterações não gravadas foram descartadas.")
            self.mouse_do_painel = m
            self.painel = Painel(m, servico.pasta_dados, backup=servico.backup)
            self.recarregar = True
            self._recarregar()
        self._sensibilidade()

    def _sensibilidade(self):
        livre = self.painel is not None and not self.ocupado
        self.editor.set_sensitive(livre)
        self.cartoes.set_sensitive(livre)
        self.vazio.set_visible(self.painel is None and self.dados is None)

    # trabalho em thread

    def _ocupar(self, sim):
        self.ocupado = sim
        self.progresso.set_opacity(1 if sim else 0)
        if sim and not self._pulso:
            self._pulso = GLib.timeout_add(80, self._pulsar)
        self._sensibilidade()

    def _pulsar(self):
        if not self.ocupado:
            self._pulso = 0
            return GLib.SOURCE_REMOVE
        self.progresso.pulse()
        return GLib.SOURCE_CONTINUE

    def _recarregar(self):
        """Dispara o listar pendente assim que o painel estiver livre."""
        if self.recarregar and self.painel is not None and not self.ocupado:
            self.recarregar = False
            self._rodar(self.painel.listar, self._carregou)

    def _rodar(self, fn, ok, msg=None, recarregar_se_falhar=False):
        """Roda fn numa thread; ok(resultado) e a mensagem de sucesso voltam pela thread principal."""
        if self.ocupado:
            return
        self._ocupar(True)

        def trabalho():
            try:
                r = fn()
            except ERROS as e:
                GLib.idle_add(self._fim, None, str(e) or type(e).__name__, ok, msg, recarregar_se_falhar)
            except Exception:
                traceback.print_exc()
                GLib.idle_add(self._fim, None, "Erro inesperado. Veja o terminal.", ok, msg, recarregar_se_falhar)
            else:
                GLib.idle_add(self._fim, r, None, ok, msg, recarregar_se_falhar)
        threading.Thread(target=trabalho, name="painel-prox2", daemon=True).start()

    def _fim(self, r, erro, ok, msg, recarregar_se_falhar=False):
        self._ocupar(False)
        if erro:
            self._toast(erro)
            if recarregar_se_falhar:
                self.recarregar = True
        else:
            ok(r)
            if msg:
                self._toast(msg)
        self._recarregar()
        return False

    def _toast(self, texto):
        self.toasts.add_toast(Adw.Toast(title=texto, timeout=6))

    # dados -> tela

    def _carregou(self, dados, manter_sel=False):
        self.dados = dados
        self.taxas = list(dados["taxas"])
        self.faixa.set_label(dados["aviso_diretorio"] or "")
        self.faixa.set_visible(bool(dados["aviso_diretorio"]))
        secs = [v["sec"] for v in dados["vagas"]]
        if self.sel not in secs:
            self.sel = dados["em_uso"] if dados["em_uso"] in secs else (secs[0] if secs else None)
        self._desenhar_cartoes()
        self._preencher()
        self._sensibilidade()

    def _vaga(self):
        return next((v for v in (self.dados or {"vagas": []})["vagas"] if v["sec"] == self.sel), None)

    def _desenhar_cartoes(self):
        while (c := self.cartoes.get_first_child()) is not None:
            self.cartoes.remove(c)
        for v in self.dados["vagas"]:
            b = Gtk.Button()
            b.add_css_class("cartao")
            if v["sec"] == self.sel:
                b.add_css_class("sel")
            if not v["ativa"]:
                b.add_css_class("off")
            caixa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            est = ("Em uso" if v["em_uso"] else "Ativa" if v["ativa"] else "Desligada") \
                + ("" if v["crc_ok"] else " (CRC inválido)")
            caixa.append(rotulo(v["nome"], "nome", wrap=True, wrap_mode=2))
            caixa.append(rotulo(", ".join(map(str, v["dpis"])) + " DPI", wrap=True))
            caixa.append(rotulo(f"{v['polling_hz']} Hz"))
            caixa.append(rotulo(est, *(["etq"] if v["em_uso"] else []), margin_top=4))
            b.set_child(caixa)
            b.connect("clicked", self._escolheu, v["sec"])
            self.cartoes.append(b)

    def _preencher(self):
        v = self._vaga()
        self.editor.set_visible(v is not None)
        if v is None:
            return
        self._montando = True
        self.titulo.set_label("Editando: " + v["nome"])
        self.aviso.set_label(v["aviso"] or "")
        self.aviso.set_visible(bool(v["aviso"]))
        f = formulario.de_vaga(v)
        taxas = self.taxas if f["polling_hz"] in self.taxas else sorted(self.taxas + [f["polling_hz"]])
        self.taxas_vaga = taxas
        self.polling.set_model(Gtk.StringList.new([f"{t} Hz" for t in taxas]))
        self.polling.set_selected(taxas.index(f["polling_hz"]))
        self.lod.set_selected(f["lod"] - 1)
        self.ativa.set_active(f["ativa"])
        self.nome.set_text(f["nome"])
        self._montar_niveis(f["niveis"], f["padrao"], f["shift"])
        self.inicial = f
        self._montando = False

    def _montar_niveis(self, niveis, padrao, shift):
        while (c := self.caixa_niveis.get_first_child()) is not None:
            self.caixa_niveis.remove(c)
        self.linhas = []
        gp = gs = None
        for i, n in enumerate(niveis):
            linha = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, min_children_per_line=1,
                                max_children_per_line=4, column_spacing=8, row_spacing=4)
            spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=n, lower=formulario.DPI_MIN,
                                                            upper=formulario.DPI_MAX, step_increment=10,
                                                            page_increment=100), numeric=True)
            rp = Gtk.CheckButton(label="Padrão", active=i == padrao)
            rs = Gtk.CheckButton(label="Shift", active=i == shift)
            if gp is None:
                gp, gs = rp, rs
            else:
                rp.set_group(gp)
                rs.set_group(gs)
            rem = botao("Remover")
            rem.set_sensitive(len(niveis) > 1)
            rem.connect("clicked", self._rem_nivel, i)
            spin.set_tooltip_text(f"DPI do nível {i + 1}")
            for w in (spin, rp, rs, rem):
                linha.append(w)
            self.caixa_niveis.append(linha)
            self.linhas.append((spin, rp, rs))
        self.btn_add.set_sensitive(len(niveis) < formulario.MAX_NIVEIS)

    def _ler_form(self):
        sp = self.linhas
        return {"niveis": [s.get_value_as_int() for s, _, _ in sp],
                "padrao": next((i for i, (_, p, _) in enumerate(sp) if p.get_active()), 0),
                "shift": next((i for i, (_, _, s) in enumerate(sp) if s.get_active()), 0),
                "polling_hz": self.taxas_vaga[self.polling.get_selected()],
                "lod": self.lod.get_selected() + 1, "ativa": self.ativa.get_active(),
                "nome": self.nome.get_text()}

    def _alterado(self):
        return self.inicial is not None and self.editor.get_visible() and \
            formulario.alterado(self.inicial, self._ler_form())

    # ações

    def _rem_nivel(self, _b, i):
        f = self._ler_form()
        n, p, s = formulario.remover_nivel(f["niveis"], f["padrao"], f["shift"], i)
        self._montar_niveis(n, p, s)

    def _add_nivel(self, _b):
        f = self._ler_form()
        self._montar_niveis(formulario.adicionar_nivel(f["niveis"]), f["padrao"], f["shift"])

    def _confirmar(self, titulo, texto, rotulo_ok, ok, perigo=True):
        d = Adw.AlertDialog(heading=titulo, body=texto)
        d.add_response("cancelar", "Cancelar")
        d.add_response("ok", rotulo_ok)
        if perigo:
            d.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE)
        d.set_default_response("cancelar")
        d.set_close_response("cancelar")
        d.connect("response", lambda _d, r: ok() if r == "ok" else None)
        d.present(self)

    def _descartando(self, seguir):
        if self._alterado():
            self._confirmar("Descartar alterações?", "Há alterações não gravadas nesta vaga.", "Descartar", seguir)
        else:
            seguir()

    def _escolheu(self, _b, sec):
        if sec == self.sel or self.ocupado:
            return

        def ir():
            self.sel = sec
            self._desenhar_cartoes()
            self._preencher()
        self._descartando(ir)

    def _gravar(self, _b):
        try:
            args = formulario.argumentos(self.inicial, self._ler_form())
        except ValueError as e:
            self._toast(str(e))
            return
        if not args:
            self._toast("Nada para gravar.")
            return
        sec, p = self.sel, self.painel
        self._rodar(lambda: (p.gravar(sec, **args), p.listar())[1], self._carregou, "Gravado e verificado", recarregar_se_falhar=True)

    def _usar(self, _b):
        def go():
            sec, p = self.sel, self.painel
            self._rodar(lambda: (p.usar_agora(sec), p.listar())[1], self._carregou, "Vaga em uso", recarregar_se_falhar=True)
        self._descartando(go)

    def _restaurar(self, _b):
        def go():
            sec, p = self.sel, self.painel
            self._rodar(lambda: (p.restaurar(sec), p.listar())[1], self._carregou, "Vaga restaurada", recarregar_se_falhar=True)
        self._confirmar("Restaurar esta vaga?", "A vaga volta aos valores de fábrica. Há backup para desfazer.",
                        "Restaurar", go)
