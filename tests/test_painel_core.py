import json
import os
import tempfile
import threading
import unittest

import perfil
from prox2 import com_crc, crc_ok
from painel_core import ErroPainel, Painel
from tests.mouse_falso import MouseFalso

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(RAIZ, "prox2_backup_perfis.json")) as f:
    B = {int(k, 16): bytes.fromhex(v) for k, v in json.load(f).items()}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        s = dict(B)
        s[perfil.ROM_FABRICA] = B[3][:-2] + b"\x00\x03"
        self.mouse = MouseFalso(s, em_uso=1)
        self.backup = os.path.join(self.tmp.name, "bk.json")
        self.painel = Painel(self.mouse, os.path.join(self.tmp.name, "dados"), backup=self.backup)

    def hist(self):
        d = os.path.join(self.tmp.name, "dados", "historico")
        return os.listdir(d) if os.path.isdir(d) else []


def estragar_crc(mouse, sec):
    d = bytearray(mouse.setores[sec])
    d[-1] ^= 0xFF
    mouse.setores[sec] = bytes(d)


class TestCorrecoesFinais(Base):
    def test_restaurar_sem_backup_com_vaga_crc_ruim(self):
        estragar_crc(self.mouse, 2)
        self.assertFalse(os.path.exists(self.backup))
        self.painel.restaurar(2)
        self.assertTrue(os.path.exists(self.backup))
        self.assertTrue(crc_ok(self.mouse.setores[2]))
        with open(self.backup) as f:
            bk = json.load(f)
        self.assertEqual(sorted(bk), [f"{s:#06x}" for s in range(6)])

    def test_backup_com_setor_crc_ruim_guarda_os_bons_integros(self):
        estragar_crc(self.mouse, 2)
        self.painel._salvar_backup()
        with open(self.backup) as f:
            bk = json.load(f)
        self.assertEqual(bk["0x0002"], self.mouse.setores[2].hex())
        for s in (0, 1, 3, 4, 5):
            self.assertEqual(bk[f"{s:#06x}"], B[s].hex())

    def test_backup_prefere_leitura_com_crc(self):
        # leitura crc=False devolve lixo passageiro, crc=True (com releitura) devolve o setor bom
        bom = self.mouse.setores[3]
        ruim = bytearray(bom)
        ruim[10] ^= 0xFF
        orig = self.mouse.ler_setor

        def ler(sec, crc=True):
            if sec == 3 and not crc:
                return bytes(ruim)
            return orig(sec, crc)

        self.mouse.ler_setor = ler
        self.painel._salvar_backup()
        with open(self.backup) as f:
            self.assertEqual(json.load(f)["0x0003"], bom.hex())

    def test_erro_original_nao_e_trocado_por_timeout(self):
        self.mouse.falhar_gravacao_em = 1
        orig = self.mouse.definir_perfil

        def definir(sec):
            if sec == self.mouse.em_uso and self.mouse.falhar_gravacao_em == 1:
                raise TimeoutError("sem resposta")
            orig(sec)
        self.mouse.definir_perfil = definir
        with self.assertRaises(ErroPainel):
            self.painel.gravar(1, dpi=800)

    def test_vaga_integra_com_leitura_ruim_transitoria(self):
        reais = self.mouse.ler_setor
        n = {"c": 0}

        def ler(sec, crc=True):
            if sec == 2 and crc and n["c"] == 0:
                n["c"] += 1
                raise IOError("CRC ruim")
            return reais(sec, crc)
        self.mouse.ler_setor = ler
        antes = self.mouse.setores[2]
        self.painel.gravar(2, dpi=800)
        self.assertEqual(perfil.ler_vaga(self.mouse.setores[2])["dpis"], [800])
        self.assertNotEqual(antes, self.mouse.setores[2])

    def test_vaga_corrompida_ligada_copia_sem_nome(self):
        s0 = self.mouse.setores[0]
        s0 = perfil.diretorio_com_ativo(s0, 2, False)
        self.mouse.setores[0] = s0
        estragar_crc(self.mouse, 2)
        self.painel.gravar(2, ativa=True)
        self.assertEqual(perfil.ler_vaga(self.mouse.setores[2])["nome"] in (None, ""), True)

    def test_listar_ordena_e_avisa_diretorio(self):
        r = self.painel.listar()
        self.assertEqual([v["sec"] for v in r["vagas"]], sorted(v["sec"] for v in r["vagas"]))
        self.assertIsNone(r["aviso_diretorio"])
        self.mouse.diretorio = lambda: [(3, True), (1, True), (2, True), (0, True)]
        r = self.painel.listar()
        self.assertEqual([v["sec"] for v in r["vagas"]], [1, 2, 3])
        self.assertIn("4 entradas", r["aviso_diretorio"])


class TestPainel(Base):
    def test_listar(self):
        r = self.painel.listar()
        self.assertEqual(len(r["vagas"]), 5)
        v = {x["sec"]: x for x in r["vagas"]}
        self.assertTrue(v[1]["ativa"] and v[2]["ativa"])
        self.assertTrue(v[1]["em_uso"])
        self.assertEqual(v[1]["nome"], "Vaga 1")

    def test_gravar_dpi(self):
        orig = self.mouse.setores[1]
        self.painel.gravar(1, dpi=800)
        self.assertEqual(perfil.ler_vaga(self.mouse.setores[1])["dpis"], [800])
        self.assertEqual(len(self.hist()), 1)
        self.assertTrue(os.path.exists(self.backup))
        defs = [e for e in self.mouse.log if e[0] == "definir"]
        self.assertEqual(defs, [("definir", 1), ("definir", 1)])
        self.assertNotEqual(orig, self.mouse.setores[1])

    def test_backup_mantido(self):
        with open(self.backup, "w") as f:
            f.write("{}")
        self.painel.gravar(1, dpi=800)
        with open(self.backup) as f:
            self.assertEqual(f.read(), "{}")

    def test_definir_original_depois(self):
        self.painel.gravar(2, dpi=800)
        defs = [e for e in self.mouse.log if e[0] == "definir"]
        self.assertEqual(defs, [("definir", 2), ("definir", 1)])

    def test_falha_regrava_original(self):
        orig = self.mouse.setores[1]
        self.mouse.falhar_gravacao_em = 1
        with self.assertRaises(ErroPainel):
            self.painel.gravar(1, dpi=800)
        self.assertEqual(self.mouse.setores[1], orig)
        self.assertEqual(self.mouse.log[-1], ("definir", 1))

    def test_desligar_em_uso(self):
        antes = dict(self.mouse.setores)
        with self.assertRaises(ErroPainel):
            self.painel.gravar(1, ativa=False)
        self.assertEqual(self.mouse.setores, antes)

    def test_desligar_ultima(self):
        s0 = perfil.diretorio_com_ativo(B[0], 1, False)
        self.mouse.setores[0] = s0
        self.mouse.em_uso = 2
        with self.assertRaises(ErroPainel):
            self.painel.gravar(2, ativa=False)

    def test_ligar_vaga_um_dpi(self):
        self.painel.gravar(3, ativa=True, dpi=1000, um_dpi_so=True)
        self.assertIn((3, True), self.mouse.diretorio())
        self.assertEqual(perfil.ler_vaga(self.mouse.setores[3])["dpis"], [1000])
        gravs = [e for e in self.mouse.log if e[0] == "gravar"]
        self.assertEqual(gravs, [("gravar", 3), ("gravar", 0)])

    def test_nome(self):
        self.painel.gravar(1, nome="Dia a dia")
        self.assertEqual(perfil.ler_vaga(self.mouse.setores[1])["nome"], "Dia a dia")
        v = {x["sec"]: x for x in self.painel.listar()["vagas"]}
        self.assertEqual(v[1]["nome"], "Dia a dia")
        self.assertEqual(v[3]["nome"], "Vaga 3")

    def test_ativa_ja_ativa_nao_grava_setor0(self):
        self.painel.gravar(1, ativa=True)
        self.assertNotIn(("gravar", 0), self.mouse.log)

    def test_ligar_grava_setor0_com_crc(self):
        self.painel.gravar(3, ativa=True)
        self.assertIn(("gravar", 0), self.mouse.log)
        self.assertTrue(crc_ok(self.mouse.setores[0]))

    def test_usar_agora_desligada(self):
        with self.assertRaises(ErroPainel):
            self.painel.usar_agora(3)

    def test_usar_agora(self):
        self.painel.usar_agora(2)
        self.assertEqual(self.mouse.em_uso, 2)

    def test_restaurar(self):
        self.painel.restaurar(1)
        self.assertEqual(self.mouse.setores[1], com_crc(self.mouse.setores[perfil.ROM_FABRICA]))

    def test_threads(self):
        ts = [threading.Thread(target=self.painel.gravar, args=(s,), kwargs={"dpi": 800}) for s in (1, 2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        lg = [e for e in self.mouse.log if e[0] != "perfil_ativo"]
        self.assertEqual(len(lg), 6)
        for i in (0, 3):
            self.assertEqual(lg[i][0], "gravar")
            self.assertEqual(lg[i + 1], ("definir", lg[i][1]))
            self.assertEqual(lg[i + 2][0], "definir")

    def test_falha_setor0_regrava_vaga(self):
        self.mouse.falhar_gravacao_em = 0
        orig = self.mouse.setores[2]
        with self.assertRaises(ErroPainel):
            self.painel.gravar(2, ativa=False, dpi=800)
        self.assertEqual(self.mouse.setores[2], orig)
        orig3 = self.mouse.setores[3]
        with self.assertRaises(ErroPainel):
            self.painel.gravar(3, ativa=True, dpi=1000, um_dpi_so=True)
        self.assertEqual(self.mouse.setores[3], orig3)

    def test_crc_ruim(self):
        b = bytearray(self.mouse.setores[2])
        b[10] ^= 0xFF
        self.mouse.setores[2] = bytes(b)
        v = {x["sec"]: x for x in self.painel.listar()["vagas"]}
        self.assertTrue(v[2]["aviso"])
        with self.assertRaises(ErroPainel) as c:
            self.painel.gravar(2, dpi=800)
        self.assertIn("restaur", str(c.exception).lower())


if __name__ == "__main__":
    unittest.main()
