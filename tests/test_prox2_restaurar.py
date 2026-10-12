import json
import os
import tempfile
import types
import unittest
from unittest import mock

import prox2
from tests.mouse_falso import MouseFalso
from tests.test_painel_core import B, estragar_crc


class TestRestaurar(unittest.TestCase):
    def test_pula_setor_com_crc_ruim_e_restaura_os_outros(self):
        mouse = MouseFalso(dict(B), em_uso=1)
        mouse.size = len(B[1])
        mouse.taxa_atual = lambda: 1000
        arq = {f"{s:#06x}": B[s].hex() for s in range(1, 6)}
        ruim = bytearray(B[2])
        ruim[-1] ^= 0xFF
        arq["0x0002"] = bytes(ruim).hex()
        # mouse com setores 3 e 4 diferentes do arquivo
        for s in (3, 4):
            d = bytearray(B[s])
            d[8] ^= 0x01
            mouse.setores[s] = prox2.com_crc(bytes(d[:-2]))
        antigo2 = mouse.setores[2]
        with tempfile.TemporaryDirectory() as t:
            caminho = os.path.join(t, "bk.json")
            with open(caminho, "w") as f:
                json.dump(arq, f)
            a = types.SimpleNamespace(arquivo=caminho, sim=True)
            with mock.patch("time.sleep"):
                prox2.cmd_restaurar(mouse, a)
        self.assertEqual(mouse.setores[3], B[3])
        self.assertEqual(mouse.setores[4], B[4])
        self.assertEqual(mouse.setores[2], antigo2)
        self.assertNotIn(("gravar", 2), mouse.log)

    def _restaurar(self, mouse, arq):
        mouse.size = len(B[1])
        mouse.taxa_atual = lambda: 1000
        with tempfile.TemporaryDirectory() as t:
            caminho = os.path.join(t, "bk.json")
            with open(caminho, "w") as f:
                json.dump(arq, f)
            with mock.patch("time.sleep"):
                prox2.cmd_restaurar(mouse, types.SimpleNamespace(arquivo=caminho, sim=True))

    def test_macro_ff_do_backup_volta_vazia_com_crc(self):
        mouse = MouseFalso(dict(B), em_uso=1)
        mouse.setores[6] = b"\x11" * 255
        self._restaurar(mouse, {"0x0006": ("ff" * 255)})
        self.assertEqual(mouse.setores[6], prox2.com_crc(b"\xff" * 255))

    def test_macro_nao_ff_com_crc_ruim_e_pulada_com_aviso(self):
        mouse = MouseFalso(dict(B), em_uso=1)
        mouse.setores[6] = b"\x11" * 255
        arq = {"0x0003": B[3].hex(), "0x0006": ("12" * 255)}
        with mock.patch("builtins.print") as p:
            self._restaurar(mouse, arq)
        self.assertEqual(mouse.setores[6], b"\x11" * 255)
        self.assertTrue(any("NÃO foram restaurados" in str(c) for c in p.call_args_list))

    def test_regravar_original_macro_sem_crc_grava_vazia_com_crc(self):
        mouse = MouseFalso(dict(B), em_uso=1)
        prox2.regravar_original(mouse, 7, b"\x22" * 255)
        self.assertEqual(mouse.setores[7], prox2.com_crc(b"\xff" * 255))


if __name__ == "__main__":
    unittest.main()
