"""Demandas direto no api.py: papéis, pessoa por token, transições, notificações, cadastros, anexos e leituras.

Dados num diretório temporário (DEMANDAS_DATA) por teste; relógio e pbkdf2 trocados para o teste ser rápido.
"""

import base64
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parents[1] / "demandas"   # pasta do módulo
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import demandas_store as ds

_spec = importlib.util.spec_from_file_location("demandas_api_teste", HERE / "api.py")
api = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(api)
ITER_REAL = api.ITER

MIN = 60000
T0 = 1_800_000_000_000
ADM = {"papel": "maquina"}
OP = {"papel": "operador"}
JPG = b"\xff\xd8\xff\xe0" + b"j" * 40
PNG = b"\x89PNG\r\n\x1a\n" + b"p" * 40
B64 = base64.b64encode(JPG).decode()


class Base(unittest.TestCase):
    def setUp(self):
        self._data = os.environ.get("DEMANDAS_DATA")
        self.dir = Path(tempfile.mkdtemp(prefix="dem-api-"))
        os.environ["DEMANDAS_DATA"] = str(self.dir)
        ds._CACHE.update(key=None, texto=None)
        ds._ARQ.update(key=None, demandas=[])
        api._TK.clear()
        api._FAILS.clear()
        self.clk = 1000.0
        self.t = T0
        api._clock = lambda: self.clk
        api._parede = lambda: self.clk
        api._agora = lambda: self.t
        api.ITER = 1000   # o real (100 000) é conferido em test_constantes
        fs = mock.patch("os.fsync", lambda fd: None)   # durabilidade é do store (testada lá); aqui só atrasa
        fs.start()
        self.addCleanup(fs.stop)
        self.mundo()

    def tearDown(self):
        api.ITER = ITER_REAL
        if self._data is None:
            os.environ.pop("DEMANDAS_DATA", None)
        else:
            os.environ["DEMANDAS_DATA"] = self._data

    # --- chamadas ---
    def adm(self, rest, body=None, ctx=ADM):
        return api.handle("POST", rest, dict(body or {}), ctx)

    def get(self, rest="", ctx=ADM):
        return api.handle("GET", rest, {}, ctx)

    def pes(self, tk, rest, body=None, ctx=OP):
        return api.handle("POST", rest, dict(body or {}, tk=tk), ctx)

    def erro(self, fn, *a, **kw):
        with self.assertRaises(api.ApiError) as c:
            fn(*a, **kw)
        return c.exception.status

    def msg(self, fn, *a, **kw):
        with self.assertRaises(api.ApiError) as c:
            fn(*a, **kw)
        return str(c.exception)

    def disco(self, nome="demandas.json"):
        return json.loads((self.dir / nome).read_text(encoding="utf-8"))

    def rev(self):
        return self.disco()["rev"]

    # --- cenário: PCP (Helena p0), CNC (Carlos p1, Bruno p2), ESP (Fernanda p3) ---
    def setor(self, sid, nome, icone="⚙️", cor="#3B82F6"):
        return self.adm("setor/salvar", {"modo": "novo", "id": sid, "nome": nome, "icone": icone, "cor": cor, "rev": 0})

    def pessoa(self, nome, setor, codigo):
        v = self.adm("pessoa/salvar", {"modo": "novo", "nome": nome, "setor": setor, "codigo": codigo, "rev": 0})
        return v["pessoas"][-1]["id"]

    def mundo(self):
        for sid, nome in (("PCP", "Planejamento"), ("CNC", "Corte CNC"), ("ESP", "Espumação")):
            self.setor(sid, nome)
        self.helena = self.pessoa("Helena", "PCP", "1111")
        self.carlos = self.pessoa("Carlos", "CNC", "2222")
        self.bruno = self.pessoa("Bruno", "CNC", "3333")
        self.fer = self.pessoa("Fernanda", "ESP", "4444")
        self.tk_h = self.entrar(self.helena, "1111")
        self.tk_c = self.entrar(self.carlos, "2222")
        self.tk_b = self.entrar(self.bruno, "3333")
        self.tk_f = self.entrar(self.fer, "4444")

    def entrar(self, pid, codigo, ctx=OP):
        return api.handle("POST", "entrar", {"pessoa": pid, "codigo": codigo}, ctx)["tk"]

    def nova(self, tk=None, **kw):
        body = {"titulo": "Cortar chapas", "tipo": "dem", "motivo": "Outro", "prio": "norm", "est": 60,
                "para": {"s": "CNC", "p": None}, "desc": ""}
        body.update(kw)
        v = self.pes(tk, "demanda/criar", body) if tk else self.adm("demanda/criar", dict({"de_s": "PCP"}, **body))
        return max(v["demandas"], key=lambda d: int(d["id"][4:]))

    def dem(self, did):
        return next(d for d in self.disco()["demandas"] if d["id"] == did)

    def notas(self, aud=None):
        return [(n["aud"], n["tipo"], n["dem"]) for n in self.disco()["notas"] if aud is None or n["aud"] == aud]

    def evs(self, did):
        return [e["ev"] for e in self.dem(did)["eventos"]]


class Contrato(Base):
    def test_constantes(self):
        self.assertEqual(ITER_REAL, 100_000)
        self.assertEqual(api.STATIC, ("demandas-fontes.css", "demandas.css", "demandas.js",
                                      "bricolage-grotesque.woff2", "figtree.woff2"))
        self.assertEqual(api.PAGE, ("demandas-fontes.css", "demandas.css", "demandas.js"))
        self.assertEqual(api.REV_FILE, "demandas.json")
        self.assertEqual((api.TENTATIVAS, api.BLOQUEIO_S, api.TK_VIDA_S, api.TK_MAX), (5, 60, 43200, 500))
        self.assertIs(api.LOCK, ds.LOCK)
        self.assertEqual(api.ICONES, ("🗂️", "⚙️", "🔩", "🪵", "🪚", "🧽", "🛠️", "🧵", "✂️", "🪡", "📦", "✅", "🔧",
                                      "🏷️", "🚚", "🎨", "🧪", "🖥️", "🧰", "🏭"))
        self.assertEqual(len(api.CORES), 12)
        self.assertEqual(api.PRIO, {"low": "Baixa", "norm": "Normal", "high": "Alta", "urg": "Urgente"})

    def test_relogio_real(self):
        spec = importlib.util.spec_from_file_location("demandas_api_relogio", HERE / "api.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        with mock.patch.object(m.time, "time", return_value=1234.5678):
            self.assertEqual(m._agora(), 1234567)

    def test_rotas_e_corpo(self):
        self.assertEqual(self.erro(api.handle, "POST", "demanda/criar", [], ADM), 400)
        self.assertEqual(self.erro(self.get, "nada"), 404)
        self.assertEqual(self.erro(api.handle, "PUT", "", {}, ADM), 404)
        self.assertEqual(self.erro(self.adm, "nada"), 404)
        self.assertEqual(self.erro(self.adm, "nada", ctx=OP), 404)   # rota desconhecida antes da identidade

    def test_get_por_papel(self):
        for papel in ("maquina", "completo"):
            v = self.get(ctx={"papel": papel})
            self.assertEqual(v["papel"], "adm")
            self.assertIn("anexos_uso", v)
        self.assertEqual(self.erro(self.get, ctx={}), 403)
        self.assertEqual(self.erro(self.get, ctx={"papel": "outro"}), 403)
        self.adm("pessoa/ativar", {"id": self.bruno, "rev": self.get()["pessoas"][2]["_rv"]})
        self.setor("PIN", "Pintura")
        s = self.get()["setores"][-1]
        self.adm("setor/ativar", {"id": "PIN", "rev": s["_rv"]})
        pub = self.get(ctx=OP)
        self.assertEqual(set(pub), {"setores", "pessoas"})
        self.assertEqual([s["id"] for s in pub["setores"]], ["PCP", "CNC", "ESP"])
        self.assertEqual([p["nome"] for p in pub["pessoas"]], ["Helena", "Carlos", "Fernanda"])
        self.assertEqual(set(pub["pessoas"][0]), {"id", "nome", "setor", "mat", "ativo", "_rv"})
        self.assertEqual(self.erro(self.get, ctx={"papel": "desconhecido"}), 403)   # perfil estranho fecha

    def test_sem_sal_nem_hash(self):
        raw = self.disco()["pessoas"][0]
        self.assertEqual(len(raw["sal"]), 32)
        self.assertEqual(raw["hash"], api._hash("1111", raw["sal"]))
        for v in (self.get(), self.pes(self.tk_c, "vista"), self.get(ctx=OP)):
            txt = json.dumps(v)
            self.assertNotIn(raw["hash"], txt)
            self.assertNotIn('"sal"', txt)
            self.assertNotIn('"hash"', txt)


class Identidade(Base):
    def test_esquecer_pessoas_depois_de_restaurar(self):
        self.pes(self.tk_c, "vista")
        self.pes(self.tk_h, "vista")
        api.esquecer_pessoas()
        self.assertEqual(len(api._TK), 0)
        self.assertEqual(self.erro(self.pes, self.tk_c, "vista"), 401)
        self.assertEqual(self.msg(self.pes, self.tk_h, "vista"), "Identifique-se de novo.")
        self.assertEqual(self.adm("vista")["papel"], "adm", "o ADM não depende de token")

    def test_entrar(self):
        out = api.handle("POST", "entrar", {"pessoa": self.carlos, "codigo": "2222"}, OP)
        self.assertEqual(out["eu"], {"id": self.carlos, "nome": "Carlos", "setor": "CNC", "mat": "M101"})
        self.assertEqual(out["vista"]["papel"], "pessoa")
        self.assertEqual(out["vista"]["eu"], out["eu"])
        self.assertGreaterEqual(len(out["tk"]), 32)
        self.assertEqual(self.pes(out["tk"], "vista")["eu"]["id"], self.carlos)

    def test_codigo_errado_bloqueio_e_liberacao(self):
        for _ in range(4):
            self.assertEqual(self.erro(self.entrar, self.carlos, "9999"), 403)
        self.assertEqual(self.erro(self.entrar, self.carlos, "abcd"), 403)   # 5º erro: bloqueia
        self.assertEqual(self.erro(self.entrar, self.carlos, "2222"), 429)   # nem o certo passa
        self.assertEqual(self.msg(self.entrar, self.carlos, "2222"), "Bloqueado por 1 minuto: muitos códigos errados.")
        self.assertEqual(self.erro(self.entrar, self.bruno, "9999"), 403)    # por pessoa
        self.clk += 59
        self.assertEqual(self.erro(self.entrar, self.carlos, "2222"), 429)
        self.clk += 1.5
        self.entrar(self.carlos, "2222")
        self.assertNotIn(self.carlos, api._FAILS)   # acerto zera

    def test_acerto_zera_contagem(self):
        for _ in range(4):
            self.erro(self.entrar, self.carlos, "0000")
        self.entrar(self.carlos, "2222")
        for _ in range(4):
            self.assertEqual(self.erro(self.entrar, self.carlos, "0000"), 403)
        self.assertEqual(api._FAILS[self.carlos][0], 4)

    def test_tentativas_em_curso_contam(self):
        api._FAILS[self.carlos] = [3, 0.0, 2]
        self.assertEqual(self.erro(self.entrar, self.carlos, "2222"), 429)
        api._FAILS[self.carlos] = [2, 0.0, 2]
        self.entrar(self.carlos, "2222")

    def test_pessoa_que_nao_entra(self):
        self.assertEqual(self.erro(self.entrar, "p99", "1111"), 404)
        self.assertEqual(self.erro(self.entrar, 7, "1111"), 404)
        self.assertEqual(self.erro(api.handle, "POST", "entrar", {"codigo": "1111"}, OP), 404)
        doc = self.disco()
        doc["pessoas"].append({"id": "p50", "nome": "Sem código", "setor": "CNC", "ativo": True})
        doc["pessoas"].append({"id": "p51", "nome": "Sal ruim", "setor": "CNC", "ativo": True, "sal": "zz", "hash": "x"})
        doc["pessoas"].append({"id": "p52", "nome": "Sem hash", "setor": "CNC", "ativo": True, "sal": "a" * 32})
        doc["pessoas"].append({"id": "p53", "nome": "Setor some", "setor": "XX", "ativo": True, "sal": "a" * 32, "hash": "x"})
        (self.dir / "demandas.json").write_text(json.dumps(doc), encoding="utf-8")
        for pid in ("p50", "p51", "p52", "p53"):
            self.assertEqual(self.erro(self.entrar, pid, "1111"), 404, pid)
        self.adm("pessoa/ativar", {"id": self.bruno, "rev": self.dem_rv("pessoas", self.bruno)})
        self.assertEqual(self.erro(self.entrar, self.bruno, "3333"), 404)

    def dem_rv(self, chave, rid):
        return next(r["_rv"] for r in self.disco()[chave] if r["id"] == rid)

    def test_codigo_trocado_durante_o_hash(self):
        with mock.patch.object(api, "_codigo_fora", return_value=(self.carlos, "0" * 32, "outro")):
            self.assertEqual(self.erro(self.entrar, self.carlos, "2222"), 409)
        for campo, valor in (("id", self.bruno), ("sal", "f" * 32)):
            raw = self.disco()["pessoas"][1]
            conf = [raw["id"], raw["sal"], raw["hash"]]
            conf[["id", "sal", "hash"].index(campo)] = valor
            with mock.patch.object(api, "_codigo_fora", return_value=tuple(conf)):
                self.assertEqual(self.erro(self.entrar, self.carlos, "2222"), 409, campo)

    def test_tokens(self):
        self.assertEqual(self.erro(self.pes, "inventado", "vista"), 401)
        self.assertEqual(self.msg(self.pes, 12, "vista"), "Identifique-se de novo.")
        self.clk += 12 * 3600 - 1
        self.pes(self.tk_c, "vista")
        self.clk += 1
        self.assertEqual(self.erro(self.pes, self.tk_c, "vista"), 401)
        self.assertNotIn(api._tk_h(self.tk_c), api._TK)   # vencido sai da memória

    def reinicia(self):
        """Como se o servidor tivesse reiniciado: a memória some, o arquivo fica."""
        api._TK.clear()
        api._TK_ARQ[0] = None

    def sessoes(self):
        return json.loads((self.dir / "pessoas-sessoes.json").read_text(encoding="utf-8"))

    def test_sessao_sobrevive_ao_reinicio(self):
        self.reinicia()
        self.assertEqual(self.pes(self.tk_c, "vista")["eu"]["id"], self.carlos)
        disco = self.sessoes()
        self.assertEqual(disco["v"], 1)
        self.assertEqual(disco["sessoes"][api._tk_h(self.tk_c)], [self.carlos, self.clk + api.TK_VIDA_S])
        txt = (self.dir / "pessoas-sessoes.json").read_text(encoding="utf-8")
        for tk in (self.tk_c, self.tk_b, self.tk_h, self.tk_f):
            self.assertNotIn(tk, txt, "no disco só o hash")
        self.clk += api.TK_VIDA_S
        self.reinicia()
        self.assertEqual(self.erro(self.pes, self.tk_c, "vista"), 401, "vencido não volta do disco")

    def test_revogado_e_sair_valem_depois_do_reinicio(self):
        api._tk_revoga(self.carlos)
        self.adm("sair", {"tk": self.tk_b}, ctx=OP)
        self.reinicia()
        self.assertEqual(self.erro(self.pes, self.tk_c, "vista"), 401)
        self.assertEqual(self.erro(self.pes, self.tk_b, "vista"), 401)
        self.pes(self.tk_h, "vista")
        api.esquecer_pessoas()
        self.reinicia()
        self.assertEqual(self.erro(self.pes, self.tk_h, "vista"), 401)
        self.assertEqual(self.sessoes()["sessoes"], {})

    def test_sair_e_revogar_sem_nada_nao_regrava(self):
        antes = (self.dir / "pessoas-sessoes.json").stat().st_mtime_ns
        with mock.patch.object(api.store, "atomic_write") as aw:
            self.adm("sair", {"tk": "inventado"}, ctx=OP)
            api._tk_revoga("p999")
        aw.assert_not_called()
        self.assertEqual((self.dir / "pessoas-sessoes.json").stat().st_mtime_ns, antes)

    def test_arquivo_de_sessoes_ruim_ou_estranho(self):
        h = "a" * 64
        casos = ["{x", "[]", '{"sessoes": []}',
                 json.dumps({"sessoes": {"curto": ["p1", 9e9], h.upper(): ["p1", 9e9], h + "0": ["p1", 9e9]}}),
                 json.dumps({"sessoes": {h: ["p1"]}}), json.dumps({"sessoes": {h: [1, 9e9]}}),
                 json.dumps({"sessoes": {h: ["p1", True]}}), json.dumps({"sessoes": {h: ["p1", "9e9"]}}),
                 json.dumps({"sessoes": {h: ["p1", self.clk]}}), json.dumps({"sessoes": {h: ("p1", 9e9, 0)}})]
        for c in casos:
            (self.dir / "pessoas-sessoes.json").write_text(c, encoding="utf-8")
            self.reinicia()
            self.assertEqual(self.erro(self.pes, self.tk_c, "vista"), 401, c)
            self.assertEqual(len(api._TK), 0, c)
        (self.dir / "pessoas-sessoes.json").write_text(json.dumps({"sessoes": {h: ["p1", self.clk + 1]}}), encoding="utf-8")
        self.reinicia()
        api._tk_pessoa("x")
        self.assertEqual(dict(api._TK), {h: ("p1", self.clk + 1)})

    def test_teto_e_ordem_ao_ler(self):
        hs = {("%064x" % i): ["p1", self.clk + 100 + i] for i in range(api.TK_MAX + 3)}
        (self.dir / "pessoas-sessoes.json").write_text(json.dumps({"sessoes": hs}), encoding="utf-8")
        self.reinicia()
        api._tk_pessoa("x")
        self.assertEqual(len(api._TK), api.TK_MAX)
        self.assertEqual(next(iter(api._TK)), "%064x" % 3, "ficam as que vencem por último; a mais antiga primeiro")

    def test_falha_ao_gravar_nao_impede_entrar(self):
        with mock.patch.object(api.store, "atomic_write", side_effect=PermissionError("travado")), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            tk = self.entrar(self.fer, "4444")
        self.assertEqual(self.pes(tk, "vista")["eu"]["id"], self.fer)
        self.assertEqual(err.getvalue(), "[sessões] não gravou: PermissionError('travado')\n")

    def test_outra_pasta_de_dados_outro_arquivo(self):
        outra = Path(tempfile.mkdtemp(prefix="dem-api-outra-"))
        with mock.patch.dict(os.environ, {"DEMANDAS_DATA": str(outra)}):
            self.assertIsNone(api._tk_pessoa(self.tk_c))
        self.assertEqual(api._tk_pessoa(self.tk_c), self.carlos)

    def test_sem_tk(self):
        self.assertEqual(self.erro(self.adm, "vista", ctx=OP), 403)
        self.assertEqual(self.erro(self.adm, "vista", ctx={}), 403)
        self.assertEqual(self.adm("vista")["papel"], "adm")
        self.assertEqual(self.pes(self.tk_c, "vista", ctx=ADM)["papel"], "pessoa")   # tk vale em qualquer papel

    def test_sair(self):
        self.assertEqual(self.adm("sair", {"tk": self.tk_c}, ctx=OP), {"ok": True})
        self.assertEqual(self.erro(self.pes, self.tk_c, "vista"), 401)
        self.assertEqual(self.adm("sair", {"tk": 5}, ctx=OP), {"ok": True})
        self.assertEqual(self.adm("sair", {}, ctx=OP), {"ok": True})
        self.pes(self.tk_b, "vista")

    def test_teto_de_tokens(self):
        primeiro = self.entrar(self.fer, "4444")
        for _ in range(api.TK_MAX):
            api._tk_novo(self.fer)
        self.assertEqual(len(api._TK), api.TK_MAX)
        self.assertEqual(self.erro(self.pes, primeiro, "vista"), 401)

    def test_revogados(self):
        rv = lambda pid: next(p["_rv"] for p in self.disco()["pessoas"] if p["id"] == pid)
        outro_c = self.entrar(self.carlos, "2222")
        self.adm("pessoa/salvar", {"modo": "editar", "id": self.carlos, "nome": "Carlos", "setor": "CNC",
                                   "codigo": "5555", "rev": rv(self.carlos)})
        self.assertEqual(self.erro(self.pes, self.tk_c, "vista"), 401)
        self.assertEqual(self.erro(self.pes, outro_c, "vista"), 401)
        self.assertEqual(self.erro(self.entrar, self.carlos, "2222"), 403)
        self.entrar(self.carlos, "5555")
        self.pes(self.tk_b, "vista")   # só os dele
        self.adm("pessoa/ativar", {"id": self.bruno, "rev": rv(self.bruno)})
        self.assertEqual(self.erro(self.pes, self.tk_b, "vista"), 401)
        self.adm("pessoa/ativar", {"id": self.bruno, "rev": rv(self.bruno)})   # reativar não ressuscita o tk
        self.assertEqual(self.erro(self.pes, self.tk_b, "vista"), 401)
        self.adm("pessoa/apagar", {"id": self.fer, "rev": rv(self.fer)})
        self.assertEqual(self.erro(self.pes, self.tk_f, "vista"), 401)

    def test_setor_desativado_derruba(self):
        self.setor("PIN", "Pintura")
        pid = self.pessoa("Paulo", "PIN", "7777")
        tk = self.entrar(pid, "7777")
        s = self.disco()["setores"][-1]
        self.adm("setor/ativar", {"id": "PIN", "rev": s["_rv"]})
        self.assertEqual(self.erro(self.pes, tk, "vista"), 401)
        self.assertEqual(self.erro(self.entrar, pid, "7777"), 404)
        doc = self.disco()
        doc["setores"] = [x for x in doc["setores"] if x["id"] != "ESP"]   # setor sumiu do arquivo
        (self.dir / "demandas.json").write_text(json.dumps(doc), encoding="utf-8")
        self.assertEqual(self.erro(self.pes, self.tk_f, "vista"), 401)

    def test_operador_so_com_tk(self):
        self.assertEqual(self.erro(self.adm, "demanda/criar", {"de_s": "PCP"}, ctx=OP), 403)
        self.assertEqual(self.erro(self.get, "anexo/a0123456789abcdef", ctx=OP), 403)
        self.assertEqual(self.nova(self.tk_h)["de"], {"s": "PCP", "p": self.helena})

    def test_rotas_de_adm_recusam_pessoa(self):
        d = self.nova()
        for rest, body in (("demanda/prioridade", {"id": d["id"], "prio": "urg"}),
                           ("demanda/estender", {"id": d["id"], "minutos": 30}),
                           ("setor/salvar", {"modo": "novo", "id": "XY", "nome": "Xis", "icone": "⚙️", "cor": "#3B82F6", "rev": 0}),
                           ("setor/ativar", {"id": "CNC", "rev": 0}), ("setor/apagar", {"id": "CNC", "rev": 0}),
                           ("pessoa/salvar", {"modo": "novo", "nome": "Ze", "setor": "CNC", "codigo": "1234", "rev": 0}),
                           ("pessoa/ativar", {"id": self.bruno, "rev": 0}), ("pessoa/apagar", {"id": self.bruno, "rev": 0}),
                           ("historico", {"de": 0, "ate": T0}), ("crono", {"dias": 7})):
            self.assertEqual(self.erro(self.pes, self.tk_c, rest, body), 403, rest)
            self.assertEqual(self.msg(self.pes, self.tk_c, rest, body), "Só o escritório pode fazer isso.")


class Criar(Base):
    def test_adm(self):
        d = self.nova(titulo="  Corte de MDF  ", prio="urg", para={"s": "CNC", "p": self.carlos}, desc="linha 1\nlinha 2")
        self.assertEqual(d["id"], "SOL-1001")
        self.assertEqual((d["titulo"], d["de"], d["para"]), ("Corte de MDF", {"s": "PCP", "p": None},
                                                             {"s": "CNC", "p": self.carlos}))
        self.assertEqual((d["status"], d["criado"], d["iniciado"], d["fim"]), ("new", T0, None, None))
        self.assertEqual(d["desc"], "linha 1\nlinha 2")
        self.assertEqual(self.dem("SOL-1001")["eventos"],
                         [{"t": T0, "ev": "created", "quem": "Escritório", "nota": ""},
                          {"t": T0, "ev": "assigned", "quem": "Escritório", "nota": "Responsável: Carlos"}])
        self.assertEqual(self.notas(), [("CNC", "new", "SOL-1001"), ("adm", "urg", "SOL-1001")])
        self.assertEqual(self.disco()["notas"][0]["quem"], "Escritório")
        self.assertEqual(self.disco()["seq"]["demanda"], 1001)
        self.assertEqual(self.nova()["id"], "SOL-1002")
        self.assertEqual(self.dem("SOL-1002")["_rv"], self.rev())

    def test_pessoa(self):
        d = self.nova(self.tk_h, desc=None)
        self.assertEqual(d["de"], {"s": "PCP", "p": self.helena})
        self.assertEqual(d["desc"], "Sem descrição adicional.")
        self.assertEqual(self.dem(d["id"])["eventos"][0]["quem"], "Helena")
        self.assertEqual(self.notas(), [("CNC", "new", d["id"])])

    def test_validacoes(self):
        ruins = [{"titulo": "abcd"}, {"titulo": "x" * 141}, {"titulo": "Cortar\x07chapas"}, {"titulo": 5},
                 {"tipo": "xx"}, {"tipo": None}, {"motivo": "Qualquer"}, {"prio": "max"}, {"est": 0}, {"est": 43201},
                 {"est": True}, {"est": "60"}, {"est": 1.5}, {"desc": "x" * 2001}, {"desc": "a\tb"}, {"desc": "a\rb"},
                 {"para": "CNC"}, {"para": {"s": "ZZ"}}, {"para": {"s": "CNC", "p": self.fer}},
                 {"para": {"s": "CNC", "p": "p99"}}, {"para": {"s": "CNC", "p": 3}}, {"de_s": "ZZ"}, {"de_s": None}]
        for r in ruins:
            self.assertEqual(self.erro(self.nova, **r), 400, r)
        self.assertEqual(self.msg(self.nova, titulo="abcd"), "Título: de 5 a 140 caracteres.")
        self.assertEqual(self.msg(self.nova, tipo="xx"), "Tipo inválido.")
        self.nova(titulo="abcde", est=43200, desc="x" * 2000)
        self.nova(titulo="x" * 140, est=1)
        self.assertEqual(self.nova(para={"s": "CNC", "p": ""})["para"]["p"], None)
        for t in ("alt", "set", "man", "mat"):
            self.nova(tipo=t, motivo="Retrabalho", prio="low")

    def test_destino_inativo(self):
        self.adm("pessoa/ativar", {"id": self.bruno, "rev": self.disco()["pessoas"][2]["_rv"]})
        self.assertEqual(self.erro(self.nova, para={"s": "CNC", "p": self.bruno}), 400)
        self.setor("PIN", "Pintura")
        self.adm("setor/ativar", {"id": "PIN", "rev": self.disco()["setores"][-1]["_rv"]})
        self.assertEqual(self.erro(self.nova, para={"s": "PIN", "p": None}), 400)
        self.assertEqual(self.erro(self.nova, de_s="PIN"), 400)

    def test_numero_conta_o_arquivo(self):
        arq = {"v": 1, "demandas": [dict(self.nova(), id="SOL-2000", status="done", fim=T0)]}
        (self.dir / "demandas-arquivo.json").write_text(json.dumps(arq), encoding="utf-8")
        self.assertEqual(self.nova()["id"], "SOL-2001")
        doc = self.disco()
        doc["seq"]["demanda"] = 5000
        (self.dir / "demandas.json").write_text(json.dumps(doc), encoding="utf-8")
        self.assertEqual(self.nova()["id"], "SOL-5001")

    def test_teto_de_abertas(self):
        with mock.patch.dict(ds.MAX, {"demandas": 2}):
            a = self.nova()
            self.nova()
            self.assertEqual(self.erro(self.nova), 400)
            self.adm("demanda/cancelar", {"id": a["id"]})
            self.nova()


class Transicoes(Base):
    def aceita(self):
        d = self.nova(self.tk_h)
        self.pes(self.tk_c, "demanda/aceitar", {"id": d["id"]})
        return d["id"]

    def test_aceitar(self):
        d = self.nova(self.tk_h)
        self.assertEqual(self.erro(self.adm, "demanda/aceitar", {"id": d["id"]}), 403)
        self.assertEqual(self.erro(self.pes, self.tk_f, "demanda/aceitar", {"id": d["id"]}), 403)
        self.assertEqual(self.erro(self.pes, self.tk_c, "demanda/aceitar", {"id": "SOL-9"}), 404)
        self.assertEqual(self.erro(self.pes, self.tk_c, "demanda/aceitar", {"id": "x"}), 400)
        self.assertEqual(self.erro(self.pes, self.tk_c, "demanda/aceitar", {}), 400)
        self.t += 5 * MIN
        v = self.pes(self.tk_c, "demanda/aceitar", {"id": d["id"]})
        r = self.dem(d["id"])
        self.assertEqual((r["status"], r["iniciado"], r["para"]["p"]), ("prog", T0 + 5 * MIN, self.carlos))
        self.assertEqual(r["eventos"][1:], [{"t": self.t, "ev": "assigned", "quem": "Carlos", "nota": "Responsável: Carlos"},
                                            {"t": self.t, "ev": "started", "quem": "Carlos", "nota": ""}])
        self.assertEqual(self.notas("PCP"), [("PCP", "accepted", d["id"])])
        self.assertEqual(v["papel"], "pessoa")
        self.assertEqual(self.erro(self.pes, self.tk_b, "demanda/aceitar", {"id": d["id"]}), 409)
        self.assertEqual(self.msg(self.pes, self.tk_b, "demanda/aceitar", {"id": d["id"]}), "A demanda não está mais aberta.")

    def test_aceitar_ja_responsavel_e_mesmo_setor(self):
        d = self.nova(self.tk_b, para={"s": "CNC", "p": self.carlos})
        self.pes(self.tk_c, "demanda/aceitar", {"id": d["id"]})
        self.assertEqual(self.evs(d["id"]), ["created", "assigned", "started"])   # sem novo "assigned"
        self.assertEqual(self.notas(), [("CNC", "new", d["id"])])                 # mesmo setor: sem "accepted"

    def test_pausar_retomar(self):
        did = self.aceita()
        body = {"id": did, "motivo": "Máquina parada", "obs": " faltou lâmina "}
        self.assertEqual(self.erro(self.pes, self.tk_b, "demanda/pausar", body), 403)
        self.assertEqual(self.erro(self.adm, "demanda/pausar", body), 403)
        for ruim in ({"motivo": "Outro"}, {"obs": "a\nb"}, {"obs": "x" * 501}, {"obs": 3}):
            self.assertEqual(self.erro(self.pes, self.tk_c, "demanda/pausar", dict(body, **ruim)), 400, ruim)
        self.assertEqual(self.erro(self.pes, self.tk_c, "demanda/retomar", {"id": did}), 409)
        self.t += MIN
        self.pes(self.tk_c, "demanda/pausar", body)
        r = self.dem(did)
        self.assertEqual(r["status"], "pause")
        self.assertEqual(r["pausas"], [{"ini": self.t, "fim": None, "motivo": "Máquina parada", "obs": "faltou lâmina",
                                        "por": "Carlos"}])
        self.assertEqual(r["eventos"][-1]["nota"], "Máquina parada — faltou lâmina")
        self.assertEqual(self.notas()[-2:], [("adm", "pause", did), ("PCP", "pause", did)])
        self.assertEqual(self.disco()["notas"][-1]["texto"], "Máquina parada")
        self.assertEqual(self.erro(self.pes, self.tk_c, "demanda/pausar", body), 409)
        self.assertEqual(self.erro(self.pes, self.tk_b, "demanda/retomar", {"id": did}), 403)
        self.t += MIN
        self.pes(self.tk_c, "demanda/retomar", {"id": did})
        r = self.dem(did)
        self.assertEqual((r["status"], r["pausas"][0]["fim"], r["eventos"][-1]["ev"]), ("prog", self.t, "resumed"))
        self.pes(self.tk_c, "demanda/pausar", {"id": did, "motivo": "Aguardando material"})
        self.assertEqual(self.dem(did)["eventos"][-1]["nota"], "Aguardando material")
        self.assertEqual(self.dem(did)["pausas"][-1]["obs"], "")

    def test_pausa_mesmo_setor_e_teto(self):
        d = self.nova(self.tk_b)
        self.pes(self.tk_c, "demanda/aceitar", {"id": d["id"]})
        with mock.patch.dict(ds.MAX, {"pausas": 1}):
            self.pes(self.tk_c, "demanda/pausar", {"id": d["id"], "motivo": "Máquina parada"})
            self.assertEqual(self.notas()[-1], ("adm", "pause", d["id"]))   # mesmo setor: só o adm
            self.pes(self.tk_c, "demanda/retomar", {"id": d["id"]})
            self.assertEqual(self.erro(self.pes, self.tk_c, "demanda/pausar", {"id": d["id"], "motivo": "Máquina parada"}), 400)

    def test_pausar_aberta_e_409(self):
        d = self.nova(self.tk_h, para={"s": "CNC", "p": self.carlos})
        self.assertEqual(self.erro(self.pes, self.tk_c, "demanda/pausar", {"id": d["id"], "motivo": "Máquina parada"}), 409)

    def test_concluir(self):
        did = self.aceita()
        self.pes(self.tk_c, "demanda/pausar", {"id": did, "motivo": "Máquina parada"})
        self.assertEqual(self.erro(self.pes, self.tk_b, "demanda/concluir", {"id": did}), 403)
        self.assertEqual(self.erro(self.adm, "demanda/concluir", {"id": did}), 403)
        self.assertEqual(self.erro(self.pes, self.tk_c, "demanda/concluir", {"id": did, "nota": "x\ny"}), 400)
        self.t += 10 * MIN
        self.pes(self.tk_c, "demanda/concluir", {"id": did, "nota": "entregue"})
        r = self.dem(did)
        self.assertEqual((r["status"], r["fim"], r["iniciado"], r["pausas"][0]["fim"]), ("done", self.t, T0, self.t))
        self.assertEqual(r["eventos"][-1], {"t": self.t, "ev": "done", "quem": "Carlos", "nota": "entregue"})
        self.assertEqual(self.notas()[-1], ("PCP", "done", did))
        self.assertEqual(self.erro(self.pes, self.tk_c, "demanda/concluir", {"id": did}), 409)
        self.assertEqual(self.msg(self.pes, self.tk_c, "demanda/concluir", {"id": did}), "A demanda já foi encerrada.")

    def test_concluir_direto_da_aberta(self):
        d = self.nova(self.tk_b, para={"s": "CNC", "p": self.carlos})
        self.t += MIN
        self.pes(self.tk_c, "demanda/concluir", {"id": d["id"]})
        r = self.dem(d["id"])
        self.assertEqual((r["iniciado"], r["fim"]), (self.t, self.t))
        self.assertEqual(self.notas(), [("CNC", "new", d["id"])])   # mesmo setor: sem "done"

    def test_cancelar(self):
        did = self.aceita()
        self.pes(self.tk_c, "demanda/pausar", {"id": did, "motivo": "Máquina parada"})
        self.assertEqual(self.erro(self.pes, self.tk_c, "demanda/cancelar", {"id": did}), 403)
        self.assertEqual(self.erro(self.pes, self.tk_h, "demanda/cancelar", {"id": did, "motivo": "\x00"}), 400)
        self.t += MIN
        self.pes(self.tk_h, "demanda/cancelar", {"id": did, "motivo": "duplicada"})
        r = self.dem(did)
        self.assertEqual((r["status"], r["fim"], r["pausas"][0]["fim"]), ("canc", self.t, self.t))
        self.assertEqual(r["eventos"][-1], {"t": self.t, "ev": "canc", "quem": "Helena", "nota": "duplicada"})
        n = self.disco()["notas"][-1]
        self.assertEqual((n["aud"], n["tipo"], n["texto"], n["quem"]), ("CNC", "canc", "duplicada", "Helena"))
        self.assertEqual(self.erro(self.adm, "demanda/cancelar", {"id": did}), 409)
        d2 = self.nova(self.tk_h)
        self.adm("demanda/cancelar", {"id": d2["id"]})
        self.assertEqual(self.dem(d2["id"])["eventos"][-1]["quem"], "Escritório")

    def test_reatribuir_de_setor(self):
        did = self.aceita()
        self.pes(self.tk_c, "demanda/pausar", {"id": did, "motivo": "Máquina parada"})
        self.t += MIN
        self.adm("demanda/reatribuir", {"id": did, "s": "ESP", "p": self.fer, "nota": "melhor lá"})
        r = self.dem(did)
        self.assertEqual((r["status"], r["iniciado"], r["fim"], r["para"]), ("new", None, None, {"s": "ESP", "p": self.fer}))
        self.assertEqual(r["pausas"][0]["fim"], self.t)
        self.assertEqual(r["eventos"][-1], {"t": self.t, "ev": "reassigned", "quem": "Escritório",
                                            "nota": "Para ESP · Fernanda — melhor lá"})
        self.assertEqual(self.notas()[-1], ("ESP", "new", did))
        self.adm("demanda/reatribuir", {"id": did, "s": "CNC", "p": None})
        self.assertEqual(self.dem(did)["eventos"][-1]["nota"], "Para CNC")

    def test_reatribuir_pessoa(self):
        d = self.nova(self.tk_h)
        self.assertEqual(self.erro(self.pes, self.tk_f, "demanda/reatribuir", {"id": d["id"], "s": "ESP"}), 403)
        self.pes(self.tk_b, "demanda/reatribuir", {"id": d["id"], "s": "CNC", "p": self.carlos})   # aberta: o setor repassa
        self.assertEqual(self.dem(d["id"])["para"], {"s": "CNC", "p": self.carlos})
        self.assertEqual(self.notas(), [("CNC", "new", d["id"])])   # mesmo setor: sem nota nova
        self.pes(self.tk_c, "demanda/aceitar", {"id": d["id"]})
        self.assertEqual(self.erro(self.pes, self.tk_b, "demanda/reatribuir", {"id": d["id"], "s": "ESP"}), 403)
        self.pes(self.tk_c, "demanda/reatribuir", {"id": d["id"], "s": "CNC", "p": self.bruno})
        r = self.dem(d["id"])
        self.assertEqual((r["status"], r["para"]["p"]), ("prog", self.bruno))   # mesmo setor, outra pessoa: segue
        self.assertEqual(r["eventos"][-1]["quem"], "Carlos")
        self.pes(self.tk_b, "demanda/reatribuir", {"id": d["id"], "s": "CNC", "p": None})
        r = self.dem(d["id"])
        self.assertEqual((r["status"], r["iniciado"], r["para"]["p"]), ("new", None, None))   # sem responsável: fila

    def test_reatribuir_invalidos(self):
        d = self.nova()
        for body in ({"s": "ZZ"}, {"s": "CNC", "p": self.fer}, {"s": "CNC", "nota": "a\x1fb"}, {"s": None}):
            self.assertEqual(self.erro(self.adm, "demanda/reatribuir", dict(body, id=d["id"])), 400, body)
        self.adm("demanda/cancelar", {"id": d["id"]})
        self.assertEqual(self.erro(self.adm, "demanda/reatribuir", {"id": d["id"], "s": "ESP"}), 409)

    def test_cobrar(self):
        d = self.nova(self.tk_h)
        self.assertEqual(self.erro(self.pes, self.tk_c, "demanda/cobrar", {"id": d["id"]}), 403)
        self.pes(self.tk_h, "demanda/cobrar", {"id": d["id"]})
        self.adm("demanda/cobrar", {"id": d["id"]})
        self.assertEqual(self.notas()[-2:], [("CNC", "nudge", d["id"])] * 2)
        self.assertEqual([e["quem"] for e in self.dem(d["id"])["eventos"][-2:]], ["Helena", "Escritório"])
        self.adm("demanda/cancelar", {"id": d["id"]})
        self.assertEqual(self.erro(self.adm, "demanda/cobrar", {"id": d["id"]}), 409)

    def test_prioridade(self):
        d = self.nova()
        r0 = self.rev()
        self.adm("demanda/prioridade", {"id": d["id"], "prio": "norm"})
        self.assertEqual(self.rev(), r0)   # nada mudou: não grava
        self.assertEqual(self.erro(self.adm, "demanda/prioridade", {"id": d["id"], "prio": "x"}), 400)
        self.adm("demanda/prioridade", {"id": d["id"], "prio": "high"})
        self.assertEqual(self.dem(d["id"])["eventos"][-1]["nota"], "Normal → Alta")
        self.assertEqual(self.notas(), [("CNC", "new", d["id"])])
        self.adm("demanda/prioridade", {"id": d["id"], "prio": "urg"})
        r = self.dem(d["id"])
        self.assertEqual((r["prio"], r["eventos"][-1]["nota"], r["eventos"][-1]["quem"]), ("urg", "Alta → Urgente", "Escritório"))
        n = self.disco()["notas"][-1]
        self.assertEqual((n["aud"], n["tipo"], n["texto"]), ("CNC", "nudge", "Prioridade elevada para URGENTE"))
        self.adm("demanda/cancelar", {"id": d["id"]})
        self.assertEqual(self.erro(self.adm, "demanda/prioridade", {"id": d["id"], "prio": "low"}), 409)

    def test_estender(self):
        d = self.nova(est=10)
        for m in (0, 1441, True, "30", None):
            self.assertEqual(self.erro(self.adm, "demanda/estender", {"id": d["id"], "minutos": m}), 400, m)
        self.t += 11 * MIN
        self.adm("demanda/cobrar", {"id": d["id"]})                    # grava: marca o atraso
        self.assertTrue(self.dem(d["id"])["atraso_avisado"])
        self.adm("demanda/estender", {"id": d["id"], "minutos": 1})   # prazo ainda passado: segue avisada
        self.assertTrue(self.dem(d["id"])["atraso_avisado"])
        self.adm("demanda/estender", {"id": d["id"], "minutos": 60})
        r = self.dem(d["id"])
        self.assertEqual((r["est"], r["atraso_avisado"]), (71, False))
        self.assertEqual(r["eventos"][-1], {"t": self.t, "ev": "deadline", "quem": "Escritório", "nota": "+1h"})
        self.adm("demanda/estender", {"id": d["id"], "minutos": 1440})
        self.assertEqual(self.dem(d["id"])["est"], 1511)
        cheia = self.nova(est=43200 - 5)
        self.assertEqual(self.erro(self.adm, "demanda/estender", {"id": cheia["id"], "minutos": 6}), 400)
        self.adm("demanda/estender", {"id": cheia["id"], "minutos": 5})
        self.adm("demanda/cancelar", {"id": d["id"]})
        self.assertEqual(self.erro(self.adm, "demanda/estender", {"id": d["id"], "minutos": 5}), 409)

    def test_estender_no_limite_do_prazo(self):
        d = self.nova(est=10)
        self.t += 11 * MIN
        self.adm("demanda/cobrar", {"id": d["id"]})
        self.adm("demanda/estender", {"id": d["id"], "minutos": 1})   # prazo == agora: ainda conta como passado
        self.assertTrue(self.dem(d["id"])["atraso_avisado"])

    def test_comentar(self):
        d = self.nova(self.tk_h)
        self.adm("demanda/comentar", {"id": d["id"], "texto": " olá\nmundo "})
        self.pes(self.tk_h, "demanda/comentar", {"id": d["id"], "texto": "origem"})
        self.pes(self.tk_b, "demanda/comentar", {"id": d["id"], "texto": "destino"})
        self.assertEqual(self.erro(self.pes, self.tk_f, "demanda/comentar", {"id": d["id"], "texto": "x"}), 403)
        for t in ("", "   ", "x" * 1001, "a\x00", None):
            self.assertEqual(self.erro(self.adm, "demanda/comentar", {"id": d["id"], "texto": t}), 400, t)
        r = self.dem(d["id"])
        self.assertEqual(r["comentarios"], [{"quem": "Escritório", "t": T0, "texto": "olá\nmundo"},
                                            {"quem": "Helena", "t": T0, "texto": "origem"},
                                            {"quem": "Bruno", "t": T0, "texto": "destino"}])
        self.assertEqual(self.evs(d["id"]), ["created"])   # comentário não vira evento
        with mock.patch.dict(ds.MAX, {"comentarios": 3}):
            self.assertEqual(self.erro(self.adm, "demanda/comentar", {"id": d["id"], "texto": "x"}), 400)
        self.adm("demanda/comentar", {"id": d["id"], "texto": "x" * 1000})

    def test_tetos_de_eventos_e_notas(self):
        d = self.nova()
        with mock.patch.dict(ds.MAX, {"eventos": 3, "notas": 4}):
            for _ in range(4):
                self.adm("demanda/cobrar", {"id": d["id"]})
        r = self.dem(d["id"])
        self.assertEqual(self.evs(d["id"]), ["created", "nudge", "nudge"])   # o "created" fica
        self.assertEqual(len(r["eventos"]), 3)
        notas = self.disco()["notas"]
        self.assertEqual([n["id"] for n in notas], [2, 3, 4, 5])   # as mais antigas saem; o id segue a sequência
        self.assertEqual(self.disco()["seq"]["nota"], 5)


class Atrasos(Base):
    def test_uma_vez_por_demanda(self):
        d = self.nova(est=10)
        feita = self.nova(self.tk_b, est=1, para={"s": "CNC", "p": self.carlos})
        self.pes(self.tk_c, "demanda/concluir", {"id": feita["id"]})
        self.t += 10 * MIN
        self.adm("nota/todas")
        self.assertFalse(self.dem(d["id"])["atraso_avisado"])   # no prazo exato ainda não
        self.t += 1
        self.adm("nota/todas")                                  # não mudou nada além do atraso: grava mesmo assim
        r = self.dem(d["id"])
        self.assertTrue(r["atraso_avisado"])
        self.assertEqual(r["eventos"][-1], {"t": self.t, "ev": "late", "quem": "Sistema", "nota": ""})
        self.assertEqual(self.notas()[-2:], [("adm", "late", d["id"]), ("CNC", "late", d["id"])])
        self.assertEqual(r["_rv"], self.rev())
        self.assertEqual(self.dem(feita["id"])["eventos"][-1]["ev"], "done")
        self.adm("demanda/cobrar", {"id": d["id"]})
        self.assertEqual(self.evs(d["id"]).count("late"), 1)
        self.assertEqual([n[1] for n in self.notas()].count("late"), 2)

    def test_leitura_nao_marca(self):
        d = self.nova(est=1)
        self.t += 5 * MIN
        r0 = self.rev()
        self.get()
        self.pes(self.tk_c, "vista")
        self.assertEqual(self.rev(), r0)
        self.assertFalse(self.dem(d["id"])["atraso_avisado"])


class Notas(Base):
    def test_lida_e_todas(self):
        d = self.nova(prio="urg")
        self.nova(prio="urg")
        notas = self.disco()["notas"]
        cnc = next(n["id"] for n in notas if n["aud"] == "CNC")
        adm = [n["id"] for n in notas if n["aud"] == "adm"]
        self.assertEqual(self.erro(self.adm, "nota/lida", {"nid": cnc}), 403)
        self.assertEqual(self.erro(self.pes, self.tk_h, "nota/lida", {"nid": cnc}), 403)
        self.assertEqual(self.erro(self.adm, "nota/lida", {"nid": 999}), 404)
        self.assertEqual(self.erro(self.adm, "nota/lida", {"nid": True}), 404)
        self.assertEqual(self.erro(self.adm, "nota/lida", {"nid": str(adm[0])}), 404)
        v = self.pes(self.tk_c, "nota/lida", {"nid": cnc})
        self.assertTrue(next(n for n in v["notas"] if n["id"] == cnc)["lida"])
        r0 = self.rev()
        self.pes(self.tk_c, "nota/lida", {"nid": cnc})
        self.assertEqual(self.rev(), r0)   # já lida: não grava
        self.adm("nota/todas")
        lidas = {n["id"]: n["lida"] for n in self.disco()["notas"]}
        self.assertTrue(all(lidas[i] for i in adm))
        self.assertFalse(lidas[[n["id"] for n in self.disco()["notas"] if n["aud"] == "CNC"][1]])
        r0 = self.rev()
        self.adm("nota/todas")
        self.assertEqual(self.rev(), r0)
        self.pes(self.tk_b, "nota/todas")
        self.assertTrue(all(n["lida"] for n in self.disco()["notas"]))
        self.assertEqual(d["id"], "SOL-1001")


class Setores(Base):
    def s(self, sid):
        return next(x for x in self.disco()["setores"] if x["id"] == sid)

    def test_novo(self):
        v = self.setor("PIN", "  Pintura  ", "🎨", "#EC4899")
        s = self.s("PIN")
        self.assertEqual({k: s[k] for k in ("id", "nome", "icone", "cor", "ativo")},
                         {"id": "PIN", "nome": "Pintura", "icone": "🎨", "cor": "#EC4899", "ativo": True})
        self.assertEqual(s["_rv"], self.rev())
        self.assertEqual(v["setores"][-1]["id"], "PIN")
        base = {"modo": "novo", "id": "XY", "nome": "Xis", "icone": "⚙️", "cor": "#3B82F6", "rev": 0}
        for ruim in ({"id": "xy"}, {"id": "X"}, {"id": "ABCDE"}, {"id": 12}, {"id": "PIN"}, {"nome": "ab"},
                     {"nome": "x" * 41}, {"icone": "🍕"}, {"cor": "#000000"}, {"modo": "outro"}, {"rev": "0"},
                     {"rev": None}, {"rev": False}, {"nome": "a\x7fb"}):
            self.assertEqual(self.erro(self.adm, "setor/salvar", dict(base, **ruim)), 400, ruim)
        self.assertEqual(self.msg(self.adm, "setor/salvar", dict(base, id="PIN")), "Esta sigla já está em uso.")
        self.adm("setor/salvar", dict(base, id="X9", nome="x" * 40))
        self.adm("setor/salvar", dict(base, id="AB12", nome="abc"))
        with mock.patch.dict(ds.MAX, {"setores": 6}):
            self.assertEqual(self.erro(self.adm, "setor/salvar", base), 400)

    def test_editar(self):
        rv = self.s("CNC")["_rv"]
        base = {"modo": "editar", "id": "CNC", "nome": "Corte", "icone": "🔩", "cor": "#0EA5E9"}
        self.assertEqual(self.erro(self.adm, "setor/salvar", dict(base, rev=rv - 1)), 409)
        self.assertEqual(self.erro(self.adm, "setor/salvar", dict(base, id="ZZ", rev=0)), 404)
        self.adm("setor/salvar", dict(base, rev=rv))
        s = self.s("CNC")
        self.assertEqual((s["nome"], s["icone"], s["cor"], s["_rv"]), ("Corte", "🔩", "#0EA5E9", self.rev()))
        self.assertEqual(self.erro(self.adm, "setor/salvar", dict(base, rev=rv)), 409)   # o rv que a tela tinha venceu

    def test_ativar(self):
        d = self.nova()
        msg = self.msg(self.adm, "setor/ativar", {"id": "CNC", "rev": self.s("CNC")["_rv"]})
        self.assertIn("1 demanda(s) em aberto", msg)
        self.nova(de_s="CNC", para={"s": "ESP", "p": None})
        self.adm("demanda/cancelar", {"id": d["id"]})
        self.adm("setor/ativar", {"id": "CNC", "rev": self.s("CNC")["_rv"]})   # aberta só como origem: pode
        self.assertFalse(self.s("CNC")["ativo"])
        self.assertEqual(self.erro(self.adm, "setor/ativar", {"id": "CNC", "rev": 0}), 409)
        self.assertEqual(self.erro(self.adm, "setor/ativar", {"id": "ZZ", "rev": 0}), 404)
        self.adm("setor/ativar", {"id": "CNC", "rev": self.s("CNC")["_rv"]})
        self.assertTrue(self.s("CNC")["ativo"])

    def test_apagar(self):
        self.setor("PIN", "Pintura")
        pid = self.pessoa("Paulo", "PIN", "7777")
        tk = self.entrar(pid, "7777")
        self.assertEqual(self.erro(self.adm, "setor/apagar", {"id": "PIN", "rev": 0}), 409)
        self.adm("setor/apagar", {"id": "PIN", "rev": self.s("PIN")["_rv"]})
        self.assertNotIn("PIN", [s["id"] for s in self.disco()["setores"]])
        self.assertNotIn(pid, [p["id"] for p in self.disco()["pessoas"]])   # as pessoas do setor vão junto
        self.assertEqual(self.erro(self.pes, tk, "vista"), 401)
        self.assertEqual(self.erro(self.adm, "setor/apagar", {"id": "PIN", "rev": 0}), 404)

    def test_apagar_com_historico(self):
        self.nova(de_s="ESP", para={"s": "PCP", "p": None})
        self.assertEqual(self.erro(self.adm, "setor/apagar", {"id": "ESP", "rev": self.s("ESP")["_rv"]}), 400)
        self.assertEqual(self.erro(self.adm, "setor/apagar", {"id": "PCP", "rev": self.s("PCP")["_rv"]}), 400)
        # pessoa do setor com histórico em outro setor (transferida depois)
        self.setor("PIN", "Pintura")
        pid = self.pessoa("Paulo", "PIN", "7777")
        doc = self.disco()
        arq = {"v": 1, "demandas": [dict(self.dem("SOL-1001"), id="SOL-900", de={"s": "CNC", "p": pid},
                                         para={"s": "ESP", "p": None}, status="done", fim=T0)]}
        (self.dir / "demandas-arquivo.json").write_text(json.dumps(arq), encoding="utf-8")
        self.assertEqual(self.erro(self.adm, "setor/apagar", {"id": "PIN", "rev": self.s("PIN")["_rv"]}), 400)
        self.assertEqual(self.erro(self.adm, "setor/apagar", {"id": "CNC", "rev": self.s("CNC")["_rv"]}), 400)
        self.assertEqual(doc["setores"][-1]["id"], "PIN")


class Pessoas(Base):
    def p(self, pid):
        return next(x for x in self.disco()["pessoas"] if x["id"] == pid)

    def test_novo(self):
        self.assertEqual([(p["id"], p["mat"]) for p in self.disco()["pessoas"]],
                         [("p0", "M100"), ("p1", "M101"), ("p2", "M102"), ("p3", "M103")])
        self.assertEqual(self.disco()["seq"]["pessoa"], 4)
        base = {"modo": "novo", "nome": "Ze", "setor": "CNC", "codigo": "1234", "rev": 0}
        for ruim in ({"codigo": None}, {"codigo": "123"}, {"codigo": "12345"}, {"codigo": "12a4"}, {"codigo": 1234},
                     {"nome": "Z"}, {"nome": "x" * 61}, {"setor": "ZZ"}, {"rev": "0"}, {"modo": None}):
            self.assertEqual(self.erro(self.adm, "pessoa/salvar", dict(base, **ruim)), 400, ruim)
        self.adm("pessoa/salvar", dict(base, nome="x" * 60))
        p = self.p("p4")
        self.assertEqual((p["nome"], p["setor"], p["mat"], p["ativo"], p["_rv"]), ("x" * 60, "CNC", "M104", True, self.rev()))
        self.assertEqual(p["hash"], api._hash("1234", p["sal"]))
        with mock.patch.dict(ds.MAX, {"pessoas": 5}):
            self.assertEqual(self.erro(self.adm, "pessoa/salvar", base), 400)

    def test_numero_sem_repetir(self):
        doc = self.disco()
        doc["seq"]["pessoa"] = 0
        (self.dir / "demandas.json").write_text(json.dumps(doc), encoding="utf-8")
        self.assertEqual(self.pessoa("Novo", "CNC", "1234"), "p4")
        doc = self.disco()
        doc["seq"]["pessoa"] = 20
        (self.dir / "demandas.json").write_text(json.dumps(doc), encoding="utf-8")
        self.assertEqual(self.pessoa("Outro", "CNC", "1234"), "p20")
        self.assertEqual(self.p("p20")["mat"], "M120")
        self.assertEqual(self.disco()["seq"]["pessoa"], 21)

    def test_setor_inativo_no_novo(self):
        self.setor("PIN", "Pintura")
        self.adm("setor/ativar", {"id": "PIN", "rev": self.disco()["setores"][-1]["_rv"]})
        self.assertEqual(self.erro(self.pessoa, "Ze", "PIN", "1234"), 400)

    def test_editar(self):
        base = {"modo": "editar", "id": self.bruno, "nome": "Bruno S.", "setor": "CNC"}
        rv = self.p(self.bruno)["_rv"]
        self.assertEqual(self.erro(self.adm, "pessoa/salvar", dict(base, rev=rv - 1)), 409)
        self.assertEqual(self.erro(self.adm, "pessoa/salvar", dict(base, id="p99", rev=0)), 404)
        h = self.p(self.bruno)["hash"]
        self.adm("pessoa/salvar", dict(base, rev=rv, codigo=""))
        p = self.p(self.bruno)
        self.assertEqual((p["nome"], p["hash"], p["_rv"]), ("Bruno S.", h, self.rev()))   # código vazio mantém
        self.pes(self.tk_b, "vista")
        self.assertEqual(self.erro(self.adm, "pessoa/salvar", dict(base, rev=p["_rv"], codigo="12")), 400)
        api._FAILS[self.bruno] = [3, 0.0, 0]
        self.adm("pessoa/salvar", dict(base, rev=p["_rv"], codigo="8888"))
        self.assertNotIn(self.bruno, api._FAILS)
        self.entrar(self.bruno, "8888")

    def test_transferir_devolve(self):
        prog = self.nova(self.tk_h)
        self.pes(self.tk_b, "demanda/aceitar", {"id": prog["id"]})
        self.pes(self.tk_b, "demanda/pausar", {"id": prog["id"], "motivo": "Máquina parada"})
        aberta = self.nova(para={"s": "CNC", "p": self.bruno})
        feita = self.nova(para={"s": "CNC", "p": self.bruno})
        self.pes(self.tk_b, "demanda/concluir", {"id": feita["id"]})
        outra = self.nova(para={"s": "CNC", "p": self.carlos})
        self.t += MIN
        self.assertEqual(self.erro(self.adm, "pessoa/salvar", {"modo": "editar", "id": self.bruno, "nome": "Bruno",
                                                               "setor": "ZZ", "rev": self.p(self.bruno)["_rv"]}), 400)
        self.adm("pessoa/salvar", {"modo": "editar", "id": self.bruno, "nome": "Bruno", "setor": "ESP",
                                   "rev": self.p(self.bruno)["_rv"]})
        self.assertEqual(self.p(self.bruno)["setor"], "ESP")
        r = self.dem(prog["id"])
        self.assertEqual((r["status"], r["iniciado"], r["para"], r["pausas"][0]["fim"]),
                         ("new", None, {"s": "CNC", "p": None}, self.t))
        self.assertEqual(r["eventos"][-1], {"t": self.t, "ev": "reassigned", "quem": "Escritório",
                                            "nota": "Usuário transferido de setor — voltou para a fila do setor"})
        a = self.dem(aberta["id"])
        self.assertEqual((a["status"], a["para"]["p"]), ("new", None))
        self.assertEqual(self.dem(feita["id"])["para"]["p"], self.bruno)
        self.assertEqual(self.dem(outra["id"])["para"]["p"], self.carlos)
        self.assertEqual(self.notas()[-2:], [("CNC", "new", prog["id"]), ("CNC", "new", aberta["id"])])

    def test_ativar(self):
        d = self.nova(para={"s": "CNC", "p": self.bruno})
        self.assertEqual(self.erro(self.adm, "pessoa/ativar", {"id": self.bruno, "rev": -1}), 409)
        self.assertEqual(self.erro(self.adm, "pessoa/ativar", {"id": "p99", "rev": 0}), 404)
        self.adm("pessoa/ativar", {"id": self.bruno, "rev": self.p(self.bruno)["_rv"]})
        self.assertFalse(self.p(self.bruno)["ativo"])
        self.assertIsNone(self.dem(d["id"])["para"]["p"])
        self.assertEqual(self.dem(d["id"])["eventos"][-1]["nota"], "Usuário desativado — voltou para a fila do setor")
        self.adm("pessoa/ativar", {"id": self.bruno, "rev": self.p(self.bruno)["_rv"]})
        self.assertTrue(self.p(self.bruno)["ativo"])
        self.entrar(self.bruno, "3333")

    def test_apagar(self):
        self.nova(self.tk_h)
        self.assertEqual(self.erro(self.adm, "pessoa/apagar", {"id": self.helena, "rev": self.p(self.helena)["_rv"]}), 400)
        d = self.nova(para={"s": "CNC", "p": self.carlos})
        self.assertEqual(self.erro(self.adm, "pessoa/apagar", {"id": self.carlos, "rev": self.p(self.carlos)["_rv"]}), 400)
        arq = {"v": 1, "demandas": [dict(self.dem(d["id"]), id="SOL-1", para={"s": "CNC", "p": self.bruno},
                                         status="done", fim=T0)]}
        (self.dir / "demandas-arquivo.json").write_text(json.dumps(arq), encoding="utf-8")
        self.assertEqual(self.erro(self.adm, "pessoa/apagar", {"id": self.bruno, "rev": self.p(self.bruno)["_rv"]}), 400)
        self.assertEqual(self.erro(self.adm, "pessoa/apagar", {"id": self.fer, "rev": -1}), 409)
        self.adm("pessoa/apagar", {"id": self.fer, "rev": self.p(self.fer)["_rv"]})
        self.assertNotIn(self.fer, [p["id"] for p in self.disco()["pessoas"]])
        self.assertEqual(self.erro(self.adm, "pessoa/apagar", {"id": self.fer, "rev": 0}), 404)


class Anexos(Base):
    def arquivos(self):
        pasta = self.dir / "demandas-anexos"
        return sorted(p.name for p in pasta.iterdir()) if pasta.exists() else []

    def enviar(self, did, tk=None, dados=B64, nome="foto.jpg"):
        body = {"id": did, "nome": nome, "dados": dados}
        return self.pes(tk, "anexo/enviar", body) if tk else self.adm("anexo/enviar", body)

    def test_enviar_e_ler(self):
        d = self.nova(self.tk_h)
        self.t += MIN
        v = self.enviar(d["id"], nome=" foto.jpg ")
        a = v["demandas"][0]["anexos"][0]
        self.assertEqual(set(a), {"id", "nome", "tipo", "bytes", "por", "t"})   # sem _p
        self.assertEqual((a["nome"], a["tipo"], a["bytes"], a["por"], a["t"]), ("foto.jpg", "jpg", len(JPG), "Escritório", self.t))
        raw = self.dem(d["id"])["anexos"][0]
        self.assertIsNone(raw["_p"])
        self.assertEqual(self.dem(d["id"])["eventos"][-1], {"t": self.t, "ev": "attach", "quem": "Escritório", "nota": "foto.jpg"})
        self.assertEqual(self.arquivos(), [a["id"] + ".jpg"])
        self.assertEqual(v["anexos_uso"]["bytes"], len(JPG))
        out = self.get("anexo/" + a["id"])
        self.assertEqual(out, {"id": a["id"], "nome": "foto.jpg", "tipo": "jpg", "dados": B64})
        self.assertEqual(self.pes(self.tk_h, "anexo/ler", {"aid": a["id"]})["dados"], B64)    # quem pediu
        self.assertEqual(self.pes(self.tk_b, "anexo/ler", {"aid": a["id"]})["tipo"], "jpg")   # setor destino
        self.assertEqual(self.erro(self.pes, self.tk_f, "anexo/ler", {"aid": a["id"]}), 403)
        self.assertEqual(self.adm("anexo/ler", {"aid": a["id"]})["id"], a["id"])
        for aid in ("a" + "0" * 16, "x", None, "../demandas"):
            self.assertEqual(self.erro(self.pes, self.tk_h, "anexo/ler", {"aid": aid}), 404, aid)
            self.assertEqual(self.erro(self.get, "anexo/%s" % aid), 404, aid)
        self.assertEqual(self.erro(self.get, "anexo/" + a["id"], ctx=OP), 403)

    def test_quem_envia(self):
        d = self.nova(self.tk_h)
        v = self.enviar(d["id"], self.tk_b, base64.b64encode(PNG).decode(), "p.png")
        a = v["demandas"][0]["anexos"][0]
        self.assertEqual((a["tipo"], a["por"]), ("png", "Bruno"))
        self.assertEqual(self.dem(d["id"])["anexos"][0]["_p"], self.bruno)
        self.enviar(d["id"], self.tk_h)
        self.assertEqual(self.erro(self.enviar, d["id"], self.tk_f), 403)
        self.assertEqual(len(self.arquivos()), 2)   # recusado não grava arquivo

    def test_limites(self):
        d = self.nova()
        for ruim in ("", "abc", "@@@@", "/9j/4A==\n", "ção=", None, 5):
            self.assertEqual(self.erro(self.enviar, d["id"], dados=ruim), 400, ruim)
        self.assertEqual(self.erro(self.enviar, d["id"], dados=base64.b64encode(b"GIF89a....").decode()), 400)
        self.assertEqual(self.erro(self.enviar, d["id"], nome="a\x01b.jpg"), 400)
        self.assertEqual(self.erro(self.enviar, d["id"], nome=""), 400)
        self.assertEqual(self.erro(self.enviar, d["id"], nome="x" * 121), 400)
        grande = "A" * ((ds.ANEXO_MAX + 2) // 3 * 4 + 4)
        with mock.patch.object(api.base64, "b64decode") as dec:
            self.assertEqual(self.erro(self.enviar, d["id"], dados=grande), 413)
            dec.assert_not_called()   # recusa pelo tamanho do texto, sem decodificar
        no_teto = base64.b64encode(JPG + b"x" * (ds.ANEXO_MAX - len(JPG))).decode()
        self.assertEqual(len(no_teto), (ds.ANEXO_MAX + 2) // 3 * 4)
        self.enviar(d["id"], dados=no_teto)
        self.assertEqual(self.erro(self.enviar, d["id"], dados=base64.b64encode(JPG + b"x" * ds.ANEXO_MAX).decode()), 413)
        for _ in range(4):
            self.enviar(d["id"])
        self.assertEqual(self.erro(self.enviar, d["id"]), 400)
        self.assertEqual(len(self.arquivos()), 5)
        self.assertEqual(self.erro(self.enviar, "SOL-9"), 404)

    def test_cota(self):
        d = self.nova()
        with mock.patch.object(ds, "COTA", len(JPG) + 10):
            self.enviar(d["id"])
            self.assertEqual(self.erro(self.enviar, d["id"]), 507)
        self.assertEqual(len(self.arquivos()), 1)

    def test_cancelada_e_encerrada(self):
        d = self.nova()
        self.adm("demanda/cancelar", {"id": d["id"]})
        self.assertEqual(self.erro(self.enviar, d["id"]), 409)
        f = self.nova(para={"s": "CNC", "p": self.carlos})
        self.pes(self.tk_c, "demanda/concluir", {"id": f["id"]})
        self.enviar(f["id"], self.tk_c)   # concluída ainda recebe (só cancelada não)

    def test_orfao_apagado_quando_a_gravacao_falha(self):
        d = self.nova()
        with mock.patch.object(ds, "commit", side_effect=OSError("disco")):
            with self.assertRaises(OSError):
                self.enviar(d["id"])
        self.assertEqual(self.arquivos(), [])
        self.assertEqual(self.dem(d["id"])["anexos"], [])

    def test_orfao_apagado_quando_o_estado_muda_no_meio(self):
        d = self.nova()
        real = ds.salvar_anexo

        def no_meio(dados, nome):
            meta = real(dados, nome)
            self.adm("demanda/cancelar", {"id": d["id"]})   # outro aparelho cancela enquanto o arquivo grava
            return meta

        with mock.patch.object(ds, "salvar_anexo", side_effect=no_meio):
            self.assertEqual(self.erro(self.enviar, d["id"]), 409)
        self.assertEqual(self.arquivos(), [])

    def test_vista_que_falha_depois_de_gravar_nao_apaga(self):
        d = self.nova()
        with mock.patch.object(api, "_vista_de", side_effect=RuntimeError("x")):
            with self.assertRaises(RuntimeError):
                self.enviar(d["id"])
        self.assertEqual(len(self.arquivos()), 1)
        self.assertEqual(len(self.dem(d["id"])["anexos"]), 1)

    def test_enviar_marca_atraso(self):
        d = self.nova(est=1)
        self.t += 2 * MIN
        self.enviar(d["id"])
        self.assertEqual(self.evs(d["id"])[-2:], ["attach", "late"])
        self.assertEqual(self.dem(d["id"])["_rv"], self.rev())

    def test_apagar(self):
        d = self.nova(self.tk_h)
        aid_b = self.enviar(d["id"], self.tk_b)["demandas"][0]["anexos"][0]["id"]
        aid_h = self.enviar(d["id"], self.tk_h)["demandas"][0]["anexos"][1]["id"]
        self.assertEqual(self.erro(self.pes, self.tk_c, "anexo/apagar", {"id": d["id"], "aid": aid_b}), 403)
        self.assertEqual(self.erro(self.pes, self.tk_h, "anexo/apagar", {"id": d["id"], "aid": aid_b}), 403)
        self.assertEqual(self.erro(self.pes, self.tk_b, "anexo/apagar", {"id": d["id"], "aid": "a" + "1" * 16}), 404)
        with mock.patch.object(ds, "commit", side_effect=OSError("disco")):
            with self.assertRaises(OSError):
                self.pes(self.tk_b, "anexo/apagar", {"id": d["id"], "aid": aid_b})
        self.assertEqual(len(self.arquivos()), 2)   # gravação falhou: o arquivo fica
        v = self.pes(self.tk_b, "anexo/apagar", {"id": d["id"], "aid": aid_b})
        self.assertEqual([a["id"] for a in v["demandas"][0]["anexos"]], [aid_h])
        self.assertEqual(self.arquivos(), [aid_h + ".jpg"])
        self.assertEqual(self.dem(d["id"])["_rv"], self.rev())
        self.adm("demanda/cancelar", {"id": d["id"]})
        self.assertEqual(self.erro(self.adm, "anexo/apagar", {"id": d["id"], "aid": aid_h}), 409)

    def test_adm_apaga_qualquer(self):
        d = self.nova(self.tk_h)
        aid = self.enviar(d["id"], self.tk_h)["demandas"][0]["anexos"][0]["id"]
        self.adm("anexo/apagar", {"id": d["id"], "aid": aid})
        self.assertEqual(self.arquivos(), [])

    def test_anexo_do_arquivo_morto(self):
        d = self.nova()
        aid = self.enviar(d["id"])["demandas"][0]["anexos"][0]["id"]
        doc = self.disco()
        morta = dict(doc["demandas"][0], status="done", fim=T0)
        doc["demandas"] = []
        (self.dir / "demandas.json").write_text(json.dumps(doc), encoding="utf-8")
        (self.dir / "demandas-arquivo.json").write_text(json.dumps({"v": 1, "demandas": [morta]}), encoding="utf-8")
        self.assertEqual(self.get("anexo/" + aid)["dados"], B64)   # o ADM abre pelo histórico
        self.assertEqual(self.erro(self.pes, self.tk_c, "anexo/ler", {"aid": aid}), 404)   # pessoa só vê o principal


class Leituras(Base):
    def test_vista_de_pessoa_nao_vaza(self):
        a = self.nova(de_s="ESP", para={"s": "PCP", "p": None})
        b = self.nova(self.tk_h, para={"s": "ESP", "p": None})
        c = self.nova(para={"s": "CNC", "p": None})
        v = self.pes(self.tk_h, "vista")
        self.assertEqual({d["id"] for d in v["demandas"]}, {a["id"], b["id"]})
        self.assertEqual({n["aud"] for n in v["notas"]}, {"PCP"})
        self.assertEqual({f["dem"] for f in v["feed"]}, {a["id"], b["id"]})
        v = self.pes(self.tk_f, "vista")
        self.assertEqual({d["id"] for d in v["demandas"]}, {b["id"]})
        self.assertNotIn(c["id"], json.dumps(v))
        self.assertNotIn("anexos_uso", v)
        self.assertNotIn("backup", v)

    def test_vista_do_adm_traz_o_aviso_do_backup_sem_caminho(self):
        for papel in ("maquina", "completo"):
            v = self.get(ctx={"papel": papel})
            self.assertEqual(v["backup"], {"alerta": "grave", "texto": "Nenhum backup feito ainda.", "ultimo_ok_t": None,
                                           "restaurado": None})
        (self.dir / "backup-estado.json").write_text(json.dumps({"ultimo_ok": {"t": self.t - 3600000},
                                                                 "restaurado": {"t": 5, "copia_t": 4, "nome": "x"}}),
                                                     encoding="utf-8")
        self.assertEqual(self.get()["backup"], {"alerta": None, "texto": "", "ultimo_ok_t": self.t - 3600000,
                                                "restaurado": {"t": 5, "copia_t": 4}})
        self.assertEqual(self.adm("vista")["backup"]["ultimo_ok_t"], self.t - 3600000)
        self.assertNotIn(str(self.dir), json.dumps(self.get()["backup"]))

    def test_historico(self):
        self.nova()
        self.t += 10 * MIN
        self.nova()
        velha = dict(self.dem("SOL-1001"), id="SOL-900", criado=T0 - 86400000, status="done", fim=T0 - 1000)
        repetida = dict(self.dem("SOL-1001"), titulo="cópia velha")
        (self.dir / "demandas-arquivo.json").write_text(json.dumps({"v": 1, "demandas": [velha, repetida]}), encoding="utf-8")
        out = self.adm("historico", {"de": T0 - 2 * 86400000, "ate": self.t})
        self.assertEqual([d["id"] for d in out["demandas"]], ["SOL-1002", "SOL-1001", "SOL-900"])
        self.assertEqual(out["demandas"][1]["titulo"], "Cortar chapas")   # o principal vence
        self.assertIn("sla", out["demandas"][2])
        self.assertEqual(out["demandas"][2]["total"], round((T0 - 1000 - (T0 - 86400000)) / MIN, 1))
        self.assertEqual([d["id"] for d in self.adm("historico", {"de": T0, "ate": T0})["demandas"]], ["SOL-1001"])
        self.assertEqual(self.adm("historico", {"de": T0 + 1, "ate": self.t - 1})["demandas"], [])
        for ruim in ({"de": T0, "ate": T0 - 1}, {"de": -1, "ate": T0}, {"de": "0", "ate": T0}, {"de": 0}, {"de": True, "ate": 5}):
            self.assertEqual(self.erro(self.adm, "historico", ruim), 400, ruim)
        with mock.patch.object(api, "HIST_MAX", 1):
            self.assertEqual([d["id"] for d in self.adm("historico", {"de": 0, "ate": self.t})["demandas"]], ["SOL-1002"])

    def test_crono(self):
        d = self.nova(self.tk_h)
        self.pes(self.tk_c, "demanda/aceitar", {"id": d["id"]})
        self.t += 30 * MIN
        self.pes(self.tk_c, "demanda/concluir", {"id": d["id"]})
        morta = dict(self.dem(d["id"]), id="SOL-5")
        (self.dir / "demandas-arquivo.json").write_text(json.dumps({"v": 1, "demandas": [morta]}), encoding="utf-8")
        for dias in (1, 7, 30):
            c = self.adm("crono", {"dias": dias})
            self.assertEqual(c["dias"], dias)
        c = self.adm("crono", {"dias": 7})
        self.assertEqual(c["kpis"]["concluidas"], 2)   # conta o arquivo morto
        self.assertEqual(c["ranking"], [{"p": self.carlos, "n": 2, "sla": 100}])
        for ruim in (2, True, "7", None):
            self.assertEqual(self.erro(self.adm, "crono", {"dias": ruim}), 400, ruim)

    def test_leitura_nao_grava(self):
        self.nova()
        r0 = self.rev()
        self.adm("historico", {"de": 0, "ate": T0})
        self.adm("crono", {"dias": 7})
        self.adm("vista")
        self.assertEqual(self.rev(), r0)

    def test_erro_sem_caminho(self):
        for nome in ("demandas.json", "demandas.json.bak"):
            (self.dir / nome).write_text("{quebrado", encoding="utf-8")
        ds._CACHE.update(key=None, texto=None)
        with self.assertRaises(api.ApiError) as c:
            self.get()
        self.assertEqual(c.exception.status, 500)
        self.assertIn("corrompido", str(c.exception))
        self.assertNotIn(str(self.dir), str(c.exception))


class Mensagens(Base):
    """Cada recusa com o status e o texto que a tela mostra (o servidor repassa str(ApiError))."""

    def falha(self, status, texto, fn, *a, **kw):
        with self.assertRaises(api.ApiError) as c:
            fn(*a, **kw)
        self.assertEqual((c.exception.status, str(c.exception)), (status, texto))

    def test_entradas(self):
        f = self.falha
        f(400, "Pedido inválido.", api.handle, "POST", "vista", [], ADM)
        for m, r in (("GET", "x"), ("PUT", ""), ("POST", "x")):
            f(404, "Caminho das demandas desconhecido.", api.handle, m, r, {}, ADM)
        f(403, "Identifique-se para usar as demandas.", self.adm, "vista", ctx=OP)
        f(404, "Pessoa não encontrada.", self.entrar, "p99", "1111")
        f(400, "Título: texto com caractere não permitido.", self.nova, titulo="a\x00bcdef")
        f(400, "Título: de 5 a 140 caracteres.", self.nova, titulo="abc")
        f(400, "Motivo inválido.", self.nova, motivo="x")
        f(400, "Prioridade inválido.", self.nova, prio="x")
        f(400, "Tempo estipulado inválido.", self.nova, est=0)
        f(400, "Descrição: de 0 a 2000 caracteres.", self.nova, desc="x" * 2001)
        f(400, "Setor responsável inválido.", self.nova, para=None)
        f(400, "Setor responsável inválido.", self.nova, para={"s": "ZZ"})
        f(400, "Setor solicitante inválido.", self.nova, de_s="ZZ")
        f(400, "Pessoa responsável inválida.", self.nova, para={"s": "CNC", "p": self.fer})
        f(400, "Demanda inválida.", self.adm, "demanda/cobrar", {"id": "x"})
        f(404, "Demanda não encontrada.", self.adm, "demanda/cobrar", {"id": "SOL-1"})
        with mock.patch.dict(ds.MAX, {"demandas": 0}):
            f(400, "Limite de demandas em aberto atingido.", self.nova)

    def test_transicoes(self):
        f = self.falha
        d = self.nova(self.tk_h)["id"]
        f(403, "Só quem é do setor responsável pode aceitar.", self.pes, self.tk_f, "demanda/aceitar", {"id": d})
        f(403, "Só o responsável pela demanda pode fazer isso.", self.pes, self.tk_c, "demanda/pausar", {"id": d})
        f(403, "Só quem pediu ou o escritório pode cancelar.", self.pes, self.tk_c, "demanda/cancelar", {"id": d})
        f(403, "Só quem pediu ou o escritório pode cobrar.", self.pes, self.tk_c, "demanda/cobrar", {"id": d})
        f(403, "Só os setores da demanda podem comentar.", self.pes, self.tk_f, "demanda/comentar", {"id": d, "texto": "x"})
        f(403, "Só o responsável (ou o setor, enquanto aberta) pode repassar.", self.pes, self.tk_f,
          "demanda/reatribuir", {"id": d, "s": "ESP"})
        f(400, "Setor inválido.", self.adm, "demanda/reatribuir", {"id": d, "s": "ZZ"})
        self.pes(self.tk_c, "demanda/aceitar", {"id": d})
        f(409, "A demanda não está pausada.", self.pes, self.tk_c, "demanda/retomar", {"id": d})
        f(400, "Motivo da pausa inválido.", self.pes, self.tk_c, "demanda/pausar", {"id": d, "motivo": "x"})
        f(400, "Observação: de 0 a 500 caracteres.", self.pes, self.tk_c, "demanda/pausar",
          {"id": d, "motivo": "Máquina parada", "obs": "x" * 501})
        f(400, "Observação: de 0 a 500 caracteres.", self.pes, self.tk_c, "demanda/concluir", {"id": d, "nota": "x" * 501})
        f(400, "Observação: de 0 a 500 caracteres.", self.adm, "demanda/reatribuir", {"id": d, "s": "CNC", "nota": "x" * 501})
        f(400, "Motivo: de 0 a 500 caracteres.", self.adm, "demanda/cancelar", {"id": d, "motivo": "x" * 501})
        f(400, "Comentário: de 1 a 1000 caracteres.", self.adm, "demanda/comentar", {"id": d, "texto": ""})
        f(400, "Prioridade inválido.", self.adm, "demanda/prioridade", {"id": d, "prio": "x"})
        f(400, "Minutos inválido.", self.adm, "demanda/estender", {"id": d, "minutos": 0})
        with mock.patch.dict(ds.MAX, {"pausas": 0, "comentarios": 0}):
            f(400, "Limite de pausas desta demanda atingido.", self.pes, self.tk_c, "demanda/pausar",
              {"id": d, "motivo": "Máquina parada"})
            f(400, "Limite de comentários desta demanda atingido.", self.adm, "demanda/comentar", {"id": d, "texto": "x"})
        self.pes(self.tk_c, "demanda/pausar", {"id": d, "motivo": "Máquina parada"})
        f(409, "Só uma demanda em andamento pode ser pausada.", self.pes, self.tk_c, "demanda/pausar",
          {"id": d, "motivo": "Máquina parada"})
        big = self.nova(est=43200)["id"]
        f(400, "O tempo estipulado passaria de 30 dias.", self.adm, "demanda/estender", {"id": big, "minutos": 1})
        # limites aceitos
        self.pes(self.tk_c, "demanda/concluir", {"id": d, "nota": "x" * 500})
        self.adm("demanda/reatribuir", {"id": big, "s": "CNC", "nota": "x" * 500})
        self.adm("demanda/comentar", {"id": big, "texto": "x"})
        self.adm("demanda/cancelar", {"id": big, "motivo": "x" * 500})
        f(409, "A demanda já foi encerrada.", self.adm, "demanda/cobrar", {"id": big})

    def test_anexos(self):
        f = self.falha
        d = self.nova(self.tk_h)["id"]

        def env(**kw):
            return self.adm("anexo/enviar", dict({"id": d, "nome": "f.jpg", "dados": B64}, **kw))

        f(403, "Só quem pediu ou o setor responsável pode anexar.", self.pes, self.tk_f, "anexo/enviar",
          {"id": d, "nome": "f.jpg", "dados": B64})
        f(400, "Anexo inválido.", env, dados="")
        f(400, "Anexo inválido.", env, dados="abc")
        limite = (ds.ANEXO_MAX + 2) // 3 * 4
        f(413, "Anexo maior que 5 MB.", env, dados="A" * (limite + 1))
        f(400, "Anexo inválido.", env, dados="A" * (limite - 1))   # no tamanho, mas base64 sem o comprimento certo
        f(400, "Nome do anexo: de 1 a 120 caracteres.", env, nome=" ")
        aid = env(nome="f")["demandas"][-1]["anexos"][0]["id"]   # nome de 1 caractere passa
        f(403, "Sem acesso a este anexo.", self.pes, self.tk_f, "anexo/ler", {"aid": aid})
        f(404, "Anexo não encontrado.", self.pes, self.tk_h, "anexo/ler", {"aid": "x"})
        f(404, "Anexo não encontrado.", self.pes, self.tk_h, "anexo/ler", {"aid": "a" + "0" * 16})
        f(404, "Anexo não encontrado.", self.adm, "anexo/apagar", {"id": d, "aid": "a" + "0" * 16})
        f(403, "Só quem enviou ou o escritório pode remover o anexo.", self.pes, self.tk_h, "anexo/apagar", {"id": d, "aid": aid})
        with mock.patch.object(ds, "ANEXOS_POR_DEMANDA", 1):
            f(400, "No máximo 1 anexos por demanda.", env)
        self.adm("demanda/cancelar", {"id": d})
        f(409, "Demanda cancelada não recebe anexo.", env)

    def test_cadastros(self):
        f = self.falha
        s = {"modo": "novo", "id": "XY", "nome": "Xis", "icone": "⚙️", "cor": "#3B82F6", "rev": 0}
        f(400, "Modo inválido.", self.adm, "setor/salvar", dict(s, modo="x"))
        f(400, "Nome do setor: de 3 a 40 caracteres.", self.adm, "setor/salvar", dict(s, nome="ab"))
        f(400, "Ícone inválido.", self.adm, "setor/salvar", dict(s, icone="x"))
        f(400, "Cor inválido.", self.adm, "setor/salvar", dict(s, cor="x"))
        f(400, "Sigla: de 2 a 4 letras maiúsculas ou números.", self.adm, "setor/salvar", dict(s, id="x"))
        f(400, "Versão do registro inválida.", self.adm, "setor/salvar", dict(s, rev=None))
        f(404, "Setor não encontrado.", self.adm, "setor/salvar", dict(s, modo="editar", id="ZZ"))
        f(404, "Setor não encontrado.", self.adm, "setor/ativar", {"id": "ZZ", "rev": 0})
        f(409, "Alterado em outro aparelho. Atualize a tela e tente de novo.", self.adm, "setor/ativar", {"id": "CNC", "rev": 99})
        with mock.patch.dict(ds.MAX, {"setores": 0, "pessoas": 0}):
            f(400, "Limite de setores atingido.", self.adm, "setor/salvar", s)
            f(400, "Limite de pessoas atingido.", self.pessoa, "Ze", "CNC", "1234")
        d = self.nova()

        def rv(k, i):
            return next(r["_rv"] for r in self.disco()[k] if r["id"] == i)

        f(400, "Setor com 1 demanda(s) em aberto: conclua ou reatribua antes de desativar.", self.adm, "setor/ativar",
          {"id": "CNC", "rev": rv("setores", "CNC")})
        f(400, "Setor com histórico de demandas: desative em vez de excluir.", self.adm, "setor/apagar",
          {"id": "CNC", "rev": rv("setores", "CNC")})
        p = {"modo": "novo", "nome": "Ze", "setor": "CNC", "codigo": "1234", "rev": 0}
        f(400, "Modo inválido.", self.adm, "pessoa/salvar", dict(p, modo="x"))
        f(400, "Nome: de 2 a 60 caracteres.", self.adm, "pessoa/salvar", dict(p, nome="Z"))
        f(400, "Setor inválido.", self.adm, "pessoa/salvar", dict(p, setor="ZZ"))
        f(400, "O código tem exatamente 4 números.", self.adm, "pessoa/salvar", dict(p, codigo="1"))
        self.adm("pessoa/salvar", dict(p, nome="Zé"))   # 2 caracteres passa
        f(404, "Pessoa não encontrada.", self.adm, "pessoa/salvar", dict(p, modo="editar", id="p99"))
        f(404, "Pessoa não encontrada.", self.adm, "pessoa/ativar", {"id": "p99", "rev": 0})
        f(400, "Setor inválido.", self.adm, "pessoa/salvar", {"modo": "editar", "id": self.bruno, "nome": "Bruno",
                                                             "setor": "ZZ", "rev": rv("pessoas", self.bruno)})
        self.adm("demanda/reatribuir", {"id": d["id"], "s": "CNC", "p": self.bruno})
        f(400, "Pessoa com histórico de demandas: desative em vez de excluir.", self.adm, "pessoa/apagar",
          {"id": self.bruno, "rev": rv("pessoas", self.bruno)})
        f(403, "Notificação de outra pessoa.", self.adm, "nota/lida", {"nid": 1})
        f(404, "Notificação não encontrada.", self.adm, "nota/lida", {"nid": 999})
        f(400, "Período inválido.", self.adm, "crono", {"dias": 3})
        f(400, "Início inválido.", self.adm, "historico", {"de": -1, "ate": 0})
        f(400, "Fim inválido.", self.adm, "historico", {"de": 5, "ate": 4})
        self.adm("historico", {"de": 10 ** 15, "ate": 10 ** 15})
        f(400, "Início inválido.", self.adm, "historico", {"de": 10 ** 15 + 1, "ate": 10 ** 15 + 1})
        f(400, "Fim inválido.", self.adm, "historico", {"de": 0, "ate": 10 ** 15 + 1})
        with mock.patch.object(api, "_codigo_fora", return_value=("p1", "0" * 32, "x")):
            f(409, "O código desta pessoa mudou. Tente de novo.", self.entrar, self.carlos, "2222")


class Detalhes(Base):
    """Estado interno que a mutação mostrou sem conferência."""

    def test_contagem_de_erros_exata(self):
        self.erro(self.entrar, self.carlos, "0000")
        self.assertEqual(api._FAILS[self.carlos], [1, 0.0, 0])
        for _ in range(4):
            self.erro(self.entrar, self.carlos, "0000")
        self.assertEqual(api._FAILS[self.carlos], [0, self.clk + 60, 0])
        self.clk += 60   # no instante em que vence, já libera
        self.entrar(self.carlos, "2222")
        api._FAILS[self.bruno] = [2, 0.0, 2]
        self.entrar(self.bruno, "3333")
        self.assertEqual(api._FAILS[self.bruno], [0, 0.0, 2])   # as tentativas em curso dos outros seguem contadas

    def test_hash_que_falha_conta_como_erro(self):
        with mock.patch.object(api, "_hash", side_effect=ValueError("x")):
            with self.assertRaises(ValueError):
                self.entrar(self.carlos, "2222")
        self.assertEqual(api._FAILS[self.carlos], [1, 0.0, 0])

    def test_token_e_teto_de_eventos(self):
        self.assertEqual(len(self.tk_c), 32)   # token_urlsafe(24)
        d = self.nova()["id"]
        with mock.patch.dict(ds.MAX, {"eventos": 3}):
            for _ in range(3):
                self.t += MIN
                self.adm("demanda/cobrar", {"id": d})
        self.assertEqual([e["t"] for e in self.dem(d)["eventos"]], [T0, T0 + 2 * MIN, T0 + 3 * MIN])

    def test_notas_completas(self):
        d = self.nova(self.tk_h, prio="urg")["id"]
        self.pes(self.tk_c, "demanda/aceitar", {"id": d})
        self.pes(self.tk_c, "demanda/concluir", {"id": d})
        d2 = self.nova(est=1)["id"]
        self.adm("demanda/cobrar", {"id": d2})
        self.adm("demanda/reatribuir", {"id": d2, "s": "ESP"})
        self.t += 2 * MIN
        self.adm("nota/todas")
        notas = [{k: v for k, v in n.items() if k != "id"} for n in self.disco()["notas"]]

        def n(aud, tipo, dem, quem, lida=False, t=T0):
            return {"aud": aud, "tipo": tipo, "dem": dem, "texto": "", "quem": quem, "t": t, "lida": lida}

        self.assertEqual(notas, [n("CNC", "new", d, "Helena"), n("adm", "urg", d, "Helena", True),
                                 n("PCP", "accepted", d, "Carlos"), n("PCP", "done", d, "Carlos"),
                                 n("CNC", "new", d2, "Escritório"), n("CNC", "nudge", d2, "Escritório"),
                                 n("ESP", "new", d2, "Escritório"),
                                 n("adm", "late", d2, "Sistema", False, T0 + 2 * MIN),
                                 n("ESP", "late", d2, "Sistema", False, T0 + 2 * MIN)])
        self.assertEqual([e["nota"] for e in self.dem(d2)["eventos"]][:2], ["", ""])

    def test_eventos_e_campos(self):
        d = self.nova(self.tk_h, tipo="mat", motivo="Retrabalho")["id"]
        raw = self.dem(d)
        self.assertEqual((raw["tipo"], raw["motivo"]), ("mat", "Retrabalho"))
        self.pes(self.tk_c, "demanda/aceitar", {"id": d})
        for _ in range(2):
            self.t += MIN
            self.pes(self.tk_c, "demanda/pausar", {"id": d, "motivo": "Máquina parada"})
            self.t += MIN
            self.pes(self.tk_c, "demanda/retomar", {"id": d})
        self.adm("demanda/prioridade", {"id": d, "prio": "low"})
        r = self.dem(d)
        self.assertEqual([p["fim"] for p in r["pausas"]], [T0 + 2 * MIN, T0 + 4 * MIN])   # a fechada não muda
        self.assertEqual(self.evs(d), ["created", "assigned", "started", "paused", "resumed", "paused", "resumed", "prio"])
        self.assertEqual(r["eventos"][4]["nota"], "")
        self.assertEqual(r["eventos"][-1]["nota"], "Normal → Baixa")

    def test_editar_sem_mudar_setor_nao_devolve(self):
        d = self.nova(para={"s": "CNC", "p": self.bruno})["id"]
        rv = next(p["_rv"] for p in self.disco()["pessoas"] if p["id"] == self.bruno)
        self.adm("pessoa/salvar", {"modo": "editar", "id": self.bruno, "nome": "Bruno B", "setor": "CNC", "rev": rv})
        self.assertEqual(self.dem(d)["para"]["p"], self.bruno)

    def test_devolve_percorre_todas(self):
        outra = self.nova(para={"s": "CNC", "p": self.carlos})["id"]
        minha = self.nova(para={"s": "CNC", "p": self.bruno})["id"]
        rv = next(p["_rv"] for p in self.disco()["pessoas"] if p["id"] == self.bruno)
        self.adm("pessoa/ativar", {"id": self.bruno, "rev": rv})
        self.assertIsNone(self.dem(minha)["para"]["p"])
        self.assertEqual(self.dem(outra)["para"]["p"], self.carlos)
        n = self.disco()["notas"][-1]
        self.assertEqual((n["aud"], n["tipo"], n["dem"], n["texto"], n["quem"]), ("CNC", "new", minha, "", "Escritório"))

    def test_marcar_atrasos_devolve_bool(self):
        self.assertIs(api.marcar_atrasos(ds.load(), self.t), False)

    def test_dominios_aceitos(self):
        for m in api.MOTIVOS:
            self.nova(motivo=m)
        d = self.nova(self.tk_b, para={"s": "CNC", "p": self.carlos})["id"]
        self.pes(self.tk_c, "demanda/aceitar", {"id": d})
        for m in api.PAUSAS:
            self.pes(self.tk_c, "demanda/pausar", {"id": d, "motivo": m})
            self.pes(self.tk_c, "demanda/retomar", {"id": d})
        self.assertEqual([p["motivo"] for p in self.dem(d)["pausas"]],
                         ["Aguardando material", "Aguardando outro setor", "Máquina parada", "Aguardando aprovação",
                          "Troca de turno ou intervalo", "Informação incompleta"])
        self.assertEqual(api.MOTIVOS, ("Falta de material", "Quebra de máquina", "Defeito de qualidade",
                                       "Mudança de projeto", "Ajuste de planejamento", "Retrabalho",
                                       "Solicitação do cliente", "Outro"))
        self.assertEqual(api.CORES, ("#6366F1", "#3B82F6", "#0EA5E9", "#06B6D4", "#0D9488", "#10B981", "#65A30D",
                                     "#D97706", "#E4572E", "#EC4899", "#8B5CF6", "#64748B"))
        self.assertEqual(api.HIST_MAX, 5000)


if __name__ == "__main__":
    unittest.main()
