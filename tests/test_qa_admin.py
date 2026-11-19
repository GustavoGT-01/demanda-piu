"""QA da aba Administração: setores, usuários e Expediente (horário de serviço), direto no api.py.

Complementa tests/test_demandas_api.py (classes Setores, Pessoas, Horario) e tests/test_demandas_agenda.py com o limite
exato e um além de cada campo, permissão por papel e os casos de borda. Matriz e bugs em docs/qa/admin.md.
Teste marcado `known-bug` expõe um defeito confirmado (falha esperada: não reprova a suíte).
"""

import datetime
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parents[1] / "demandas"
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import demandas_agenda as ag  # noqa: E402
import demandas_store as ds  # noqa: E402

_spec = importlib.util.spec_from_file_location("demandas_api_qa_admin", HERE / "api.py")
api = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(api)
ITER_REAL = api.ITER

MIN = 60000
T0 = 1_800_000_000_000
ADM = {"papel": "maquina"}
COMPLETO = {"papel": "completo"}
OP = {"papel": "operador"}


class Base(unittest.TestCase):
    def setUp(self):
        self._data = os.environ.get("DEMANDAS_DATA")
        self.dir = Path(tempfile.mkdtemp(prefix="dem-qa-admin-"))
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
        api.ITER = 1000
        fs = mock.patch("os.fsync", lambda fd: None)
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

    # --- cenário: PCP (Helena), CNC (Carlos, Bruno), ESP (Fernanda) ---
    def setor(self, sid, nome, icone="⚙️", cor="#3B82F6", **kw):
        return self.adm("setor/salvar", dict({"modo": "novo", "id": sid, "nome": nome, "icone": icone, "cor": cor,
                                             "rev": 0}, **kw))

    def pessoa(self, nome, setor, codigo, **kw):
        v = self.adm("pessoa/salvar", dict({"modo": "novo", "nome": nome, "setor": setor, "codigo": codigo, "rev": 0}, **kw))
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

    def s(self, sid):
        return next(x for x in self.disco()["setores"] if x["id"] == sid)

    def p(self, pid):
        return next(x for x in self.disco()["pessoas"] if x["id"] == pid)

    def arquivo(self, **dem):
        """Uma demanda só no arquivo morto (histórico que não está no principal)."""
        d = {"id": "SOL-900", "titulo": "Antiga", "tipo": "dem", "motivo": "Outro", "prio": "norm", "est": 60,
             "de": {"s": "PCP", "p": None}, "para": {"s": "CNC", "p": None}, "desc": "x", "status": "done",
             "criado": T0, "iniciado": T0, "fim": T0, "atraso_avisado": False, "pausas": [], "eventos": [],
             "comentarios": [], "anexos": [], "_rv": 1}
        d.update(dem)
        (self.dir / "demandas-arquivo.json").write_text(json.dumps({"v": 1, "demandas": [d]}), encoding="utf-8")
        ds._ARQ.update(key=None, demandas=[])


def email_de(n):
    """E-mail válido com exatamente n caracteres (local de 64, domínio com o resto)."""
    dominio = "d" * (n - 65 - 4) + ".com"
    return "a" * 64 + "@" + dominio


# =============================================================================================== setores
class SetorSalvar(Base):
    BASE = {"modo": "novo", "id": "XY", "nome": "Xis", "icone": "⚙️", "cor": "#3B82F6", "rev": 0}

    def novo(self, **kw):
        return self.adm("setor/salvar", dict(self.BASE, **kw))

    def test_sigla_valida_nos_limites(self):
        for sid in ("AB", "A1", "12", "ABCD", "A1B2", "0000"):
            with self.subTest(sid=sid):
                self.novo(id=sid)
                self.assertEqual(self.s(sid)["id"], sid)

    def test_sigla_invalida(self):
        for sid in ("", "A", "ABCDE", "ab", "aB", "A B", "A-B", "AÇ", "A\n", "AB\n", "\nAB", " AB", "AB ", None, 12, ["AB"], True):
            with self.subTest(sid=sid):
                self.assertEqual(self.erro(self.novo, id=sid), 400)
        self.assertEqual(self.msg(self.novo, id="A"), "Sigla: de 2 a 4 letras maiúsculas ou números.")
        self.assertEqual(self.msg(self.adm, "setor/salvar", {k: v for k, v in self.BASE.items() if k != "id"}),
                         "Sigla: de 2 a 4 letras maiúsculas ou números.")

    def test_sigla_repetida_ate_de_setor_inativo(self):
        self.novo()
        self.assertEqual(self.msg(self.novo), "Esta sigla já está em uso.")
        self.adm("setor/ativar", {"id": "XY", "rev": self.s("XY")["_rv"]})
        self.assertEqual(self.msg(self.novo), "Esta sigla já está em uso.")

    def test_nome_limites(self):
        self.novo(id="N3", nome="abc")
        self.novo(id="N4", nome="x" * 40)
        self.assertEqual(self.s("N4")["nome"], "x" * 40)
        for nome in ("", "ab", "x" * 41, "  ab  ", " " * 10, "a\tb", "a\nb", "a\x00b", "a\x7fb", None, 123, ["abc"]):
            with self.subTest(nome=nome):
                self.assertEqual(self.erro(self.novo, id="N5", nome=nome), 400)
        self.assertNotIn("N5", [x["id"] for x in self.disco()["setores"]])

    def test_nome_com_espacos_nas_pontas_e_acentos(self):
        self.novo(id="N6", nome="   Marcenaria Ç   ")
        self.assertEqual(self.s("N6")["nome"], "Marcenaria Ç")
        self.novo(id="N7", nome=" " + "x" * 40 + " ")   # 40 depois do strip
        self.assertEqual(len(self.s("N7")["nome"]), 40)

    def test_nome_com_html_vai_como_texto(self):
        self.novo(id="N8", nome="<img src=x onerror=1>")
        self.assertEqual(self.s("N8")["nome"], "<img src=x onerror=1>")   # a tela escapa (esc) ao desenhar

    def test_icone_e_cor_todos_validos(self):
        for i, ic in enumerate(api.ICONES):
            with self.subTest(icone=ic):
                self.novo(id="I%02d" % i, icone=ic)
                self.assertEqual(self.s("I%02d" % i)["icone"], ic)
        for i, cor in enumerate(api.CORES):
            with self.subTest(cor=cor):
                self.novo(id="C%02d" % i, cor=cor)
                self.assertEqual(self.s("C%02d" % i)["cor"], cor)

    def test_icone_e_cor_invalidos(self):
        for ic in ("", "🍕", "⚙", "⚙️⚙️", None, 1, ["⚙️"], "x"):
            with self.subTest(icone=ic):
                self.assertEqual(self.erro(self.novo, icone=ic), 400)
        for cor in ("", "#000000", "#6366f1", "6366F1", "#6366F", "red", None, 1, ["#6366F1"]):
            with self.subTest(cor=cor):
                self.assertEqual(self.erro(self.novo, cor=cor), 400)
        self.assertEqual(self.msg(self.novo, icone="🍕"), "Ícone inválido.")
        self.assertEqual(self.msg(self.novo, cor="#000000"), "Cor inválido.")

    def test_modo_invalido(self):
        for modo in ("", "NOVO", "outro", None, 1, ["novo"]):
            with self.subTest(modo=modo):
                self.assertEqual(self.erro(self.novo, modo=modo), 400)
        corpo = dict(self.BASE)
        del corpo["modo"]
        self.assertEqual(self.erro(self.adm, "setor/salvar", corpo), 400)

    def test_rev_do_pedido(self):
        for rev in ("0", None, False, True, 1.5, [0]):
            with self.subTest(rev=rev):
                self.assertEqual(self.erro(self.novo, rev=rev), 400)
        corpo = dict(self.BASE)
        del corpo["rev"]
        self.assertEqual(self.erro(self.adm, "setor/salvar", corpo), 400)
        self.novo(rev=7)       # no novo qualquer inteiro serve: não há registro com que comparar
        self.novo(id="NG", rev=-3)

    def test_email(self):
        casos = {"corte@empresa.com.br": "corte@empresa.com.br", "  Corte@Empresa.COM  ": "corte@empresa.com",
                 "a@b.co": "a@b.co", "x+y_z.w@sub.dominio.com": "x+y_z.w@sub.dominio.com"}
        for i, (entra, sai) in enumerate(casos.items()):
            with self.subTest(email=entra):
                self.novo(id="E%d" % i, email=entra)
                self.assertEqual(self.s("E%d" % i)["email"], sai)

    def test_email_invalido(self):
        for e in ("semarroba", "a@b", "a@b.c", "a b@c.com", "a@b .com", "a,b@c.com", "a;b@c.com", "<a@b.com>", '"a"@b.com',
                  "@b.com", "a@", "a@@b.com", "a@b.com\nBcc: x@y.com", "a@b.com\r\nBcc: x@y.com", 123, ["a@b.com"], True, {}):
            with self.subTest(email=e):
                self.assertEqual(self.erro(self.novo, email=e), 400)
        self.assertEqual(self.msg(self.novo, email="x"), "E-mail inválido: use algo como nome@empresa.com.br.")

    def test_email_limite_254(self):
        e254, e255 = email_de(254), email_de(255)
        self.assertEqual((len(e254), len(e255)), (254, 255))
        self.novo(id="E1", email=e254)
        self.assertEqual(self.s("E1")["email"], e254)
        self.assertEqual(self.erro(self.novo, id="E2", email=e255), 400)
        self.novo(id="E3", email="a" * 64 + "@x.com")
        self.assertEqual(self.erro(self.novo, id="E4", email="a" * 65 + "@x.com"), 400)

    def test_email_vazio_apaga_e_ausente_nao_mexe(self):
        self.novo(email="a@b.com")
        rv = lambda: self.s("XY")["_rv"]  # noqa: E731
        ed = {"modo": "editar", "id": "XY", "nome": "Xis", "icone": "⚙️", "cor": "#3B82F6"}
        self.adm("setor/salvar", dict(ed, rev=rv()))                      # ausente: mantém
        self.assertEqual(self.s("XY")["email"], "a@b.com")
        for vazio in ("", "   ", None):
            self.adm("setor/salvar", dict(ed, rev=rv(), email="z@y.com"))
            self.assertEqual(self.s("XY")["email"], "z@y.com")
            self.adm("setor/salvar", dict(ed, rev=rv(), email=vazio))
            self.assertNotIn("email", self.s("XY"), repr(vazio))

    def test_novo_nasce_ativo_com_rv_e_vista(self):
        v = self.novo()
        s = self.s("XY")
        self.assertEqual((s["ativo"], s["_rv"]), (True, self.rev()))
        self.assertEqual(v["setores"][-1]["id"], "XY")
        self.assertNotIn("email", s)

    def test_limite_de_setores(self):
        with mock.patch.dict(ds.MAX, {"setores": 4}):
            self.novo(id="L1")
            self.assertEqual(self.msg(self.novo, id="L2"), "Limite de setores atingido.")

    def test_editar_campos_e_sigla_imutavel(self):
        ed = {"modo": "editar", "id": "CNC", "nome": "  Corte  ", "icone": "🔩", "cor": "#0EA5E9", "email": "c@d.com"}
        self.adm("setor/salvar", dict(ed, rev=self.s("CNC")["_rv"]))
        s = self.s("CNC")
        self.assertEqual((s["id"], s["nome"], s["icone"], s["cor"], s["email"]), ("CNC", "Corte", "🔩", "#0EA5E9", "c@d.com"))
        self.assertEqual(self.erro(self.adm, "setor/salvar", dict(ed, id="cnc", rev=0)), 404)   # a sigla é a chave
        self.assertEqual(self.erro(self.adm, "setor/salvar", dict(ed, id=None, rev=0)), 404)
        for ruim in ({"nome": "ab"}, {"nome": "x" * 41}, {"icone": "🍕"}, {"cor": "#111111"}, {"email": "x"}):
            with self.subTest(ruim=ruim):
                self.assertEqual(self.erro(self.adm, "setor/salvar", dict(ed, rev=self.s("CNC")["_rv"], **ruim)), 400)

    def test_editar_nao_muda_ativo_e_conflito_409(self):
        self.adm("setor/ativar", {"id": "ESP", "rev": self.s("ESP")["_rv"]})
        rv = self.s("ESP")["_rv"]
        ed = {"modo": "editar", "id": "ESP", "nome": "Espuma", "icone": "🧽", "cor": "#10B981"}
        self.assertEqual(self.erro(self.adm, "setor/salvar", dict(ed, rev=rv - 1)), 409)
        self.assertEqual(self.erro(self.adm, "setor/salvar", dict(ed, rev=rv + 1)), 409)
        self.assertEqual(self.msg(self.adm, "setor/salvar", dict(ed, rev=0)),
                         "Alterado em outro aparelho. Atualize a tela e tente de novo.")
        self.adm("setor/salvar", dict(ed, rev=rv))
        self.assertFalse(self.s("ESP")["ativo"])
        self.assertEqual(self.erro(self.adm, "setor/salvar", dict(ed, rev=rv)), 409)   # o mesmo rev não vale duas vezes

    def test_rv_so_muda_no_registro_tocado(self):
        rv_cnc, rv_esp = self.s("CNC")["_rv"], self.s("ESP")["_rv"]
        self.adm("setor/salvar", {"modo": "editar", "id": "CNC", "nome": "Corte", "icone": "🔩", "cor": "#0EA5E9", "rev": rv_cnc})
        self.assertGreater(self.s("CNC")["_rv"], rv_cnc)
        self.assertEqual(self.s("ESP")["_rv"], rv_esp)

    def test_so_o_adm_salva(self):
        corpo = dict(self.BASE)
        for ctx, tk in ((OP, self.tk_c), (OP, self.tk_h)):
            self.assertEqual(self.erro(self.pes, tk, "setor/salvar", corpo, ctx), 403)
        self.assertEqual(self.erro(self.adm, "setor/salvar", corpo, OP), 403)           # operador sem tk
        self.assertEqual(self.erro(self.adm, "setor/salvar", corpo, {}), 403)           # sem papel
        self.assertEqual(self.erro(self.adm, "setor/salvar", corpo, {"papel": "x"}), 403)
        self.assertEqual(self.erro(self.pes, "tk-falso", "setor/salvar", corpo), 401)
        self.assertNotIn("XY", [x["id"] for x in self.disco()["setores"]])
        self.adm("setor/salvar", corpo, COMPLETO)   # o papel completo também é ADM
        self.assertEqual(self.s("XY")["id"], "XY")

    def test_tk_de_pessoa_no_papel_maquina_ainda_e_pessoa(self):
        self.assertEqual(self.erro(self.pes, self.tk_c, "setor/salvar", dict(self.BASE), ADM), 403)


class SetorAtivar(Base):
    def rv(self, sid):
        return self.s(sid)["_rv"]

    def test_desativar_e_reativar(self):
        self.adm("setor/ativar", {"id": "ESP", "rev": self.rv("ESP")})
        self.assertFalse(self.s("ESP")["ativo"])
        self.adm("setor/ativar", {"id": "ESP", "rev": self.rv("ESP")})
        self.assertTrue(self.s("ESP")["ativo"])

    def test_recusa_com_demanda_aberta_conta_novas_em_andamento_e_pausadas(self):
        a, b, c = self.nova(), self.nova(titulo="Segunda demanda"), self.nova(titulo="Terceira demanda")
        self.pes(self.tk_c, "demanda/aceitar", {"id": b["id"]})
        self.pes(self.tk_c, "demanda/aceitar", {"id": c["id"]})
        self.pes(self.tk_c, "demanda/pausar", {"id": c["id"], "motivo": "Máquina parada"})
        m = self.msg(self.adm, "setor/ativar", {"id": "CNC", "rev": self.rv("CNC")})
        self.assertEqual(m, "Setor com 3 demanda(s) em aberto: conclua ou reatribua antes de desativar.")
        self.assertTrue(self.s("CNC")["ativo"])
        self.adm("demanda/cancelar", {"id": a["id"]})
        self.pes(self.tk_c, "demanda/concluir", {"id": b["id"]})
        self.assertIn("1 demanda(s)", self.msg(self.adm, "setor/ativar", {"id": "CNC", "rev": self.rv("CNC")}))
        self.pes(self.tk_c, "demanda/concluir", {"id": c["id"]})
        self.adm("setor/ativar", {"id": "CNC", "rev": self.rv("CNC")})
        self.assertFalse(self.s("CNC")["ativo"])

    def test_aberta_so_como_origem_nao_impede(self):
        self.nova(de_s="CNC", para={"s": "ESP", "p": None})
        self.adm("setor/ativar", {"id": "CNC", "rev": self.rv("CNC")})
        self.assertFalse(self.s("CNC")["ativo"])

    def test_reativar_nao_confere_demandas(self):
        self.adm("setor/ativar", {"id": "ESP", "rev": self.rv("ESP")})
        self.adm("setor/ativar", {"id": "ESP", "rev": self.rv("ESP")})
        self.assertTrue(self.s("ESP")["ativo"])

    def test_rev_id_e_corpo(self):
        self.assertEqual(self.erro(self.adm, "setor/ativar", {"id": "ESP", "rev": self.rv("ESP") - 1}), 409)
        self.assertEqual(self.erro(self.adm, "setor/ativar", {"id": "ZZ", "rev": 0}), 404)
        self.assertEqual(self.erro(self.adm, "setor/ativar", {"rev": 0}), 404)
        self.assertEqual(self.erro(self.adm, "setor/ativar", {"id": ["ESP"], "rev": 0}), 404)
        for rev in (None, "1", True):
            with self.subTest(rev=rev):
                self.assertEqual(self.erro(self.adm, "setor/ativar", {"id": "ESP", "rev": rev}), 400)
        self.assertEqual(self.erro(self.adm, "setor/ativar", {"id": "ESP"}), 400)
        self.assertTrue(self.s("ESP")["ativo"])

    def test_so_o_adm(self):
        corpo = {"id": "ESP", "rev": self.rv("ESP")}
        self.assertEqual(self.erro(self.pes, self.tk_c, "setor/ativar", corpo), 403)
        self.assertEqual(self.erro(self.adm, "setor/ativar", corpo, OP), 403)
        self.assertTrue(self.s("ESP")["ativo"])

    def test_setor_inativo_barra_a_pessoa_e_o_token(self):
        self.adm("setor/ativar", {"id": "CNC", "rev": self.rv("CNC")})
        self.assertEqual(self.erro(self.entrar, self.carlos, "2222"), 404)
        self.assertEqual(self.erro(self.pes, self.tk_c, "vista"), 401)
        self.adm("setor/ativar", {"id": "CNC", "rev": self.rv("CNC")})
        self.entrar(self.carlos, "2222")

    def test_setor_inativo_nao_recebe_pessoa_nova_nem_demanda(self):
        self.adm("setor/ativar", {"id": "ESP", "rev": self.rv("ESP")})
        self.assertEqual(self.erro(self.pessoa, "Zeca", "ESP", "1234"), 400)
        self.assertEqual(self.erro(self.nova, para={"s": "ESP", "p": None}), 400)

    def test_recusa_de_desativar_com_demanda_aberta_diz_quantas(self):
        """QA-ADM-03: o CONTRATO descreve a recusa como a frase "Setor com N demanda(s) em aberto…" (sem campo extra)."""
        self.nova()
        with self.assertRaises(api.ApiError) as c:
            self.adm("setor/ativar", {"id": "CNC", "rev": self.rv("CNC")})
        self.assertEqual(c.exception.status, 400)
        self.assertIn("em aberto", str(c.exception))


class SetorApagar(Base):
    def rv(self, sid):
        return self.s(sid)["_rv"]

    def test_apaga_setor_vazio_e_pessoas_com_token_revogado(self):
        self.setor("PIN", "Pintura")
        pid = self.pessoa("Paulo", "PIN", "7777")
        tk = self.entrar(pid, "7777")
        self.adm("setor/apagar", {"id": "PIN", "rev": self.rv("PIN")})
        self.assertNotIn("PIN", [x["id"] for x in self.disco()["setores"]])
        self.assertNotIn(pid, [x["id"] for x in self.disco()["pessoas"]])
        self.assertEqual(self.erro(self.pes, tk, "vista"), 401)
        self.assertEqual(self.erro(self.entrar, pid, "7777"), 404)

    def test_recusa_historico_no_principal_origem_e_destino(self):
        self.nova(de_s="ESP", para={"s": "PCP", "p": None})
        for sid in ("ESP", "PCP"):
            with self.subTest(sid=sid):
                self.assertEqual(self.msg(self.adm, "setor/apagar", {"id": sid, "rev": self.rv(sid)}),
                                 "Setor com histórico de demandas: desative em vez de excluir.")
        self.assertIn("ESP", [x["id"] for x in self.disco()["setores"]])

    def test_recusa_historico_so_no_arquivo_origem_destino_e_pessoa(self):
        self.setor("ORI", "Origem")
        self.setor("DES", "Destino")
        self.setor("GEN", "Gente")
        pid = self.pessoa("Gil", "GEN", "5555")
        self.arquivo(de={"s": "ORI", "p": None}, para={"s": "DES", "p": None})
        self.assertEqual(self.erro(self.adm, "setor/apagar", {"id": "ORI", "rev": self.rv("ORI")}), 400)
        self.assertEqual(self.erro(self.adm, "setor/apagar", {"id": "DES", "rev": self.rv("DES")}), 400)
        self.arquivo(de={"s": "ORI", "p": None}, para={"s": "ORI", "p": pid})   # só a pessoa do setor GEN aparece
        self.assertEqual(self.erro(self.adm, "setor/apagar", {"id": "GEN", "rev": self.rv("GEN")}), 400)
        self.assertIn(pid, [x["id"] for x in self.disco()["pessoas"]])   # nada foi apagado pela metade

    def test_recusa_pessoa_do_setor_com_historico_em_outro_setor(self):
        self.setor("PIN", "Pintura")
        pid = self.pessoa("Paulo", "PIN", "7777")
        self.nova(de_s="PCP", para={"s": "CNC", "p": None})
        self.adm("demanda/reatribuir", {"id": "SOL-1001", "s": "CNC", "p": self.carlos})
        d = self.dem("SOL-1001")
        d["para"]["p"] = pid   # simulação direta: a pessoa de PIN consta numa demanda de CNC
        doc = self.disco()
        doc["demandas"][0]["para"]["p"] = pid
        (self.dir / "demandas.json").write_text(json.dumps(doc), encoding="utf-8")
        ds._CACHE.update(key=None, texto=None)
        self.assertEqual(self.erro(self.adm, "setor/apagar", {"id": "PIN", "rev": self.rv("PIN")}), 400)

    def test_rev_404_e_permissao(self):
        self.setor("PIN", "Pintura")
        self.assertEqual(self.erro(self.adm, "setor/apagar", {"id": "PIN", "rev": self.rv("PIN") - 1}), 409)
        self.assertEqual(self.erro(self.adm, "setor/apagar", {"id": "ZZ", "rev": 0}), 404)
        self.assertEqual(self.erro(self.adm, "setor/apagar", {"id": "PIN"}), 400)
        self.assertEqual(self.erro(self.pes, self.tk_c, "setor/apagar", {"id": "PIN", "rev": self.rv("PIN")}), 403)
        self.assertEqual(self.erro(self.adm, "setor/apagar", {"id": "PIN", "rev": self.rv("PIN")}, OP), 403)
        self.assertIn("PIN", [x["id"] for x in self.disco()["setores"]])

    def test_rev_velha_vence_o_historico(self):
        self.nova(de_s="ESP", para={"s": "PCP", "p": None})
        self.assertEqual(self.erro(self.adm, "setor/apagar", {"id": "ESP", "rev": self.rv("ESP") - 1}), 409)

    def test_sigla_apagada_pode_voltar(self):
        self.setor("PIN", "Pintura")
        self.adm("setor/apagar", {"id": "PIN", "rev": self.rv("PIN")})
        self.setor("PIN", "Pintura 2")
        self.assertEqual(self.s("PIN")["nome"], "Pintura 2")

    def test_known_bug_excluir_setor_deixa_horario_orfao_e_trava_o_expediente(self):
        """known-bug QA-ADM-01: setor/apagar não tira o horário próprio nem os feriados do setor da agenda; a agenda
        fica com sigla inexistente e agenda/salvar passa a recusar com "Setor inválido" (a tela não mostra como tirar)."""
        self.setor("PIN", "Pintura")
        v = self.disco()["agenda"]["v"]
        self.adm("agenda/salvar", {"agenda": {**ag.padrao(), "ativa": True, "v": v,
                                              "setores": {"PIN": {"dias": [1], "turnos": [["07:00", "08:00"]]}},
                                              "feriados": [{"data": "2026-12-25", "nome": "Natal", "setores": ["PIN"]}]}})
        self.adm("setor/apagar", {"id": "PIN", "rev": self.s("PIN")["_rv"]})
        atual = self.disco()["agenda"]
        # esperado: sem referência ao setor apagado (ou, no mínimo, a agenda continua salvável)
        self.adm("agenda/salvar", {"agenda": dict(atual, ativa=False)})


# ============================================================================================== usuários
class PessoaSalvar(Base):
    BASE = {"modo": "novo", "nome": "Ze", "setor": "CNC", "codigo": "1234", "rev": 0}

    def novo(self, **kw):
        return self.adm("pessoa/salvar", dict(self.BASE, **kw))

    def test_matricula_e_ids_sequenciais(self):
        self.assertEqual([(x["id"], x["mat"]) for x in self.disco()["pessoas"]],
                         [("p0", "M100"), ("p1", "M101"), ("p2", "M102"), ("p3", "M103")])
        self.novo()
        self.assertEqual((self.p("p4")["mat"], self.p("p4")["ativo"]), ("M104", True))

    def test_id_nao_e_reusado_depois_de_apagar(self):
        self.novo()                                                    # p4 / M104
        self.adm("pessoa/apagar", {"id": "p4", "rev": self.p("p4")["_rv"]})
        self.novo(nome="Outro")
        self.assertEqual((self.disco()["pessoas"][-1]["id"], self.disco()["pessoas"][-1]["mat"]), ("p5", "M105"))

    def test_nome_limites(self):
        self.novo(nome="Zé")
        self.novo(nome="x" * 60)
        self.assertEqual(self.disco()["pessoas"][-1]["nome"], "x" * 60)
        for nome in ("", "Z", " Z ", "x" * 61, " " * 5, "a\tb", "a\nb", "a\x00b", None, 12, ["Ze"]):
            with self.subTest(nome=nome):
                self.assertEqual(self.erro(self.novo, nome=nome), 400)
        self.novo(nome="  Ana Maria  ")
        self.assertEqual(self.disco()["pessoas"][-1]["nome"], "Ana Maria")

    def test_codigo_obrigatorio_no_novo_e_exatamente_4_digitos(self):
        for cod in (None, "", "0", "123", "12345", "12a4", "abcd", " 123", "123 ", "١٢٣٤", 1234, ["1234"], True):
            with self.subTest(codigo=cod):
                self.assertEqual(self.erro(self.novo, codigo=cod), 400)
        corpo = {k: v for k, v in self.BASE.items() if k != "codigo"}
        self.assertEqual(self.msg(self.adm, "pessoa/salvar", corpo), "O código tem exatamente 4 números.")
        for cod in ("0000", "9999", "0123"):
            self.novo(codigo=cod)
            self.assertEqual(api._hash(cod, self.disco()["pessoas"][-1]["sal"]), self.disco()["pessoas"][-1]["hash"])

    def test_codigo_nunca_vai_em_claro_nem_para_a_vista(self):
        v = self.novo(codigo="8421")
        gravado = (self.dir / "demandas.json").read_text(encoding="utf-8")
        self.assertNotIn("8421", gravado)
        for vista in (v, self.get(), self.pes(self.tk_c, "vista"), self.get("", OP)):
            texto = json.dumps(vista)
            self.assertNotIn('"hash"', texto)
            self.assertNotIn('"sal"', texto)
            self.assertNotIn("8421", texto)

    def test_codigo_igual_gera_hash_diferente_por_sal(self):
        self.novo(codigo="5555")
        self.novo(codigo="5555", nome="Ze2")
        a, b = self.disco()["pessoas"][-2:]
        self.assertNotEqual((a["sal"], a["hash"]), (b["sal"], b["hash"]))

    def test_known_bug_codigo_com_quebra_de_linha_no_fim_passa(self):
        """known-bug QA-ADM-02: CODE_RE usa ^...$ com match(): "1234\\n" passa como código de 4 números."""
        self.assertEqual(self.erro(self.novo, codigo="1234\n"), 400)

    def test_setor_do_novo(self):
        for setor in ("ZZ", "", None, 3, ["CNC"], "cnc"):
            with self.subTest(setor=setor):
                self.assertEqual(self.erro(self.novo, setor=setor), 400)
        self.assertEqual(self.msg(self.novo, setor="ZZ"), "Setor inválido.")
        self.adm("setor/ativar", {"id": "ESP", "rev": self.s("ESP")["_rv"]})
        self.assertEqual(self.erro(self.novo, setor="ESP"), 400)       # inativo não recebe pessoa nova

    def test_email(self):
        self.novo(email="  Ze@Empresa.COM ")
        self.assertEqual(self.disco()["pessoas"][-1]["email"], "ze@empresa.com")
        self.novo(email=email_de(254), nome="Ze3")
        self.assertEqual(len(self.disco()["pessoas"][-1]["email"]), 254)
        self.assertEqual(self.erro(self.novo, email=email_de(255)), 400)
        for e in ("x", "a@b", "a b@c.com", "a@b.com\nBcc: x@y.com", 1):
            with self.subTest(email=e):
                self.assertEqual(self.erro(self.novo, email=e), 400)
        self.novo(email="", nome="Sem email")
        self.assertNotIn("email", self.disco()["pessoas"][-1])

    def test_rev_do_pedido_e_modo(self):
        for rev in ("0", None, False, 0.5):
            with self.subTest(rev=rev):
                self.assertEqual(self.erro(self.novo, rev=rev), 400)
        for modo in (None, "", "NOVO", "x", 0):
            with self.subTest(modo=modo):
                self.assertEqual(self.erro(self.novo, modo=modo), 400)

    def test_limite_de_pessoas(self):
        with mock.patch.dict(ds.MAX, {"pessoas": 5}):
            self.novo()
            self.assertEqual(self.msg(self.novo, nome="Mais um"), "Limite de pessoas atingido.")

    def test_so_o_adm(self):
        for tk in (self.tk_c, self.tk_h):
            self.assertEqual(self.erro(self.pes, tk, "pessoa/salvar", dict(self.BASE)), 403)
        self.assertEqual(self.erro(self.adm, "pessoa/salvar", dict(self.BASE), OP), 403)
        self.assertEqual(self.erro(self.adm, "pessoa/salvar", dict(self.BASE), {}), 403)
        self.assertEqual(len(self.disco()["pessoas"]), 4)
        self.novo()                          # ADM da máquina
        self.adm("pessoa/salvar", dict(self.BASE, nome="Ze Dois"), COMPLETO)
        self.assertEqual(len(self.disco()["pessoas"]), 6)


class PessoaEditar(Base):
    def ed(self, pid=None, **kw):
        pid = pid or self.bruno
        return self.adm("pessoa/salvar", dict({"modo": "editar", "id": pid, "nome": "Bruno", "setor": "CNC",
                                              "rev": self.p(pid)["_rv"]}, **kw))

    def test_nome_e_email_sem_mexer_no_codigo(self):
        h = self.p(self.bruno)["hash"]
        self.ed(nome="Bruno S.", email="b@x.com")
        p = self.p(self.bruno)
        self.assertEqual((p["nome"], p["email"], p["hash"], p["mat"]), ("Bruno S.", "b@x.com", h, "M102"))
        self.ed(email="")
        self.assertNotIn("email", self.p(self.bruno))
        for ruim in ({"nome": "B"}, {"nome": "x" * 61}, {"email": "x"}, {"nome": 5}):
            with self.subTest(ruim=ruim):
                self.assertEqual(self.erro(self.ed, **ruim), 400)

    def test_codigo_vazio_ou_ausente_mantem_e_novo_codigo_troca(self):
        h = self.p(self.bruno)["hash"]
        self.ed(codigo="")
        self.ed(codigo=None)
        self.ed()
        self.assertEqual(self.p(self.bruno)["hash"], h)
        for ruim in ("1", "12345", "abcd", 1234, "12 4"):
            with self.subTest(codigo=ruim):
                self.assertEqual(self.erro(self.ed, codigo=ruim), 400)
        tk = self.entrar(self.bruno, "3333")
        self.ed(codigo="0007")
        self.assertEqual(self.erro(self.pes, tk, "vista"), 401)           # o código novo derruba quem estava entrado
        self.assertEqual(self.erro(self.entrar, self.bruno, "3333"), 403)
        self.entrar(self.bruno, "0007")

    def test_trocar_codigo_zera_bloqueio(self):
        api._FAILS[self.bruno] = [4, 0.0, 0]
        self.ed(codigo="1212")
        self.assertNotIn(self.bruno, api._FAILS)

    def test_rev_404_e_id(self):
        self.assertEqual(self.erro(self.adm, "pessoa/salvar", {"modo": "editar", "id": self.bruno, "nome": "Bruno",
                                                              "setor": "CNC", "rev": self.p(self.bruno)["_rv"] - 1}), 409)
        for pid in ("p99", None, "", 2, ["p2"]):
            with self.subTest(id=pid):
                self.assertEqual(self.erro(self.adm, "pessoa/salvar", {"modo": "editar", "id": pid, "nome": "Bruno",
                                                                      "setor": "CNC", "rev": 0}), 404)

    def test_transferir_para_setor_ativo_inativo_e_inexistente(self):
        for setor in ("ZZ", "", None, 3):
            with self.subTest(setor=setor):
                self.assertEqual(self.erro(self.ed, setor=setor), 400)
        self.adm("setor/ativar", {"id": "ESP", "rev": self.s("ESP")["_rv"]})
        self.assertEqual(self.erro(self.ed, setor="ESP"), 400)
        self.assertEqual(self.p(self.bruno)["setor"], "CNC")
        self.ed(setor="PCP")
        self.assertEqual(self.p(self.bruno)["setor"], "PCP")

    def test_pessoa_de_setor_inativo_pode_ser_editada_sem_trocar_de_setor(self):
        self.adm("setor/ativar", {"id": "ESP", "rev": self.s("ESP")["_rv"]})
        self.ed(self.fer, nome="Fernanda B.", setor="ESP")
        self.assertEqual(self.p(self.fer)["nome"], "Fernanda B.")

    def test_transferir_devolve_so_as_ativas_dela_para_a_fila_do_setor_antigo(self):
        a = self.nova(para={"s": "CNC", "p": self.bruno})
        self.pes(self.entrar(self.bruno, "3333"), "demanda/aceitar", {"id": a["id"]})
        self.ed(setor="ESP")
        d = self.dem(a["id"])
        self.assertEqual((d["status"], d["para"], d["iniciado"]), ("new", {"s": "CNC", "p": None}, None))

    def test_so_o_adm(self):
        corpo = {"modo": "editar", "id": self.bruno, "nome": "Bruno", "setor": "CNC", "rev": self.p(self.bruno)["_rv"]}
        self.assertEqual(self.erro(self.pes, self.tk_c, "pessoa/salvar", corpo), 403)
        self.assertEqual(self.erro(self.adm, "pessoa/salvar", corpo, OP), 403)


class PessoaAtivar(Base):
    def rv(self, pid):
        return self.p(pid)["_rv"]

    def test_desativar_devolve_ativas_a_fila_e_revoga_token(self):
        tk = self.entrar(self.bruno, "3333")
        a = self.nova(para={"s": "CNC", "p": self.bruno})
        b = self.nova(para={"s": "CNC", "p": self.bruno}, titulo="Segunda demanda")
        self.pes(tk, "demanda/aceitar", {"id": b["id"]})
        self.pes(tk, "demanda/pausar", {"id": b["id"], "motivo": "Máquina parada"})
        c = self.nova(para={"s": "CNC", "p": self.bruno}, titulo="Terceira demanda")
        self.pes(tk, "demanda/aceitar", {"id": c["id"]})
        self.pes(tk, "demanda/concluir", {"id": c["id"]})
        self.adm("pessoa/ativar", {"id": self.bruno, "rev": self.rv(self.bruno)})
        self.assertFalse(self.p(self.bruno)["ativo"])
        for did in (a["id"], b["id"]):
            d = self.dem(did)
            self.assertEqual((d["status"], d["para"], d["iniciado"]), ("new", {"s": "CNC", "p": None}, None), did)
        self.assertTrue(all(x["fim"] is not None for x in self.dem(b["id"])["pausas"]))   # pausa aberta foi fechada
        self.assertEqual((self.dem(c["id"])["status"], self.dem(c["id"])["para"]["p"]), ("done", self.bruno))  # concluída fica
        self.assertEqual(self.erro(self.pes, tk, "vista"), 401)
        self.assertEqual(self.erro(self.entrar, self.bruno, "3333"), 404)

    def test_so_as_dele_voltam(self):
        d = self.nova(para={"s": "CNC", "p": self.carlos})
        self.adm("pessoa/ativar", {"id": self.bruno, "rev": self.rv(self.bruno)})
        self.assertEqual(self.dem(d["id"])["para"]["p"], self.carlos)

    def test_reativar_volta_a_entrar_mas_nao_recupera_demandas(self):
        d = self.nova(para={"s": "CNC", "p": self.bruno})
        self.adm("pessoa/ativar", {"id": self.bruno, "rev": self.rv(self.bruno)})
        self.adm("pessoa/ativar", {"id": self.bruno, "rev": self.rv(self.bruno)})
        self.assertTrue(self.p(self.bruno)["ativo"])
        self.entrar(self.bruno, "3333")
        self.assertIsNone(self.dem(d["id"])["para"]["p"])

    def test_inativo_nao_e_escolhido_como_responsavel(self):
        self.adm("pessoa/ativar", {"id": self.bruno, "rev": self.rv(self.bruno)})
        self.assertEqual(self.erro(self.nova, para={"s": "CNC", "p": self.bruno}), 400)

    def test_rev_404_e_permissao(self):
        self.assertEqual(self.erro(self.adm, "pessoa/ativar", {"id": self.bruno, "rev": self.rv(self.bruno) - 1}), 409)
        self.assertEqual(self.erro(self.adm, "pessoa/ativar", {"id": "p99", "rev": 0}), 404)
        self.assertEqual(self.erro(self.adm, "pessoa/ativar", {"rev": 0}), 404)
        for rev in (None, "1", True):
            self.assertEqual(self.erro(self.adm, "pessoa/ativar", {"id": self.bruno, "rev": rev}), 400, rev)
        self.assertEqual(self.erro(self.pes, self.tk_c, "pessoa/ativar", {"id": self.bruno, "rev": self.rv(self.bruno)}), 403)
        self.assertEqual(self.erro(self.adm, "pessoa/ativar", {"id": self.bruno, "rev": self.rv(self.bruno)}, OP), 403)
        self.assertTrue(self.p(self.bruno)["ativo"])

    def test_a_pessoa_nao_se_desativa_sozinha(self):
        self.assertEqual(self.erro(self.pes, self.tk_c, "pessoa/ativar", {"id": self.carlos, "rev": self.rv(self.carlos)}), 403)


class PessoaApagar(Base):
    def rv(self, pid):
        return self.p(pid)["_rv"]

    def test_apaga_sem_historico_e_revoga_token(self):
        tk = self.entrar(self.fer, "4444")
        self.adm("pessoa/apagar", {"id": self.fer, "rev": self.rv(self.fer)})
        self.assertNotIn(self.fer, [x["id"] for x in self.disco()["pessoas"]])
        self.assertEqual(self.erro(self.pes, tk, "vista"), 401)

    def test_recusa_historico_como_origem_destino_e_no_arquivo(self):
        self.nova(self.tk_h)                                                    # Helena pediu
        self.nova(para={"s": "CNC", "p": self.carlos})                          # Carlos é destino
        for pid in (self.helena, self.carlos):
            with self.subTest(pid=pid):
                self.assertEqual(self.msg(self.adm, "pessoa/apagar", {"id": pid, "rev": self.rv(pid)}),
                                 "Pessoa com histórico de demandas: desative em vez de excluir.")
        self.arquivo(para={"s": "CNC", "p": self.bruno})
        self.assertEqual(self.erro(self.adm, "pessoa/apagar", {"id": self.bruno, "rev": self.rv(self.bruno)}), 400)
        self.arquivo(de={"s": "ESP", "p": self.fer})
        self.assertEqual(self.erro(self.adm, "pessoa/apagar", {"id": self.fer, "rev": self.rv(self.fer)}), 400)

    def test_historico_cancelado_tambem_conta(self):
        d = self.nova(para={"s": "CNC", "p": self.bruno})
        self.adm("demanda/cancelar", {"id": d["id"]})
        self.assertEqual(self.erro(self.adm, "pessoa/apagar", {"id": self.bruno, "rev": self.rv(self.bruno)}), 400)

    def test_rev_404_e_permissao(self):
        self.assertEqual(self.erro(self.adm, "pessoa/apagar", {"id": self.fer, "rev": self.rv(self.fer) - 1}), 409)
        self.assertEqual(self.erro(self.adm, "pessoa/apagar", {"id": "p99", "rev": 0}), 404)
        self.assertEqual(self.erro(self.adm, "pessoa/apagar", {"id": self.fer}), 400)
        self.assertEqual(self.erro(self.pes, self.tk_c, "pessoa/apagar", {"id": self.fer, "rev": self.rv(self.fer)}), 403)
        self.assertEqual(self.erro(self.adm, "pessoa/apagar", {"id": self.fer, "rev": self.rv(self.fer)}, OP), 403)
        self.assertIn(self.fer, [x["id"] for x in self.disco()["pessoas"]])


class AdminLeituras(Base):
    def test_vista_do_adm_traz_setores_inativos_e_pessoas_com_matricula(self):
        self.adm("setor/ativar", {"id": "ESP", "rev": self.s("ESP")["_rv"]})
        v = self.get()
        self.assertEqual([x["ativo"] for x in v["setores"]], [True, True, False])
        self.assertEqual([x["mat"] for x in v["pessoas"]][:2], ["M100", "M101"])

    def test_lista_publica_do_operador_so_tem_ativos_sem_email_nem_segredo(self):
        self.adm("setor/salvar", {"modo": "editar", "id": "CNC", "nome": "Corte", "icone": "🔩", "cor": "#0EA5E9",
                                  "email": "corte@empresa.com", "rev": self.s("CNC")["_rv"]})
        self.adm("pessoa/ativar", {"id": self.bruno, "rev": self.p(self.bruno)["_rv"]})
        self.adm("setor/ativar", {"id": "ESP", "rev": self.s("ESP")["_rv"]})
        pub = self.get("", OP)
        self.assertEqual(sorted(x["id"] for x in pub["setores"]), ["CNC", "PCP"])
        self.assertNotIn(self.bruno, [x["id"] for x in pub["pessoas"]])
        texto = json.dumps(pub)
        for segredo in ("corte@empresa.com", "hash", '"sal"'):
            self.assertNotIn(segredo, texto, segredo)

    def test_pessoa_nao_ve_email_de_ninguem(self):
        self.adm("pessoa/salvar", {"modo": "editar", "id": self.carlos, "nome": "Carlos", "setor": "CNC",
                                   "email": "carlos@empresa.com", "rev": self.p(self.carlos)["_rv"]})
        self.assertNotIn("carlos@empresa.com", json.dumps(self.pes(self.tk_h, "vista")))
        self.assertIn("carlos@empresa.com", json.dumps(self.get()))


# =============================================================================================== expediente
def grade(dias=(1, 2, 3, 4, 5), turnos=(("07:00", "12:00"), ("13:00", "17:00"))):
    return {"dias": list(dias), "turnos": [list(t) for t in turnos]}


class Expediente(Base):
    def agenda(self, **kw):
        base = self.disco()["agenda"]
        return {**base, **kw}

    def salva(self, ctx=ADM, **kw):
        return self.adm("agenda/salvar", {"agenda": self.agenda(**kw)}, ctx)

    def liga(self, **kw):
        return self.salva(ativa=True, **kw)

    def v(self):
        return self.disco()["agenda"]["v"]

    # --- ligar / desligar / dias ---
    def test_de_fabrica(self):
        a = self.disco()["agenda"]
        self.assertEqual((a["ativa"], a["v"], a["padrao"]["dias"], a["padrao"]["turnos"], a["setores"], a["feriados"]),
                         (False, 0, [1, 2, 3, 4, 5], [["07:00", "12:00"], ["13:00", "17:00"]], {}, []))

    def test_ligar_e_desligar_gastam_versao(self):
        self.liga()
        self.assertEqual((self.v(), self.disco()["agenda"]["ativa"]), (1, True))
        self.salva(ativa=False)
        self.assertEqual((self.v(), self.disco()["agenda"]["ativa"]), (2, False))
        self.assertEqual(sorted(self.disco()["agendas"]), ["2"])

    def test_ativa_precisa_ser_booleano(self):
        for ativa in ("sim", 1, 0, None, [], "true"):
            with self.subTest(ativa=ativa):
                self.assertEqual(self.msg(self.salva, ativa=ativa), "Informe se o horário de serviço está ligado.")
        corpo = self.agenda()
        del corpo["ativa"]
        self.assertEqual(self.erro(self.adm, "agenda/salvar", {"agenda": corpo}), 400)

    def test_dias_validos_ordenados_e_sem_repeticao(self):
        self.liga(padrao=grade(dias=(7, 1, 1, 3, 5, 3)))
        self.assertEqual(self.disco()["agenda"]["padrao"]["dias"], [1, 3, 5, 7])

    def test_dias_invalidos(self):
        for dias in ([0], [8], [-1], ["1"], [True], [1.0], [None], "12345", None, 1, {"1": 1}):
            with self.subTest(dias=dias):
                self.assertEqual(self.msg(self.liga, padrao={"dias": dias, "turnos": [["07:00", "17:00"]]}),
                                 "Horário padrão: dias da semana inválidos.")
        self.assertEqual(self.msg(self.liga, padrao={"turnos": [["07:00", "17:00"]]}), "Horário padrão: dias da semana inválidos.")

    def test_dia_unico_e_sete_dias_valem(self):
        self.liga(padrao=grade(dias=(1,)))
        self.liga(padrao=grade(dias=(1, 2, 3, 4, 5, 6, 7)))
        self.assertEqual(self.disco()["agenda"]["padrao"]["dias"], [1, 2, 3, 4, 5, 6, 7])

    def test_padrao_ausente_ou_do_tipo_errado(self):
        for padrao in (None, "x", [], 5):
            with self.subTest(padrao=padrao):
                self.assertEqual(self.msg(self.liga, padrao=padrao), "Horário padrão: horário inválido.")

    # --- turnos ---
    def test_hhmm_validos_e_invalidos(self):
        for ini, fim in (("00:00", "23:59"), ("07:00", "07:01"), ("23:59", "00:00"), ("00:00", "00:01")):
            with self.subTest(ini=ini, fim=fim):
                self.salva(ativa=False, padrao=grade(turnos=((ini, fim),)))   # desligado: o mínimo de 15 min não vale
        for ruim in ("24:00", "7:00", "07:60", "07:5", "7:5", "0700", "07-00", "", " 07:00", "07:00 ", "07:00:00", "ab:cd", "-1:00",
                     "07:00\x00", None, 700, 7.0, ["07:00"], True):
            with self.subTest(hhmm=ruim):
                self.assertEqual(self.msg(self.liga, padrao=grade(turnos=((ruim, "17:00"),))),
                                 "Horário padrão: horário do turno inválido (use HH:MM).")
                self.assertEqual(self.erro(self.liga, padrao=grade(turnos=((("07:00"), ruim),))), 400)

    def test_known_bug_hhmm_com_quebra_de_linha_no_fim_passa(self):
        """known-bug QA-ADM-02: HHMM_RE usa ^...$ com match(): "07:00\\n" é aceito e gravado com a quebra."""
        self.assertEqual(self.erro(self.liga, padrao=grade(turnos=(("07:00\n", "17:00"),))), 400)

    def test_turno_com_formato_errado(self):
        for turno in ([], ["07:00"], ["07:00", "08:00", "09:00"], "07:00-08:00", None, {"ini": "07:00", "fim": "08:00"}):
            with self.subTest(turno=turno):
                self.assertEqual(self.erro(self.liga, padrao={"dias": [1], "turnos": [turno]}), 400)
        self.assertEqual(self.erro(self.liga, padrao={"dias": [1], "turnos": "x"}), 400)
        self.assertEqual(self.erro(self.liga, padrao={"dias": [1]}), 400)

    def test_inicio_igual_ao_fim(self):
        self.assertEqual(self.msg(self.liga, padrao=grade(turnos=(("07:00", "07:00"),))),
                         "Horário padrão: o turno não pode começar e terminar na mesma hora.")
        self.assertEqual(self.erro(self.liga, padrao=grade(turnos=(("00:00", "00:00"),))), 400)

    def test_limite_de_6_turnos(self):
        seis = tuple(("%02d:00" % (2 * i), "%02d:30" % (2 * i)) for i in range(6))
        self.liga(padrao=grade(turnos=seis))
        self.assertEqual(len(self.disco()["agenda"]["padrao"]["turnos"]), 6)
        sete = seis + (("12:00", "12:30"),)
        self.assertEqual(self.msg(self.liga, padrao=grade(turnos=sete)), "Horário padrão: no máximo 6 turnos.")
        self.assertEqual(len(self.disco()["agenda"]["padrao"]["turnos"]), 6)

    def test_turnos_sao_gravados_em_ordem(self):
        self.liga(padrao=grade(turnos=(("13:00", "17:00"), ("07:00", "12:00"))))
        self.assertEqual(self.disco()["agenda"]["padrao"]["turnos"], [["07:00", "12:00"], ["13:00", "17:00"]])

    def test_sobreposicao(self):
        self.liga(padrao=grade(turnos=(("07:00", "12:00"), ("12:00", "17:00"))))        # encostar não é sobrepor
        for t in ((("07:00", "12:00"), ("11:59", "17:00")), (("07:00", "17:00"), ("08:00", "09:00")),
                  (("07:00", "12:00"), ("07:00", "12:00")), (("07:00", "12:00"), ("06:00", "07:01"))):
            with self.subTest(t=t):
                self.assertEqual(self.msg(self.liga, padrao=grade(turnos=t)), "Horário padrão: dois turnos se sobrepõem.")

    def test_virada_de_noite(self):
        self.liga(padrao=grade(dias=(1, 2, 3, 4, 5), turnos=(("22:00", "06:00"),)))
        self.liga(padrao=grade(dias=(1, 2, 3, 4, 5, 6, 7), turnos=(("22:00", "06:00"),)))      # 06:00 do outro dia, sem choque
        self.assertEqual(self.erro(self.liga, padrao=grade(turnos=(("22:00", "06:00"), ("05:59", "08:00")))), 400)
        self.assertEqual(self.erro(self.liga, padrao=grade(turnos=(("22:00", "06:00"), ("23:00", "23:30")))), 400)
        self.liga(padrao=grade(turnos=(("22:00", "06:00"), ("06:00", "08:00"))))                 # encostam em 06:00
        self.assertEqual(self.erro(self.liga, padrao=grade(turnos=(("22:00", "23:00"), ("23:00", "22:01")))), 400)  # passa 1 min de 22:00

    def test_virada_de_noite_vence_dia_com_turno_de_dia_seguinte(self):
        # sexta 20:00 → sábado 04:00 e sábado 03:00: só dá choque se o sábado estiver nos dias
        self.liga(padrao=grade(dias=(1, 2, 3, 4, 5), turnos=(("20:00", "04:00"),)))
        self.assertEqual(self.erro(self.liga, padrao=grade(dias=(5, 6), turnos=(("20:00", "04:00"), ("03:00", "05:00")))), 400)

    def test_semana_circular_domingo_para_segunda(self):
        ruim = grade(dias=(7, 1), turnos=(("22:00", "06:00"), ("05:00", "08:00")))
        self.assertEqual(self.msg(self.liga, padrao=ruim), "Horário padrão: dois turnos se sobrepõem.")
        self.liga(padrao=grade(dias=(7, 1), turnos=(("22:00", "06:00"), ("06:00", "08:00"))))   # encosta: vale
        self.liga(padrao=grade(dias=(7,), turnos=(("22:00", "06:00"),)))                         # domingo à noite → segunda 06:00

    def test_minimo_de_15_minutos_por_semana(self):
        self.assertEqual(self.msg(self.liga, padrao=grade(dias=(1,), turnos=(("07:00", "07:14"),))),
                         "Horário padrão: precisa de ao menos 15 minutos de trabalho por semana.")
        self.liga(padrao=grade(dias=(1,), turnos=(("07:00", "07:15"),)))
        self.liga(padrao=grade(dias=(1, 2, 3), turnos=(("07:00", "07:05"),)))                   # 3 × 5 = 15
        self.assertEqual(self.erro(self.liga, padrao=grade(dias=(1, 2), turnos=(("07:00", "07:05"),))), 400)
        self.assertEqual(self.erro(self.liga, padrao=grade(dias=(), turnos=(("07:00", "17:00"),))), 400)
        self.assertEqual(self.erro(self.liga, padrao=grade(dias=(1,), turnos=())), 400)
        self.assertEqual(self.erro(self.liga, padrao=grade(dias=(), turnos=())), 400)

    def test_o_minimo_so_vale_com_o_horario_ligado(self):
        self.salva(ativa=False, padrao=grade(dias=(), turnos=()))
        self.assertEqual(self.disco()["agenda"]["padrao"], {"dias": [], "turnos": []})
        self.assertEqual(self.erro(self.liga, padrao=grade(dias=(), turnos=())), 400)

    def test_regras_de_formato_valem_com_o_horario_desligado(self):
        self.assertEqual(self.erro(self.salva, ativa=False, padrao=grade(turnos=(("07:00", "07:00"),))), 400)
        self.assertEqual(self.erro(self.salva, ativa=False, padrao=grade(turnos=(("07:00", "12:00"), ("11:00", "13:00")))), 400)

    # --- por setor ---
    def test_horario_proprio_do_setor(self):
        self.liga(setores={"CNC": grade(dias=(6,), turnos=(("06:00", "10:00"),))})
        self.assertEqual(self.disco()["agenda"]["setores"], {"CNC": {"dias": [6], "turnos": [["06:00", "10:00"]]}})
        self.liga(setores={})                    # desmarcar "horário próprio" remove a exceção
        self.assertEqual(self.disco()["agenda"]["setores"], {})

    def test_horario_do_setor_segue_as_mesmas_regras(self):
        for g, trecho in ((grade(dias=(1,), turnos=(("07:00", "07:10"),)), "Setor CNC: precisa de ao menos 15"),
                          (grade(turnos=(("07:00", "07:00"),)), "Setor CNC: o turno não pode"),
                          (grade(turnos=(("07:00", "12:00"), ("11:00", "13:00"))), "Setor CNC: dois turnos se sobrepõem"),
                          (grade(dias=(9,)), "Setor CNC: dias da semana inválidos"),
                          (grade(turnos=tuple(("%02d:00" % (2 * i), "%02d:30" % (2 * i)) for i in range(7))), "Setor CNC: no máximo 6"),
                          ("x", "Setor CNC: horário inválido")):
            with self.subTest(trecho=trecho):
                self.assertIn(trecho, self.msg(self.liga, setores={"CNC": g}))

    def test_setor_da_excecao(self):
        g = grade(dias=(6,), turnos=(("06:00", "10:00"),))
        for sid in ("ZZ", "cnc", "", "CNCX", "CN\n", 5):
            with self.subTest(sid=sid):
                self.assertEqual(self.msg(self.liga, setores={sid: g}), "Setor inválido no horário por setor.")
        for exc in ([], "x", 5):
            with self.subTest(exc=exc):
                self.assertEqual(self.msg(self.liga, setores=exc), "Horários por setor inválidos.")
        self.liga(setores={"PCP": g, "CNC": g, "ESP": g})
        self.assertEqual(sorted(self.disco()["agenda"]["setores"]), ["CNC", "ESP", "PCP"])

    def test_setor_inativo_pode_ter_horario(self):
        self.adm("setor/ativar", {"id": "ESP", "rev": self.s("ESP")["_rv"]})
        self.liga(setores={"ESP": grade(dias=(6,), turnos=(("06:00", "10:00"),))})
        self.assertIn("ESP", self.disco()["agenda"]["setores"])

    def test_setores_nulo_equivale_a_vazio(self):
        self.liga(setores=None)
        self.assertEqual(self.disco()["agenda"]["setores"], {})

    # --- feriados ---
    def feriado(self, data="2026-12-25", nome="Natal", setores=()):
        return {"data": data, "nome": nome, "setores": list(setores)}

    def test_feriado_valido_ordenado_e_normalizado(self):
        self.liga(feriados=[self.feriado("2026-12-25", "  Natal  "), self.feriado("2026-01-01", "Ano Novo"),
                            self.feriado("2026-12-25", "Natal CNC", ["CNC"])])
        f = self.disco()["agenda"]["feriados"]
        self.assertEqual([(x["data"], x["nome"], x["setores"]) for x in f],
                         [("2026-01-01", "Ano Novo", []), ("2026-12-25", "Natal", []), ("2026-12-25", "Natal CNC", ["CNC"])])

    def test_data_do_feriado(self):
        for ok in ("2028-02-29", "2026-01-01", "2026-12-31", "0001-01-01", "9999-12-31"):
            with self.subTest(ok=ok):
                self.liga(feriados=[self.feriado(ok)])
        for ruim in ("2027-02-29", "2026-02-30", "2026-13-01", "2026-00-10", "2026-04-31", "2026-1-1", "26-01-01", "2026/01/01",
                     "2026-01-01\n", "2026-01-01T00:00", "", " 2026-01-01", "ontem", None, 20261225, ["2026-12-25"], "0000-01-01"):
            with self.subTest(ruim=ruim):
                self.assertEqual(self.erro(self.liga, feriados=[self.feriado(ruim)]), 400)
        self.assertIn("Data de feriado inválida: 2026-02-30.", self.msg(self.liga, feriados=[self.feriado("2026-02-30")]))
        self.assertEqual(self.msg(self.liga, feriados=[{"nome": "x"}]), "Data de feriado inválida.")

    def test_nome_do_feriado_limite_60(self):
        self.liga(feriados=[self.feriado(nome="x" * 60)])
        self.assertEqual(len(self.disco()["agenda"]["feriados"][0]["nome"]), 60)
        self.assertEqual(self.msg(self.liga, feriados=[self.feriado("2026-12-26", "x" * 61)]),
                         "Nome de feriado com mais de 60 letras.")
        self.liga(feriados=[self.feriado("2026-12-27", "  " + "y" * 60 + "  ")])      # 60 depois do strip
        self.assertEqual(self.disco()["agenda"]["feriados"][0]["nome"], "y" * 60)
        self.liga(feriados=[self.feriado("2026-12-28", "")])
        self.assertEqual(self.disco()["agenda"]["feriados"][0]["nome"], "")
        self.liga(feriados=[{"data": "2026-12-29", "setores": []}])             # sem nome
        self.assertEqual(self.disco()["agenda"]["feriados"][0]["nome"], "")
        for nome in (None, 5, ["Natal"], {}):
            with self.subTest(nome=nome):
                self.assertEqual(self.erro(self.liga, feriados=[self.feriado("2026-12-30", nome)]), 400)

    def test_known_bug_nome_do_feriado_aceita_caractere_de_controle(self):
        """known-bug QA-ADM-04: todos os outros textos recusam \\x00-\\x1f; o nome do feriado grava "Natal\\n\\x00"."""
        self.assertEqual(self.erro(self.liga, feriados=[self.feriado(nome="Na\nta\x00l")]), 400)

    def test_feriado_por_setor_e_para_todos(self):
        self.liga(feriados=[self.feriado(setores=["CNC"]), self.feriado("2026-12-26", "X", ["ESP", "CNC"]), self.feriado("2026-12-27")])
        por_data = {x["data"]: x["setores"] for x in self.disco()["agenda"]["feriados"]}
        self.assertEqual(por_data, {"2026-12-25": ["CNC"], "2026-12-26": ["CNC", "ESP"], "2026-12-27": []})
        for ss in (["ZZ"], ["cnc"], [5], "CNC", None, ["CNC", "ZZ"], [None], [["CNC"]]):
            with self.subTest(ss=ss):
                self.assertEqual(self.erro(self.liga, feriados=[{"data": "2026-12-25", "nome": "x", "setores": ss}]), 400)
        self.assertEqual(self.msg(self.liga, feriados=[self.feriado(setores=["ZZ"])]), "Setor inválido no feriado de 2026-12-25.")

    def test_feriado_duplicado(self):
        self.assertEqual(self.msg(self.liga, feriados=[self.feriado(), self.feriado(nome="Outro nome")]), "Feriado repetido em 2026-12-25.")
        self.assertEqual(self.erro(self.liga, feriados=[self.feriado(setores=["CNC"]), self.feriado(setores=["CNC"])]), 400)
        self.assertEqual(self.erro(self.liga, feriados=[self.feriado(setores=["CNC", "ESP"]), self.feriado(setores=["ESP", "CNC"])]), 400)
        self.assertEqual(self.erro(self.liga, feriados=[self.feriado(setores=["CNC", "CNC"]), self.feriado(setores=["CNC"])]), 400)
        self.liga(feriados=[self.feriado(), self.feriado(setores=["CNC"]), self.feriado(setores=["ESP"])])   # chaves diferentes: vale
        self.assertEqual(len(self.disco()["agenda"]["feriados"]), 3)

    def test_limite_de_400_feriados(self):
        dia0 = datetime.date(2026, 1, 1)
        mais = lambda n: [self.feriado((dia0 + datetime.timedelta(days=i)).isoformat(), "f") for i in range(n)]  # noqa: E731
        self.liga(feriados=mais(400))
        self.assertEqual(len(self.disco()["agenda"]["feriados"]), 400)
        self.assertEqual(self.msg(self.liga, feriados=mais(401)), "No máximo 400 feriados.")
        self.assertEqual(len(self.disco()["agenda"]["feriados"]), 400)
        for f in ("x", 5, {}, [None], [5], ["2026-12-25"], [[]]):
            with self.subTest(f=f):
                self.assertEqual(self.erro(self.liga, feriados=f), 400)

    def test_feriados_nulo_equivale_a_vazio(self):
        self.liga(feriados=None)
        self.assertEqual(self.disco()["agenda"]["feriados"], [])

    # --- versão ---
    def test_versao_sobe_de_um_em_um(self):
        for i in range(1, 5):
            self.liga(feriados=[self.feriado("2026-12-%02d" % i)])
            self.assertEqual(self.v(), i)

    def test_versao_atrasada_ou_adiantada_e_409(self):
        self.liga()
        self.liga(feriados=[self.feriado()])
        for v in (0, 1, 3, 99, -1):
            with self.subTest(v=v):
                self.assertEqual(self.msg(self.salva, v=v, feriados=[self.feriado("2026-01-01")]),
                                 "Outro aparelho alterou o horário de serviço. Recarregue e confira antes de salvar.")
        self.assertEqual(self.v(), 2)

    def test_versao_ausente_ou_de_tipo_errado_conta_como_zero(self):
        self.liga()
        corpo = self.agenda(feriados=[self.feriado()])
        for v in ("1", None, True, 1.0, [1]):
            with self.subTest(v=v):
                self.assertEqual(self.erro(self.adm, "agenda/salvar", {"agenda": dict(corpo, v=v)}), 409)
        sem = dict(corpo)
        del sem["v"]
        self.assertEqual(self.erro(self.adm, "agenda/salvar", {"agenda": sem}), 409)

    def test_invalido_vence_a_versao_velha(self):
        self.liga()
        self.assertEqual(self.erro(self.salva, v=0, padrao=grade(turnos=(("07:00", "07:00"),))), 400)

    def test_nada_mudou_nao_gasta_versao_nem_grava(self):
        self.liga(feriados=[self.feriado(), self.feriado("2026-01-01", "Ano")])
        r, v = self.rev(), self.v()
        # mesma coisa em outra ordem, com espaços e dias repetidos
        self.salva(feriados=[self.feriado("2026-01-01", " Ano "), self.feriado("2026-12-25", "Natal")],
                   padrao=grade(dias=(5, 4, 3, 2, 1, 1), turnos=(("13:00", "17:00"), ("07:00", "12:00"))))
        self.assertEqual((self.rev(), self.v()), (r, v))
        self.assertEqual(sorted(self.disco()["agendas"]), [str(v)])
        self.liga(feriados=[self.feriado("2026-01-01", "Ano novo"), self.feriado("2026-12-25", "Natal")])
        self.assertEqual((self.rev(), self.v()), (r + 1, v + 1))

    def test_nada_mudou_devolve_a_vista_normal(self):
        self.liga()
        v = self.salva(ativa=True)
        self.assertEqual(v["agenda"]["v"], 1)

    # --- poda de agendas ---
    def test_poda_mantem_a_versao_das_ativas_e_a_vigente(self):
        self.liga()
        d1 = self.nova(est=60)["id"]                                                   # versão 1
        self.liga(feriados=[self.feriado("2026-12-01")])                                   # 2: ninguém
        d3 = self.nova(est=60, titulo="Terceira demanda")["id"]                        # criada na 2
        self.liga(feriados=[self.feriado("2026-12-02")])                                   # 3
        self.assertEqual(sorted(self.disco()["agendas"]), ["1", "2", "3"])
        self.assertEqual((self.dem(d1)["agenda_v"], self.dem(d3)["agenda_v"]), (1, 2))
        self.adm("demanda/cancelar", {"id": d1})
        self.liga(feriados=[self.feriado("2026-12-03")])                                   # 4: a 1 saiu, a 2 ainda tem ativa
        self.assertEqual(sorted(self.disco()["agendas"]), ["2", "4"])
        self.adm("demanda/cancelar", {"id": d3})
        self.liga(feriados=[self.feriado("2026-12-04")])
        self.assertEqual(sorted(self.disco()["agendas"]), ["5"])

    def test_poda_limite_de_versoes(self):
        with mock.patch.dict(ds.MAX, {"versoes": 3}):
            for i in range(1, 6):
                self.liga(feriados=[self.feriado("2026-12-%02d" % i)])
                self.nova(est=60, titulo="Demanda %d de teste" % i)
            # todas as cinco demandas seguem ativas: nenhuma versão em uso some, mesmo acima do teto de 3
            self.assertEqual(sorted(self.disco()["agendas"], key=int), ["1", "2", "3", "4", "5"])
            self.assertEqual(self.disco()["agenda"]["v"], 5)

    def test_copia_da_versao_e_igual_a_vigente(self):
        self.liga(feriados=[self.feriado()], setores={"CNC": grade(dias=(6,), turnos=(("06:00", "10:00"),))})
        doc = self.disco()
        self.assertEqual(doc["agendas"][str(doc["agenda"]["v"])], doc["agenda"])

    # --- permissão ---
    def test_so_o_adm_salva(self):
        corpo = {"agenda": self.agenda(ativa=True)}
        self.assertEqual(self.erro(self.pes, self.tk_c, "agenda/salvar", corpo), 403)
        self.assertEqual(self.erro(self.pes, self.tk_h, "agenda/salvar", corpo), 403)
        self.assertEqual(self.erro(self.adm, "agenda/salvar", corpo, OP), 403)
        self.assertEqual(self.erro(self.adm, "agenda/salvar", corpo, {}), 403)
        self.assertEqual(self.erro(self.pes, "tk-falso", "agenda/salvar", corpo), 401)
        self.assertFalse(self.disco()["agenda"]["ativa"])
        self.assertEqual(self.v(), 0)
        self.adm("agenda/salvar", corpo, COMPLETO)
        self.assertTrue(self.disco()["agenda"]["ativa"])

    def test_corpo_invalido(self):
        for corpo in ({}, {"agenda": None}, {"agenda": "x"}, {"agenda": []}, {"agenda": 5}, {"agenda": {}}):
            with self.subTest(corpo=corpo):
                self.assertEqual(self.erro(self.adm, "agenda/salvar", corpo), 400)
        self.assertEqual(self.msg(self.adm, "agenda/salvar", {"agenda": "x"}), "Horário inválido.")

    def test_todos_veem_a_agenda_na_vista(self):
        self.liga()
        for v in (self.get(), self.pes(self.tk_c, "vista")):
            self.assertTrue(v["agenda"]["ativa"])
            self.assertEqual(v["agenda"]["v"], 1)
        self.assertNotIn("agenda", self.get("", OP))                     # a lista pública do tablet não precisa dela

    def test_known_bug_agenda_fica_com_setor_apagado_e_o_feriado_dele(self):
        """known-bug QA-ADM-01 (outra ponta): o feriado só desse setor continua depois de setor/apagar."""
        self.setor("PIN", "Pintura")
        self.liga(feriados=[self.feriado(setores=["PIN"])])
        self.adm("setor/apagar", {"id": "PIN", "rev": self.s("PIN")["_rv"]})
        self.assertEqual([f for f in self.disco()["agenda"]["feriados"] if "PIN" in f["setores"]], [])


if __name__ == "__main__":
    unittest.main()
