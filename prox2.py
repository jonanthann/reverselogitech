#!/usr/bin/env python3
"""Lê e troca o polling rate gravado nos perfis (memória interna) do Logitech
PRO X 2 Superlight, via HID++ 2.0 em hidraw. Só stdlib, sem sudo.

Uso:
  prox2.py status
  prox2.py bateria [--seguir]
  prox2.py rate <hz> [--perfil N ...]   (N = número do setor, 1..5)
  prox2.py dpi <n> [--perfil N ...]
  prox2.py backup <arquivo.json>
  prox2.py restaurar <arquivo.json> [--sim]
"""
import argparse, contextlib, errno, fcntl, json, os, queue, select, struct, sys, tempfile, threading, time

import caminhos

SWID = 0x0A
RATES = [125, 250, 500, 1000, 2000, 4000, 8000]
# faixas de DPI do sensor 0 (feature 0x2202): (início, fim, passo)
DPI_FAIXAS = [(100, 200, 1), (200, 500, 2), (500, 1000, 5), (1000, 2000, 10), (2000, 5000, 20),
              (5000, 10000, 50), (10000, 20000, 100), (20000, 32000, 125), (32000, 44000, 200)]
BACKUP_PADRAO = caminhos.arquivo_backup()


def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return crc


def crc_ok(setor):
    return len(setor) > 2 and struct.unpack(">H", setor[-2:])[0] == crc16(setor[:-2])


def com_crc(setor):
    b = bytearray(setor)
    b[-2:] = struct.pack(">H", crc16(b[:-2]))
    return bytes(b)


class ErroMouse(IOError):
    """Herda de IOError para os rollbacks e os except (TimeoutError, IOError) cobrirem o mouse."""


class TravaOcupada(ErroMouse):
    """Outro processo segura o flock de gravação."""


class MouseInalcancavel(ErroMouse):
    """Mouse desligado, fora de alcance ou desconectado do receptor."""


def achar_no_hidpp():
    """Acha o hidraw HID++ do receptor 046d:c54d pelo report descriptor."""
    for n in sorted(os.listdir("/sys/class/hidraw")):
        p = f"/sys/class/hidraw/{n}/device"
        try:
            if "046D:0000C54D" not in open(f"{p}/uevent").read().upper():
                continue
            desc = open(f"{p}/report_descriptor", "rb").read()
        except OSError:
            continue
        if desc.startswith(b"\x05\x01\x09\x02"):
            continue  # nó do mouse
        if b"\x85\x11" in desc:
            return f"/dev/{n}"
    raise ErroMouse("Receptor HID++ não encontrado (mouse ligado?).")


class Mouse:
    def __init__(self, idx=1, caminho=None, fd=None, leitor=False, abrir=None,
                 arq_trava=None, espera_trava=5.0, intervalo_reabrir=5.0):
        """leitor=True inicia a thread leitora (eventos + reconexão). abrir: fábrica de fd para
        reabrir após desconexão (padrão: achar_no_hidpp). arq_trava: arquivo do flock de gravação."""
        self.idx = idx
        self._abrir = abrir or self._abrir_padrao
        self._proprio = fd is None
        if fd is None:
            caminho = caminho or achar_no_hidpp()
            fd = os.open(caminho, os.O_RDWR)
        self.caminho = caminho
        self.fd = fd
        self._arq_trava = arq_trava
        self._espera_trava = espera_trava
        self._intervalo_reabrir = intervalo_reabrir
        self._caps_bateria = None
        self.feat = {}
        self._lock = threading.RLock()
        self._prof_trava = 0
        self._fd_trava = None
        self._pend = None
        self._swid = 0
        self._trava_fd = threading.Lock()
        self._thread = None
        self._parar = threading.Event()
        self._conectado = True
        self._cb_evento, self._cb_bateria, self._cb_conexao, self._cb_estado = [], [], [], []
        self._iniciar_features()
        if leitor:
            self.iniciar_leitor()

    def _abrir_padrao(self):
        self.caminho = achar_no_hidpp()
        return os.open(self.caminho, os.O_RDWR)

    def _proximo_swid(self):
        # 1..15, nunca 0 (0 é evento); respostas atrasadas de outra requisição não casam
        self._swid = self._swid % 15 + 1
        return self._swid

    def _carregar_caps_bateria(self):
        import bateria
        f = self.fi(0x1004)
        if f is not None:
            self._caps_bateria = bateria.decodificar_caps(self.req(f, 0))

    def _iniciar_features(self):
        self.feat = {}
        self._caps_bateria = None
        self.op = self.fi(0x8100)
        self.rr = self.fi(0x8061)
        if self.op is None or self.rr is None:
            raise ErroMouse("Mouse sem as features 0x8100/0x8061.")
        self.size = struct.unpack(">H", self.req(self.op, 0)[7:9])[0]

    # callbacks (chamados na thread leitora: não fazer requisições dentro deles)
    def ao_evento(self, fn):
        self._cb_evento.append(fn)

    def ao_bateria(self, fn):
        self._cb_bateria.append(fn)

    def ao_conexao(self, fn):
        self._cb_conexao.append(fn)

    def ao_estado(self, fn):
        self._cb_estado.append(fn)

    @staticmethod
    def _chamar(lista, *args):
        for fn in list(lista):
            try:
                fn(*args)
            except Exception:
                pass

    def iniciar_leitor(self):
        if self._thread is None:
            self._parar.clear()
            self._thread = threading.Thread(target=self._laco, name="leitor-prox2", daemon=True)
            self._thread.start()

    def fechar(self):
        self._parar.set()
        t, self._thread = self._thread, None
        if t is not None and t is not threading.current_thread():
            t.join(5)
        self._fechar_fd()

    def _fechar_fd(self):
        with self._trava_fd:
            fd, self.fd = self.fd, None
        if fd is not None and self._proprio:
            try:
                os.close(fd)
            except OSError:
                pass

    def _eh_leitor(self):
        return self._thread is not None and threading.current_thread() is self._thread

    def _laco(self):
        while not self._parar.is_set():
            fd = self.fd
            if fd is None:
                if self._parar.wait(self._intervalo_reabrir):
                    break
                self._reabrir()
                continue
            try:
                if not select.select([fd], [], [], 0.2)[0]:
                    continue
                d = os.read(fd, 64)
            except (OSError, ValueError):
                d = b""
            if not d:
                self._desconectar()
                continue
            self._classificar(d)

    def _desconectar(self):
        # sem o lock: um solicitante pode estar esperando a resposta com ele seguro
        self._conectado = False
        p = self._pend
        if p:
            p[2].put(MouseInalcancavel("Mouse desconectado."))
        self._fechar_fd()
        self._chamar(self._cb_estado, "desconectado")

    def _reabrir(self):
        with self._lock:
            try:
                fd = self._abrir()
                with self._trava_fd:
                    if self._parar.is_set():  # fechar() já rodou: não deixa fd aberto
                        os.close(fd)
                        return
                    self._proprio = True
                    self.fd = fd
                self._iniciar_features()
                self._carregar_caps_bateria()
            except (ErroMouse, OSError, TimeoutError):
                self._fechar_fd()
                return
            self._conectado = True
        self._chamar(self._cb_estado, "conectado")

    def _classificar(self, d):
        if len(d) < 6 or d[0] not in (0x10, 0x11) or d[1] != self.idx:
            return
        p = self._pend
        if d[2] == 0x8F:  # erro HID++ 1.0: só vale se casar com a requisição pendente
            if p and d[3] == p[0] and d[4] == p[1]:
                p[2].put(MouseInalcancavel("Mouse desligado ou fora de alcance."))
            return
        if d[2] == 0xFF and p and d[3] == p[0] and d[4] == p[1]:
            p[2].put(IOError(f"erro HID++ {d[5]:#x} (fidx={p[0]}, func={p[1] >> 4})"))
            return
        if d[2] == 0x41 and d[0] == 0x10:  # HID++ 1.0: conexão do dispositivo
            self._chamar(self._cb_evento, d)
            self._chamar(self._cb_conexao, not d[4] & 0x40)
            return
        if d[3] & 0x0F:  # resposta: só a da requisição pendente, as atrasadas são descartadas
            if p and d[0] == 0x11 and d[2] == p[0] and d[3] == p[1]:
                p[2].put(d[4:20])
            return
        self._chamar(self._cb_evento, d)
        if d[2] == self.feat.get(0x1004) and d[3] >> 4 == 0:
            import bateria
            info = bateria.decodificar_evento(d, self._caps_bateria)
            if info:
                self._chamar(self._cb_bateria, info)

    @contextlib.contextmanager
    def transacao(self, gravando=False):
        """Segura o lock das requisições; com gravando=True pega também o flock entre processos."""
        with self._lock:
            if gravando and self._prof_trava == 0:
                self._pegar_flock()
            self._prof_trava += gravando
            try:
                yield self
            finally:
                if gravando:
                    self._prof_trava -= 1
                    if self._prof_trava == 0:
                        self._soltar_flock()

    def _caminho_trava(self):
        if self._arq_trava:
            return self._arq_trava
        base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
        return os.path.join(base, "myprox2.lock")

    def _pegar_flock(self):
        fd = os.open(self._caminho_trava(), os.O_RDWR | os.O_CREAT, 0o600)
        fim = time.monotonic() + self._espera_trava
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._fd_trava = fd
                return
            except OSError as e:
                if e.errno not in (errno.EAGAIN, errno.EACCES) or time.monotonic() >= fim:
                    os.close(fd)
                    if e.errno in (errno.EAGAIN, errno.EACCES):
                        raise TravaOcupada("Outro programa (CLI, painel ou app) está gravando no mouse. Tente de novo em instantes.")
                    raise
                time.sleep(0.05)

    def _soltar_flock(self):
        fd, self._fd_trava = self._fd_trava, None
        os.close(fd)  # fechar libera o flock

    def req(self, fidx, func, params=b"", timeout=1.0, retry=True):
        with self._lock:
            for t in range(4 if retry else 1):
                try:
                    return self._req(fidx, func, params, timeout)
                except TimeoutError:
                    if t == 3 or not retry:
                        raise

    def _req(self, fidx, func, params, timeout):
        if self._thread is not None and not self._eh_leitor():
            return self._req_fila(fidx, func, params, timeout)
        return self._req_direto(fidx, func, params, timeout)

    def _pacote(self, fidx, func, params, swid):
        return (bytes([0x11, self.idx, fidx, (func << 4) | swid]) + params).ljust(20, b"\0")

    def _req_fila(self, fidx, func, params, timeout):
        q = queue.Queue()
        swid = self._proximo_swid()
        with self._trava_fd:  # fd capturado e escrito sob a trava: fechar_fd não corre junto
            fd = self.fd
            if not self._conectado or fd is None:
                raise MouseInalcancavel("Mouse desconectado.")
            self._pend = (fidx, (func << 4) | swid, q)
            try:
                os.write(fd, self._pacote(fidx, func, params, swid))
            except OSError as e:
                self._pend = None
                raise MouseInalcancavel(f"Mouse desconectado ({e.strerror}).")
        try:
            try:
                r = q.get(timeout=timeout)
            except queue.Empty:
                raise TimeoutError(f"sem resposta (fidx={fidx}, func={func})")
        finally:
            self._pend = None
        if isinstance(r, Exception):
            raise r
        return r

    def _req_direto(self, fidx, func, params, timeout):
        swid = self._proximo_swid()
        pkt = self._pacote(fidx, func, params, swid)
        with self._trava_fd:
            fd = self.fd
        if fd is None:
            raise MouseInalcancavel("Mouse desconectado.")
        alvo = (func << 4) | swid
        # esvazia respostas atrasadas para não casar com a requisição errada
        while select.select([fd], [], [], 0)[0]:
            os.read(fd, 64)
        os.write(fd, pkt)
        fim = time.monotonic() + timeout
        while True:
            resto = fim - time.monotonic()
            if resto <= 0 or not select.select([fd], [], [], resto)[0]:
                raise TimeoutError(f"sem resposta (fidx={fidx}, func={func})")
            d = os.read(fd, 64)
            if len(d) < 6 or d[1] != self.idx or d[0] not in (0x10, 0x11):
                continue
            if d[2] == 0x8F and d[3] == fidx and d[4] == alvo:
                raise MouseInalcancavel("Mouse desligado ou fora de alcance.")
            if d[2] == 0xFF and d[3] == fidx and d[4] == alvo:
                raise IOError(f"erro HID++ {d[5]:#x} (fidx={fidx}, func={func})")
            if d[0] == 0x11 and d[2] == fidx and d[3] == alvo:
                return d[4:20]

    def fi(self, fid):
        if fid not in self.feat:
            r = self.req(0, 0, struct.pack(">H", fid))
            self.feat[fid] = r[0] or None
        return self.feat[fid]

    def _ler_cru(self, sec):
        out = b""
        while len(out) < self.size:
            o = min(len(out), self.size - 16)
            out = out[:o] + self.req(self.op, 5, struct.pack(">HH", sec, o))
        return out[:self.size]

    def ler_setor(self, sec, crc=True):
        """Lê o setor inteiro; com crc=True relê até 3 vezes se o CRC falhar.
        O setor 0 (diretório) pode não ter CRC: aceita duas leituras iguais."""
        anterior = None
        for _ in range(3):
            d = self._ler_cru(sec)
            if not crc or crc_ok(d) or (sec == 0 and d == anterior):
                return d
            anterior = d
        raise IOError(f"CRC ruim ao ler o setor {sec} (3 tentativas)")

    def gravar_setor(self, sec, data):
        assert len(data) == self.size
        with self.transacao(gravando=True):
            for t in range(2):
                try:
                    self.req(self.op, 6, struct.pack(">HHH", sec, 0, self.size), retry=False)
                    for i in range(0, self.size, 16):
                        self.req(self.op, 7, data[i:i + 16].ljust(16, b"\0"), retry=False)
                    self.req(self.op, 8, retry=False)
                    return
                except (TimeoutError, IOError):
                    if t == 1:
                        raise

    def gravar_verificado(self, sec, data):
        self.gravar_setor(sec, data)
        if self.ler_setor(sec, crc=False) != data:
            raise IOError(f"setor {sec}: releitura diferente do esperado")

    def perfil_ativo(self):
        return struct.unpack(">H", self.req(self.op, 4)[:2])[0]

    def definir_perfil(self, sec):
        self.req(self.op, 3, struct.pack(">H", sec))

    def diretorio(self):
        """Lista de (setor, ativo) do setor 0."""
        d = self.ler_setor(0)
        res = []
        for i in range(0, len(d) - 3, 4):
            sec = struct.unpack(">H", d[i:i + 2])[0]
            if sec == 0xFFFF:
                break
            res.append((sec, bool(d[i + 2])))
        return res

    def taxas_suportadas(self):
        bm = self.req(self.rr, 1)[1]
        return [RATES[i] for i in range(len(RATES)) if bm & (1 << i)]

    def taxa_atual(self):
        return self.req(self.rr, 2)[0]

    def bateria(self):
        """Lê a bateria (feature 0x1004). Devolve o dict de bateria.decodificar_status, ou None sem a feature."""
        import bateria
        f = self.fi(0x1004)
        if f is None:
            return None
        if self._caps_bateria is None:
            self._carregar_caps_bateria()
        return bateria.decodificar_status(self.req(f, 1), self._caps_bateria)

    def nome(self):
        f = self.fi(0x0005)
        if f is None:
            return "?"
        n = self.req(f, 0)[0]
        s = b""
        while len(s) < n:
            parte = self.req(f, 1, bytes([len(s)]))
            s += parte.split(b"\0")[0] if b"\0" in parte else parte
            if b"\0" in parte:
                break
        return s[:n].decode("ascii", "replace")

    def firmware(self):
        f = self.fi(0x0003)
        if f is None:
            return "?"
        n = self.req(f, 0)[0]
        res = []
        for i in range(n):
            r = self.req(f, 1, bytes([i]))
            if r[0] > 3:
                continue
            nome = r[1:4].decode("ascii", "replace")
            res.append(f"{nome} {r[4]:02x}.{r[5]:02x}.{struct.unpack('>H', r[6:8])[0]:04x}")
        return ", ".join(res) or "?"


def hz(i):
    return f"{RATES[i]} Hz" if i < len(RATES) else f"índice {i}?"


def dpis(setor):
    res = []
    for k in range(5):
        o = 4 + k * 5
        x, y = struct.unpack("<HH", setor[o:o + 4])
        if x:
            res.append(str(x) if x == y else f"{x}x{y}")
    return res


def dpi_valido(n):
    return any(lo <= n <= hi and (n - lo) % st == 0 for lo, hi, st in DPI_FAIXAS)


def dpis_proximos(n):
    cand = set()
    for lo, hi, st in DPI_FAIXAS:
        c = min(max(n, lo), hi)
        baixo = lo + (c - lo) // st * st
        cand.update((baixo, min(baixo + st, hi)))
    abaixo = [c for c in cand if c < n]
    acima = [c for c in cand if c > n]
    return ([max(abaixo)] if abaixo else []) + ([min(acima)] if acima else [])


def cmd_status(m, a):
    print("Nome:", m.nome())
    print("Firmware:", m.firmware())
    modo = m.req(m.op, 2)[0]
    print("Modo:", {1: "memória interna", 2: "host"}.get(modo, str(modo)))
    print(f"Perfil ativo (setor): {m.perfil_ativo():#06x}")
    print("Taxa atual:", hz(m.taxa_atual()))
    print("Taxas suportadas:", ", ".join(str(t) for t in m.taxas_suportadas()), "Hz")
    f = m.fi(0x2202)
    if f is not None:
        try:
            r = m.req(f, 5, b"\0")
            print("DPI atual (sensor):", struct.unpack(">H", r[1:3])[0])
        except (TimeoutError, IOError) as e:
            print(f"DPI atual (sensor): não lido ({e})")
    for sec, ativo in m.diretorio():
        s = m.ler_setor(sec)
        linha = f"Perfil setor {sec}: ativo={'sim' if ativo else 'não'}"
        linha += f", polling={hz(s[0])} (byte 0), {hz(s[1])} (byte 1)"
        if s[0] != s[1]:
            linha += " [AVISO: bytes diferentes]"
        linha += f", DPIs={', '.join(dpis(s)) or '-'}, CRC {'ok' if crc_ok(s) else 'RUIM'}"
        print(linha)


def texto_bateria(b):
    soc = f"{b['soc']}% " if b["soc"] is not None else ""
    txt = f"Bateria: {soc}({b['nivel']}), {b['estado_carga'].replace('_', ' ')}"
    ext = {"nenhuma": "sem energia externa", "com_fio": "no cabo", "sem_fio": "em carga sem fio"}
    return f"{txt}, {ext[b['energia_externa']]}" if b["energia_externa"] != "nenhuma" or not b["carregando"] else txt


def cmd_bateria(m, a):
    b = m.bateria()
    if b is None:
        sys.exit("Mouse sem a feature de bateria (0x1004).")
    print(texto_bateria(b), flush=True)
    if not a.seguir:
        return
    m.ao_bateria(lambda i: print(texto_bateria(i), flush=True))
    m.ao_conexao(lambda ok: print("Conexão: " + ("estabelecida" if ok else "perdida"), flush=True))
    m.ao_estado(lambda e: print(f"Receptor: {e}", flush=True))
    m.iniciar_leitor()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        m.fechar()


def _gravando(f):
    """Roda o comando inteiro (leitura, gravação e verificação) sob o flock de gravação."""
    def envolto(m, a):
        with m.transacao(gravando=True):
            return f(m, a)
    envolto.__name__ = f.__name__
    return envolto


@_gravando
def cmd_rate(m, a):
    if a.hz not in RATES or a.hz not in m.taxas_suportadas():
        sys.exit(f"Taxa {a.hz} Hz não suportada. Suportadas: {m.taxas_suportadas()}")
    novo = RATES.index(a.hz)
    dire = m.diretorio()
    if a.perfil:
        alvo = []
        for p in a.perfil:
            if p not in [s for s, _ in dire]:
                sys.exit(f"Setor {p} não está no diretório.")
            alvo.append(p)
    else:
        alvo = [s for s, ativo in dire if ativo]
    if not alvo:
        sys.exit("Nenhum perfil alvo.")

    atuais = {s: m.ler_setor(s) for s in alvo}
    for s, d in atuais.items():
        if not crc_ok(d):
            sys.exit(f"CRC ruim no setor {s}, recusando gravar.")

    if not os.path.exists(BACKUP_PADRAO):
        try:
            salvar_backup(m, BACKUP_PADRAO, exclusivo=True)
        except FileExistsError:
            print("Backup já existe, mantido:", BACKUP_PADRAO)
        except Exception as e:
            sys.exit(f"Backup falhou ({e}), nada foi gravado no mouse.")
    else:
        print("Backup já existe, mantido:", BACKUP_PADRAO)

    original = m.perfil_ativo()
    try:
        for s, d in atuais.items():
            if d[0] == novo and d[1] == novo:
                print(f"Setor {s}: já em {a.hz} Hz, pulando.")
                continue
            esperado = bytearray(d)
            esperado[0] = esperado[1] = novo
            esperado = com_crc(esperado)
            try:
                m.gravar_verificado(s, esperado)
            except (TimeoutError, IOError) as e:
                print(f"Setor {s}: falha ao gravar ({e}).")
                regravar_original(m, s, d)
                sys.exit(1)
            m.definir_perfil(s)  # recarrega o perfil gravado
            print(f"Setor {s}: gravado {a.hz} Hz e verificado.")
    finally:
        m.definir_perfil(original)
        time.sleep(0.5)
    print("Taxa atual:", hz(m.taxa_atual()))


@_gravando
def cmd_dpi(m, a):
    if not dpi_valido(a.n):
        sug = ", ".join(map(str, dpis_proximos(a.n)))
        sys.exit(f"DPI {a.n} inválido. Valores válidos mais próximos: {sug}")
    dire = m.diretorio()
    if a.perfil:
        alvo = []
        for p in a.perfil:
            if p not in [s for s, _ in dire]:
                sys.exit(f"Setor {p} não está no diretório.")
            alvo.append(p)
    else:
        alvo = [s for s, ativo in dire if ativo]
    if not alvo:
        sys.exit("Nenhum perfil alvo.")

    atuais = {s: m.ler_setor(s) for s in alvo}
    for s, d in atuais.items():
        if not crc_ok(d):
            sys.exit(f"CRC ruim no setor {s}, recusando gravar.")
        n = sum(1 for k in range(5) if any(d[4 + 5 * k:8 + 5 * k]))
        if n != 1 or not any(d[4:8]):
            sys.exit(f"Setor {s} tem {n} níveis de DPI preenchidos (DPIs={', '.join(dpis(d)) or '-'}). "
                     "Só perfis com exatamente 1 nível são aceitos, pois o índice do nível ativo "
                     "ainda não foi confirmado. Nada foi gravado.")

    if not os.path.exists(BACKUP_PADRAO):
        try:
            salvar_backup(m, BACKUP_PADRAO, exclusivo=True)
        except FileExistsError:
            print("Backup já existe, mantido:", BACKUP_PADRAO)
        except Exception as e:
            sys.exit(f"Backup falhou ({e}), nada foi gravado no mouse.")
    else:
        print("Backup já existe, mantido:", BACKUP_PADRAO)

    original = m.perfil_ativo()
    try:
        for s, d in atuais.items():
            esperado = bytearray(d)
            esperado[4:8] = struct.pack("<HH", a.n, a.n)  # byte 8 (LOD) preservado
            esperado = com_crc(esperado)
            if esperado == d:
                print(f"Setor {s}: já em {a.n} DPI, pulando.")
                continue
            try:
                m.gravar_verificado(s, esperado)
            except (TimeoutError, IOError) as e:
                print(f"Setor {s}: falha ao gravar ({e}).")
                regravar_original(m, s, d)
                sys.exit(1)
            m.definir_perfil(s)  # recarrega o perfil gravado
            print(f"Setor {s}: gravado {a.n} DPI e verificado.")
    finally:
        m.definir_perfil(original)
        time.sleep(0.5)


def regravar_original(m, sec, original):
    """Tenta uma vez regravar o conteúdo original do setor."""
    if sec >= 6 and not crc_ok(original):
        original = com_crc(b"\xff" * len(original))  # o mouse recusa setor de macro sem CRC
    try:
        m.gravar_verificado(sec, original)
        print(f"Setor {sec}: conteúdo original regravado.")
    except (TimeoutError, IOError) as e:
        print(f"Setor {sec} ficou RUIM ({e}). Para restaurar rode:")
        print("  python3 prox2.py restaurar prox2_backup_perfis.json")


def salvar_backup(m, caminho, exclusivo=False):
    # leituras com CRC conferido; grava em temporário e publica de uma vez
    # setores 6..15 (macros) podem estar vazios sem CRC, então sem conferência
    bk = {f"{s:#06x}": m.ler_setor(s, crc=s < 6).hex() for s in range(0, 16)}
    os.makedirs(os.path.dirname(os.path.abspath(caminho)), exist_ok=True)
    tmp = caminho + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(bk, f, indent=1)
        if exclusivo:
            os.link(tmp, caminho)  # falha se já existir, nunca sobrescreve
            os.unlink(tmp)
        else:
            os.replace(tmp, caminho)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    print("Backup salvo em", caminho)


def cmd_backup(m, a):
    salvar_backup(m, a.arquivo)


def cmd_restaurar(m, a):
    with open(a.arquivo) as f:
        bk = {int(k, 16): bytes.fromhex(v) for k, v in json.load(f).items()}
    difer, antes, pulados = [], {}, []
    for sec in range(1, 16):
        if sec not in bk:
            continue
        if len(bk[sec]) != m.size:
            sys.exit(f"Setor {sec} do arquivo inválido (tamanho). Nada foi gravado.")
        if sec > 5 and bk[sec] == b"\xff" * len(bk[sec]):
            bk[sec] = com_crc(bk[sec])  # macro vazia sem CRC volta como vazia com CRC
        if not crc_ok(bk[sec]):
            print(f"Setor {sec} do backup tem CRC inválido, pulado.")
            pulados.append(sec)
            continue
        antes[sec] = m.ler_setor(sec, crc=False)
        if antes[sec] != bk[sec]:
            difer.append(sec)
    if not antes:
        print("Nenhum setor válido no arquivo, nada foi gravado.")
        return
    if not difer:
        print("Mouse já igual ao arquivo nos setores válidos, nada a fazer.")
        avisar_pulados(pulados)
        return
    print("Setores que serão regravados:", ", ".join(map(str, difer)))
    if not a.sim and input("Continuar? (s/N) ").strip().lower() != "s":
        print("Cancelado.")
        return
    with m.transacao(gravando=True):
        original = m.perfil_ativo()
        try:
            for sec in difer:
                try:
                    m.gravar_verificado(sec, bk[sec])
                except (TimeoutError, IOError) as e:
                    print(f"Setor {sec}: falha ao gravar ({e}).")
                    regravar_original(m, sec, antes[sec])
                    sys.exit(1)
                if sec <= 5:
                    m.definir_perfil(sec)
                print(f"Setor {sec}: restaurado e verificado.")
        finally:
            m.definir_perfil(original)
            time.sleep(0.5)
    print("Taxa atual:", hz(m.taxa_atual()))
    avisar_pulados(pulados)


def avisar_pulados(pulados):
    if pulados:
        print(f"Atenção: setores {', '.join(map(str, pulados))} NÃO foram restaurados, o backup não tem "
              "cópia válida deles. Use \"Restaurar\" no painel para voltar essas vagas ao padrão de fábrica.")


def cmd_painel(m, a):
    import webbrowser
    from painel_core import Painel
    from painel_web import criar_servidor, servir
    pasta = caminhos.pasta_painel()
    srv, url = criar_servidor(Painel(m, pasta), a.porta)
    print("Painel em:", url, flush=True)
    print("Ctrl+C para encerrar (fecha sozinho 120 s depois de fechar a página).")
    if not a.sem_navegador:
        webbrowser.open(url)
    servir(srv)


def main():
    caminhos.migrar(os.path.dirname(os.path.abspath(__file__)))
    p = argparse.ArgumentParser(description="Polling rate do PRO X 2 Superlight (perfis onboard)")
    sp = p.add_subparsers(dest="cmd", required=True)
    sp.add_parser("status").set_defaults(f=cmd_status)
    bt = sp.add_parser("bateria")
    bt.add_argument("--seguir", action="store_true", help="continua imprimindo eventos até Ctrl+C")
    bt.set_defaults(f=cmd_bateria)
    r = sp.add_parser("rate")
    r.add_argument("hz", type=int)
    r.add_argument("--perfil", type=int, nargs="+", help="setores (1..5); padrão: perfis ativos")
    r.set_defaults(f=cmd_rate)
    d = sp.add_parser("dpi")
    d.add_argument("n", type=int)
    d.add_argument("--perfil", type=int, nargs="+", help="setores (1..5); padrão: perfis ativos")
    d.set_defaults(f=cmd_dpi)
    b = sp.add_parser("backup")
    b.add_argument("arquivo")
    b.set_defaults(f=cmd_backup)
    s = sp.add_parser("restaurar")
    s.add_argument("arquivo")
    s.add_argument("--sim", action="store_true", help="não pedir confirmação")
    s.set_defaults(f=cmd_restaurar)
    w = sp.add_parser("painel", help="abre o painel web local")
    w.add_argument("--porta", type=int, default=0, help="porta local (0 = livre)")
    w.add_argument("--sem-navegador", action="store_true", help="não abrir o navegador")
    w.set_defaults(f=cmd_painel)
    a = p.parse_args()
    try:
        m = Mouse()
    except ErroMouse as e:
        sys.exit(str(e))
    try:
        a.f(m, a)
    except (ErroMouse, TimeoutError) as e:
        sys.exit(f"Erro: {e}")


if __name__ == "__main__":
    main()
