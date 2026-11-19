"""QA da sessão G: avisos, e-mail, backup, configurações e robustez transversal, pelo HTTP de verdade.

Complementa (não repete) test_servidor.py, test_demandas_avisos.py, test_email_envio.py e test_demandas_backup.py:
aqui o foco é o caminho completo (servidor -> api -> arquivo/SMTP falso), os limites exatos de cada campo e o que
acontece com entrada malformada em TODA rota. Cada teste leva o id da matriz de docs/qa/avisos.md (NT, AP, AC, EM, BK,
CF, RB). Bug confirmado = @unittest.expectedFailure com o id do bug (B1...). Nunca envia e-mail de verdade: só o SMTP
falso desta pasta (127.0.0.1). Dados num diretório temporário por teste.

    py -3 -m unittest tests.test_qa_avisos
"""

from __future__ import annotations

import base64
import email
import email.policy
import hashlib
import http.client
import json
import os
import secrets
import shutil
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEMANDAS_DATA", tempfile.mkdtemp(prefix="dem-qa-g-"))
import servidor  # noqa: E402

JPG = b"\xff\xd8\xff\xe0" + b"j" * 40
PNG = b"\x89PNG\r\n\x1a\n" + b"p" * 40
XSS = '<img src=x onerror="alert(1)">'
MIN = 60000


class Base(unittest.TestCase):
    """Servidor real em 127.0.0.1 (papel "maquina": o Escritório) e uma pasta de dados nova por teste."""

    @classmethod
    def setUpClass(cls):
        cls.srv = servidor.Server(("127.0.0.1", 0), servidor.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.api = servidor.api_mod()
        cls.ds = cls.api.ds
        cls._iter = cls.api.ITER
        cls.api.ITER = 1000   # o valor real (100 000) é conferido em test_demandas_api

    @classmethod
    def tearDownClass(cls):
        cls.api.ITER = cls._iter
        servidor.NET_ON = False
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dem-qa-g-"))
        self.data = self.tmp / "data"
        self.data.mkdir()
        env = mock.patch.dict(os.environ, {"DEMANDAS_DATA": str(self.data)})
        env.start()
        self.addCleanup(env.stop)
        fs = mock.patch("os.fsync", lambda fd: None)   # durabilidade é do store; aqui só atrasa
        fs.start()
        self.addCleanup(fs.stop)
        self.api._TK.clear()
        self.api._FAILS.clear()
        self.api._TK_ARQ[0] = None
        for c in (servidor.SESSIONS, servidor.FAILS):
            c.clear()
        servidor._REV.update(key=None, rev=0)
        servidor.NET_ON = False
        self.addCleanup(shutil.rmtree, self.tmp, True)

    # --- HTTP ---
    def req(self, method, path, body=None, raw=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            dados = raw if raw is not None else (None if body is None else json.dumps(body).encode())
            h = {"Content-Type": "application/json"}
            h.update(headers or {})
            c.request(method, path, dados if method == "POST" else None, h)
            r = c.getresponse()
            return r.status, r.headers, r.read()
        finally:
            c.close()

    def chama(self, rest, body=None, tk=None, raw=None):
        """(status, json ou texto) de POST /api/local/demandas/<rest>."""
        b = None if body is None else dict(body, **({"tk": tk} if tk else {}))
        st, _, dados = self.req("POST", "/api/local/demandas/" + rest, b, raw)
        txt = dados.decode("utf-8", "replace")
        try:
            return st, json.loads(txt)
        except ValueError:
            return st, txt

    def ok(self, rest, body=None, tk=None):
        st, r = self.chama(rest, {} if body is None else body, tk)
        self.assertEqual(st, 200, "%s -> %s %s" % (rest, st, r))
        return r

    def erro(self, rest, body, tk=None, status=None):
        st, r = self.chama(rest, body, tk)
        self.assertGreaterEqual(st, 400, "%s deveria recusar: %s" % (rest, r))
        self.assertLess(st, 500, "%s deu erro do servidor: %s" % (rest, r))
        if status is not None:
            self.assertEqual(st, status, "%s -> %s %s" % (rest, st, r))
        return r

    def sys_(self, method, path, body=None, raw=None):
        """Rotas do sistema (/api/email, /api/backup, /api/avisos, /api/rede, /api/servidor): (status, json ou texto)."""
        st, _, dados = self.req(method, path, body, raw)
        txt = dados.decode("utf-8", "replace")
        try:
            return st, json.loads(txt)
        except ValueError:
            return st, txt

    def disco(self, nome="demandas.json"):
        return json.loads((self.data / nome).read_text(encoding="utf-8"))

    def op(self, rest, body=None, papel="operador"):
        """Direto no módulo, para os papéis que o HTTP local não alcança (operador sem sessão)."""
        return self.api.handle("POST", rest, dict(body or {}), {"papel": papel})

    # --- cenário: PCP (Helena), CNC (Carlos, Bruno) ---
    def setor(self, sid, nome, **extra):
        return self.ok("setor/salvar", dict({"modo": "novo", "id": sid, "nome": nome, "icone": "🗂️", "cor": "#6366F1",
                                              "rev": 0}, **extra))

    def pessoa(self, nome, setor, codigo, **extra):
        v = self.ok("pessoa/salvar", dict({"modo": "novo", "nome": nome, "setor": setor, "codigo": codigo, "rev": 0}, **extra))
        return v["pessoas"][-1]["id"]

    def entrar(self, pid, codigo):
        return self.ok("entrar", {"pessoa": pid, "codigo": codigo})["tk"]

    def mundo(self, emails=False):
        self.setor("PCP", "Planejamento")
        self.setor("CNC", "Corte CNC", **({"email": "cnc@empresa.com"} if emails else {}))
        self.h = self.pessoa("Helena", "PCP", "1111", **({"email": "helena@empresa.com"} if emails else {}))
        self.c = self.pessoa("Carlos", "CNC", "2222", **({"email": "carlos@empresa.com"} if emails else {}))
        self.b = self.pessoa("Bruno", "CNC", "3333")
        self.tk_h, self.tk_c, self.tk_b = (self.entrar(self.h, "1111"), self.entrar(self.c, "2222"), self.entrar(self.b, "3333"))

    def nova(self, tk=None, **kw):
        body = {"titulo": "Cortar chapas", "tipo": "dem", "motivo": "Outro", "prio": "norm", "est": 60,
                "para": {"s": "CNC", "p": None}, "desc": ""}
        body.update(kw)
        if not tk:
            body.setdefault("de_s", "PCP")
        v = self.ok("demanda/criar", body, tk)
        return max(v["demandas"], key=lambda d: int(d["id"][4:]))

    def notas(self, tk=None):
        return self.ok("vista", {}, tk)["notas"]


# =====================================================================================================
# 1. SINO E NOTAS (nota/lida, nota/todas, por pessoa, contador)
# =====================================================================================================

class Notas(Base):
    def setUp(self):
        super().setUp()
        self.mundo()

    def test_NT01_nota_da_fila_chega_ao_setor_todo_e_cada_um_marca_a_sua(self):
        self.nova(self.tk_h)
        nc, nb = self.notas(self.tk_c), self.notas(self.tk_b)
        self.assertEqual(([n["lida"] for n in nc], [n["lida"] for n in nb]), ([False], [False]))
        self.assertEqual(self.notas(self.tk_h), [], "quem pediu não recebe aviso do próprio pedido")
        self.assertEqual(self.notas(), [], "o Escritório só vê as notas dele (adm)")
        self.ok("nota/lida", {"nid": nc[0]["id"]}, self.tk_c)
        self.assertTrue(self.notas(self.tk_c)[0]["lida"])
        self.assertFalse(self.notas(self.tk_b)[0]["lida"], "o Bruno continua com a dele não lida")

    def test_NT02_marcar_de_novo_nao_grava(self):
        self.nova(self.tk_h)
        nid = self.notas(self.tk_c)[0]["id"]
        self.ok("nota/lida", {"nid": nid}, self.tk_c)
        rev = self.disco()["rev"]
        self.ok("nota/lida", {"nid": nid}, self.tk_c)
        self.ok("nota/todas", {}, self.tk_c)
        self.assertEqual(self.disco()["rev"], rev, "nada mudou: o rev não sobe e as telas não recarregam")

    def test_NT03_nota_so_para_uma_pessoa_e_de_mais_ninguem(self):
        self.nova(self.tk_h, para={"s": "CNC", "p": self.c})
        nc = self.notas(self.tk_c)
        self.assertEqual(len(nc), 1)
        self.assertEqual(self.notas(self.tk_b), [], "o colega do mesmo setor não vê a nota escolhida para o Carlos")
        nid = nc[0]["id"]
        for quem, tk in (("Bruno", self.tk_b), ("Helena", self.tk_h), ("Escritório", None)):
            self.assertEqual(self.erro("nota/lida", {"nid": nid}, tk, 403), "Notificação de outra pessoa.", quem)
        self.assertFalse(self.notas(self.tk_c)[0]["lida"], "recusadas: nada foi marcado")

    def test_NT04_escritorio_so_marca_as_proprias(self):
        d = self.nova(self.tk_h, prio="urg")
        adm = self.notas()
        self.assertEqual([(n["tipo"], n["dem"]) for n in adm], [("urg", d["id"])])
        nc = self.notas(self.tk_c)[0]["id"]
        self.assertEqual(self.erro("nota/lida", {"nid": nc}, None, 403), "Notificação de outra pessoa.")
        self.ok("nota/todas", {})
        self.assertTrue(self.notas()[0]["lida"])
        self.assertFalse(self.notas(self.tk_c)[0]["lida"], "marcar todas do Escritório não mexe nas do setor")

    def test_NT05_todas_marca_so_as_minhas(self):
        for i in range(3):
            self.nova(self.tk_h, titulo="Pedido %d" % i)
        self.nova(self.tk_h, titulo="Só do Carlos", para={"s": "CNC", "p": self.c})
        self.ok("nota/todas", {}, self.tk_c)
        self.assertEqual([n["lida"] for n in self.notas(self.tk_c)], [True] * 4)
        self.assertEqual([n["lida"] for n in self.notas(self.tk_b)], [False] * 3, "o Bruno ainda tem as três")

    def test_NT06_nid_invalido_nunca_vira_500(self):
        for nid in (99999, 0, -1, "1", 1.0, True, False, None, [], {}, [1], 2 ** 70, "x" * 1000):
            with self.subTest(nid=repr(nid)[:30]):
                self.assertEqual(self.erro("nota/lida", {"nid": nid}, self.tk_c, 404), "Notificação não encontrada.")
        self.assertEqual(self.erro("nota/lida", {}, self.tk_c, 404), "Notificação não encontrada.")

    def test_NT07_sem_identidade_ou_com_identidade_vencida(self):
        self.nova(self.tk_h)
        nid = self.notas(self.tk_c)[0]["id"]
        with self.assertRaises(self.api.ApiError) as c:
            self.op("nota/lida", {"nid": nid})   # aparelho de operador sem entrar
        self.assertEqual((c.exception.status, str(c.exception)), (403, "Identifique-se para usar as demandas."))
        self.assertEqual(self.erro("nota/lida", {"nid": nid}, "tk-que-nao-existe", 401), "Identifique-se de novo.")
        self.assertEqual(self.erro("nota/todas", {}, "tk-que-nao-existe", 401), "Identifique-se de novo.")
        rev = next(p["_rv"] for p in self.disco()["pessoas"] if p["id"] == self.c)
        self.ok("pessoa/ativar", {"id": self.c, "rev": rev})   # desativa o Carlos
        self.assertEqual(self.erro("nota/lida", {"nid": nid}, self.tk_c, 401), "Identifique-se de novo.")

    def test_NT08_so_as_1000_mais_novas_ficam_e_o_id_nunca_volta(self):
        ds = self.ds
        with self.api.LOCK:
            doc = ds.load()
            for i in range(1005):
                self.api._nota(doc, "adm", "late", "SOL-1001", "", "Sistema", i)
            ds.commit(doc)
        notas = self.disco()["notas"]
        self.assertEqual(len(notas), 1000)
        self.assertEqual([n["id"] for n in notas], list(range(6, 1006)), "saem as mais antigas; os ids seguem subindo")
        with self.api.LOCK:
            doc = ds.load()
            self.api._nota(doc, "adm", "late", "SOL-1001", "", "Sistema", 9)
            self.assertEqual(doc["notas"][-1]["id"], 1006)

    def test_NT09_vista_da_pessoa_nao_traz_nota_de_outro_setor(self):
        self.nova(self.tk_c, titulo="Do Carlos para o PCP", para={"s": "PCP", "p": None})
        self.nova(self.tk_h, titulo="Da Helena para a CNC")
        self.assertEqual([n["aud"] for n in self.notas(self.tk_h)], ["PCP"])
        self.assertEqual([n["aud"] for n in self.notas(self.tk_c)], ["CNC"])
        for n in self.notas(self.tk_c) + self.notas(self.tk_h):
            self.assertIn(n["pid"], (None, self.c, self.h, self.b))


# =====================================================================================================
# 2. "MEUS AVISOS" (aviso/prefs) e padrões da central (/api/avisos)
# =====================================================================================================

HORAS_OK = ("00:00", "23:59", "12:30", "06:00", "22:00", "09:09")
HORAS_RUINS = ("24:00", "23:60", "7:00", "07:0", "0700", "", " 22:00", "22:00 ", "22:00\n", "aa:bb", "22-00", "22:00:00",
               "２２:００", 2200, None, True, [], {})
EVENTOS = ("new", "fila", "accepted", "pause", "done", "canc", "nudge", "late", "comment")


class MeusAvisos(Base):
    def setUp(self):
        super().setUp()
        self.mundo()

    def prefs(self, body=None, tk=None):
        return self.chama("aviso/prefs", {} if body is None else body, tk)

    def av(self):
        return json.loads((self.data / "avisos.json").read_text(encoding="utf-8"))

    def test_AP01_sem_nada_gravado_e_o_padrao_da_tabela(self):
        st, r = self.prefs()
        self.assertEqual(st, 200)
        p = r["prefs"]
        self.assertEqual(set(p["eventos"]), set(EVENTOS))
        self.assertTrue(all(p["eventos"].values()))
        self.assertEqual((p["som"], p["vibrar"], p["agrupar_min"], p["urgente_fura"], p["proprio"]), ("curto", True, 10, True, False))
        self.assertEqual(p["silencio"], {"ligado": False, "ini": "22:00", "fim": "06:00"})
        self.assertFalse((self.data / "avisos.json").exists(), "ler não cria arquivo")

    def test_AP02_cada_evento_sozinho_por_pessoa(self):
        for k in EVENTOS:
            with self.subTest(evento=k):
                st, r = self.prefs({"prefs": {"eventos": {k: False}}}, self.tk_c)
                self.assertEqual(st, 200)
                self.assertEqual({e for e, v in r["prefs"]["eventos"].items() if not v}, {k})
                self.assertTrue(r["prefs"]["proprio"])
                self.assertEqual(self.av()["pessoas"][self.c], {"eventos": {k: False}}, "só a diferença fica no arquivo")
                self.assertTrue(self.prefs({}, self.tk_b)[1]["prefs"]["eventos"][k], "o Bruno não muda")
                self.assertTrue(self.prefs({})[1]["prefs"]["eventos"][k], "o Escritório não muda")
                self.assertEqual(self.prefs({"padrao": True}, self.tk_c)[0], 200)
        self.assertNotIn(self.c, self.av()["pessoas"])

    def test_AP03_hora_do_silencio_limite_valido_e_invalido(self):
        for h in HORAS_OK:
            with self.subTest(ok=h):
                st, r = self.prefs({"prefs": {"silencio": {"ligado": True, "ini": h, "fim": "06:00"}}}, self.tk_c)
                self.assertEqual((st, r["prefs"]["silencio"]["ini"]), (200, h))
        for h in HORAS_RUINS:
            with self.subTest(ruim=repr(h)):
                antes = self.prefs({}, self.tk_c)[1]
                for campo in ("ini", "fim"):
                    st, r = self.prefs({"prefs": {"silencio": {campo: h}}}, self.tk_c)
                    self.assertEqual((st, r), (400, "Horário de silêncio inválido: use HH:MM."))
                self.assertEqual(self.prefs({}, self.tk_c)[1], antes, "recusado = nada gravado")

    def test_AP04_silencio_e_eventos_com_tipo_errado(self):
        for s in ("x", 5, None, [], True, {"ligado": "true"}, {"ligado": 1}, {"ligado": None}, {"ini": None}):
            with self.subTest(silencio=repr(s)):
                self.assertEqual(self.prefs({"prefs": {"silencio": s}}, self.tk_c)[0], 400)
        for ev in ("x", 5, None, [], True, {"new": "sim"}, {"new": 1}, {"late": None}, {"new": True, "fila": "x"}):
            with self.subTest(eventos=repr(ev)):
                self.assertEqual(self.prefs({"prefs": {"eventos": ev}}, self.tk_c), (400, "Eventos inválidos."))
        for u in ("x", 1, None, [], {}):
            self.assertEqual(self.prefs({"prefs": {"urgente_fura": u}}, self.tk_c), (400, "Opção do urgente inválida."))
        self.assertFalse((self.data / "avisos.json").exists(), "nenhuma recusa gravou")

    def test_AP05_evento_que_nao_existe_e_campo_extra_sao_ignorados(self):
        st, r = self.prefs({"prefs": {"eventos": {"inventado": False, "new": False}, "extra": 1, "__proto__": {"x": 1}}}, self.tk_c)
        self.assertEqual(st, 200)
        self.assertNotIn("inventado", r["prefs"]["eventos"])
        self.assertEqual(self.av()["pessoas"][self.c], {"eventos": {"new": False}})
        self.assertEqual(self.prefs({"prefs": {}}, self.tk_c)[0], 200, "prefs vazio: nada muda")

    def test_AP06_som_vibrar_e_agrupar_sao_do_aparelho_a_pessoa_nao_grava(self):
        st, r = self.prefs({"prefs": {"som": "sino", "vibrar": False, "agrupar_min": 0, "urgente_fura": False}}, self.tk_c)
        self.assertEqual(st, 200)
        self.assertEqual((r["prefs"]["som"], r["prefs"]["vibrar"], r["prefs"]["agrupar_min"]), ("curto", True, 10))
        self.assertEqual(self.av()["pessoas"][self.c], {"urgente_fura": False}, "só a parte da pessoa")
        st, r = self.prefs({"prefs": {"som": "valor-invalido", "vibrar": "x", "agrupar_min": 77}}, self.tk_c)
        self.assertEqual(st, 200, "campos do aparelho nem são lidos")

    def test_AP07_prefs_que_nao_e_objeto(self):
        for p in ([], "x", 5, None, True, [1]):
            with self.subTest(prefs=repr(p)):
                self.assertEqual(self.prefs({"prefs": p}, self.tk_c), (400, "Pedido inválido."))

    def test_AP08_voltar_ao_padrao_so_com_true_e_ganha_de_prefs(self):
        self.prefs({"prefs": {"eventos": {"late": False}}}, self.tk_c)
        for v in (False, "true", 1, "x", None, [True]):   # nada disso é "voltar ao padrão": só lê
            st, r = self.prefs({"padrao": v}, self.tk_c)
            self.assertEqual((st, r["prefs"]["eventos"]["late"]), (200, False), repr(v))
        st, r = self.prefs({"padrao": True, "prefs": {"eventos": {"done": False}}}, self.tk_c)
        self.assertEqual((st, r["prefs"]["proprio"], r["prefs"]["eventos"]["done"]), (200, False, True))
        self.assertNotIn(self.c, self.av()["pessoas"])

    def test_AP09_quem_grava_e_so_dono_das_proprias(self):
        self.prefs({"prefs": {"eventos": {"canc": False}}})   # o Escritório (sem tk) é a chave "adm"
        self.prefs({"prefs": {"eventos": {"done": False}}}, self.tk_c)
        pessoas = self.av()["pessoas"]
        self.assertEqual(pessoas["adm"], {"eventos": {"canc": False}})
        self.assertEqual(pessoas[self.c], {"eventos": {"done": False}})
        self.assertNotIn(self.b, pessoas)
        self.assertEqual(self.erro("aviso/prefs", {}, "tk-errado", 401), "Identifique-se de novo.")
        with self.assertRaises(self.api.ApiError) as e:
            self.op("aviso/prefs", {"prefs": {}})
        self.assertEqual(e.exception.status, 403, "aparelho de operador sem entrar não lê nem grava")

    def test_AP10_arquivo_estragado_vira_padrao_e_o_proximo_salvar_conserta(self):
        for lixo in ("{x", "[]", '"x"', "null", '{"pessoas": []}', '{"pessoas": {"%s": "x"}}' % self.c,
                     '{"pessoas": {"%s": {"eventos": {"new": "x"}, "silencio": 5}}}' % self.c):
            with self.subTest(lixo=lixo[:30]):
                (self.data / "avisos.json").write_text(lixo, encoding="utf-8")
                st, r = self.prefs({}, self.tk_c)
                self.assertEqual((st, r["prefs"]["som"], r["prefs"]["eventos"]["new"]), (200, "curto", True))
                self.assertEqual(self.prefs({"prefs": {"eventos": {"new": False}}}, self.tk_c)[0], 200)
                self.assertFalse(self.prefs({}, self.tk_c)[1]["prefs"]["eventos"]["new"])


class PadroesDaCentral(Base):
    """/api/avisos: o padrão de quem nunca mexeu em "Meus avisos". Só o computador principal."""

    def central(self, body=None):
        return self.sys_("POST", "/api/avisos", body)

    def test_AC01_som_valido_e_invalido(self):
        for s in ("curto", "sino", "desligado"):
            self.assertEqual(self.central({"som": s})[1]["padrao"]["som"], s)
        for s in ("", "Curto", "bip", None, 1, True, [], {}, "sino ", "x" * 500):
            with self.subTest(som=repr(s)[:20]):
                self.assertEqual(self.central({"som": s}), (400, "Som inválido."))
        self.assertEqual(self.sys_("GET", "/api/avisos")[1]["padrao"]["som"], "desligado", "recusado não muda o que estava")

    def test_AC02_agrupar_so_0_5_ou_10(self):
        for n in (0, 5, 10):
            self.assertEqual(self.central({"agrupar_min": n})[1]["padrao"]["agrupar_min"], n)
        for n in (1, 4, 6, 15, 11, -1, 3600, "5", None, True, False, [], {}, "10"):
            with self.subTest(agrupar=repr(n)):
                self.assertEqual(self.central({"agrupar_min": n}), (400, "Agrupamento inválido."))
        self.assertEqual(self.sys_("GET", "/api/avisos")[1]["padrao"]["agrupar_min"], 10)

    def test_AC03_vibrar_e_urgente_so_booleano(self):
        for campo, msg in (("vibrar", "Opção de vibração inválida."), ("urgente_fura", "Opção do urgente inválida.")):
            for v in (True, False):
                self.assertEqual(self.central({campo: v})[1]["padrao"][campo], v)
            for v in ("true", 1, 0, None, [], {}, "false"):
                with self.subTest(campo=campo, valor=repr(v)):
                    self.assertEqual(self.central({campo: v}), (400, msg))

    def test_AC04_silencio_e_eventos(self):
        r = self.central({"silencio": {"ligado": True, "ini": "23:00", "fim": "05:00"}, "eventos": {"late": False}})[1]["padrao"]
        self.assertEqual(r["silencio"], {"ligado": True, "ini": "23:00", "fim": "05:00"})
        self.assertFalse(r["eventos"]["late"])
        self.assertTrue(r["eventos"]["new"], "só o que veio muda")
        for h in HORAS_RUINS:
            self.assertEqual(self.central({"silencio": {"ini": h}})[0], 400, repr(h))
        for ev in ("x", [], {"new": "sim"}, {"fila": 1}):
            self.assertEqual(self.central({"eventos": ev}), (400, "Eventos inválidos."))
        self.assertEqual(self.central({"eventos": {"inventado": False}})[0], 200)

    def test_AC05_um_campo_ruim_recusa_o_pedido_inteiro(self):
        self.central({"som": "sino"})
        self.assertEqual(self.central({"som": "desligado", "agrupar_min": 7})[0], 400)
        self.assertEqual(self.sys_("GET", "/api/avisos")[1]["padrao"]["som"], "sino")

    def test_AC06_padrao_novo_vale_para_quem_nao_mexeu_e_nao_para_quem_mexeu(self):
        self.setor("PCP", "Planejamento")
        a = self.pessoa("Ana", "PCP", "1111")
        b = self.pessoa("Beto", "PCP", "2222")
        ta, tb = self.entrar(a, "1111"), self.entrar(b, "2222")
        self.chama("aviso/prefs", {"prefs": {"eventos": {"canc": False}}}, tb)
        self.central({"eventos": {"canc": False, "done": False}, "silencio": {"ligado": True}})
        pa = self.chama("aviso/prefs", {}, ta)[1]["prefs"]
        pb = self.chama("aviso/prefs", {}, tb)[1]["prefs"]
        self.assertEqual((pa["eventos"]["done"], pa["silencio"]["ligado"], pa["proprio"]), (False, True, False))
        self.assertEqual((pb["eventos"]["done"], pb["proprio"]), (False, False), "a diferença dele passou a coincidir com a central")
        self.central({"eventos": {"canc": True}})
        self.assertTrue(self.chama("aviso/prefs", {}, ta)[1]["prefs"]["eventos"]["canc"], "quem não mexeu acompanha a central")
        self.assertFalse(self.chama("aviso/prefs", {}, tb)[1]["prefs"]["eventos"]["canc"], "quem mexeu mantém a escolha")

    def test_AC07_corpo_e_arquivo_malformados(self):
        for raw in (b"{x", b"\xff\xfe", b"[1]", b'"x"', b"5", b"null"):
            st, _ = self.sys_("POST", "/api/avisos", raw=raw)
            self.assertIn(st, (400,), raw)
        (self.data / "avisos.json").write_text("{x", encoding="utf-8")
        self.assertEqual(self.sys_("GET", "/api/avisos")[1]["padrao"]["som"], "curto")
        self.assertEqual(self.central({"som": "sino"})[0], 200, "o salvar conserta o arquivo")
        self.assertEqual(json.loads((self.data / "avisos.json").read_text(encoding="utf-8"))["padrao"]["som"], "sino")

    def test_AC08_so_o_computador_principal(self):
        # o operador sem sessão e a rede são testados em test_servidor.Avisos; aqui, o papel que o módulo recebe
        self.assertFalse(servidor.pode("operador", "configurar"))
        self.assertEqual(self.sys_("GET", "/api/avisos/x"), (404, "Não encontrado."))

    def setor(self, sid, nome):
        return self.ok("setor/salvar", {"modo": "novo", "id": sid, "nome": nome, "icone": "🗂️", "cor": "#6366F1", "rev": 0})


# =====================================================================================================
# 3. E-MAIL: configuração, cadastro, SMTP falso, eventos, fila, ✉ na gaveta
# =====================================================================================================

class Atende(socketserver.StreamRequestHandler):
    """O mínimo de um servidor SMTP: anuncia AUTH PLAIN se o dono mandar, guarda as mensagens e os logins."""

    def handle(self):
        s = self.server

        def w(t):
            self.wfile.write((t + "\r\n").encode())
            self.wfile.flush()

        w("220 falso ESMTP")
        dados, corpo, de, para = False, [], None, []
        while True:
            try:
                bruto = self.rfile.readline()
            except OSError:
                return
            if not bruto:
                return
            linha = bruto.decode("utf-8", "replace").rstrip("\r\n")
            if dados:
                if linha == ".":
                    dados = False
                    s.recebidas.append({"de": de, "para": list(para), "bruto": "\r\n".join(corpo)})
                    w("250 2.0.0 aceito")
                    corpo, para = [], []
                else:
                    corpo.append(linha[1:] if linha.startswith("..") else linha)
                continue
            c = linha.split(" ", 1)[0].upper()
            if c == "EHLO":
                if s.auth is None:
                    w("250 falso")
                else:
                    w("250-falso")
                    w("250 AUTH PLAIN")
            elif c == "AUTH":
                partes = base64.b64decode(linha.split(" ")[-1]).split(b"\0")
                s.logins.append((partes[1].decode(), partes[2].decode()))
                w("235 2.7.0 ok" if s.auth == "ok" else "535 5.7.8 usuario ou senha recusados")
            elif c == "MAIL":
                de = linha
                w("250 ok")
            elif c == "RCPT":
                if s.rcpt:
                    w(s.rcpt)
                else:
                    para.append(linha)
                    w("250 ok")
            elif c == "DATA":
                w("354 manda")
                dados = True
            elif c == "QUIT":
                w("221 tchau")
                return
            elif c in ("RSET", "NOOP"):
                w("250 ok")
            else:
                w("502 comando desconhecido")


class SMTPFalso(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), Atende)
        self.recebidas, self.logins = [], []
        self.auth, self.rcpt = None, None   # auth: None = não anuncia, "ok" ou "recusa"; rcpt: resposta fixa ao RCPT


EV7 = ("created", "started", "done", "nudge", "late", "comment", "canc")
SEG = ("starttls", "ssl", "nenhuma")
FILA = ("setor_ou_pessoas", "so_setor", "pessoas")
N300 = 300 - len(" <c@x.com>")
EMAIL254 = "a" * 64 + "@" + "d" * 185 + ".com"

CAMPOS_EMAIL = [   # campo, valores aceitos (e o guardado), valores recusados
    ("host", ["a" * 253, "smtp.empresa.com.br", " smtp.x.com "], ["a" * 254, "a b", "smtp://x", "x/y", "é.com", 5, None, [], "x:25"]),
    ("porta", [1, 587, 65535], [0, 65536, -1, "587", 587.0, True, None, [], 2 ** 40]),
    ("seguranca", list(SEG), ["tls", "", None, True, "STARTTLS", ["ssl"]]),
    ("usuario", ["", "u" * 254, "ana@x.com"], ["u" * 255, "a\nb", "a\x00b", 5, None, []]),
    ("remetente", ["", "c@x.com", "Central de demandas <c@x.com>", "X" * N300 + " <c@x.com>"],
     ["x", "c@x.com\nBcc: z@z.com", "X" * (N300 + 1) + " <c@x.com>", 5, None, "A <b>", "c@x.com\r\nX: y", "<>"]),
    ("link_base", ["", "http://" + "a" * 200, "https://x.com:8090", "http://192.168.0.20:8090/"],
     ["http://" + "a" * 201, "ftp://x", "javascript:alert(1)", "http://a b", 'http://a"b', "http://a<b", "http://", 5, None, "//x.com"]),
    ("fila_setor", list(FILA), ["x", None, "", True, "Pessoas"]),
    ("copia_solicitante", [True, False], ["true", 1, 0, None, "x", []]),
    ("descricao", [True, False], ["true", 1, 0, None, "x", []]),
]


class EmailConfig(Base):
    def setUp(self):
        super().setUp()
        self.setor("PCP", "Planejamento")

    def cfg(self):
        return self.sys_("GET", "/api/email")[1]["cfg"]

    def test_EM01_padrao_sem_arquivo(self):
        st, r = self.sys_("GET", "/api/email")
        self.assertEqual(st, 200)
        c = r["cfg"]
        self.assertEqual((c["ligado"], c["host"], c["porta"], c["seguranca"], c["fila_setor"], c["descricao"], c["copia_solicitante"]),
                         (False, "", 587, "starttls", "setor_ou_pessoas", True, False))
        self.assertEqual({k for k, v in c["eventos"].items() if v}, {"created"}, "só 'demanda nova' vem ligado")
        self.assertEqual(set(c["eventos"]), set(EV7))
        self.assertEqual((c["tem_senha"], c["senha_abre"]), (False, False))
        self.assertNotIn("senha", c)
        self.assertNotIn("instalacao", c, "o sorteio interno não vai para a tela")
        self.assertEqual((r["estado"]["pendentes"], r["estado"]["pausada"]), (0, None))
        self.assertFalse((self.data / "email.json").exists(), "ler não cria arquivo")

    def test_EM02_cada_campo_no_limite_exato_e_um_alem(self):
        for campo, bons, ruins in CAMPOS_EMAIL:
            for v in bons:
                with self.subTest(campo=campo, ok=repr(v)[:30]):
                    st, r = self.sys_("POST", "/api/email", {campo: v})
                    self.assertEqual(st, 200, r)
                    self.assertEqual(r["cfg"][campo], v.strip() if isinstance(v, str) else v)
            for v in ruins:
                with self.subTest(campo=campo, ruim=repr(v)[:30]):
                    antes = self.cfg()
                    st, r = self.sys_("POST", "/api/email", {campo: v})
                    self.assertEqual(st, 400, r)
                    self.assertEqual(self.cfg(), antes, "recusado: nada mudou")

    def test_EM03_eventos_um_a_um_e_tipos(self):
        for k in EV7:
            with self.subTest(evento=k):
                r = self.sys_("POST", "/api/email", {"eventos": {k: True}})[1]["cfg"]["eventos"]
                self.assertTrue(r[k])
                r = self.sys_("POST", "/api/email", {"eventos": {k: False}})[1]["cfg"]["eventos"]
                self.assertFalse(r[k])
        for ev in ("x", 5, None, [], True, {"done": "sim"}, {"late": 1}, {"created": None}):
            with self.subTest(eventos=repr(ev)):
                self.assertEqual(self.sys_("POST", "/api/email", {"eventos": ev}), (400, "Eventos inválidos."))
        r = self.sys_("POST", "/api/email", {"eventos": {"inventado": True, "done": True}})[1]["cfg"]["eventos"]
        self.assertNotIn("inventado", r)
        self.assertTrue(r["done"])

    def test_EM04_ligar_exige_servidor_e_remetente(self):
        msg = (400, "Para ligar o e-mail, preencha o servidor e o remetente.")
        self.assertEqual(self.sys_("POST", "/api/email", {"ligado": True}), msg)
        self.assertEqual(self.sys_("POST", "/api/email", {"ligado": True, "host": "smtp.x.com"}), msg)
        self.assertEqual(self.sys_("POST", "/api/email", {"ligado": True, "remetente": "c@x.com"}), msg)
        self.assertEqual(self.sys_("POST", "/api/email", {"ligado": True, "host": "smtp.x.com", "remetente": "c@x.com"})[0], 200)
        # já ligado, esvaziar o servidor também é recusado (o estado final nunca fica ligado sem servidor)
        self.assertEqual(self.sys_("POST", "/api/email", {"host": ""}), msg)
        self.assertEqual(self.sys_("POST", "/api/email", {"ligado": False, "host": ""})[0], 200)

    def test_EM05_um_campo_ruim_recusa_tudo_e_nao_toca_no_arquivo(self):
        self.sys_("POST", "/api/email", {"host": "smtp.x.com", "porta": 25})
        antes = (self.data / "email.json").read_bytes()
        st, _ = self.sys_("POST", "/api/email", {"host": "smtp.novo.com", "porta": 0, "senha": "x"})
        self.assertEqual(st, 400)
        self.assertEqual((self.data / "email.json").read_bytes(), antes)

    def test_EM06_senha_limite_troca_apaga_e_nunca_volta(self):
        seg = "S" * 500
        st, r = self.sys_("POST", "/api/email", {"senha": seg})
        self.assertEqual((st, r["cfg"]["tem_senha"]), (200, True))
        for ruim in ("S" * 501, 5, ["x"], {"a": 1}, True):
            self.assertEqual(self.sys_("POST", "/api/email", {"senha": ruim}), (400, "Senha inválida."), repr(ruim)[:20])
        self.assertTrue(self.cfg()["tem_senha"], "recusada: a anterior continua")
        for manter in ({}, {"senha": None}, {"host": "smtp.x.com"}):
            self.assertTrue(self.sys_("POST", "/api/email", manter)[1]["cfg"]["tem_senha"], manter)
        todo = json.dumps(self.sys_("GET", "/api/email")[1])
        self.assertNotIn(seg, todo)
        bruto = (self.data / "email.json").read_text(encoding="utf-8")
        if '"dpapi"' in bruto:
            self.assertNotIn(seg, bruto, "no Windows a senha é cifrada no disco")
            self.assertTrue(self.cfg()["senha_abre"])
        self.assertFalse(self.sys_("POST", "/api/email", {"senha": ""})[1]["cfg"]["tem_senha"], "'' apaga")

    def test_EM07_corpo_malformado(self):
        for raw in (b"{x", b"\xff", b"[1]", b'"x"', b"null", b"5", b"true"):
            st, _ = self.sys_("POST", "/api/email", raw=raw)
            self.assertEqual(st, 400, raw)
        for acao in ("retomar", "x", None, 5, [], {}, "RETOMAR", True):
            st, r = self.sys_("POST", "/api/email/fila", {"acao": acao})
            self.assertEqual(st, 200 if acao == "retomar" else 400, (acao, r))

    def test_EM08_email_de_pessoa_e_setor_limites_e_injecao(self):
        bons = [("a@b.co", "a@b.co"), (" Ana.Silva@Empresa.COM.br ", "ana.silva@empresa.com.br"), ("u" * 64 + "@x.com", "u" * 64 + "@x.com"),
                (EMAIL254, EMAIL254), ("a+b_c-d@sub.dominio.com", "a+b_c-d@sub.dominio.com")]
        ruins = ["u" * 65 + "@x.com", "a" * 64 + "@" + "d" * 186 + ".com", "a@b", "a@b.c", "a b@c.com", "a@b.com,c@d.com",
                 "a@b.com;c@d.com", "<a@b.com>", 'a"b@c.com', "a@b.com\nBcc: x@y.com", "a@@b.com", "@b.com",
                 "a@.com", 5, [], {}, True, "Ana <a@b.com>", "a@b.com\t x"]
        self.assertEqual(len(EMAIL254), 254)
        for n, (digitado, guardado) in enumerate(bons):
            with self.subTest(ok=digitado[:30]):
                v = self.ok("pessoa/salvar", {"modo": "novo", "nome": "Pessoa %d" % n, "setor": "PCP", "codigo": "1234", "rev": 0,
                                              "email": digitado})
                self.assertEqual(v["pessoas"][-1]["email"], guardado)
                self.assertEqual(self.disco()["pessoas"][-1]["email"], guardado)
        pid = v["pessoas"][-1]["id"]

        def rev():
            return next(p["_rv"] for p in self.disco()["pessoas"] if p["id"] == pid)

        for ruim in ruins:
            with self.subTest(ruim=repr(ruim)[:40]):
                self.assertEqual(self.chama("pessoa/salvar", {"modo": "editar", "id": pid, "nome": "X Y", "setor": "PCP", "rev": rev(),
                                                              "email": ruim})[0], 400)
                self.assertEqual(self.chama("setor/salvar", {"modo": "editar", "id": "PCP", "nome": "Plan", "icone": "🗂️", "cor": "#6366F1",
                                                             "rev": self.disco()["setores"][0]["_rv"], "email": ruim})[0], 400)
        # vazio, espaços e None tiram o e-mail; campo ausente não mexe
        base = {"modo": "editar", "id": pid, "nome": "Pessoa Y", "setor": "PCP"}
        self.ok("pessoa/salvar", dict(base, rev=rev()))
        self.assertIn("email", self.disco()["pessoas"][-1], "ausente = não mexe")
        for vazio in ("", "   ", None):
            self.ok("pessoa/salvar", dict(base, rev=rev(), email="a@b.co"))
            self.ok("pessoa/salvar", dict(base, rev=rev(), email=vazio))
            self.assertNotIn("email", self.disco()["pessoas"][-1], repr(vazio))

    def test_EM09_email_so_aparece_para_o_escritorio(self):
        self.setor("CNC", "Corte", email="cnc@empresa.com")
        p = self.pessoa("Carlos", "CNC", "2222", email="carlos@empresa.com")
        tk = self.entrar(p, "2222")
        self.assertIn("@empresa.com", json.dumps(self.ok("vista")))
        self.assertNotIn("@", json.dumps(self.ok("vista", {}, tk)), "a pessoa não vê e-mail de ninguém")
        pub = self.api.handle("GET", "", {}, {"papel": "operador"})
        self.assertNotIn("@", json.dumps(pub), "a lista pública do aparelho de operador também não")


class EmailEnvio(Base):
    """E-mail ligado de ponta a ponta: ação na tela -> fila -> SMTP falso."""

    def setUp(self):
        super().setUp()
        self.mundo(emails=True)
        self.smtp = SMTPFalso()
        threading.Thread(target=self.smtp.serve_forever, daemon=True).start()
        self.addCleanup(self.smtp.server_close)
        self.addCleanup(self.smtp.shutdown)
        self.mail = servidor.email_mod()
        self.cfg(ligado=True, host="127.0.0.1", porta=self.smtp.server_address[1], seguranca="nenhuma",
                 remetente="Central <central@empresa.com>", link_base="http://192.168.0.20:8090",
                 eventos={k: True for k in EV7})
        t = mock.patch.object(self.mail, "TIMEOUT", 3)
        t.start()
        self.addCleanup(t.stop)

    def cfg(self, **kw):
        st, r = self.sys_("POST", "/api/email", kw)
        self.assertEqual(st, 200, r)
        return r["cfg"]

    def fila(self):
        p = self.data / "email-fila.json"
        return json.loads(p.read_text(encoding="utf-8"))["itens"] if p.exists() else []

    def rodar(self, depois_ms=5000):
        self.mail.tarefa(int(time.time() * 1000) + depois_ms)

    def msgs(self):
        return [email.message_from_string(m["bruto"], policy=email.policy.default) for m in self.smtp.recebidas]

    def estado(self):
        return self.sys_("GET", "/api/email")[1]["estado"]

    def test_EM10_cada_evento_vira_um_email_para_quem_deve_receber(self):
        self.cfg(copia_solicitante=True)
        d1 = self.nova(self.tk_h, titulo="Cortar chapas de MDF")["id"]
        self.ok("demanda/aceitar", {"id": d1}, self.tk_c)
        self.ok("demanda/comentar", {"id": d1, "texto": "Preciso da medida"}, self.tk_c)
        self.ok("demanda/comentar", {"id": d1, "texto": "Mando agora"}, self.tk_h)
        self.ok("demanda/cobrar", {"id": d1}, self.tk_h)
        self.ok("demanda/concluir", {"id": d1}, self.tk_c)
        d2 = self.nova(self.tk_h, titulo="Pedido que vai ser cancelado")["id"]
        self.ok("demanda/cancelar", {"id": d2, "motivo": "Mudou o projeto"}, self.tk_h)
        d3 = self.nova(self.tk_h, titulo="Pedido que vai atrasar")["id"]
        self.ok("demanda/prioridade", {"id": d3, "prio": "high"})   # prioridade não é evento de e-mail
        self.ok("demanda/estender", {"id": d3, "minutos": 30})        # prazo também não
        self.assertTrue(self.api.tick(int(time.time() * 1000) + 30 * 86400000), "o atraso é marcado pela thread de fundo")
        esperado = [(d1, "created", ["cnc@empresa.com"], ["helena@empresa.com"]), (d1, "started", ["helena@empresa.com"], []),
                    (d1, "comment", ["helena@empresa.com"], []), (d1, "comment", ["carlos@empresa.com"], ["helena@empresa.com"]),
                    (d1, "nudge", ["carlos@empresa.com"], ["helena@empresa.com"]), (d1, "done", ["helena@empresa.com"], []),
                    (d2, "created", ["cnc@empresa.com"], ["helena@empresa.com"]), (d2, "canc", ["cnc@empresa.com"], ["helena@empresa.com"]),
                    (d3, "created", ["cnc@empresa.com"], ["helena@empresa.com"]), (d3, "late", ["cnc@empresa.com"], ["helena@empresa.com"])]
        self.assertEqual([(i["dem"], i["ev"], i["para"], i["cc"]) for i in self.fila()], esperado)
        self.rodar(31 * 86400000)   # o e-mail do atraso nasce com a hora do atraso (30 dias adiante)
        self.assertEqual(len(self.smtp.recebidas), len(esperado))
        self.assertEqual(self.estado()["pendentes"], 0)
        ms = self.msgs()
        self.assertEqual(len({m["Message-ID"] for m in ms}), len(ms), "cada e-mail tem o seu Message-ID")
        raiz = {m["X-Central-Demanda"]: m["Message-ID"] for m in ms if m["In-Reply-To"] is None}
        self.assertEqual(set(raiz), {d1, d2, d3}, "só o primeiro e-mail de cada demanda abre um fio")
        for m in ms:
            self.assertEqual(m["Auto-Submitted"], "auto-generated")
            self.assertRegex(m["Subject"], r"^\[SOL-\d+\] ")
            if m["In-Reply-To"] is not None:
                self.assertEqual(m["In-Reply-To"], raiz[m["X-Central-Demanda"]], "no mesmo fio da demanda")
            corpo = m.get_body(preferencelist=("plain",)).get_content()
            self.assertIn("Abrir a demanda: http://192.168.0.20:8090/#" + m["X-Central-Demanda"], corpo)

    def test_EM11_evento_desligado_e_email_desligado_nao_enfileiram(self):
        self.cfg(eventos={"created": False})
        self.nova(self.tk_h)
        self.assertEqual(self.fila(), [], "evento desligado: nada na fila")
        self.cfg(eventos={"created": True}, ligado=False)
        self.nova(self.tk_h)
        self.assertEqual(self.fila(), [], "e-mail desligado: nada guardado para depois")
        self.cfg(ligado=True)
        self.nova(self.tk_h)
        self.assertEqual(len(self.fila()), 1)
        self.cfg(ligado=False)
        self.rodar()
        self.assertEqual(self.smtp.recebidas, [], "desligado a thread não manda o que sobrou")

    def test_EM12_sem_destinatario_so_no_registro(self):
        self.cfg(fila_setor="so_setor")
        d = self.nova(self.tk_c, para={"s": "PCP", "p": None})   # o setor PCP não tem e-mail
        self.assertEqual(self.fila(), [])
        v = self.ok("vista")
        self.assertEqual([e["status"] for e in v["emails"][d["id"]]], ["sem_destinatario"])

    def test_EM13_linhas_da_gaveta_so_para_o_escritorio(self):
        d = self.nova(self.tk_h)["id"]
        self.rodar()
        linhas = self.ok("vista")["emails"][d]
        self.assertEqual([(e["ev"], e["status"], e["para"]) for e in linhas], [("created", "ok", ["cnc@empresa.com"])])
        self.assertEqual(set(linhas[0]), {"t", "ev", "para", "status"}, "sem o item guardado nem o erro")
        self.assertNotIn("emails", self.ok("vista", {}, self.tk_c))
        self.assertNotIn("emails", self.ok("vista", {}, self.tk_h))

    def test_EM14_texto_do_usuario_vai_escapado_no_html_do_email(self):
        p = self.pessoa("<script>alert(1)</script>", "CNC", "5555")
        tk = self.entrar(p, "5555")
        d = self.nova(self.tk_h, titulo=XSS, desc="<b>negrito</b> & \"aspas\"", para={"s": "CNC", "p": p})["id"]
        self.ok("demanda/aceitar", {"id": d}, tk)
        self.ok("demanda/comentar", {"id": d, "texto": "<iframe src=x></iframe>"}, tk)
        self.rodar()
        self.assertGreaterEqual(len(self.msgs()), 3)
        for m in self.msgs():
            html = m.get_body(preferencelist=("html",)).get_content()
            for cru in ("<img", "<script", "<iframe", "<b>", 'onerror="'):
                self.assertNotIn(cru, html, "%s sem escape em %s" % (cru, m["Subject"]))
            self.assertIn("&lt;", html)
        self.assertEqual(self.msgs()[0]["Subject"], "[%s] %s" % (d, XSS), "no assunto (texto puro) o título vai como foi digitado")

    def test_EM15_link_com_e_sem_barra_e_sem_link(self):
        self.cfg(link_base="http://192.168.0.20:8090/")
        d = self.nova(self.tk_h)["id"]
        self.rodar()   # o link vale a configuração da hora do envio
        self.cfg(link_base="")
        self.nova(self.tk_h)
        self.rodar()
        a, b = self.msgs()
        self.assertIn("http://192.168.0.20:8090/#" + d, a.get_body(preferencelist=("plain",)).get_content())
        self.assertNotIn("//#", a.get_body(preferencelist=("plain",)).get_content())
        self.assertIn('href="http://192.168.0.20:8090/#%s"' % d, a.get_body(preferencelist=("html",)).get_content())
        self.assertNotIn("Abrir a demanda", b.get_body(preferencelist=("plain",)).get_content())
        self.assertNotIn("href=", b.get_body(preferencelist=("html",)).get_content())

    def test_EM16_descricao_desligada_nao_vai_no_email(self):
        self.cfg(descricao=False)
        self.nova(self.tk_h, desc="Texto secreto da descrição")
        self.rodar()
        self.assertNotIn("secreto", self.smtp.recebidas[0]["bruto"])
        self.cfg(descricao=True)
        self.nova(self.tk_h, desc="Texto secreto da descrição")
        self.rodar()
        self.assertIn("secreto", self.smtp.recebidas[1]["bruto"])

    def test_EM17_B3_titulo_com_separador_de_linha_unicode_e_recusado(self):
        """B3: U+2028 e U+0085 viravam quebra de linha no assunto do e-mail (ValueError, aviso perdido): o título os recusa."""
        for ch in ("\u2028", "\u0085", "\u2029"):
            with self.assertRaises(AssertionError) as c:   # o ajudante `ok` falha quando o servidor não responde 200
                self.nova(self.tk_h, titulo="Cortar" + ch + "chapas")
            self.assertIn("-> 400", str(c.exception))

    def test_EM18_fila_falha_permanente_reenviar_e_limpar(self):
        self.smtp.rcpt = "550 5.1.1 caixa nao existe"
        self.nova(self.tk_h)
        self.rodar()
        e = self.estado()
        self.assertEqual((e["pendentes"], e["falhas_24h"]), (0, 1))
        self.assertEqual(e["log"][0]["status"], "falhou")
        self.assertNotIn("item", e["log"][0], "o item guardado não vai para a tela")
        st, r = self.sys_("POST", "/api/email/fila", {"acao": "reenviar_falhas"})
        self.assertEqual((st, r["mexeu"], r["estado"]["pendentes"]), (200, 1, 1))
        self.smtp.rcpt = None
        self.rodar()
        self.assertEqual(len(self.smtp.recebidas), 1)
        e = self.estado()
        self.assertEqual((e["pendentes"], e["falhas_24h"], e["enviados_hoje"]), (0, 0, 1), "reenviada: a falha deixa de contar")
        self.smtp.rcpt = "550 5.1.1 x"
        self.nova(self.tk_h)
        self.rodar()
        self.assertEqual(self.sys_("POST", "/api/email/fila", {"acao": "limpar_falhas"})[1]["mexeu"], 1)
        self.assertEqual(self.estado()["falhas_24h"], 0)
        self.assertEqual(self.sys_("POST", "/api/email/fila", {"acao": "reenviar_falhas"})[1]["mexeu"], 0, "limpa não volta")

    def test_EM19_senha_recusada_pausa_a_fila_e_retomar_manda_tudo(self):
        self.cfg(usuario="central", senha="errada")
        self.smtp.auth = "recusa"
        for _ in range(3):
            self.nova(self.tk_h)
        self.rodar()
        e = self.estado()
        self.assertEqual(e["pendentes"], 3)
        self.assertIsNotNone(e["pausada"])
        self.assertEqual(len(self.smtp.logins), 1, "um login só: insistir bloquearia a conta")
        self.assertNotIn("errada", json.dumps(self.sys_("GET", "/api/email")[1]))
        self.rodar()
        self.assertEqual(len(self.smtp.logins), 1, "pausada: a rodada seguinte nem conecta")
        self.smtp.auth = "ok"
        self.assertEqual(self.sys_("POST", "/api/email/fila", {"acao": "retomar"})[1]["mexeu"], 3)
        self.rodar()
        self.assertEqual((len(self.smtp.recebidas), self.estado()["pendentes"]), (3, 0))

    def test_EM20_enviar_teste_ok_com_o_formulario_sem_salvar(self):
        st, r = self.sys_("POST", "/api/email/teste", {"para": " Ana@Empresa.COM "})
        self.assertEqual(st, 200)
        t = r["teste"]
        self.assertTrue(t["ok"], t)
        self.assertRegex(t["msg"], r"^Enviado para ana@empresa\.com · conectou em 127\.0\.0\.1:%d sem criptografia em \d+,\d s\." % self.smtp.server_address[1])
        m = self.msgs()[0]
        self.assertEqual((m["Subject"], m["To"]), ("Teste da Central de demandas", "ana@empresa.com"))
        antes = (self.data / "email.json").read_bytes()
        t = self.sys_("POST", "/api/email/teste", {"para": "ana@empresa.com", "porta": 1, "host": "127.0.0.1"})[1]["teste"]
        self.assertFalse(t["ok"], "o teste usa a porta do formulário (1: ninguém ouve)")
        self.assertEqual((self.data / "email.json").read_bytes(), antes, "testar não salva")
        self.assertEqual(self.sys_("GET", "/api/email")[1]["cfg"]["porta"], self.smtp.server_address[1])

    def test_EM21_enviar_teste_destinatario_limites_e_tipos(self):
        self.assertTrue(self.sys_("POST", "/api/email/teste", {"para": EMAIL254})[1]["teste"]["ok"])
        for ruim in ("a" * 64 + "@" + "d" * 186 + ".com", "x", "", "a@b", None, 5, [], {}, True, "a@b.com,c@d.com", "a@b.com\nBcc: x@y.com"):
            with self.subTest(para=repr(ruim)[:30]):
                self.assertEqual(self.sys_("POST", "/api/email/teste", {"para": ruim}), (400, "E-mail do teste inválido."))
        self.assertEqual(self.sys_("POST", "/api/email/teste", {}), (400, "E-mail do teste inválido."))
        self.assertEqual(self.sys_("POST", "/api/email/teste", {"para": "a@b.com", "porta": 0})[0], 400, "campo ruim do formulário")
        self.assertEqual(len(self.smtp.recebidas), 1, "nenhum dos recusados chegou ao SMTP")

    def test_EM22_teste_usa_a_senha_digitada_ou_a_guardada(self):
        self.smtp.auth = "ok"
        self.cfg(usuario="central", senha="guardada")
        self.sys_("POST", "/api/email/teste", {"para": "a@b.com"})
        self.sys_("POST", "/api/email/teste", {"para": "a@b.com", "senha": "digitada"})
        self.sys_("POST", "/api/email/teste", {"para": "a@b.com", "senha": ""})
        self.assertEqual(self.smtp.logins, [("central", "guardada"), ("central", "digitada"), ("central", "guardada")])
        self.assertEqual(self.sys_("GET", "/api/email")[1]["cfg"]["tem_senha"], True)

    def test_EM23_teste_com_falha_vira_frase_em_portugues_e_nunca_500(self):
        self.cfg(usuario="central", senha="senha-x")
        self.smtp.auth = "recusa"
        t = self.sys_("POST", "/api/email/teste", {"para": "a@b.com"})[1]["teste"]
        self.assertFalse(t["ok"])
        self.assertRegex(t["erro"], r"^Conectou, mas o usuário ou a senha foram recusados \(535 ")
        self.assertNotIn("senha-x", json.dumps(t))
        self.smtp.auth, self.smtp.rcpt = "ok", "550 5.1.1 nao existe"
        t = self.sys_("POST", "/api/email/teste", {"para": "a@b.com"})[1]["teste"]
        self.assertRegex(t["erro"], r"^O servidor de e-mail recusou: ")
        livre = socket.socket()
        livre.bind(("127.0.0.1", 0))
        porta = livre.getsockname()[1]
        livre.close()   # ninguém ouve nesta porta
        t = self.sys_("POST", "/api/email/teste", {"para": "a@b.com", "porta": porta})[1]["teste"]
        self.assertRegex(t["erro"], r"^Não deu para enviar \(.*\)\. Confira o servidor, a porta e a segurança\.$")
        for seg in ("starttls", "ssl"):   # o SMTP falso não fala TLS: erro tratado, nunca exceção
            with self.subTest(seguranca=seg):
                st, r = self.sys_("POST", "/api/email/teste", {"para": "a@b.com", "seguranca": seg})
                self.assertEqual((st, r["teste"]["ok"]), (200, False))


# =====================================================================================================
# 4. BACKUP: configuração, cópia, restauração, cópias v0/v1, zips fabricados
# =====================================================================================================

CAMPOS_BK = [   # campo, valores aceitos, valores recusados
    ("hora", ["00:00", "23:59", "03:00", "12:30"], ["24:00", "23:60", "7:00", "3:00", "", "12:30:00", " 03:00", "03:00\n", None, 5, True, []]),
    ("on", [True, False], ["true", 1, 0, None, "x", []]),
    ("ao_ligar", [True, False], ["true", 1, 0, None, "x", []]),
    ("limite_mb", [50, 1000000, 5000], [49, 1000001, 0, -1, "5000", 5000.0, True, None, [], 2 ** 70]),
]
RET_OK = [{"diarias": 1}, {"diarias": 60}, {"semanais": 1, "mensais": 60}, {"manuais": 30}, {}]
RET_RUIM = [{"diarias": 0}, {"diarias": 61}, {"mensais": -1}, {"manuais": 0}, {"diarias": "7"}, {"diarias": True}, {"diarias": 7.0},
            {"semanais": None}, "x", [], None, 5, True]


class BackupBase(Base):
    def setUp(self):
        super().setUp()
        self.bk = servidor.backup_mod()
        self.destino = self.tmp / "backup"   # a pasta padrão: ao lado de data/

    def painel(self):
        return self.sys_("GET", "/api/backup")[1]

    def agora(self, corpo=None):
        return self.sys_("POST", "/api/backup/agora", {} if corpo is None else corpo)

    def zip_falso(self, membros, nome="central-demandas_20260101-1200_manual.zip", manifesto=None, formato=1):
        """Zip de cópia fabricado na pasta de backup: membros {nome: bytes}; manifesto coerente com eles, salvo se vier um."""
        self.destino.mkdir(exist_ok=True)
        man = manifesto if manifesto is not None else {
            "programa": "Central de demandas", "formato_backup": formato, "v_dados": 2, "criado": 1767268800000, "tipo": "manual",
            "rev": 1, "arquivos": {n: {"bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()} for n, b in membros.items()},
            "contagem": {"demandas": 0, "arquivo": 0, "pessoas": 0, "setores": 0, "anexos": 0}, "faltando": []}
        with zipfile.ZipFile(self.destino / nome, "w") as z:
            for n, b in membros.items():
                z.writestr(n, b)
            if man is not False:
                z.writestr("manifesto.json", json.dumps(man))
        return nome


class BackupConfig(BackupBase):
    def test_BK01_cada_campo_no_limite_exato_e_um_alem(self):
        for campo, bons, ruins in CAMPOS_BK:
            for v in bons:
                with self.subTest(campo=campo, ok=repr(v)):
                    st, r = self.sys_("POST", "/api/backup", {campo: v})
                    self.assertEqual((st, r["cfg"][campo] if st == 200 else r), (200, v))
            for v in ruins:
                with self.subTest(campo=campo, ruim=repr(v)[:30]):
                    antes = self.painel()["cfg"]
                    st, r = self.sys_("POST", "/api/backup", {campo: v})
                    self.assertEqual(st, 400, r)
                    self.assertEqual(self.painel()["cfg"], antes, "recusado: nada mudou")

    def test_BK02_retencao_um_a_um_e_limites(self):
        for ret in RET_OK:
            with self.subTest(ok=ret):
                st, r = self.sys_("POST", "/api/backup", {"ret": ret})
                self.assertEqual(st, 200, r)
                for k, v in ret.items():
                    self.assertEqual(r["cfg"]["ret"][k], v)
        for ret in RET_RUIM:
            with self.subTest(ruim=repr(ret)):
                antes = self.painel()["cfg"]
                self.assertEqual(self.sys_("POST", "/api/backup", {"ret": ret})[0], 400)
                self.assertEqual(self.painel()["cfg"], antes)
        st, r = self.sys_("POST", "/api/backup", {"ret": {"diarias": 3, "inventado": 5}, "campo_novo": 1})
        self.assertEqual(st, 200)
        self.assertNotIn("inventado", r["cfg"]["ret"], "chave desconhecida é ignorada")
        self.assertNotIn("campo_novo", json.loads((self.data / "backup.json").read_text(encoding="utf-8")))

    def test_BK03_pasta_de_destino_valida_e_invalida(self):
        destino = self.tmp / "Cópias é ñ"
        destino.mkdir()
        st, r = self.sys_("POST", "/api/backup", {"local": " %s " % destino})
        self.assertEqual((st, r["cfg"]["local"]), (200, str(destino.resolve())), "espaços nas pontas saem; o nome acentuado vale")
        self.assertFalse(any(destino.iterdir()), "o teste de gravação não deixa arquivo")
        self.assertEqual(self.agora()[0], 200)
        self.assertEqual(len(list(destino.glob("*.zip"))), 1, "a cópia vai para a pasta escolhida")
        self.assertFalse(self.destino.exists(), "e não para a padrão")
        arquivo = self.tmp / "arquivo.txt"
        arquivo.write_text("x")
        ruins = ["backup", "./backup", "..", str(self.data), str(self.data / "sub"), "C:\\", "C:/", "/",
                 str(self.tmp / "nao" / "existe"), "x" * 261, "   ", 5, None, [], {}, True]
        for ruim in ruins:
            with self.subTest(local=repr(ruim)[:50]):
                st, r = self.sys_("POST", "/api/backup", {"local": ruim})
                self.assertEqual(st, 400, "%r -> %s %s" % (ruim, st, r))
                self.assertEqual(self.painel()["cfg"]["local"], str(destino.resolve()))
        self.assertEqual(self.sys_("POST", "/api/backup", {"local": str(arquivo)}), (400, "Não foi possível gravar na pasta escolhida."))
        self.assertEqual(self.sys_("POST", "/api/backup", {"local": ""})[1]["cfg"]["local"], "", "'' volta para a pasta padrão")

    def test_BK03b_B4_pasta_com_caractere_nulo_deveria_ser_400(self):
        """known-bug B4: o mkdir da pasta levanta ValueError (não OSError) e o servidor derruba a conexão sem responder."""
        destino = self.tmp / "dest"
        destino.mkdir()
        st, r = self.sys_("POST", "/api/backup", {"local": str(destino) + "\x00x"})
        self.assertEqual(st, 400, r)

    def test_BK04_ruins_juntos_recusam_tudo(self):
        self.sys_("POST", "/api/backup", {"hora": "04:00"})
        antes = (self.data / "backup.json").read_bytes()
        self.assertEqual(self.sys_("POST", "/api/backup", {"hora": "05:00", "limite_mb": 1})[0], 400)
        self.assertEqual((self.data / "backup.json").read_bytes(), antes)

    def test_BK05_corpo_malformado_e_metodo(self):
        for raw in (b"{x", b"\xff", b"[1]", b'"x"', b"null", b"5"):
            self.assertEqual(self.sys_("POST", "/api/backup", raw=raw)[0], 400, raw)
        self.assertEqual(self.sys_("POST", "/api/backup/previa", raw=b"[1]")[0], 400)
        self.assertEqual(self.sys_("POST", "/api/backup/restaurar", raw=b"{x")[0], 400)
        self.assertFalse(self.destino.exists(), "nenhuma recusa criou cópia ou pasta")


class BackupCopias(BackupBase):
    def setUp(self):
        super().setUp()
        self.mundo()

    def test_BK06_fazer_agora_zip_verificado_e_lista(self):
        self.nova(self.tk_h, titulo="Primeira")
        st, r = self.agora()
        self.assertEqual(st, 200)
        self.assertEqual(len(r["copias"]), 1)
        c = r["copias"][0]
        self.assertRegex(c["nome"], r"^central-demandas_\d{8}-\d{4}_manual\.zip$")
        self.assertEqual((c["tipo"], r["pasta_ok"], r["usado"], r["resumo"]["alerta"]), ("manual", True, c["bytes"], None))
        self.assertTrue(r["estado"]["ultimo_ok"]["verificado"])
        zp = self.destino / c["nome"]
        man = self.bk.verificar(zp)
        with zipfile.ZipFile(zp) as z:
            self.assertEqual(set(z.namelist()), {"demandas.json", "manifesto.json"})
            self.assertEqual(z.read("demandas.json"), (self.data / "demandas.json").read_bytes(), "o zip tem o arquivo como está no disco")
        self.assertEqual((man["contagem"]["demandas"], man["contagem"]["pessoas"], man["contagem"]["setores"]), (1, 3, 2))
        self.assertFalse(list(self.destino.glob("*.part")), "sem sobra de .part")
        nomes = {p.name for p in self.destino.iterdir()}
        self.assertFalse(any(x in " ".join(nomes) for x in ("rede", "sessoes", "email", "avisos")), "só as cópias do padrão")

    def test_BK07_lista_mais_nova_primeiro_e_retencao_de_manuais(self):
        self.sys_("POST", "/api/backup", {"ret": {"manuais": 2}})
        base = int(time.time() * 1000) - 4 * 86400000
        for i in range(4):
            self.bk.fazer("manual", base + i * 3 * MIN)
        nomes = [c["nome"] for c in self.painel()["copias"]]
        self.assertEqual(len(nomes), 2, "só as 2 últimas manuais ficam")
        self.assertEqual(nomes, sorted(nomes, reverse=True), "mais nova primeiro")
        self.assertEqual(nomes[0], self.bk.nome_zip(base + 9 * MIN, "manual"))

    def migra(self, v):
        texto = json.dumps({"v": v, "rev": 5, "seq": {"pessoa": 0, "demanda": 1000, "nota": 0}, "setores": [], "pessoas": []})
        (self.data / "demandas.json").write_text(texto, encoding="utf-8")
        self.assertEqual(self.ok("vista")["rev"], 5)
        velha = self.data / ("demandas.json.v%d.bak" % v)
        self.assertEqual(velha.read_text(encoding="utf-8"), texto, "a cópia é o arquivo antigo, intacto")
        self.assertEqual(self.disco()["v"], 2)
        self.assertEqual(self.disco()["rev"], 5, "migrar não muda o rev")
        self.assertFalse((self.data / "demandas.json.v2.bak").exists(), "arquivo já na versão atual não gera cópia nova")
        velha.write_text("marca", encoding="utf-8")
        (self.data / "demandas.json").write_text(texto, encoding="utf-8")
        self.ok("vista")
        self.assertEqual(velha.read_text(encoding="utf-8"), "marca", "nenhuma gravação pisa na cópia antiga")

    def test_BK08a_banco_v0_guarda_demandas_json_v0_bak(self):
        self.migra(0)

    def test_BK08b_banco_v1_guarda_demandas_json_v1_bak(self):
        self.migra(1)

    def test_BK09_banco_de_versao_mais_nova_nao_e_tocado(self):
        texto = json.dumps({"v": 3, "rev": 9, "demandas": []})
        (self.data / "demandas.json").write_text(texto, encoding="utf-8")
        st, r = self.chama("vista", {})
        self.assertEqual((st, r), (500, "Demandas gravadas por uma versão mais nova da Central de demandas: atualize o programa."))
        self.assertEqual((self.data / "demandas.json").read_text(encoding="utf-8"), texto)
        self.assertFalse(list(self.data.glob("demandas.json.v*.bak")))
        st, r = self.agora()
        self.assertEqual(st, 400, "a cópia de dados de versão mais nova é recusada na verificação, não gravada")
        self.assertRegex(r, r"^Cópia com defeito: dados de uma versão mais nova")
        self.assertFalse(list(self.destino.glob("*.zip")) + list(self.destino.glob("*.part")))
        self.assertEqual(self.painel()["resumo"]["alerta"], "grave")

    def test_BK10_cobre_a_copia_de_um_banco_ainda_na_versao_1(self):
        (self.data / "demandas.json").write_text(json.dumps({"v": 1, "rev": 5}), encoding="utf-8")
        self.assertEqual(self.agora()[0], 200)
        self.assertEqual(self.disco()["v"], 1, "copiar não migra nem muda o arquivo")
        self.assertEqual(len(list(self.destino.glob("*.zip"))), 1)

    def test_BK11_restaurar_pelo_http_volta_os_dados_e_derruba_as_sessoes(self):
        self.nova(self.tk_h, titulo="Antes da cópia")
        nome = self.agora()[1]["copias"][0]["nome"]
        self.nova(self.tk_h, titulo="Depois da cópia")
        rev0 = self.disco()["rev"]
        st, p = self.sys_("POST", "/api/backup/previa", {"nome": nome})
        self.assertEqual((st, p["copia"]["contagem"]["demandas"], p["agora"]["contagem"]["demandas"], p["proximo"]),
                         (200, 1, 2, "SOL-1003"))
        for corpo in ({"nome": nome}, {"nome": nome, "confirmo": " RESTAURAR"}, {"nome": nome, "confirmo": "RESTAURAR "},
                      {"nome": nome, "confirmo": "Restaurar"}, {"nome": nome, "confirmo": ["RESTAURAR"]}, {"nome": nome, "confirmo": None}):
            self.assertEqual(self.sys_("POST", "/api/backup/restaurar", corpo), (400, "Para restaurar, digite RESTAURAR."), corpo)
        self.assertEqual(len(self.ok("vista")["demandas"]), 2, "sem a confirmação nada mudou")
        st, r = self.sys_("POST", "/api/backup/restaurar", {"nome": nome, "confirmo": "RESTAURAR"})
        self.assertEqual(st, 200)
        self.assertEqual(r["estado"]["restaurado"]["nome"], nome)
        self.assertEqual({c["tipo"] for c in r["copias"]}, {"manual", "antes-restaurar"})
        v = self.ok("vista")
        self.assertEqual([d["titulo"] for d in v["demandas"]], ["Antes da cópia"])
        self.assertGreater(v["rev"], rev0, "o rev sobe: as telas abertas recarregam")
        self.assertIsNotNone(v["backup"]["restaurado"], "a tela avisa 'dados restaurados'")
        self.assertEqual(self.chama("vista", {}, self.tk_h), (401, "Identifique-se de novo."), "todo mundo se identifica de novo")
        self.assertEqual(self.nova()["id"], "SOL-1003", "o número usado depois da cópia não volta")
        antes = [c for c in r["copias"] if c["tipo"] == "antes-restaurar"][0]["nome"]
        with zipfile.ZipFile(self.destino / antes) as z:
            self.assertEqual(len(json.loads(z.read("demandas.json"))["demandas"]), 2, "o 'antes de restaurar' guarda o que ia se perder")
        self.assertFalse((self.data / ".restaurar-tmp").exists())

    def test_BK12_nome_da_copia_que_nao_e_da_pasta_vira_404_nunca_500(self):
        self.agora()
        nome = self.painel()["copias"][0]["nome"]
        fora = self.tmp / "fora"
        fora.mkdir()
        shutil.copy(self.destino / nome, fora / nome)
        ruins = ["../" + nome, "..\\" + nome, str(fora / nome), "fora/" + nome, "central-demandas_20200101-0000_manual.zip", "x.zip", "",
                 5, None, [], {}, True, nome + "\x00", nome + " ", nome.upper(), "x" * 2000]
        for ruim in ruins:
            for rota, corpo in (("previa", {"nome": ruim}), ("restaurar", {"nome": ruim, "confirmo": "RESTAURAR"})):
                with self.subTest(rota=rota, nome=repr(ruim)[:40]):
                    self.assertEqual(self.sys_("POST", "/api/backup/" + rota, corpo), (404, "Cópia não encontrada."))
        self.assertEqual(self.sys_("POST", "/api/backup/previa", {})[0], 404)
        self.assertFalse((self.data / ".restaurar-tmp").exists())

    def test_BK13_zip_fabricado_com_defeito_e_recusado_sem_mexer_em_nada(self):
        ok = json.dumps({"v": 2, "rev": 1}).encode()
        casos = {
            "caminho com ..": dict(membros={"demandas.json": ok, "../evil.txt": b"x"}),
            "caminho absoluto": dict(membros={"demandas.json": ok, "C:/evil.txt": b"x"}),
            "pasta de anexo com ..": dict(membros={"demandas.json": ok, "demandas-anexos/../../evil": b"x"}),
            "nome fora da lista": dict(membros={"demandas.json": ok, "rede.json": b"{}"}),
            "sem manifesto": dict(membros={"demandas.json": ok}, manifesto=False),
            "formato mais novo": dict(membros={"demandas.json": ok}, formato=99),
            "json ilegível": dict(membros={"demandas.json": b"{x"}),
            "dados mais novos": dict(membros={"demandas.json": json.dumps({"v": 3}).encode()}),
            "sem o principal": dict(membros={"demandas-arquivo.json": ok}),
            "hash diferente": dict(membros={"demandas.json": ok}, manifesto={"formato_backup": 1, "arquivos": {"demandas.json": {"bytes": 1, "sha256": "0" * 64}}}),
            "manifesto de outro tipo": dict(membros={"demandas.json": ok}, manifesto=["x"]),
        }
        self.mundo_antes = (self.data / "demandas.json").read_bytes()
        n = 0
        for rotulo, kw in casos.items():
            n += 1
            nome = "central-demandas_202601%02d-1200_manual.zip" % n
            with self.subTest(caso=rotulo):
                try:
                    self.zip_falso(nome=nome, **kw)
                except (ValueError, OSError):
                    continue   # o próprio zipfile recusou o nome: nada a testar
                for rota, corpo in (("previa", {"nome": nome}), ("restaurar", {"nome": nome, "confirmo": "RESTAURAR"})):
                    st, r = self.sys_("POST", "/api/backup/" + rota, corpo)
                    self.assertEqual(st, 400, (rota, r))
                    self.assertRegex(r, r"^Cópia com defeito: ")
        for conteudo in (b"", b"isto nao e um zip", b"PK\x03\x04" + b"\0" * 20):
            n += 1
            nome = "central-demandas_202601%02d-1200_manual.zip" % n
            (self.destino / nome).write_bytes(conteudo)
            with self.subTest(conteudo=conteudo[:10]):
                st, r = self.sys_("POST", "/api/backup/restaurar", {"nome": nome, "confirmo": "RESTAURAR"})
                self.assertEqual((st, r[:16]), (400, "Cópia com defeit"))
        self.assertEqual((self.data / "demandas.json").read_bytes(), self.mundo_antes, "nada foi restaurado")
        self.assertFalse((self.data / ".restaurar-tmp").exists())
        self.assertFalse((self.tmp / "evil.txt").exists() or (self.data / "evil.txt").exists() or (self.data.parent.parent / "evil.txt").exists())
        self.assertFalse(any(c["tipo"] == "antes-restaurar" for c in self.painel()["copias"]), "recusada antes de qualquer gravação")

    def test_BK14_copia_valida_mas_vazia_ou_cheia_de_lixo_restaura_e_o_programa_segue(self):
        for rotulo, texto in (("só o número da versão", {"v": 2}),
                              ("lixo em todo lugar", {"v": 2, "rev": "x", "setores": "y", "pessoas": {"a": 1}, "notas": 5, "cids": "z",
                                                       "demandas": [1, "a", {"id": "SOL-1"}, {"id": "SOL-2", "status": "new", "de": {}, "para": {}}]})):
            with self.subTest(caso=rotulo):
                nome = self.zip_falso({"demandas.json": json.dumps(texto).encode()}, nome="central-demandas_20260102-1200_manual.zip")
                st, r = self.sys_("POST", "/api/backup/restaurar", {"nome": nome, "confirmo": "RESTAURAR"})
                self.assertEqual(st, 200, r)
                v = self.ok("vista")
                self.assertEqual((v["setores"], v["pessoas"], v["demandas"]), ([], [], []))
                self.assertEqual(self.chama("setor/salvar", {"modo": "novo", "id": "AA", "nome": "Depois", "icone": "🗂️", "cor": "#6366F1",
                                                              "rev": 0})[0], 200, "dá para trabalhar depois de restaurar")
                self.sys_("POST", "/api/backup", {"on": True})
                self.chama("setor/apagar", {"id": "AA", "rev": self.disco()["setores"][0]["_rv"]})

    def test_BK15_anexo_apagado_volta_com_a_restauracao(self):
        d = self.nova(self.tk_h)["id"]
        self.ok("anexo/enviar", {"id": d, "nome": "foto.jpg", "dados": base64.b64encode(JPG).decode()}, self.tk_h)
        aid = self.ok("vista")["demandas"][0]["anexos"][0]["id"]
        nome = self.agora()[1]["copias"][0]["nome"]
        with zipfile.ZipFile(self.destino / nome) as z:
            self.assertIn("demandas-anexos/%s.jpg" % aid, z.namelist())
        self.ok("anexo/apagar", {"id": d, "aid": aid}, self.tk_h)
        self.assertEqual(self.chama("anexo/ler", {"aid": aid})[0], 404)
        self.assertEqual(self.sys_("POST", "/api/backup/restaurar", {"nome": nome, "confirmo": "RESTAURAR"})[0], 200)
        r = self.ok("anexo/ler", {"aid": aid})
        self.assertEqual(base64.b64decode(r["dados"]), JPG)

    def test_BK16_pasta_sumiu_alerta_grave_sem_mostrar_o_caminho(self):
        usb = self.tmp / "usb"
        usb.mkdir()
        self.assertEqual(self.sys_("POST", "/api/backup", {"local": str(usb / "cópias")})[0], 200)
        shutil.rmtree(usb)   # o pen drive saiu
        st, r = self.agora()
        self.assertEqual((st, r), (500, "Pasta do backup não encontrada."))
        p = self.painel()
        self.assertEqual((p["pasta_ok"], p["resumo"]["alerta"]), (False, "grave"))
        self.assertEqual(p["resumo"]["texto"], "Nenhum backup feito ainda: Pasta do backup não encontrada")
        self.assertEqual(p["estado"]["falhas_seguidas"], 1)
        vista = self.ok("vista")
        self.assertEqual(vista["backup"]["alerta"], "grave")
        self.assertNotIn(str(self.tmp), json.dumps(vista["backup"]), "o ADM pela rede também vê a vista: sem caminho de pasta")
        self.assertNotIn("backup", self.ok("vista", {}, self.tk_c))
        usb.mkdir()   # voltou o pen drive, mas a pasta 'cópias' não existe: a Central a recria
        self.assertEqual(self.agora()[0], 200)
        self.assertEqual((self.painel()["estado"]["falhas_seguidas"], self.painel()["resumo"]["alerta"]), (0, None))

    def test_BK17_backup_desligado_vira_aviso_e_a_thread_nao_copia(self):
        self.assertEqual(self.sys_("POST", "/api/backup", {"on": False})[0], 200)
        r = self.ok("vista")["backup"]
        self.assertEqual((r["alerta"], r["texto"]), ("aviso", "Backup automático desligado."))
        self.bk.tarefa(int(time.time() * 1000) + 10 * 86400000)
        self.assertFalse(self.destino.exists())


# =====================================================================================================
# 5. CONFIGURAÇÕES: Rede/PIN, Servidor, modo demonstração, .bat
# =====================================================================================================

class Configuracoes(Base):
    def test_CF01_rede_so_bool_liga_e_so_true_gera_pin(self):
        st, r = self.sys_("GET", "/api/rede")
        self.assertEqual((st, set(r)), (200, {"on", "pin", "pin_op", "active", "urls"}))
        pin, op = r["pin"], r["pin_op"]
        for corpo in ({"on": "true"}, {"on": 1}, {"on": None}, {"newpin": "true"}, {"newpin": 1}, {"newpin_op": []}, {"x": 1}, {}):
            with self.subTest(corpo=corpo):
                st, r = self.sys_("POST", "/api/rede", corpo)
                self.assertEqual((st, r["on"], r["pin"], r["pin_op"]), (200, False, pin, op), "nada disso muda a rede nem os PINs")
        st, r = self.sys_("POST", "/api/rede", {"on": True})
        self.assertEqual((st, r["on"], r["active"]), (200, True, False), "ligar só vale ao religar o servidor")
        self.assertEqual(self.sys_("POST", "/api/rede", {"on": False})[1]["on"], False)
        for raw in (b"[1]", b"{x", b"\xff", b'"x"', b"null"):
            self.assertEqual(self.sys_("POST", "/api/rede", raw=raw), (400, "Falha ao gravar a configuração da rede."), raw)
        self.assertEqual(self.sys_("GET", "/api/rede")[1]["pin"], pin)

    def test_CF02_pins_sempre_6_digitos_e_diferentes(self):
        for i in range(25):
            r = self.sys_("POST", "/api/rede", {"newpin": True, "newpin_op": i % 2 == 0})[1]
            for p in (r["pin"], r["pin_op"]):
                self.assertRegex(p, r"^\d{6}$")
            self.assertNotEqual(r["pin"], r["pin_op"])
        antes = self.sys_("GET", "/api/rede")[1]
        novo = self.sys_("POST", "/api/rede", {"newpin": True})[1]
        self.assertEqual(novo["pin_op"], antes["pin_op"], "trocar o PIN do escritório não troca o dos operadores")
        novo2 = self.sys_("POST", "/api/rede", {"newpin_op": True})[1]
        self.assertEqual(novo2["pin"], novo["pin"])

    def test_CF03_servidor_mostra_a_saude_sem_segredos(self):
        self.sys_("POST", "/api/email", {"senha": "senha-super-secreta", "host": "smtp.x.com"})
        pins = self.sys_("GET", "/api/rede")[1]
        for i in range(30):
            servidor.registra("linha %d" % i)
        st, r = self.sys_("GET", "/api/servidor")
        self.assertEqual(st, 200)
        self.assertEqual(set(r), {"versao", "modo", "inicio", "python", "sistema", "nome_pc", "porta", "rede", "sessoes_rede", "urls", "disco",
                                  "dados", "backup", "tarefa", "log"})
        self.assertEqual((r["versao"], r["modo"], r["porta"], r["rede"]), ("1.0.0", "normal", self.port, False))
        self.assertEqual(len(r["log"]), 12, "só as 12 últimas linhas")
        self.assertTrue(r["log"][-1].endswith("linha 29"))
        texto = json.dumps(r)
        for segredo in ("senha-super-secreta", pins["pin"], pins["pin_op"]):
            self.assertNotIn(segredo, texto)
        self.assertNotIn(str(self.tmp), texto, "nenhum caminho de pasta")
        self.assertEqual(r["backup"], {"ultimo": None, "copias": 0})
        self.sys_("POST", "/api/backup/agora", {})
        self.assertEqual(self.sys_("GET", "/api/servidor")[1]["backup"]["copias"], 1)

    def test_CF04_modo_vem_do_ambiente_em_qualquer_caixa(self):
        for valor, esperado in (("demo", "demo"), ("DEMO", "demo"), (" Demo ", "demo"), ("demonstracao", "normal"), ("1", "normal"),
                                ("", "normal"), ("demo2", "normal")):
            with self.subTest(DEMANDAS_MODO=valor):
                r = subprocess.run([sys.executable, "-I", "-c", "import sys;sys.path.insert(0, %r);import servidor;print(servidor.MODO)" % str(ROOT)],
                                   env={**os.environ, "DEMANDAS_MODO": valor, "DEMANDAS_DATA": str(self.data)},
                                   capture_output=True, text=True, timeout=60)
                self.assertEqual(r.stdout.strip(), esperado, r.stderr)

    def copia_do_programa(self):
        """O programa numa pasta temporária: o 'data' dela é a base real DELA, nunca a do projeto."""
        raiz = self.tmp / "programa"
        raiz.mkdir()
        for f in ("servidor.py", "store.py", "email_envio.py"):
            shutil.copy(ROOT / f, raiz / f)
        for pasta in ("demandas", "web"):
            shutil.copytree(ROOT / pasta, raiz / pasta, ignore=shutil.ignore_patterns("__pycache__"))
        return raiz

    def test_CF05_demonstracao_recusa_a_base_real_e_nao_toca_nela(self):
        raiz = self.copia_do_programa()
        (raiz / "data").mkdir()
        (raiz / "data" / "demandas.json").write_text('{"v": 2, "rev": 7}', encoding="utf-8")
        antes = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in (raiz / "data").iterdir()}
        porta = socket.socket()
        porta.bind(("127.0.0.1", 0))
        livre = porta.getsockname()[1]
        porta.close()
        variantes = {"sem DEMANDAS_DATA": None, "caminho igual": str(raiz / "data"), "com ..": str(raiz / "data" / ".." / "data"),
                     "com barra no fim": str(raiz / "data") + os.sep}
        for rotulo, dados in variantes.items():
            with self.subTest(variante=rotulo):
                env = {k: v for k, v in os.environ.items() if k != "DEMANDAS_DATA"}
                env.update(DEMANDAS_MODO="demo", DEMANDAS_PORT=str(livre))
                if dados:
                    env["DEMANDAS_DATA"] = dados
                r = subprocess.run([sys.executable, str(raiz / "servidor.py")], env=env, capture_output=True, text=True, timeout=60)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn("Modo demonstração apontado para a base real (data/)", r.stdout)
                self.assertEqual({p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in (raiz / "data").iterdir()}, antes,
                                 "a recusa vem antes de qualquer arquivo: nada criado nem mexido")

    def test_CF06_demonstracao_sobe_na_base_propria_e_mostra_o_modo(self):
        raiz = self.copia_do_programa()
        demo = self.tmp / "data-demo"
        porta = socket.socket()
        porta.bind(("127.0.0.1", 0))
        livre = porta.getsockname()[1]
        porta.close()
        env = {**os.environ, "DEMANDAS_MODO": "demo", "DEMANDAS_PORT": str(livre), "DEMANDAS_DATA": str(demo)}
        p = subprocess.Popen([sys.executable, str(raiz / "servidor.py")], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            eu = None
            for _ in range(80):
                try:
                    c = http.client.HTTPConnection("127.0.0.1", livre, timeout=3)
                    c.request("GET", "/api/eu")
                    eu = json.loads(c.getresponse().read())
                    c.close()
                    break
                except (OSError, ValueError):
                    time.sleep(0.25)
            self.assertEqual(eu, {"papel": "maquina", "modo": "demo"})
            c = http.client.HTTPConnection("127.0.0.1", livre, timeout=10)
            c.request("GET", "/api/servidor")
            self.assertEqual(json.loads(c.getresponse().read())["modo"], "demo")
            c.close()
            self.assertTrue((demo / "rede.json").exists(), "a base da demonstração é a pasta apontada")
            self.assertFalse((raiz / "data").exists() and any((raiz / "data").iterdir()), "a pasta data do programa não foi tocada")
        finally:
            if os.name == "nt":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
            else:
                p.kill()
            p.wait(timeout=20)
            p.stdout.close()

    def test_CF07_scripts_bat_da_demonstracao_apontam_para_a_base_e_a_porta_dela(self):
        demo = (ROOT / "iniciar-demo.bat").read_text(encoding="utf-8", errors="replace")
        real = (ROOT / "iniciar.bat").read_text(encoding="utf-8", errors="replace")
        for trecho in ('DEMANDAS_DATA=%~dp0data-demo"', 'DEMANDAS_PORT=8091"', 'DEMANDAS_MODO=demo"'):
            self.assertIn(trecho, demo)
        self.assertNotIn("DEMANDAS_MODO", real, "a Central de verdade nunca liga em modo demonstração")
        self.assertNotIn("data-demo", real)
        self.assertNotIn("8091", real)
        self.assertTrue((ROOT / "parar.bat").exists())


# =====================================================================================================
# 6. ROBUSTEZ TRANSVERSAL: entrada malformada em toda rota, corpo grande, revisão, concorrência, XSS nos dados
# =====================================================================================================

DROP = object()
RUINS = [None, True, False, 0, -1, 2 ** 63, 1.5, "", " ", "x" * 300, "x" * 20000, "\x00", "\n", XSS, [], [1], {}, {"a": 1}, "SOL-0",
         "p999", "../../etc/passwd", "𝕏" * 70, "‮", "%s%s", "{0}"]


def variantes(base, prefixo=(), fundo=3):
    """(caminho, valor ruim) para cada campo (e cada campo dentro de objetos), um por vez; DROP = tira o campo."""
    for k, v in base.items():
        for ruim in RUINS + [DROP]:
            yield prefixo + (k,), ruim
        if isinstance(v, dict) and fundo > 1:
            yield from variantes(v, prefixo + (k,), fundo - 1)


def aplica(base, caminho, valor):
    corpo = json.loads(json.dumps(base))
    alvo = corpo
    for k in caminho[:-1]:
        alvo = alvo[k]
    if valor is DROP:
        alvo.pop(caminho[-1], None)
    else:
        alvo[caminho[-1]] = valor
    return corpo


class Robustez(Base):
    def setUp(self):
        super().setUp()
        self.mundo()
        self.sn = 0

    # --- fixtures ---
    def D(self):
        return self.nova(self.tk_h)["id"]

    def DA(self):
        d = self.D()
        self.ok("demanda/aceitar", {"id": d}, self.tk_c)
        return d

    def DP(self):
        d = self.DA()
        self.ok("demanda/pausar", {"id": d, "motivo": "Máquina parada", "obs": ""}, self.tk_c)
        return d

    def rv(self, lista, ident):
        return next(x["_rv"] for x in self.disco()[lista] if x["id"] == ident)

    def setor_novo(self):
        self.sn += 1
        sid = "T%02d" % self.sn
        self.setor(sid, "Setor %s" % sid)
        return sid

    def pessoa_nova(self):
        self.sn += 1
        return self.pessoa("Pessoa T%d" % self.sn, "CNC", "7777")

    def nid(self):
        self.D()
        return self.notas(self.tk_c)[-1]["id"]

    def com_anexo(self):
        d = self.D()
        self.ok("anexo/enviar", {"id": d, "nome": "f.jpg", "dados": base64.b64encode(JPG).decode()}, self.tk_h)
        dem = next(x for x in self.ok("vista", {}, self.tk_h)["demandas"] if x["id"] == d)
        return d, dem["anexos"][0]["id"]

    def rotas(self):
        """(rota, ator, fábrica do corpo válido) de TODA rota POST das demandas."""
        T = lambda t, b: dict(b, tk=t)   # noqa: E731
        c, h = self.tk_c, self.tk_h
        crio = {"titulo": "Fuzz criar", "tipo": "dem", "motivo": "Outro", "prio": "norm", "est": 60, "para": {"s": "CNC", "p": None},
                "desc": "d", "cid": "abcdefgh1234"}
        return [
            ("vista", None, lambda: {}), ("vista", c, lambda: T(c, {})),
            ("historico", None, lambda: {"de": 0, "ate": 2 ** 40}), ("crono", None, lambda: {"dias": 7}),
            ("cronograma", None, lambda: {"de": 0, "ate": 86400000, "por": "setor"}),
            ("demanda/criar", None, lambda: dict(crio, de_s="PCP")), ("demanda/criar", h, lambda: T(h, crio)),
            ("demanda/aceitar", c, lambda: T(c, {"id": self.D()})),
            ("demanda/pausar", c, lambda: T(c, {"id": self.DA(), "motivo": "Máquina parada", "obs": "o"})),
            ("demanda/retomar", c, lambda: T(c, {"id": self.DP()})),
            ("demanda/concluir", c, lambda: T(c, {"id": self.DA(), "nota": "ok"})),
            ("demanda/cancelar", h, lambda: T(h, {"id": self.D(), "motivo": "m"})),
            ("demanda/reatribuir", c, lambda: T(c, {"id": self.D(), "s": "CNC", "p": None, "nota": "n"})),
            ("demanda/cobrar", h, lambda: T(h, {"id": self.D()})),
            ("demanda/prioridade", None, lambda: {"id": self.D(), "prio": "urg"}),
            ("demanda/estender", None, lambda: {"id": self.D(), "minutos": 30}),
            ("demanda/comentar", h, lambda: T(h, {"id": self.D(), "texto": "t", "cid": "cidcid123456"})),
            ("anexo/enviar", h, lambda: T(h, {"id": self.D(), "nome": "f.jpg", "dados": base64.b64encode(JPG).decode()})),
            ("anexo/ler", None, lambda: {"aid": self.com_anexo()[1]}),
            ("anexo/apagar", h, lambda: (lambda d, a: T(h, {"id": d, "aid": a}))(*self.com_anexo())),
            ("nota/lida", c, lambda: T(c, {"nid": self.nid()})), ("nota/todas", c, lambda: T(c, {})),
            ("setor/salvar", None, lambda: {"modo": "novo", "id": "ZZ1", "nome": "Setor fuzz", "icone": "🗂️", "cor": "#6366F1", "rev": 0,
                                            "email": "z@x.com"}),
            ("setor/salvar", None, lambda: {"modo": "editar", "id": "CNC", "nome": "Corte CNC", "icone": "🗂️", "cor": "#6366F1",
                                            "rev": self.rv("setores", "CNC"), "email": "c@x.com"}),
            ("setor/ativar", None, lambda: (lambda s: {"id": s, "rev": self.rv("setores", s)})(self.setor_novo())),
            ("setor/apagar", None, lambda: (lambda s: {"id": s, "rev": self.rv("setores", s)})(self.setor_novo())),
            ("pessoa/salvar", None, lambda: {"modo": "novo", "nome": "Pessoa fuzz", "setor": "CNC", "codigo": "4321", "rev": 0, "email": "p@x.com"}),
            ("pessoa/salvar", None, lambda: {"modo": "editar", "id": self.b, "nome": "Bruno", "setor": "CNC", "rev": self.rv("pessoas", self.b),
                                             "codigo": "", "email": "b@x.com"}),
            ("pessoa/ativar", None, lambda: (lambda p: {"id": p, "rev": self.rv("pessoas", p)})(self.pessoa_nova())),
            ("pessoa/apagar", None, lambda: (lambda p: {"id": p, "rev": self.rv("pessoas", p)})(self.pessoa_nova())),
            ("agenda/salvar", None, lambda: {"agenda": self.ok("vista")["agenda"]}),
            ("entrar", None, lambda: {"pessoa": self.b, "codigo": "3333"}), ("sair", None, lambda: {"tk": self.tk_b}),
            ("aviso/prefs", h, lambda: T(h, {"prefs": {"eventos": {"new": False}, "silencio": {"ligado": True, "ini": "22:00", "fim": "06:00"},
                                                       "urgente_fura": True}})),
            ("aviso/prefs", None, lambda: {"padrao": True}),
        ]

    def test_RB01_nenhuma_rota_responde_500_nem_cai_com_campo_ruim(self):
        """Cada campo de cada rota (e dos objetos dentro dele) recebe cada valor ruim, um por vez: nunca 5xx nem conexão caída."""
        defeitos, pedidos, rotas = [], 0, self.rotas()
        for rota, ator, fabrica in rotas:
            base = fabrica()
            for caminho, ruim in variantes(base):
                if caminho == ("tk",) and rota in ("vista", "sair") and ruim is DROP:
                    continue
                corpo = aplica(base, caminho, ruim)
                pedidos += 1
                try:
                    st, r = self.chama(rota, corpo)
                except Exception as e:   # noqa: BLE001 - conexão caída é exatamente o defeito procurado
                    defeitos.append((rota, ".".join(caminho), repr(ruim)[:30], "sem resposta: %r" % e))
                    continue
                if st >= 500 or st < 200 or (st >= 300 and st < 400):
                    defeitos.append((rota, ".".join(caminho), repr(ruim)[:30], st, str(r)[:80]))
        self.assertGreater(pedidos, 3000, "a bateria tem de ter o tamanho esperado")
        self.assertEqual(defeitos[:20], [], "%d defeitos em %d pedidos" % (len(defeitos), pedidos))
        self.assertEqual(self.req("GET", "/api/rev")[0], 200, "o servidor continua de pé")
        self.assertEqual(self.chama("vista", {})[0], 200)
        doc = self.ds.load()   # o arquivo continua abrindo e passando pela normalização
        for d in doc["demandas"]:
            self.assertIsInstance(d["titulo"], str)
            self.assertIn(d["prio"], self.api.PRIO)
            self.assertIn(d["tipo"], self.api.TIPOS)
            self.assertTrue(1 <= d["est"] <= self.api.EST_MAX)
            self.assertTrue(5 <= len(d["titulo"]) <= 140)
        self.assertEqual(len({n["id"] for n in doc["notas"]}), len(doc["notas"]))
        for p in doc["pessoas"]:
            self.assertNotIn("codigo", p)
            self.assertRegex(p["hash"], r"^[0-9a-f]{64}$")

    def test_RB02_campo_extra_nunca_vira_dado(self):
        lixo = {"status": "done", "fim": 5, "id": "SOL-1", "_rv": 99999, "atraso_avisado": True, "pausas": [{"x": 1}],
                "eventos": [{"ev": "fake", "quem": "Escritório"}], "comentarios": [{"texto": "falso", "quem": "x"}],
                "anexos": [{"id": "a" + "0" * 16}], "iniciado": 5, "prazo_em": 1, "agenda_v": 3, "util": {"total": 1}, "lida": True,
                "quem": "Escritório", "t": 1, "aud": "adm", "__proto__": {"x": 1}, "constructor": {"prototype": {}}, "ativo": False}
        limpa = self.nova(self.tk_h, titulo="Limpa demais")
        suja = self.nova(self.tk_h, titulo="Suja demais", **lixo)
        self.assertEqual(set(suja) - {"id", "titulo"}, set(limpa) - {"id", "titulo"}, "mesmas chaves")
        d = next(x for x in self.disco()["demandas"] if x["id"] == suja["id"])
        self.assertEqual((d["status"], d["fim"], d["iniciado"], d["pausas"], d["comentarios"], d["anexos"], d["atraso_avisado"]),
                         ("new", None, None, [], [], [], False))
        self.assertEqual([e["ev"] for e in d["eventos"]], ["created"])
        self.assertNotIn("prazo_em", d)
        self.assertNotEqual(d["_rv"], 99999)
        # comentário: o autor vem do token, nunca do pedido
        self.ok("demanda/comentar", {"id": suja["id"], "texto": "oi", **{k: lixo[k] for k in ("quem", "t")}}, self.tk_c)
        com = next(x for x in self.disco()["demandas"] if x["id"] == suja["id"])["comentarios"][-1]
        self.assertEqual((com["quem"], com["texto"]), ("Carlos", "oi"))
        self.assertNotEqual(com["t"], 1)
        # cadastros
        self.ok("setor/salvar", dict({"modo": "novo", "id": "XX", "nome": "Extra", "icone": "🗂️", "cor": "#6366F1", "rev": 0}, **{k: v for k, v in lixo.items() if k != "id"}))
        s = next(x for x in self.disco()["setores"] if x["id"] == "XX")
        self.assertEqual((s["ativo"], s["nome"]), (True, "Extra"))
        self.assertNotIn("pausas", s)
        self.ok("pessoa/salvar", dict({"modo": "novo", "nome": "Extra Y", "setor": "CNC", "codigo": "5151", "rev": 0}, **{k: v for k, v in lixo.items() if k != "id"},
                                      hash="x", sal="y", mat="M1"))
        p = self.disco()["pessoas"][-1]
        self.assertEqual((p["ativo"], p["id"].startswith("p"), p["id"] != "SOL-1", p["mat"] != "M1"), (True, True, True, True))
        self.assertNotIn("pausas", p)
        self.assertIsNotNone(self.entrar(p["id"], "5151"), "o código digitado continua valendo (hash e sal vêm do servidor)")

    def test_RB03_conflito_de_revisao_409_e_nada_muda(self):
        s = self.setor_novo()
        rev = self.rv("setores", s)
        corpo = {"modo": "editar", "id": s, "nome": "Mudou", "icone": "🗂️", "cor": "#6366F1"}
        self.ok("setor/salvar", dict(corpo, rev=rev))
        msg = "Alterado em outro aparelho. Atualize a tela e tente de novo."
        for rota, extra in (("setor/salvar", corpo), ("setor/ativar", {"id": s}), ("setor/apagar", {"id": s})):
            self.assertEqual(self.erro(rota, dict(extra, rev=rev), None, 409), msg, rota)
        self.assertEqual(next(x for x in self.disco()["setores"] if x["id"] == s)["nome"], "Mudou")
        p = self.pessoa_nova()
        rev = self.rv("pessoas", p)
        base = {"modo": "editar", "id": p, "nome": "Mudou P", "setor": "CNC"}
        self.ok("pessoa/salvar", dict(base, rev=rev))
        for rota, extra in (("pessoa/salvar", base), ("pessoa/ativar", {"id": p}), ("pessoa/apagar", {"id": p})):
            self.assertEqual(self.erro(rota, dict(extra, rev=rev), None, 409), msg, rota)
        for ruim in (None, True, "1", 1.5, [], {}, "x"):
            self.assertEqual(self.erro("setor/salvar", dict(corpo, rev=ruim), None, 400), "Versão do registro inválida.", repr(ruim))
        self.assertEqual(self.erro("setor/salvar", corpo, None, 400), "Versão do registro inválida.", "sem rev")
        # o horário de serviço também versiona
        ag = self.ok("vista")["agenda"]
        self.ok("agenda/salvar", {"agenda": dict(ag, padrao=dict(ag["padrao"], dias=[1, 2, 3]))})
        self.assertRegex(self.erro("agenda/salvar", {"agenda": ag}, None, 409), r"^Outro aparelho alterou o horário de serviço")

    def test_RB04_duas_telas_com_a_mesma_revisao_so_uma_ganha(self):
        s = self.setor_novo()
        rev = self.rv("setores", s)
        res, trava = [], threading.Barrier(8)

        def tenta(i):
            trava.wait()
            res.append(self.chama("setor/salvar", {"modo": "editar", "id": s, "nome": "Tela %d" % i, "icone": "🗂️", "cor": "#6366F1", "rev": rev})[0])

        ts = [threading.Thread(target=tenta, args=(i,)) for i in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(sorted(res), [200] + [409] * 7)

    def test_RB05_muitos_pedidos_ao_mesmo_tempo_ids_unicos_e_sem_500(self):
        res, ids, trava = [], [], threading.Barrier(12)

        def trabalha(i):
            trava.wait()
            for j in range(4):
                st, r = self.chama("demanda/criar", {"titulo": "Paralela %d-%d" % (i, j), "tipo": "dem", "motivo": "Outro", "prio": "norm",
                                                     "est": 60, "para": {"s": "CNC", "p": None}, "desc": "", "de_s": "PCP"})
                res.append(st)
                if st == 200:
                    ids.append(max(int(d["id"][4:]) for d in r["demandas"]))
                res.append(self.chama("nota/todas", {}, self.tk_c)[0])
                res.append(self.chama("vista", {}, self.tk_b)[0])

        ts = [threading.Thread(target=trabalha, args=(i,)) for i in range(12)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(set(res), {200})
        doc = self.disco()
        self.assertEqual(len({d["id"] for d in doc["demandas"]}), 48, "nenhuma demanda repetiu o número nem se perdeu")
        self.assertEqual(doc["seq"]["demanda"], max(int(d["id"][4:]) for d in doc["demandas"]))

    # --- corpo ---
    def cru(self, caminho, linhas_extra, corpo=b"", metodo="POST"):
        s = socket.create_connection(("127.0.0.1", self.port), timeout=30)
        try:
            cab = ["%s %s HTTP/1.1" % (metodo, caminho), "Host: 127.0.0.1:%d" % self.port] + linhas_extra
            s.sendall(("\r\n".join(cab) + "\r\n\r\n").encode() + corpo)
            raw = b""
            while True:
                try:
                    p = s.recv(65536)
                except OSError:
                    break
                if not p:
                    break
                raw += p
        finally:
            s.close()
        return raw

    def status(self, raw):
        return int(raw.split(b" ", 2)[1]) if raw.startswith(b"HTTP/") else None

    def test_RB06_corpo_acima_de_16_mb_e_413_em_toda_rota_que_le_corpo(self):
        for caminho in ("/api/local/demandas/vista", "/api/local/demandas/anexo/enviar", "/api/backup", "/api/email", "/api/avisos", "/api/rede"):
            with self.subTest(rota=caminho):
                raw = self.cru(caminho, ["Content-Length: %d" % (servidor.MAX_BODY + 1), "Content-Type: application/json"], b"{" + b" " * 1000)
                self.assertEqual(self.status(raw), 413, raw[:120])
                self.assertIn("Arquivo grande demais.".encode(), raw)
        self.assertEqual(self.req("GET", "/api/rev")[0], 200)

    def test_RB07_corpo_no_limite_exato_passa_e_um_byte_a_mais_nao(self):
        with mock.patch.object(servidor, "MAX_BODY", 2000):
            for caminho in ("/api/local/demandas/vista", "/api/email", "/api/backup", "/api/avisos", "/api/rede"):
                exato = b"{" + b" " * 1998 + b"}"
                self.assertEqual(len(exato), 2000)
                with self.subTest(rota=caminho):
                    st, _, _ = self.req("POST", caminho, raw=exato)
                    self.assertEqual(st, 200)
                    st, _, r = self.req("POST", caminho, raw=exato + b" ")
                    self.assertEqual((st, r), (413, "Arquivo grande demais.".encode()))

    def test_RB08_content_length_ruim_ou_corpo_curto_nao_derruba(self):
        for cl in ("abc", "-1", "1e3", "", "0x10", "99999999999999999999999"):
            with self.subTest(content_length=cl):
                raw = self.cru("/api/local/demandas/vista", ["Content-Length: " + cl])
                self.assertIn(self.status(raw), (400, 413), raw[:100])
        raw = self.cru("/api/local/demandas/vista", ["Content-Length: 500"], b'{"x":')   # anuncia 500, manda 6 e fecha
        self.assertIn(self.status(raw), (400, None))
        self.assertEqual(self.req("GET", "/api/rev")[0], 200)

    def test_RB09_anexo_no_limite_de_5_mb_e_um_byte_alem(self):
        d = self.D()
        limite = 5 * 1024 * 1024
        ok = (JPG + b"\0" * limite)[:limite]
        r = self.ok("anexo/enviar", {"id": d, "nome": "grande.jpg", "dados": base64.b64encode(ok).decode()}, self.tk_h)
        self.assertEqual(r["demandas"][0]["anexos"][0]["bytes"], limite)
        for tamanho in (limite + 1, limite + 3):
            with self.subTest(bytes=tamanho):
                mais = (JPG + b"\0" * tamanho)[:tamanho]
                self.assertEqual(self.erro("anexo/enviar", {"id": d, "nome": "x.jpg", "dados": base64.b64encode(mais).decode()}, self.tk_h, 413),
                                 "Anexo maior que 5 MB.")
        for dados in ("", "***", "ab\ncd", 5, None, [], base64.b64encode(b"texto qualquer, nao e imagem").decode()):
            with self.subTest(dados=repr(dados)[:20]):
                self.erro("anexo/enviar", {"id": d, "nome": "x.jpg", "dados": dados}, self.tk_h, 400)
        pdf = base64.b64encode(b"%PDF-1.4 x").decode()
        png = base64.b64encode(PNG).decode()
        self.ok("anexo/enviar", {"id": d, "nome": "a" * 120, "dados": png}, self.tk_h)
        self.assertEqual(self.erro("anexo/enviar", {"id": d, "nome": "a" * 121, "dados": png}, self.tk_h, 400), "Nome do anexo: de 1 a 120 caracteres.")
        self.assertEqual(self.erro("anexo/enviar", {"id": d, "nome": "", "dados": png}, self.tk_h, 400), "Nome do anexo: de 1 a 120 caracteres.")
        self.ok("anexo/enviar", {"id": d, "nome": "doc.pdf", "dados": pdf}, self.tk_h)

    # --- forma do JSON ---
    def test_RB10_json_de_forma_estranha(self):
        for rota in ("vista", "demanda/criar", "entrar", "nota/todas", "aviso/prefs"):
            for raw, esperado in ((b"null", 400), (b"true", 400), (b"5", 400), (b'"x"', 400), (b"[]", 400), (b"[{}]", 400), (b"{", 400),
                                  (b"", None), (b"\xef\xbb\xbf{}", 400), (b"{\"a\":NaN}", None),
                                  (b"{\"a\":Infinity}", None), (b"{\"a\":1,\"a\":2}", None), (b"\xff\xfe{}", 400), (b"{} lixo", 400)):
                with self.subTest(rota=rota, corpo=raw[:20]):
                    st, _, r = self.req("POST", "/api/local/demandas/" + rota, raw=raw)
                    self.assertLess(st, 500, r)
                    if esperado:
                        self.assertEqual(st, esperado, r)

    def test_RB11_B1_json_muito_aninhado_deveria_ser_400(self):
        """known-bug B1: o json.loads estoura a pilha (RecursionError, que não é ValueError) e a conexão cai sem resposta."""
        for caminho in ("/api/local/demandas/vista", "/api/backup", "/api/email", "/api/avisos", "/api/rede"):
            st, _, _ = self.req("POST", caminho, raw=b"[" * 200000)
            self.assertEqual(st, 400, caminho)

    def test_RB12_metodos_e_caminhos_estranhos(self):
        for metodo in ("PUT", "DELETE", "PATCH", "OPTIONS", "TRACE", "FOO"):
            with self.subTest(metodo=metodo):
                raw = self.cru("/api/local/demandas/vista", ["Content-Length: 0"], metodo=metodo)
                self.assertEqual(self.status(raw), 501, raw[:100])
        fontes = ("import ", "def ", "class Handler", "DEMANDAS_DATA")
        for caminho in ("/../servidor.py", "/%2e%2e/servidor.py", "/local/demandas/../api.py", "/local/demandas/..%5capi.py", "/local/demandas/api.py",
                        "/local/demandas/demandas_store.py", "/local/demandas/demandas.js/", "//etc/passwd", "/data/demandas.json", "/.git/config",
                        "/%00", "/" + "x" * 5000, "/api/local/demandas/../../servidor.py", "/api/local/demandas/anexo/../../../servidor.py",
                        "/local/demandas/CONTRATO.md", "/local/demandas/contrato.json", "/store.py", "/web/app.js", "/email_envio.py",
                        "/local/demandas/%2e%2e%2fapi.py", "\\servidor.py"):
            with self.subTest(caminho=caminho[:50]):
                try:
                    st, _, r = self.req("GET", caminho)
                except (http.client.HTTPException, OSError, ValueError):
                    continue   # o cliente nem montou o pedido
                self.assertIn(st, (400, 404), "%s -> %s" % (caminho[:50], st))
                self.assertFalse(any(f.encode() in r for f in fontes), "o código-fonte vazou em %s" % caminho[:50])
        st, h, r = self.req("GET", "/local/demandas/demandas.js?x=1#y")
        self.assertEqual((st, h["Content-Type"]), (200, "text/javascript; charset=utf-8"))

    def test_RB13_cabecalhos_de_seguranca_em_todo_tipo_de_resposta(self):
        respostas = [self.req("GET", "/"), self.req("GET", "/nada"), self.req("POST", "/api/local/demandas/vista", raw=b"{x"),
                     self.req("GET", "/api/local/demandas"), self.req("POST", "/api/email", raw=b"{x"), self.req("GET", "/api/rev"),
                     self.req("POST", "/api/local/demandas/vista", {}, headers={"Origin": "http://evil.com"}),
                     self.req("GET", "/", headers={"Host": "evil.com"}), self.req("GET", "/local/demandas/demandas.css")]
        for st, h, _ in respostas:
            with self.subTest(status=st):
                for k, v in (("X-Content-Type-Options", "nosniff"), ("X-Frame-Options", "DENY"), ("Cache-Control", "no-store"),
                             ("Referrer-Policy", "same-origin")):
                    self.assertEqual(h[k], v, k)
                self.assertIn("script-src 'self'", h["Content-Security-Policy"])
                self.assertIn("frame-ancestors 'none'", h["Content-Security-Policy"])
        self.assertTrue(respostas[1][1]["Content-Type"].startswith("text/plain"), "erro é texto puro: o que foi digitado nunca vira HTML")
        self.assertEqual(respostas[3][1]["Content-Type"], "application/json; charset=utf-8")

    # --- texto digitado: limites e XSS nos dados ---
    def test_RB14_limite_exato_de_cada_texto_digitado(self):
        d = self.DA()
        tabela = [   # rota, quem, campo, mínimo, máximo, fábrica (valor -> corpo), cria demanda nova a cada pedido?
            ("titulo", 5, 140, lambda v: ("demanda/criar", self.tk_h, {"titulo": v, "tipo": "dem", "motivo": "Outro", "prio": "norm", "est": 60,
                                                                         "para": {"s": "CNC", "p": None}, "desc": ""})),
            ("descrição", 0, 2000, lambda v: ("demanda/criar", self.tk_h, {"titulo": "Título ok", "tipo": "dem", "motivo": "Outro", "prio": "norm",
                                                                             "est": 60, "para": {"s": "CNC", "p": None}, "desc": v})),
            ("comentário", 1, 1000, lambda v: ("demanda/comentar", self.tk_c, {"id": d, "texto": v})),
            ("nome do setor", 3, 40, lambda v: ("setor/salvar", None, {"modo": "novo", "id": "N%s" % secrets.token_hex(1).upper(), "nome": v,
                                                                         "icone": "🗂️", "cor": "#6366F1", "rev": 0})),
            ("nome da pessoa", 2, 60, lambda v: ("pessoa/salvar", None, {"modo": "novo", "nome": v, "setor": "CNC", "codigo": "1234", "rev": 0})),
            ("observação da pausa", 0, 500, lambda v: ("demanda/pausar", self.tk_c, {"id": self.DA(), "motivo": "Máquina parada", "obs": v})),
            ("nota da conclusão", 0, 500, lambda v: ("demanda/concluir", self.tk_c, {"id": self.DA(), "nota": v})),
            ("motivo do cancelamento", 0, 500, lambda v: ("demanda/cancelar", self.tk_h, {"id": self.D(), "motivo": v})),
            ("nota de repasse", 0, 500, lambda v: ("demanda/reatribuir", self.tk_c, {"id": self.D(), "s": "CNC", "p": None, "nota": v})),
        ]
        for campo, lo, hi, fab in tabela:
            casos = [("A" * hi, 200), ("A" * (hi + 1), 400), ("  " + "A" * hi + "  ", 200), ("A" * (lo - 1), 400) if lo else None,
                     ("A" * lo, 200) if lo else None, ("😀" * hi, 200), ("😀" * (hi + 1), 400), ("com\x00nulo", 400), ("com\x07sino", 400)]
            for caso in [c for c in casos if c]:
                valor, esperado = caso
                with self.subTest(campo=campo, tamanho=len(valor), esperado=esperado):
                    rota, tk, corpo = fab(valor)
                    st, r = self.chama(rota, corpo, tk)
                    self.assertEqual(st, esperado, "%s: %s" % (campo, r if st != 200 else ""))
        self.assertEqual(self.chama("demanda/comentar", {"id": d, "texto": "linha1\nlinha2"}, self.tk_c)[0], 200, "comentário aceita quebra de linha")
        self.assertEqual(self.chama("demanda/comentar", {"id": d, "texto": "com\rcr"}, self.tk_c)[0], 400)
        self.assertEqual(self.chama("demanda/criar", {"titulo": "com\nquebra", "tipo": "dem", "motivo": "Outro", "prio": "norm", "est": 60,
                                                      "para": {"s": "CNC", "p": None}, "desc": ""}, self.tk_h)[0], 400, "título é uma linha só")

    def test_RB15_todo_texto_digitado_volta_como_dado_sem_mudar(self):
        sujo = '<img src=x onerror="window.__xss=1"> & "aspas" \'simples\' </script><svg onload=alert(1)>'
        titulo = sujo[:140]
        pessoa = self.pessoa(sujo[:60], "CNC", "8888")
        tk = self.entrar(pessoa, "8888")
        self.ok("setor/salvar", {"modo": "editar", "id": "CNC", "nome": sujo[:40], "icone": "🗂️", "cor": "#6366F1", "rev": self.rv("setores", "CNC")})
        d = self.nova(self.tk_h, titulo=titulo, desc=sujo, para={"s": "CNC", "p": pessoa})["id"]
        self.ok("demanda/aceitar", {"id": d}, tk)
        self.ok("demanda/pausar", {"id": d, "motivo": "Máquina parada", "obs": sujo}, tk)
        self.ok("demanda/retomar", {"id": d}, tk)
        self.ok("demanda/comentar", {"id": d, "texto": sujo}, self.tk_h)
        self.ok("anexo/enviar", {"id": d, "nome": sujo[:120], "dados": base64.b64encode(JPG).decode()}, self.tk_h)
        self.ok("demanda/concluir", {"id": d, "nota": sujo}, tk)
        v = self.ok("vista")
        dem = next(x for x in v["demandas"] if x["id"] == d)
        self.assertEqual((dem["titulo"], dem["desc"]), (titulo, sujo))
        self.assertEqual(dem["comentarios"][0]["texto"], sujo)
        self.assertEqual(dem["anexos"][0]["nome"], sujo[:120])
        self.assertEqual(dem["pausas"][0]["obs"], sujo)
        self.assertIn(sujo, [e["nota"] for e in dem["eventos"]])
        self.assertEqual(next(s for s in v["setores"] if s["id"] == "CNC")["nome"], sujo[:40])
        self.assertEqual(next(p for p in v["pessoas"] if p["id"] == pessoa)["nome"], sujo[:60])
        st, h, _ = self.req("POST", "/api/local/demandas/vista", {})
        self.assertEqual((h["Content-Type"], h["X-Content-Type-Options"]), ("application/json; charset=utf-8", "nosniff"))
        r = self.ok("anexo/ler", {"aid": dem["anexos"][0]["id"]})
        self.assertEqual(r["nome"], sujo[:120], "o nome do anexo sai como dado, num JSON (nunca como página)")

    def test_RB16_nome_de_anexo_perde_so_controle_e_formatacao_invisivel(self):
        d = self.D()
        r = self.ok("anexo/enviar", {"id": d, "nome": "fatura‮gpj.exe", "dados": base64.b64encode(JPG).decode()}, self.tk_h)
        self.assertEqual(r["demandas"][0]["anexos"][0]["nome"], "faturagpj.exe", "o U+202E (inverte o texto) sai do nome")
        r = self.ok("anexo/enviar", {"id": d, "nome": "​​", "dados": base64.b64encode(PNG).decode()}, self.tk_h)
        self.assertEqual(r["demandas"][0]["anexos"][1]["nome"], "anexo.png", "nome que sobra vazio vira anexo.<tipo>")

    def test_RB17_nome_de_feriado_limite_e_texto_cru(self):
        ag = self.ok("vista")["agenda"]
        sujo = XSS
        novo = dict(ag, feriados=[{"data": "2026-12-25", "nome": sujo, "setores": []}, {"data": "2026-12-26", "nome": "N" * 60, "setores": ["CNC"]}])
        r = self.ok("agenda/salvar", {"agenda": novo})
        self.assertEqual([f["nome"] for f in r["agenda"]["feriados"]], [sujo, "N" * 60])
        v = r["agenda"]["v"]
        ruim = dict(ag, v=v, feriados=[{"data": "2026-12-27", "nome": "N" * 61, "setores": []}])
        self.assertEqual(self.erro("agenda/salvar", {"agenda": ruim}, None, 400), "Nome de feriado com mais de 60 letras.")
        for nome in (5, None, [], {}):
            self.erro("agenda/salvar", {"agenda": dict(ag, v=v, feriados=[{"data": "2026-12-27", "nome": nome, "setores": []}])}, None, 400)

    def test_RB18_B2_regex_com_match_e_dollar_aceita_quebra_de_linha_no_fim(self):
        """known-bug B2: CODE_RE/HHMM_RE usam .match com '$', que casa antes de um '\n' final: '1234\n' e '07:00\n' passam."""
        st, _ = self.chama("pessoa/salvar", {"modo": "novo", "nome": "Código Nl", "setor": "CNC", "codigo": "1234\n", "rev": 0})
        ag = self.ok("vista")["agenda"]
        st2, _ = self.chama("agenda/salvar", {"agenda": dict(ag, padrao=dict(ag["padrao"], turnos=[["07:00\n", "12:00"]]))})
        self.assertEqual((st, st2), (400, 400))
