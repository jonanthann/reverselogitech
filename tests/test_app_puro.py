import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bateria
from app import puro

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INFO = {"soc": 57, "nivel": "bom", "carregando": False, "estado_carga": "descarregando", "energia_externa": "nenhuma"}


class TestAppPuro(unittest.TestCase):
    def test_layout(self):
        rev, (i, _p, filhos) = puro.layout_menu(INFO, 4)
        self.assertEqual((rev, i), (4, 0))
        self.assertEqual(filhos[0][1], {"label": "Bateria 57% (descarregando)", "enabled": False})
        self.assertEqual(filhos[1][1]["type"], "separator")
        self.assertEqual([f[1]["label"] for f in filhos[2:]], ["Abrir myproX2", "Sair"])
        self.assertEqual(puro.texto_item_bateria(None), "Bateria indisponível")

    def test_tooltip(self):
        self.assertEqual(puro.texto_tooltip(INFO, True), ("myproX2", "57%, descarregando"))
        self.assertIn("última leitura", puro.texto_tooltip(INFO, False, 0)[1])
        self.assertIn("57%", puro.texto_tooltip(INFO, False, 0)[1])

    def test_notificacoes(self):
        a = bateria.Alertas()
        env = []
        for soc in (50, 19, 18, 9, 8):
            env.append(puro.decidir_notificacoes(a.atualizar(dict(INFO, soc=soc))))
        self.assertEqual(env, [[], [("baixa", False)], [], [("critica", True)], []])
        self.assertEqual(puro.decidir_notificacoes(["baixa", "critica"]), [("critica", True)])
        self.assertEqual(puro.texto_notificacao("carregada", INFO)[0], "Bateria carregada")

    def test_escapar_exec(self):
        self.assertEqual(puro.escapar_exec('/a b/"x"$y`z`\\%'), '"/a b/\\"x\\"\\$y\\`z\\`\\\\%%"')

    def test_desktop_e_autostart(self):
        with tempfile.TemporaryDirectory() as t:
            d, i = puro.instalar_local(RAIZ, t)
            txt = open(d).read()
            self.assertIn(os.path.join(RAIZ, "myprox2.py"), txt)
            self.assertTrue(os.path.exists(i))
            self.assertEqual(len(puro.desinstalar_local(t)), 2)
            self.assertFalse(puro.autostart_ativo(t))
            puro.definir_autostart(True, "myprox2", t)
            self.assertTrue(puro.autostart_ativo(t))
            self.assertIn("--background", open(puro.caminho_autostart(t)).read())
            puro.definir_autostart(False, "myprox2", t)
            self.assertFalse(puro.autostart_ativo(t))

    def test_comando_app(self):
        self.assertEqual(puro.comando_app("/usr/share/prox2"), "myprox2")
        self.assertEqual(puro.comando_app(RAIZ), f'python3 {puro.escapar_exec(os.path.join(RAIZ, "myprox2.py"))}')

    def test_autostart_instalado_regrava_exec_antigo(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertFalse(puro.atualizar_autostart("myprox2", t))
            puro.definir_autostart(True, puro.comando_app(RAIZ), t)
            self.assertTrue(puro.atualizar_autostart("myprox2", t))
            self.assertIn("Exec=myprox2 --background\n", open(puro.caminho_autostart(t)).read())
            self.assertFalse(puro.atualizar_autostart("myprox2", t))


if __name__ == "__main__":
    unittest.main()
