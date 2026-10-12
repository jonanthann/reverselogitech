"""Mouse em memória para testes do Painel (nunca abre /dev/hidraw)."""
import contextlib
import struct

from prox2 import RATES, crc_ok


class MouseFalso:
    def __init__(self, setores, em_uso=1):
        self.setores = dict(setores)
        self.em_uso = em_uso
        self.falhar_gravacao_em = None
        self.log = []
        self.transacoes = []

    @contextlib.contextmanager
    def transacao(self, gravando=False):
        self.transacoes.append(gravando)
        yield self

    def ler_setor(self, sec, crc=True):
        d = self.setores[sec]
        if crc and not crc_ok(d):
            raise IOError(f"CRC ruim ao ler o setor {sec}")
        return d

    def gravar_verificado(self, sec, data):
        self.log.append(("gravar", sec))
        if self.falhar_gravacao_em == sec:
            raise IOError(f"falha simulada no setor {sec}")
        self.setores[sec] = bytes(data)

    def perfil_ativo(self):
        self.log.append(("perfil_ativo",))
        return self.em_uso

    def definir_perfil(self, sec):
        self.log.append(("definir", sec))
        self.em_uso = sec

    def diretorio(self):
        d = self.setores[0]
        res = []
        for i in range(0, len(d) - 3, 4):
            sec = struct.unpack(">H", d[i:i + 2])[0]
            if sec == 0xFFFF:
                break
            res.append((sec, bool(d[i + 2])))
        return res

    def taxas_suportadas(self):
        return list(RATES)
