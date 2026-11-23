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
# Marca que o finge_rede() lê para contar um pedido como "da rede" numa máquina sem placa. O servidor não
# conhece este cabeçalho: ele só existe enquanto o _remote está trocado, e só nessa máquina.
H_REDE = "X-Teste-Rede"


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
        # Os três papéis do endereço num pedido "da rede". Com placa, os dois últimos são o IP dela e o
        # _remote real é exercitado. Sem placa, o Host leva um IP literal fixo (é o que o ip_host do
        # servidor exige), a conexão sai pelo loopback e quem faz o pedido contar como "da rede" é o
        # finge_rede() abaixo: essa faixa é escopo crítico da mutação e não pode ficar sem teste.
        cls.ip_host = cls.ip or "10.0.0.5"   # vai no cabeçalho Host
        cls.ip_visto = cls.ip or "127.0.0.1"   # para onde a conexão vai, e o que o servidor vê em client_address

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
        host = self.ip_host if rede else "127.0.0.1"
        c = http.client.HTTPConnection(self.ip_visto if rede else "127.0.0.1", self.port, timeout=30)
        try:
            c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            h = {"Host": "%s:%d" % (host, self.port)}
            if rede and not self.ip:
                h[H_REDE] = "1"
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

    def raw(self, linhas, corpo=b"", rede=False):
        """Pedido cru; devolve (quantas respostas HTTP vieram, a primeira linha)."""
        s = socket.create_connection((self.ip_visto if rede else "127.0.0.1", self.port), timeout=30)
        if rede and not self.ip:
            linhas = [*linhas, "%s: 1" % H_REDE]
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

    def finge_rede(self):
        """Sem placa, faz contar como "da rede" só o pedido marcado com H_REDE; com placa, não mexe em nada.

        A marca é por pedido de propósito: um _remote que dissesse True para tudo faria o pedido do próprio
        PC também parecer da rede, e os testes que comparam os dois lados no mesmo caso perderiam o sentido.
        """
        if self.ip:
            return
        original = servidor.Handler._remote

        def _remote(h):
            return bool(h.headers.get(H_REDE)) or original(h)

        p = mock.patch.object(servidor.Handler, "_remote", _remote)
        p.start()
        self.addCleanup(p.stop)

    def precisa_rede(self):
        """Liga o acesso pela rede, com o pedido contando como "da rede"."""
        self.finge_rede()
        servidor.NET_ON = True

    def login(self, pin):
        form = {"Content-Type": "application/x-www-form-urlencoded",
                "Origin": "http://%s:%d" % (self.ip_host, self.port)}
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
        self.assertEqual(json.loads(self.req("GET", "/api/eu")[2]), {"papel": "maquina", "modo": "normal"})
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


class Modo(Base):
    """Modo demonstração (DEMANDAS_MODO=demo): a tela ganha o selo e o servidor não sobe sobre a base real."""

    def test_eu_diz_o_modo(self):
        with mock.patch.object(servidor, "MODO", "demo"):
            self.assertEqual(json.loads(self.req("GET", "/api/eu")[2]), {"papel": "maquina", "modo": "demo"})
        self.assertEqual(json.loads(self.req("GET", "/api/eu")[2])["modo"], "normal")

    def test_saude_diz_o_modo(self):
        self.assertEqual(servidor.saude(self.port)["modo"], "normal")
        with mock.patch.object(servidor, "MODO", "demo"):
            self.assertEqual(servidor.saude(self.port)["modo"], "demo")

    def test_modo_vem_do_ambiente(self):
        for valor, esperado in (("demo", "demo"), ("DEMO", "demo"), (" demo ", "demo"), ("", "normal"),
                                ("demonstracao", "normal"), ("1", "normal"), ("normal", "normal")):
            with mock.patch.dict(os.environ, {"DEMANDAS_MODO": valor}):
                modo = "demo" if (os.environ.get("DEMANDAS_MODO") or "").strip().lower() == "demo" else "normal"
            self.assertEqual(modo, esperado, valor)

    def test_dados_reais_reconhece_a_base_do_programa(self):
        self.assertFalse(servidor.dados_reais())   # a pasta do teste é temporária
        with mock.patch.object(servidor.store, "data_dir", return_value=servidor.ROOT / "data"):
            self.assertTrue(servidor.dados_reais())
        with mock.patch.object(servidor.store, "data_dir", return_value=servidor.ROOT / "demandas" / ".." / "data"):
            self.assertTrue(servidor.dados_reais())
        with mock.patch.object(servidor.store, "data_dir", return_value=servidor.ROOT / "data-demo"):
            self.assertFalse(servidor.dados_reais())

    def test_erro_modo_so_na_demonstracao_sobre_a_base_real(self):
        self.assertIsNone(servidor.erro_modo())
        with mock.patch.object(servidor, "MODO", "demo"):
            self.assertIsNone(servidor.erro_modo())          # pasta temporária: pode
            with mock.patch.object(servidor, "dados_reais", return_value=True):
                self.assertEqual(servidor.erro_modo(),
                                 "Modo demonstração apontado para a base real (data/): use o iniciar-demo.bat,"
                                 " que aponta DEMANDAS_DATA para a pasta data-demo.")
        with mock.patch.object(servidor, "dados_reais", return_value=True):
            self.assertIsNone(servidor.erro_modo())          # modo normal na base real: é o de sempre

    def test_main_recusa_a_demonstracao_na_base_real(self):
        with mock.patch.object(servidor, "MODO", "demo"), \
                mock.patch.object(servidor, "dados_reais", return_value=True), \
                mock.patch.object(servidor, "net_config") as net, \
                mock.patch.object(servidor, "Server") as srv, \
                mock.patch("sys.stdout", io.StringIO()) as saida:
            with self.assertRaises(SystemExit) as c:
                servidor.main([])
        self.assertEqual(c.exception.code, 1)
        self.assertIn("iniciar-demo.bat", saida.getvalue())
        net.assert_not_called()   # nem leu a configuração da rede: não escreve nada na base real
        srv.assert_not_called()

    def test_a_tela_tem_o_selo_ligado_ao_modo(self):
        html = self.req("GET", "/")[2].decode("utf-8")
        self.assertIn('id="cx-demo"', html)
        self.assertIn("hidden", html.split('id="cx-demo"')[1].split(">")[0])   # escondido até o app.js mostrar
        js = self.req("GET", "/app.js")[2].decode("utf-8")
        self.assertIn("eu.modo === 'demo'", js)
        self.assertIn("cx-demo", js)


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
        self.finge_rede()   # sem ligar NET_ON: é a rede desligada que está sob teste
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
        self.assertEqual(json.loads(self.req("GET", "/api/eu", headers=h, rede=True)[2]),
                         {"papel": "completo", "modo": "normal"})
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
        self.assertEqual(json.loads(self.req("GET", "/api/eu", headers=h, rede=True)[2]),
                         {"papel": "operador", "modo": "normal"})
        pub = json.loads(self.req("GET", "/api/local/demandas", headers=h, rede=True)[2])
        self.assertEqual(sorted(pub), ["pessoas", "setores"])   # só o necessário para o "quem é você?"
        self.assertNotIn("sal", json.dumps(pub))
        self.assertEqual(self.post("vista", {}, h, rede=True)[0], 403)   # sem tk: aqui não existe Escritório
        tk = self.ok("entrar", {"pessoa": "p0", "codigo": "1234"}, h, rede=True)["tk"]
        v = self.ok("demanda/criar", {"tk": tk, "titulo": "Afiar a fresa 6 mm", "tipo": "man", "motivo": "Outro",
                                      "prio": "norm", "est": 30, "para": {"s": "CNC", "p": None}, "desc": ""}, h, rede=True)
        self.assertEqual((v["papel"], len(v["demandas"])), ("pessoa", 1))
        p = self.ok("aviso/prefs", {"tk": tk, "prefs": {"eventos": {"fila": False}}}, h, rede=True)["prefs"]
        self.assertEqual(p["eventos"]["fila"], False, "Meus avisos funciona no aparelho de operador")
        negadas = ["setor/salvar", "setor/ativar", "setor/apagar", "pessoa/salvar", "pessoa/ativar", "pessoa/apagar",
                   "demanda/prioridade", "demanda/estender", "crono", "cronograma", "historico", "entrar/",
                   "entrar/../setor/salvar", "demanda/criar/x", "demanda/"]
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
        s = socket.create_connection((self.ip_visto, self.port), timeout=30)
        try:
            lines = ["POST /api/local/demandas/setor/salvar HTTP/1.1", "Host: %s:%d" % (self.ip_host, self.port),
                     "Cookie: " + h["Cookie"], "Content-Length: 2"]
            if not self.ip:
                lines.append("%s: 1" % H_REDE)
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
        self.assertEqual(json.loads(self.req("GET", "/api/eu?x=1")[2]), {"papel": "maquina", "modo": "normal"})
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

    def test_endereco_ilegivel_conta_como_rede(self):
        """client_address que não é IP: o pedido conta como da rede, nunca como o próprio computador.

        É o ramo de erro do _remote. Falhar para o lado fechado importa: dar "maquina" a um endereço que
        não se consegue ler entregaria as Configurações e os dois PINs.
        """
        h = servidor.Handler.__new__(servidor.Handler)
        h.client_address = ("nao-e-um-ip", 0)
        self.assertIs(h._remote(), True)
        h.client_address = ("127.0.0.1", 0)
        self.assertIs(h._remote(), False)

    def test_pagina_de_pin_sem_erro_na_primeira_vez(self):
        """A página de entrada só mostra o parágrafo de erro depois de um PIN errado."""
        self.precisa_rede()
        raw = self.req("GET", "/", rede=True)[2]
        self.assertIn(b'name="pin"', raw)
        self.assertNotIn(b'class="e"', raw)
        form = {"Content-Type": "application/x-www-form-urlencoded"}
        errada = self.req("POST", "/api/login", b"pin=0", form, rede=True)[2]
        self.assertIn(b'class="e"', errada)   # o contraste: com erro, o parágrafo aparece

    def test_pela_rede_textos_login_e_cookie(self):
        self.finge_rede()   # NET_ON é ligado no meio do teste: o começo testa a rede desligada
        rede_host = "%s:%d" % (self.ip_host, self.port)
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
        self.assertIn(self.ip_visto, servidor.FAILS)   # o erro conta para o IP de quem tentou (o login certo abaixo zera)
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


class Avisos(Base):
    """/api/avisos: padrões da central; só o computador principal."""

    def json(self, method, path, body=None, headers=None, rede=False):
        st, _, raw = self.req(method, path, body, headers, rede)
        return st, (json.loads(raw) if st == 200 else raw.decode("utf-8"))

    def test_ler_e_salvar(self):
        st, r = self.json("GET", "/api/avisos")
        self.assertEqual((st, r["padrao"]["som"], r["padrao"]["silencio"]["ligado"]), (200, "curto", False))
        st, r = self.json("POST", "/api/avisos", {"som": "sino", "eventos": {"late": False}})
        self.assertEqual((st, r["padrao"]["som"], r["padrao"]["eventos"]["late"]), (200, "sino", False))
        self.assertEqual(self.json("GET", "/api/avisos")[1], r)
        self.assertEqual(self.json("POST", "/api/avisos", {"som": "x"}), (400, "Som inválido."))
        self.assertEqual(self.json("POST", "/api/avisos", b"{x"), (400, "JSON inválido."))
        self.assertEqual(self.json("POST", "/api/avisos", b"\xff"), (400, "JSON inválido."))
        self.assertEqual(self.json("POST", "/api/avisos", [1]), (400, "Pedido inválido."))
        self.assertEqual(self.json("POST", "/api/avisos")[1]["padrao"]["som"], "sino", "corpo vazio: nada muda")
        self.assertEqual(self.json("GET", "/api/avisos/x"), (404, "Não encontrado."))
        with mock.patch.object(servidor.avisos_mod().store, "atomic_write", side_effect=PermissionError("travado")), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            self.assertEqual(self.json("POST", "/api/avisos", {"som": "curto"}),
                             (500, "Falha ao gravar os avisos: veja a janela do servidor."))
        self.assertEqual(err.getvalue(), "[avisos] POST: PermissionError('travado')\n")

    def test_pela_rede_nunca(self):
        self.precisa_rede()
        adm = self.login(servidor.net_config()["pin"])
        for method in ("GET", "POST"):
            self.assertEqual(self.json(method, "/api/avisos", {} if method == "POST" else None, adm, rede=True),
                             (403, "Só no computador principal."), method)
        op = self.login(servidor.net_config()["pin_op"])
        self.assertEqual(self.json("GET", "/api/avisos", None, op, rede=True), (403, servidor.OPERADOR_MSG))

    def test_avisos_mod(self):
        m = servidor.avisos_mod()
        self.assertIs(m, sys.modules["demandas_avisos"])
        self.assertIs(servidor.api_mod().av, m, "o api.py usa o mesmo módulo (o mesmo LOCK)")


class Saude(Base):
    """/api/servidor (seção Servidor das Configurações): só o computador principal; números da pasta de dados."""

    def setUp(self):
        super().setUp()
        self.data = self.data / "data"   # a pasta padrão do backup fica ao lado de data/: nunca a %TEMP%\backup comum
        self.data.mkdir()
        os.environ["DEMANDAS_DATA"] = str(self.data)

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
        # nenhum mutante do main() pode ligar servidor nem processo de verdade daqui (já houve uma cadeia de processos)
        nao = AssertionError("não devia ligar servidor nem processo")
        with mock.patch.multiple(servidor, Server=mock.Mock(side_effect=nao), iniciar_fundo=mock.Mock(side_effect=nao),
                                 _roda_filho=mock.Mock(side_effect=nao), sempre=mock.Mock(side_effect=nao),
                                 ligado=mock.Mock(side_effect=nao)):
            self._main_ligado_e_sempre()

    def _main_ligado_e_sempre(self):
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

    def sem_processos(self):
        """Trava os caminhos do main() que criam processos de verdade: um mutante que troca o --sempre não pode
        ligar uma cadeia de servidores."""
        nao = AssertionError("não devia criar processo")
        return mock.patch.multiple(servidor, sempre=mock.Mock(side_effect=nao), ligado=mock.Mock(side_effect=nao),
                                   _roda_filho=mock.Mock(side_effect=nao))

    def roda_main(self, rede, server=None, lan=("10.0.0.5",), hosts=frozenset()):
        """hosts fixo: sem isso um DEMANDAS_HOSTS na máquina de quem roda os testes entra na saída do main."""
        srv = mock.Mock()
        srv.serve_forever.side_effect = KeyboardInterrupt
        with self.sem_processos(), mock.patch.object(servidor, "net_config", return_value={"on": rede}), \
                mock.patch.object(servidor, "HOSTS_PUB", hosts), \
                mock.patch.object(servidor, "sessions_load") as sl, \
                mock.patch.object(servidor, "Server", side_effect=server, return_value=srv) as cls, \
                mock.patch.object(servidor, "lan_addresses", return_value=list(lan)), \
                mock.patch.object(servidor, "iniciar_fundo") as fundo, \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            try:
                servidor.main([])
            except (KeyboardInterrupt, SystemExit) as exc:
                fim = exc
        net = servidor.NET_ON
        servidor.NET_ON = False
        return cls, fundo, out.getvalue(), fim, net, sl

    def test_main_com_e_sem_rede(self):
        cls, fundo, out, fim, net, sl = self.roda_main(False)
        self.assertEqual(cls.call_args.args, (("127.0.0.1", servidor.PORT), servidor.Handler))
        self.assertEqual((out, net, type(fim)), ("Central de demandas aberta em http://127.0.0.1:%d\n" % servidor.PORT, False, KeyboardInterrupt))
        sl.assert_called_once_with()
        cls, fundo, out, fim, net, sl = self.roda_main(True, lan=("10.0.0.5", "10.0.0.6"))
        self.assertEqual((cls.call_args.args[0], net), (("0.0.0.0", servidor.PORT), True))
        self.assertEqual(out.splitlines()[1], "Acesso pela rede ligado (com PIN): http://10.0.0.5:%d, http://10.0.0.6:%d"
                         % (servidor.PORT, servidor.PORT))

    def test_main_avisa_o_modo_demonstracao(self):
        with mock.patch.object(servidor, "MODO", "demo"):
            _cls, _fundo, out, _fim, _net, _sl = self.roda_main(False)
        self.assertEqual(out.splitlines()[0], "MODO DEMONSTRAÇÃO: dados fictícios em %s" % servidor.store.data_dir())
        self.assertIn("Central de demandas aberta", out.splitlines()[1])
        _cls, _fundo, out, _fim, _net, _sl = self.roda_main(False)
        self.assertNotIn("DEMONSTRAÇÃO", out)

    def test_main_porta_ocupada_nao_liga_nada(self):
        cls, fundo, out, fim, net, sl = self.roda_main(False, server=OSError("em uso"))
        self.assertEqual((type(fim), fim.code), (SystemExit, 1))
        self.assertEqual(out, "Já existe um servidor na porta %d: use a janela aberta ou feche-a\n" % servidor.PORT)
        fundo.assert_not_called()

    def test_main_liga_as_tres_tarefas_depois_de_abrir_a_porta(self):
        srv = mock.Mock()
        srv.serve_forever.side_effect = KeyboardInterrupt
        with self.sem_processos(), mock.patch.object(servidor, "net_config", return_value={"on": False}), \
                mock.patch.object(servidor, "sessions_load"), mock.patch.object(servidor, "Server", return_value=srv), \
                mock.patch.object(servidor, "iniciar_fundo") as fundo, mock.patch("builtins.print"), \
                self.assertRaises(KeyboardInterrupt):
            servidor.main([])
        tarefas = fundo.call_args.args[0]
        self.assertEqual(tarefas, [servidor.backup_mod().tarefa, servidor.api_mod().tick, servidor.email_mod().tarefa])

    def test_backup_mod_usa_o_mesmo_banco_do_api(self):
        bk = servidor.backup_mod()
        self.assertIs(bk.ds, sys.modules["demandas_store"])
        self.assertIs(bk.ds.LOCK, servidor.api_mod().ds.LOCK)
        self.assertTrue(callable(bk.tarefa))


class RecusaGrande(unittest.TestCase):
    """A recusa 413 drena o corpo antes de fechar.

    É a única recusa que decide antes de o corpo ser lido, justamente porque o corpo é grande. Fechar a
    conexão com dados por ler vira RST no Windows, e aí o cliente toma conexão abortada em vez de ler a
    mensagem — era uma falha intermitente de verdade no `qa.py all`. Aqui o handler é montado à mão, sem
    socket, para medir exatamente quanto foi drenado.
    """

    class Conexao:
        """Só o que o _recusa_grande usa do socket, guardando os timeouts que recebeu."""

        def __init__(self, t):
            self.t = t
            self.postos = []

        def gettimeout(self):
            return self.t

        def settimeout(self, v):
            self.t = v
            self.postos.append(v)

    def handler(self, corpo: bytes, timeout=7.5):
        h = servidor.Handler.__new__(servidor.Handler)
        h.rfile = io.BytesIO(corpo)
        h.connection = self.Conexao(timeout)
        h.close_connection = False
        h.enviados = []
        h._send = lambda st, raw, mime: h.enviados.append((st, raw.decode("utf-8"), mime))
        return h

    def test_drena_o_corpo_inteiro_e_responde(self):
        h = self.handler(b"12345")
        h._recusa_grande("Arquivo grande demais.", 5)
        self.assertEqual(h.rfile.tell(), 5)   # nada ficou por ler: é isso que evita o RST
        self.assertEqual(h.rfile.read(), b"")
        self.assertEqual(h.enviados, [(413, "Arquivo grande demais.", "text/plain; charset=utf-8")])
        self.assertIs(h.close_connection, True)

    def test_drena_um_byte(self):
        h = self.handler(b"x")
        h._recusa_grande("m", 1)
        self.assertEqual(h.rfile.tell(), 1)

    def test_drena_no_maximo_o_teto(self):
        with mock.patch.object(servidor, "MAX_BODY_ANON", 10):
            h = self.handler(b"x" * 50)
            h._recusa_grande("m", 50)
        self.assertEqual(h.rfile.tell(), 10)   # o teto é do MAX_BODY_ANON, não do anunciado
        self.assertEqual(h.enviados[0][0], 413)

    def test_drena_em_pedacos_ate_o_fim(self):
        """Corpo maior que um pedaço: o laço continua em vez de parar no primeiro."""
        with mock.patch.object(servidor, "MAX_BODY_ANON", 200000):
            h = self.handler(b"x" * 150000)
            h._recusa_grande("m", 150000)
        self.assertEqual(h.rfile.tell(), 150000)

    def test_corpo_menor_que_o_anunciado_nao_trava(self):
        h = self.handler(b"abc")
        h._recusa_grande("m", 10)   # anunciou 10, mandou 3: para no fim do que veio
        self.assertEqual(h.rfile.tell(), 3)
        self.assertEqual(h.enviados[0][0], 413)

    def test_devolve_o_timeout_que_estava(self):
        h = self.handler(b"12345", timeout=7.5)
        h._recusa_grande("m", 5)
        self.assertEqual(h.connection.postos, [servidor.DRENO_S, 7.5])
        self.assertEqual(h.connection.t, 7.5)

    def test_timeout_na_drenagem_nao_sobe(self):
        h = self.handler(b"")
        h.rfile = io.BytesIO(b"")
        h.rfile.read = lambda n: (_ for _ in ()).throw(TimeoutError("drenagem"))
        h._recusa_grande("m", 10)   # TimeoutError é OSError: engolido, a resposta sai
        self.assertEqual(h.enviados[0][0], 413)
        self.assertEqual(h.connection.postos, [servidor.DRENO_S, 7.5])

    def test_fail_fecha_so_a_partir_de_400(self):
        for st, fecha in ((200, False), (303, False), (400, True), (401, True), (413, True), (500, True)):
            h = self.handler(b"")
            h._fail(st, "x")
            self.assertIs(h.close_connection, fecha, st)
            self.assertEqual(h.enviados[0][:2], (st, "x"))


class Hospedado(Base):
    """Modo hospedado (DEMANDAS_HOSTS): o pedido que chega pelo domínio vem de fora, ainda que pelo loopback.

    É o caso do túnel (Cloudflare, ngrok) rodando no próprio PC: sem isto, quem abrisse o domínio entraria
    como o computador principal, sem PIN. A conexão destes testes sai do loopback de propósito.
    """

    DOM = "demandas.exemplo.com"

    def setUp(self):
        super().setUp()
        p = mock.patch.object(servidor, "HOSTS_PUB", frozenset({self.DOM}))
        p.start()
        self.addCleanup(p.stop)

    def dom(self, method, path, body=None, headers=None, host=None):
        """Pedido como o túnel entrega: Host do domínio, conexão pelo loopback."""
        h = {"Host": host or self.DOM}
        h.update(headers or {})
        return self.req(method, path, body, h)

    def texto(self, *args, **kw):
        st, _, raw = self.dom(*args, **kw)
        return st, raw.decode("utf-8")

    def forma(self, **extra):
        f = {"Content-Type": "application/x-www-form-urlencoded", "Origin": "https://" + self.DOM}
        f.update(extra)
        return f

    def entra(self, pin, ip_real=None):
        form = self.forma(**({"CF-Connecting-IP": ip_real} if ip_real else {}))
        st, h, _ = self.dom("POST", "/api/login", ("pin=" + pin).encode(), form)
        self.assertEqual(st, 303)
        return {"Cookie": h["Set-Cookie"].split(";")[0]}

    # ---------- a variável ----------
    def test_hosts_publicos_le_a_lista(self):
        self.assertEqual(servidor.hosts_publicos("demandas.exemplo.com"), frozenset({"demandas.exemplo.com"}))
        self.assertEqual(servidor.hosts_publicos(" A.exemplo.com ,b.exemplo.com. ;c.exemplo.com"),
                         frozenset({"a.exemplo.com", "b.exemplo.com", "c.exemplo.com"}))
        self.assertEqual(servidor.hosts_publicos("x.exemplo.com:8443"), frozenset({"x.exemplo.com:8443"}))
        for torto in ("", "   ", ",,", "https://x.exemplo.com", "x.exemplo.com/caminho", "x exemplo.com",
                      "x.exemplo.com:", "evil.com?a=1", "-x.exemplo.com", "*.exemplo.com", "a" * 300):
            self.assertEqual(servidor.hosts_publicos(torto), frozenset(), torto)
        self.assertEqual(servidor.hosts_publicos("bom.exemplo.com, https://ruim.com"),
                         frozenset({"bom.exemplo.com"}))
        self.assertEqual(servidor.hosts_publicos(None), servidor.hosts_publicos(os.environ.get("DEMANDAS_HOSTS")))

    def test_variavel_vem_do_ambiente(self):
        with mock.patch.dict(os.environ, {"DEMANDAS_HOSTS": "a.exemplo.com"}):
            self.assertEqual(servidor.hosts_publicos(), frozenset({"a.exemplo.com"}))
        with mock.patch.dict(os.environ, {"DEMANDAS_HOSTS": ""}):
            self.assertEqual(servidor.hosts_publicos(), frozenset())

    # ---------- Host ----------
    def test_o_dominio_passa_e_o_resto_segue_recusado(self):
        self.assertEqual(self.dom("GET", "/api/eu")[0], 401)
        self.assertEqual(self.texto("GET", "/api/eu", host="outro.exemplo.com"), (421, "Host não aceito."))
        self.assertEqual(self.texto("GET", "/api/eu", host="evil.com"), (421, "Host não aceito."))
        self.assertEqual(self.dom("GET", "/api/eu", host=self.DOM.upper() + ".")[0], 401)
        self.assertEqual(self.req("GET", "/api/eu")[0], 200)

    def test_sem_a_variavel_o_dominio_volta_a_ser_recusado(self):
        with mock.patch.object(servidor, "HOSTS_PUB", frozenset()):
            self.assertEqual(self.texto("GET", "/api/eu"), (421, "Host não aceito."))

    # ---------- nunca "maquina" ----------
    def test_pelo_dominio_nunca_e_o_computador_principal(self):
        self.assertEqual(self.texto("GET", "/api/eu"), (401, "Entre com o PIN."))
        self.assertIn(b'name="pin"', self.dom("GET", "/")[2])
        self.assertEqual(self.dom("HEAD", "/index.html")[0], 200)
        sessao = self.entra(servidor.net_config()["pin"])
        self.assertEqual(json.loads(self.dom("GET", "/api/eu", headers=sessao)[2])["papel"], "completo")
        for rota in ("/api/rede", "/api/servidor"):
            self.assertEqual(self.texto("GET", rota, headers=sessao), (403, "Só no computador principal."))
        self.assertEqual(self.texto("GET", "/api/servidor"), (401, "Entre com o PIN."))

    def test_login_pelo_dominio_sem_a_rede_ligada(self):
        self.assertFalse(servidor.NET_ON)
        sessao = self.entra(servidor.net_config()["pin"])
        resp = self.dom("POST", "/api/local/demandas/vista", {}, {**sessao, "Origin": "https://" + self.DOM})
        self.assertEqual(resp[0], 200)

    def test_cookie_do_dominio_sai_com_secure(self):
        pin = servidor.net_config()["pin"]
        _, h, _ = self.dom("POST", "/api/login", ("pin=" + pin).encode(), self.forma())
        self.assertRegex(h["Set-Cookie"],
                         r"^demandas_s=[A-Za-z0-9_-]{43}; Path=/; HttpOnly; SameSite=Strict; Secure; Max-Age=2592000$")

    def test_operador_pelo_dominio_so_alcanca_a_tela_dele(self):
        op = self.entra(servidor.net_config()["pin_op"])
        self.assertEqual(json.loads(self.dom("GET", "/api/eu", headers=op)[2])["papel"], "operador")
        self.assertEqual(self.dom("GET", "/app.js", headers=op)[0], 200)
        self.assertEqual(self.texto("GET", "/api/rede", headers=op), (403, servidor.OPERADOR_MSG))

    # ---------- Origin ----------
    def test_origem_https_do_dominio_passa_e_o_resto_nao(self):
        sessao = self.entra(servidor.net_config()["pin"])
        vista = "/api/local/demandas/vista"
        self.assertEqual(self.dom("POST", vista, {}, {**sessao, "Origin": "https://" + self.DOM})[0], 200)
        for ruim in ("http://" + self.DOM, "https://evil.com", "https://" + self.DOM + ":8443", "null"):
            self.assertEqual(self.texto("POST", vista, {}, {**sessao, "Origin": ruim}),
                             (403, "Origem não aceita."), ruim)
        self.assertEqual(self.dom("POST", vista, {}, sessao)[0], 200)
        self.assertEqual(self.post("vista", {}, {"Origin": "http://127.0.0.1:%d" % self.port})[0], 200)
        self.assertEqual(self.post("vista", {}, {"Origin": "https://" + self.DOM})[0], 403)

    def test_origem_com_porta_quando_o_dominio_tem_porta(self):
        with mock.patch.object(servidor, "HOSTS_PUB", frozenset({"x.exemplo.com:8443"})):
            st, _, _ = self.req("POST", "/api/login", b"pin=0",
                                {"Host": "x.exemplo.com:8443", "Origin": "https://x.exemplo.com:8443",
                                 "Content-Type": "application/x-www-form-urlencoded"})
            self.assertEqual(st, 200)

    # ---------- IP real ----------
    def test_bloqueio_conta_pelo_ip_do_cabecalho_do_proxy(self):
        for _ in range(5):
            self.dom("POST", "/api/login", b"pin=000000", self.forma(**{"CF-Connecting-IP": "198.51.100.9"}))
        self.assertIn("198.51.100.9", servidor.FAILS)
        self.assertNotIn("127.0.0.1", servidor.FAILS)
        pin = servidor.net_config()["pin"]
        bloqueado = self.dom("POST", "/api/login", ("pin=" + pin).encode(),
                             self.forma(**{"CF-Connecting-IP": "198.51.100.9"}))
        self.assertEqual(bloqueado[0], 200)
        self.entra(pin, ip_real="203.0.113.7")

    def test_x_forwarded_for_vale_o_ultimo_e_o_torto_cai_no_endereco(self):
        self.dom("POST", "/api/login", b"pin=000000", self.forma(**{"X-Forwarded-For": "10.0.0.1, 203.0.113.9"}))
        self.assertIn("203.0.113.9", servidor.FAILS)
        servidor.FAILS.clear()
        self.dom("POST", "/api/login", b"pin=000000", self.forma(**{"CF-Connecting-IP": "nao-e-ip"}))
        self.assertIn("127.0.0.1", servidor.FAILS)
        servidor.FAILS.clear()
        self.dom("POST", "/api/login", b"pin=000000",
                 self.forma(**{"CF-Connecting-IP": "x", "X-Forwarded-For": "203.0.113.5"}))
        self.assertIn("203.0.113.5", servidor.FAILS)

    def test_cabecalho_de_proxy_nao_vale_fora_do_dominio(self):
        self.precisa_rede()
        form = {"Content-Type": "application/x-www-form-urlencoded", "CF-Connecting-IP": "203.0.113.1",
                "Origin": "http://%s:%d" % (self.ip_host, self.port)}
        self.req("POST", "/api/login", b"pin=000000", form, rede=True)
        self.assertIn(self.ip_visto, servidor.FAILS)
        self.assertNotIn("203.0.113.1", servidor.FAILS)

    # ---------- corpo grande ----------
    def test_corpo_grande_pelo_dominio_exige_o_pin(self):
        sessao = self.entra(servidor.net_config()["pin"])   # a entrada fica fora do teto abaixo
        with mock.patch.object(servidor, "MAX_BODY_ANON", 4):
            self.assertEqual(self.texto("POST", "/api/local/demandas/vista", b"{      }"),
                             (413, "Entre com o PIN antes de enviar arquivos."))
            self.assertEqual(self.dom("POST", "/api/local/demandas/vista", b"{      }", sessao)[0], 200)
            self.assertEqual(self.post("vista", b"{      }")[0], 200)


    # ---------- sem Host, e o _ip_cliente de perto ----------
    def test_pedido_sem_host_nao_vira_publico(self):
        with mock.patch.object(servidor, "HOSTS_PUB", frozenset({"xxxx"})):
            n, linha = self.raw(["GET /api/eu HTTP/1.0"])   # sem cabeçalho Host
            self.assertEqual((n, linha.split(" ")[1]), (1, "200"))   # segue sendo o computador principal
            n, linha = self.raw(["POST /api/local/demandas/vista HTTP/1.0", "Origin: http://XXXX",
                                 "Content-Type: application/json", "Content-Length: 2"], b"{}")
            self.assertEqual((n, linha.split(" ")[1]), (1, "403"))   # sem Host nenhuma origem casa

    def ip_handler(self, headers, ip="127.0.0.1"):
        h = servidor.Handler.__new__(servidor.Handler)
        h.headers = headers
        h.client_address = (ip, 4321)
        return h

    def test_ip_cliente_so_confia_no_cabecalho_do_dominio(self):
        casos = [
            ({"CF-Connecting-IP": "203.0.113.1"}, "127.0.0.1", "127.0.0.1"),                  # sem domínio: ignora
            ({"Host": self.DOM, "CF-Connecting-IP": "203.0.113.1"}, "127.0.0.1", "203.0.113.1"),   # o túnel
            ({"Host": self.DOM, "CF-Connecting-IP": "203.0.113.1"}, "192.168.0.9", "192.168.0.9"),  # não é o túnel
            ({"Host": self.DOM, "X-Forwarded-For": "203.0.113.9, lixo"}, "127.0.0.1", "203.0.113.9"),
            ({"Host": self.DOM, "X-Forwarded-For": "lixo, pior"}, "127.0.0.1", "127.0.0.1"),
            ({"Host": self.DOM, "CF-Connecting-IP": " 2001:db8::1 "}, "127.0.0.1", "2001:db8::1"),
            ({"Host": self.DOM}, "127.0.0.1", "127.0.0.1"),                                   # sem cabeçalho nenhum
        ]
        for headers, conexao, esperado in casos:
            self.assertEqual(self.ip_handler(headers, conexao)._ip_cliente(), esperado, headers)

    def test_main_anuncia_o_modo_hospedado(self):
        nao = AssertionError("não devia ligar servidor de verdade")
        with mock.patch.object(servidor, "HOSTS_PUB", frozenset({"b.exemplo.com", "a.exemplo.com"})), \
                mock.patch.object(servidor, "net_config", return_value={"on": False, "pin": "123456", "pin_op": "654321"}), \
                mock.patch.object(servidor, "sessions_load"), \
                mock.patch.object(servidor, "api_mod"), \
                mock.patch.object(servidor, "iniciar_fundo"), \
                mock.patch.object(servidor, "sempre", mock.Mock(side_effect=nao)), \
                mock.patch.object(servidor, "Server") as srv, \
                mock.patch("sys.stdout", io.StringIO()) as saida:
            servidor.main([])
        self.assertIn("Modo hospedado (só com PIN, nunca como o computador principal): "
                      "https://a.exemplo.com, https://b.exemplo.com", saida.getvalue())
        srv.return_value.serve_forever.assert_called_once()

    def test_main_calado_sem_a_variavel(self):
        with mock.patch.object(servidor, "HOSTS_PUB", frozenset()), \
                mock.patch.object(servidor, "net_config", return_value={"on": False, "pin": "123456", "pin_op": "654321"}), \
                mock.patch.object(servidor, "sessions_load"), \
                mock.patch.object(servidor, "api_mod"), \
                mock.patch.object(servidor, "iniciar_fundo"), \
                mock.patch.object(servidor, "Server"), \
                mock.patch("sys.stdout", io.StringIO()) as saida:
            servidor.main([])
        self.assertNotIn("Modo hospedado", saida.getvalue())


if __name__ == "__main__":
    unittest.main()
