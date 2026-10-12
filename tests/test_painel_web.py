import contextlib
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

import perfil
import prox2
from painel_core import Painel
from painel_web import criar_servidor
from tests.mouse_falso import MouseFalso

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(RAIZ, "tests", "dados", "prox2_backup_perfis.json")) as f:
    B = {int(k, 16): bytes.fromhex(v) for k, v in json.load(f).items()}


class MouseDormindo(MouseFalso):
    def ler_setor(self, sec, crc=True):
        raise TimeoutError("sem resposta")

    def diretorio(self):
        raise TimeoutError("sem resposta")


class Base(unittest.TestCase):
    classe_mouse = MouseFalso

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        s = dict(B)
        s.update({m: b"\xff" * 255 for m in range(6, 16)})
        s[perfil.ROM_FABRICA] = B[3][:-2] + b"\x00\x03"
        self.mouse = self.classe_mouse(s, em_uso=1)
        painel = Painel(self.mouse, os.path.join(self.tmp.name, "dados"),
                        backup=os.path.join(self.tmp.name, "bk.json"))
        self.srv, url = criar_servidor(painel)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        self.token = url.split("token=")[1]
        t = threading.Thread(target=self.srv.serve_forever, daemon=True)
        t.start()
        self.addCleanup(t.join)
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def req(self, metodo, caminho, corpo=None, token=True, headers=None):
        h = dict(headers or {})
        if token:
            h["X-Token"] = self.token
        dados = None
        if corpo is not None:
            dados = json.dumps(corpo).encode()
            h["Content-Type"] = "application/json"
        r = urllib.request.Request(self.base + caminho, data=dados, method=metodo, headers=h)
        try:
            with urllib.request.urlopen(r) as resp:
                txt = resp.read()
                return resp.status, (json.loads(txt) if txt else None)
        except urllib.error.HTTPError as e:
            txt = e.read()
            return e.code, (json.loads(txt) if txt else None)


class TestWeb(Base):
    def test_sem_token(self):
        self.assertEqual(self.req("GET", "/api/vagas", token=False)[0], 403)

    def test_listar(self):
        c, d = self.req("GET", "/api/vagas")
        self.assertEqual(c, 200)
        self.assertEqual(len(d["vagas"]), 5)

    def test_token_nao_ascii(self):
        c, _ = self.req("GET", "/?token=%C3%A9", token=False)
        self.assertEqual(c, 403)

    def test_content_length_negativo(self):
        c, _ = self.req("POST", "/api/vagas/1", {}, headers={"Content-Length": "-1"})
        self.assertEqual(c, 400)

    def test_dpi_invalido(self):
        c, d = self.req("POST", "/api/vagas/1", {"niveis": [1601]})
        self.assertEqual(c, 400)
        self.assertIn("1610", d["erro"])

    def test_origin_errada(self):
        antes = self.mouse.setores[1]
        c, _ = self.req("POST", "/api/vagas/1", {"niveis": [800]}, headers={"Origin": "http://evil.example"})
        self.assertEqual(c, 403)
        self.assertEqual(self.mouse.setores[1], antes)

    def test_gravar(self):
        c, d = self.req("POST", "/api/vagas/1", {"niveis": [800]})
        self.assertEqual(c, 200)
        self.assertEqual(d["dpis"], [800])

    def test_tipos_invalidos(self):
        antes = dict(self.mouse.setores)
        for corpo in ({"ativa": 0}, {"niveis": "800"}, {"ativa": "false"}, {"niveis": [True]}, {"nome": 5}):
            c, d = self.req("POST", "/api/vagas/1", corpo)
            self.assertEqual(c, 400, corpo)
            self.assertIn("inválido", d["erro"])
        self.assertEqual(self.mouse.setores, antes)

    def test_macros_rotas(self):
        passos = [{"tipo": "aperta", "mod": 0, "tecla": 4}, {"tipo": "solta", "mod": 0, "tecla": 4}]
        c, d = self.req("POST", "/api/macros", {"passos": passos})
        self.assertEqual((c, d), (200, {"sec": 7}))  # o 6 é referenciado pela vaga 2
        c, d = self.req("POST", "/api/macros", {"texto": "Ab 1", "espera_ms": 20})
        self.assertEqual((c, d), (200, {"sec": 8}))
        c, d = self.req("POST", "/api/macros/8", {"texto": "x"})
        self.assertEqual((c, d), (200, {"sec": 8}))
        c, d = self.req("GET", "/api/vagas")
        self.assertEqual([m["estado"] for m in d["macros"]][1:4], ["ok", "ok", "vazia"])
        c, d = self.req("POST", "/api/macros/8/apagar", {})
        self.assertEqual((c, d), (200, {"sec": 8}))

    def test_macros_erros(self):
        for caminho, corpo in (("/api/macros", {}), ("/api/macros", {"passos": "x"}),
                               ("/api/macros", {"passos": [1]}), ("/api/macros", {"passos": []}),
                               ("/api/macros", {"texto": "é"}), ("/api/macros", {"texto": 5}),
                               ("/api/macros", {"texto": "a", "espera_ms": 0}),
                               ("/api/macros/5", {"texto": "a"}), ("/api/macros/6/apagar", {})):
            c, d = self.req("POST", caminho, corpo)
            self.assertEqual(c, 400, (caminho, corpo))
            self.assertIn("erro", d)
        self.assertEqual(self.req("POST", "/api/macros/abc", {})[0], 404)

    def test_campos_novos_tipos(self):
        for corpo in ({"botoes": "x"}, {"gshift": [1]}, {"niveis": [800.5]}, {"dpi_padrao": "1"}):
            self.assertEqual(self.req("POST", "/api/vagas/1", corpo)[0], 400, corpo)
        c, d = self.req("POST", "/api/vagas/1", {"niveis": [800, 1600], "dpi_padrao": 1})
        self.assertEqual(c, 200)
        self.assertEqual(d["niveis"], [800, 1600])
        c, d = self.req("POST", "/api/vagas/1", {"botoes": [{"tipo": "desligado"}] * 5})
        self.assertEqual(c, 400)

    def test_nome_real(self):
        v = self.req("GET", "/api/vagas")[1]["vagas"]
        self.assertTrue(all("nome_real" in x for x in v))

    def test_servir_espera_gravacao(self):
        from painel_web import servir
        import time
        srv2, _ = criar_servidor(self.srv.painel)
        self.srv.painel.lock.acquire()
        threading.Timer(0.5, self.srv.painel.lock.release).start()
        threading.Timer(0.1, srv2.shutdown).start()
        t0 = time.monotonic()
        servir(srv2)
        self.assertGreaterEqual(time.monotonic() - t0, 0.45)

    def test_pagina_com_token(self):
        r = urllib.request.Request(self.base + "/?token=" + self.token)
        with urllib.request.urlopen(r) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("painel_token_", resp.headers["Set-Cookie"])
            self.assertIn("HttpOnly", resp.headers["Set-Cookie"])

    def test_pagina_ignora_cookie_antigo(self):
        porta = self.base.rsplit(":", 1)[1]
        r = urllib.request.Request(self.base + "/?token=" + self.token, headers={
            "Cookie": f"painel_token_{porta}=antigo; token=antigo"})
        with urllib.request.urlopen(r) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn(f"painel_token_{porta}={self.token}", resp.headers["Set-Cookie"])

    def test_sinal(self):
        self.assertEqual(self.req("POST", "/api/sinal")[0], 204)


class TestWebMouseDormindo(Base):
    classe_mouse = MouseDormindo

    def test_503(self):
        c, d = self.req("GET", "/api/vagas")
        self.assertEqual(c, 503)
        self.assertEqual(d["erro"], "mouse não encontrado")


class MouseInalcancavelFalso(MouseFalso):
    def ler_setor(self, sec, crc=True):
        raise prox2.MouseInalcancavel("Mouse desligado ou fora de alcance.")


class MouseTravado(MouseFalso):
    @contextlib.contextmanager
    def transacao(self, gravando=False):
        raise prox2.TravaOcupada("Outro programa está gravando no mouse.")
        yield


class TestWebErroMouse(Base):
    classe_mouse = MouseInalcancavelFalso

    def test_inalcancavel_503(self):
        c, d = self.req("GET", "/api/vagas")
        self.assertEqual(c, 503)
        self.assertIn("fora de alcance", d["erro"])


class TestWebTravaOcupada(Base):
    classe_mouse = MouseTravado

    def test_trava_ocupada_409(self):
        c, d = self.req("POST", "/api/vagas/1", {"polling_hz": 500})
        self.assertEqual(c, 409)


if __name__ == "__main__":
    unittest.main()
