import json
import os
import unittest

import acoes
from prox2 import crc_ok

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(RAIZ, "tests", "dados", "prox2_backup_perfis.json")) as f:
    B = {int(k, 16): bytes.fromhex(v) for k, v in json.load(f).items()}

AB = bytes.fromhex("430004" "40001e" "440004" "40001e" "430005" "40001e" "440005" "ff")


class TestAcoes(unittest.TestCase):
    def test_round_trip_backup(self):
        for sec in range(1, 6):
            for ini in (48, 112):
                for i in range(5):
                    b = B[sec][ini + 4 * i:ini + 4 * i + 4]
                    self.assertEqual(acoes.codificar_acao(acoes.decodificar_acao(b)), b, (sec, ini, i))

    def test_tipos(self):
        self.assertEqual(acoes.decodificar_acao(bytes.fromhex("00060002")),
                         {"tipo": "macro", "sec": 6, "offset": 2})
        self.assertEqual(acoes.decodificar_acao(bytes.fromhex("80010008")), {"tipo": "clique", "botao": "voltar"})
        self.assertEqual(acoes.decodificar_acao(bytes.fromhex("90050000")), {"tipo": "especial", "codigo": "ciclo_dpi"})
        self.assertEqual(acoes.decodificar_acao(bytes.fromhex("8003cd00")), {"tipo": "midia", "codigo": 0xCD00})
        self.assertEqual(acoes.decodificar_acao(bytes.fromhex("ffffffff")), {"tipo": "desligado"})

    def test_bruto_round_trip(self):
        for h in ("80010003", "90ff0000", "00050000", "00060100", "12345678", "80020003"):
            d = acoes.decodificar_acao(bytes.fromhex(h))
            self.assertEqual(d["tipo"], "bruto", h)
            self.assertEqual(acoes.codificar_acao(d).hex(), h)

    def test_codificar_erros(self):
        for d in ({"tipo": "macro", "sec": 5, "offset": 0}, {"tipo": "macro", "sec": 6, "offset": 253},
                  {"tipo": "tecla", "mod": 0, "tecla": 3}, {"tipo": "tecla", "mod": 256, "tecla": 4},
                  {"tipo": "midia", "codigo": 65536}, {"tipo": "clique", "botao": "x"},
                  {"tipo": "especial", "codigo": "x"}, {"tipo": "bruto", "hex": "1234"},
                  {"tipo": "bruto", "hex": "zzzzzzzz"}, {"tipo": "outro"}, "x"):
            with self.assertRaises(ValueError, msg=d):
                acoes.codificar_acao(d)

    def test_macro_ab_bate_com_referencia(self):
        setor = acoes.montar_macro(acoes.texto_para_passos("ab", 30))
        self.assertEqual(len(setor), 255)
        self.assertEqual(setor[:len(AB)], AB)
        self.assertEqual(setor[len(AB):253], b"\xff" * (253 - len(AB)))
        self.assertTrue(crc_ok(setor))
        r = acoes.ler_macro(setor)
        self.assertEqual(r["estado"], "ok")
        self.assertEqual(acoes.montar_macro(r["passos"]), setor)

    def test_ler_macro_estados(self):
        self.assertEqual(acoes.ler_macro(b"\xff" * 255)["estado"], "vazia")
        self.assertEqual(acoes.ler_macro(acoes.setor_macro_vazio())["estado"], "vazia")
        setor = acoes.montar_macro(acoes.texto_para_passos("a"))
        self.assertEqual(acoes.ler_macro(setor, 3)["passos"][0]["tipo"], "espera")
        self.assertEqual(acoes.ler_macro(setor, 100)["estado"], "vazia")
        ruim = bytearray(setor)
        ruim[-1] ^= 0xFF
        self.assertEqual(acoes.ler_macro(bytes(ruim))["estado"], "invalida")
        lixo = bytearray(b"\xff" * 255)
        lixo[0] = 0x77
        self.assertEqual(acoes.ler_macro(bytes(lixo))["estado"], "invalida")

    def test_montar_macro_erros(self):
        ap = {"tipo": "aperta", "mod": 0, "tecla": 4}
        for passos in ([], [ap], [{"tipo": "espera", "ms": 0}], [{"tipo": "espera", "ms": 65536}],
                       [{"tipo": "x"}], [{"tipo": "espera", "ms": 1}] * 85):
            with self.assertRaises(ValueError, msg=passos):
                acoes.montar_macro(passos)
        acoes.montar_macro([{"tipo": "espera", "ms": 1}] * 84)  # 252 bytes + ff = 253

    def test_texto(self):
        p = acoes.texto_para_passos("A 1\n\t0")
        teclas = [(x["mod"], x["tecla"]) for x in p if x["tipo"] == "aperta"]
        self.assertEqual(teclas, [(2, 4), (0, 0x2C), (0, 0x1E), (0, 0x28), (0, 0x2B), (0, 0x27)])
        for txt in ("é", "a.", ""):
            with self.assertRaises(ValueError):
                acoes.montar_macro(acoes.texto_para_passos(txt))
        with self.assertRaises(ValueError):
            acoes.texto_para_passos("a", 0)


if __name__ == "__main__":
    unittest.main()
