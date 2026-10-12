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
        s.update({m: b"\xff" * 255 for m in range(6, 16)})
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


class TestTransacao(Base):
    def test_operacoes_de_escrita_usam_transacao_gravando(self):
        for op in (lambda: self.painel.gravar(1, polling_hz=500), lambda: self.painel.restaurar(2)):
            self.mouse.transacoes.clear()
            op()
            self.assertIn(True, self.mouse.transacoes)

    def test_apagar_macro_usa_transacao(self):
        self.mouse.transacoes.clear()
        self.painel.apagar_macro(8)
        self.assertIn(True, self.mouse.transacoes)

    def test_erro_mouse_dispara_rollback(self):
        from prox2 import MouseInalcancavel
        original = self.mouse.setores[1]
        grav = self.mouse.gravar_verificado

        def falha(sec, data):
            if sec == 1 and self.mouse.setores[1] == original:
                self.mouse.setores[1] = bytes(data)  # gravou, mas depois o mouse some
                raise MouseInalcancavel("sumiu")
            grav(sec, data)
        self.mouse.gravar_verificado = falha
        with self.assertRaises(ErroPainel):
            self.painel.gravar(1, polling_hz=500)
        self.assertEqual(self.mouse.setores[1], original)


class TestCorrecoesFinais(Base):
    def test_restaurar_sem_backup_com_vaga_crc_ruim(self):
        estragar_crc(self.mouse, 2)
        self.assertFalse(os.path.exists(self.backup))
        self.painel.restaurar(2)
        self.assertTrue(os.path.exists(self.backup))
        self.assertTrue(crc_ok(self.mouse.setores[2]))
        with open(self.backup) as f:
            bk = json.load(f)
        self.assertEqual(sorted(bk), [f"{s:#06x}" for s in range(16)])

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
            self.painel.gravar(1, niveis=[800])

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
        self.painel.gravar(2, niveis=[800])
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
        self.painel.gravar(1, niveis=[800])
        self.assertEqual(perfil.ler_vaga(self.mouse.setores[1])["dpis"], [800])
        self.assertEqual(len(self.hist()), 1)
        self.assertTrue(os.path.exists(self.backup))
        defs = [e for e in self.mouse.log if e[0] == "definir"]
        self.assertEqual(defs, [("definir", 1), ("definir", 1)])
        self.assertNotEqual(orig, self.mouse.setores[1])

    def test_backup_mantido(self):
        with open(self.backup, "w") as f:
            f.write("{}")
        self.painel.gravar(1, niveis=[800])
        with open(self.backup) as f:
            self.assertEqual(f.read(), "{}")

    def test_definir_original_depois(self):
        self.painel.gravar(2, niveis=[800])
        defs = [e for e in self.mouse.log if e[0] == "definir"]
        self.assertEqual(defs, [("definir", 2), ("definir", 1)])

    def test_falha_regrava_original(self):
        orig = self.mouse.setores[1]
        self.mouse.falhar_gravacao_em = 1
        with self.assertRaises(ErroPainel):
            self.painel.gravar(1, niveis=[800])
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
        self.painel.gravar(3, ativa=True, niveis=[1000])
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
        ts = [threading.Thread(target=self.painel.gravar, args=(s,), kwargs={"niveis": [800]}) for s in (1, 2)]
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
            self.painel.gravar(2, ativa=False, niveis=[800])
        self.assertEqual(self.mouse.setores[2], orig)
        orig3 = self.mouse.setores[3]
        with self.assertRaises(ErroPainel):
            self.painel.gravar(3, ativa=True, niveis=[1000])
        self.assertEqual(self.mouse.setores[3], orig3)

    def test_crc_ruim(self):
        b = bytearray(self.mouse.setores[2])
        b[10] ^= 0xFF
        self.mouse.setores[2] = bytes(b)
        v = {x["sec"]: x for x in self.painel.listar()["vagas"]}
        self.assertTrue(v[2]["aviso"])
        with self.assertRaises(ErroPainel) as c:
            self.painel.gravar(2, niveis=[800])
        self.assertIn("restaur", str(c.exception).lower())


class TestMacros(Base):
    PASSOS = [{"tipo": "aperta", "mod": 0, "tecla": 4}, {"tipo": "solta", "mod": 0, "tecla": 4}]

    def liga(self, sec_vaga, sec_macro, i=3, camada="botoes"):
        v = perfil.ler_vaga(self.mouse.setores[sec_vaga])
        lista = list(v[camada])
        lista[i] = {"tipo": "macro", "sec": sec_macro, "offset": 0}
        self.painel.gravar(sec_vaga, **{camada: lista})

    def test_listar_vaga_2_com_macro_vazia(self):
        r = self.painel.listar()
        v = {x["sec"]: x for x in r["vagas"]}
        b = v[2]["botoes"][3]
        self.assertEqual((b["tipo"], b["sec"], b["macro_estado"]), ("macro", 6, "vazia"))
        self.assertEqual(b["aviso"], "Botão voltar: macro no setor 6 está vazia, o botão não faz nada")
        self.assertIn("G-Shift, botão voltar", v[2]["gshift"][3]["aviso"])
        self.assertEqual([m["sec"] for m in r["macros"]], list(range(6, 16)))
        self.assertEqual(r["macros"][0]["usada_por"][0], {"vaga": 2, "camada": "normal", "botao": "voltar", "offset": 0})
        self.assertEqual(v[3]["niveis"], [800, 1200, 1600, 2400, 3200])

    def test_especial_testado(self):
        l = list(perfil.ler_vaga(self.mouse.setores[1])["gshift"])
        l[0] = {"tipo": "especial", "codigo": "ciclo_dpi"}
        l[1] = {"tipo": "especial", "codigo": "gshift"}
        self.painel.gravar(1, gshift=l)
        g = {x["sec"]: x for x in self.painel.listar()["vagas"]}[1]["gshift"]
        self.assertIs(g[0]["testado"], True)
        self.assertIs(g[1]["testado"], False)

    def test_alocacao_pula_referenciado(self):
        # setor 6 está vazio mas referenciado pela vaga 2: a nova macro vai para o 7
        self.assertEqual(self.painel.gravar_macro(None, self.PASSOS), 7)
        self.assertEqual(self.painel.gravar_macro(None, self.PASSOS), 8)
        m = {x["sec"]: x for x in self.painel.listar()["macros"]}
        self.assertEqual(m[7]["estado"], "ok")
        self.assertEqual(len(m[7]["passos"]), 2)
        self.assertTrue(crc_ok(self.mouse.setores[7]))
        self.assertEqual(len([h for h in self.hist() if "setor7" in h]), 1)

    def test_gravar_macro_recusa_referencia_com_offset(self):
        # vaga 2 G-Shift voltar aponta para o setor 6 com offset 2
        d = bytearray(self.mouse.setores[2])
        o = perfil.CAMADA_GSHIFT + 4 * 3
        d[o:o + 4] = bytes([0x00, 0x06, 0x00, 0x02])
        self.mouse.setores[2] = perfil.com_crc(bytes(d))
        with self.assertRaises(ErroPainel) as c:
            self.painel.gravar_macro(6, self.PASSOS)
        self.assertIn("vaga 2", str(c.exception))
        self.assertIn("G-Shift", str(c.exception))
        self.assertEqual(self.mouse.setores[6], b"\xff" * 255)

    def test_rollback_macro_sem_crc_volta_vazia_com_crc(self):
        original = self.mouse.gravar_verificado
        falhou = []

        def gravar(sec, data):
            if sec == 9 and not falhou:
                falhou.append(1)
                raise IOError("falha simulada")
            original(sec, data)
        self.mouse.gravar_verificado = gravar
        with self.assertRaises(ErroPainel):
            self.painel.gravar_macro(9, self.PASSOS)
        self.assertEqual(self.mouse.setores[9], perfil.com_crc(b"\xff" * 255))

    def test_alocacao_prefere_vazia_a_invalida(self):
        self.mouse.setores[7] = b"\x77" * 255
        self.assertEqual(self.painel.gravar_macro(None, self.PASSOS), 8)

    def test_macro_invalida_e_orfa(self):
        for s in range(7, 16):  # sem setor vazio, lixo sem referência é reaproveitado
            self.mouse.setores[s] = b"\x77" * 255
        self.assertEqual(self.painel.gravar_macro(None, self.PASSOS), 7)
        self.painel.gravar_macro(9, self.PASSOS)
        m = {x["sec"]: x for x in self.painel.listar()["macros"]}
        self.assertEqual(m[9]["usada_por"], [])  # órfã aparece na lista
        self.assertEqual(m[9]["estado"], "ok")

    def test_passos_invalidos(self):
        with self.assertRaises(ErroPainel):
            self.painel.gravar_macro(None, [self.PASSOS[0]])
        with self.assertRaises(ErroPainel):
            self.painel.gravar_macro(5, self.PASSOS)
        self.assertEqual(self.hist(), [])

    def test_sem_setor_livre(self):
        for s in range(7, 16):
            self.painel.gravar_macro(s, self.PASSOS)
        # o 6 está referenciado pela vaga 2
        with self.assertRaises(ErroPainel):
            self.painel.gravar_macro(None, self.PASSOS)

    def test_apagar(self):
        self.painel.gravar_macro(8, self.PASSOS)
        self.painel.apagar_macro(8)
        self.assertEqual(self.mouse.setores[8], perfil.com_crc(b"\xff" * 255))
        n = len(self.hist())
        self.painel.apagar_macro(8)  # já vazia: nada a gravar
        self.assertEqual(len(self.hist()), n)

    def test_apagar_referenciado_recusado(self):
        with self.assertRaises(ErroPainel) as c:
            self.painel.apagar_macro(6)
        self.assertIn("vaga 2", str(c.exception))
        self.assertIn("voltar", str(c.exception))
        self.assertEqual(self.mouse.setores[6], b"\xff" * 255)

    def test_ordem_macro_antes_do_perfil(self):
        self.painel.gravar_macro(8, self.PASSOS)
        self.liga(1, 8)
        gravs = [e[1] for e in self.mouse.log if e[0] == "gravar"]
        self.assertEqual(gravs, [8, 1])
        self.assertEqual(perfil.ler_vaga(self.mouse.setores[1])["botoes"][3],
                         {"tipo": "macro", "sec": 8, "offset": 0})

    def test_ligar_macro_vazia_recusado_mas_edicao_do_perfil_2_ok(self):
        l = list(perfil.ler_vaga(self.mouse.setores[1])["botoes"])
        l[3] = {"tipo": "macro", "sec": 9, "offset": 0}
        with self.assertRaises(ErroPainel) as c:
            self.painel.gravar(1, botoes=l)
        self.assertIn("macro", str(c.exception))
        # perfil 2 já aponta para a macro vazia 6: editar outro campo continua permitido
        b2 = perfil.ler_vaga(self.mouse.setores[2])["botoes"]
        self.painel.gravar(2, botoes=b2, lod=3)
        self.assertEqual(perfil.ler_vaga(self.mouse.setores[2])["lod"], 3)

    def test_recarrega_perfil_em_uso(self):
        self.painel.gravar_macro(8, self.PASSOS)
        self.liga(1, 8)
        self.mouse.log.clear()
        self.painel.gravar_macro(8, self.PASSOS + [{"tipo": "espera", "ms": 10}])
        self.assertEqual(self.mouse.log.count(("definir", 1)), 1)
        self.mouse.log.clear()
        self.painel.gravar_macro(9, self.PASSOS)  # não referenciada: sem recarga
        self.assertNotIn("definir", [e[0] for e in self.mouse.log])

    def test_backup_macros_a_parte(self):
        with open(self.backup, "w") as f:
            json.dump({f"{s:#06x}": B[s].hex() for s in range(6)}, f)
        self.painel.gravar_macro(8, self.PASSOS)
        arq = os.path.join(self.tmp.name, "dados", "backup_macros.json")
        with open(arq) as f:
            bk = json.load(f)
        self.assertEqual(sorted(bk), [f"{s:#06x}" for s in range(6, 16)])
        self.assertEqual(bk["0x0008"], ("ff" * 255))
        self.painel.gravar_macro(9, self.PASSOS)
        with open(arq) as f:
            self.assertEqual(json.load(f), bk)  # não sobrescreve

    def test_backup_novo_cobre_macros(self):
        self.painel.gravar_macro(8, self.PASSOS)
        with open(self.backup) as f:
            self.assertEqual(len(json.load(f)), 16)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "dados", "backup_macros.json")))

    def test_gravar_niveis_e_indices(self):
        self.painel.gravar(3, niveis=[800, 1600], dpi_padrao=1, dpi_shift=0)
        v = {x["sec"]: x for x in self.painel.listar()["vagas"]}[3]
        self.assertEqual((v["niveis"], v["dpi_padrao"], v["dpi_shift"]), ([800, 1600], 1, 0))
        with self.assertRaises(ErroPainel):
            self.painel.gravar(3, dpi_padrao=2)


if __name__ == "__main__":
    unittest.main()
