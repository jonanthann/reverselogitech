import json
import os
import unittest

import perfil
from prox2 import crc_ok

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(RAIZ, "tests", "dados", "prox2_backup_perfis.json")) as f:
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
        n = perfil.montar_vaga(S1, niveis=[800], polling_hz=2000, lod=None)
        self.assertEqual(n[0], 4)
        self.assertEqual(n[1], 4)
        self.assertEqual(n[4:8], bytes([0x20, 0x03, 0x20, 0x03]))
        self.assertEqual(n[8], 2)
        self.assertTrue(crc_ok(n))
        self.assertEqual(n[9:253], S1[9:253])

    def test_dpi_invalido(self):
        with self.assertRaises(ValueError) as c:
            perfil.montar_vaga(S1, niveis=[1601], polling_hz=None, lod=None)
        self.assertIn("1600", str(c.exception))
        self.assertIn("1610", str(c.exception))

    def test_niveis_recusa_x_diferente_de_y_e_buraco(self):
        b = bytearray(S3)
        b[4:6] = b"\x20\x03"
        b[6:8] = b"\x58\x02"  # X != Y no nível 0
        with self.assertRaises(ValueError):
            perfil.montar_vaga(perfil.com_crc(bytes(b)), niveis=[800, 1200])
        c = bytearray(S3)
        c[9:14] = bytes(5)  # buraco no nível 1
        with self.assertRaises(ValueError):
            perfil.montar_vaga(perfil.com_crc(bytes(c)), niveis=[800, 1200, 1600])

    def test_varios_niveis(self):
        n = perfil.montar_vaga(S3, niveis=[800])
        self.assertEqual(n[9:29], bytes(20))
        self.assertEqual(n[4:8], bytes([0x20, 0x03, 0x20, 0x03]))
        self.assertEqual(n[8], S3[8])
        self.assertEqual((n[2], n[3]), (0, 0))
        r = perfil.ler_vaga(perfil.montar_vaga(S1, niveis=[800, 1600, 3200], dpi_padrao=2, dpi_shift=1))
        self.assertEqual((r["niveis"], r["dpi_padrao"], r["dpi_shift"]), ([800, 1600, 3200], 2, 1))
        self.assertEqual(r["botoes"], perfil.ler_vaga(S1)["botoes"])

    def test_indices_ajustados_e_invalidos(self):
        b = bytearray(S3)
        b[2], b[3] = 4, 3
        n = perfil.montar_vaga(perfil.com_crc(bytes(b)), niveis=[800, 1600])
        self.assertEqual((n[2], n[3]), (1, 1))
        for kw in ({"dpi_padrao": 5}, {"dpi_shift": -1}, {"niveis": []}, {"niveis": [800] * 6}):
            with self.assertRaises(ValueError):
                perfil.montar_vaga(S3, **kw)

    def test_botoes_gshift(self):
        r = perfil.ler_vaga(S1)
        self.assertEqual(r["botoes"][0], {"tipo": "clique", "botao": "esquerdo"})
        botoes = list(r["botoes"])
        botoes[3] = {"tipo": "tecla", "mod": 0, "tecla": 4}
        gs = [{"tipo": "especial", "codigo": "ciclo_dpi"}] + [{"tipo": "desligado"}] * 4
        n = perfil.montar_vaga(S1, botoes=botoes, gshift=gs)
        self.assertEqual(n[48 + 12:48 + 16], bytes([0x80, 2, 0, 4]))
        self.assertEqual(n[112:116], bytes([0x90, 5, 0, 0]))
        self.assertEqual(n[29:48], S1[29:48])
        self.assertEqual(n[208:253], S1[208:253])
        self.assertTrue(crc_ok(n))

    def test_botoes_recusados(self):
        sem = [{"tipo": "desligado"}] * 5
        with self.assertRaises(ValueError):
            perfil.montar_vaga(S1, botoes=sem)
        perfil.montar_vaga(S1, gshift=sem)  # G-Shift pode ficar todo desligado
        with self.assertRaises(ValueError):
            perfil.montar_vaga(S1, gshift=[{"tipo": "macro", "sec": 5, "offset": 0}] + sem[1:])
        with self.assertRaises(ValueError):
            perfil.montar_vaga(S1, gshift=sem[:4])

    def test_polling_invalido(self):
        with self.assertRaises(ValueError):
            perfil.montar_vaga(S1, polling_hz=3000, lod=None)

    def test_sem_mudanca(self):
        self.assertEqual(perfil.montar_vaga(S1, polling_hz=None, lod=None), S1)

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
        n = perfil.montar_vaga(S1, polling_hz=None, lod=3, nome="Dia a dia")
        self.assertEqual(n[8], 3)
        self.assertEqual(perfil.ler_vaga(n)["nome"], "Dia a dia")
        self.assertIsNone(perfil.ler_vaga(perfil.montar_vaga(n, polling_hz=None, lod=None, nome=""))["nome"])
        with self.assertRaises(ValueError):
            perfil.montar_vaga(S1, polling_hz=None, lod=4)
        with self.assertRaises(ValueError):
            perfil.montar_vaga(S1, polling_hz=None, lod=None, nome="x" * 25)
        with self.assertRaises(ValueError):
            perfil.montar_vaga(S1, polling_hz=None, lod=None, nome="\U0001F600" * 24)


if __name__ == "__main__":
    unittest.main()
