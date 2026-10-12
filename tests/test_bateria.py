import os
import socket
import tempfile
import threading
import unittest

import bateria
import caminhos
import prox2

CAPS = bateria.decodificar_caps(bytes([0x0F, 0x0F, 0x02]))


def info(soc, carga=0, ext=0, nivel=4):
    return bateria.decodificar_status(bytes([soc, nivel, carga, ext]), CAPS)


class TestDecodificar(unittest.TestCase):
    def test_status(self):
        r = bateria.decodificar_status(bytes([0x39, 4, 0, 0]), CAPS)
        self.assertEqual(r, {"soc": 57, "nivel": "bom", "carregando": False,
                             "estado_carga": "descarregando", "energia_externa": "nenhuma"})

    def test_sem_soc(self):
        caps = bateria.decodificar_caps(bytes([0x0F, 0x01]))
        self.assertIsNone(bateria.decodificar_status(bytes([50, 2, 0, 0]), caps)["soc"])

    def test_evento(self):
        r = bateria.decodificar_evento(bytes([0x11, 1, 6, 0, 80, 8, 1, 1]) + bytes(12), CAPS)
        self.assertEqual((r["soc"], r["nivel"], r["estado_carga"], r["energia_externa"]),
                         (80, "cheio", "carregando", "com_fio"))
        self.assertIsNone(bateria.decodificar_evento(bytes([0x11, 1, 6, 0x1A, 1, 1, 1, 1])))


class TestIcone(unittest.TestCase):
    def test_icones(self):
        self.assertEqual(bateria.nome_icone(info(57)), "battery-level-50-symbolic")
        self.assertEqual(bateria.nome_icone(info(57, 1, 1)), "battery-level-50-charging-symbolic")
        self.assertEqual(bateria.nome_icone(info(5)), "battery-level-0-symbolic")
        self.assertEqual(bateria.nome_icone(info(100)), "battery-level-100-symbolic")
        self.assertEqual(bateria.nome_icone(info(100, 3, 1)), "battery-level-100-charged-symbolic")
        self.assertEqual(bateria.nome_icone(None), "battery-missing-symbolic")


class TestAlertas(unittest.TestCase):
    def test_descarga(self):
        a = bateria.Alertas()
        r = [a.atualizar(info(s)) for s in (25, 19, 18, 9, 8)]
        self.assertEqual(r, [[], ["baixa"], [], ["critica"], []])

    def test_carregar_rearma(self):
        a = bateria.Alertas()
        a.atualizar(info(19))
        a.atualizar(info(30, 1, 1))
        self.assertEqual(a.atualizar(info(19)), ["baixa"])

    def test_sobe_5_rearma(self):
        a = bateria.Alertas()
        a.atualizar(info(19))
        a.atualizar(info(26))
        self.assertEqual(a.atualizar(info(19)), ["baixa"])

    def test_carregada(self):
        a = bateria.Alertas()
        r = [a.atualizar(info(100, 3, 1)), a.atualizar(info(100, 3, 1))]
        self.assertEqual(r, [["carregada"], []])
        a.atualizar(info(100))
        self.assertEqual(a.atualizar(info(100, 3, 1)), ["carregada"])

    def test_sem_soc_usa_nivel(self):
        caps = bateria.decodificar_caps(bytes([0x0F, 0x01]))
        a = bateria.Alertas()
        self.assertEqual(a.atualizar(bateria.decodificar_status(bytes([0, 2, 0, 0]), caps)), ["baixa"])
        self.assertEqual(a.atualizar(bateria.decodificar_status(bytes([0, 1, 0, 0]), caps)), ["critica"])


class TestCaminhos(unittest.TestCase):
    def test_migrar_copia_sem_sobrescrever(self):
        with tempfile.TemporaryDirectory() as t:
            o, d = os.path.join(t, "o.json"), os.path.join(t, "sub", "d.json")
            open(o, "w").write("A")
            self.assertTrue(caminhos.migrar_backup(o, d))
            self.assertTrue(os.path.exists(o))
            open(o, "w").write("B")
            self.assertFalse(caminhos.migrar_backup(o, d))
            self.assertEqual(open(d).read(), "A")

    def test_pastas_xdg(self):
        os.environ["XDG_DATA_HOME"] = "/x"
        try:
            self.assertEqual(caminhos.pasta_dados(), "/x/myproX2")
        finally:
            del os.environ["XDG_DATA_HOME"]


class TestMouseBateria(unittest.TestCase):
    def test_fd_injetado(self):
        a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        feats = {0x8100: 1, 0x8061: 2, 0x1004: 6}

        def servir():
            while True:
                try:
                    d = b.recv(64)
                except OSError:
                    return
                if not d:
                    return
                fidx, fs = d[2], d[3]
                if fidx == 0:
                    r = bytes([feats.get(int.from_bytes(d[4:6], "big"), 0)])
                elif fidx == 1:
                    r = bytes(3) + b"\0\0\0\0\x00\x10"
                elif fidx == 6 and fs >> 4 == 0:
                    r = bytes([0x0F, 0x0F, 0x02])
                else:
                    r = bytes([0x39, 4, 0, 0])
                b.send((bytes([0x11, d[1], fidx, fs]) + r).ljust(20, b"\0"))

        threading.Thread(target=servir, daemon=True).start()
        m = prox2.Mouse(fd=a.fileno())
        r = m.bateria()
        self.assertEqual((r["soc"], r["nivel"], r["estado_carga"]), (57, "bom", "descarregando"))
        a.close()
        b.close()


if __name__ == "__main__":
    unittest.main()
