import os
import tempfile
import unittest

import caminhos


class TestCaminhos(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dados = os.path.join(self.tmp.name, "xdg")
        antigo = os.environ.get("XDG_DATA_HOME")
        os.environ["XDG_DATA_HOME"] = self.dados
        self.addCleanup(lambda: os.environ.__setitem__("XDG_DATA_HOME", antigo) if antigo is not None else os.environ.pop("XDG_DATA_HOME", None))
        self.raiz = os.path.join(self.tmp.name, "repo")
        os.makedirs(os.path.join(self.raiz, "painel_dados", "historico"))
        with open(os.path.join(self.raiz, "prox2_backup_perfis.json"), "w") as f:
            f.write("{}")
        with open(os.path.join(self.raiz, "painel_dados", "backup_macros.json"), "w") as f:
            f.write("velho")

    def test_instalado(self):
        self.assertTrue(caminhos.instalado("/usr/share/prox2"))
        self.assertFalse(caminhos.instalado("/home/x/prox2"))

    def test_caminhos_na_pasta_dados(self):
        self.assertEqual(caminhos.arquivo_backup(), os.path.join(self.dados, "myproX2", "prox2_backup_perfis.json"))
        self.assertEqual(caminhos.pasta_painel(), os.path.join(self.dados, "myproX2", "painel_dados"))

    def test_migrar_copia_sem_apagar(self):
        caminhos.migrar(self.raiz)
        self.assertTrue(os.path.isfile(caminhos.arquivo_backup()))
        self.assertTrue(os.path.isfile(os.path.join(caminhos.pasta_painel(), "backup_macros.json")))
        self.assertTrue(os.path.isfile(os.path.join(self.raiz, "prox2_backup_perfis.json")))
        self.assertTrue(os.path.isdir(os.path.join(self.raiz, "painel_dados", "historico")))

    def test_migrar_descarta_tmp_parcial_e_completa(self):
        parcial = caminhos.pasta_painel() + ".tmp"
        os.makedirs(parcial)
        with open(os.path.join(parcial, "lixo"), "w") as f:
            f.write("x")
        caminhos.migrar(self.raiz)
        self.assertTrue(os.path.isfile(os.path.join(caminhos.pasta_painel(), "backup_macros.json")))
        self.assertFalse(os.path.exists(os.path.join(caminhos.pasta_painel(), "lixo")))
        self.assertFalse(os.path.exists(parcial))
        self.assertFalse(os.path.exists(caminhos.arquivo_backup() + ".tmp"))

    def test_migrar_nao_sobrescreve(self):
        os.makedirs(caminhos.pasta_painel())
        with open(caminhos.arquivo_backup(), "w") as f:
            f.write("meu")
        caminhos.migrar(self.raiz)
        with open(caminhos.arquivo_backup()) as f:
            self.assertEqual(f.read(), "meu")
        self.assertEqual(os.listdir(caminhos.pasta_painel()), [])

    def test_migrar_nao_roda_instalado(self):
        from unittest import mock
        with mock.patch("caminhos.instalado", return_value=True):
            caminhos.migrar(self.raiz)
        self.assertFalse(os.path.exists(caminhos.arquivo_backup()))
        self.assertFalse(os.path.exists(caminhos.pasta_painel()))


if __name__ == "__main__":
    unittest.main()
