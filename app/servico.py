"""Serviço em segundo plano: dono do Mouse em modo leitor. Callbacks da UI sempre via GLib.idle_add."""
import os
import threading
import time
import traceback

from gi.repository import GLib

import bateria as bat
import caminhos
import prox2

INTERVALO_REABRIR = 5
INTERVALO_BATERIA = 300
PASTA_DADOS = caminhos.pasta_painel()


class Servico:
    def __init__(self, simular=None, simular_carga=False, mouse_falso=None, pasta_dados=None, backup=None):
        self.info = None
        self.conectado = False
        self.ultima = None
        self.alertas = bat.Alertas()
        self._ouvintes = []  # fn(servico, avisos)
        self._mouse = None
        self._parar = threading.Event()
        self._ler = threading.Event()
        self._simular = simular
        self._carga = simular_carga
        self._thread = None
        self._falso = mouse_falso
        self.pasta_dados = pasta_dados or PASTA_DADOS
        self.backup = backup or prox2.BACKUP_PADRAO

    @property
    def mouse(self):
        """Mouse para o Painel, ou None se desconectado. Chamadas ao Mouse devem rodar fora da thread principal."""
        if not self.conectado:
            return None
        return self._falso or self._mouse

    def ao_mudar(self, fn):
        self._ouvintes.append(fn)

    def iniciar(self):
        alvo = self._laco_simulado if self._simular is not None else self._laco
        self._thread = threading.Thread(target=alvo, name="servico-prox2", daemon=True)
        self._thread.start()

    def parar(self):
        self._parar.set()
        self._ler.set()
        m, self._mouse = self._mouse, None
        if m is not None:
            # fecha fora da thread principal para não travar o encerramento
            threading.Thread(target=m.fechar, name="fechar-prox2", daemon=True).start()

    def _publicar(self, info, conectado):
        GLib.idle_add(self._aplicar, info, conectado)

    def _aplicar(self, info, conectado):
        # Alertas e estado só mudam na thread principal
        avisos = self.alertas.atualizar(info) if info is not None else []
        if info is not None:
            self.ultima = time.time()
            self.info = info
        self.conectado = conectado
        for fn in list(self._ouvintes):
            try:
                fn(self, avisos)
            except Exception:
                traceback.print_exc()
        return False

    def _laco_simulado(self):
        n = self._simular
        while not self._parar.is_set():
            info = {"soc": max(n, 0), "nivel": "bom", "carregando": self._carga,
                    "estado_carga": "carregando" if self._carga else "descarregando",
                    "energia_externa": "com_fio" if self._carga else "nenhuma"}
            self._publicar(info, True)
            n -= 1
            if n < 0:
                break
            self._parar.wait(3)

    def _abrir(self):
        m = prox2.Mouse(leitor=True)
        m.ao_bateria(lambda i: self._publicar(i, True))
        m.ao_conexao(lambda ok: (self._ler.set() if ok else self._publicar(None, False)))
        if self._parar.is_set():
            threading.Thread(target=m.fechar, name="fechar-prox2", daemon=True).start()
            return
        self._mouse = m

    def _laco(self):
        try:
            while not self._parar.is_set() and self._mouse is None:
                try:
                    self._abrir()
                except (prox2.ErroMouse, OSError):
                    self._mouse = None
                    self._publicar(None, False)
                    self._parar.wait(INTERVALO_REABRIR)
            self._ler.set()
            while not self._parar.is_set():
                self._ler.wait(INTERVALO_BATERIA)
                self._ler.clear()
                m = self._mouse
                if self._parar.is_set() or m is None:
                    break
                try:
                    self._publicar(m.bateria(), True)
                except (prox2.ErroMouse, OSError):
                    self._publicar(None, False)
        except Exception:
            traceback.print_exc()
