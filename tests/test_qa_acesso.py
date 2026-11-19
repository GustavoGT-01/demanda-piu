"""QA da área ACESSO E PERMISSÕES (sessão A da bateria): entrar com o código, bloqueio, token, sair, papéis, rotas só do
ADM, visão da pessoa (calc.ve) e a autorização do servidor.py (_auth_ok, OPERADOR_RE, OPERADOR_ROTAS).

Duas partes: (1) direto no api.py, com relógios trocados e pbkdf2 leve, dados em pasta temporária (DEMANDAS_DATA);
(2) pelo HTTP de verdade, com um servidor na porta efêmera. A matriz de cobertura está em docs/qa/acesso.md.
Teste que expõe bug confirmado fica com @unittest.expectedFailure e comentário `known-bug` (id do bug no .md).
"""

import base64
import hashlib
import http.client
import io
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parents[1] / "demandas"
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
os.environ.setdefault("DEMANDAS_DATA", tempfile.mkdtemp(prefix="dem-qa-acesso-"))

import demandas_calc as calc  # noqa: E402
import demandas_store as ds  # noqa: E402

_spec = importlib.util.spec_from_file_location("demandas_api_qa_acesso", HERE / "api.py")
api = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(api)
ITER_REAL = api.ITER

import servidor  # noqa: E402

T0 = 1_800_000_000_000
ADM = {"papel": "maquina"}
COMPLETO = {"papel": "completo"}
OP = {"papel": "operador"}
JPG = b"\xff\xd8\xff\xe0" + b"j" * 40
B64 = base64.b64encode(JPG).decode()
MSG_ADM = "Só o escritório pode fazer isso."
MSG_IDENT = "Identifique-se para usar as demandas."
MSG_TK = "Identifique-se de novo."
MSG_BLOQ = "Bloqueado por 1 minuto: muitos códigos errados."

# Rotas que só o Escritório alcança (api.py chama _so_adm) e as que o aparelho de operador alcança (servidor.py).
ROTAS_SO_ADM = ("setor/salvar", "setor/ativar", "setor/apagar", "pessoa/salvar", "pessoa/ativar", "pessoa/apagar",
                "agenda/salvar", "demanda/prioridade", "demanda/estender", "historico", "crono", "cronograma")
ROTAS_PESSOA = ("entrar", "sair", "vista", "demanda/criar", "demanda/aceitar", "demanda/pausar", "demanda/retomar",
                "demanda/concluir", "demanda/cancelar", "demanda/reatribuir", "demanda/cobrar", "demanda/comentar",
                "anexo/enviar", "anexo/ler", "anexo/apagar", "nota/lida", "nota/todas", "aviso/prefs")


class Base(unittest.TestCase):
    """Cenário: PCP (Helena), CNC (Carlos, Bruno), ESP (Fernanda); relógio do bloqueio e do tk sob controle."""

    def setUp(self):
        self._data = os.environ.get("DEMANDAS_DATA")
        self.dir = Path(tempfile.mkdtemp(prefix="dem-qa-ac-"))
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

    def adm(self, rest, body=None, ctx=ADM):
        return api.handle("POST", rest, dict(body or {}), ctx)

    def get(self, rest="", ctx=ADM):
        return api.handle("GET", rest, {}, ctx)

    def pes(self, tk, rest, body=None, ctx=OP):
        return api.handle("POST", rest, dict(body or {}, tk=tk), ctx)

    def erro(self, fn, *a, **kw):
        with self.assertRaises(api.ApiError) as c:
            fn(*a, **kw)
        return c.exception.status, str(c.exception)

    def disco(self, nome="demandas.json"):
        return json.loads((self.dir / nome).read_text(encoding="utf-8"))

    def entrar(self, pid, codigo, ctx=OP):
        return api.handle("POST", "entrar", {"pessoa": pid, "codigo": codigo}, ctx)

    def tk_de(self, pid, codigo):
        return self.entrar(pid, codigo)["tk"]

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
        self.tk_h = self.tk_de(self.helena, "1111")
        self.tk_c = self.tk_de(self.carlos, "2222")
        self.tk_b = self.tk_de(self.bruno, "3333")
        self.tk_f = self.tk_de(self.fer, "4444")

    def pedido(self, tk, para_s, titulo="Cortar chapas"):
        body = {"titulo": titulo, "tipo": "dem", "motivo": "Outro", "prio": "norm", "est": 60,
                "para": {"s": para_s, "p": None}, "desc": ""}
        if tk is None:
            body["de_s"] = "PCP"
            v = self.adm("demanda/criar", body)
        else:
            v = self.pes(tk, "demanda/criar", body)
        return max(v["demandas"], key=lambda d: int(d["id"][4:]))["id"]


# ===================================================================================== entrar com o código
class EntrarCodigo(Base):
    def test_entra_com_o_codigo_certo_em_qualquer_papel(self):
        for ctx in (OP, ADM, COMPLETO):
            r = self.entrar(self.carlos, "2222", ctx)
            self.assertEqual(set(r), {"tk", "eu", "vista"})
            self.assertEqual(r["eu"], {"id": self.carlos, "nome": "Carlos", "setor": "CNC", "mat": r["eu"]["mat"]})
            self.assertEqual(r["vista"]["papel"], "pessoa")
            self.assertEqual(r["vista"]["eu"], r["eu"])

    def test_token_tem_32_caracteres_urlsafe_e_cada_entrada_e_um_token_novo(self):
        a, b = self.tk_de(self.carlos, "2222"), self.tk_de(self.carlos, "2222")
        self.assertRegex(a, r"^[A-Za-z0-9_-]{32}$")
        self.assertNotEqual(a, b)

    def test_zeros_a_esquerda_valem(self):
        p = self.pessoa("Zeca", "ESP", "0007")
        self.assertTrue(self.tk_de(p, "0007"))
        self.assertEqual(self.erro(self.entrar, p, "7")[0], 403)
        self.assertEqual(self.erro(self.entrar, p, "0070")[0], 403)

    def test_codigo_errado_403_com_a_mensagem_da_tela(self):
        self.assertEqual(self.erro(self.entrar, self.carlos, "9999"), (403, "Código errado."))
        self.assertEqual(self.erro(self.entrar, self.carlos, "1111"), (403, "Código errado."))   # o de outra pessoa

    def test_codigo_vazio_ausente_ou_de_formato_ruim(self):
        ruins = ["", None, "123", "12345", "abcd", "12 4", " 2222", "2222 ", "2222\n", "２２２２", "22.2", "-222", 2222, 22.0,
                 True, [], {}, ["2222"], "2222\x00"]
        for c in ruins:
            api._FAILS.clear()   # cada um é uma tentativa nova: o bloqueio tem teste próprio
            self.assertEqual(self.erro(self.entrar, self.carlos, c), (403, "Código errado."), repr(c))
        api._FAILS.clear()
        self.assertEqual(self.erro(api.handle, "POST", "entrar", {"pessoa": self.carlos}, OP), (403, "Código errado."))

    def test_pessoa_que_nao_entra_404(self):
        for pid in ("p999", "", None, 7, [], {}, True, "P0", " p0"):
            self.assertEqual(self.erro(self.entrar, pid, "1111"), (404, "Pessoa não encontrada."), repr(pid))
        self.assertEqual(self.erro(api.handle, "POST", "entrar", {"codigo": "1111"}, OP)[0], 404)
        self.assertEqual(self.erro(api.handle, "POST", "entrar", {}, OP)[0], 404)

    def test_pessoa_ou_setor_inativo_nao_entra(self):
        rv = lambda lst, i: next(x for x in lst if x["id"] == i)["_rv"]  # noqa: E731
        v = self.get()
        self.adm("pessoa/ativar", {"id": self.bruno, "rev": rv(v["pessoas"], self.bruno)})
        self.assertEqual(self.erro(self.entrar, self.bruno, "3333"), (404, "Pessoa não encontrada."))
        self.adm("pessoa/ativar", {"id": self.bruno, "rev": rv(self.get()["pessoas"], self.bruno)})   # volta
        self.assertTrue(self.tk_de(self.bruno, "3333"))
        self.adm("setor/ativar", {"id": "ESP", "rev": rv(self.get()["setores"], "ESP")})
        self.assertEqual(self.erro(self.entrar, self.fer, "4444"), (404, "Pessoa não encontrada."))

    def test_pessoa_inexistente_nao_conta_para_o_bloqueio(self):
        for _ in range(8):
            self.assertEqual(self.erro(self.entrar, "p999", "0000")[0], 404)
        self.assertEqual(api._FAILS, {})

    def test_cadastro_sem_sal_valido_nao_entra(self):
        doc = self.disco()
        for p in doc["pessoas"]:
            if p["id"] == self.carlos:
                p["sal"] = "xyz"
        (self.dir / "demandas.json").write_text(json.dumps(doc), encoding="utf-8")
        ds._CACHE.update(key=None, texto=None)
        self.assertEqual(self.erro(self.entrar, self.carlos, "2222")[0], 404)

    def test_corpo_nao_objeto_400(self):
        for corpo in ([], "x", None, 5):
            self.assertEqual(self.erro(api.handle, "POST", "entrar", corpo, OP), (400, "Pedido inválido."))

    def test_resposta_nao_vaza_sal_hash_nem_email(self):
        raw = self.disco()["pessoas"][1]
        txt = json.dumps(self.entrar(self.carlos, "2222"))
        for proibido in (raw["hash"], raw["sal"], '"sal"', '"hash"', '"email"', "2222"):
            self.assertNotIn(proibido, txt)

    def test_vista_ao_entrar_e_a_da_pessoa(self):
        v = self.entrar(self.carlos, "2222")["vista"]
        self.assertNotIn("anexos_uso", v)
        self.assertEqual(v["papel"], "pessoa")
        self.assertTrue(all("email" not in x for x in v["pessoas"] + v["setores"]))


# ===================================================================================== bloqueio por tentativas
class Bloqueio(Base):
    def erros(self, n, pid=None, codigo="0000"):
        for _ in range(n):
            self.assertEqual(self.erro(self.entrar, pid or self.carlos, codigo)[0], 403)

    def test_constantes(self):
        self.assertEqual((api.TENTATIVAS, api.BLOQUEIO_S), (5, 60))

    def test_quatro_erros_ainda_deixam_entrar_e_o_acerto_zera_a_conta(self):
        self.erros(4)
        self.assertTrue(self.tk_de(self.carlos, "2222"))
        self.erros(4)   # conta de novo do zero: 4 erros não bloqueiam
        self.assertTrue(self.tk_de(self.carlos, "2222"))

    def test_quinto_erro_bloqueia_e_ate_o_codigo_certo_e_barrado(self):
        self.erros(5)   # o 5º ainda responde 403 (errado); a partir do 6º é 429
        self.assertEqual(self.erro(self.entrar, self.carlos, "0000"), (429, MSG_BLOQ))
        self.assertEqual(self.erro(self.entrar, self.carlos, "2222"), (429, MSG_BLOQ))
        self.assertEqual(self.erro(self.entrar, self.carlos, ""), (429, MSG_BLOQ))

    def test_limite_exato_do_bloqueio(self):
        self.erros(5)
        self.clk += api.BLOQUEIO_S - 0.001
        self.assertEqual(self.erro(self.entrar, self.carlos, "2222")[0], 429)   # 59,999 s: ainda bloqueado
        self.clk += 0.001                                                          # 60 s exatos: livre
        self.assertTrue(self.tk_de(self.carlos, "2222"))

    def test_bloqueio_nao_renova_com_tentativa_durante_o_bloqueio(self):
        self.erros(5)
        self.clk += 30
        for _ in range(10):
            self.assertEqual(self.erro(self.entrar, self.carlos, "0000")[0], 429)
        self.clk += 30   # 60 s desde o 5º erro: o 429 não esticou o prazo
        self.assertTrue(self.tk_de(self.carlos, "2222"))

    def test_depois_do_bloqueio_a_conta_recomeca(self):
        self.erros(5)
        self.clk += 61
        self.erros(4)
        self.assertEqual(self.erro(self.entrar, self.carlos, "0000")[0], 403)   # 5º novo erro
        self.assertEqual(self.erro(self.entrar, self.carlos, "2222")[0], 429)   # bloqueou de novo

    def test_bloqueio_e_por_pessoa(self):
        self.erros(5)
        self.assertEqual(self.erro(self.entrar, self.carlos, "2222")[0], 429)
        self.assertTrue(self.tk_de(self.bruno, "3333"))
        self.assertTrue(self.tk_de(self.helena, "1111"))

    def test_erro_de_formato_conta_como_erro(self):
        for c in ("", "abc", None, "12345", "99"):
            self.assertEqual(self.erro(self.entrar, self.carlos, c)[0], 403)
        self.assertEqual(self.erro(self.entrar, self.carlos, "2222")[0], 429)   # os 5 erros bloquearam

    def test_bloqueio_nao_derruba_quem_ja_esta_dentro(self):
        self.erros(5)
        self.assertEqual(self.pes(self.tk_c, "vista")["papel"], "pessoa")

    def test_trocar_o_codigo_pelo_escritorio_libera_o_bloqueio(self):
        self.erros(5)
        rv = next(p["_rv"] for p in self.get()["pessoas"] if p["id"] == self.carlos)
        self.adm("pessoa/salvar", {"modo": "editar", "id": self.carlos, "nome": "Carlos", "setor": "CNC", "codigo": "5555",
                                   "rev": rv})
        self.assertTrue(self.tk_de(self.carlos, "5555"))

    def test_palpites_em_paralelo_nao_passam_de_cinco(self):
        api.ITER = 20_000   # o pbkdf2 mais lento aumenta a sobreposição das tentativas
        # recria a pessoa com o ITER de agora para o hash bater com o do teste
        saidas, barreira = [], threading.Barrier(24)

        def palpite():
            barreira.wait()
            try:
                self.entrar(self.carlos, "0000")
                saidas.append(200)
            except api.ApiError as exc:
                saidas.append(exc.status)

        ts = [threading.Thread(target=palpite) for _ in range(24)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(saidas.count(403), 5, saidas)
        self.assertEqual(saidas.count(429), 19, saidas)
        self.assertNotIn(200, saidas)

    def test_em_curso_zera_ao_fim_e_o_mapa_nao_cresce_com_acertos(self):
        self.tk_de(self.carlos, "2222")
        self.assertEqual(api._FAILS, {})   # acerto limpa o registro: nada fica em memória
        self.erros(2)
        self.assertEqual(api._FAILS[self.carlos], [2, 0.0, 0])


# ===================================================================================== token: vida, teto, disco, sair
class Token(Base):
    def test_constantes(self):
        self.assertEqual((api.TK_VIDA_S, api.TK_MAX), (43200, 500))

    def test_validade_de_12h_limite_exato(self):
        tk = self.tk_de(self.carlos, "2222")
        self.clk += api.TK_VIDA_S - 0.001
        self.assertEqual(self.pes(tk, "vista")["papel"], "pessoa")
        self.clk += 0.001   # vence no instante exato
        self.assertEqual(self.erro(self.pes, tk, "vista"), (401, MSG_TK))
        self.assertEqual(self.erro(self.pes, tk, "vista")[0], 401)   # e não volta

    def test_tk_nao_renova_com_o_uso(self):
        tk = self.tk_de(self.carlos, "2222")
        for _ in range(3):
            self.clk += api.TK_VIDA_S / 4
            self.pes(tk, "vista")
        self.clk += api.TK_VIDA_S / 4 + 1
        self.assertEqual(self.erro(self.pes, tk, "vista")[0], 401)

    def test_tk_ruim_401_e_sem_tk_depende_do_papel(self):
        for tk in ("", "inventado", "x" * 5000, 123, 1.5, True, [], {}, ["a"], b"abc"):
            self.assertEqual(self.erro(self.pes, tk, "vista"), (401, MSG_TK), repr(tk))
        corpo = {"tk": None}
        self.assertEqual(self.erro(api.handle, "POST", "vista", corpo, OP), (403, MSG_IDENT))
        self.assertEqual(api.handle("POST", "vista", corpo, ADM)["papel"], "adm")   # PC principal sem tk = Escritório
        self.assertEqual(api.handle("POST", "vista", {}, COMPLETO)["papel"], "adm")

    def test_tk_de_pessoa_vale_em_qualquer_papel_e_o_papel_nao_vira_adm(self):
        for ctx in (OP, ADM, COMPLETO):
            v = api.handle("POST", "vista", {"tk": self.tk_c}, ctx)
            self.assertEqual((v["papel"], v["eu"]["id"]), ("pessoa", self.carlos))
            self.assertEqual(self.erro(api.handle, "POST", "setor/ativar", {"tk": self.tk_c}, ctx), (403, MSG_ADM))

    def test_tokens_da_mesma_pessoa_sao_independentes(self):
        a, b = self.tk_de(self.carlos, "2222"), self.tk_de(self.carlos, "2222")
        self.pes(a, "sair")
        self.assertEqual(self.erro(self.pes, a, "vista")[0], 401)
        self.assertEqual(self.pes(b, "vista")["papel"], "pessoa")

    def test_teto_de_500_tokens_descarta_o_mais_antigo(self):
        base = len(api._TK)
        tks = []
        for i in range(api.TK_MAX - base + 1):
            self.clk += 1
            tks.append(api._tk_novo(self.carlos))
        self.assertEqual(len(api._TK), api.TK_MAX)
        self.assertEqual(self.erro(self.pes, self.tk_h, "vista")[0], 401)   # o primeiro de todos saiu
        self.assertEqual(self.pes(tks[-1], "vista")["papel"], "pessoa")
        self.assertEqual(self.pes(tks[0], "vista")["papel"], "pessoa")

    def test_so_o_hash_vai_para_o_disco_e_sobrevive_ao_reinicio(self):
        arq = (self.dir / "pessoas-sessoes.json")
        txt = arq.read_text(encoding="utf-8")
        self.assertNotIn(self.tk_c, txt)
        self.assertIn(hashlib.sha256(self.tk_c.encode()).hexdigest(), json.loads(txt)["sessoes"])
        api._TK.clear()
        api._TK_ARQ[0] = None   # o servidor reiniciou
        self.assertEqual(self.pes(self.tk_c, "vista")["eu"]["id"], self.carlos)

    def test_reinicio_nao_traz_de_volta_o_vencido_nem_a_linha_estranha(self):
        self.clk += api.TK_VIDA_S + 1
        api._TK.clear()
        api._TK_ARQ[0] = None
        self.assertEqual(self.erro(self.pes, self.tk_c, "vista")[0], 401)
        arq = self.dir / "pessoas-sessoes.json"
        h = hashlib.sha256(b"bom").hexdigest()
        arq.write_text(json.dumps({"v": 1, "sessoes": {
            h: [self.carlos, self.clk + 100], "curto": [self.carlos, self.clk + 100], "%064x" % 1: [self.carlos],
            "%064x" % 2: [1, self.clk + 100], "%064x" % 3: [self.carlos, True], "%064x" % 4: [self.carlos, "9"]}}),
            encoding="utf-8")
        api._TK.clear()
        api._TK_ARQ[0] = None
        self.assertEqual(self.pes("bom", "vista")["eu"]["id"], self.carlos)
        self.assertEqual(list(api._TK), [h])

    def test_arquivo_de_sessoes_ruim_ninguem_identificado(self):
        for lixo in ("{x", "[]", '{"sessoes": 5}', "", '{"sessoes": []}'):
            (self.dir / "pessoas-sessoes.json").write_text(lixo, encoding="utf-8")
            api._TK.clear()
            api._TK_ARQ[0] = None
            self.assertEqual(self.erro(self.pes, self.tk_c, "vista")[0], 401, lixo)
            self.assertEqual(api._TK, {})

    def test_arquivo_com_mais_de_500_fica_so_com_os_500_mais_novos(self):
        sess = {"%064x" % i: [self.carlos, self.clk + 100 + i] for i in range(api.TK_MAX + 20)}
        (self.dir / "pessoas-sessoes.json").write_text(json.dumps({"v": 1, "sessoes": sess}), encoding="utf-8")
        api._TK.clear()
        api._TK_ARQ[0] = None
        api._tk_pessoa("x")
        self.assertEqual(len(api._TK), api.TK_MAX)
        self.assertNotIn("%064x" % 0, api._TK)
        self.assertIn("%064x" % (api.TK_MAX + 19), api._TK)

    def test_falha_ao_gravar_nao_derruba_a_entrada(self):
        with mock.patch.object(api.store, "atomic_write", side_effect=OSError("disco cheio")):
            with mock.patch.object(sys, "stderr", new=io.StringIO()):
                r = self.entrar(self.carlos, "2222")
        self.assertEqual(self.pes(r["tk"], "vista")["papel"], "pessoa")   # vale até reiniciar

    def test_sair_derruba_o_tk_e_e_idempotente(self):
        self.assertEqual(self.pes(self.tk_c, "sair"), {"ok": True})
        self.assertEqual(self.erro(self.pes, self.tk_c, "vista")[0], 401)
        self.assertEqual(self.pes(self.tk_c, "sair"), {"ok": True})
        for corpo in ({}, {"tk": None}, {"tk": 5}, {"tk": ["x"]}, {"tk": "inventado"}):
            self.assertEqual(api.handle("POST", "sair", corpo, OP), {"ok": True}, corpo)
        self.assertEqual(self.pes(self.tk_b, "vista")["eu"]["id"], self.bruno)   # o de outro segue valendo
        self.assertEqual(self.erro(api.handle, "POST", "sair", [], OP)[0], 400)

    def test_sair_grava_no_disco(self):
        self.pes(self.tk_c, "sair")
        self.assertNotIn(hashlib.sha256(self.tk_c.encode()).hexdigest(),
                         json.loads((self.dir / "pessoas-sessoes.json").read_text(encoding="utf-8"))["sessoes"])

    def test_desativar_trocar_codigo_apagar_ou_restaurar_derruba_o_tk(self):
        rv = lambda i: next(p["_rv"] for p in self.get()["pessoas"] if p["id"] == i)  # noqa: E731
        self.adm("pessoa/salvar", {"modo": "editar", "id": self.carlos, "nome": "Carlos", "setor": "CNC", "codigo": "8888",
                                   "rev": rv(self.carlos)})
        self.assertEqual(self.erro(self.pes, self.tk_c, "vista"), (401, MSG_TK))
        self.assertEqual(self.erro(self.entrar, self.carlos, "2222")[0], 403)   # o código antigo morreu
        self.adm("pessoa/ativar", {"id": self.bruno, "rev": rv(self.bruno)})
        self.assertEqual(self.erro(self.pes, self.tk_b, "vista")[0], 401)
        self.adm("pessoa/ativar", {"id": self.bruno, "rev": rv(self.bruno)})   # reativar não ressuscita o tk
        self.assertEqual(self.erro(self.pes, self.tk_b, "vista")[0], 401)
        self.adm("pessoa/apagar", {"id": self.fer, "rev": rv(self.fer)})
        self.assertEqual(self.erro(self.pes, self.tk_f, "vista")[0], 401)
        api.esquecer_pessoas()
        self.assertEqual(self.erro(self.pes, self.tk_h, "vista")[0], 401)
        self.assertEqual(api._TK, {})

    def test_setor_desativado_ou_apagado_faz_o_tk_dar_401(self):
        rvs = lambda i: next(s["_rv"] for s in self.get()["setores"] if s["id"] == i)  # noqa: E731
        self.adm("setor/ativar", {"id": "CNC", "rev": rvs("CNC")})
        self.assertEqual(self.erro(self.pes, self.tk_c, "vista"), (401, MSG_TK))
        self.adm("setor/ativar", {"id": "CNC", "rev": rvs("CNC")})
        # comportamento atual (não documentado no CONTRATO): o tk de quem não foi desativado volta a valer com o setor
        self.assertEqual(self.pes(self.tk_c, "vista")["papel"], "pessoa")
        self.adm("setor/apagar", {"id": "ESP", "rev": rvs("ESP")})
        self.assertEqual(self.erro(self.pes, self.tk_f, "vista")[0], 401)

    def test_pessoa_desativada_com_tk_antigo_nao_age_mesmo_se_o_tk_voltasse(self):
        rv = next(p["_rv"] for p in self.get()["pessoas"] if p["id"] == self.carlos)
        h = hashlib.sha256(self.tk_c.encode()).hexdigest()
        saved = api._TK[h]
        self.adm("pessoa/ativar", {"id": self.carlos, "rev": rv})
        api._TK[h] = saved   # finge um tk que escapou da revogação
        self.assertEqual(self.erro(self.pes, self.tk_c, "vista")[0], 401)   # _ator confere "ativo" de novo


# ===================================================================================== papéis e rotas só do ADM
class Papeis(Base):
    def test_get_por_papel(self):
        for papel in ("maquina", "completo"):
            v = self.get(ctx={"papel": papel})
            self.assertEqual(v["papel"], "adm")
            self.assertIn("anexos_uso", v)
        pub = self.get(ctx=OP)
        self.assertEqual(set(pub), {"setores", "pessoas"})
        for ctx in ({}, {"papel": None}, {"papel": "Maquina"}, {"papel": "ADM"}, {"papel": "admin"}, {"papel": ""},
                    {"papel": "operador "}, {"papel": 1}):
            self.assertEqual(self.erro(self.get, ctx=ctx), (403, MSG_IDENT), ctx)

    def test_lista_publica_do_operador_so_tem_ativos_e_sem_segredo(self):
        rv = next(p["_rv"] for p in self.get()["pessoas"] if p["id"] == self.bruno)
        self.adm("pessoa/ativar", {"id": self.bruno, "rev": rv})
        self.adm("pessoa/salvar", {"modo": "editar", "id": self.carlos, "nome": "Carlos", "setor": "CNC",
                                   "email": "carlos@empresa.com", "rev": next(
                                       p["_rv"] for p in self.get()["pessoas"] if p["id"] == self.carlos)})
        pub = self.get(ctx=OP)
        self.assertEqual([p["nome"] for p in pub["pessoas"]], ["Helena", "Carlos", "Fernanda"])
        txt = json.dumps(pub)
        for x in ("hash", "sal", "email", "carlos@empresa.com", "demandas"):
            self.assertNotIn(x, txt)
        self.assertEqual(set(pub["pessoas"][0]), {"id", "nome", "setor", "mat", "ativo", "_rv"})
        self.assertIn("carlos@empresa.com", json.dumps(self.get()))   # o ADM, sim

    def test_pessoa_nao_recebe_email_na_vista(self):
        self.adm("pessoa/salvar", {"modo": "editar", "id": self.carlos, "nome": "Carlos", "setor": "CNC",
                                   "email": "carlos@empresa.com", "rev": next(
                                       p["_rv"] for p in self.get()["pessoas"] if p["id"] == self.carlos)})
        self.assertNotIn("@empresa.com", json.dumps(self.pes(self.tk_h, "vista")))

    def test_rotas_so_do_adm_dao_403_para_pessoa_e_nada_muda(self):
        self.pedido(self.tk_h, "CNC")
        rev0 = self.disco()["rev"]
        for rest in ROTAS_SO_ADM:
            for tk in (self.tk_h, self.tk_c, self.tk_f):
                self.assertEqual(self.erro(api.handle, "POST", rest, {"tk": tk}, OP), (403, MSG_ADM), rest)
                self.assertEqual(self.erro(api.handle, "POST", rest, {"tk": tk}, ADM), (403, MSG_ADM), rest + " (maquina)")
        self.assertEqual(self.disco()["rev"], rev0)

    def test_rotas_so_do_adm_com_corpo_valido_ainda_dao_403(self):
        d = self.pedido(self.tk_h, "CNC")
        corpos = {"setor/salvar": {"modo": "novo", "id": "XXX", "nome": "Novo setor", "icone": "⚙️", "cor": "#3B82F6", "rev": 0},
                  "setor/ativar": {"id": "CNC", "rev": 1}, "setor/apagar": {"id": "ESP", "rev": 1},
                  "pessoa/salvar": {"modo": "novo", "nome": "Intruso", "setor": "CNC", "codigo": "0000", "rev": 0},
                  "pessoa/ativar": {"id": self.bruno, "rev": 1}, "pessoa/apagar": {"id": self.bruno, "rev": 1},
                  "demanda/prioridade": {"id": d, "prio": "urg"}, "demanda/estender": {"id": d, "minutos": 10},
                  "historico": {"de": 0, "ate": 10 ** 13}, "crono": {"dias": 7}, "cronograma": {"de": 0, "ate": 86400000}}
        antes = self.disco()
        for rest, corpo in corpos.items():
            self.assertEqual(self.erro(self.pes, self.tk_c, rest, corpo), (403, MSG_ADM), rest)
        self.assertEqual(self.disco(), antes)

    def test_so_adm_com_tk_ruim_e_401_antes_do_403(self):
        for rest in ROTAS_SO_ADM:
            self.assertEqual(self.erro(self.pes, "inventado", rest)[0], 401, rest)

    def test_sem_tk_no_papel_operador_toda_rota_de_ator_da_403(self):
        for rest in tuple(api.ESCRITAS) + tuple(api.LEITURAS) + ("anexo/enviar", "anexo/ler", "aviso/prefs"):
            if rest in ("entrar", "sair"):
                continue
            corpo = {"aid": "a" + "0" * 16} if rest == "anexo/ler" else {}   # id malformado dá 404 antes da identidade
            self.assertEqual(self.erro(api.handle, "POST", rest, corpo, OP), (403, MSG_IDENT), rest)
        self.assertEqual(self.erro(api.handle, "GET", "anexo/a0123456789abcdef", {}, OP)[0], 403)
        self.assertEqual(self.erro(api.handle, "POST", "anexo/ler", {}, OP)[0], 404)

    def test_sem_papel_nenhum_toda_rota_de_ator_da_403(self):
        for rest in ("vista", "demanda/criar", "setor/salvar", "historico", "aviso/prefs", "anexo/enviar"):
            for ctx in ({}, {"papel": None}, {"papel": "x"}):
                self.assertEqual(self.erro(api.handle, "POST", rest, {}, ctx), (403, MSG_IDENT), (rest, ctx))

    def test_adm_alcanca_as_rotas_de_adm_e_vira_escritorio(self):
        for ctx in (ADM, COMPLETO):
            self.assertIn("demandas", api.handle("POST", "historico", {"de": 0, "ate": 10 ** 13}, ctx))
            self.assertIn("dias", api.handle("POST", "crono", {"dias": 7}, ctx) | {"dias": 1})
        d = self.pedido(None, "CNC")
        v = self.adm("demanda/prioridade", {"id": d, "prio": "urg"})
        self.assertEqual(next(x for x in v["demandas"] if x["id"] == d)["prio"], "urg")
        self.assertEqual(self.disco()["demandas"][0]["eventos"][-1]["quem"], "Escritório")

    def test_rota_desconhecida_e_404_antes_da_identidade(self):
        for ctx in (OP, ADM, {}):
            self.assertEqual(self.erro(api.handle, "POST", "nada", {}, ctx)[0], 404)
            self.assertEqual(self.erro(api.handle, "GET", "nada", {}, ctx)[0], 404)
        self.assertEqual(self.erro(api.handle, "DELETE", "", {}, ADM)[0], 404)
        self.assertEqual(self.erro(api.handle, "GET", "entrar", {}, ADM)[0], 404)   # entrar só por POST

    def test_o_servidor_e_o_api_concordam_sobre_quais_rotas_sao_so_do_adm(self):
        """Toda rota que o api.py recusa à pessoa com 403 "Só o escritório" tem de estar FORA do OPERADOR_RE do servidor,
        e toda rota que a pessoa usa tem de estar DENTRO: rota nova que esquecer um dos dois lados reprova aqui."""
        rotas = set(api.ESCRITAS) | set(api.LEITURAS) | {"entrar", "sair", "anexo/enviar", "anexo/ler", "aviso/prefs"}
        so_adm = set()
        for rest in sorted(rotas):
            if rest in ("entrar", "sair"):
                continue
            try:
                api.handle("POST", rest, {"tk": self.tk_c}, OP)
            except api.ApiError as exc:
                if exc.status == 403 and str(exc) == MSG_ADM:
                    so_adm.add(rest)
            except Exception:   # corpo vazio quebra a regra de negócio, não a identidade: serve
                pass
        self.assertEqual(so_adm, set(ROTAS_SO_ADM))
        for rest in rotas:
            liberada = bool(servidor.OPERADOR_RE.fullmatch("POST /api/local/demandas/" + rest))
            self.assertEqual(liberada, rest not in so_adm, rest)
        self.assertEqual(set(ROTAS_PESSOA), rotas - so_adm)


# ===================================================================================== o que a pessoa vê (calc.ve)
class VisaoDaPessoa(Base):
    def setUp(self):
        super().setUp()
        self.d1 = self.pedido(self.tk_h, "CNC", "Helena para CNC")
        self.d2 = self.pedido(self.tk_c, "ESP", "Carlos para ESP")
        self.d3 = self.pedido(self.tk_h, "ESP", "Helena para ESP")
        self.d4 = self.pedido(None, "CNC", "Escritório para CNC")
        self.d5 = self.pedido(self.tk_b, "ESP", "Bruno para ESP")
        self.por_pessoa = {"Helena": self.tk_h, "Carlos": self.tk_c, "Bruno": self.tk_b, "Fernanda": self.tk_f}

    def ids(self, tk):
        return {d["id"] for d in self.pes(tk, "vista")["demandas"]}

    def test_cada_pessoa_ve_o_setor_dela_e_o_que_ela_pediu(self):
        self.assertEqual(self.ids(self.tk_h), {self.d1, self.d3})                 # só o que ela pediu (PCP não recebe nada)
        self.assertEqual(self.ids(self.tk_c), {self.d1, self.d4, self.d2})        # destino CNC + o dela
        self.assertEqual(self.ids(self.tk_b), {self.d1, self.d4, self.d5})        # destino CNC + o dele; não vê o do Carlos
        self.assertEqual(self.ids(self.tk_f), {self.d2, self.d3, self.d5})        # destino ESP

    def test_colega_do_setor_de_origem_nao_ve_o_pedido_do_outro(self):
        self.assertNotIn(self.d5, self.ids(self.tk_c))
        self.assertNotIn(self.d2, self.ids(self.tk_b))

    def test_adm_ve_tudo(self):
        self.assertEqual({d["id"] for d in self.get()["demandas"]}, {self.d1, self.d2, self.d3, self.d4, self.d5})

    def test_a_vista_da_pessoa_bate_com_calc_ve_sobre_o_banco(self):
        doc = self.disco()
        for nome, tk in self.por_pessoa.items():
            p = next(x for x in doc["pessoas"] if x["nome"] == nome)
            esperado = {d["id"] for d in doc["demandas"] if calc.ve(d, p)}
            self.assertEqual(self.ids(tk), esperado, nome)

    def test_vista_da_pessoa_nao_traz_dados_de_adm(self):
        for tk in self.por_pessoa.values():
            v = self.pes(tk, "vista")
            self.assertNotIn("anexos_uso", v)
            self.assertEqual(v["papel"], "pessoa")
            self.assertTrue(all(n["aud"] != "adm" for n in v["notas"]))
            self.assertTrue(all(set(f) == {"t", "tipo", "dem", "msg"} for f in v["feed"]))
            self.assertTrue({f["dem"] for f in v["feed"]} <= {d["id"] for d in v["demandas"]})

    def test_notas_so_do_setor_e_da_pessoa(self):
        doc = self.disco()
        for nome, tk in self.por_pessoa.items():
            p = next(x for x in doc["pessoas"] if x["nome"] == nome)
            esperado = {n["id"] for n in doc["notas"] if n["aud"] == p["setor"] and n["pid"] in (None, p["id"])}
            self.assertEqual({n["id"] for n in self.pes(tk, "vista")["notas"]}, esperado, nome)
        adm = {n["id"] for n in self.get()["notas"]}
        self.assertEqual(adm, {n["id"] for n in doc["notas"] if n["aud"] == "adm"})

    def test_nota_de_outra_pessoa_nao_marca(self):
        nid = next(n["id"] for n in self.disco()["notas"] if n["aud"] == "ESP")
        self.assertEqual(self.erro(self.pes, self.tk_c, "nota/lida", {"nid": nid}), (403, "Notificação de outra pessoa."))
        self.assertEqual(self.erro(self.pes, self.tk_h, "nota/lida", {"nid": nid})[0], 403)
        self.assertEqual(self.erro(self.adm, "nota/lida", {"nid": nid})[0], 403)   # nem o ADM: é do setor ESP

    def test_anexo_so_para_quem_ve_a_demanda(self):
        self.pes(self.tk_h, "anexo/enviar", {"id": self.d1, "nome": "foto.jpg", "dados": B64})
        aid = self.disco()["demandas"][0]["anexos"][0]["id"]
        for tk in (self.tk_h, self.tk_c, self.tk_b):
            self.assertEqual(self.pes(tk, "anexo/ler", {"aid": aid})["nome"], "foto.jpg")
        self.assertEqual(self.erro(self.pes, self.tk_f, "anexo/ler", {"aid": aid}), (403, "Sem acesso a este anexo."))
        self.assertEqual(self.get("anexo/" + aid)["nome"], "foto.jpg")          # ADM pelo GET
        self.assertEqual(self.erro(self.get, "anexo/" + aid, OP)[0], 403)        # operador sem tk
        self.assertEqual(self.erro(self.pes, self.tk_c, "anexo/ler", {"aid": "a" + "0" * 16})[0], 404)
        for ruim in ("", None, 5, "../x", "a123"):
            self.assertEqual(self.erro(self.pes, self.tk_c, "anexo/ler", {"aid": ruim})[0], 404, repr(ruim))

    def test_pessoa_nao_age_em_demanda_que_nao_ve(self):
        for rest, corpo in (("demanda/comentar", {"texto": "oi"}), ("demanda/cobrar", {}), ("demanda/cancelar", {"motivo": "Outro"}),
                            ("demanda/aceitar", {})):
            status, _ = self.erro(self.pes, self.tk_f, rest, dict(corpo, id=self.d1))
            self.assertEqual(status, 403, rest)
        self.assertEqual(self.erro(self.pes, self.tk_h, "demanda/aceitar", {"id": self.d4})[0], 403)

    def test_criar_como_pessoa_usa_o_setor_dela_e_ignora_de_s(self):
        v = self.pes(self.tk_f, "demanda/criar", {"titulo": "Tentando passar por outro", "tipo": "dem", "motivo": "Outro",
                                                  "prio": "norm", "est": 60, "para": {"s": "CNC", "p": None}, "desc": "",
                                                  "de_s": "PCP"})
        nova = max(v["demandas"], key=lambda d: int(d["id"][4:]))
        self.assertEqual((nova["de"]["s"], nova["de"]["p"]), ("ESP", self.fer))


# ===================================================================================== servidor.py: autorização pelo HTTP
H_REDE = "X-Teste-Rede"


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = servidor.Server(("127.0.0.1", 0), servidor.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        servidor.NET_ON = False
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        self.data = Path(tempfile.mkdtemp(prefix="dem-qa-srv-"))
        self._env = mock.patch.dict(os.environ, {"DEMANDAS_DATA": str(self.data)})
        self._env.start()
        for c in (servidor.SESSIONS, servidor.FAILS):
            c.clear()
        servidor._REV.update(key=None, rev=0)
        servidor.NET_ON = False
        self.sapi = servidor.api_mod()
        self._iter = self.sapi.ITER
        self.sapi.ITER = 1000
        self.sapi._TK.clear()
        self.sapi._FAILS.clear()
        self.sapi.ds._CACHE.update(key=None, texto=None)
        self.sapi.ds._ARQ.update(key=None, demandas=[])
        orig = servidor.Handler._remote
        p = mock.patch.object(servidor.Handler, "_remote", lambda h: bool(h.headers.get(H_REDE)) or orig(h))
        p.start()
        self.addCleanup(p.stop)
        fs = mock.patch("os.fsync", lambda fd: None)
        fs.start()
        self.addCleanup(fs.stop)

    def tearDown(self):
        self.sapi.ITER = self._iter
        self.sapi._TK.clear()
        self.sapi._FAILS.clear()
        servidor.NET_ON = False
        for c in (servidor.SESSIONS, servidor.FAILS):
            c.clear()
        self._env.stop()

    def req(self, method, path, body=None, headers=None, rede=False, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            h = {"Host": host or ("10.0.0.5:%d" % self.port if rede else "127.0.0.1:%d" % self.port)}
            if rede:
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
        st, _, raw = self.post(rest, obj, headers, rede)
        self.assertEqual(st, 200, raw.decode("utf-8", "replace"))
        return json.loads(raw)

    def login(self, pin, rede=True):
        form = {"Content-Type": "application/x-www-form-urlencoded", "Origin": "http://10.0.0.5:%d" % self.port}
        st, h, _ = self.req("POST", "/api/login", ("pin=" + pin).encode(), form, rede=rede)
        self.assertEqual(st, 303)
        return {"Cookie": h["Set-Cookie"].split(";")[0]}

    def mundo(self):
        self.ok("setor/salvar", {"modo": "novo", "id": "CNC", "nome": "Corte CNC", "icone": "⚙️", "cor": "#3B82F6", "rev": 0})
        self.ok("setor/salvar", {"modo": "novo", "id": "ESP", "nome": "Espumação", "icone": "🧰", "cor": "#10B981", "rev": 0})
        self.ok("pessoa/salvar", {"modo": "novo", "nome": "Carlos", "setor": "CNC", "codigo": "1234", "rev": 0})
        self.ok("pessoa/salvar", {"modo": "novo", "nome": "Fernanda", "setor": "ESP", "codigo": "4321", "rev": 0})

    def rede_on(self):
        servidor.NET_ON = True

    def sessao(self, papel):
        cfg = servidor.net_config()
        return self.login(cfg["pin"] if papel == "completo" else cfg["pin_op"])


class AuthRede(Http):
    def test_o_proprio_pc_e_maquina_sem_cookie(self):
        st, _, raw = self.req("GET", "/api/eu")
        self.assertEqual((st, json.loads(raw)), (200, {"papel": "maquina", "modo": servidor.MODO}))
        self.assertEqual(json.loads(self.req("GET", "/api/local/demandas")[2])["papel"], "adm")

    def test_rede_desligada_barra_tudo_da_rede(self):
        for path in ("/", "/api/eu", "/api/local/demandas"):
            st, _, raw = self.req("GET", path, host="127.0.0.1:%d" % self.port, headers={H_REDE: "1"})
            self.assertEqual((st, raw.decode()), (403, "Acesso pela rede desligado."), path)
        self.assertEqual(self.req("POST", "/api/local/demandas/vista", {}, {H_REDE: "1"},
                                  host="127.0.0.1:%d" % self.port)[0], 403)

    def test_sem_sessao_na_rede(self):
        self.rede_on()
        st, _, raw = self.req("GET", "/", rede=True)
        self.assertEqual(st, 200)
        self.assertIn(b'name="pin"', raw)
        self.assertEqual(self.req("HEAD", "/", rede=True)[0], 200)
        for path in ("/index.html", "/index.html?x=1"):
            self.assertIn(b'name="pin"', self.req("GET", path, rede=True)[2])
        for path in ("/api/eu", "/api/rev", "/api/local/demandas", "/app.js", "/local/demandas/demandas.js", "/api/rede"):
            st, _, raw = self.req("GET", path, rede=True)
            self.assertEqual((st, raw.decode()), (401, "Entre com o PIN."), path)
        st, _, raw = self.post("vista", {}, rede=True)
        self.assertEqual((st, raw.decode()), (401, "Entre com o PIN."))

    def test_cookie_falso_de_outro_nome_ou_vencido_nao_vale(self):
        self.rede_on()
        h = self.sessao("completo")
        valor = h["Cookie"].split("=", 1)[1]
        for cookie in ("demandas_s=inventado", "outro=" + valor, "demandas_s=", "demandas_s", valor):
            self.assertEqual(self.req("GET", "/api/eu", headers={"Cookie": cookie}, rede=True)[0], 401, cookie)
        for s in servidor.SESSIONS.values():
            s["exp"] = time.time() - 1
        self.assertEqual(self.req("GET", "/api/eu", headers=h, rede=True)[0], 401)

    def test_pin_errado_nao_da_cookie_e_pin_certo_define_o_papel(self):
        self.rede_on()
        form = {"Content-Type": "application/x-www-form-urlencoded"}
        st, h, raw = self.req("POST", "/api/login", b"pin=000000", form, rede=True)
        self.assertEqual(st, 200)
        self.assertNotIn("Set-Cookie", h)
        self.assertIn("PIN errado".encode(), raw)
        cfg = servidor.net_config()
        self.assertNotEqual(cfg["pin"], cfg["pin_op"])
        for pin, papel in ((cfg["pin"], "completo"), (cfg["pin_op"], "operador"), ("  %s " % cfg["pin_op"], "operador")):
            h = self.login(pin)
            self.assertEqual(json.loads(self.req("GET", "/api/eu", headers=h, rede=True)[2])["papel"], papel)

    def test_cookie_sem_httponly_nem_samesite_nao_existe(self):
        self.rede_on()
        form = {"Content-Type": "application/x-www-form-urlencoded"}
        st, h, _ = self.req("POST", "/api/login", ("pin=" + servidor.net_config()["pin"]).encode(), form, rede=True)
        self.assertEqual(st, 303)
        c = h["Set-Cookie"]
        for atributo in ("HttpOnly", "SameSite=Strict", "Path=/", "Max-Age=%d" % (servidor.SESSION_DAYS * 86400)):
            self.assertIn(atributo, c)

    def test_login_do_proprio_pc_nao_existe(self):
        self.rede_on()
        st, _, raw = self.req("POST", "/api/login", b"pin=1", {"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual((st, raw.decode()), (403, "Acesso pela rede desligado."))

    def test_origem_estranha_e_host_estranho(self):
        self.rede_on()
        h = self.sessao("completo")
        st, _, raw = self.req("POST", "/api/local/demandas/vista", {}, dict(h, Origin="http://evil.example"), rede=True)
        self.assertEqual((st, raw.decode()), (403, "Origem não aceita."))
        self.assertEqual(self.req("GET", "/api/eu", headers=h, host="evil.example:%d" % self.port, rede=True)[0], 421)
        self.assertEqual(self.req("GET", "/api/eu", host="evil.example:%d" % self.port)[0], 421)   # nem do próprio PC
        self.assertEqual(self.req("GET", "/api/eu", headers=h, host="10.0.0.5", rede=True)[0], 421)   # sem porta
        self.assertEqual(self.req("GET", "/api/eu", headers=h, host="10.0.0.5:1", rede=True)[0], 421)   # porta errada

    def test_sessao_de_papel_desconhecido_fecha_em_403(self):
        self.rede_on()
        h = self.sessao("completo")
        for s in servidor.SESSIONS.values():
            s["papel"] = "superadmin"
        for path in ("/api/eu", "/api/local/demandas", "/api/rede", "/"):
            st, _, raw = self.req("GET", path, headers=h, rede=True)
            self.assertEqual((st, raw.decode()), (403, servidor.OPERADOR_MSG), path)

    def test_so_o_pc_principal_configura(self):
        self.rede_on()
        completo, oper = self.sessao("completo"), self.sessao("operador")
        pc = self.req("GET", "/api/rede")
        self.assertEqual(pc[0], 200)
        for path in ("/api/rede", "/api/backup", "/api/email", "/api/avisos", "/api/servidor"):
            self.assertEqual(self.req("GET", path)[0], 200, path + " (pc)")
            self.assertEqual(self.req("GET", path, headers=completo, rede=True)[0], 403, path + " (completo)")
            self.assertEqual(self.req("GET", path, headers=oper, rede=True)[0], 403, path + " (operador)")
        for path in ("/api/rede", "/api/backup", "/api/email", "/api/avisos"):
            self.assertEqual(self.req("POST", path, {}, completo, rede=True)[0], 403, path)

    def test_pins_novos_derrubam_as_sessoes_certas(self):
        self.rede_on()
        completo, oper = self.sessao("completo"), self.sessao("operador")
        self.assertEqual(self.req("POST", "/api/rede", {"newpin_op": True})[0], 200)
        self.assertEqual(self.req("GET", "/api/eu", headers=oper, rede=True)[0], 401)
        self.assertEqual(self.req("GET", "/api/eu", headers=completo, rede=True)[0], 200)
        self.assertEqual(self.req("POST", "/api/rede", {"newpin": True})[0], 200)
        self.assertEqual(self.req("GET", "/api/eu", headers=completo, rede=True)[0], 401)

    def test_pin_5_erros_travam_o_ip_por_5_minutos(self):
        cfg = servidor.net_config()
        for _ in range(4):
            self.assertIsNone(servidor.check_pin("10.1.1.1", "999999", now=100))
        self.assertTrue(servidor.check_pin("10.1.1.1", cfg["pin_op"], now=100))
        for _ in range(5):
            self.assertIsNone(servidor.check_pin("10.1.1.1", "999999", now=100))
        self.assertIsNone(servidor.check_pin("10.1.1.1", cfg["pin"], now=399.9))
        self.assertTrue(servidor.check_pin("10.1.1.1", cfg["pin"], now=400.1))
        self.assertTrue(servidor.check_pin("10.1.1.2", cfg["pin"], now=100))


class AuthOperador(Http):
    PERMITIDAS = (("GET", "/"), ("GET", "/index.html"), ("GET", "/app.js"), ("GET", "/api/eu"), ("GET", "/api/rev"),
                  ("GET", "/api/local/demandas"), ("HEAD", "/"), ("HEAD", "/api/eu"), ("HEAD", "/api/rev"),
                  ("GET", "/local/demandas/demandas.js"), ("GET", "/local/demandas/demandas.css"),
                  ("GET", "/local/demandas/figtree.woff2"), ("GET", "/local/demandas/demandas-fontes.css"),
                  ("GET", "/index.html?x=1"), ("GET", "/api/eu?x=1"))
    NEGADAS = (("GET", "/api/rede"), ("GET", "/api/backup"), ("GET", "/api/email"), ("GET", "/api/avisos"),
               ("GET", "/api/servidor"), ("GET", "/api/local/demandas/vista"), ("GET", "/api/local/demandas/"),
               ("GET", "/api/local/demandas/anexo/a0123456789abcdef"), ("GET", "/api/local/demandas/historico"),
               ("GET", "/api/eu/"), ("GET", "/API/EU"), ("GET", "/api/rev/"), ("GET", "/index.htm"),
               ("GET", "/App.js"), ("GET", "/local/demandas/"), ("GET", "/local/demandas/../servidor.py"),
               ("GET", "/local/demandas/.hidden"), ("GET", "/local/demandas/a/b.js"), ("GET", "/local/demandas/x%20y.js"),
               ("GET", "/local/demandas/" + "a" * 61), ("GET", "/servidor.py"), ("GET", "/data/demandas.json"),
               ("HEAD", "/api/rede"), ("HEAD", "/api/local/demandas/vista"), ("GET", "/nada"))

    def preparo(self):
        self.rede_on()
        self.mundo()
        return self.sessao("operador")

    def test_permitidas(self):
        h = self.preparo()
        for metodo, path in self.PERMITIDAS:
            st, _, raw = self.req(metodo, path, headers=h, rede=True)
            self.assertEqual(st, 200, "%s %s -> %s %r" % (metodo, path, st, raw[:60]))

    def test_negadas(self):
        h = self.preparo()
        for metodo, path in self.NEGADAS:
            st, _, raw = self.req(metodo, path, headers=h, rede=True)
            if metodo != "HEAD":
                self.assertEqual((st, raw.decode()), (403, servidor.OPERADOR_MSG), "%s %s" % (metodo, path))
            else:
                self.assertEqual(st, 403, "%s %s" % (metodo, path))

    def test_metodos_que_o_servidor_nao_tem(self):
        h = self.preparo()
        for metodo in ("PUT", "DELETE", "PATCH", "OPTIONS"):
            self.assertEqual(self.req(metodo, "/api/local/demandas/setor/salvar", {}, h, rede=True)[0], 501, metodo)

    def test_get_na_rota_de_post_e_post_na_rota_de_get(self):
        h = self.preparo()
        for rest in ("entrar", "sair", "demanda/criar", "aviso/prefs"):
            self.assertEqual(self.req("GET", "/api/local/demandas/" + rest, headers=h, rede=True)[0], 403, rest)
        self.assertEqual(self.req("POST", "/api/local/demandas", {}, h, rede=True)[0], 403)
        self.assertEqual(self.req("POST", "/api/eu", {}, h, rede=True)[0], 403)
        self.assertEqual(self.req("POST", "/api/rev", {}, h, rede=True)[0], 403)

    def test_rotas_so_do_adm_pelo_operador_com_ou_sem_tk(self):
        h = self.preparo()
        tk = self.ok("entrar", {"pessoa": "p0", "codigo": "1234"}, h, rede=True)["tk"]
        for rest in ROTAS_SO_ADM + ("entrar/", "entrar/../setor/salvar", "demanda/criar/x", "demanda/", "demanda/prioridade",
                                    "demanda/estender", "anexo/", "anexo/x", "nota/", "aviso/", "vista/", "SAIR", "Entrar",
                                    "demanda/criar%20", "sair?x=1/../setor/salvar"):
            for corpo in ({}, {"tk": tk}):
                st, _, raw = self.post(rest, corpo, h, rede=True)
                if rest == "sair?x=1/../setor/salvar":   # a consulta é descartada: é "sair", rota de operador
                    self.assertEqual(st, 200, rest)
                    continue
                self.assertEqual((st, raw.decode()), (403, servidor.OPERADOR_MSG), rest)

    def test_rotas_de_pessoa_pelo_operador(self):
        h = self.preparo()
        self.assertEqual(self.post("vista", {}, h, rede=True)[2].decode(), MSG_IDENT)   # sem tk: aqui não existe Escritório
        r = self.ok("entrar", {"pessoa": "p0", "codigo": "1234"}, h, rede=True)
        self.assertEqual((r["eu"]["nome"], r["vista"]["papel"]), ("Carlos", "pessoa"))
        tk = r["tk"]
        self.assertEqual(self.ok("vista", {"tk": tk}, h, rede=True)["papel"], "pessoa")
        v = self.ok("demanda/criar", {"tk": tk, "titulo": "Afiar a fresa", "tipo": "man", "motivo": "Outro", "prio": "norm",
                                      "est": 30, "para": {"s": "ESP", "p": None}, "desc": ""}, h, rede=True)
        self.assertEqual(len(v["demandas"]), 1)
        self.assertEqual(self.ok("aviso/prefs", {"tk": tk}, h, rede=True)["prefs"]["urgente_fura"], True)
        self.assertEqual(self.ok("sair", {"tk": tk}, h, rede=True), {"ok": True})
        self.assertEqual(self.post("vista", {"tk": tk}, h, rede=True)[0], 401)

    def test_lista_publica_do_operador_pelo_http(self):
        h = self.preparo()
        pub = json.loads(self.req("GET", "/api/local/demandas", headers=h, rede=True)[2])
        self.assertEqual(sorted(pub), ["pessoas", "setores"])
        for x in ("sal", "hash", "email"):
            self.assertNotIn(x, json.dumps(pub))

    def test_negado_nao_executa_nada(self):
        h = self.preparo()
        antes = (self.data / "demandas.json").read_bytes()
        self.post("setor/salvar", {"modo": "novo", "id": "XXX", "nome": "Setor invasor", "icone": "⚙️", "cor": "#3B82F6",
                                   "rev": 0}, h, rede=True)
        self.post("pessoa/apagar", {"id": "p0", "rev": 1}, h, rede=True)
        self.assertEqual((self.data / "demandas.json").read_bytes(), antes)


class AuthCompleto(Http):
    def test_pin_completo_na_rede_tem_as_rotas_de_adm_mas_nao_a_configuracao(self):
        self.rede_on()
        h = self.sessao("completo")
        self.assertEqual(json.loads(self.req("GET", "/api/eu", headers=h, rede=True)[2])["papel"], "completo")
        self.assertEqual(json.loads(self.req("GET", "/api/local/demandas", headers=h, rede=True)[2])["papel"], "adm")
        self.ok("setor/salvar", {"modo": "novo", "id": "CNC", "nome": "Corte CNC", "icone": "⚙️", "cor": "#3B82F6", "rev": 0}, h,
                True)
        self.assertEqual(self.post("historico", {"de": 0, "ate": 10 ** 13}, h, rede=True)[0], 200)
        self.assertEqual(self.post("crono", {"dias": 7}, h, rede=True)[0], 200)
        self.assertEqual(self.req("GET", "/api/rede", headers=h, rede=True)[0], 403)

    def test_pessoa_no_pc_principal_tambem_e_so_pessoa(self):
        self.mundo()
        tk = self.ok("entrar", {"pessoa": "p0", "codigo": "1234"})["tk"]
        st, _, raw = self.post("setor/ativar", {"tk": tk, "id": "CNC", "rev": 1})
        self.assertEqual((st, raw.decode()), (403, MSG_ADM))
        self.assertEqual(self.ok("vista", {"tk": tk})["papel"], "pessoa")

    def test_bloqueio_e_token_pelo_http(self):
        self.mundo()
        for _ in range(5):
            self.assertEqual(self.post("entrar", {"pessoa": "p0", "codigo": "0000"})[0], 403)
        st, _, raw = self.post("entrar", {"pessoa": "p0", "codigo": "1234"})
        self.assertEqual((st, raw.decode()), (429, MSG_BLOQ))
        self.assertEqual(self.post("entrar", {"pessoa": "p1", "codigo": "4321"})[0], 200)
        st, _, raw = self.post("vista", {"tk": "inventado"})
        self.assertEqual((st, raw.decode()), (401, MSG_TK))
        self.assertEqual(self.post("entrar", {"pessoa": "p9", "codigo": "1234"})[0], 404)
        self.assertEqual(self.req("POST", "/api/local/demandas/entrar", b"{x")[0], 400)
        self.assertEqual(self.req("POST", "/api/local/demandas/entrar", b"[1]")[0], 400)


if __name__ == "__main__":
    unittest.main()
