#!/usr/bin/env python3
"""Lê e troca o polling rate gravado nos perfis (memória interna) do Logitech
PRO X 2 Superlight, via HID++ 2.0 em hidraw. Só stdlib, sem sudo.

Uso:
  prox2.py status
  prox2.py rate <hz> [--perfil N ...]   (N = número do setor, 1..5)
  prox2.py dpi <n> [--perfil N ...]
  prox2.py backup <arquivo.json>
  prox2.py restaurar <arquivo.json> [--sim]
"""
import argparse, json, os, select, struct, sys, time

SWID = 0x0A
RATES = [125, 250, 500, 1000, 2000, 4000, 8000]
# faixas de DPI do sensor 0 (feature 0x2202): (início, fim, passo)
DPI_FAIXAS = [(100, 200, 1), (200, 500, 2), (500, 1000, 5), (1000, 2000, 10), (2000, 5000, 20),
              (5000, 10000, 50), (10000, 20000, 100), (20000, 32000, 125), (32000, 44000, 200)]
BACKUP_PADRAO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prox2_backup_perfis.json")


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
    sys.exit("Receptor HID++ não encontrado (mouse ligado?).")


class Mouse:
    def __init__(self, idx=1):
        self.idx = idx
        self.fd = os.open(achar_no_hidpp(), os.O_RDWR)
        self.feat = {}
        self.op = self.fi(0x8100)
        self.rr = self.fi(0x8061)
        if self.op is None or self.rr is None:
            sys.exit("Mouse sem as features 0x8100/0x8061.")
        self.size = struct.unpack(">H", self.req(self.op, 0)[7:9])[0]

    def req(self, fidx, func, params=b"", timeout=1.0, retry=True):
        for t in range(4 if retry else 1):
            try:
                return self._req(fidx, func, params, timeout)
            except TimeoutError:
                if t == 3 or not retry:
                    raise

    def _req(self, fidx, func, params, timeout):
        pkt = (bytes([0x11, self.idx, fidx, (func << 4) | SWID]) + params).ljust(20, b"\0")
        # esvazia respostas atrasadas para não casar com a requisição errada
        while select.select([self.fd], [], [], 0)[0]:
            os.read(self.fd, 64)
        os.write(self.fd, pkt)
        fim = time.monotonic() + timeout
        while True:
            resto = fim - time.monotonic()
            if resto <= 0 or not select.select([self.fd], [], [], resto)[0]:
                raise TimeoutError(f"sem resposta (fidx={fidx}, func={func})")
            d = os.read(self.fd, 64)
            if len(d) < 6 or d[1] != self.idx:
                continue
            if d[0] in (0x10, 0x11) and d[2] == 0xFF and d[3] == fidx and d[4] == ((func << 4) | SWID):
                raise IOError(f"erro HID++ {d[5]:#x} (fidx={fidx}, func={func})")
            if d[0] == 0x11 and d[2] == fidx and d[3] == ((func << 4) | SWID):
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
    try:
        m.gravar_verificado(sec, original)
        print(f"Setor {sec}: conteúdo original regravado.")
    except (TimeoutError, IOError) as e:
        print(f"Setor {sec} ficou RUIM ({e}). Para restaurar rode:")
        print("  python3 prox2.py restaurar prox2_backup_perfis.json")


def salvar_backup(m, caminho, exclusivo=False):
    # leituras com CRC conferido; grava em temporário e publica de uma vez
    bk = {f"{s:#06x}": m.ler_setor(s).hex() for s in range(0, 6)}
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
    difer, antes = [], {}
    for sec in range(1, 6):
        if sec not in bk:
            continue
        if len(bk[sec]) != m.size or not crc_ok(bk[sec]):
            sys.exit(f"Setor {sec} do arquivo inválido (tamanho ou CRC). Nada foi gravado.")
        antes[sec] = m.ler_setor(sec, crc=False)
        if antes[sec] != bk[sec]:
            difer.append(sec)
    if not difer:
        print("Mouse já igual ao arquivo, nada a fazer.")
        return
    print("Setores que serão regravados:", ", ".join(map(str, difer)))
    if not a.sim and input("Continuar? (s/N) ").strip().lower() != "s":
        print("Cancelado.")
        return
    original = m.perfil_ativo()
    try:
        for sec in difer:
            try:
                m.gravar_verificado(sec, bk[sec])
            except (TimeoutError, IOError) as e:
                print(f"Setor {sec}: falha ao gravar ({e}).")
                regravar_original(m, sec, antes[sec])
                sys.exit(1)
            m.definir_perfil(sec)
            print(f"Setor {sec}: restaurado e verificado.")
    finally:
        m.definir_perfil(original)
        time.sleep(0.5)
    print("Taxa atual:", hz(m.taxa_atual()))


def main():
    p = argparse.ArgumentParser(description="Polling rate do PRO X 2 Superlight (perfis onboard)")
    sp = p.add_subparsers(dest="cmd", required=True)
    sp.add_parser("status").set_defaults(f=cmd_status)
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
    a = p.parse_args()
    a.f(Mouse(), a)


if __name__ == "__main__":
    main()
