import json
import os
import unittest

import perfil
from prox2 import crc_ok

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(RAIZ, "prox2_backup_perfis.json")) as f:
    B = {k: bytes.fromhex(v) for k, v in json.load(f).items()}
S0, S1, S3 = B["0x0000"], B["0x0001"], B["0x0003"]


def com_nome(setor, nome):
    b = bytearray(setor)
    b[160:208] = b"\xff" * 48
    raw = nome.encode("utf-16-le")
    b[160:160 + len(raw)] = raw
    b[160 + len(raw):208] = b"\x00" * (48 - len(raw))
    return perfil.com_crc(bytes(b))


class TestPerfil(unittest.TestCase):
    def test_ler_um_nivel(self):
        r = perfil.ler_vaga(S1)
        self.assertEqual(r["dpis"], [1600])
        self.assertEqual(r["polling_hz"], 1000)
        self.assertEqual(r["lod"], 2)
        self.assertIs(r["um_nivel"], True)
        self.assertIs(r["crc_ok"], True)

    def test_ler_cinco_niveis(self):
        r = perfil.ler_vaga(S3)
        self.assertEqual(r["dpis"], [800, 1200, 1600, 2400, 3200])
        self.assertIs(r["um_nivel"], False)
        self.assertIsNone(r["nome"])

    def test_montar_dpi_polling(self):
        n = perfil.montar_vaga(S1, dpi=800, polling_hz=2000, lod=None)
        self.assertEqual(n[0], 4)
        self.assertEqual(n[1], 4)
        self.assertEqual(n[4:8], bytes([0x20, 0x03, 0x20, 0x03]))
        self.assertEqual(n[8], 2)
        self.assertTrue(crc_ok(n))
        self.assertEqual(n[9:253], S1[9:253])

    def test_dpi_invalido(self):
        with self.assertRaises(ValueError) as c:
            perfil.montar_vaga(S1, dpi=1601, polling_hz=None, lod=None)
        self.assertIn("1600", str(c.exception))
        self.assertIn("1610", str(c.exception))

    def test_varios_niveis(self):
        with self.assertRaises(ValueError):
            perfil.montar_vaga(S3, dpi=800, polling_hz=None, lod=None)
        n = perfil.montar_vaga(S3, dpi=800, polling_hz=None, lod=None, um_dpi_so=True)
        self.assertEqual(n[9:29], bytes(20))
        self.assertEqual(n[4:8], bytes([0x20, 0x03, 0x20, 0x03]))
        self.assertEqual(n[8], S3[8])

    def test_polling_invalido(self):
        with self.assertRaises(ValueError):
            perfil.montar_vaga(S1, dpi=None, polling_hz=3000, lod=None)

    def test_sem_mudanca(self):
        self.assertEqual(perfil.montar_vaga(S1, dpi=None, polling_hz=None, lod=None), S1)

    def test_diretorio(self):
        n = perfil.diretorio_com_ativo(S0, 3, True)
        self.assertEqual(n[10], 1)
        self.assertEqual(n[:10], S0[:10])
        self.assertEqual(n[11:253], S0[11:253])
        self.assertTrue(crc_ok(n))
        with self.assertRaises(ValueError):
            perfil.diretorio_com_ativo(S0, 9, True)

    def test_nome_lido(self):
        self.assertEqual(perfil.ler_vaga(com_nome(S1, "minecraft"))["nome"], "minecraft")

    def test_nome_montar(self):
        n = perfil.montar_vaga(S1, dpi=None, polling_hz=None, lod=3, nome="Dia a dia")
        self.assertEqual(n[8], 3)
        self.assertEqual(perfil.ler_vaga(n)["nome"], "Dia a dia")
        self.assertIsNone(perfil.ler_vaga(perfil.montar_vaga(n, dpi=None, polling_hz=None, lod=None, nome=""))["nome"])
        with self.assertRaises(ValueError):
            perfil.montar_vaga(S1, dpi=None, polling_hz=None, lod=4)
        with self.assertRaises(ValueError):
            perfil.montar_vaga(S1, dpi=None, polling_hz=None, lod=None, nome="x" * 25)
        with self.assertRaises(ValueError):
            perfil.montar_vaga(S1, dpi=None, polling_hz=None, lod=None, nome="\U0001F600" * 24)


if __name__ == "__main__":
    unittest.main()
