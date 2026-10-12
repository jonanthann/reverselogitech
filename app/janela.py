"""Janela principal: vagas do mouse (cartões e editor), botões (2 camadas) e macros."""
import os
import re
import threading
import traceback

from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk

import acoes
import caminhos
import prox2
from app import formulario, puro, teclas
from painel_core import ErroPainel, Painel

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LODS = ["baixo", "médio", "alto"]
ERROS = (ErroPainel, OSError, prox2.ErroMouse, ValueError)
CLIQUES = [("esquerdo", "Esquerdo"), ("direito", "Direito"), ("meio", "Meio"), ("voltar", "Trás"), ("avancar", "Frente")]
ORDEM = [k for k, _ in CLIQUES]  # índice da lista de botões, igual a formulario.NOMES_BOTOES
BOTAO_GTK = {1: "esquerdo", 2: "meio", 3: "direito", 8: "voltar", 9: "avancar"}
SVG_MOUSE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mouse.svg")
ALTURA_MOUSE = 220
MIDIAS = [(0xCD, "Play/pausa"), (0xB5, "Próxima faixa"), (0xB6, "Faixa anterior"), (0xE9, "Volume +"),
          (0xEA, "Volume -"), (0xE2, "Mudo")]
ESPECIAIS = [("proximo_dpi", "Próximo DPI"), ("dpi_anterior", "DPI anterior"), ("ciclo_dpi", "Ciclar DPI"),
             ("dpi_padrao", "DPI padrão"), ("shift_dpi", "DPI shift"), ("proximo_perfil", "Próximo perfil"),
             ("perfil_anterior", "Perfil anterior"), ("ciclo_perfil", "Ciclar perfil"), ("gshift", "G-Shift")]
TIPOS = [("clique", "Clique"), ("tecla", "Tecla"), ("midia", "Mídia"), ("especial", "Especial"),
         ("macro", "Macro"), ("desligado", "Desligado")]
PASSOS = [("aperta", "Aperta"), ("solta", "Solta"), ("espera", "Espera")]
ESTADOS_MACRO = {"vazia": "Vazia", "ok": "Pronta", "invalida": "Inválida"}


def carregar_css():
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
        self.recarga_ok = None  # callback da recarga pendente (None: recarga completa)
        self._pulso = 0
        self._montando = False
        self.linhas = []
        self.taxas = []
        self.est_btn = None  # botões em edição: [normal, gshift]
        self.ini_btn = None
        self.med = None  # macro em edição: sec, modo, passos, texto, espera, para
        self.btn_sel = None  # índice do botão selecionado (None: nenhum)
        self.btn_press = None  # região do botão físico pressionado sobre o desenho
        self.linhas_btn = {}  # (camada, índice) -> linha da lista
        self._roda = False
        self._roda_id = 0
        self._svg = None
        self._dim = None  # (largura, altura, escala) da última renderização
        self._mascara = None

        self.toasts = Adw.ToastOverlay()
        self.pilha = Adw.ViewStack()
        self.pilha.add_titled_with_icon(self._pagina_vagas(), "vagas", "Vagas", "view-list-symbolic")
        self.pilha.add_titled_with_icon(self._pagina_botoes(), "botoes", "Botões", "input-mouse-symbolic")
        self.pilha.add_titled_with_icon(self._pagina_macros(), "macros", "Macros", "media-record-symbolic")
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
        if caminhos.instalado(RAIZ):
            try:
                puro.atualizar_autostart(puro.comando_app(RAIZ))
            except OSError:
                pass
        acao = Gio.SimpleAction.new_stateful("autostart", None, GLib.Variant.new_boolean(puro.autostart_ativo()))
        acao.connect("activate", self._auto)
        self.add_action(acao)
        return h

    def _rolagem(self, col):
        sc = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        sc.set_child(Adw.Clamp(maximum_size=960, child=col))
        return sc

    def _pagina_botoes(self):
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=14, margin_bottom=14,
                      margin_start=12, margin_end=12)
        self.tit_botoes = rotulo("", "titulo-vaga", wrap=True)
        col.append(self.tit_botoes)
        col.append(self._desenho_mouse())
        col.append(rotulo("Passe o mouse sobre o desenho e aperte os botões para testar.", "suave", wrap=True))
        self.caixa_botoes = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.caixa_botoes.add_css_class("vidro")
        col.append(self.caixa_botoes)
        self.b_gravar_btn = botao("Gravar no mouse", "prim")
        self.b_gravar_btn.set_halign(Gtk.Align.START)
        self.b_gravar_btn.connect("clicked", self._gravar)
        col.append(self.b_gravar_btn)
        return self._rolagem(col)

    def _desenho_mouse(self):
        self.pic = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True, hexpand=True)
        self.pic.set_size_request(-1, ALTURA_MOUSE)
        clique = Gtk.GestureClick()
        clique.set_button(0)
        clique.connect("pressed", self._mouse_press)
        for sinal in ("released", "cancel", "stopped"):
            clique.connect(sinal, self._mouse_solta)
        self.pic.add_controller(clique)
        # garante que os botões 8 e 9 sobre o desenho não chegam a quem navega entre abas
        legado = Gtk.EventControllerLegacy()
        legado.connect("event", self._mouse_evento)
        self.pic.add_controller(legado)
        # sem grab implícito o release some fora do desenho ou sem foco: solta ao sair
        saida = Gtk.EventControllerMotion()
        saida.connect("leave", self._mouse_solta)
        self.pic.add_controller(saida)
        self.connect("notify::is-active", lambda w, _p: w.props.is_active or self._mouse_solta())
        roda = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        roda.connect("scroll", self._mouse_roda)
        self.pic.add_controller(roda)
        estilo = Adw.StyleManager.get_default()
        estilo.connect("notify::dark", lambda *_: self._render_mouse())
        estilo.connect("notify::accent-color", lambda *_: self._render_mouse())
        self.pic.add_tick_callback(self._mouse_tick)
        return self.pic

    def _mouse_tick(self, pic, _clock):
        dim = (pic.get_width(), pic.get_height(), self.get_scale_factor())
        if dim[0] > 0 and dim != self._dim:
            self._render_mouse()
        return GLib.SOURCE_CONTINUE

    def _pagina_macros(self):
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=14, margin_bottom=14,
                      margin_start=12, margin_end=12)
        self.lista_macros = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        col.append(self.lista_macros)
        self.b_nova = botao("Nova macro")
        self.b_nova.set_halign(Gtk.Align.START)
        self.b_nova.connect("clicked", lambda _b: self._abrir_macro(None, None))
        col.append(self.b_nova)
        self.editor_macro = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, visible=False)
        self.editor_macro.add_css_class("vidro")
        col.append(self.editor_macro)
        return self._rolagem(col)

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
            puro.definir_autostart(novo, puro.comando_app(RAIZ))
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
        for w in (self.caixa_botoes, self.b_gravar_btn, self.lista_macros, self.b_nova, self.editor_macro):
            w.set_sensitive(livre)
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
            ok, self.recarga_ok = self.recarga_ok or self._carregou, None
            self._rodar(self.painel.listar, ok)

    def _rodar(self, fn, ok, msg=None, recarregar_se_falhar=False, recarga=None):
        """Roda fn numa thread; ok(resultado) e a mensagem de sucesso voltam pela thread principal."""
        if self.ocupado:
            return
        self._ocupar(True)

        def trabalho():
            try:
                r = fn()
            except ERROS as e:
                GLib.idle_add(self._fim, None, str(e) or type(e).__name__, ok, msg, recarregar_se_falhar, recarga)
            except Exception:
                traceback.print_exc()
                GLib.idle_add(self._fim, None, "Erro inesperado. Veja o terminal.", ok, msg, recarregar_se_falhar, recarga)
            else:
                GLib.idle_add(self._fim, r, None, ok, msg, recarregar_se_falhar, recarga)
        threading.Thread(target=trabalho, name="painel-prox2", daemon=True).start()

    def _fim(self, r, erro, ok, msg, recarregar_se_falhar=False, recarga=None):
        self._ocupar(False)
        if erro:
            self._toast(erro)
            if recarregar_se_falhar:
                self.recarregar = True
                self.recarga_ok = recarga
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
        self._desenhar_macros()
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
        self.tit_botoes.set_label("Botões de: " + v["nome"])
        self.est_btn = [[dict(a) for a in v["botoes"]], [dict(a) for a in v["gshift"]]]
        self.ini_btn = [[formulario.limpa_acao(a) for a in c] for c in self.est_btn]
        self._desenhar_botoes()

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
            (formulario.alterado(self.inicial, self._ler_form()) or self._botoes_alterados())

    def _botoes_alterados(self):
        return self.est_btn is not None and \
            [[formulario.limpa_acao(a) for a in c] for c in self.est_btn] != self.ini_btn

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
        if self.ini_btn is None or self.est_btn is None:
            return
        try:
            args = formulario.argumentos(self.inicial, self._ler_form())
            args.update(formulario.argumentos_botoes(self.ini_btn, self.est_btn, self.dados["macros"]))
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


    # botões

    def _dropdown(self, pares, valor, ao_mudar):
        """Lista de (valor, texto); ao_mudar(valor) só dispara por ação do usuário."""
        pares = list(pares)
        if valor not in [v for v, _ in pares]:
            pares.append((valor, f"Código {valor}"))
        dd = Gtk.DropDown(model=Gtk.StringList.new([t for _, t in pares]))
        dd.set_selected([v for v, _ in pares].index(valor))
        dd.connect("notify::selected", lambda d, _p: ao_mudar(pares[d.get_selected()][0]))
        return dd

    def _caixa_tecla(self, tecla, ao_mudar):
        """Botão que captura a próxima tecla: keycode X11 menos 8 = evdev."""
        nome = lambda: teclas.nome_tecla(tecla) if tecla else "Clique e tecle"
        b = Gtk.Button(label=nome())
        ctl = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        foco = Gtk.EventControllerFocus()
        estado = {"cap": False}

        def clicou(_b):
            estado["cap"] = True
            b.set_label("Pressione...")
            b.grab_focus()

        def tecla_pressionada(_c, _kv, keycode, _st):
            nonlocal tecla
            if not estado["cap"]:
                return False
            uso = teclas.evdev_para_hid(keycode - 8)
            if uso is None:
                b.set_label("Tecla não suportada")
                return True
            tecla = uso
            estado["cap"] = False
            b.set_label(nome())
            ao_mudar(uso)
            return True

        def saiu(_c):
            estado["cap"] = False
            b.set_label(nome())
        b.connect("clicked", clicou)
        ctl.connect("key-pressed", tecla_pressionada)
        foco.connect("leave", saiu)
        b.add_controller(ctl)
        b.add_controller(foco)
        return b

    def _caixas_mod(self, mod, ao_mudar):
        caixa = Gtk.Box(spacing=8)
        estado = {"mod": mod}
        for bit, nome in teclas.MODS:
            c = Gtk.CheckButton(label=nome, active=bool(mod & bit))

            def mudou(chk, bit=bit):
                estado["mod"] = estado["mod"] | bit if chk.get_active() else estado["mod"] & ~bit
                ao_mudar(estado["mod"])
            c.connect("toggled", mudou)
            caixa.append(c)
        return caixa

    def _limpar(self, caixa):
        while (c := caixa.get_first_child()) is not None:
            caixa.remove(c)

    def _desenhar_botoes(self):
        self._limpar(self.caixa_botoes)
        self.linhas_btn = {}
        for cam, titulo in ((0, "Camada normal"), (1, "G-Shift")):
            self.caixa_botoes.append(rotulo(titulo, "suave", margin_top=8 if cam else 0))
            for i, a in enumerate(self.est_btn[cam]):
                self.caixa_botoes.append(self._linha_botao(cam, i, a))
        self._marcar_linhas()

    def _novo_tipo(self, cam, i, tipo):
        macros = [m for m in self.dados["macros"] if m["estado"] == "ok"]
        antes = self.est_btn[cam][i]
        nova = {"clique": {"tipo": "clique", "botao": "esquerdo"}, "tecla": {"tipo": "tecla", "mod": 0, "tecla": 4},
                "midia": {"tipo": "midia", "codigo": MIDIAS[0][0]},
                "especial": {"tipo": "especial", "codigo": "ciclo_dpi", "testado": True},
                "desligado": {"tipo": "desligado"},
                "macro": {"tipo": "macro", "sec": macros[0]["sec"] if macros else acoes.SEC_MACRO_MIN, "offset": 0}}[tipo]
        self.est_btn[cam][i] = nova
        self._desenhar_botoes()
        if tipo == "macro" and not macros:
            self._abrir_macro(None, (cam, i, antes))

    def _linha_botao(self, cam, i, a):
        linha = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, min_children_per_line=1, max_children_per_line=5,
                            column_spacing=8, row_spacing=4)
        self.linhas_btn[(cam, i)] = linha
        pega = Gtk.GestureClick(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        pega.connect("pressed", lambda *_: self._selecionar(i))  # não reivindica: os dropdowns seguem funcionando
        linha.add_controller(pega)
        foco = Gtk.EventControllerFocus()
        foco.connect("notify::contains-focus", lambda c, _p: c.props.contains_focus and self._selecionar(i))
        linha.add_controller(foco)
        linha.append(rotulo(formulario.NOMES_BOTOES[i], "suave", width_chars=8))
        tipos = TIPOS + ([("bruto", "Bruto")] if a["tipo"] == "bruto" else [])
        t = self._dropdown(tipos, a["tipo"], lambda v: v != a["tipo"] and self._novo_tipo(cam, i, v))
        t.set_tooltip_text(f"Tipo de {formulario.NOMES_BOTOES[i]}")
        linha.append(t)
        if a["tipo"] == "clique":
            linha.append(self._dropdown(CLIQUES, a["botao"], lambda v: a.update(botao=v)))
        elif a["tipo"] == "tecla":
            linha.append(self._caixa_tecla(a["tecla"], lambda u: a.update(tecla=u)))
            linha.append(self._caixas_mod(a["mod"], lambda m: a.update(mod=m)))
        elif a["tipo"] == "midia":
            linha.append(self._dropdown(MIDIAS, a["codigo"], lambda v: a.update(codigo=v)))
        elif a["tipo"] == "especial":
            def esp(v):
                a.update(codigo=v, testado=v in acoes.ESPECIAIS_TESTADOS)
                self._desenhar_botoes()
            linha.append(self._dropdown([(v, n + ("" if v in acoes.ESPECIAIS_TESTADOS else " (não testado)"))
                                         for v, n in ESPECIAIS], a["codigo"], esp))
        elif a["tipo"] == "macro":
            ms = [(m["sec"], f"Macro {m['sec']}" + ("" if m["estado"] == "ok" else f" ({ESTADOS_MACRO[m['estado']].lower()})"))
                  for m in self.dados["macros"] if m["estado"] == "ok" or m["sec"] == a["sec"]]

            def mac(v):
                a.update(sec=v, offset=0)
                a.pop("aviso", None)
                a.pop("macro_estado", None)
                self._desenhar_botoes()
            linha.append(self._dropdown(ms, a["sec"], mac))
            n = Gtk.Button(label="Nova macro...")
            n.add_css_class("acao")
            n.connect("clicked", lambda _b: self._abrir_macro(None, (cam, i, dict(a))))
            linha.append(n)
        elif a["tipo"] == "bruto":
            linha.append(rotulo(a["hex"]))
        if a.get("aviso"):
            linha.append(rotulo(a["aviso"], "aviso-vaga", wrap=True))
        return linha

    # desenho do mouse

    def _pixbuf_svg(self, estilo, w, h):
        """Rasteriza o SVG com o estilo injetado, ajustado em w x h sem deformar."""
        if self._svg is None:
            try:
                with open(SVG_MOUSE, encoding="utf-8") as f:
                    self._svg = f.read()
            except OSError:
                self._svg = ""
        m = re.search(r"<svg[^>]*>", self._svg)
        if m is None:
            return None
        texto = self._svg[:m.end()] + f"<style>{estilo}</style>" + self._svg[m.end():]
        loader = GdkPixbuf.PixbufLoader.new_with_type("svg")

        def ajustar(l, nw, nh):
            e = min(w / nw, h / nh)
            l.set_size(max(1, round(nw * e)), max(1, round(nh * e)))
        loader.connect("size-prepared", ajustar)
        loader.write(texto.encode("utf-8"))
        loader.close()
        return loader.get_pixbuf()

    @staticmethod
    def _hex(c):
        return "#%02x%02x%02x" % tuple(round(max(0, min(1, v)) * 255) for v in (c.red, c.green, c.blue))

    def _render_mouse(self):
        w = self.pic.get_width() or 480
        h = self.pic.get_height() or ALTURA_MOUSE
        esc = self.get_scale_factor()
        fg = self._hex(self.get_color())
        ac = self._hex(Adw.StyleManager.get_default().get_accent_color_rgba())
        estilo = f"svg{{color:{fg}}}"
        if self.btn_sel is not None:
            estilo += f"#{ORDEM[self.btn_sel]}{{fill:{ac};fill-opacity:0.25;stroke:{ac};stroke-width:3}}"
        for r in {self.btn_press, "meio" if self._roda else None} - {None}:
            estilo += f"#{r}{{fill:{ac};fill-opacity:1}}"
        pb = self._pixbuf_svg(estilo, w * esc, h * esc)
        if self._dim != (w, h, esc):
            self._mascara = None
        self._dim = (w, h, esc)
        self.pic.set_paintable(Gdk.Texture.new_for_pixbuf(pb) if pb else None)

    def _regiao_em(self, x, y):
        """Id da região sob (x, y) do widget, lido de uma máscara de cores renderizada do próprio SVG."""
        w, h = self.pic.get_width(), self.pic.get_height()
        if w <= 0 or h <= 0:
            return None
        if self._mascara is None or self._dim[:2] != (w, h):
            self._render_mouse()
        if self._mascara is None:
            estilo = "svg *{fill:none;stroke:none}" + "".join(
                f"#{r}{{fill:rgb({(k + 1) * 40},0,0);fill-opacity:1;shape-rendering:crispEdges}}"
                for k, r in enumerate(ORDEM))
            self._mascara = self._pixbuf_svg(estilo, w * self._dim[2], h * self._dim[2])
        mp = self._mascara
        if mp is None:
            return None
        mw, mh = mp.get_width(), mp.get_height()
        e = min(w / mw, h / mh)  # CONTAIN: a imagem cabe inteira, centralizada
        iw, ih = mw * e, mh * e
        px = int((x - (w - iw) / 2) / e)
        py = int((y - (h - ih) / 2) / e)
        if not (0 <= px < mw and 0 <= py < mh):
            return None
        d, n = mp.get_pixels(), mp.get_n_channels()
        i = py * mp.get_rowstride() + px * n
        if n == 4 and d[i + 3] < 128:
            return None
        k = round(d[i] / 40) - 1
        return ORDEM[k] if 0 <= k < len(ORDEM) else None

    def _selecionar(self, i):
        if i == self.btn_sel:
            return
        self.btn_sel = i
        self._marcar_linhas()
        self._render_mouse()

    def _marcar_linhas(self):
        for (_cam, j), linha in self.linhas_btn.items():
            if j == self.btn_sel:
                linha.add_css_class("sel")
            else:
                linha.remove_css_class("sel")

    def _mouse_press(self, g, _n, x, y):
        b = g.get_current_button()
        reg = BOTAO_GTK.get(b)
        if reg is None:
            return
        self.btn_press = reg
        if b == 1:
            sob = self._regiao_em(x, y)
            if sob:
                self.btn_sel = None  # força a atualização mesmo repetindo a seleção
                self._selecionar(ORDEM.index(sob))
        self._render_mouse()

    def _mouse_solta(self, *_a):
        if self.btn_press is not None:
            self.btn_press = None
            self._render_mouse()

    def _mouse_evento(self, _c, ev):
        # nesta versão do PyGObject o sinal entrega o evento como None
        ev = ev or _c.get_current_event()
        if ev is None:
            return False
        tipo = ev.get_event_type()
        if tipo in (Gdk.EventType.BUTTON_PRESS, Gdk.EventType.BUTTON_RELEASE):
            b = ev.get_button()
            if b not in (8, 9):
                return False
            # consome 8/9 (não troca de aba) e acende o desenho aqui, pois o gesto não os recebe
            self.btn_press = BOTAO_GTK[b] if tipo == Gdk.EventType.BUTTON_PRESS else None
            self._render_mouse()
            return True
        return False

    def _mouse_roda(self, _c, _dx, _dy):
        self._roda = True
        if self._roda_id:
            GLib.source_remove(self._roda_id)
        self._roda_id = GLib.timeout_add(150, self._fim_roda)
        self._render_mouse()
        return True

    def _fim_roda(self):
        self._roda = False
        self._roda_id = 0
        self._render_mouse()
        return GLib.SOURCE_REMOVE

    # macros

    def _resumo(self, passos):
        ap = [teclas.rotulo_tecla(p["mod"], p["tecla"]) for p in passos if p["tipo"] == "aperta"]
        es = [p["ms"] for p in passos if p["tipo"] == "espera"]
        if not passos:
            return "(vazia)"
        if es and all(x == es[0] for x in es) and len(ap) == sum(1 for p in passos if p["tipo"] == "solta"):
            return " ".join(ap) + f" (espera {es[0]} ms)"
        return ", ".join(teclas.rotulo_tecla(p["mod"], p["tecla"]) if p["tipo"] == "aperta" else f"espera {p['ms']} ms"
                         for p in passos if p["tipo"] != "solta")

    def _desenhar_macros(self):
        self._limpar(self.lista_macros)
        nomes = dict(CLIQUES)
        for m in self.dados["macros"]:
            usos = [f"Vaga {u['vaga']}, {'G-Shift' if u['camada'] == 'gshift' else 'normal'}, {nomes.get(u['botao'], u['botao'])}"
                    for u in m["usada_por"]]
            cart = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            cart.add_css_class("vidro")
            cart.append(rotulo(f"Macro {m['sec']} ({ESTADOS_MACRO.get(m['estado'], m['estado'])})", "nome", wrap=True))
            if m["estado"] == "ok":
                cart.append(rotulo(self._resumo(m["passos"]), "suave", wrap=True))
            cart.append(rotulo("Usada por: " + "; ".join(usos) if usos else "Não usada", "suave", wrap=True))
            bs = Gtk.Box(spacing=8, margin_top=6)
            ed = botao("Editar")
            ed.connect("clicked", lambda _b, m=m: self._abrir_macro(m, None))
            ap = botao("Apagar", "perigo")
            ap.set_sensitive(not usos and m["estado"] != "vazia")
            ap.set_tooltip_text("Em uso: tire a macro dos botões antes de apagar." if usos
                                else "Setor já vazio." if m["estado"] == "vazia" else "Apagar a macro")
            ap.connect("clicked", lambda _b, m=m: self._apagar_macro(m["sec"]))
            bs.append(ed)
            bs.append(ap)
            cart.append(bs)
            self.lista_macros.append(cart)

    def _apagar_macro(self, sec):
        def go():
            p = self.painel
            self._rodar(lambda: (p.apagar_macro(sec), p.listar())[1], self._carregou_macro, "Macro apagada",
                        recarregar_se_falhar=True, recarga=self._carregou_macro)
        self._confirmar(f"Apagar a macro {sec}?", "O setor volta a ficar vazio. Há backup para desfazer.", "Apagar", go)

    def _carregou_macro(self, dados):
        """Atualiza a lista de macros e as linhas de botão, sem perder o que está em edição."""
        self.dados = dados
        self._desenhar_macros()
        if self.est_btn is not None:
            self._desenhar_botoes()

    def _abrir_macro(self, m, para):
        ok = m is not None and m["estado"] == "ok"
        alvo = self.est_btn[para[0]][para[1]] if para and self.est_btn is not None else None
        self.med = {"sec": m["sec"] if m else None, "modo": "passos", "passos": [dict(p) for p in m["passos"]] if ok else [],
                    "texto": "", "espera": 30, "para": para, "vaga": self.sel, "alvo": alvo}
        self._desenhar_editor_macro()
        self.pilha.set_visible_child_name("macros")

    def _desenhar_editor_macro(self):
        e = self.editor_macro
        self._limpar(e)
        med = self.med
        e.set_visible(med is not None)
        if med is None:
            return
        e.append(rotulo("Nova macro" if med["sec"] is None else f"Editando macro {med['sec']}", "titulo-vaga"))
        modo = self._dropdown([("passos", "Passos"), ("texto", "Texto")], med["modo"], self._modo_macro)
        modo.set_halign(Gtk.Align.START)
        e.append(modo)
        if med["modo"] == "texto":
            ent = Gtk.Entry(text=med["texto"])
            ent.connect("changed", lambda w: med.update(texto=w.get_text()))
            esp = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=med["espera"], lower=1, upper=65535, step_increment=10,
                                                           page_increment=100), numeric=True, halign=Gtk.Align.START)
            esp.connect("value-changed", lambda w: med.update(espera=w.get_value_as_int()))
            e.append(ent)
            e.append(rotulo("Aceita só letras, números e espaço (sem acentos).", "suave", wrap=True))
            e.append(rotulo("Espera entre teclas (ms)", "suave"))
            e.append(esp)
        else:
            for i, p in enumerate(med["passos"]):
                e.append(self._linha_passo(p, i))
            bar = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, min_children_per_line=1, max_children_per_line=3,
                              column_spacing=8, row_spacing=6, margin_top=6)
            for t, tx in (("aperta", "Adicionar aperta"), ("solta", "Adicionar solta"), ("espera", "Adicionar espera")):
                b = botao(tx)
                b.connect("clicked", lambda _b, t=t: self._add_passo(t))
                bar.append(b)
            e.append(bar)
        fim = Gtk.Box(spacing=8, margin_top=10)
        salvar = botao("Salvar macro", "prim")
        salvar.connect("clicked", self._salvar_macro)
        canc = botao("Cancelar")
        canc.connect("clicked", self._cancelar_macro)
        fim.append(salvar)
        fim.append(canc)
        e.append(fim)

    def _modo_macro(self, v):
        if self.med and v != self.med["modo"]:
            self.med["modo"] = v
            self._desenhar_editor_macro()

    def _add_passo(self, t):
        self.med["passos"].append({"tipo": t, "ms": 50} if t == "espera" else {"tipo": t, "mod": 0, "tecla": 4})
        self._desenhar_editor_macro()

    def _linha_passo(self, p, i):
        passos = self.med["passos"]
        linha = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, min_children_per_line=1, max_children_per_line=6,
                            column_spacing=8, row_spacing=4)

        def tipo(v):
            if v != p["tipo"]:
                passos[i] = {"tipo": "espera", "ms": 50} if v == "espera" else {"tipo": v, "mod": p.get("mod", 0), "tecla": p.get("tecla", 4)}
                self._desenhar_editor_macro()
        linha.append(self._dropdown(PASSOS, p["tipo"], tipo))
        if p["tipo"] == "espera":
            sp = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=p["ms"], lower=1, upper=65535, step_increment=10,
                                                          page_increment=100), numeric=True)
            sp.connect("value-changed", lambda w: p.update(ms=w.get_value_as_int()))
            linha.append(sp)
        else:
            linha.append(self._caixa_tecla(p["tecla"], lambda u: p.update(tecla=u)))
            linha.append(self._caixas_mod(p["mod"], lambda m: p.update(mod=m)))

        def mover(d):
            j = i + d
            if 0 <= j < len(passos):
                passos[i], passos[j] = passos[j], passos[i]
                self._desenhar_editor_macro()

        def remover(_b):
            del passos[i]
            self._desenhar_editor_macro()
        for tx, fn in (("Subir", lambda _b: mover(-1)), ("Descer", lambda _b: mover(1)), ("Remover", remover)):
            b = botao(tx)
            b.connect("clicked", fn)
            linha.append(b)
        return linha

    def _destino_macro(self, med):
        """O destino só vale se a vaga e o botão continuam como estavam ao abrir o editor."""
        para = med["para"]
        if para and self.est_btn is not None and self.sel == med["vaga"] and self.est_btn[para[0]][para[1]] is med["alvo"]:
            return para
        return None

    def _cancelar_macro(self, _b):
        para = self._destino_macro(self.med)
        if para:
            cam, i, antes = para
            self.est_btn[cam][i] = antes
            self._desenhar_botoes()
        self.med = None
        self._desenhar_editor_macro()

    def _salvar_macro(self, _b):
        med, p = self.med, self.painel
        try:
            if med["modo"] == "texto":
                if not med["texto"]:
                    raise ValueError("Digite o texto da macro.")
                passos = acoes.texto_para_passos(med["texto"], med["espera"])
            else:
                if not med["passos"]:
                    raise ValueError("Adicione ao menos um passo.")
                passos = [{"tipo": "espera", "ms": q["ms"]} if q["tipo"] == "espera"
                          else {"tipo": q["tipo"], "mod": q["mod"], "tecla": q["tecla"]} for q in med["passos"]]
            acoes.montar_macro(passos)  # valida antes de gastar uma gravação
        except ValueError as e:
            self._toast(str(e))
            return
        sec = med["sec"]

        def trabalho():
            s = p.gravar_macro(sec, passos)
            return s, p.listar()

        def fim(r):
            s, dados = r
            self.med = None
            self._desenhar_editor_macro()
            self._carregou_macro(dados)
            para = self._destino_macro(med)
            if para:
                self.est_btn[para[0]][para[1]] = {"tipo": "macro", "sec": s, "offset": 0}
                self._desenhar_botoes()
        self._rodar(trabalho, fim, "Gravado e verificado", recarregar_se_falhar=True,
                    recarga=self._carregou_macro)
