import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import formulario as f

BASE = {"niveis": [400, 800, 1600], "padrao": 1, "shift": 2, "polling_hz": 1000, "lod": 2, "ativa": True, "nome": ""}


class TestFormulario(unittest.TestCase):
    def test_sem_mudanca(self):
        self.assertEqual(f.argumentos(BASE, dict(BASE)), {})

    def test_so_o_que_mudou(self):
        a = dict(BASE, polling_hz=500, nome="Jogo")
        self.assertEqual(f.argumentos(BASE, a), {"polling_hz": 500, "nome": "Jogo"})

    def test_niveis_levam_indices(self):
        a = dict(BASE, niveis=[400, 800, 3200])
        self.assertEqual(f.argumentos(BASE, a), {"niveis": [400, 800, 3200], "dpi_padrao": 1, "dpi_shift": 2})

    def test_invalidos(self):
        for a in (dict(BASE, niveis=[]), dict(BASE, niveis=[50]), dict(BASE, niveis=[800] * 6),
                  dict(BASE, nome="x" * 25)):
            with self.assertRaises(ValueError):
                f.argumentos(BASE, a)

    def test_remover_ajusta_indices(self):
        self.assertEqual(f.remover_nivel([1, 2, 3], 1, 2, 0), ([2, 3], 0, 1))
        self.assertEqual(f.remover_nivel([1, 2, 3], 1, 2, 1), ([1, 3], 0, 1))
        self.assertEqual(f.remover_nivel([1, 2, 3], 0, 2, 2), ([1, 2], 0, 0))
        self.assertEqual(f.remover_nivel([5], 0, 0, 0), ([5], 0, 0))

    def test_adicionar(self):
        self.assertEqual(f.adicionar_nivel([400, 800]), [400, 800, 800])
        self.assertEqual(len(f.adicionar_nivel([1] * 5)), 5)

    def test_de_vaga(self):
        v = {"niveis": [800], "dpi_padrao": 0, "dpi_shift": 0, "polling_hz": 1000, "lod": 2, "ativa": 1, "nome_real": None}
        self.assertEqual(f.de_vaga(v)["nome"], "")
        self.assertIs(f.de_vaga(v)["ativa"], True)


CL = [{"tipo": "clique", "botao": b, "extra": 1} for b in ("esquerdo", "direito", "meio", "voltar", "avancar")]
GS = [{"tipo": "desligado"}] * 5
MACROS = [{"sec": 6, "estado": "ok"}, {"sec": 7, "estado": "vazia"}]


class TestBotoes(unittest.TestCase):
    def test_sem_mudanca(self):
        self.assertEqual(f.argumentos_botoes([CL, GS], [CL, GS], MACROS), {})

    def test_so_a_camada_que_mudou(self):
        gs = [{"tipo": "tecla", "mod": 0, "tecla": 4}] + GS[1:]
        self.assertEqual(f.argumentos_botoes([CL, GS], [CL, gs], MACROS), {"gshift": gs})

    def test_exige_clique_esquerdo(self):
        n = [{"tipo": "desligado"}] + CL[1:]
        with self.assertRaises(ValueError):
            f.argumentos_botoes([CL, GS], [n, GS], MACROS)

    def test_macro_nao_pronta(self):
        gs = [{"tipo": "macro", "sec": 7, "offset": 0}] + GS[1:]
        with self.assertRaises(ValueError):
            f.argumentos_botoes([CL, GS], [CL, gs], MACROS)
        gs = [{"tipo": "macro", "sec": 6, "offset": 0}] + GS[1:]
        self.assertEqual(f.argumentos_botoes([CL, GS], [CL, gs], MACROS), {"gshift": gs})


if __name__ == "__main__":
    unittest.main()
