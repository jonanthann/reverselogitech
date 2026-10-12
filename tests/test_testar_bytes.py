import argparse
import os
import tempfile
import unittest
from unittest import mock

import testar_bytes as tb
from prox2 import com_crc, crc_ok
from tests.mouse_falso import MouseFalso


def setor_base():
    return com_crc(bytes(range(253)) + b"\x00\x00")


class TestValidacao(unittest.TestCase):
    def test_aceita_validos(self):
        self.assertEqual(tb.valor_set("0=6"), (0, 6))
        self.assertEqual(tb.valor_set("34=1"), (34, 1))
        self.assertEqual(tb.valor_set("37=0xFF"), (37, 255))

    def test_rejeita_invalidos(self):
        for t in ("0=7", "1=-1", "34=2", "37=256", "5=1", "abc", "0"):
            with self.assertRaises(argparse.ArgumentTypeError, msg=t):
                tb.valor_set(t)


class TestMontagem(unittest.TestCase):
    def test_altera_so_os_bytes_pedidos_e_recalcula_crc(self):
        o = setor_base()
        n = tb.montar_setor(o, {0: 2, 37: 50})
        self.assertTrue(crc_ok(n))
        difs = [i for i in range(253) if n[i] != o[i]]
        self.assertEqual(difs, [0, 37])
        self.assertEqual((n[0], n[37]), (2, 50))

    def test_tamanho_errado(self):
        with self.assertRaises(ValueError):
            tb.montar_setor(b"\x00" * 10, {0: 1})


class TestFluxo(unittest.TestCase):
    def test_leitura_nao_grava(self):
        m = MouseFalso({1: setor_base()})
        tb.mostrar(m.ler_setor(1))
        self.assertFalse([x for x in m.log if x[0] == "gravar"])

    def test_set_grava_e_restaura(self):
        o = setor_base()
        m = MouseFalso({1: o})
        with tempfile.TemporaryDirectory() as t, mock.patch.object(tb, "PASTA_BACKUP", t), \
                mock.patch("builtins.input", return_value=""):
            tb.cmd_set(m, 1, {34: 1}, True)
            self.assertEqual(len(os.listdir(t)), 1)
            with open(os.path.join(t, os.listdir(t)[0]), "rb") as f:
                self.assertEqual(f.read(), o)
        self.assertEqual(m.setores[1], o)
        self.assertEqual(m.log.count(("gravar", 1)), 2)

    def test_sem_restaurar_mantem(self):
        m = MouseFalso({1: setor_base()})
        with tempfile.TemporaryDirectory() as t, mock.patch.object(tb, "PASTA_BACKUP", t):
            tb.cmd_set(m, 1, {34: 1}, False)
        self.assertEqual(m.setores[1][34], 1)
        self.assertTrue(crc_ok(m.setores[1]))


class TestFalhas(unittest.TestCase):
    def rodar(self, m, restaurar=True, **kw):
        with tempfile.TemporaryDirectory() as t, mock.patch.object(tb, "PASTA_BACKUP", t), \
                mock.patch("builtins.input", return_value=""):
            tb.cmd_set(m, 1, {34: 1}, restaurar)

    def test_falha_na_gravacao_regrava_original_e_sai(self):
        o = setor_base()
        m = MouseFalso({1: o})
        orig = m.gravar_verificado

        def gravar(sec, d):
            if d != o:
                raise IOError("falha")
            orig(sec, d)
        m.gravar_verificado = gravar
        with self.assertRaises(SystemExit) as c:
            self.rodar(m)
        self.assertEqual(c.exception.code, 1)
        self.assertEqual(m.setores[1], o)

    def test_falha_na_restauracao_avisa_e_sai_1(self):
        o = setor_base()
        m = MouseFalso({1: o})
        orig = m.gravar_verificado

        def gravar(sec, d):
            if d == o:
                raise TimeoutError("falha")
            orig(sec, d)
        m.gravar_verificado = gravar
        with self.assertRaises(SystemExit) as c, mock.patch("builtins.print") as pr:
            self.rodar(m)
        self.assertEqual(c.exception.code, 1)
        saida = " ".join(str(x) for ch in pr.call_args_list for x in ch.args)
        self.assertIn("ficou alterado", saida)
        self.assertIn("--restaurar", saida)


class TestCmdRestaurar(unittest.TestCase):
    def arquivo(self, t, nome="perfil_2_x.bin", dados=None):
        c = os.path.join(t, nome)
        with open(c, "wb") as f:
            f.write(setor_base() if dados is None else dados)
        return c

    def test_restaura(self):
        m = MouseFalso({2: com_crc(b"\x01" * 253 + b"\x00\x00")})
        with tempfile.TemporaryDirectory() as t:
            tb.cmd_restaurar(m, self.arquivo(t), 2)
        self.assertEqual(m.setores[2], setor_base())

    def test_perfil_diferente_recusa(self):
        m = MouseFalso({2: setor_base()})
        with tempfile.TemporaryDirectory() as t, self.assertRaises(SystemExit):
            tb.cmd_restaurar(m, self.arquivo(t), 3)
        self.assertEqual(m.log, [])

    def test_crc_invalido_recusa(self):
        m = MouseFalso({2: setor_base()})
        with tempfile.TemporaryDirectory() as t, self.assertRaises(SystemExit):
            tb.cmd_restaurar(m, self.arquivo(t, dados=b"\x00" * 255), 2)
        self.assertEqual(m.log, [])


class TestMain(unittest.TestCase):
    def rodar(self, argv, ativo):
        m = MouseFalso({1: setor_base()}, em_uso=ativo)
        m.fechar = lambda: None
        with mock.patch.object(tb, "Mouse", return_value=m), mock.patch("sys.argv", ["x", *argv]):
            tb.main()
        return m

    def test_perfil_ativo_fora_da_faixa(self):
        with self.assertRaises(SystemExit):
            self.rodar([], 7)

    def test_restaurar_exige_perfil(self):
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            self.rodar(["--restaurar", "perfil_1_x.bin"], 1)


if __name__ == "__main__":
    unittest.main()
