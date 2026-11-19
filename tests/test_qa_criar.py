"""QA da "Nova solicitação": a rota demanda/criar (api._criar) campo a campo, pelo api.handle e pelo HTTP de verdade.

Cada campo: válido, inválido, vazio, limite exato e um além, tipo errado e permissão. A matriz com o resultado de cada
caso e o que a tela faz está em docs/qa/criar.md; o formulário (jsdom) está em tests/check_criar.js.
Teste marcado com expectedFailure expõe um bug CONFIRMADO (ver "Bugs encontrados" no doc): quando for corrigido o
teste passa "inesperadamente" e deve perder a marca.
Dados num diretório temporário (DEMANDAS_DATA) por teste; relógio e pbkdf2 trocados para ficar rápido.
"""

import datetime
import http.client
import importlib.util
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parents[1] / "demandas"
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import demandas_agenda as ag  # noqa: E402
import demandas_store as ds  # noqa: E402

_spec = importlib.util.spec_from_file_location("demandas_api_qa_criar", HERE / "api.py")
api = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(api)
ITER_REAL = api.ITER

MIN = 60000
HORA = 60 * MIN
T0 = 1_800_000_000_000
ADM = {"papel": "maquina"}
COMPLETO = {"papel": "completo"}
OP = {"papel": "operador"}
FALTA = object()   # "o campo nem vai no corpo"
CASOS = [0]        # quantos casos (válido/inválido/limite/permissão) rodaram


def tearDownModule():
    print("\n[qa criar] casos executados: %d" % CASOS[0], file=sys.stderr)


def loc(a, m, d, h=0, mi=0):
    return int(datetime.datetime(a, m, d, h, mi).timestamp() * 1000)


SEXTA_1630 = loc(2026, 11, 13, 16, 30)
SEG_0730 = loc(2026, 11, 16, 7, 30)


class Base(unittest.TestCase):
    def setUp(self):
        self._data = os.environ.get("DEMANDAS_DATA")
        self.dir = Path(tempfile.mkdtemp(prefix="dem-qa-criar-"))
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

    def pes(self, tk, rest, body=None, ctx=OP):
        return api.handle("POST", rest, dict(body or {}, tk=tk), ctx)

    def erro(self, fn, *a, **kw):
        with self.assertRaises(api.ApiError) as c:
            fn(*a, **kw)
        return c.exception.status, str(c.exception)

    def disco(self, nome="demandas.json"):
        return json.loads((self.dir / nome).read_text(encoding="utf-8"))

    def rev(self):
        return self.disco()["rev"]

    # --- cenário: PCP (Helena), CNC (Carlos, Bruno), ESP (Fernanda) ---
    def setor(self, sid, nome):
        return self.adm("setor/salvar", {"modo": "novo", "id": sid, "nome": nome, "icone": "⚙️", "cor": "#3B82F6", "rev": 0})

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

    def entrar(self, pid, codigo):
        return api.handle("POST", "entrar", {"pessoa": pid, "codigo": codigo}, OP)["tk"]

    # --- criar ---
    def corpo(self, **kw):
        b = {"titulo": "Cortar chapas", "tipo": "dem", "motivo": "Outro", "prio": "norm", "est": 60,
             "para": {"s": "CNC", "p": None}, "desc": "", "de_s": "PCP"}
        b.update(kw)
        return {k: v for k, v in b.items() if v is not FALTA}

    def cria(self, tk=None, ctx=None, **kw):
        """A resposta crua (vista) de demanda/criar. tk=None: ADM; com tk: a pessoa."""
        b = self.corpo(**kw)
        if tk is None:
            return api.handle("POST", "demanda/criar", b, ADM if ctx is None else ctx)
        if "de_s" not in kw:   # a tela da pessoa não manda de_s
            b.pop("de_s")
        return api.handle("POST", "demanda/criar", dict(b, tk=tk), OP if ctx is None else ctx)

    def nova(self, tk=None, **kw):
        v = self.cria(tk, **kw)
        return max(v["demandas"], key=lambda d: int(d["id"][4:]))

    def dem(self, did):
        return next(d for d in self.disco()["demandas"] if d["id"] == did)

    def ndem(self):
        return len(self.disco()["demandas"])

    def aceita(self, tk=None, **kw):
        CASOS[0] += 1
        return self.nova(tk, **kw)

    def rejeita(self, status, trecho="", tk=None, ctx=None, **kw):
        """Recusa com o status e a frase: e nada muda no disco (nem o rev, nem o número, nem os avisos)."""
        CASOS[0] += 1
        antes = self.disco()
        st, m = self.erro(self.cria, tk, ctx, **kw)
        self.assertEqual(st, status, (kw, m))
        self.assertIn(trecho, m, kw)
        self.assertEqual(self.disco(), antes, "recusou mas gravou algo: %r" % (kw,))
        return m


# ======================================================================== título
class Titulo(Base):
    def test_limites_exatos(self):
        self.assertEqual(self.aceita(titulo="abcde")["titulo"], "abcde")           # 5: o mínimo
        self.assertEqual(len(self.aceita(titulo="x" * 140)["titulo"]), 140)        # 140: o máximo
        self.rejeita(400, "Título: de 5 a 140 caracteres.", titulo="abcd")        # 4
        self.rejeita(400, "Título: de 5 a 140 caracteres.", titulo="x" * 141)     # 141

    def test_vazio_nulo_ausente(self):
        for v in ("", "     ", None, FALTA):
            self.rejeita(400, "Título", titulo=v)

    def test_espacos_nas_pontas_nao_contam(self):
        self.assertEqual(self.aceita(titulo="   abcde   ")["titulo"], "abcde")
        self.rejeita(400, "de 5 a 140", titulo="  abcd  ")                         # 4 letras + espaços: ainda curto
        self.assertEqual(self.aceita(titulo=" " + "x" * 140 + " ")["titulo"], "x" * 140)   # 142 crus, 140 úteis
        self.assertEqual(self.aceita(titulo=" abcde ")["titulo"], "abcde")   # espaço sem quebra também
        self.assertEqual(self.aceita(titulo="ab   cd")["titulo"], "ab   cd")       # espaço de dentro fica

    def test_caracteres_de_controle(self):
        for ch in ("\x00", "\x07", "\t", "\n", "\r", "\x1f", "\x7f"):
            self.rejeita(400, "caractere não permitido", titulo="Corte%schapas" % ch)
        self.rejeita(400, "caractere não permitido", titulo="Corte chapas\n")      # controle na ponta: recusa, não corta

    def test_tipos_errados(self):
        for v in (5, 5.5, True, ["abcde"], {"a": "abcde"}):
            self.rejeita(400, "caractere não permitido", titulo=v)

    def test_unicode_conta_pontos_de_codigo(self):
        self.assertEqual(self.aceita(titulo="ção✓é✓ç")["titulo"], "ção✓é✓ç")
        self.aceita(titulo="😀" * 5)
        self.rejeita(400, "de 5 a 140", titulo="😀" * 4)
        self.aceita(titulo="😀" * 140)
        self.rejeita(400, "de 5 a 140", titulo="😀" * 141)

    def test_html_vai_cru_para_o_banco(self):
        # o escape é da tela (esc()); o servidor guarda o que veio, sem alterar
        t = '<img src=x onerror="alert(1)"> & "aspas"'
        self.assertEqual(self.aceita(titulo=t)["titulo"], t)

    def test_known_bug_titulo_so_de_caracteres_invisiveis(self):
        """QA-C-04: cinco U+200B (largura zero) passam como título e a solicitação aparece sem nome na lista."""
        self.rejeita(400, "Título", titulo="​" * 5)


# ============================================================ tipo, motivo, prioridade
class TipoMotivoPrioridade(Base):
    def test_tipos_validos(self):
        for t in api.TIPOS:
            self.assertEqual(self.aceita(tipo=t)["tipo"], t)

    def test_tipo_invalido(self):
        for v in ("", "DEM", "dem ", " dem", "demanda", None, FALTA, 0, ["dem"], True):
            self.rejeita(400, "Tipo inválido.", tipo=v)

    def test_motivos_validos(self):
        for m in api.MOTIVOS:
            self.assertEqual(self.aceita(motivo=m)["motivo"], m)

    def test_motivo_invalido(self):
        import unicodedata
        nfd = unicodedata.normalize("NFD", "Mudança de projeto")   # mesma frase, outra codificação
        for v in ("", "outro", "Outro ", "Qualquer", None, FALTA, 1, ["Outro"], nfd):
            self.rejeita(400, "Motivo inválido.", motivo=v)

    def test_prioridades_validas(self):
        for p in api.PRIO:
            self.assertEqual(self.aceita(prio=p)["prio"], p)

    def test_prioridade_invalida(self):
        for v in ("", "URG", "normal", "max", "baixa", None, FALTA, 1, ["urg"]):
            self.rejeita(400, "Prioridade inv", prio=v)

    def test_known_bug_frase_de_prioridade_no_masculino(self):
        """QA-C-05: a mensagem sai "Prioridade inválido." (deveria concordar: "inválida"). Só se vê por fora da tela."""
        self.assertEqual(self.rejeita(400, "Prioridade", prio="max"), "Prioridade inválida.")


# ================================================================= tempo estipulado
class Tempo(Base):
    def test_atalhos_da_tela(self):
        for est in (30, 60, 120, 240, 480):
            d = self.aceita(est=est)
            self.assertEqual((d["est"], d["prazo"]), (est, T0 + est * MIN))

    def test_limites_exatos(self):
        self.assertEqual(self.aceita(est=1)["prazo"], T0 + MIN)
        self.assertEqual(self.aceita(est=43200)["prazo"], T0 + 43200 * MIN)     # 30 dias corridos
        self.rejeita(400, "Tempo estipulado inválido.", est=0)
        self.rejeita(400, "Tempo estipulado inválido.", est=43201)

    def test_invalidos(self):
        for v in (-1, -43200, 10 ** 18, 1.5, 60.0, float("nan"), float("inf"), "60", "", None, FALTA, True, False, [60], {"m": 60}):
            self.rejeita(400, "Tempo estipulado inválido.", est=v)


# ===================================================================== descrição
class Descricao(Base):
    PADRAO = "Sem descrição adicional."

    def test_vazia_nula_ausente_ou_so_espacos_vira_padrao(self):
        for v in ("", None, FALTA, "   ", "\n\n", "  \n  "):
            self.assertEqual(self.aceita(desc=v)["desc"], self.PADRAO, repr(v))

    def test_limite_exato(self):
        self.assertEqual(len(self.aceita(desc="x" * 2000)["desc"]), 2000)
        self.rejeita(400, "Descrição: de 0 a 2000 caracteres.", desc="x" * 2001)

    def test_espacos_das_pontas_nao_contam_no_limite(self):
        self.assertEqual(len(self.aceita(desc="  " + "x" * 2000 + "  ")["desc"]), 2000)
        self.rejeita(400, "de 0 a 2000", desc="  " + "x" * 2001)

    def test_quebras_de_linha_ficam(self):
        self.assertEqual(self.aceita(desc="linha 1\nlinha 2\n\nlinha 4")["desc"], "linha 1\nlinha 2\n\nlinha 4")
        self.assertEqual(self.aceita(desc="\nlinha\n")["desc"], "linha")           # as das pontas saem (strip)
        self.assertEqual(self.dem(self.aceita(desc="a\nb")["id"])["desc"], "a\nb")

    def test_tab_e_outros_controles_sao_recusados(self):
        for ch in ("\t", "\r", "\x00", "\x07", "\x1b", "\x7f"):
            self.rejeita(400, "Descrição: texto com caractere não permitido.", desc="a%sb" % ch)
        self.rejeita(400, "caractere não permitido", desc="a\r\nb")                # CRLF de arquivo colado

    def test_tipos_errados(self):
        for v in (0, 5, True, ["a"], {"a": 1}):
            self.rejeita(400, "Descrição", desc=v)

    def test_unicode_e_html_guardados_como_vieram(self):
        d = "Ação: 3×4 mm ✓ 😀 <b>x</b>"
        self.assertEqual(self.aceita(desc=d)["desc"], d)


# ========================================================== setor e pessoa responsável
class Destino(Base):
    def test_fila_do_setor_e_pessoa(self):
        for p in (None, "", FALTA):
            para = {"s": "CNC", "p": p} if p is not FALTA else {"s": "CNC"}
            self.assertEqual(self.aceita(para=para)["para"], {"s": "CNC", "p": None}, repr(p))
        self.assertEqual(self.aceita(para={"s": "CNC", "p": self.carlos})["para"], {"s": "CNC", "p": self.carlos})

    def test_para_invalido(self):
        for v in ("CNC", None, FALTA, [], ["CNC"], 5, True):
            self.rejeita(400, "Setor responsável inválido.", para=v)

    def test_setor_invalido(self):
        for s in ("ZZ", "", "cnc", " CNC", None, 5, ["CNC"], {"id": "CNC"}):
            self.rejeita(400, "Setor responsável inválido.", para={"s": s, "p": None})
        self.rejeita(400, "Setor responsável inválido.", para={"p": None})

    def test_setor_inativo(self):
        self.setor("PIN", "Pintura")
        self.adm("setor/ativar", {"id": "PIN", "rev": self.disco()["setores"][-1]["_rv"]})
        self.rejeita(400, "Setor responsável inválido.", para={"s": "PIN", "p": None})
        self.adm("setor/ativar", {"id": "PIN", "rev": self.disco()["setores"][-1]["_rv"]})   # liga de novo
        self.assertEqual(self.aceita(para={"s": "PIN", "p": None})["para"]["s"], "PIN")

    def test_pessoa_de_outro_setor_inexistente_ou_inativa(self):
        for p in (self.fer, "p99", " ", 3, ["x"], {"id": self.carlos}, False):
            self.rejeita(400, "Pessoa responsável inválida.", para={"s": "CNC", "p": p})
        self.adm("pessoa/ativar", {"id": self.bruno, "rev": self.disco()["pessoas"][2]["_rv"]})
        self.rejeita(400, "Pessoa responsável inválida.", para={"s": "CNC", "p": self.bruno})

    def test_pessoa_do_setor_gera_evento_e_aviso_so_para_ela(self):
        d = self.aceita(para={"s": "CNC", "p": self.carlos})
        evs = self.dem(d["id"])["eventos"]
        self.assertEqual([e["ev"] for e in evs], ["created", "assigned"])
        self.assertEqual(evs[1]["nota"], "Responsável: Carlos")
        nota = [n for n in self.disco()["notas"] if n["tipo"] == "new"][-1]
        self.assertEqual((nota["aud"], nota["pid"], nota["dem"]), ("CNC", self.carlos, d["id"]))

    def test_fila_do_setor_avisa_o_setor_todo(self):
        d = self.aceita()
        self.assertEqual([e["ev"] for e in self.dem(d["id"])["eventos"]], ["created"])
        nota = [n for n in self.disco()["notas"] if n["tipo"] == "new"][-1]
        self.assertEqual((nota["aud"], nota["pid"]), ("CNC", None))

    def test_setor_sem_ninguem_aceita_o_pedido(self):
        self.setor("ALM", "Almoxarifado")
        self.assertEqual(self.aceita(para={"s": "ALM", "p": None})["para"], {"s": "ALM", "p": None})


# ============================================================ solicitante (de_s) e ator
class Solicitante(Base):
    def test_adm_escolhe_o_setor_que_pede(self):
        for s in ("PCP", "CNC", "ESP"):
            self.assertEqual(self.aceita(de_s=s)["de"], {"s": s, "p": None})

    def test_adm_pede_para_o_proprio_setor_de_destino(self):
        self.assertEqual(self.aceita(de_s="CNC", para={"s": "CNC", "p": None})["de"]["s"], "CNC")

    def test_adm_sem_setor_solicitante_ou_invalido(self):
        for v in (FALTA, None, "", "ZZ", "pcp", 5, ["PCP"], {"id": "PCP"}):
            self.rejeita(400, "Setor solicitante inválido.", de_s=v)

    def test_adm_setor_solicitante_inativo(self):
        self.setor("PIN", "Pintura")
        self.adm("setor/ativar", {"id": "PIN", "rev": self.disco()["setores"][-1]["_rv"]})
        self.rejeita(400, "Setor solicitante inválido.", de_s="PIN")

    def test_pessoa_pede_como_ela_mesma(self):
        d = self.aceita(self.tk_h)
        self.assertEqual(d["de"], {"s": "PCP", "p": self.helena})
        self.assertEqual(self.dem(d["id"])["eventos"][0]["quem"], "Helena")

    def test_pessoa_nao_forja_o_solicitante(self):
        for fake in ("ESP", "ZZ", None, 5):
            d = self.aceita(self.tk_h, de_s=fake)
            self.assertEqual(d["de"], {"s": "PCP", "p": self.helena}, fake)

    def test_pessoa_pode_pedir_para_o_proprio_setor_ou_para_si(self):
        self.assertEqual(self.aceita(self.tk_c, para={"s": "CNC", "p": self.carlos})["para"]["p"], self.carlos)
        self.assertEqual(self.aceita(self.tk_c, para={"s": "CNC", "p": None})["de"]["s"], "CNC")

    def test_campos_de_sistema_no_corpo_sao_ignorados(self):
        d = self.aceita(status="done", id="SOL-9", criado=1, iniciado=5, fim=9, eventos=[{"ev": "x"}], anexos=[1],
                        pausas=[1], comentarios=[1], atraso_avisado=True, prazo_em=7, agenda_v=9, _rv=99, tk=None)
        r = self.dem(d["id"])
        self.assertEqual((r["id"], r["status"], r["criado"], r["iniciado"], r["fim"]), ("SOL-1001", "new", T0, None, None))
        self.assertEqual((r["pausas"], r["comentarios"], r["anexos"], r["atraso_avisado"]), ([], [], [], False))
        self.assertEqual([e["ev"] for e in r["eventos"]], ["created"])
        self.assertNotIn("prazo_em", r)
        self.assertNotEqual(r["_rv"], 99)


class Permissao(Base):
    def test_operador_sem_tk_nao_cria(self):
        self.rejeita(403, "Identifique-se para usar as demandas.", ctx=OP)

    def test_sem_papel_nao_cria(self):
        for papel in (None, "", "visitante", "ADMIN"):
            self.rejeita(403, "Identifique-se", ctx={"papel": papel})
        self.rejeita(403, "Identifique-se", ctx={})

    def test_maquina_e_completo_criam_como_escritorio(self):
        for ctx in (ADM, COMPLETO):
            d = self.nova(ctx=ctx)
            self.assertEqual(self.dem(d["id"])["eventos"][0]["quem"], "Escritório")

    def test_tk_ruim_e_401(self):
        for tk in ("", "tk-que-nao-existe", "x" * 500, 123, ["a"], {"a": 1}, False):
            self.rejeita(401, "Identifique-se de novo.", tk=tk)
        self.rejeita(401, "Identifique-se de novo.", tk="tk-ruim", ctx=ADM)   # tk ruim vale mesmo no PC (não vira Escritório)

    def test_tk_vencido_e_401(self):
        self.clk += api.TK_VIDA_S + 1
        self.rejeita(401, "Identifique-se de novo.", tk=self.tk_h)

    def test_pessoa_desativada_perde_o_acesso(self):
        self.adm("pessoa/ativar", {"id": self.helena, "rev": self.disco()["pessoas"][0]["_rv"]})
        self.rejeita(401, "Identifique-se de novo.", tk=self.tk_h)

    def test_setor_da_pessoa_desativado_derruba_o_pedido(self):
        self.adm("setor/ativar", {"id": "PCP", "rev": self.disco()["setores"][0]["_rv"]})
        self.rejeita(401, "Identifique-se de novo.", tk=self.tk_h)

    def test_tk_de_um_nao_cria_em_nome_de_outro(self):
        d = self.aceita(self.tk_c)
        self.assertEqual(d["de"]["p"], self.carlos)
        self.assertEqual(self.dem(d["id"])["eventos"][0]["quem"], "Carlos")

    def test_corpo_que_nao_e_objeto(self):
        for corpo in ([], "x", 5, None):
            CASOS[0] += 1
            self.assertEqual(self.erro(api.handle, "POST", "demanda/criar", corpo, ADM), (400, "Pedido inválido."))

    def test_metodo_e_rota_errados(self):
        CASOS[0] += 2
        self.assertEqual(self.erro(api.handle, "GET", "demanda/criar", {}, ADM)[0], 404)
        self.assertEqual(self.erro(api.handle, "POST", "demanda/criarx", self.corpo(), ADM)[0], 404)
        self.assertEqual(self.ndem(), 0)


# ======================================================================== a chave cid
class Cid(Base):
    def test_formato(self):
        bons = ["abcdefgh", "A" * 64, "3f2a9c1e-0b7d-4e55-9a31-5c2f1d8e7a60", "a_b-c_d-e", "12345678"]
        for i, c in enumerate(bons):
            self.assertEqual(self.aceita(titulo="Pedido número %d" % i, cid=c)["id"], "SOL-%d" % (1001 + i))
        ruins = ["abcdefg", "A" * 65, "", "abc def gh", "açãoaçãoação", "abc.defgh", "abcdefgh\n", "abcdefgh ", 12345678,
                 ["abcdefgh"], {"a": 1}, True]
        for c in ruins:
            self.rejeita(400, "Chave do pedido inválida.", cid=c)

    def test_sem_cid_grava_e_nao_anota(self):
        self.aceita()
        self.aceita()
        self.assertEqual(self.ndem(), 2)
        self.assertEqual(self.disco()["cids"], [])

    def test_reenvio_nao_duplica(self):
        d = self.aceita(cid="chave-0001")
        antes = self.disco()
        v = self.cria(cid="chave-0001")        # a resposta se perdeu: a tela manda de novo
        CASOS[0] += 1
        self.assertEqual(self.disco(), antes)  # nada gravado: nem demanda, nem aviso, nem número, nem rev
        self.assertEqual([x["id"] for x in v["demandas"]], [d["id"]])
        self.assertEqual(self.disco()["cids"], [["chave-0001", d["id"]]])

    def test_reenvio_pela_pessoa_nao_duplica(self):
        self.aceita(self.tk_c, cid="chave-0002")
        self.aceita(self.tk_c, cid="chave-0002")
        self.assertEqual(self.ndem(), 1)

    def test_cids_diferentes_criam_pedidos_diferentes(self):
        self.aceita(cid="chave-0001")
        self.assertEqual(self.aceita(cid="chave-0002")["id"], "SOL-1002")
        self.assertEqual(self.disco()["cids"], [["chave-0001", "SOL-1001"], ["chave-0002", "SOL-1002"]])

    def test_pedido_recusado_nao_gasta_a_chave(self):
        self.rejeita(400, "Título", cid="chave-0003", titulo="abcd")
        self.assertEqual(self.disco()["cids"], [])
        self.assertEqual(self.aceita(cid="chave-0003", titulo="abcde")["id"], "SOL-1001")   # corrigiu e reenviou: grava

    def test_chave_repetida_ganha_da_validacao(self):
        """Comportamento do contrato (devolve a vista sem gravar): a chave repetida vem antes de conferir os campos."""
        self.aceita(cid="chave-0004")
        CASOS[0] += 1
        v = self.cria(cid="chave-0004", titulo="x")     # corpo inválido, mas a chave já foi gravada
        self.assertEqual(len(v["demandas"]), 1)

    def test_a_memoria_guarda_so_as_ultimas(self):
        with mock.patch.dict(ds.MAX, {"cids": 3}):
            for i in range(4):
                self.aceita(cid="chave-000%d" % i, titulo="Pedido %d" % i)
            self.assertEqual([c[0] for c in self.disco()["cids"]], ["chave-0001", "chave-0002", "chave-0003"])
            self.assertEqual(self.aceita(cid="chave-0003")["id"], "SOL-1004")                    # ainda lembrada: não duplicou
            self.assertEqual(self.aceita(cid="chave-0000", titulo="Pedido de novo")["id"], "SOL-1005")   # esquecida: grava

    def test_reenvios_em_paralelo_gravam_uma_vez(self):
        CASOS[0] += 1
        saidas, erros = [], []

        def envia():
            try:
                saidas.append(self.cria(cid="chave-paralela"))
            except Exception as exc:    # pragma: no cover - só se der errado
                erros.append(exc)

        ths = [threading.Thread(target=envia) for _ in range(8)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        self.assertEqual((erros, len(saidas), self.ndem()), ([], 8, 1))


# ======================================================== teto, número e concorrência
class TetoENumero(Base):
    def test_teto_de_abertas_limite_exato(self):
        with mock.patch.dict(ds.MAX, {"demandas": 3}):
            a = self.aceita(titulo="Primeira demanda")
            self.aceita(titulo="Segunda demanda")
            self.aceita(titulo="Terceira demanda")            # a 3ª (teto) cabe
            m = self.rejeita(400, "Limite de demandas em aberto atingido.", titulo="Quarta demanda")
            self.assertIn("aberto", m)
            self.adm("demanda/cancelar", {"id": a["id"]})     # cancelada libera a vaga
            self.assertEqual(self.aceita(titulo="Quarta demanda")["id"], "SOL-1004")
            self.rejeita(400, "Limite de demandas em aberto atingido.", titulo="Quinta demanda")

    def test_concluida_nao_conta_no_teto(self):
        with mock.patch.dict(ds.MAX, {"demandas": 1}):
            a = self.aceita()
            self.pes(self.tk_c, "demanda/aceitar", {"id": a["id"]})
            self.pes(self.tk_c, "demanda/concluir", {"id": a["id"]})
            self.aceita(titulo="Depois da concluída")

    def test_teto_vale_para_a_pessoa_tambem(self):
        with mock.patch.dict(ds.MAX, {"demandas": 1}):
            self.aceita(self.tk_h)
            self.rejeita(400, "Limite de demandas em aberto", tk=self.tk_h, titulo="Outra da Helena")

    def test_validacao_vem_antes_do_teto(self):
        with mock.patch.dict(ds.MAX, {"demandas": 1}):
            self.aceita()
            self.rejeita(400, "Título", titulo="abcd")

    def test_numeracao_continua_sem_buracos_e_nao_reusa(self):
        ids = [self.aceita(titulo="Pedido %d" % i)["id"] for i in range(3)]
        self.assertEqual(ids, ["SOL-1001", "SOL-1002", "SOL-1003"])
        self.adm("demanda/cancelar", {"id": "SOL-1003"})
        self.assertEqual(self.aceita()["id"], "SOL-1004")         # a cancelada não devolve o número
        self.rejeita(400, "Título", titulo="abcd")
        self.assertEqual(self.aceita()["id"], "SOL-1005")         # recusa não gasta número

    def test_numero_continua_depois_do_maior_do_arquivo_morto(self):
        arq = {"v": 1, "demandas": [dict(self.nova(), id="SOL-2000", status="done", fim=T0)]}
        (self.dir / "demandas-arquivo.json").write_text(json.dumps(arq), encoding="utf-8")
        ds._ARQ.update(key=None, demandas=[])
        self.assertEqual(self.aceita()["id"], "SOL-2001")

    def test_criacoes_em_paralelo_nao_repetem_numero(self):
        CASOS[0] += 1
        ids, erros = [], []

        def envia(i):
            try:
                ids.append(self.nova(titulo="Paralelo %02d" % i)["id"])
            except Exception as exc:    # pragma: no cover
                erros.append(exc)

        ths = [threading.Thread(target=envia, args=(i,)) for i in range(10)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        self.assertEqual(erros, [])
        self.assertEqual(sorted(d["id"] for d in self.disco()["demandas"]), ["SOL-%d" % n for n in range(1001, 1011)])


# =================================================================== gravação e avisos
class Gravacao(Base):
    def test_o_registro_inteiro(self):
        d = self.aceita(titulo="  Corte de MDF  ", tipo="mat", motivo="Retrabalho", prio="high", est=90,
                        para={"s": "CNC", "p": self.carlos}, desc="a\nb", de_s="ESP")
        r = self.dem(d["id"])
        r.pop("_rv")
        self.assertEqual(r, {
            "id": "SOL-1001", "titulo": "Corte de MDF", "tipo": "mat", "motivo": "Retrabalho", "prio": "high", "est": 90,
            "de": {"s": "ESP", "p": None}, "para": {"s": "CNC", "p": self.carlos}, "desc": "a\nb", "status": "new",
            "criado": T0, "iniciado": None, "fim": None, "atraso_avisado": False, "pausas": [],
            "eventos": [{"t": T0, "ev": "created", "quem": "Escritório", "nota": ""},
                        {"t": T0, "ev": "assigned", "quem": "Escritório", "nota": "Responsável: Carlos"}],
            "comentarios": [], "anexos": []})

    def test_cada_criacao_sobe_o_rev_uma_vez(self):
        r0 = self.rev()
        self.aceita()
        self.assertEqual(self.rev(), r0 + 1)
        self.assertEqual(self.dem("SOL-1001")["_rv"], r0 + 1)

    def test_resposta_traz_a_demanda_e_o_prazo(self):
        v = self.cria(est=30)
        d = next(x for x in v["demandas"] if x["id"] == "SOL-1001")
        self.assertEqual((d["prazo"], d["status"], d["est"]), (T0 + 30 * MIN, "new", 30))

    def test_aviso_de_nova_e_so_urgente_avisa_o_escritorio(self):
        for prio in ("low", "norm", "high"):
            self.aceita(prio=prio)
        self.assertEqual({n["aud"] for n in self.disco()["notas"] if n["tipo"] == "new"}, {"CNC"})
        self.assertEqual([n for n in self.disco()["notas"] if n["tipo"] == "urg"], [])
        d = self.aceita(prio="urg")
        notas = [(n["aud"], n["tipo"], n["dem"], n["quem"], n["lida"]) for n in self.disco()["notas"] if n["dem"] == d["id"]]
        self.assertEqual(notas, [("CNC", "new", d["id"], "Escritório", False), ("adm", "urg", d["id"], "Escritório", False)])

    def test_urgente_da_pessoa_avisa_o_escritorio_com_o_nome_dela(self):
        d = self.aceita(self.tk_h, prio="urg")
        urg = [n for n in self.disco()["notas"] if n["tipo"] == "urg" and n["dem"] == d["id"]]
        self.assertEqual([(n["aud"], n["quem"]) for n in urg], [("adm", "Helena")])
        self.assertTrue(any(n["aud"] == "CNC" and n["tipo"] == "new" for n in self.disco()["notas"]))

    def test_recusa_nao_cria_aviso(self):
        self.rejeita(400, "Título", titulo="abcd", prio="urg")
        self.assertEqual(self.disco()["notas"], [])


# ===================================================================== horário de serviço
class Horario(Base):
    def setUp(self):
        super().setUp()
        self.t = SEXTA_1630

    def liga(self, **kw):
        v = self.disco()["agenda"]["v"]
        return self.adm("agenda/salvar", {"agenda": {**ag.padrao(), "ativa": True, "v": v, **kw}})

    def test_desligado_e_tempo_corrido(self):
        r = self.dem(self.aceita(est=60)["id"])
        self.assertNotIn("prazo_em", r)
        self.assertNotIn("agenda_v", r)

    def test_ligado_grava_prazo_em_e_agenda_v(self):
        self.liga()
        d = self.aceita(est=60)
        r = self.dem(d["id"])
        self.assertEqual((r["agenda_v"], r["prazo_em"], d["prazo"]), (1, SEG_0730, SEG_0730))   # sexta 16:30 + 60 min úteis
        self.assertEqual(r["criado"], SEXTA_1630)

    def test_dentro_do_turno_o_prazo_e_so_a_soma(self):
        self.liga()
        self.t = loc(2026, 11, 16, 8, 0)    # segunda 08:00
        self.assertEqual(self.dem(self.aceita(est=30)["id"])["prazo_em"], loc(2026, 11, 16, 8, 30))
        self.assertEqual(self.dem(self.aceita(est=240)["id"])["prazo_em"], loc(2026, 11, 16, 12, 0))   # 08-12: as 4 h cabem
        self.assertEqual(self.dem(self.aceita(est=480)["id"])["prazo_em"], loc(2026, 11, 16, 17, 0))   # 4 h + almoço + 4 h

    def test_almoco_nao_conta(self):
        self.liga()
        self.t = loc(2026, 11, 16, 11, 30)   # 30 min até o almoço e depois 13:00
        self.assertEqual(self.dem(self.aceita(est=60)["id"])["prazo_em"], loc(2026, 11, 16, 13, 30))

    def test_criada_fora_do_expediente_conta_da_proxima_abertura(self):
        self.liga()
        for quando, esperado in ((loc(2026, 11, 14, 10, 0), loc(2026, 11, 16, 7, 1)),     # sábado
                                 (loc(2026, 11, 13, 23, 0), loc(2026, 11, 16, 7, 1)),     # sexta à noite
                                 (loc(2026, 11, 16, 6, 0), loc(2026, 11, 16, 7, 1))):     # segunda antes de abrir
            self.t = quando
            self.assertEqual(self.dem(self.aceita(est=1)["id"])["prazo_em"], esperado, quando)

    def test_horario_do_setor_destino_e_a_versao_vigente(self):
        self.liga(setores={"CNC": {"dias": [6], "turnos": [["06:00", "10:00"]]}})
        c = self.dem(self.aceita(est=60, para={"s": "CNC", "p": None})["id"])
        e = self.dem(self.aceita(est=60, para={"s": "ESP", "p": None})["id"])
        self.assertEqual((c["prazo_em"], e["prazo_em"]), (loc(2026, 11, 14, 7, 0), SEG_0730))
        self.assertEqual((c["agenda_v"], e["agenda_v"]), (1, 1))
        self.liga(feriados=[{"data": "2026-12-25", "nome": "Natal", "setores": []}])
        self.assertEqual(self.dem(self.aceita(est=60)["id"])["agenda_v"], 2)
        self.assertEqual(self.dem(c["id"])["agenda_v"], 1)          # a antiga não muda

    def test_feriado_pula_o_dia(self):
        self.liga(feriados=[{"data": "2026-11-16", "nome": "Segunda emendada", "setores": []}])
        self.assertEqual(self.dem(self.aceita(est=60)["id"])["prazo_em"], loc(2026, 11, 17, 7, 30))

    def test_desligar_depois_nao_muda_o_prazo_gravado(self):
        self.liga()
        d = self.aceita(est=60)
        self.liga(ativa=False)
        v = self.adm("vista")
        self.assertEqual(next(x for x in v["demandas"] if x["id"] == d["id"])["prazo"], SEG_0730)

    def test_tempo_limite_do_maior_est_cabe_no_padrao(self):
        self.liga()
        d = self.aceita(est=43200)
        self.assertGreater(self.dem(d["id"])["prazo_em"], SEXTA_1630 + 30 * 24 * HORA)   # útil dura mais que corrido

    def test_que_nao_cabe_e_recusado_sem_gravar(self):
        self.liga(padrao={"dias": [1], "turnos": [["07:00", "07:15"]]})
        m = self.rejeita(400, "não tem trabalho suficiente", est=43200)
        self.assertIn("dias", m)
        self.assertEqual(self.ndem(), 0)

    def test_recusa_de_horario_nao_gasta_cid_nem_numero(self):
        self.liga(padrao={"dias": [1], "turnos": [["07:00", "07:15"]]})
        self.rejeita(400, "não tem trabalho suficiente", est=43200, cid="chave-hs-01")
        self.assertEqual(self.disco()["cids"], [])
        self.assertEqual(self.aceita(est=1, cid="chave-hs-01")["id"], "SOL-1001")


# ============================================================== HTTP (servidor.py de verdade)
class Http(unittest.TestCase):
    """O mesmo caminho que a tela faz: POST /api/local/demandas/demanda/criar no servidor, do próprio PC (papel maquina)."""

    @classmethod
    def setUpClass(cls):
        cls._data = os.environ.get("DEMANDAS_DATA")
        cls.dir = tempfile.mkdtemp(prefix="dem-qa-criar-http-")
        os.environ["DEMANDAS_DATA"] = cls.dir
        import servidor
        cls.srv = servidor.Server(("127.0.0.1", 0), servidor.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        ds._CACHE.update(key=None, texto=None)
        for sid, nome in (("PCP", "Planejamento"), ("CNC", "Corte CNC")):
            st, _ = cls.post("setor/salvar", {"modo": "novo", "id": sid, "nome": nome, "icone": "⚙️", "cor": "#3B82F6", "rev": 0})
            assert st == 200, st

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        if cls._data is None:
            os.environ.pop("DEMANDAS_DATA", None)
        else:
            os.environ["DEMANDAS_DATA"] = cls._data

    @classmethod
    def post(cls, rest, body=None, raw=None, headers=None, metodo="POST"):
        c = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=15)
        data = raw if raw is not None else json.dumps(body if body is not None else {}).encode("utf-8")
        h = {"Content-Type": "application/json", "Content-Length": str(len(data))}
        h.update(headers or {})
        c.request(metodo, "/api/local/demandas/" + rest, body=data, headers=h)
        r = c.getresponse()
        txt = r.read().decode("utf-8")
        c.close()
        return r.status, txt

    def corpo(self, **kw):
        return {**{"titulo": "Pedido pelo HTTP", "tipo": "dem", "motivo": "Outro", "prio": "norm", "est": 60,
                   "para": {"s": "CNC", "p": None}, "desc": "", "de_s": "PCP"}, **kw}

    def n(self):
        return len(json.loads(Path(self.dir, "demandas.json").read_text(encoding="utf-8"))["demandas"])

    def test_cria_e_responde_a_vista(self):
        CASOS[0] += 1
        n0 = self.n()
        st, txt = self.post("demanda/criar", self.corpo(cid="http-cid-0001"))
        self.assertEqual(st, 200)
        v = json.loads(txt)
        self.assertEqual(len(v["demandas"]), n0 + 1)
        self.assertEqual(self.n(), n0 + 1)
        st, _ = self.post("demanda/criar", self.corpo(cid="http-cid-0001"))    # reenvio da mesma chave
        self.assertEqual((st, self.n()), (200, n0 + 1))

    def test_erro_de_campo_vira_400_com_a_frase_pura(self):
        CASOS[0] += 1
        n0 = self.n()
        st, txt = self.post("demanda/criar", self.corpo(titulo="abcd"))
        self.assertEqual((st, self.n()), (400, n0))
        self.assertIn("Título: de 5 a 140 caracteres.", txt)

    def test_json_invalido_e_corpo_que_nao_e_objeto(self):
        CASOS[0] += 3
        n0 = self.n()
        st, txt = self.post("demanda/criar", raw=b"{titulo:")
        self.assertEqual(st, 400)
        self.assertIn("JSON inválido", txt)
        st, txt = self.post("demanda/criar", raw=b"[1, 2]")
        self.assertEqual(st, 400)
        self.assertIn("Pedido inválido", txt)
        st, _ = self.post("demanda/criar", raw="\xff\xfe".encode("latin-1"))
        self.assertEqual(st, 400)
        self.assertEqual(self.n(), n0)

    def test_corpo_vazio_e_recusado_por_campo(self):
        CASOS[0] += 1
        st, txt = self.post("demanda/criar", raw=b"")
        self.assertEqual(st, 400)
        self.assertIn("Título", txt)

    def test_outro_site_nao_posta_pedido(self):
        CASOS[0] += 1
        n0 = self.n()
        st, txt = self.post("demanda/criar", self.corpo(), headers={"Origin": "http://site-de-fora.example"})
        self.assertEqual((st, self.n()), (403, n0))
        self.assertIn("Origem", txt)

    def test_get_na_rota_de_escrita_nao_cria(self):
        CASOS[0] += 1
        n0 = self.n()
        st, _ = self.post("demanda/criar", raw=b"", metodo="GET")
        self.assertIn(st, (400, 404, 405))
        self.assertEqual(self.n(), n0)

    def test_acentos_e_emoji_passam_pelo_http(self):
        CASOS[0] += 1
        st, txt = self.post("demanda/criar", self.corpo(titulo="Ação ✓ 😀 çãé", desc="linha 1\nlinha 2"))
        self.assertEqual(st, 200)
        d = max(json.loads(txt)["demandas"], key=lambda x: int(x["id"][4:]))
        self.assertEqual((d["titulo"], d["desc"]), ("Ação ✓ 😀 çãé", "linha 1\nlinha 2"))


if __name__ == "__main__":
    unittest.main()
