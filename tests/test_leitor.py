import os
import socket
import tempfile
import threading
import time
import unittest

import prox2

FEATS = {0x8100: 1, 0x8061: 2, 0x1004: 6, 0x0005: 3}


def servidor(b, responder=None):
    """Simula o receptor: responde ao protocolo mínimo; responder(d) pode devolver o pacote ou None."""
    def servir():
        while True:
            try:
                d = b.recv(64)
            except OSError:
                return
            if not d:
                return
            if responder:
                r = responder(d)
                if r is not None:
                    b.send(r)
                    continue
                if r is None and d[2] not in (0, 1):
                    continue
            fidx, fs = d[2], d[3]
            if fidx == 0:
                r = bytes([FEATS.get(int.from_bytes(d[4:6], "big"), 0)])
            elif fidx == 1:
                r = bytes(3) + b"\0\0\0\0\x00\x10"
            else:
                r = bytes([0x39, 4, 0, 0])
            b.send((bytes([0x11, d[1], fidx, fs]) + r).ljust(20, b"\0"))
    threading.Thread(target=servir, daemon=True).start()


def par():
    return socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)


def esperar(cond, t=3):
    fim = time.monotonic() + t
    while time.monotonic() < fim:
        if cond():
            return True
        time.sleep(0.02)
    return False


class TestLeitor(unittest.TestCase):
    def setUp(self):
        self.a, self.b = par()
        self.m = None

    def tearDown(self):
        if self.m:
            self.m.fechar()
        self.a.close()
        self.b.close()

    def test_resposta_e_evento(self):
        eventos, bats = [], []

        def resp(d):
            if d[2] == 6:  # evento de bateria antes da resposta
                self.b.send(bytes([0x11, 1, 6, 0, 80, 8, 1, 1]).ljust(20, b"\0"))
                return bytes([0x11, 1, 6, d[3], 0x39, 4, 0, 0]).ljust(20, b"\0")
            return None
        servidor(self.b, resp)
        self.m = prox2.Mouse(fd=self.a.fileno(), leitor=True)
        self.m.ao_evento(eventos.append)
        self.m.ao_bateria(bats.append)
        self.m.feat[0x1004] = 6
        r = self.m.req(6, 1)
        self.assertEqual(r[0], 0x39)
        self.assertTrue(esperar(lambda: eventos and bats))
        self.assertEqual(bats[0]["soc"], 80)

    def test_erro_8f_imediato(self):
        servidor(self.b, lambda d: bytes([0x10, 1, 0x8F, d[2], d[3], 0x03, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])[:7]
                 if d[2] == 6 else None)
        self.m = prox2.Mouse(fd=self.a.fileno(), leitor=True)
        t = time.monotonic()
        with self.assertRaises(prox2.MouseInalcancavel):
            self.m.req(6, 1)
        self.assertLess(time.monotonic() - t, 0.5)

    def test_erro_8f_sincrono(self):
        servidor(self.b, lambda d: bytes([0x10, 1, 0x8F, d[2], d[3], 0x03, 0]) if d[2] == 6 else None)
        self.m = prox2.Mouse(fd=self.a.fileno())
        t = time.monotonic()
        with self.assertRaises(prox2.MouseInalcancavel):
            self.m.req(6, 1)
        self.assertLess(time.monotonic() - t, 0.5)

    def test_concorrentes(self):
        def resp(d):
            if d[2] == 6:
                time.sleep(0.01 * (d[4] % 3))
                return (bytes([0x11, 1, 6, d[3]]) + bytes([d[4]])).ljust(20, b"\0")
            return None
        servidor(self.b, resp)
        self.m = prox2.Mouse(fd=self.a.fileno(), leitor=True)
        erros = []

        def trab(n):
            for i in range(20):
                v = (n * 20 + i) % 256
                if self.m.req(6, 0, bytes([v]))[0] != v:
                    erros.append(v)
        ts = [threading.Thread(target=trab, args=(n,)) for n in range(2)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(erros, [])

    def test_reconexao(self):
        servidor(self.b)
        novos = []

        def abrir():
            x, y = par()
            novos.append((x, y))
            servidor(y)
            return x.detach()
        estados = []
        self.m = prox2.Mouse(fd=self.a.fileno(), leitor=True, abrir=abrir, intervalo_reabrir=0.1)
        self.m.ao_estado(estados.append)
        self.b.shutdown(socket.SHUT_RDWR)
        self.assertTrue(esperar(lambda: estados == ["desconectado", "conectado"]))
        self.assertEqual(self.m.req(6, 1)[0], 0x39)
        for x, y in novos:
            y.close()

    def test_desconectado_falha_rapido(self):
        servidor(self.b)
        self.m = prox2.Mouse(fd=self.a.fileno(), leitor=True, abrir=lambda: (_ for _ in ()).throw(prox2.ErroMouse("x")),
                             intervalo_reabrir=10)
        estados = []
        self.m.ao_estado(estados.append)
        self.b.shutdown(socket.SHUT_RDWR)
        self.assertTrue(esperar(lambda: estados == ["desconectado"]))
        t = time.monotonic()
        with self.assertRaises(prox2.MouseInalcancavel):
            self.m.req(6, 1)
        self.assertLess(time.monotonic() - t, 0.5)

    def test_8f_de_outra_requisicao_e_ignorado(self):
        def resp(d):
            if d[2] == 6:
                self.b.send(bytes([0x10, 1, 0x8F, 9, 0x1A, 0x03, 0]))  # não casa com a pendente
                return bytes([0x11, 1, 6, d[3], 0x39]).ljust(20, b"\0")
            return None
        servidor(self.b, resp)
        self.m = prox2.Mouse(fd=self.a.fileno(), leitor=True)
        self.assertEqual(self.m.req(6, 1)[0], 0x39)

    def test_8f_de_outra_requisicao_sincrono(self):
        def resp(d):
            if d[2] == 6:
                self.b.send(bytes([0x10, 1, 0x8F, 9, 0x1A, 0x03, 0]))
                return bytes([0x11, 1, 6, d[3], 0x39]).ljust(20, b"\0")
            return None
        servidor(self.b, resp)
        self.m = prox2.Mouse(fd=self.a.fileno())
        self.assertEqual(self.m.req(6, 1)[0], 0x39)

    def test_resposta_atrasada_descartada(self):
        for leitor in (True, False):
            a, b = par()
            def resp(d, b=b):
                if d[2] == 6:
                    ant = bytes([0x11, 1, 6, (d[3] & 0xF0) | (d[3] - 1 if d[3] & 0xF > 1 else 15), 0xEE])
                    b.send(ant.ljust(20, b"\0"))  # resposta velha, SWID diferente
                    return bytes([0x11, 1, 6, d[3], 0x39]).ljust(20, b"\0")
                return None
            servidor(b, resp)
            m = prox2.Mouse(fd=a.fileno(), leitor=leitor)
            try:
                for _ in range(20):
                    self.assertEqual(m.req(6, 1)[0], 0x39)
                self.assertTrue(all(1 <= prox2.Mouse._proximo_swid(m) <= 15 for _ in range(40)))
            finally:
                m.fechar()
                a.close()
                b.close()

    def test_erro_mouse_e_ioerror(self):
        self.assertTrue(issubclass(prox2.ErroMouse, IOError))
        self.assertTrue(issubclass(prox2.TravaOcupada, prox2.ErroMouse))

    def test_trava_nome_fixo(self):
        servidor(self.b)
        self.m = prox2.Mouse(fd=self.a.fileno(), caminho="/dev/hidraw7")
        self.assertEqual(os.path.basename(self.m._caminho_trava()), "myprox2.lock")

    def test_reabrir_recarrega_caps_bateria(self):
        novos = []

        def resp(d):
            if d[2] == 6 and d[3] >> 4 == 0:
                return bytes([0x11, 1, 6, d[3], 0x39, 4, 0, 0]).ljust(20, b"\0")
            return None

        def abrir():
            x, y = par()
            novos.append((x, y))
            servidor(y, resp)
            return x.detach()
        servidor(self.b, resp)
        estados = []
        self.m = prox2.Mouse(fd=self.a.fileno(), leitor=True, abrir=abrir, intervalo_reabrir=0.1)
        self.m.ao_estado(estados.append)
        self.b.shutdown(socket.SHUT_RDWR)
        self.assertTrue(esperar(lambda: estados == ["desconectado", "conectado"]))
        self.assertIsNotNone(self.m._caps_bateria)
        for x, y in novos:
            y.close()

    def test_fechar_impede_reabrir(self):
        abertos = []

        def abrir():
            x, y = par()
            abertos.append(y)
            return x.detach()
        servidor(self.b)
        self.m = prox2.Mouse(fd=self.a.fileno(), abrir=abrir)
        self.m.fechar()
        self.m._reabrir()
        self.assertIsNone(self.m.fd)
        for y in abertos:
            y.close()


class TestTrava(unittest.TestCase):
    def test_flock_impede_gravacao_simultanea(self):
        a, b = par()
        servidor(b)
        with tempfile.TemporaryDirectory() as t:
            arq = os.path.join(t, "x.lock")
            m1 = prox2.Mouse(fd=a.fileno(), arq_trava=arq, espera_trava=0.3)
            m2 = prox2.Mouse(fd=a.fileno(), arq_trava=arq, espera_trava=0.3)
            with m1.transacao(gravando=True):
                with self.assertRaises(prox2.ErroMouse) as c:
                    m2.gravar_setor(1, bytes(m2.size))
                self.assertIn("gravando", str(c.exception))
            with m1.transacao(gravando=True):
                with m1.transacao(gravando=True):
                    pass
            with m2.transacao(gravando=True):
                pass
        a.close()
        b.close()


if __name__ == "__main__":
    unittest.main()
