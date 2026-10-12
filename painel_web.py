"""Servidor HTTP local do painel (só 127.0.0.1, protegido por token)."""
import json
import os
import re
import secrets
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import acoes
from painel_core import ErroPainel

PAGINA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "painel", "index.html")
CAMPOS = ("niveis", "dpi_padrao", "dpi_shift", "lod", "polling_hz", "botoes", "gshift", "ativa", "nome")
ROTA_MACRO = re.compile(r"^/api/macros(?:/(\d+)(?:/(apagar))?)?$")
ROTA_VAGA = re.compile(r"^/api/vagas/(\d+)(?:/(usar|restaurar))?$")
LIMITE_CORPO = 65536
SEM_SINAL_S = 120


def validar_campos(campos):
    """Devolve uma mensagem de erro em português, ou None se os tipos estão certos."""
    for k, v in campos.items():
        if k == "ativa":
            ok = isinstance(v, bool)
        elif k == "niveis":
            ok = isinstance(v, list) and all(isinstance(n, int) and not isinstance(n, bool) for n in v)
        elif k in ("botoes", "gshift"):
            ok = isinstance(v, list) and all(isinstance(a, dict) for a in v)
        elif k == "nome":
            ok = isinstance(v, str)
        else:
            ok = isinstance(v, int) and not isinstance(v, bool)
        if not ok:
            return f"Valor inválido para {k}."
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "painel"

    def log_message(self, *a):
        pass

    def _json(self, codigo, obj=None):
        corpo = b"" if obj is None else json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(codigo)
        if obj is not None:
            self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _cookie_nome(self):
        return f"painel_token_{self.server.server_address[1]}"

    def _token_enviado(self):
        url = urlparse(self.path)
        if url.path == "/":
            t = parse_qs(url.query).get("token", [""])[0]
            if t:
                return t
        t = self.headers.get("X-Token")
        if t:
            return t
        c = SimpleCookie(self.headers.get("Cookie", ""))
        nome = self._cookie_nome()
        if nome in c:
            return c[nome].value
        return ""

    def _autorizado(self, post):
        if self.headers.get("Host") != f"127.0.0.1:{self.server.server_address[1]}":
            return False
        if post:
            origem = self.headers.get("Origin")
            if origem is not None and origem != f"http://127.0.0.1:{self.server.server_address[1]}":
                return False
        return secrets.compare_digest(self._token_enviado().encode(), self.server.token.encode())

    def _proibido(self):
        self._json(403, {"erro": "acesso negado"})

    def do_GET(self):
        if not self._autorizado(False):
            return self._proibido()
        caminho = urlparse(self.path).path
        if caminho == "/":
            with open(PAGINA, "rb") as f:
                corpo = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Set-Cookie", f"{self._cookie_nome()}={self.server.token}; HttpOnly; SameSite=Strict; Path=/")
            self.end_headers()
            self.wfile.write(corpo)
        elif caminho == "/api/vagas":
            self._executar(self.server.painel.listar)
        else:
            self._json(404, {"erro": "não encontrado"})

    def do_POST(self):
        if not self._autorizado(True):
            return self._proibido()
        caminho = urlparse(self.path).path
        if caminho == "/api/sinal":
            self.server.ultimo_sinal = time.monotonic()
            return self._json(204)
        mm = ROTA_MACRO.match(caminho)
        if mm:
            return self._post_macro(mm)
        m = ROTA_VAGA.match(caminho)
        if not m:
            return self._json(404, {"erro": "não encontrado"})
        sec, acao = int(m.group(1)), m.group(2)
        p = self.server.painel
        if acao == "usar":
            return self._executar(p.usar_agora, sec)
        if acao == "restaurar":
            return self._executar(p.restaurar, sec)
        dados = self._corpo()
        if dados is None:
            return
        campos = {k: v for k, v in dados.items() if k in CAMPOS}
        erro = validar_campos(campos)
        if erro:
            return self._json(400, {"erro": erro})
        self._executar(p.gravar, sec, **campos)

    def _corpo(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n < 0 or n > LIMITE_CORPO:
                raise ValueError
            dados = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(dados, dict):
                raise ValueError
            return dados
        except (ValueError, RecursionError):
            self._json(400, {"erro": "corpo inválido"})

    def _post_macro(self, mm):
        p = self.server.painel
        if mm.group(2):
            return self._executar(lambda: {"sec": p.apagar_macro(int(mm.group(1)))})
        dados = self._corpo()
        if dados is None:
            return
        try:
            if "texto" in dados:
                if not isinstance(dados["texto"], str):
                    raise ValueError("Texto inválido.")
                passos = acoes.texto_para_passos(dados["texto"], dados.get("espera_ms", 30))
            else:
                passos = dados.get("passos")
                if not isinstance(passos, list) or not all(isinstance(x, dict) for x in passos):
                    raise ValueError("Informe passos ou texto.")
        except ValueError as e:
            return self._json(400, {"erro": str(e)})
        sec = int(mm.group(1)) if mm.group(1) else None
        self._executar(lambda: {"sec": p.gravar_macro(sec, passos)})

    def _executar(self, f, *args, **kw):
        try:
            r = f(*args, **kw)
        except ErroPainel as e:
            return self._json(400, {"erro": str(e)})
        except (OSError, TimeoutError, SystemExit):
            return self._json(503, {"erro": "mouse não encontrado"})
        except TypeError:
            return self._json(400, {"erro": "campos inválidos"})
        self._json(200, r)


def criar_servidor(painel, porta=0):
    srv = ThreadingHTTPServer(("127.0.0.1", porta), Handler)
    srv.painel = painel
    srv.token = secrets.token_urlsafe(24)
    srv.ultimo_sinal = None
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/?token={srv.token}"


def servir(srv, sem_sinal_s=SEM_SINAL_S):
    """Atende até Ctrl+C ou até sem_sinal_s segundos sem /api/sinal (após o primeiro)."""
    parar = threading.Event()

    def vigia():
        while not parar.wait(1):
            u = srv.ultimo_sinal
            if u is not None and time.monotonic() - u > sem_sinal_s and not srv.painel.lock.locked():
                srv.shutdown()
                return

    threading.Thread(target=vigia, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        parar.set()
        # espera uma gravação em andamento terminar (com rollback) antes de sair
        if srv.painel.lock.acquire(timeout=30):
            srv.painel.lock.release()
        srv.server_close()
