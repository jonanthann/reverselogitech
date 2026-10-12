import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

import perfil
from painel_core import Painel
from painel_web import criar_servidor
from tests.mouse_falso import MouseFalso

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(RAIZ, "prox2_backup_perfis.json")) as f:
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
        c, d = self.req("POST", "/api/vagas/1", {"dpi": 1601})
        self.assertEqual(c, 400)
        self.assertIn("1610", d["erro"])

    def test_origin_errada(self):
        antes = self.mouse.setores[1]
        c, _ = self.req("POST", "/api/vagas/1", {"dpi": 800}, headers={"Origin": "http://evil.example"})
        self.assertEqual(c, 403)
        self.assertEqual(self.mouse.setores[1], antes)

    def test_gravar(self):
        c, d = self.req("POST", "/api/vagas/1", {"dpi": 800})
        self.assertEqual(c, 200)
        self.assertEqual(d["dpis"], [800])

    def test_tipos_invalidos(self):
        antes = dict(self.mouse.setores)
        for corpo in ({"ativa": 0}, {"dpi": "800"}, {"ativa": "false"}, {"dpi": True}, {"nome": 5}):
            c, d = self.req("POST", "/api/vagas/1", corpo)
            self.assertEqual(c, 400, corpo)
            self.assertIn("inválido", d["erro"])
        self.assertEqual(self.mouse.setores, antes)

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


if __name__ == "__main__":
    unittest.main()
