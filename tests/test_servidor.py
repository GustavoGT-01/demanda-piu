"""servidor.py pelo HTTP de verdade: arquivos que saem, PIN e sessões, papéis, lista fechada do operador e defesas.

Os pedidos "da rede" saem de um endereço que não é loopback: o teste liga o servidor em todas as interfaces e fala
com ele pelo IP da máquina (sem IP de rede, esses testes são pulados). Dados num diretório temporário.
"""

import hashlib
import http.client
import io
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEMANDAS_DATA", tempfile.mkdtemp(prefix="dem-srv-"))
import servidor  # noqa: E402

XSS = '<img src=x onerror="alert(1)">'
TAB = "aaaaaaaa-1111"


def ip_rede():
    for ip in servidor.lan_addresses():
        try:
            s = socket.create_connection((ip, 9), timeout=0.01)
            s.close()
        except OSError:
            pass
        return ip
    return None


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = servidor.Server(("0.0.0.0", 0), servidor.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.ip = ip_rede()

    @classmethod
    def tearDownClass(cls):
        servidor.NET_ON = False
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        self.data = Path(tempfile.mkdtemp(prefix="dem-srv-"))
        self._env = mock.patch.dict(os.environ, {"DEMANDAS_DATA": str(self.data)})
        self._env.start()
        for c in (servidor.SESSIONS, servidor.FAILS):
            c.clear()
        servidor._REV.update(key=None, rev=0)
        servidor.NET_ON = False

    def tearDown(self):
        servidor.NET_ON = False
        for c in (servidor.SESSIONS, servidor.FAILS):
            c.clear()
        self._env.stop()

    def req(self, method, path, body=None, headers=None, rede=False):
        """rede=True: pede pelo IP da máquina (conta como aparelho da rede)."""
        host = self.ip if rede else "127.0.0.1"
        c = http.client.HTTPConnection(host, self.port, timeout=30)
        try:
            c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            h = {"Host": "%s:%d" % (host, self.port)}
            h.update(headers or {})
            raw = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
            if raw is not None:
                h.setdefault("Content-Type", "application/json")
                h["Content-Length"] = str(len(raw))
            elif method == "POST":
                h["Content-Length"] = "0"
            for k, v in h.items():
                c.putheader(k, v)
            c.endheaders(raw)
            r = c.getresponse()
            return r.status, r.headers, r.read()
        finally:
            c.close()

    def post(self, rest, obj, headers=None, rede=False):
        return self.req("POST", "/api/local/demandas/" + rest, obj, headers, rede)

    def ok(self, rest, obj, headers=None, rede=False):
        st, h, raw = self.post(rest, obj, headers, rede)
        self.assertEqual(st, 200, raw.decode("utf-8", "replace"))
        return json.loads(raw)

    def precisa_rede(self):
        if not self.ip:
            self.skipTest("sem IP de rede nesta máquina")
        servidor.NET_ON = True

    def login(self, pin):
        form = {"Content-Type": "application/x-www-form-urlencoded", "Origin": "http://%s:%d" % (self.ip, self.port)}
        st, h, _ = self.req("POST", "/api/login", ("pin=" + pin).encode(), form, rede=True)
        self.assertEqual(st, 303)
        return {"Cookie": h["Set-Cookie"].split(";")[0]}


class Arquivos(Base):
    def test_so_a_pagina_a_casca_e_o_static_saem(self):
        st, h, raw = self.req("GET", "/")
        self.assertEqual(st, 200)
        self.assertIn(b'<main data-view="demandas">', raw)
        for path, tipo in (("/index.html", "text/html"), ("/app.js", "text/javascript"),
                           ("/local/demandas/demandas.js", "text/javascript"), ("/local/demandas/demandas.css", "text/css"),
                           ("/local/demandas/demandas-fontes.css", "text/css"),
                           ("/local/demandas/bricolage-grotesque.woff2", "font/woff2"),
                           ("/local/demandas/figtree.woff2", "font/woff2")):
            st, h, raw = self.req("GET", path)
            self.assertEqual(st, 200, path)
            self.assertTrue(h["Content-Type"].startswith(tipo), (path, h["Content-Type"]))
        self.assertEqual(self.req("HEAD", "/")[0], 200)
        self.ok("setor/salvar", {"modo": "novo", "id": "PCP", "nome": "Planejamento", "icone": "🗂️", "cor": "#6366F1", "rev": 0})
        for path in ("/servidor.py", "/store.py", "/local/demandas/api.py", "/local/demandas/CONTRATO.md",
                     "/local/demandas/contrato.json", "/local/demandas/demandas_store.py", "/local/demandas/../servidor.py",
                     "/local/demandas/..%2Fservidor.py", "/local/demandas/x.woff2", "/data/demandas.json", "/demandas.json",
                     "/web/app.js", "/local/outro/demandas.js", "/local/demandas/"):
            self.assertEqual(self.req("GET", path)[0], 404, path)

    def test_cabecalhos_de_seguranca(self):
        _, h, _ = self.req("GET", "/")
        self.assertIn("default-src 'self'", h["Content-Security-Policy"])
        self.assertEqual((h["X-Content-Type-Options"], h["X-Frame-Options"], h["Cache-Control"]), ("nosniff", "DENY", "no-store"))


class Api(Base):
    def test_maquina_e_adm(self):
        self.assertEqual(json.loads(self.req("GET", "/api/eu")[2]), {"papel": "maquina"})
        v = json.loads(self.req("GET", "/api/local/demandas")[2])
        self.assertEqual((v["papel"], v["demandas"]), ("adm", []))

    def test_erros_viram_texto(self):
        st, h, raw = self.post("demanda/aceitar", {"id": "SOL-1"})
        self.assertEqual((st, raw.decode()), (404, "Demanda não encontrada."))
        self.assertTrue(h["Content-Type"].startswith("text/plain"))
        self.assertEqual(self.req("POST", "/api/local/demandas/vista", b"{x")[0], 400)
        self.assertEqual(self.req("POST", "/api/local/demandas/vista", b"[1]")[0], 400)
        self.assertEqual(self.req("POST", "/api/nada", {})[0], 404)
        self.assertEqual(self.req("GET", "/api/nada")[0], 404)

    def test_erro_inesperado_nao_vaza(self):
        with mock.patch.object(servidor.api_mod(), "handle", side_effect=RuntimeError("C:\\segredo\\caminho")):
            st, _, raw = self.req("GET", "/api/local/demandas")
        self.assertEqual((st, raw.decode()), (500, "Erro interno do servidor."))
        with mock.patch.object(servidor.api_mod(), "handle", return_value=[1]):
            self.assertEqual(self.req("GET", "/api/local/demandas")[0], 500)
        with mock.patch.object(servidor.api_mod(), "handle", return_value={"x": float("nan")}):
            self.assertEqual(self.req("GET", "/api/local/demandas")[0], 500)

    def test_xss_volta_como_dado(self):
        self.ok("setor/salvar", {"modo": "novo", "id": "CNC", "nome": XSS, "icone": "⚙️", "cor": "#3B82F6", "rev": 0})
        raw = self.req("GET", "/api/local/demandas")[2]
        self.assertIn(XSS, json.loads(raw)["setores"][0]["nome"])

    def test_rev(self):
        self.assertEqual(json.loads(self.req("GET", "/api/rev")[2]), {"rev": 0, "inicio": servidor.INICIO_MS})
        self.ok("setor/salvar", {"modo": "novo", "id": "PCP", "nome": "Planejamento", "icone": "🗂️", "cor": "#6366F1", "rev": 0})
        self.assertEqual(json.loads(self.req("GET", "/api/rev")[2]), {"rev": 1, "inicio": servidor.INICIO_MS})
        (self.data / "demandas.json").write_text("{quebrado", encoding="utf-8")
        self.assertEqual(json.loads(self.req("GET", "/api/rev")[2]), {"rev": 1, "inicio": servidor.INICIO_MS})   # arquivo ruim: fica a última rev
        (self.data / "demandas.json").write_text('{"rev": true}', encoding="utf-8")
        self.assertEqual(json.loads(self.req("GET", "/api/rev")[2]), {"rev": 0, "inicio": servidor.INICIO_MS})

    def test_origem_e_host(self):
        self.assertEqual(self.post("vista", {}, {"Origin": "http://evil.com"})[0], 403)
        self.assertEqual(self.post("vista", {}, {"Origin": "http://127.0.0.1:%d" % self.port})[0], 200)   # a própria origem passa
        self.assertEqual(self.req("GET", "/", headers={"Host": "evil.com"})[0], 421)
        self.assertEqual(self.req("GET", "/", headers={"Host": "192.168.0.10:%d" % self.port})[0], 421)   # IP só com a rede ligada

    def test_corpo(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            c.putrequest("POST", "/api/local/demandas/vista", skip_host=True)
            c.putheader("Host", "127.0.0.1:%d" % self.port)
            c.endheaders()
            r = c.getresponse()
            self.assertEqual((r.status, r.read().decode()), (400, "Content-Length ausente ou inválido."))   # sem Content-Length
        finally:
            c.close()
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            c.putrequest("POST", "/api/local/demandas/vista", skip_host=True)
            c.putheader("Host", "127.0.0.1:%d" % self.port)
            c.putheader("Content-Length", str(servidor.MAX_BODY + 1))   # recusado antes de ler o corpo
            c.endheaders()
            self.assertEqual(c.getresponse().status, 413)
        finally:
            c.close()

    def test_rede_so_no_computador_principal(self):
        r = json.loads(self.req("GET", "/api/rede")[2])
        self.assertEqual((r["on"], r["active"]), (False, False))
        self.assertRegex(r["pin"], r"^[0-9]{6}$")
        r2 = json.loads(self.req("POST", "/api/rede", {"on": True, "newpin_op": True})[2])
        self.assertTrue(r2["on"])
        self.assertEqual(r2["pin"], r["pin"])
        self.assertNotEqual(r2["pin_op"], r["pin_op"])
        self.assertEqual(self.req("POST", "/api/rede", b"[x")[0], 400)


class Pins(Base):
    def test_rede_json_antigo_ou_ruim(self):
        (self.data / "rede.json").write_text(json.dumps({"on": True, "pin": "123456"}), encoding="utf-8")
        cfg = servidor.net_config()
        self.assertEqual((cfg["on"], cfg["pin"]), (True, "123456"))
        self.assertRegex(cfg["pin_op"], r"^[0-9]{6}$")
        self.assertNotEqual(cfg["pin_op"], "123456")
        self.assertEqual(json.loads((self.data / "rede.json").read_text(encoding="utf-8"))["pin_op"], cfg["pin_op"])
        self.assertEqual(servidor.net_config(), cfg)   # gravado: a segunda leitura não troca
        (self.data / "rede.json").write_text(json.dumps({"on": True, "pin": "123456", "pin_op": "123456"}), encoding="utf-8")
        self.assertNotEqual(servidor.net_config()["pin_op"], "123456")
        (self.data / "rede.json").write_text("[1]", encoding="utf-8")
        cfg = servidor.net_config()
        self.assertEqual(cfg["on"], False)
        self.assertNotEqual(cfg["pin"], cfg["pin_op"])

    def test_pin_novo(self):
        with mock.patch.object(servidor.secrets, "randbelow", side_effect=[111111, 111111, 222222]) as r:
            self.assertEqual(servidor._pin_novo("111111"), "222222")
        r.assert_called_with(10**6)
        self.assertFalse(servidor._pin_ok("12345"))
        self.assertFalse(servidor._pin_ok("12345a"))
        self.assertFalse(servidor._pin_ok(123456))
        self.assertTrue(servidor._pin_ok("123456"))

    def test_cada_pin_cria_seu_perfil(self):
        cfg = servidor.net_config()
        tc, to = servidor.check_pin("10.0.0.1", cfg["pin"]), servidor.check_pin("10.0.0.1", cfg["pin_op"])
        self.assertEqual(servidor.session_ok("%s=%s" % (servidor.COOKIE, tc)), "completo")
        self.assertEqual(servidor.session_ok("%s=%s" % (servidor.COOKIE, to)), "operador")
        self.assertIsNone(servidor.session_ok("%s=inventado" % servidor.COOKIE))
        self.assertIsNone(servidor.session_ok("outro=%s" % tc))
        self.assertIsNone(servidor.session_ok(None))
        gravado = json.loads((self.data / "sessoes.json").read_text(encoding="utf-8"))
        self.assertNotIn(tc, json.dumps(gravado))   # só o hash vai para o disco
        self.assertIn(hashlib.sha256(tc.encode()).hexdigest(), gravado)

    def test_pin_errado_bloqueia(self):
        cfg = servidor.net_config()
        for _ in range(4):
            self.assertIsNone(servidor.check_pin("10.0.0.9", "999999", now=1000))
        self.assertTrue(servidor.check_pin("10.0.0.9", cfg["pin"], now=1000))   # 4 erros ainda não bloqueiam; acerto zera
        for _ in range(5):
            self.assertIsNone(servidor.check_pin("10.0.0.9", "999999", now=1000))
        self.assertIsNone(servidor.check_pin("10.0.0.9", cfg["pin"], now=1299))   # 5 erros: 5 minutos parado
        self.assertTrue(servidor.check_pin("10.0.0.8", cfg["pin"], now=1299))     # outro IP segue
        self.assertTrue(servidor.check_pin("10.0.0.9", cfg["pin"], now=1301))

    def test_sessao_vence_e_tem_teto(self):
        cfg = servidor.net_config()
        t = servidor.check_pin("10.0.0.1", cfg["pin"], now=1000)
        self.assertIsNone(servidor.session_ok("%s=%s" % (servidor.COOKIE, t)))   # venceu (1000 + 30 dias já passou)
        servidor.SESSIONS.clear()
        agora = time.time()
        for i in range(200):
            servidor.SESSIONS["%064x" % i] = {"exp": agora + 1000 + i, "papel": "completo"}
        servidor.check_pin("10.0.0.1", cfg["pin"])
        self.assertEqual(len(servidor.SESSIONS), 200)
        self.assertNotIn("%064x" % 0, servidor.SESSIONS)   # a mais antiga saiu

    def test_sessoes_sobrevivem_ao_reinicio(self):
        exp = time.time() + 3600
        h1, h2, h3, h4 = ("%064x" % i for i in range(1, 5))
        raw = {h1: {"exp": exp, "papel": "completo"}, h2: {"exp": exp, "papel": "operador"}, h3: {"exp": exp, "papel": "admin"},
               h4: {"exp": time.time() - 1, "papel": "completo"}, "curto": {"exp": exp, "papel": "completo"}, "%064x" % 9: exp}
        (self.data / "sessoes.json").write_text(json.dumps(raw), encoding="utf-8")
        servidor.sessions_load()
        self.assertEqual(servidor.SESSIONS, {h1: {"exp": exp, "papel": "completo"}, h2: {"exp": exp, "papel": "operador"}})
        servidor.SESSIONS.clear()
        (self.data / "sessoes.json").write_text("[]", encoding="utf-8")
        servidor.sessions_load()
        (self.data / "sessoes.json").write_text("{x", encoding="utf-8")
        servidor.sessions_load()
        self.assertEqual(servidor.SESSIONS, {})

    def test_pin_novo_derruba_sessoes(self):
        cfg = servidor.net_config()
        tc, to = servidor.check_pin("10.0.0.1", cfg["pin"]), servidor.check_pin("10.0.0.1", cfg["pin_op"])
        novo = servidor.net_save(new_pin_op=True)
        self.assertEqual(novo["pin"], cfg["pin"])
        self.assertEqual(servidor.session_ok("%s=%s" % (servidor.COOKIE, tc)), "completo")
        self.assertIsNone(servidor.session_ok("%s=%s" % (servidor.COOKIE, to)))
        servidor.net_save(new_pin=True)
        self.assertIsNone(servidor.session_ok("%s=%s" % (servidor.COOKIE, tc)))
        cfg = servidor.net_config()
        self.assertNotEqual(cfg["pin"], cfg["pin_op"])
        self.assertIs(servidor.net_save(on=True)["on"], True)
        self.assertIs(servidor.net_save()["on"], True)   # sem "on": fica como estava
        self.assertIs(servidor.net_save(on=False)["on"], False)


class PelaRede(Base):
    def test_rede_desligada_recusa(self):
        if not self.ip:
            self.skipTest("sem IP de rede nesta máquina")
        self.assertEqual(self.req("GET", "/", rede=True)[0], 421)   # Host com IP só vale com a rede ligada
        servidor.NET_ON = True
        servidor.NET_ON = False
        st, _, raw = self.req("GET", "/", headers={"Host": "127.0.0.1:%d" % self.port}, rede=True)
        self.assertEqual((st, raw.decode()), (403, "Acesso pela rede desligado."))

    def test_sem_sessao_pede_pin(self):
        self.precisa_rede()
        st, _, raw = self.req("GET", "/", rede=True)
        self.assertEqual(st, 200)
        self.assertIn(b'name="pin"', raw)   # a página de PIN, não o app
        self.assertEqual(self.req("GET", "/api/local/demandas", rede=True)[0], 401)
        self.assertEqual(self.post("vista", {}, rede=True)[0], 401)
        st, _, raw = self.req("POST", "/api/login", b"pin=000000x", {"Content-Type": "application/x-www-form-urlencoded"}, rede=True)
        self.assertEqual(st, 200)
        self.assertIn("PIN errado".encode(), raw)
        st, _, raw = self.req("POST", "/api/login", b"pin=1", {"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual((st, raw.decode()), (403, "Acesso pela rede desligado."))   # do próprio PC não tem login
        big = b"x" * (servidor.MAX_BODY_ANON + 1)
        self.assertEqual(self.req("POST", "/api/local/demandas/vista", big, rede=True)[0], 413)

    def test_escritorio_tem_tudo_menos_a_rede(self):
        self.precisa_rede()
        h = self.login(servidor.net_config()["pin"])
        self.assertEqual(json.loads(self.req("GET", "/api/eu", headers=h, rede=True)[2]), {"papel": "completo"})
        self.assertEqual(json.loads(self.req("GET", "/api/local/demandas", headers=h, rede=True)[2])["papel"], "adm")
        self.assertEqual(self.post("setor/salvar", {"modo": "novo", "id": "PCP", "nome": "Planejamento", "icone": "🗂️",
                                                    "cor": "#6366F1", "rev": 0}, h, rede=True)[0], 200)
        self.assertEqual(self.req("GET", "/api/rede", headers=h, rede=True)[0], 403)
        self.assertEqual(self.req("POST", "/api/rede", {"on": False}, h, rede=True)[0], 403)
        self.assertNotIn(b'name="pin"', self.req("GET", "/", headers=h, rede=True)[2])

    def test_operador_so_alcanca_a_tela_de_operador(self):
        self.precisa_rede()
        self.ok("setor/salvar", {"modo": "novo", "id": "CNC", "nome": "Corte CNC", "icone": "⚙️", "cor": "#3B82F6", "rev": 0})
        self.ok("pessoa/salvar", {"modo": "novo", "nome": "Carlos", "setor": "CNC", "codigo": "1234", "rev": 0})
        h = self.login(servidor.net_config()["pin_op"])
        for path in ("/", "/index.html", "/app.js", "/local/demandas/demandas.js", "/local/demandas/figtree.woff2", "/api/rev"):
            self.assertEqual(self.req("GET", path, headers=h, rede=True)[0], 200, path)
        self.assertEqual(json.loads(self.req("GET", "/api/eu", headers=h, rede=True)[2]), {"papel": "operador"})
        pub = json.loads(self.req("GET", "/api/local/demandas", headers=h, rede=True)[2])
        self.assertEqual(sorted(pub), ["pessoas", "setores"])   # só o necessário para o "quem é você?"
        self.assertNotIn("sal", json.dumps(pub))
        self.assertEqual(self.post("vista", {}, h, rede=True)[0], 403)   # sem tk: aqui não existe Escritório
        tk = self.ok("entrar", {"pessoa": "p0", "codigo": "1234"}, h, rede=True)["tk"]
        v = self.ok("demanda/criar", {"tk": tk, "titulo": "Afiar a fresa 6 mm", "tipo": "man", "motivo": "Outro",
                                      "prio": "norm", "est": 30, "para": {"s": "CNC", "p": None}, "desc": ""}, h, rede=True)
        self.assertEqual((v["papel"], len(v["demandas"])), ("pessoa", 1))
        negadas = ["setor/salvar", "setor/ativar", "setor/apagar", "pessoa/salvar", "pessoa/ativar", "pessoa/apagar",
                   "demanda/prioridade", "demanda/estender", "crono", "historico", "entrar/", "entrar/../setor/salvar",
                   "demanda/criar/x", "demanda/"]
        for rest in negadas:
            st, _, raw = self.post(rest, {"tk": tk}, h, rede=True)
            self.assertEqual((st, raw.decode()), (403, servidor.OPERADOR_MSG), rest)
        for path in ("/api/rede", "/api/local/demandas/anexo/a0123456789abcdef", "/api/local/demandas/vista",
                     "/local/demandas/../servidor.py", "/api/local/demandas/", "/API/EU", "/api/eu/"):
            self.assertEqual(self.req("GET", path, headers=h, rede=True)[0], 403, path)
        self.assertEqual(self.req("POST", "/api/rede", {"on": False}, h, rede=True)[0], 403)

    def test_negado_para_no_403(self):
        """Uma resposta só: uma checagem que mandasse o 403 e deixasse seguir escreveria outra."""
        self.precisa_rede()
        h = self.login(servidor.net_config()["pin_op"])
        s = socket.create_connection((self.ip, self.port), timeout=30)
        try:
            lines = ["POST /api/local/demandas/setor/salvar HTTP/1.1", "Host: %s:%d" % (self.ip, self.port),
                     "Cookie: " + h["Cookie"], "Content-Length: 2"]
            s.sendall(("\r\n".join(lines) + "\r\n\r\n").encode() + b"{}")
            raw = b""
            while True:
                part = s.recv(65536)
                if not part:
                    break
                raw += part
        finally:
            s.close()
        self.assertEqual(raw.count(b"HTTP/1."), 1)
        self.assertIn(b" 403 ", raw.split(b"\r\n", 1)[0])

    def test_pin_dos_operadores_novo_tira_o_aparelho(self):
        self.precisa_rede()
        h = self.login(servidor.net_config()["pin_op"])
        self.assertEqual(self.req("POST", "/api/rede", {"newpin_op": True})[0], 200)
        self.assertEqual(self.req("GET", "/api/eu", headers=h, rede=True)[0], 401)


class Detalhes(Base):
    """Os detalhes que o teste de mutação cobra: textos de erro, cabeçalhos, limites e uma resposta só por pedido."""

    def raw(self, linhas, corpo=b"", rede=False):
        """Pedido cru; devolve (quantas respostas HTTP vieram, a primeira linha)."""
        host = self.ip if rede else "127.0.0.1"
        s = socket.create_connection((host, self.port), timeout=30)
        try:
            s.sendall(("\r\n".join(linhas) + "\r\n\r\n").encode() + corpo)
            raw = b""
            while True:
                part = s.recv(65536)
                if not part:
                    break
                raw += part
        finally:
            s.close()
        return raw.count(b"HTTP/1."), raw.split(b"\r\n", 1)[0].decode()

    def texto(self, *args, **kw):
        st, _, raw = self.req(*args, **kw)
        return st, raw.decode("utf-8")

    def test_textos_de_erro(self):
        self.assertEqual(self.texto("GET", "/nada"), (404, "Não encontrado."))
        self.assertEqual(self.texto("POST", "/nada", {}), (404, "Não encontrado."))
        self.assertEqual(self.texto("GET", "/", headers={"Host": "evil.com"}), (421, "Host não aceito."))
        self.assertEqual(self.texto("POST", "/api/local/demandas/vista", b"{x"), (400, "JSON inválido."))
        self.assertEqual(self.texto("POST", "/api/local/demandas/vista", b"[1]"), (400, "Pedido inválido."))
        self.assertEqual(self.texto("POST", "/api/local/demandas/vista", {}, {"Origin": "http://evil.com"}), (403, "Origem não aceita."))
        self.assertEqual(self.texto("POST", "/api/rede", b"[x"), (400, "Falha ao gravar a configuração da rede."))
        with mock.patch.object(servidor.api_mod(), "handle", return_value=[1]):
            self.assertEqual(self.texto("GET", "/api/local/demandas"), (500, "Resposta do módulo inválida."))
        with mock.patch.object(servidor, "MAX_BODY", 4):
            self.assertEqual(self.texto("POST", "/api/local/demandas/vista", b"12345"), (413, "Arquivo grande demais."))
        n, linha = self.raw(["POST /api/local/demandas/vista HTTP/1.1", "Host: 127.0.0.1:%d" % self.port, "Content-Length: x"])
        self.assertEqual((n, linha.split(" ")[1]), (1, "400"))
        n, linha = self.raw(["POST /api/local/demandas/vista HTTP/1.1", "Host: 127.0.0.1:%d" % self.port, "Content-Length: -1"])
        self.assertEqual((n, linha.split(" ")[1]), (1, "400"))

    def test_cabecalhos(self):
        _, h, _ = self.req("GET", "/")
        self.assertEqual(h["Referrer-Policy"], "same-origin")

    def test_query_string_nao_muda_a_rota(self):
        self.assertEqual(json.loads(self.req("GET", "/api/eu?x=1")[2]), {"papel": "maquina"})
        self.assertEqual(self.req("GET", "/app.js?v=2")[0], 200)
        self.assertEqual(self.req("POST", "/api/local/demandas/vista?x=1", {})[0], 200)
        self.assertEqual(self.req("GET", "/api/local/demandasX")[0], 404)

    def test_corpo_vazio_e_limite_exato(self):
        self.assertEqual(self.req("POST", "/api/local/demandas/vista")[0], 200)   # Content-Length 0: corpo {}
        with mock.patch.object(servidor, "MAX_BODY", 2):
            self.assertEqual(self.req("POST", "/api/local/demandas/vista", b"{}")[0], 200)   # exatamente no limite passa

    def test_x_tab_e_resto_chegam_ao_modulo(self):
        visto = {}

        def handle(method, rest, body, ctx):
            visto.update(method=method, rest=rest, body=body, ctx=ctx)
            return {"ok": True}
        with mock.patch.object(servidor.api_mod(), "handle", side_effect=handle):
            self.req("POST", "/api/local/demandas/demanda/criar", {"a": 1}, {"X-Tab": "aba-123"})
        self.assertEqual(visto, {"method": "POST", "rest": "demanda/criar", "body": {"a": 1},
                                 "ctx": {"papel": "maquina", "tab": "aba-123"}})
        with mock.patch.object(servidor.api_mod(), "handle", side_effect=handle):
            self.req("GET", "/api/local/demandas")
        self.assertEqual((visto["method"], visto["rest"]), ("GET", ""))

    def test_status_do_erro_do_modulo(self):
        class Erro(Exception):
            def __init__(self, status):
                self.status = status
                super().__init__("erro %d" % status)
        for status, esperado in ((400, 400), (599, 599), (399, 500), (600, 500), ("403", 500)):
            with mock.patch.object(servidor.api_mod(), "handle", side_effect=Erro(status) if isinstance(status, int) else Exception()):
                st, txt = self.texto("GET", "/api/local/demandas")
            self.assertEqual(st, esperado, status)
            if esperado == 500:
                self.assertEqual(txt, "Erro interno do servidor.")

    def test_anexo_do_adm_pela_rota_do_modulo(self):
        st, txt = self.texto("GET", "/api/local/demandas/anexo/a0123456789abcdef")
        self.assertEqual(st, 404)   # chegou ao módulo (não existe), não ao 404 do servidor
        self.assertNotEqual(txt, "Não encontrado.")

    def test_static_so_nomes_validos(self):
        with mock.patch.object(servidor.api_mod(), "STATIC", (1, "ok.js", "../x.js", "a.py", "b.css")):
            self.assertEqual(servidor.static_files(), ("ok.js", "b.css"))

    def test_rev_le_o_arquivo_do_modulo(self):
        (self.data / "outro.json").write_text('{"rev": 7}', encoding="utf-8")
        with mock.patch.object(servidor.api_mod(), "REV_FILE", "outro.json"):
            self.assertEqual(servidor.rev(), 7)
        servidor._REV.update(key=None, rev=0)
        (self.data / "demandas.json").write_text('{"rev": 3}', encoding="utf-8")
        with mock.patch.object(servidor, "api_mod", return_value=object()):   # módulo sem REV_FILE: demandas.json
            self.assertEqual(servidor.rev(), 3)

    def test_ip_host(self):
        p = self.port
        self.assertTrue(servidor.ip_host("192.168.0.10:%d" % p, p))
        self.assertFalse(servidor.ip_host("192.168.0.10:1", p))
        self.assertFalse(servidor.ip_host("evil.com:%d" % p, p))
        self.assertFalse(servidor.ip_host("[::1]:%d" % p, p))
        self.assertFalse(servidor.ip_host("sem-porta", p))

    def test_cookie_e_sessao(self):
        cfg = servidor.net_config()
        t = servidor.check_pin("10.0.0.1", cfg["pin"], now=5000)
        self.assertEqual(len(t), 43)   # 32 bytes aleatórios
        self.assertEqual(servidor.SESSIONS[servidor._token_hash(t)]["exp"], 5000 + 30 * 86400)
        agora = servidor.check_pin("10.0.0.1", cfg["pin"])
        self.assertEqual(servidor.session_ok("a=1; %s=%s; b=2" % (servidor.COOKIE, agora)), "completo")
        self.assertIsNone(servidor.session_ok("%s=" % servidor.COOKIE))
        self.assertIsNone(servidor.session_ok(""))

    def test_bloqueio_nos_instantes_exatos(self):
        cfg = servidor.net_config()
        self.assertTrue(servidor.check_pin("10.1.0.1", cfg["pin"], now=0.5))   # IP novo não começa bloqueado
        self.assertIsNone(servidor.check_pin("10.1.0.2", "999999", now=0.5))
        self.assertTrue(servidor.check_pin("10.1.0.2", cfg["pin"], now=0.5))   # um erro não bloqueia
        servidor.FAILS["10.1.0.3"] = [0, 1000.0]
        self.assertTrue(servidor.check_pin("10.1.0.3", cfg["pin"], now=1000))   # bloqueio acaba no instante marcado
        for _ in range(5):
            servidor.check_pin("10.1.0.4", "999999", now=2000)
        self.assertIsNone(servidor.check_pin("10.1.0.4", cfg["pin"], now=2299.9))
        for _ in range(4):   # depois do bloqueio a conta recomeça do zero: 4 erros ainda não bloqueiam
            self.assertIsNone(servidor.check_pin("10.1.0.4", "999999", now=2300))
        self.assertTrue(servidor.check_pin("10.1.0.4", cfg["pin"], now=2300))

    def test_net_save_padroes(self):
        cfg = servidor.net_config()
        self.assertEqual(servidor.net_save(), cfg)   # sem nada pedido, nada muda
        novo = servidor.net_save(new_pin=True)
        self.assertRegex(novo["pin"], r"^[0-9]{6}$")
        self.assertEqual(json.loads((self.data / "rede.json").read_text(encoding="utf-8"))["pin"], novo["pin"])
        self.assertRegex(servidor.net_save(new_pin_op=True)["pin_op"], r"^[0-9]{6}$")
        r = json.loads(self.req("POST", "/api/rede", b"")[2])
        self.assertEqual((r["pin"], r["pin_op"]), (servidor.net_config()["pin"], servidor.net_config()["pin_op"]))
        r2 = json.loads(self.req("POST", "/api/rede", {"newpin": False})[2])
        self.assertEqual(r2["pin"], r["pin"])
        r3 = json.loads(self.req("POST", "/api/rede", {"newpin": True})[2])
        self.assertNotEqual(r3["pin"], r["pin"])

    def test_origem_do_proprio_computador(self):
        h = {"Origin": "http://localhost:%d" % self.port}
        self.assertEqual(self.req("POST", "/api/local/demandas/vista", {}, h)[0], 200)

    def test_recusas_mandam_uma_resposta_so(self):
        n, linha = self.raw(["GET / HTTP/1.1", "Host: evil.com"])
        self.assertEqual((n, linha.split(" ")[1]), (1, "421"))
        n, linha = self.raw(["POST /api/local/demandas/vista HTTP/1.1", "Host: evil.com", "Content-Length: 2"], b"{}")
        self.assertEqual((n, linha.split(" ")[1]), (1, "421"))

    def test_pela_rede_textos_login_e_cookie(self):
        if not self.ip:
            self.skipTest("sem IP de rede nesta máquina")
        rede_host = "%s:%d" % (self.ip, self.port)
        n, linha = self.raw(["GET /api/eu HTTP/1.1", "Host: 127.0.0.1:%d" % self.port], rede=True)
        self.assertEqual((n, linha.split(" ")[1]), (1, "403"))   # rede desligada: uma resposta só
        self.assertEqual(self.texto("GET", "/api/eu", headers={"Host": "127.0.0.1:%d" % self.port}, rede=True),
                         (403, "Acesso pela rede desligado."))
        servidor.NET_ON = True
        n, linha = self.raw(["GET /api/eu HTTP/1.1", "Host: " + rede_host], rede=True)
        self.assertEqual((n, linha.split(" ")[1]), (1, "401"))
        self.assertEqual(self.texto("GET", "/api/eu", rede=True), (401, "Entre com o PIN."))
        for path in ("/?x=1", "/index.html"):
            self.assertIn(b'name="pin"', self.req("GET", path, rede=True)[2], path)
        self.assertEqual(self.req("HEAD", "/", rede=True)[0], 200)   # HEAD também recebe a página de PIN
        self.assertEqual(self.texto("GET", "/api/rede", headers=self.login(servidor.net_config()["pin"]), rede=True),
                         (403, "Só no computador principal."))
        with mock.patch.object(servidor, "MAX_BODY_ANON", 4):
            self.assertEqual(self.texto("POST", "/api/login", b"pin=1", {"Content-Type": "application/x-www-form-urlencoded"},
                                        rede=True), (413, "Entre com o PIN antes de enviar arquivos."))
            self.assertEqual(self.req("POST", "/api/login", b"pin=", {"Content-Type": "application/x-www-form-urlencoded"},
                                      rede=True)[0], 200)   # exatamente no limite ainda é lido
        form = {"Content-Type": "application/x-www-form-urlencoded"}
        st, txt = self.texto("POST", "/api/login", b"pin=0", form, rede=True)
        self.assertIn('<p class="e">PIN errado. Depois de 5 erros, espere 5 minutos.</p>', txt)
        self.assertIn(self.ip, servidor.FAILS)   # o erro conta para o IP de quem tentou (o login certo abaixo zera)
        self.assertEqual(self.texto("POST", "/api/rede", {"on": False}, self.login(servidor.net_config()["pin"]), rede=True),
                         (403, "Só no computador principal."))
        sessao = self.login(servidor.net_config()["pin"])
        with mock.patch.object(servidor, "MAX_BODY_ANON", 4):   # com sessão, o teto de quem não entrou não vale
            self.assertEqual(self.req("POST", "/api/local/demandas/vista", b"{    }", sessao, rede=True)[0], 200)
        self.assertIn(b'name="pin"', self.req("POST", "/api/login", b"outro=1", form, rede=True)[2])   # sem o campo
        st, h, raw = self.req("POST", "/api/login", ("pin=+%s+" % servidor.net_config()["pin_op"]).encode(), form, rede=True)
        self.assertEqual((st, h["Location"], h["Content-Length"], raw), (303, "/", "0", b""))   # espaços em volta saem
        self.assertRegex(h["Set-Cookie"], r"^demandas_s=[A-Za-z0-9_-]{43}; Path=/; HttpOnly; SameSite=Strict; Max-Age=2592000$")
        op = {"Cookie": h["Set-Cookie"].split(";")[0]}
        self.assertEqual(self.req("HEAD", "/app.js", headers=op, rede=True)[0], 200)   # HEAD vale como GET na lista
        self.assertEqual(self.texto("GET", "/api/rede", headers=op, rede=True), (403, servidor.OPERADOR_MSG))


class Backup(Base):
    """Rotas /api/backup*: só o computador principal. Dados em <tmp>/data: as cópias vão para <tmp>/backup."""

    def setUp(self):
        super().setUp()
        self.data = self.data / "data"
        self.data.mkdir()
        os.environ["DEMANDAS_DATA"] = str(self.data)

    def json(self, method, path, body=None, headers=None, rede=False):
        st, _, raw = self.req(method, path, body, headers, rede)
        return st, (json.loads(raw) if st == 200 else raw.decode("utf-8"))

    def test_pode(self):
        self.assertTrue(servidor.pode("maquina", "configurar"))
        for papel in ("completo", "operador", None, "x"):
            self.assertFalse(servidor.pode(papel, "configurar"))
        self.assertFalse(servidor.pode("maquina", "outra"))

    def test_painel_salvar_e_fazer_agora(self):
        st, p = self.json("GET", "/api/backup")
        self.assertEqual(st, 200)
        self.assertEqual((p["copias"], p["pasta"], p["pasta_ok"], p["rodando"]), ([], str(self.data.parent / "backup"), False, False))
        self.assertEqual(p["resumo"]["texto"], "Nenhum backup feito ainda.")
        st, p = self.json("POST", "/api/backup", {"hora": "12:30", "ret": {"diarias": 3}})
        self.assertEqual((st, p["cfg"]["hora"], p["cfg"]["ret"]["diarias"]), (200, "12:30", 3))
        self.assertEqual(self.json("POST", "/api/backup", {"hora": "25:00"}),
                         (400, "Horário inválido: use HH:MM, de 00:00 a 23:59."))
        self.assertEqual(self.json("POST", "/api/backup", b"{x"), (400, "JSON inválido."))
        self.assertEqual(self.json("POST", "/api/backup", b"\xff"), (400, "JSON inválido."))
        self.assertEqual(self.json("POST", "/api/backup", [1])[0], 400)
        st, p = self.json("POST", "/api/backup/agora", {})
        self.assertEqual(st, 200)
        self.assertEqual(len(p["copias"]), 1)
        self.assertEqual(p["copias"][0]["tipo"], "manual")
        self.assertTrue(p["pasta_ok"])
        self.assertEqual(p["usado"], p["copias"][0]["bytes"])
        self.assertIsNone(p["resumo"]["alerta"])
        self.assertTrue((self.data.parent / "backup" / p["copias"][0]["nome"]).is_file())
        st, p = self.json("POST", "/api/backup/agora")   # corpo vazio também vale
        self.assertEqual(st, 200)

    def test_previa_e_restaurar(self):
        api = servidor.api_mod()
        self.ok("setor/salvar", {"modo": "novo", "id": "PCP", "nome": "Planejamento", "icone": "🗂️", "cor": "#6366F1", "rev": 0})
        nome = self.json("POST", "/api/backup/agora", {})[1]["copias"][0]["nome"]
        self.ok("setor/salvar", {"modo": "novo", "id": "CNC", "nome": "Corte CNC", "icone": "🗂️", "cor": "#6366F1", "rev": 0})
        st, p = self.json("POST", "/api/backup/previa", {"nome": nome})
        self.assertEqual(st, 200)
        self.assertEqual((p["nome"], p["copia"]["contagem"]["setores"], p["agora"]["contagem"]["setores"]), (nome, 1, 2))
        self.assertEqual(self.json("POST", "/api/backup/previa", {"nome": "x.zip"}), (404, "Cópia não encontrada."))
        for corpo in ({"nome": nome}, {"nome": nome, "confirmo": "restaurar"}, {"nome": nome, "confirmo": True}):
            self.assertEqual(self.json("POST", "/api/backup/restaurar", corpo), (400, "Para restaurar, digite RESTAURAR."))
        self.assertEqual(self.json("POST", "/api/backup/restaurar", [nome]), (400, "Pedido inválido."))
        api._TK["tk-de-alguem"] = ("p1", time.monotonic() + 999)
        rev = json.loads(self.req("GET", "/api/rev")[2])["rev"]
        st, p = self.json("POST", "/api/backup/restaurar", {"nome": nome, "confirmo": "RESTAURAR"})
        self.assertEqual(st, 200)
        self.assertEqual(p["estado"]["restaurado"]["nome"], nome)
        self.assertEqual({c["tipo"] for c in p["copias"]}, {"manual", "antes-restaurar"})
        self.assertEqual(len(api._TK), 0, "todo mundo se identifica de novo")
        v = json.loads(self.req("GET", "/api/local/demandas")[2])
        self.assertEqual([s["id"] for s in v["setores"]], ["PCP"])
        self.assertGreater(v["rev"], rev)
        self.assertGreater(json.loads(self.req("GET", "/api/rev")[2])["rev"], rev)
        self.assertEqual(self.json("POST", "/api/backup/restaurar", {"nome": "nada.zip", "confirmo": "RESTAURAR"}),
                         (404, "Cópia não encontrada."))

    def test_uma_de_cada_vez(self):
        bk = servidor.backup_mod()
        with bk._BACKUP:
            self.assertEqual(self.json("POST", "/api/backup/agora", {}), (409, "Já tem um backup em andamento."))
            self.assertTrue(self.json("GET", "/api/backup")[1]["rodando"])

    def test_abrir_pasta(self):
        self.assertEqual(self.json("POST", "/api/backup/abrir", {}),
                         (404, "A pasta do backup ainda não existe: faça um backup primeiro."))
        (self.data.parent / "backup").mkdir()
        with mock.patch.object(servidor.os, "startfile", create=True) as sf:
            st, _ = self.json("POST", "/api/backup/abrir", {"pasta": "C:\\Windows"})
        self.assertEqual(st, 200)
        sf.assert_called_once_with(self.data.parent / "backup")   # nunca o caminho que veio no pedido
        with mock.patch.object(servidor.os, "startfile", side_effect=OSError("x"), create=True), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            self.assertEqual(self.json("POST", "/api/backup/abrir", {}), (500, "Falha no backup: veja a janela do servidor."))
        self.assertEqual(err.getvalue(), "[backup] POST /api/backup/abrir: OSError('x')\n")

    def test_rotas_desconhecidas(self):
        for method, path in (("GET", "/api/backup/agora"), ("GET", "/api/backup/abrir"), ("POST", "/api/backup/x"),
                             ("GET", "/api/backup/"), ("GET", "/api/backup/restaurar"), ("GET", "/api/backup/previa")):
            self.assertEqual(self.json(method, path, {} if method == "POST" else None), (404, "Não encontrado."), path)
        self.assertEqual(self.req("GET", "/api/backupx")[0], 404)

    def test_pela_rede_nunca(self):
        self.precisa_rede()
        adm = self.login(servidor.net_config()["pin"])
        for method, path in (("GET", "/api/backup"), ("POST", "/api/backup"), ("POST", "/api/backup/agora"),
                             ("POST", "/api/backup/abrir"), ("GET", "/api/backup/agora"), ("POST", "/api/backup/previa"),
                             ("POST", "/api/backup/restaurar")):
            body = {} if method == "POST" else None
            self.assertEqual(self.json(method, path, body, adm, rede=True), (403, "Só no computador principal."), path)
            self.assertEqual(self.json(method, path, body, rede=True)[0], 401, path)
        st, h, _ = self.req("POST", "/api/login", ("pin=" + servidor.net_config()["pin_op"]).encode(),
                            {"Content-Type": "application/x-www-form-urlencoded"}, rede=True)
        op = {"Cookie": h["Set-Cookie"].split(";")[0]}
        self.assertEqual(self.json("GET", "/api/backup", None, op, rede=True), (403, servidor.OPERADOR_MSG))
        self.assertFalse((self.data.parent / "backup").exists())

    def test_origem_estranha(self):
        self.assertEqual(self.json("POST", "/api/backup/agora", {}, {"Origin": "http://mal.example"}),
                         (403, "Origem não aceita."))
        self.assertEqual(self.req("GET", "/api/backup", headers={"Host": "mal.example:%d" % self.port})[0], 421)


class Email(Base):
    """Rotas /api/email*: só o computador principal; a senha nunca volta."""

    def json(self, method, path, body=None, headers=None, rede=False):
        st, _, raw = self.req(method, path, body, headers, rede)
        return st, (json.loads(raw) if st == 200 else raw.decode("utf-8"))

    def test_ler_salvar_testar_e_fila(self):
        st, r = self.json("GET", "/api/email")
        self.assertEqual(st, 200)
        self.assertEqual((r["cfg"]["ligado"], r["estado"]["pendentes"], r["sugestao_link"]),
                         (False, 0, "http://127.0.0.1:%d" % self.port))
        st, r = self.json("POST", "/api/email", {"ligado": True, "host": "smtp.x.com", "remetente": "c@x.com", "senha": "segredo-123"})
        self.assertEqual((st, r["cfg"]["ligado"], r["cfg"]["tem_senha"]), (200, True, True))
        self.assertNotIn("segredo-123", json.dumps(r))
        self.assertNotIn("segredo-123", self.req("GET", "/api/email")[2].decode("utf-8"))
        self.assertEqual(self.json("POST", "/api/email", {"porta": 0}), (400, "Porta inválida: de 1 a 65535."))
        self.assertEqual(self.json("POST", "/api/email", b"{x"), (400, "JSON inválido."))
        self.assertEqual(self.json("POST", "/api/email", [1]), (400, "Pedido inválido."))
        mail, eu = servidor.email_mod(), mock.Mock()
        original = mail.teste
        with mock.patch.object(mail, "teste", side_effect=lambda body: original(body, enviar=eu)):
            st, r = self.json("POST", "/api/email/teste", {"para": "ana@x.com"})
        self.assertEqual((st, r["teste"]["ok"]), (200, True))
        self.assertEqual(eu.call_args.args[2], "segredo-123")
        self.assertEqual(self.json("POST", "/api/email/teste", {"para": "x"}), (400, "E-mail do teste inválido."))
        st, r = self.json("POST", "/api/email/fila", {"acao": "retomar"})
        self.assertEqual((st, r["mexeu"]), (200, 0))
        self.assertEqual(self.json("POST", "/api/email/fila", {"acao": "x"}), (400, "Ação da fila inválida."))

    def test_sugestao_com_rede(self):
        servidor.NET_ON = True
        with mock.patch.object(servidor, "lan_addresses", return_value=["10.0.0.7"]):
            self.assertEqual(self.json("GET", "/api/email")[1]["sugestao_link"], "http://10.0.0.7:%d" % self.port)
        with mock.patch.object(servidor, "lan_addresses", return_value=[]):
            self.assertEqual(self.json("GET", "/api/email")[1]["sugestao_link"], "http://127.0.0.1:%d" % self.port)

    def test_rotas_desconhecidas_e_disco(self):
        for method, path in (("GET", "/api/email/teste"), ("GET", "/api/email/fila"), ("POST", "/api/email/x"), ("GET", "/api/email/")):
            self.assertEqual(self.json(method, path, {} if method == "POST" else None), (404, "Não encontrado."), path)
        with mock.patch.object(servidor.email_mod().store, "atomic_write", side_effect=PermissionError("travado")), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            self.assertEqual(self.json("POST", "/api/email", {"host": "smtp.x.com"}),
                             (500, "Falha ao gravar a configuração do e-mail: veja a janela do servidor."))
        self.assertEqual(err.getvalue(), "[e-mail] POST /api/email: PermissionError('travado')\n")

    def test_pela_rede_nunca(self):
        self.precisa_rede()
        adm = self.login(servidor.net_config()["pin"])
        for method, path in (("GET", "/api/email"), ("POST", "/api/email"), ("POST", "/api/email/teste"),
                             ("POST", "/api/email/fila"), ("GET", "/api/email/teste")):
            body = {} if method == "POST" else None
            self.assertEqual(self.json(method, path, body, adm, rede=True), (403, "Só no computador principal."), path)
        st, h, _ = self.req("POST", "/api/login", ("pin=" + servidor.net_config()["pin_op"]).encode(),
                            {"Content-Type": "application/x-www-form-urlencoded"}, rede=True)
        self.assertEqual(self.json("GET", "/api/email", None, {"Cookie": h["Set-Cookie"].split(";")[0]}, rede=True),
                         (403, servidor.OPERADOR_MSG))

    def test_email_mod(self):
        m = servidor.email_mod()
        self.assertIs(m, sys.modules["email_envio"])
        self.assertIs(servidor.api_mod().mail, m, "o api.py usa o mesmo módulo (a mesma fila)")


class Saude(Base):
    """/api/servidor (seção Servidor das Configurações): só o computador principal; números da pasta de dados."""

    def test_saude_no_computador_principal(self):
        (self.data / "servidor.log").write_text("\n".join("linha %d" % i for i in range(20)) + "\n", encoding="utf-8")
        self.ok("setor/salvar", {"modo": "novo", "id": "PCP", "nome": "Planejamento", "icone": "🗂️", "cor": "#6366F1", "rev": 0})
        with mock.patch.object(servidor, "tarefa_instalada", return_value=True):
            st, _, raw = self.req("GET", "/api/servidor")
        self.assertEqual(st, 200)
        s = json.loads(raw)
        self.assertEqual((s["versao"], s["inicio"], s["porta"], s["rede"], s["tarefa"]),
                         (servidor.VERSAO, servidor.INICIO_MS, self.port, False, True))
        self.assertEqual(s["dados"]["demandas"], (self.data / "demandas.json").stat().st_size)
        self.assertEqual((s["dados"]["arquivo"], s["dados"]["anexos"]), (0, 0))
        self.assertEqual(s["dados"]["cota"], 300 * 1024 * 1024)
        self.assertEqual(s["log"], ["linha %d" % i for i in range(8, 20)], "as 12 últimas")
        self.assertEqual(s["backup"], {"ultimo": None, "copias": 0})
        self.assertEqual(s["urls"], [])
        self.assertEqual(s["sessoes_rede"], 0)
        self.assertTrue(s["disco"]["total"] >= s["disco"]["livre"] > 0)
        self.assertEqual((s["nome_pc"], s["python"], s["sistema"]),
                         (socket.gethostname(), servidor.platform.python_version(), servidor.platform.platform(terse=True)))

    def test_saude_detalhes(self):
        servidor.SESSIONS.update({"a" * 64: {"exp": 2000.0, "papel": "operador"}, "b" * 64: {"exp": 500.0, "papel": "completo"},
                                  "c" * 64: {"exp": 1000.0, "papel": "operador"}})   # vence exatamente agora: não conta
        servidor.NET_ON = True
        bk = servidor.backup_mod()
        (self.data.parent / ("%s-bk" % self.data.name)).mkdir()
        bk.salvar_config({"local": str(self.data.parent / ("%s-bk" % self.data.name))})
        bk.fazer("manual", 1000)
        with mock.patch.object(servidor, "tarefa_instalada", return_value=None), \
                mock.patch.object(servidor, "lan_addresses", return_value=["10.0.0.5"]):
            s = servidor.saude(8123, agora=1000.0)
        self.assertEqual((s["sessoes_rede"], s["rede"], s["urls"], s["tarefa"]), (1, True, ["http://10.0.0.5:8123"], None))
        self.assertEqual(s["backup"], {"ultimo": 1000, "copias": 1})
        with mock.patch.object(servidor.shutil, "disk_usage", side_effect=OSError("x")):
            self.assertIsNone(servidor.saude(8123)["disco"])
        (self.data / "servidor.log").write_bytes(b"\xff\xfe")
        self.assertEqual(servidor.saude(8123)["log"], [])

    def test_tarefa_instalada(self):
        with mock.patch.object(servidor.subprocess, "run", return_value=mock.Mock(returncode=0)) as r:
            self.assertIs(servidor.tarefa_instalada(), True)
        self.assertEqual(r.call_args.args[0], ["schtasks", "/query", "/tn", "Central de demandas"])
        self.assertEqual(r.call_args.kwargs, {"capture_output": True, "timeout": 5})
        with mock.patch.object(servidor.subprocess, "run", return_value=mock.Mock(returncode=1)):
            self.assertIs(servidor.tarefa_instalada(), False)
        for erro in (FileNotFoundError("sem schtasks"), servidor.subprocess.TimeoutExpired("schtasks", 5)):
            with mock.patch.object(servidor.subprocess, "run", side_effect=erro):
                self.assertIsNone(servidor.tarefa_instalada())

    def test_tamanho(self):
        self.assertEqual(servidor._tamanho(self.data / "nada.json"), 0)
        (self.data / "x.json").write_bytes(b"12345")
        self.assertEqual(servidor._tamanho(self.data / "x.json"), 5)

    def texto(self, *args, **kw):
        st, _, raw = self.req(*args, **kw)
        return st, raw.decode("utf-8")

    def test_saude_pela_rede_nunca(self):
        self.precisa_rede()
        adm = self.login(servidor.net_config()["pin"])
        self.assertEqual(self.texto("GET", "/api/servidor", headers=adm, rede=True), (403, "Só no computador principal."))
        self.assertEqual(self.req("GET", "/api/servidor", rede=True)[0], 401)
        st, h, _ = self.req("POST", "/api/login", ("pin=" + servidor.net_config()["pin_op"]).encode(),
                            {"Content-Type": "application/x-www-form-urlencoded"}, rede=True)
        op = {"Cookie": h["Set-Cookie"].split(";")[0]}
        self.assertEqual(self.texto("GET", "/api/servidor", headers=op, rede=True), (403, servidor.OPERADOR_MSG))


class Sempre(unittest.TestCase):
    """Laço de reinício da tarefa agendada (--sempre), servidor.log e a checagem --ligado do iniciar.bat."""

    def setUp(self):
        self.data = Path(tempfile.mkdtemp(prefix="dem-sempre-"))
        self._env = mock.patch.dict(os.environ, {"DEMANDAS_DATA": str(self.data)})
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def log(self):
        return (self.data / "servidor.log").read_text(encoding="utf-8").splitlines()

    def test_registra(self):
        t = time.mktime((2026, 10, 27, 8, 2, 0, 0, 0, -1))
        servidor.registra("ligado", t)
        servidor.registra("parou", t + 60)
        self.assertEqual(self.log(), ["27/10 08:02  ligado", "27/10 08:03  parou"])
        antes = time.strftime("%d/%m %H:%M")
        servidor.registra("agora")
        self.assertIn(self.log()[-1], (antes + "  agora", time.strftime("%d/%m %H:%M") + "  agora"))
        (self.data / "servidor.log").write_bytes(b"\xff\xfe ruim")
        servidor.registra("depois do arquivo ruim", t)
        self.assertEqual(self.log(), ["27/10 08:02  depois do arquivo ruim"])

    def test_registra_guarda_as_ultimas(self):
        with mock.patch.object(servidor, "LOG_MAX", 3):
            for i in range(5):
                servidor.registra("linha %d" % i, 0)
        self.assertEqual([ln.split("  ")[1] for ln in self.log()], ["linha 2", "linha 3", "linha 4"])

    def test_religa_e_desiste_com_quedas_seguidas(self):
        rodadas, esperas = [], []
        relogio = iter(range(0, 1000, 10)).__next__   # cada queda 10 s depois da outra: 10 em 100 s < 120 s

        def rodar(cmd):
            rodadas.append(cmd)
            return 3

        self.assertEqual(servidor.sempre(["py", "servidor.py"], rodar=rodar, relogio=relogio, dormir=esperas.append), 1)
        self.assertEqual(len(rodadas), 10)
        self.assertEqual(rodadas[0], ["py", "servidor.py"])
        self.assertEqual(esperas, [5] * 9)
        log = self.log()
        self.assertTrue(log[0].endswith("  ligado com o Windows (tarefa agendada)"))
        self.assertTrue(log[1].endswith("  parou (código 3) · religado em 5 s"))
        self.assertTrue(log[-1].endswith("  parou 10 vezes em 120 s (último código 3): desisti. Veja data/servidor-saida.log"))
        self.assertEqual(len(log), 11)

    def test_quedas_espacadas_nao_desistem(self):
        rodadas = []
        relogio = iter(range(0, 10 ** 6, 13)).__next__   # 10 quedas ocupam 117 s... a 11ª já tirou a 1ª da janela

        def rodar(cmd):
            rodadas.append(1)
            if len(rodadas) == 30:
                raise KeyboardInterrupt
            return 1

        with self.assertRaises(KeyboardInterrupt):
            servidor.sempre(["x"], rodar=rodar, relogio=relogio, dormir=lambda s: None, janela=117)
        self.assertEqual(len(rodadas), 30)

    def test_codigo_do_windows_com_sinal(self):
        codigos = iter([4294967295, 2 ** 31, 2 ** 31 - 1])
        servidor.sempre(["x"], rodar=lambda c: next(codigos), relogio=iter([0, 1, 2]).__next__, dormir=lambda s: None,
                        limite=3)
        log = self.log()
        self.assertTrue(log[1].endswith("parou (código -1) · religado em 5 s"))
        self.assertTrue(log[2].endswith("parou (código -2147483648) · religado em 5 s"))
        self.assertIn("(último código 2147483647)", log[3])

    def test_limite_exato(self):
        rodadas = []
        relogio = iter([0, 1, 2]).__next__
        servidor.sempre(["x"], rodar=lambda c: rodadas.append(c) or 0, relogio=relogio, dormir=lambda s: None, limite=3)
        self.assertEqual(len(rodadas), 3)

    def test_roda_filho_grava_a_saida(self):
        cod = servidor._roda_filho([sys.executable, "-c", "print('oi'); import sys; sys.exit(7)"])
        self.assertEqual(cod, 7)
        self.assertIn(b"oi", (self.data / "servidor-saida.log").read_bytes())
        tam = (self.data / "servidor-saida.log").stat().st_size
        with mock.patch.object(servidor, "SAIDA_MAX", tam):   # exatamente no limite: ainda não troca
            servidor._roda_filho([sys.executable, "-c", "print('mesmo')"])
        self.assertFalse((self.data / "servidor-saida.log.1").exists())
        with mock.patch.object(servidor, "SAIDA_MAX", 1):
            servidor._roda_filho([sys.executable, "-c", "print('segunda')"])
        self.assertIn(b"mesmo", (self.data / "servidor-saida.log.1").read_bytes())
        self.assertEqual((self.data / "servidor-saida.log").read_bytes().strip(), b"segunda")

    def test_ligado(self):
        srv = servidor.Server(("127.0.0.1", 0), servidor.Handler)
        porta = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            self.assertTrue(servidor.ligado(porta))
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertFalse(servidor.ligado(porta, timeout=0.5))
        resp = mock.MagicMock()
        resp.__enter__.return_value.read.return_value = b'{"rev": 3}'
        with mock.patch.object(servidor.urllib.request.OpenerDirector, "open", return_value=resp) as abre:
            self.assertTrue(servidor.ligado(4321))
        abre.assert_called_once_with("http://127.0.0.1:4321/api/rev", timeout=2)
        resp.__enter__.return_value.read.return_value = b'{"rev": "1"}'
        with mock.patch.object(servidor.urllib.request.OpenerDirector, "open", return_value=resp):
            self.assertFalse(servidor.ligado(porta), "outro programa na porta")
        resp.__enter__.return_value.read.return_value = b'[1]'
        with mock.patch.object(servidor.urllib.request.OpenerDirector, "open", return_value=resp):
            self.assertFalse(servidor.ligado(porta))
        resp.__enter__.return_value.read.return_value = b'<html>'
        with mock.patch.object(servidor.urllib.request.OpenerDirector, "open", return_value=resp):
            self.assertFalse(servidor.ligado(porta))

    def test_main_ligado_e_sempre(self):
        with mock.patch.object(servidor, "ligado", return_value=True), self.assertRaises(SystemExit) as cm:
            servidor.main(["--ligado"])
        self.assertEqual(cm.exception.code, 0)
        with mock.patch.object(servidor, "ligado", return_value=False), self.assertRaises(SystemExit) as cm:
            servidor.main(["--ligado"])
        self.assertEqual(cm.exception.code, 1)
        with mock.patch.object(servidor, "ligado", return_value=True), self.assertRaises(SystemExit) as cm:
            servidor.main(["--ligado", "a mais"])
        self.assertEqual(cm.exception.code, 0)
        with mock.patch.object(servidor, "sempre", return_value=4), self.assertRaises(SystemExit) as cm:
            servidor.main(["--sempre", "a mais"])
        self.assertEqual(cm.exception.code, 4)
        with mock.patch.object(servidor, "sempre", return_value=1) as s, self.assertRaises(SystemExit) as cm:
            servidor.main(["--sempre"])
        self.assertEqual(cm.exception.code, 1)
        s.assert_called_once_with([sys.executable, str(servidor.ROOT / "servidor.py")])
        with mock.patch.object(sys, "argv", ["servidor.py", "--ligado"]), \
                mock.patch.object(servidor, "ligado", return_value=True), \
                mock.patch.object(servidor, "net_config", side_effect=AssertionError("não devia ligar o servidor")), \
                self.assertRaises(SystemExit) as cm:
            servidor.main()
        self.assertEqual(cm.exception.code, 0)


class Fundo(unittest.TestCase):
    """Thread de fundo comum: roda ao ligar e a cada intervalo, com o relógio injetado; uma tarefa que falha não
    derruba as outras."""

    def test_roda_ao_ligar_e_a_cada_intervalo_ate_parar(self):
        visto, parar = [], threading.Event()
        relogio = iter(range(1000, 100000, 1000)).__next__

        def tarefa(agora):
            visto.append(agora)
            if len(visto) == 3:
                parar.set()

        servidor.fundo([tarefa], parar, intervalo=0.001, relogio=relogio)   # volta quando parar
        self.assertEqual(visto, [1000, 2000, 3000])

    def test_falha_de_uma_tarefa_nao_derruba_as_outras(self):
        visto, parar = [], threading.Event()

        def ruim(agora):
            raise RuntimeError("quebrou")

        def boa(agora):
            visto.append(agora)
            parar.set()

        with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            servidor.fundo([ruim, boa], parar, intervalo=0.001, relogio=lambda: 7)
        self.assertEqual(visto, [7])
        self.assertEqual(err.getvalue(), "[fundo] ruim: RuntimeError('quebrou')\n")

    def test_intervalo_padrao_de_60_s(self):
        parar = mock.Mock()
        parar.wait.return_value = True
        servidor.fundo([], parar, relogio=lambda: 0)
        parar.wait.assert_called_once_with(60)
        with mock.patch.object(servidor.threading, "Thread") as th:
            servidor.iniciar_fundo([])
        self.assertEqual(th.call_args.kwargs["args"][2], 60)

    def test_relogio_padrao_em_ms(self):
        visto, parar = [], threading.Event()
        parar.set()
        antes = int(time.time() * 1000)
        servidor.fundo([visto.append], parar, intervalo=0)
        self.assertEqual(len(visto), 1)
        self.assertTrue(antes <= visto[0] <= int(time.time() * 1000))

    def test_iniciar_fundo_e_daemon_e_para(self):
        rodou = threading.Event()
        parar = servidor.iniciar_fundo([lambda agora: rodou.set()], intervalo=0.01)
        self.assertTrue(rodou.wait(5))
        t = next(t for t in threading.enumerate() if t.name == "fundo")
        self.assertTrue(t.daemon)
        parar.set()
        t.join(5)
        self.assertFalse(t.is_alive())

    def test_backup_mod_usa_o_mesmo_banco_do_api(self):
        bk = servidor.backup_mod()
        self.assertIs(bk.ds, sys.modules["demandas_store"])
        self.assertIs(bk.ds.LOCK, servidor.api_mod().ds.LOCK)
        self.assertTrue(callable(bk.tarefa))


if __name__ == "__main__":
    unittest.main()
