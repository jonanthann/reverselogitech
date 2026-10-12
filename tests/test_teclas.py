import unittest

from app import teclas


class TestTeclas(unittest.TestCase):
    def test_letras_e_numeros(self):
        self.assertEqual(teclas.evdev_para_hid(30), 4)    # A
        self.assertEqual(teclas.evdev_para_hid(44), 29)   # Z
        self.assertEqual(teclas.evdev_para_hid(16), 20)   # Q
        self.assertEqual(teclas.evdev_para_hid(2), 30)    # 1
        self.assertEqual(teclas.evdev_para_hid(11), 39)   # 0

    def test_funcao_e_navegacao(self):
        self.assertEqual(teclas.evdev_para_hid(59), 58)   # F1
        self.assertEqual(teclas.evdev_para_hid(68), 67)   # F10
        self.assertEqual(teclas.evdev_para_hid(87), 68)   # F11
        self.assertEqual(teclas.evdev_para_hid(88), 69)   # F12
        self.assertEqual(teclas.evdev_para_hid(183), 104)  # F13
        self.assertEqual(teclas.evdev_para_hid(194), 115)  # F24
        self.assertEqual(teclas.evdev_para_hid(28), 40)   # Enter
        self.assertEqual(teclas.evdev_para_hid(57), 44)   # Espaço
        self.assertEqual(teclas.evdev_para_hid(103), 82)  # seta cima

    def test_alfabeto_completo_sem_repeticao(self):
        usos = [teclas.evdev_para_hid(c) for c in (30, 48, 46, 32, 18, 33, 34, 35, 23, 36, 37, 38, 50,
                                                   49, 24, 25, 16, 19, 31, 20, 22, 47, 17, 45, 21, 44)]
        self.assertEqual(usos, list(range(4, 30)))

    def test_nao_suportada_e_modificadores(self):
        self.assertIsNone(teclas.evdev_para_hid(29))      # Ctrl sozinho
        self.assertIsNone(teclas.evdev_para_hid(9999))
        self.assertEqual(teclas.mod_de_evdev(29), 1)
        self.assertEqual(teclas.mod_de_evdev(54), 2)
        self.assertEqual(teclas.mod_de_evdev(100), 4)
        self.assertEqual(teclas.mod_de_evdev(125), 8)
        self.assertEqual(teclas.mod_de_evdev(30), 0)

    def test_nomes(self):
        self.assertEqual(teclas.rotulo_tecla(0, 4), "A")
        self.assertEqual(teclas.rotulo_tecla(3, 44), "Ctrl+Shift+Espaço")
        self.assertEqual(teclas.nome_tecla(200), "HID 200")
