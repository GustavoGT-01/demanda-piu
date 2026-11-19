"""QA do ciclo da solicitação e dos anexos (sessão C da bateria de testes).

Cobre, depois que a demanda existe: aceitar, pausar, retomar, concluir, repassar, cancelar, cobrar, prioridade,
estender, comentar, anexos (enviar, ler, apagar), a máquina de estados inteira (ação x situação x quem), os eventos
da linha do tempo, os avisos do sino, os limites de cada campo e o ciclo completo com o horário de serviço ligado e
desligado. A tela (botões e modais) está em tests/check_ciclo.js; a matriz de cobertura, em docs/qa/ciclo.md.

Dados num diretório temporário (DEMANDAS_DATA) por teste; relógio e pbkdf2 trocados para o teste ser rápido.
Teste de bug confirmado fica como @unittest.expectedFailure ("known-bug") até alguém corrigir o código: quando o
bug for corrigido o teste passa "inesperadamente" e a marca deve sair.
"""

import base64
import datetime
import importlib.util
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

_spec = importlib.util.spec_from_file_location("demandas_api_qa_ciclo", HERE / "api.py")
api = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(api)
ITER_REAL = api.ITER

MIN = 60000
HORA = 60 * MIN
T0 = 1_800_000_000_000
ADM = {"papel": "maquina"}
ADM_PIN = {"papel": "completo"}
OP = {"papel": "operador"}
JPG = b"\xff\xd8\xff\xe0" + b"j" * 40
PNG = b"\x89PNG\r\n\x1a\n" + b"p" * 40
PDF = b"%PDF-1.4\n" + b"d" * 40
B64 = base64.b64encode(JPG).decode()


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def loc(a, m, d, h=0, mi=0):
    return int(datetime.datetime(a, m, d, h, mi).timestamp() * 1000)


class Base(unittest.TestCase):
    """Cenário: PCP (Helena p0), CNC (Carlos p1, Bruno p2), ESP (Fernanda p3); todos com token."""

    def setUp(self):
        self._data = os.environ.get("DEMANDAS_DATA")
        self.dir = Path(tempfile.mkdtemp(prefix="dem-qa-ciclo-"))
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

    def arquivos(self):
        pasta = self.dir / "demandas-anexos"
        return sorted(p.name for p in pasta.iterdir()) if pasta.exists() else []

    def setor(self, sid, nome, icone="⚙️", cor="#3B82F6"):
        return self.adm("setor/salvar", {"modo": "novo", "id": sid, "nome": nome, "icone": icone, "cor": cor, "rev": 0})

    def pessoa(self, nome, setor, codigo):
        v = self.adm("pessoa/salvar", {"modo": "novo", "nome": nome, "setor": setor, "codigo": codigo, "rev": 0})
        return v["pessoas"][-1]["id"]

    def entrar(self, pid, codigo, ctx=OP):
        return api.handle("POST", "entrar", {"pessoa": pid, "codigo": codigo}, ctx)["tk"]

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
        self.tks = {"helena": self.tk_h, "carlos": self.tk_c, "bruno": self.tk_b, "fer": self.tk_f}

    def nova(self, tk=None, **kw):
        body = {"titulo": "Cortar chapas", "tipo": "dem", "motivo": "Outro", "prio": "norm", "est": 60,
                "para": {"s": "CNC", "p": None}, "desc": ""}
        body.update(kw)
        v = self.pes(tk, "demanda/criar", body) if tk else self.adm("demanda/criar", dict({"de_s": "PCP"}, **body))
        return max(v["demandas"], key=lambda d: int(d["id"][4:]))

    def dem(self, did):
        return next(d for d in self.disco()["demandas"] if d["id"] == did)

    def evs(self, did):
        return [e["ev"] for e in self.dem(did)["eventos"]]

    def notas(self, aud=None):
        return [(n["aud"], n["tipo"], n["dem"]) for n in self.disco()["notas"] if aud is None or n["aud"] == aud]

    def chama(self, ator, rest, body):
        """ator: "adm" (o Escritório, sem token) ou o nome de uma pessoa do cenário."""
        return self.adm(rest, body) if ator == "adm" else self.pes(self.tks[ator], rest, body)

    # --- demanda em cada situação (pedida pela Helena, de PCP para CNC) ---
    def prepara(self, st, **kw):
        did = self.nova(self.tk_h, **kw)["id"]
        if st == "new":
            return did
        self.pes(self.tk_c, "demanda/aceitar", {"id": did})
        if st == "prog":
            return did
        if st == "pause":
            self.pes(self.tk_c, "demanda/pausar", {"id": did, "motivo": "Máquina parada"})
            return did
        if st == "done":
            self.pes(self.tk_c, "demanda/concluir", {"id": did})
            return did
        if st == "canc":
            self.adm("demanda/cancelar", {"id": did})
            return did
        raise AssertionError(st)


# =====================================================================================================
# 1. Máquina de estados: ação x situação x quem faz (contrato: "Rotas" e "Domínios fixos")
# =====================================================================================================

ATIVAS = ("new", "prog", "pause")
SITUACOES = ("new", "prog", "pause", "done", "canc")
ATORES = ("adm", "helena", "carlos", "bruno", "fer")   # Helena pediu; Carlos atende (responsável fora de "new")

# ação -> (rota, corpo, situação final se der certo, último evento se der certo)
ACOES = {
    "aceitar": ("demanda/aceitar", lambda d: {"id": d}, "prog", "started"),
    "pausar": ("demanda/pausar", lambda d: {"id": d, "motivo": "Máquina parada"}, "pause", "paused"),
    "retomar": ("demanda/retomar", lambda d: {"id": d}, "prog", "resumed"),
    "concluir": ("demanda/concluir", lambda d: {"id": d, "nota": "feito"}, "done", "done"),
    "cancelar": ("demanda/cancelar", lambda d: {"id": d, "motivo": "duplicada"}, "canc", "canc"),
    "reatribuir": ("demanda/reatribuir", lambda d: {"id": d, "s": "ESP", "p": None}, "new", "reassigned"),
    "cobrar": ("demanda/cobrar", lambda d: {"id": d}, None, "nudge"),
    "prioridade": ("demanda/prioridade", lambda d: {"id": d, "prio": "high"}, None, "prio"),
    "estender": ("demanda/estender", lambda d: {"id": d, "minutos": 10}, None, "deadline"),
    "comentar": ("demanda/comentar", lambda d: {"id": d, "texto": "olá"}, None, None),
    "anexar": ("anexo/enviar", lambda d: {"id": d, "nome": "foto.jpg", "dados": B64}, None, "attach"),
}


def esperado(acao, st, ator):
    """O que o contrato manda: None = dá certo; número = status do erro. Escrito à parte do api.py de propósito."""
    destino = ator in ("carlos", "bruno")                   # pessoa do setor que atende
    resp = ator == "carlos" and st != "new"                 # responsável: quem aceitou (na fila ninguém é)
    ativa = st in ATIVAS
    pediu = ator in ("adm", "helena")                       # o Escritório ou quem pediu
    if acao == "aceitar":
        return 403 if not destino else (409 if st != "new" else None)
    if acao == "pausar":
        return 403 if not resp else (409 if st != "prog" else None)
    if acao == "retomar":
        return 403 if not resp else (409 if st != "pause" else None)
    if acao == "concluir":
        return 403 if not resp else (409 if not ativa else None)
    if acao in ("cancelar", "cobrar"):
        return 403 if not pediu else (409 if not ativa else None)
    if acao == "reatribuir":
        pode = ator == "adm" or (destino and (st == "new" or resp))
        return 403 if not pode else (409 if not ativa else None)
    if acao in ("prioridade", "estender"):
        return 403 if ator != "adm" else (409 if not ativa else None)
    if acao == "comentar":
        return 403 if ator == "fer" else None
    if acao == "anexar":
        return 403 if ator == "fer" else (409 if st == "canc" else None)
    raise AssertionError(acao)


class Maquina(Base):
    def test_matriz_acao_situacao_ator(self):
        """11 ações x 5 situações x 5 quem = 275 casos: o resultado, o 4xx e que a falha não grava nada."""
        total = 0
        for acao, (rota, corpo, final, ultimo) in ACOES.items():
            for st in SITUACOES:
                for ator in ATORES:
                    with self.subTest(acao=acao, situacao=st, ator=ator):
                        did = self.prepara(st)
                        antes, arqs = self.disco(), self.arquivos()
                        quer = esperado(acao, st, ator)
                        if quer is None:
                            self.chama(ator, rota, corpo(did))
                            r = self.dem(did)
                            self.assertEqual(r["status"], final or st)
                            if ultimo:
                                self.assertEqual(r["eventos"][-1]["ev"], ultimo)
                            else:
                                self.assertEqual(len(r["eventos"]), len(self.evs(did)))
                        else:
                            self.assertEqual(self.erro(self.chama, ator, rota, corpo(did)), quer)
                            self.assertEqual(self.disco(), antes, "falha não pode gravar nada")
                            self.assertEqual(self.arquivos(), arqs, "falha não pode deixar arquivo órfão")
                        total += 1
        self.assertEqual(total, 275)

    def test_um_so_vencedor_ao_aceitar(self):
        did = self.nova(self.tk_h)["id"]
        self.pes(self.tk_c, "demanda/aceitar", {"id": did})
        self.assertEqual(self.msg(self.pes, self.tk_b, "demanda/aceitar", {"id": did}), "A demanda não está mais aberta.")
        self.assertEqual(self.dem(did)["para"]["p"], self.carlos)
        self.assertEqual(self.evs(did), ["created", "assigned", "started"])

    def test_aceitar_demanda_designada_a_outro_do_setor_vira_dele(self):
        did = self.nova(self.tk_h, para={"s": "CNC", "p": self.carlos})["id"]
        self.pes(self.tk_b, "demanda/aceitar", {"id": did})   # Bruno pega a que era do Carlos: documentado ("vira responsável")
        self.assertEqual((self.dem(did)["para"]["p"], self.dem(did)["status"]), (self.bruno, "prog"))
        self.assertEqual(self.dem(did)["eventos"][-2]["nota"], "Responsável: Bruno")

    def test_ciclo_pausa_retoma_varias_vezes(self):
        did = self.prepara("prog")
        for i in range(3):
            self.t += MIN
            self.pes(self.tk_c, "demanda/pausar", {"id": did, "motivo": api.PAUSAS[i]})
            self.t += MIN
            self.pes(self.tk_c, "demanda/retomar", {"id": did})
        r = self.dem(did)
        self.assertEqual([p["motivo"] for p in r["pausas"]], list(api.PAUSAS[:3]))
        self.assertTrue(all(p["fim"] is not None for p in r["pausas"]))
        self.assertEqual(r["status"], "prog")

    def test_nenhuma_transicao_sai_de_done_ou_canc(self):
        """Encerrada é para sempre: nenhuma ação de mudança de estado (nem do ADM) reabre."""
        for st in ("done", "canc"):
            did = self.prepara(st)
            for acao in ("aceitar", "pausar", "retomar", "concluir", "cancelar", "reatribuir"):
                rota, corpo, _, _ = ACOES[acao]
                for ator in ATORES:
                    with self.subTest(situacao=st, acao=acao, ator=ator):
                        try:
                            self.chama(ator, rota, corpo(did))
                        except api.ApiError:
                            pass
                        self.assertEqual(self.dem(did)["status"], st)

    def test_concluir_pausada_fecha_a_pausa_e_o_fim_e_um_so(self):
        did = self.prepara("pause")
        self.t += 7 * MIN
        self.pes(self.tk_c, "demanda/concluir", {"id": did})
        r = self.dem(did)
        self.assertEqual((r["pausas"][0]["fim"], r["fim"], r["status"]), (self.t, self.t, "done"))

    def test_cancelar_pausada_fecha_a_pausa(self):
        did = self.prepara("pause")
        self.t += 3 * MIN
        self.pes(self.tk_h, "demanda/cancelar", {"id": did})
        r = self.dem(did)
        self.assertEqual((r["pausas"][0]["fim"], r["fim"], r["status"]), (self.t, self.t, "canc"))

    def test_repassar_de_setor_zera_responsavel_inicio_e_pausa(self):
        for st in ("prog", "pause"):
            did = self.prepara(st)
            self.t += MIN
            self.pes(self.tk_c, "demanda/reatribuir", {"id": did, "s": "ESP", "p": self.fer, "nota": "é com vocês"})
            r = self.dem(did)
            self.assertEqual((r["status"], r["iniciado"], r["para"]), ("new", None, {"s": "ESP", "p": self.fer}), st)
            self.assertTrue(all(p["fim"] is not None for p in r["pausas"]))
            # quem repassou saiu do jogo: não pode mais agir nem repassar (não é do setor novo)
            self.assertEqual(self.erro(self.pes, self.tk_c, "demanda/reatribuir", {"id": did, "s": "CNC"}), 403, st)
            self.pes(self.tk_f, "demanda/aceitar", {"id": did})
            self.assertEqual(self.dem(did)["status"], "prog")

    def test_repassar_para_a_fila_do_mesmo_setor(self):
        did = self.prepara("prog")
        self.pes(self.tk_c, "demanda/reatribuir", {"id": did, "s": "CNC", "p": None})
        r = self.dem(did)
        self.assertEqual((r["status"], r["iniciado"], r["para"]), ("new", None, {"s": "CNC", "p": None}))
        self.pes(self.tk_b, "demanda/aceitar", {"id": did})   # a fila: qualquer um do setor pega
        self.assertEqual(self.dem(did)["para"]["p"], self.bruno)

    def test_repassar_mesma_pessoa_nao_muda_o_estado(self):
        did = self.prepara("prog")
        self.pes(self.tk_c, "demanda/reatribuir", {"id": did, "s": "CNC", "p": self.carlos, "nota": "só registrando"})
        r = self.dem(did)
        self.assertEqual((r["status"], r["para"]["p"]), ("prog", self.carlos))
        self.assertEqual(r["eventos"][-1]["nota"], "Para CNC · Carlos — só registrando")

    def test_repassar_pausada_para_outro_do_setor_segue_pausada(self):
        did = self.prepara("pause")
        self.pes(self.tk_c, "demanda/reatribuir", {"id": did, "s": "CNC", "p": self.bruno})
        r = self.dem(did)
        self.assertEqual((r["status"], r["para"]["p"], r["pausas"][0]["fim"]), ("pause", self.bruno, None))
        self.pes(self.tk_b, "demanda/retomar", {"id": did})   # agora é do Bruno retomar
        self.assertEqual(self.dem(did)["status"], "prog")
        self.assertEqual(self.erro(self.pes, self.tk_c, "demanda/pausar", {"id": did, "motivo": "Máquina parada"}), 403)

    def test_pessoa_desativada_devolve_a_fila_e_perde_o_token(self):
        did = self.prepara("prog")
        p = next(x for x in self.disco()["pessoas"] if x["id"] == self.carlos)
        self.adm("pessoa/ativar", {"id": self.carlos, "rev": p["_rv"]})
        r = self.dem(did)
        self.assertEqual((r["status"], r["para"]["p"], r["iniciado"]), ("new", None, None))
        self.assertEqual(self.erro(self.pes, self.tk_c, "demanda/concluir", {"id": did}), 401)
        self.pes(self.tk_b, "demanda/aceitar", {"id": did})
        self.assertEqual(self.dem(did)["para"]["p"], self.bruno)


# =====================================================================================================
# 2. Quem pode: 401 / 403 por papel e por token (backend; a tela só esconde o botão)
# =====================================================================================================

ROTAS_ACAO = ("demanda/aceitar", "demanda/pausar", "demanda/retomar", "demanda/concluir", "demanda/cancelar",
              "demanda/reatribuir", "demanda/cobrar", "demanda/prioridade", "demanda/estender", "demanda/comentar",
              "anexo/enviar", "anexo/apagar")


class Permissao(Base):
    def corpo(self, did):
        return {"id": did, "motivo": "Máquina parada", "s": "CNC", "prio": "high", "minutos": 5, "texto": "x",
                "nome": "a.jpg", "dados": B64, "aid": "a" + "0" * 16}

    def test_operador_sem_token_e_403_em_toda_acao(self):
        did = self.prepara("prog")
        for rota in ROTAS_ACAO:
            with self.subTest(rota=rota):
                self.assertEqual(self.erro(self.adm, rota, self.corpo(did), ctx=OP), 403)
                self.assertEqual(self.msg(self.adm, rota, self.corpo(did), ctx=OP), "Identifique-se para usar as demandas.")

    def test_token_ruim_ou_vencido_e_401_em_toda_acao(self):
        did = self.prepara("prog")
        for rota in ROTAS_ACAO:
            for tk in ("tk-que-nao-existe", "", 7):
                with self.subTest(rota=rota, tk=tk):
                    self.assertEqual(self.erro(self.pes, tk, rota, self.corpo(did)), 401)
        self.clk += api.TK_VIDA_S + 1   # 12 h depois
        self.assertEqual(self.erro(self.pes, self.tk_c, "demanda/pausar", self.corpo(did)), 401)
        self.assertEqual(self.dem(did)["status"], "prog")

    def test_token_sai_com_sair(self):
        did = self.prepara("prog")
        self.adm("sair", {"tk": self.tk_c}, ctx=OP)
        self.assertEqual(self.erro(self.pes, self.tk_c, "demanda/pausar", self.corpo(did)), 401)

    def test_papeis_do_escritorio_agem_sem_token(self):
        did = self.nova()["id"]
        for ctx in (ADM, ADM_PIN):
            self.adm("demanda/cobrar", {"id": did}, ctx=ctx)
            self.adm("demanda/comentar", {"id": did, "texto": "oi"}, ctx=ctx)
            self.adm("demanda/prioridade", {"id": did, "prio": "low" if ctx is ADM else "high"}, ctx=ctx)
        self.assertEqual(self.erro(self.adm, "demanda/cobrar", {"id": did}, ctx={"papel": "visitante"}), 403)
        self.assertEqual(self.erro(self.adm, "demanda/cobrar", {"id": did}, ctx={}), 403)

    def test_adm_com_token_age_como_a_pessoa_e_nao_como_adm(self):
        """Quem manda tk é a pessoa, mesmo vindo do PC principal: prioridade/estender (só ADM) dão 403."""
        did = self.prepara("prog")
        self.assertEqual(self.erro(self.pes, self.tk_h, "demanda/prioridade", {"id": did, "prio": "high"}, ctx=ADM), 403)
        self.assertEqual(self.erro(self.pes, self.tk_c, "demanda/estender", {"id": did, "minutos": 5}, ctx=ADM), 403)

    def test_so_adm_prioridade_e_estender(self):
        did = self.prepara("prog")
        for ator in ("helena", "carlos", "bruno", "fer"):
            for rota, corpo in (("demanda/prioridade", {"prio": "urg"}), ("demanda/estender", {"minutos": 5})):
                with self.subTest(ator=ator, rota=rota):
                    self.assertEqual(self.erro(self.chama, ator, rota, dict(corpo, id=did)), 403)
        self.assertEqual((self.dem(did)["prio"], self.dem(did)["est"]), ("norm", 60))

    def test_403_vem_antes_do_409_e_do_400(self):
        did = self.prepara("done")
        # quem não pode recebe 403 mesmo com o corpo inválido e a demanda encerrada
        self.assertEqual(self.erro(self.pes, self.tk_f, "demanda/cancelar", {"id": did, "motivo": "x" * 999}), 403)
        self.assertEqual(self.erro(self.pes, self.tk_h, "demanda/cobrar", {"id": did}), 409)
        self.assertEqual(self.erro(self.pes, self.tk_b, "demanda/concluir", {"id": did, "nota": "x" * 999}), 403)
        self.assertEqual(self.erro(self.pes, self.tk_c, "demanda/concluir", {"id": did, "nota": "x" * 999}), 409)

    def test_pessoa_de_outro_setor_nao_age_em_demanda_alheia(self):
        did = self.prepara("prog")
        for rota in ("demanda/pausar", "demanda/retomar", "demanda/concluir", "demanda/cancelar", "demanda/cobrar",
                     "demanda/reatribuir", "demanda/comentar", "anexo/enviar", "demanda/aceitar"):
            with self.subTest(rota=rota):
                self.assertEqual(self.erro(self.pes, self.tk_f, rota, self.corpo(did)), 403)

    def test_demanda_inexistente_e_id_malformado(self):
        for rota in ROTAS_ACAO:
            for did, quer in (("SOL-9", 404), ("SOL-0", 404), ("SOL-0001", 404), ("sol-1001", 400), ("SOL-", 400),
                              ("SOL-1234567890", 400), ("SOL-1;x", 400), ("", 400), (None, 400), (1001, 400),
                              (["SOL-1001"], 400), ({"a": 1}, 400)):
                with self.subTest(rota=rota, id=did):
                    self.assertEqual(self.erro(self.adm, rota, dict(self.corpo("x"), id=did)), quer)
        self.assertEqual(self.erro(self.adm, "demanda/cobrar", {}), 400)

    def test_corpo_que_nao_e_objeto_e_400(self):
        for corpo in ([], "x", 3, None):
            self.assertEqual(self.erro(api.handle, "POST", "demanda/cobrar", corpo, ADM), 400)


# =====================================================================================================
# 3. Limites de cada campo (exato e um além) e valores inválidos
# =====================================================================================================

class Limites(Base):
    def setUp(self):
        super().setUp()
        self.did = self.prepara("prog")

    def pausa(self, **kw):
        return self.pes(self.tk_c, "demanda/pausar", dict({"id": self.did, "motivo": "Máquina parada"}, **kw))

    def volta(self):
        self.pes(self.tk_c, "demanda/retomar", {"id": self.did})

    # --- pausar ---
    def test_pausa_os_seis_motivos(self):
        self.assertEqual(len(api.PAUSAS), 6)
        for motivo in api.PAUSAS:
            with self.subTest(motivo=motivo):
                self.pausa(motivo=motivo)
                self.assertEqual(self.dem(self.did)["pausas"][-1]["motivo"], motivo)
                self.assertEqual(self.dem(self.did)["eventos"][-1]["nota"], motivo)
                self.volta()

    def test_pausa_motivo_invalido(self):
        for ruim in ("Outro", "Falta de material", "aguardando material", "Aguardando material ", "", None, 3, ["Máquina parada"],
                     {"a": 1}, True):
            with self.subTest(motivo=ruim):
                self.assertEqual(self.erro(self.pausa, motivo=ruim), 400)
        body = {"id": self.did}   # motivo ausente
        self.assertEqual(self.erro(self.pes, self.tk_c, "demanda/pausar", body), 400)
        self.assertEqual(self.dem(self.did)["status"], "prog")

    def test_pausa_observacao_limite_500(self):
        self.pausa(obs="x" * 500)
        self.assertEqual(len(self.dem(self.did)["pausas"][-1]["obs"]), 500)
        self.volta()
        self.assertEqual(self.erro(self.pausa, obs="x" * 501), 400)
        self.assertEqual(self.msg(self.pausa, obs="x" * 501), "Observação: de 0 a 500 caracteres.")
        self.assertEqual(self.dem(self.did)["status"], "prog")

    def test_pausa_observacao_vazia_nula_e_espacos(self):
        for obs, quer in ((None, ""), ("", ""), ("   ", ""), ("  ok  ", "ok")):
            with self.subTest(obs=obs):
                self.pausa(obs=obs)
                self.assertEqual(self.dem(self.did)["pausas"][-1]["obs"], quer)
                self.assertEqual(self.dem(self.did)["eventos"][-1]["nota"], "Máquina parada" + (" — " + quer if quer else ""))
                self.volta()

    def test_pausa_espacos_nas_pontas_nao_contam_para_o_limite(self):
        self.pausa(obs="  " + "y" * 500 + "  ")
        self.assertEqual(self.dem(self.did)["pausas"][-1]["obs"], "y" * 500)

    def test_pausa_observacao_tipos_e_controles(self):
        for ruim in (3, True, ["a"], {"a": 1}, "a\nb", "a\tb", "a\rb", "a\x00b", "a\x1fb", "a\x7fb"):
            with self.subTest(obs=ruim):
                self.assertEqual(self.erro(self.pausa, obs=ruim), 400)

    def test_pausa_observacao_com_acento_e_emoji_conta_por_caractere(self):
        self.pausa(obs="ç" * 250 + "😀" * 250)   # 500 caracteres
        self.volta()
        self.assertEqual(self.erro(self.pausa, obs="ç" * 250 + "😀" * 251), 400)

    def test_pausa_teto_de_200_pausas_por_demanda(self):
        self.assertEqual(ds.MAX["pausas"], 200)
        with mock.patch.dict(ds.MAX, {"pausas": 3}):
            for _ in range(3):
                self.pausa()
                self.volta()
            self.assertEqual(self.erro(self.pausa), 400)
            self.assertEqual(self.dem(self.did)["status"], "prog")

    # --- concluir ---
    def test_concluir_observacao_limite_500(self):
        d2 = self.prepara("prog")
        self.pes(self.tk_c, "demanda/concluir", {"id": self.did, "nota": "n" * 500})
        self.assertEqual(self.dem(self.did)["eventos"][-1]["nota"], "n" * 500)
        self.assertEqual(self.erro(self.pes, self.tk_c, "demanda/concluir", {"id": d2, "nota": "n" * 501}), 400)
        self.assertEqual(self.dem(d2)["status"], "prog")

    def test_concluir_observacao_vazia_nula_ausente_e_invalida(self):
        for corpo in ({}, {"nota": None}, {"nota": ""}, {"nota": "   "}):
            with self.subTest(corpo=corpo):
                d = self.prepara("prog")
                self.pes(self.tk_c, "demanda/concluir", dict(corpo, id=d))
                self.assertEqual(self.dem(d)["eventos"][-1]["nota"], "")
        for ruim in (5, ["x"], "a\nb", "a\x00"):
            with self.subTest(nota=ruim):
                d = self.prepara("prog")
                self.assertEqual(self.erro(self.pes, self.tk_c, "demanda/concluir", {"id": d, "nota": ruim}), 400)
                self.assertEqual(self.dem(d)["status"], "prog")

    # --- cancelar ---
    def test_cancelar_motivo_limite_500(self):
        d2 = self.prepara("prog")
        self.pes(self.tk_h, "demanda/cancelar", {"id": self.did, "motivo": "m" * 500})
        self.assertEqual(self.dem(self.did)["eventos"][-1]["nota"], "m" * 500)
        self.assertEqual(self.erro(self.pes, self.tk_h, "demanda/cancelar", {"id": d2, "motivo": "m" * 501}), 400)
        self.assertEqual(self.dem(d2)["status"], "prog")

    def test_cancelar_motivo_vazio_nulo_ausente_e_invalido(self):
        for corpo in ({}, {"motivo": None}, {"motivo": ""}, {"motivo": "  "}):
            with self.subTest(corpo=corpo):
                d = self.prepara("prog")
                self.pes(self.tk_h, "demanda/cancelar", dict(corpo, id=d))
                self.assertEqual(self.dem(d)["eventos"][-1], {"t": T0, "ev": "canc", "quem": "Helena", "nota": ""})
        for ruim in (1, [], "a\nb", "\x00"):
            with self.subTest(motivo=ruim):
                d = self.prepara("prog")
                self.assertEqual(self.erro(self.pes, self.tk_h, "demanda/cancelar", {"id": d, "motivo": ruim}), 400)

    # --- repassar ---
    def test_repassar_observacao_limite_500(self):
        d2 = self.prepara("prog")
        self.pes(self.tk_c, "demanda/reatribuir", {"id": self.did, "s": "ESP", "p": None, "nota": "r" * 500})
        self.assertTrue(self.dem(self.did)["eventos"][-1]["nota"].endswith("r" * 500))
        self.assertEqual(self.erro(self.pes, self.tk_c, "demanda/reatribuir", {"id": d2, "s": "ESP", "nota": "r" * 501}), 400)
        self.assertEqual(self.dem(d2)["para"], {"s": "CNC", "p": self.carlos})

    def test_repassar_setor_e_pessoa_invalidos(self):
        casos = [({"s": "ZZ"}, 400), ({"s": None}, 400), ({"s": 5}, 400), ({}, 400), ({"s": "cnc"}, 400),
                 ({"s": "CNC", "p": self.fer}, 400), ({"s": "CNC", "p": "p999"}, 400), ({"s": "CNC", "p": 7}, 400),
                 ({"s": "ESP", "p": self.carlos}, 400)]
        for corpo, quer in casos:
            with self.subTest(corpo=corpo):
                self.assertEqual(self.erro(self.adm, "demanda/reatribuir", dict(corpo, id=self.did)), quer)
        self.assertEqual(self.dem(self.did)["para"], {"s": "CNC", "p": self.carlos})

    def test_repassar_para_setor_ou_pessoa_inativos(self):
        p = next(x for x in self.disco()["pessoas"] if x["id"] == self.bruno)
        self.adm("pessoa/ativar", {"id": self.bruno, "rev": p["_rv"]})
        self.assertEqual(self.erro(self.adm, "demanda/reatribuir", {"id": self.did, "s": "CNC", "p": self.bruno}), 400)
        self.setor("OFI", "Oficina")
        s = next(x for x in self.disco()["setores"] if x["id"] == "OFI")
        self.adm("setor/ativar", {"id": "OFI", "rev": s["_rv"]})
        self.assertEqual(self.erro(self.adm, "demanda/reatribuir", {"id": self.did, "s": "OFI"}), 400)

    def test_repassar_pessoa_vazia_vira_fila(self):
        for vazio in (None, ""):
            with self.subTest(p=vazio):
                d = self.prepara("prog")
                self.pes(self.tk_c, "demanda/reatribuir", {"id": d, "s": "CNC", "p": vazio})
                self.assertEqual(self.dem(d)["para"], {"s": "CNC", "p": None})

    # --- estender ---
    def test_estender_limites_um_e_1440(self):
        self.adm("demanda/estender", {"id": self.did, "minutos": 1})
        self.assertEqual(self.dem(self.did)["est"], 61)
        self.adm("demanda/estender", {"id": self.did, "minutos": 1440})
        self.assertEqual(self.dem(self.did)["est"], 1501)
        self.assertEqual(api.ESTENDER_MAX, 1440)

    def test_estender_invalidos(self):
        for ruim in (0, -1, 1441, 1_000_000, True, False, 1.5, 30.0, "30", None, [30], {"m": 1}):
            with self.subTest(minutos=ruim):
                self.assertEqual(self.erro(self.adm, "demanda/estender", {"id": self.did, "minutos": ruim}), 400)
        self.assertEqual(self.erro(self.adm, "demanda/estender", {"id": self.did}), 400)
        self.assertEqual(self.dem(self.did)["est"], 60)
        self.assertEqual(len(self.dem(self.did)["eventos"]), 3)

    def test_estender_teto_de_30_dias_no_minuto_exato(self):
        self.assertEqual(api.EST_MAX, 30 * 24 * 60)
        d = self.nova(est=api.EST_MAX - 1440)
        self.adm("demanda/estender", {"id": d["id"], "minutos": 1440})   # bate em 43200 exatos
        self.assertEqual(self.dem(d["id"])["est"], api.EST_MAX)
        self.assertEqual(self.msg(self.adm, "demanda/estender", {"id": d["id"], "minutos": 1}),
                         "O tempo estipulado passaria de 30 dias.")
        e = self.nova(est=api.EST_MAX - 1440 + 1)
        self.assertEqual(self.erro(self.adm, "demanda/estender", {"id": e["id"], "minutos": 1440}), 400)
        self.assertEqual(self.dem(e["id"])["est"], api.EST_MAX - 1439)

    def test_estender_varias_vezes_acumula_e_registra_cada_uma(self):
        for m in (30, 60, 5):
            self.adm("demanda/estender", {"id": self.did, "minutos": m})
        self.assertEqual(self.dem(self.did)["est"], 155)
        notas = [e["nota"] for e in self.dem(self.did)["eventos"] if e["ev"] == "deadline"]
        self.assertEqual(notas, ["+30 min", "+1h", "+5 min"])

    def test_estender_estende_o_prazo_na_vista(self):
        antes = self.adm("vista")["demandas"][0]["prazo"]
        v = self.adm("demanda/estender", {"id": self.did, "minutos": 90})
        self.assertEqual(next(x for x in v["demandas"] if x["id"] == self.did)["prazo"], antes + 90 * MIN)

    def test_estender_em_cada_situacao_ativa(self):
        for st in ATIVAS:
            with self.subTest(situacao=st):
                d = self.prepara(st)
                self.adm("demanda/estender", {"id": d, "minutos": 15})
                self.assertEqual(self.dem(d)["est"], 75)

    # --- prioridade ---
    def test_prioridade_os_quatro_valores_e_invalidos(self):
        for prio in ("low", "high", "urg", "norm"):
            with self.subTest(prio=prio):
                self.adm("demanda/prioridade", {"id": self.did, "prio": prio})
                self.assertEqual(self.dem(self.did)["prio"], prio)
        for ruim in ("alta", "", "URG", None, 1, ["urg"], True):
            with self.subTest(prio=ruim):
                self.assertEqual(self.erro(self.adm, "demanda/prioridade", {"id": self.did, "prio": ruim}), 400)
        self.assertEqual(self.erro(self.adm, "demanda/prioridade", {"id": self.did}), 400)

    def test_prioridade_igual_nao_grava_nem_cria_evento(self):
        r0, n0 = self.rev(), len(self.dem(self.did)["eventos"])
        self.adm("demanda/prioridade", {"id": self.did, "prio": "norm"})
        self.assertEqual((self.rev(), len(self.dem(self.did)["eventos"])), (r0, n0))

    def test_prioridade_texto_do_evento_para_cada_troca(self):
        quer = {"low": "Normal → Baixa", "high": "Baixa → Alta", "urg": "Alta → Urgente", "norm": "Urgente → Normal"}
        for prio, texto in quer.items():
            self.adm("demanda/prioridade", {"id": self.did, "prio": prio})
            self.assertEqual(self.dem(self.did)["eventos"][-1], {"t": T0, "ev": "prio", "quem": "Escritório", "nota": texto})

    def test_prioridade_urgente_avisa_so_na_subida(self):
        self.adm("demanda/prioridade", {"id": self.did, "prio": "urg"})
        n = len(self.notas())
        self.adm("demanda/prioridade", {"id": self.did, "prio": "high"})   # baixar não avisa
        self.assertEqual(len(self.notas()), n)

    # --- comentar ---
    def test_comentar_limites_1_e_1000(self):
        self.adm("demanda/comentar", {"id": self.did, "texto": "x"})
        self.adm("demanda/comentar", {"id": self.did, "texto": "y" * 1000})
        self.assertEqual([len(c["texto"]) for c in self.dem(self.did)["comentarios"]], [1, 1000])
        self.assertEqual(self.erro(self.adm, "demanda/comentar", {"id": self.did, "texto": "y" * 1001}), 400)
        self.assertEqual(self.msg(self.adm, "demanda/comentar", {"id": self.did, "texto": "y" * 1001}),
                         "Comentário: de 1 a 1000 caracteres.")

    def test_comentar_vazio_espacos_nulo_tipos_e_controles(self):
        for ruim in ("", " ", "\n", "   \n  ", None, 5, True, ["a"], {"a": 1}, "a\x00", "a\tb", "a\rb", "a\x7f"):
            with self.subTest(texto=ruim):
                self.assertEqual(self.erro(self.adm, "demanda/comentar", {"id": self.did, "texto": ruim}), 400)
        self.assertEqual(self.erro(self.adm, "demanda/comentar", {"id": self.did}), 400)
        self.assertEqual(self.dem(self.did)["comentarios"], [])

    def test_comentar_aceita_quebra_de_linha_e_tira_espacos_das_pontas(self):
        self.adm("demanda/comentar", {"id": self.did, "texto": "  linha 1\nlinha 2  "})
        self.assertEqual(self.dem(self.did)["comentarios"][0]["texto"], "linha 1\nlinha 2")

    def test_comentar_nao_grava_evento_e_vale_em_qualquer_situacao(self):
        for st in SITUACOES:
            with self.subTest(situacao=st):
                d = self.prepara(st)
                n = len(self.dem(d)["eventos"])
                self.pes(self.tk_h, "demanda/comentar", {"id": d, "texto": "fecho"})
                self.assertEqual(len(self.dem(d)["eventos"]), n)
                self.assertEqual(len(self.dem(d)["comentarios"]), 1)

    def test_comentar_teto_de_300_por_demanda(self):
        self.assertEqual(ds.MAX["comentarios"], 300)
        with mock.patch.dict(ds.MAX, {"comentarios": 2}):
            for _ in range(2):
                self.adm("demanda/comentar", {"id": self.did, "texto": "ok"})
            self.assertEqual(self.erro(self.adm, "demanda/comentar", {"id": self.did, "texto": "mais um"}), 400)

    def test_comentar_quem_e_quando(self):
        self.t += 5 * MIN
        self.pes(self.tk_b, "demanda/comentar", {"id": self.did, "texto": "do Bruno"})
        self.adm("demanda/comentar", {"id": self.did, "texto": "do escritório"})
        self.assertEqual([(c["quem"], c["t"]) for c in self.dem(self.did)["comentarios"]],
                         [("Bruno", self.t), ("Escritório", self.t)])

    def test_comentar_setor_de_origem_e_destino_podem_o_resto_nao(self):
        for ator, quer in (("adm", None), ("helena", None), ("carlos", None), ("bruno", None), ("fer", 403)):
            with self.subTest(ator=ator):
                if quer:
                    self.assertEqual(self.erro(self.chama, ator, "demanda/comentar", {"id": self.did, "texto": "x"}), quer)
                else:
                    self.chama(ator, "demanda/comentar", {"id": self.did, "texto": "x"})


# =====================================================================================================
# 4. Eventos, linha do tempo e avisos do sino
# =====================================================================================================

class Eventos(Base):
    def test_linha_do_tempo_do_ciclo_inteiro_quem_e_nota(self):
        self.t = T0
        did = self.nova(self.tk_h)["id"]
        passos = [
            (1, lambda: self.pes(self.tk_c, "demanda/aceitar", {"id": did})),
            (2, lambda: self.pes(self.tk_c, "demanda/pausar", {"id": did, "motivo": "Aguardando material", "obs": "4 espumas"})),
            (3, lambda: self.pes(self.tk_c, "demanda/retomar", {"id": did})),
            (4, lambda: self.adm("demanda/estender", {"id": did, "minutos": 30})),
            (5, lambda: self.adm("demanda/prioridade", {"id": did, "prio": "urg"})),
            (6, lambda: self.pes(self.tk_h, "demanda/cobrar", {"id": did})),
            (7, lambda: self.pes(self.tk_b, "anexo/enviar", {"id": did, "nome": "foto.jpg", "dados": B64})),
            (8, lambda: self.pes(self.tk_c, "demanda/reatribuir", {"id": did, "s": "CNC", "p": self.bruno, "nota": "turno"})),
            (9, lambda: self.pes(self.tk_b, "demanda/concluir", {"id": did, "nota": "ok"})),
        ]
        for i, f in passos:
            self.t = T0 + i * MIN
            f()
        quer = [
            (0, "created", "Helena", ""),
            (1, "assigned", "Carlos", "Responsável: Carlos"),
            (1, "started", "Carlos", ""),
            (2, "paused", "Carlos", "Aguardando material — 4 espumas"),
            (3, "resumed", "Carlos", ""),
            (4, "deadline", "Escritório", "+30 min"),
            (5, "prio", "Escritório", "Normal → Urgente"),
            (6, "nudge", "Helena", ""),
            (7, "attach", "Bruno", "foto.jpg"),
            (8, "reassigned", "Carlos", "Para CNC · Bruno — turno"),
            (9, "done", "Bruno", "ok"),
        ]
        got = [(e["t"] - T0) // MIN for e in self.dem(did)["eventos"]], [(e["ev"], e["quem"], e["nota"]) for e in self.dem(did)["eventos"]]
        self.assertEqual(got[1], [q[1:] for q in quer])
        self.assertEqual(got[0], [q[0] for q in quer])
        self.assertEqual(sorted(got[0]), got[0], "linha do tempo em ordem de tempo")

    def test_cancelamento_pelo_escritorio_e_pela_pessoa(self):
        a, b = self.nova(self.tk_h)["id"], self.nova(self.tk_h)["id"]
        self.adm("demanda/cancelar", {"id": a, "motivo": "pedido duplicado"})
        self.pes(self.tk_h, "demanda/cancelar", {"id": b})
        self.assertEqual(self.dem(a)["eventos"][-1], {"t": T0, "ev": "canc", "quem": "Escritório", "nota": "pedido duplicado"})
        self.assertEqual(self.dem(b)["eventos"][-1], {"t": T0, "ev": "canc", "quem": "Helena", "nota": ""})

    def test_evento_dos_anexos_so_no_envio(self):
        did = self.nova()["id"]
        v = self.adm("anexo/enviar", {"id": did, "nome": "a.jpg", "dados": B64})
        aid = v["demandas"][0]["anexos"][0]["id"]
        self.adm("anexo/apagar", {"id": did, "aid": aid})
        self.assertEqual(self.evs(did), ["created", "attach"])   # apagar não deixa rastro na linha do tempo (documentado: só "attach")

    def test_o_created_nunca_sai_do_teto_de_eventos(self):
        did = self.nova()["id"]
        with mock.patch.dict(ds.MAX, {"eventos": 4}):
            for _ in range(6):
                self.adm("demanda/cobrar", {"id": did})
        self.assertEqual(self.evs(did), ["created", "nudge", "nudge", "nudge"])

    # --- avisos do sino: quem recebe o quê ---
    def test_avisos_de_pedido_do_escritorio_vao_para_adm(self):
        did = self.nova()["id"]   # Escritório pediu: ponta de origem sem pessoa = "adm"
        self.pes(self.tk_c, "demanda/aceitar", {"id": did})
        self.pes(self.tk_c, "demanda/pausar", {"id": did, "motivo": "Máquina parada"})
        self.pes(self.tk_c, "demanda/retomar", {"id": did})
        self.pes(self.tk_c, "demanda/concluir", {"id": did})
        self.assertEqual(self.notas()[1:], [("adm", "accepted", did), ("adm", "pause", did), ("adm", "done", did)])
        self.assertEqual(self.notas("PCP"), [])

    def test_avisos_de_pedido_de_pessoa_vao_para_ela_e_adm_so_no_pause(self):
        did = self.nova(self.tk_h)["id"]
        self.pes(self.tk_c, "demanda/aceitar", {"id": did})
        self.pes(self.tk_c, "demanda/pausar", {"id": did, "motivo": "Máquina parada"})
        self.pes(self.tk_c, "demanda/retomar", {"id": did})
        self.pes(self.tk_c, "demanda/concluir", {"id": did})
        self.assertEqual(self.notas()[1:], [("PCP", "accepted", did), ("adm", "pause", did), ("PCP", "pause", did),
                                            ("PCP", "done", did)])
        self.assertTrue(all(n["pid"] == self.helena for n in self.disco()["notas"] if n["aud"] == "PCP"))

    def test_retomar_nao_avisa_ninguem(self):
        did = self.prepara("pause")
        n = len(self.notas())
        self.pes(self.tk_c, "demanda/retomar", {"id": did})
        self.assertEqual(len(self.notas()), n)

    def test_cancelar_avisa_o_destino_pessoa_ou_fila(self):
        a = self.prepara("prog")
        b = self.nova(self.tk_h)["id"]   # na fila
        self.pes(self.tk_h, "demanda/cancelar", {"id": a, "motivo": "mudou"})
        self.pes(self.tk_h, "demanda/cancelar", {"id": b})
        ns = [n for n in self.disco()["notas"] if n["tipo"] == "canc"]
        self.assertEqual([(n["aud"], n["pid"], n["texto"], n["quem"]) for n in ns],
                         [("CNC", self.carlos, "mudou", "Helena"), ("CNC", None, "", "Helena")])

    def test_cobrar_pelo_escritorio_nao_avisa_o_proprio_escritorio(self):
        did = self.nova(self.tk_h)["id"]
        self.adm("demanda/cobrar", {"id": did})
        self.pes(self.tk_h, "demanda/cobrar", {"id": did})
        self.assertEqual([n for n in self.notas() if n[1] == "nudge"],
                         [("CNC", "nudge", did), ("CNC", "nudge", did), ("adm", "nudge", did)])

    def test_comentario_avisa_o_outro_lado_e_corta_em_120(self):
        did = self.prepara("prog")
        self.pes(self.tk_c, "demanda/comentar", {"id": did, "texto": "de dentro"})        # quem atende -> quem pediu
        self.pes(self.tk_h, "demanda/comentar", {"id": did, "texto": "de volta"})         # quem pediu -> quem atende
        self.adm("demanda/comentar", {"id": did, "texto": "do escritório"})               # ADM -> destino
        ns = [n for n in self.disco()["notas"] if n["tipo"] == "comment"]
        self.assertEqual([(n["aud"], n["pid"], n["texto"], n["quem"]) for n in ns],
                         [("PCP", self.helena, "de dentro", "Carlos"), ("CNC", self.carlos, "de volta", "Helena"),
                          ("CNC", self.carlos, "do escritório", "Escritório")])
        self.pes(self.tk_h, "demanda/comentar", {"id": did, "texto": "z" * 120})
        self.pes(self.tk_h, "demanda/comentar", {"id": did, "texto": "w" * 121})
        ns = [n["texto"] for n in self.disco()["notas"] if n["tipo"] == "comment"][-2:]
        self.assertEqual((ns[0], len(ns[1]), ns[1][-1]), ("z" * 120, 120, "…"))

    def test_prioridade_urgente_avisa_o_destino_com_texto(self):
        did = self.prepara("prog")
        self.adm("demanda/prioridade", {"id": did, "prio": "urg"})
        n = self.disco()["notas"][-1]
        self.assertEqual((n["aud"], n["pid"], n["tipo"], n["texto"], n["quem"]),
                         ("CNC", self.carlos, "nudge", "Prioridade elevada para URGENTE", "Escritório"))

    def test_repassar_avisa_so_quando_muda_setor_ou_pessoa(self):
        did = self.prepara("prog")
        n0 = len(self.notas())
        self.pes(self.tk_c, "demanda/reatribuir", {"id": did, "s": "CNC", "p": self.carlos})   # igual: nada
        self.assertEqual(len(self.notas()), n0)
        self.pes(self.tk_c, "demanda/reatribuir", {"id": did, "s": "CNC", "p": self.bruno})
        self.assertEqual(self.disco()["notas"][-1]["pid"], self.bruno)
        self.pes(self.tk_b, "demanda/reatribuir", {"id": did, "s": "CNC", "p": None})   # fila do mesmo setor: sem aviso
        self.assertEqual(len(self.notas()), n0 + 1)
        self.pes(self.tk_b, "demanda/reatribuir", {"id": did, "s": "ESP", "p": None})
        self.assertEqual(self.notas()[-1], ("ESP", "new", did))

    def test_anexo_e_prioridade_nao_urgente_nao_avisam(self):
        did = self.nova()["id"]
        n0 = len(self.notas())
        self.adm("anexo/enviar", {"id": did, "nome": "a.jpg", "dados": B64})
        self.adm("demanda/prioridade", {"id": did, "prio": "high"})
        self.adm("demanda/estender", {"id": did, "minutos": 5})
        self.assertEqual(len(self.notas()), n0)

    def test_vista_cada_um_ve_so_o_seu_sino(self):
        did = self.prepara("prog")
        self.pes(self.tk_c, "demanda/pausar", {"id": did, "motivo": "Máquina parada"})
        vh = self.pes(self.tk_h, "vista")
        vf = self.pes(self.tk_f, "vista")
        self.assertIn(did, [n["dem"] for n in vh["notas"]])
        self.assertEqual(vf["demandas"], [])
        self.assertEqual(vf["notas"], [])
        self.assertIn(did, [d["id"] for d in vh["demandas"]])

    def test_atraso_entra_na_linha_do_tempo_uma_vez(self):
        did = self.nova(self.tk_h, est=10)["id"]
        self.t += 11 * MIN
        self.pes(self.tk_c, "demanda/aceitar", {"id": did})
        self.t += 5 * MIN
        self.pes(self.tk_c, "demanda/pausar", {"id": did, "motivo": "Máquina parada"})
        self.assertEqual(self.evs(did).count("late"), 1)
        self.assertEqual(self.evs(did), ["created", "assigned", "started", "late", "paused"])

    def test_cobrar_e_cancelar_em_cada_situacao_ativa_para_quem_pediu(self):
        for st in ATIVAS:
            with self.subTest(situacao=st):
                a, b = self.prepara(st), self.prepara(st)
                self.pes(self.tk_h, "demanda/cobrar", {"id": a})
                self.pes(self.tk_h, "demanda/cancelar", {"id": b})
                self.assertEqual((self.dem(a)["status"], self.dem(b)["status"]), (st, "canc"))


# =====================================================================================================
# 5. Anexos
# =====================================================================================================

class Anexos(Base):
    def enviar(self, did, tk=None, dados=B64, nome="foto.jpg", **kw):
        body = dict({"id": did, "nome": nome, "dados": dados}, **kw)
        return self.pes(tk, "anexo/enviar", body) if tk else self.adm("anexo/enviar", body)

    def aid(self, v, did, i=-1):
        return next(d for d in v["demandas"] if d["id"] == did)["anexos"][i]["id"]

    # --- tipo pela assinatura do arquivo ---
    def test_os_tres_tipos_aceitos(self):
        did = self.nova()["id"]
        for raw, tipo in ((JPG, "jpg"), (PNG, "png"), (PDF, "pdf")):
            with self.subTest(tipo=tipo):
                v = self.enviar(did, dados=b64(raw), nome="x." + tipo)
                a = next(d for d in v["demandas"] if d["id"] == did)["anexos"][-1]
                self.assertEqual((a["tipo"], a["bytes"]), (tipo, len(raw)))
                self.assertTrue((self.dir / "demandas-anexos" / ("%s.%s" % (a["id"], tipo))).exists())
                self.assertEqual(self.get("anexo/" + a["id"])["dados"], b64(raw))

    def test_assinatura_minima_aceita_e_um_byte_a_menos_recusa(self):
        for raw, tipo, curto in ((b"\xff\xd8\xff", "jpg", b"\xff\xd8"), (b"\x89PNG\r\n\x1a\n", "png", b"\x89PNG\r\n\x1a"),
                                 (b"%PDF-", "pdf", b"%PDF")):
            with self.subTest(tipo=tipo):
                did = self.nova()["id"]
                a = self.aid(self.enviar(did, dados=b64(raw)), did)
                self.assertEqual(self.dem(did)["anexos"][0]["tipo"], tipo)
                self.assertTrue(a)
                self.assertEqual(self.erro(self.enviar, did, dados=b64(curto)), 400)

    def test_o_tipo_vem_dos_bytes_nao_do_nome_nem_do_mime(self):
        did = self.nova()["id"]
        self.enviar(did, dados=b64(PDF), nome="foto.jpg")           # PDF com nome de JPG: vale pelos bytes
        self.enviar(did, dados=b64(PNG), nome="documento.pdf")      # PNG com nome de PDF
        for nome in ("x.exe", "x.jpg.exe", "x"):                    # a extensão do nome não decide
            self.enviar(did, dados=b64(JPG), nome=nome)
        self.assertEqual([a["tipo"] for a in self.dem(did)["anexos"]], ["pdf", "png", "jpg", "jpg", "jpg"])

    def test_formatos_nao_aceitos_sao_400_e_nao_gravam(self):
        did = self.nova()["id"]
        falsos = {"gif": b"GIF89a" + b"x" * 20, "gif87": b"GIF87a" + b"x" * 20, "zip": b"PK\x03\x04" + b"x" * 20,
                  "exe": b"MZ\x90\x00" + b"x" * 20, "html": b"<html><script>alert(1)</script>", "svg": b"<svg xmlns='x'/>",
                  "webp": b"RIFF\x00\x00\x00\x00WEBP", "bmp": b"BM" + b"x" * 30, "txt": b"texto puro qualquer",
                  "pdf com espaço antes": b" %PDF-1.4", "pdf com BOM": b"\xef\xbb\xbf%PDF-1.4",
                  "jpg sem o terceiro byte": b"\xff\xd8\x00\xe0" + b"x" * 20, "png truncado": b"\x89PNG\r\n" + b"x" * 20,
                  "png com CRLF trocado": b"\x89PNG\n\r\x1a\n" + b"x" * 20, "elf": b"\x7fELF" + b"x" * 20,
                  "um byte": b"\xff", "zeros": b"\x00" * 64}
        for nome, raw in falsos.items():
            with self.subTest(tipo=nome):
                self.assertEqual(self.erro(self.enviar, did, dados=b64(raw), nome="foto.jpg"), 400)
                self.assertEqual(self.msg(self.enviar, did, dados=b64(raw)),
                                 "Tipo de arquivo não aceito: use JPG, PNG ou PDF.")
        self.assertEqual((self.arquivos(), self.dem(did)["anexos"]), ([], []))

    # --- base64 e tamanho ---
    def test_base64_invalido_vazio_e_tipos_errados(self):
        did = self.nova()["id"]
        for ruim in ("", "abc", "@@@@", "/9j/4A==\n", " /9j/4A==", "ção=", None, 5, True, ["a"], {"a": 1}, B64 + "!"):
            with self.subTest(dados=ruim):
                self.assertEqual(self.erro(self.enviar, did, dados=ruim), 400)
        body = {"id": did, "nome": "a.jpg"}   # sem o campo
        self.assertEqual(self.erro(self.adm, "anexo/enviar", body), 400)
        self.assertEqual(self.arquivos(), [])

    def test_tamanho_5mb_exato_aceita_e_um_byte_a_mais_recusa(self):
        self.assertEqual(ds.ANEXO_MAX, 5 * 1024 * 1024)
        did = self.nova()["id"]
        no_teto = JPG + b"x" * (ds.ANEXO_MAX - len(JPG))
        v = self.enviar(did, dados=b64(no_teto))
        self.assertEqual(next(d for d in v["demandas"] if d["id"] == did)["anexos"][0]["bytes"], ds.ANEXO_MAX)
        self.assertEqual(self.get("anexo/" + self.dem(did)["anexos"][0]["id"])["dados"], b64(no_teto))
        self.assertEqual(self.erro(self.enviar, did, dados=b64(no_teto + b"x")), 413)
        self.assertEqual(self.msg(self.enviar, did, dados=b64(no_teto + b"x")), "Anexo maior que 5 MB.")
        self.assertEqual(len(self.arquivos()), 1)

    def test_cinco_por_demanda_e_apagar_libera_a_vaga(self):
        did = self.nova()["id"]
        outra = self.nova()["id"]
        for _ in range(5):
            self.enviar(did)
        self.assertEqual(self.erro(self.enviar, did), 400)
        self.assertEqual(self.msg(self.enviar, did), "No máximo 5 anexos por demanda.")
        self.enviar(outra)   # o teto é por demanda
        aid = self.dem(did)["anexos"][2]["id"]
        self.adm("anexo/apagar", {"id": did, "aid": aid})
        self.enviar(did)
        self.assertEqual(len(self.dem(did)["anexos"]), 5)
        self.assertEqual(len(self.arquivos()), 6)

    def test_cota_no_byte_exato_e_apagar_devolve_espaco(self):
        did = self.nova()["id"]
        with mock.patch.object(ds, "COTA", len(JPG) * 2):
            self.enviar(did)
            self.enviar(did)   # == cota: cabe
            self.assertEqual(self.erro(self.enviar, did), 507)
            self.assertEqual(self.msg(self.enviar, did), "Espaço dos anexos esgotado (300 MB). Apague anexos antigos.")
            self.assertEqual(len(self.arquivos()), 2)
            self.adm("anexo/apagar", {"id": did, "aid": self.dem(did)["anexos"][0]["id"]})
            self.enviar(did)
            self.assertEqual(self.get()["anexos_uso"], {"bytes": len(JPG) * 2, "cota": len(JPG) * 2})
        self.assertEqual(ds.COTA, 300 * 1024 * 1024)

    def test_cota_e_global_entre_demandas(self):
        a, b = self.nova()["id"], self.nova()["id"]
        with mock.patch.object(ds, "COTA", len(JPG)):
            self.enviar(a)
            self.assertEqual(self.erro(self.enviar, b), 507)

    def test_uso_de_anexos_so_para_o_adm(self):
        did = self.nova(self.tk_h)["id"]
        self.enviar(did)
        self.assertEqual(self.adm("vista")["anexos_uso"]["bytes"], len(JPG))
        self.assertNotIn("anexos_uso", self.pes(self.tk_h, "vista"))

    # --- nome limpo ---
    def test_nome_limpo(self):
        casos = [(" foto.jpg ", "foto.jpg"), ("a‮gpj.exe", "agpj.exe"), ("x​y.jpg", "xy.jpg"),
                 ("​", "anexo.jpg"), ("..\\..\\windows\\sistema.jpg", "..\\..\\windows\\sistema.jpg"),
                 ("../../etc/passwd", "../../etc/passwd"), ("ação-ç😀.jpg", "ação-ç😀.jpg"), ("a" * 120, "a" * 120),
                 ("﻿bom.jpg", "bom.jpg")]
        for nome, quer in casos:
            with self.subTest(nome=nome):
                d = self.nova()["id"]
                v = self.enviar(d, nome=nome)
                a = next(x for x in v["demandas"] if x["id"] == d)["anexos"][0]
                self.assertEqual(a["nome"], quer)
                self.assertRegex(a["id"], r"^a[0-9a-f]{16}$")
                self.assertTrue((self.dir / "demandas-anexos" / (a["id"] + ".jpg")).exists(), "o arquivo usa só o id")
        self.assertEqual(sorted(p.name for p in self.dir.iterdir() if p.is_dir()), ["demandas-anexos"])
        self.assertFalse((self.dir.parent / "passwd").exists())
        self.assertTrue(all(n.startswith("a") and n.endswith(".jpg") for n in self.arquivos()), "só <id>.jpg no disco")

    def test_nome_limites_e_invalidos(self):
        did = self.nova()["id"]
        self.assertEqual(self.erro(self.enviar, did, nome="x" * 121), 400)
        self.assertEqual(self.msg(self.enviar, did, nome="x" * 121), "Nome do anexo: de 1 a 120 caracteres.")
        for ruim in ("", "   ", None, 5, ["a.jpg"], "a\x00.jpg", "a\n.jpg", "a\t.jpg", "a\x7f.jpg", "a\x1b.jpg"):
            with self.subTest(nome=ruim):
                self.assertEqual(self.erro(self.enviar, did, nome=ruim), 400)
        self.assertEqual(self.erro(self.adm, "anexo/enviar", {"id": did, "dados": B64}), 400)   # sem nome
        self.assertEqual(self.arquivos(), [])

    # --- quem envia ---
    def test_quem_envia_demanda_em_cada_situacao(self):
        for st in SITUACOES:
            for ator in ATORES:
                with self.subTest(situacao=st, ator=ator):
                    did = self.prepara(st)
                    quer = esperado("anexar", st, ator)
                    n = len(self.arquivos())
                    if quer:
                        self.assertEqual(self.erro(self.chama, ator, "anexo/enviar", {"id": did, "nome": "a.jpg", "dados": B64}), quer)
                        self.assertEqual(len(self.arquivos()), n)
                    else:
                        self.chama(ator, "anexo/enviar", {"id": did, "nome": "a.jpg", "dados": B64})
                        self.assertEqual(len(self.arquivos()), n + 1)
                        a = self.dem(did)["anexos"][0]
                        self.assertEqual(a["por"], "Escritório" if ator == "adm" else self.disco()["pessoas"][
                            {"helena": 0, "carlos": 1, "bruno": 2, "fer": 3}[ator]]["nome"])

    def test_quem_pediu_envia_mesmo_sem_ser_do_setor_e_o_colega_do_pedinte_nao(self):
        outra = self.pessoa("Paula", "PCP", "5555")
        tk_p = self.entrar(outra, "5555")
        did = self.nova(self.tk_h)["id"]
        self.enviar(did, self.tk_h)
        self.assertEqual(self.erro(self.enviar, did, tk_p), 403)   # mesmo setor de quem pediu, mas não foi ela

    # --- ler ---
    def test_ler_por_quem_ve_a_demanda(self):
        did = self.nova(self.tk_h)["id"]
        a = self.aid(self.enviar(did, self.tk_h, b64(PNG), "p.png"), did)
        quer = {"id": a, "nome": "p.png", "tipo": "png", "dados": b64(PNG)}
        self.assertEqual(self.get("anexo/" + a), quer)
        self.assertEqual(self.get("anexo/" + a, ctx=ADM_PIN), quer)
        self.assertEqual(self.adm("anexo/ler", {"aid": a}), quer)
        for tk in (self.tk_h, self.tk_c, self.tk_b):   # quem pediu e o setor destino
            self.assertEqual(self.pes(tk, "anexo/ler", {"aid": a}), quer)
        self.assertEqual(self.erro(self.pes, self.tk_f, "anexo/ler", {"aid": a}), 403)
        self.assertEqual(self.msg(self.pes, self.tk_f, "anexo/ler", {"aid": a}), "Sem acesso a este anexo.")

    def test_ler_colega_do_setor_de_origem_que_nao_pediu_nao_ve(self):
        outra = self.pessoa("Paula", "PCP", "5555")
        tk_p = self.entrar(outra, "5555")
        did = self.nova(self.tk_h)["id"]
        a = self.aid(self.enviar(did, self.tk_h), did)
        self.assertEqual(self.erro(self.pes, tk_p, "anexo/ler", {"aid": a}), 403)
        self.assertNotIn(did, [d["id"] for d in self.pes(tk_p, "vista")["demandas"]])

    def test_ler_exige_identidade_e_o_get_e_so_do_escritorio(self):
        did = self.nova()["id"]
        a = self.aid(self.enviar(did), did)
        self.assertEqual(self.erro(self.get, "anexo/" + a, ctx=OP), 403)
        self.assertEqual(self.erro(self.adm, "anexo/ler", {"aid": a}, ctx=OP), 403)
        self.assertEqual(self.erro(self.pes, "tk-ruim", "anexo/ler", {"aid": a}), 401)
        self.assertEqual(self.erro(self.get, "anexo/" + a, ctx={}), 403)

    def test_ler_id_invalido_ou_inexistente_e_404(self):
        for aid in ("a" + "0" * 16, "x", "", None, 5, "../demandas", "a" + "0" * 15, "a" + "0" * 17, "A" + "0" * 16,
                    "a" + "g" * 16, "a" + "0" * 16 + ".jpg", "a" * 17, "../../a" + "0" * 16, ["a" + "0" * 16], True):
            with self.subTest(aid=aid):
                self.assertEqual(self.erro(self.pes, self.tk_h, "anexo/ler", {"aid": aid}), 404)
                self.assertEqual(self.erro(self.adm, "anexo/ler", {"aid": aid}), 404)
                if isinstance(aid, str):
                    self.assertEqual(self.erro(self.get, "anexo/" + aid), 404)

    def test_ler_depois_de_encerrada_a_demanda_continua_abrindo(self):
        did = self.prepara("prog")
        a = self.aid(self.enviar(did, self.tk_c), did)
        self.pes(self.tk_c, "demanda/concluir", {"id": did})
        self.assertEqual(self.pes(self.tk_h, "anexo/ler", {"aid": a})["dados"], B64)
        d2 = self.prepara("prog")
        b = self.aid(self.enviar(d2, self.tk_c), d2)
        self.adm("demanda/cancelar", {"id": d2})
        self.assertEqual(self.adm("anexo/ler", {"aid": b})["dados"], B64)

    def test_ler_arquivo_sumido_ou_trocado_e_404(self):
        did = self.nova()["id"]
        a = self.aid(self.enviar(did), did)
        arq = self.dir / "demandas-anexos" / (a + ".jpg")
        arq.write_bytes(b"MZ conteudo trocado a mao")
        self.assertEqual(self.erro(self.get, "anexo/" + a), 404)
        arq.unlink()
        self.assertEqual(self.erro(self.get, "anexo/" + a), 404)

    def test_ler_so_devolve_o_que_a_vista_publica_sem_campos_internos(self):
        did = self.nova(self.tk_h)["id"]
        v = self.enviar(did, self.tk_b, nome="b.jpg")
        a = next(d for d in v["demandas"] if d["id"] == did)["anexos"][0]
        self.assertEqual(set(a), {"id", "nome", "tipo", "bytes", "por", "t"})
        for visao in (self.pes(self.tk_h, "vista"), self.pes(self.tk_c, "vista")):
            self.assertNotIn("_p", json.dumps(visao))

    # --- apagar ---
    def test_apagar_so_adm_ou_quem_enviou_e_so_demanda_ativa(self):
        for ator in ATORES:
            for st in SITUACOES:
                with self.subTest(ator=ator, situacao=st):
                    did = self.prepara("prog")   # os anexos entram com a demanda ativa
                    a_c = self.aid(self.enviar(did, self.tk_c), did)    # do Carlos
                    a_h = self.aid(self.enviar(did, self.tk_h), did)    # da Helena
                    a_adm = self.aid(self.enviar(did), did)             # do Escritório
                    if st == "new":
                        self.pes(self.tk_c, "demanda/reatribuir", {"id": did, "s": "CNC", "p": None})
                    elif st == "pause":
                        self.pes(self.tk_c, "demanda/pausar", {"id": did, "motivo": "Máquina parada"})
                    elif st == "done":
                        self.pes(self.tk_c, "demanda/concluir", {"id": did})
                    elif st == "canc":
                        self.adm("demanda/cancelar", {"id": did})
                    for aid, dono in ((a_c, "carlos"), (a_h, "helena"), (a_adm, "adm")):
                        pode = ator == "adm" or ator == dono
                        ativa = st in ATIVAS
                        quer = 403 if not pode else (409 if not ativa else None)
                        if quer:
                            self.assertEqual(self.erro(self.chama, ator, "anexo/apagar", {"id": did, "aid": aid}), quer)
                            self.assertIn(aid + ".jpg", self.arquivos())
                        else:
                            self.chama(ator, "anexo/apagar", {"id": did, "aid": aid})
                            self.assertNotIn(aid + ".jpg", self.arquivos())
                            self.assertNotIn(aid, [x["id"] for x in self.dem(did)["anexos"]])

    def test_apagar_inexistente_e_de_outra_demanda_e_404(self):
        a, b = self.nova()["id"], self.nova()["id"]
        aid_b = self.aid(self.enviar(b), b)
        for aid in ("a" + "1" * 16, aid_b, "x", None, 5, "../x"):
            with self.subTest(aid=aid):
                self.assertEqual(self.erro(self.adm, "anexo/apagar", {"id": a, "aid": aid}), 404)
        self.assertEqual(self.erro(self.adm, "anexo/apagar", {"id": a}), 404)
        self.assertIn(aid_b + ".jpg", self.arquivos())

    def test_apagar_tira_do_disco_e_do_uso(self):
        did = self.nova()["id"]
        self.enviar(did)
        a = self.dem(did)["anexos"][0]["id"]
        self.assertEqual(self.adm("vista")["anexos_uso"]["bytes"], len(JPG))
        self.adm("anexo/apagar", {"id": did, "aid": a})
        self.assertEqual((self.adm("vista")["anexos_uso"]["bytes"], self.arquivos(), self.dem(did)["anexos"]), (0, [], []))
        self.assertEqual(self.erro(self.get, "anexo/" + a), 404)
        self.assertEqual(self.erro(self.adm, "anexo/apagar", {"id": did, "aid": a}), 404)   # de novo: já foi

    # --- integridade ---
    def test_gravacao_que_falha_nao_deixa_arquivo_orfao(self):
        did = self.nova()["id"]
        with mock.patch.object(ds, "commit", side_effect=OSError("disco")):
            with self.assertRaises(OSError):
                self.enviar(did)
        self.assertEqual((self.arquivos(), self.dem(did)["anexos"]), ([], []))

    def test_enviar_nao_perde_o_que_ja_estava_na_demanda(self):
        did = self.prepara("prog")
        self.pes(self.tk_c, "demanda/comentar", {"id": did, "texto": "antes"})
        self.enviar(did, self.tk_c)
        r = self.dem(did)
        self.assertEqual(([c["texto"] for c in r["comentarios"]], r["status"], r["para"]["p"]), (["antes"], "prog", self.carlos))

    def test_enviar_revisao_da_demanda_acompanha_o_banco(self):
        did = self.nova()["id"]
        self.enviar(did)
        self.assertEqual(self.dem(did)["_rv"], self.rev())

    def test_anexos_pelo_horario_de_servico_ligado_continuam_valendo(self):
        v = self.disco()["agenda"]["v"]
        self.adm("agenda/salvar", {"agenda": {**__import__("demandas_agenda").padrao(), "ativa": True, "v": v}})
        self.t = loc(2026, 11, 14, 22, 0)   # sábado à noite: fora do expediente
        did = self.nova()["id"]
        a = self.aid(self.enviar(did), did)
        self.assertEqual(self.get("anexo/" + a)["dados"], B64)
        self.adm("anexo/apagar", {"id": did, "aid": a})


# =====================================================================================================
# 6. Ciclo completo com o horário de serviço desligado e ligado
# =====================================================================================================

SEG = (2026, 11, 16)   # segunda-feira; padrão: 07-12 e 13-17, segunda a sexta


def seg(h, m=0):
    return loc(*SEG, h, m)


class CicloBase(Base):
    LIGADO = False

    def setUp(self):
        super().setUp()
        self.t = seg(10, 30)
        if self.LIGADO:
            ag = __import__("demandas_agenda")
            v = self.disco()["agenda"]["v"]
            self.adm("agenda/salvar", {"agenda": {**ag.padrao(), "ativa": True, "v": v}})

    def roda(self):
        """Pede, aceita, pausa, retoma, estende, comenta, anexa, cobra, muda a prioridade e conclui."""
        did = self.nova(self.tk_h, est=120)["id"]                                           # 10:30
        self.t = seg(10, 40)
        self.pes(self.tk_c, "demanda/aceitar", {"id": did})
        self.t = seg(11, 50)
        self.pes(self.tk_c, "demanda/pausar", {"id": did, "motivo": "Aguardando material", "obs": "espumas"})
        self.t = seg(13, 10)
        self.pes(self.tk_c, "demanda/retomar", {"id": did})
        self.pes(self.tk_h, "demanda/comentar", {"id": did, "texto": "como está?"})
        self.pes(self.tk_c, "anexo/enviar", {"id": did, "nome": "foto.jpg", "dados": B64})
        self.pes(self.tk_h, "demanda/cobrar", {"id": did})
        self.adm("demanda/prioridade", {"id": did, "prio": "high"})
        self.t = seg(14, 0)
        self.pes(self.tk_c, "demanda/concluir", {"id": did, "nota": "entregue"})
        return did

    def test_ciclo_completo_eventos_e_estado_final(self):
        did = self.roda()
        r = self.dem(did)
        self.assertEqual(r["status"], "done")
        self.assertEqual((r["criado"], r["iniciado"], r["fim"]), (seg(10, 30), seg(10, 40), seg(14, 0)))
        self.assertEqual(r["pausas"], [{"ini": seg(11, 50), "fim": seg(13, 10), "motivo": "Aguardando material",
                                        "obs": "espumas", "por": "Carlos"}])
        evs = self.evs(did)
        self.assertEqual([e for e in evs if e != "late"],
                         ["created", "assigned", "started", "paused", "resumed", "attach", "nudge", "prio", "done"])
        self.assertEqual(len(r["comentarios"]), 1)
        self.assertEqual(len(r["anexos"]), 1)

    def test_acoes_nao_dependem_do_expediente(self):
        """Nenhuma ação é barrada fora do horário de serviço: só a contagem do tempo muda."""
        self.t = loc(2026, 11, 14, 23, 0)   # sábado à noite
        did = self.nova(self.tk_h, est=60)["id"]
        self.t = loc(2026, 11, 15, 10, 0)   # domingo de manhã
        self.pes(self.tk_c, "demanda/aceitar", {"id": did})
        self.pes(self.tk_c, "demanda/pausar", {"id": did, "motivo": "Troca de turno ou intervalo"})
        self.pes(self.tk_c, "demanda/retomar", {"id": did})
        self.pes(self.tk_h, "demanda/comentar", {"id": did, "texto": "fim de semana"})
        self.adm("demanda/estender", {"id": did, "minutos": 30})
        self.pes(self.tk_c, "demanda/concluir", {"id": did})
        self.assertEqual(self.dem(did)["status"], "done")


class CicloSemHorario(CicloBase):
    LIGADO = False

    def test_tempo_corrido_e_sem_util(self):
        did = self.roda()
        r = self.dem(did)
        self.assertNotIn("agenda_v", r)
        self.assertNotIn("prazo_em", r)
        self.assertNotIn("util", r)
        d = next(x for x in self.adm("vista")["demandas"] if x["id"] == did)
        self.assertEqual((d["espera"], d["execucao"], d["pausado"], d["total"]), (10.0, 120.0, 80.0, 210.0))
        self.assertEqual(d["prazo"], seg(12, 30))   # 10:30 + 120 min corridos
        self.assertNotIn("atraso", d)

    def test_atraso_corrido_entra_na_linha_do_tempo(self):
        did = self.roda()
        self.assertEqual(self.evs(did).count("late"), 1)   # passou das 12:30 durante a pausa e foi marcado na retomada
        self.assertEqual(self.evs(did)[self.evs(did).index("late") - 1], "resumed")

    def test_estender_soma_minutos_corridos(self):
        did = self.nova(self.tk_h, est=60)["id"]
        self.adm("demanda/estender", {"id": did, "minutos": 90})
        self.assertEqual(self.adm("vista")["demandas"][0]["prazo"], self.t + 150 * MIN)


class CicloComHorario(CicloBase):
    LIGADO = True

    def test_tempo_util_e_util_gravado_ao_concluir(self):
        did = self.roda()
        r = self.dem(did)
        self.assertEqual(r["agenda_v"], 1)
        self.assertEqual(r["prazo_em"], seg(13, 30))   # 10:30 + 120 min úteis, pulando o almoço (12-13)
        self.assertEqual(r["util"], {"espera": 10 * MIN, "execucao": 120 * MIN, "pausado": 20 * MIN, "total": 150 * MIN,
                                     "atraso": 30 * MIN})
        d = next(x for x in self.adm("vista")["demandas"] if x["id"] == did)
        self.assertEqual((d["espera"], d["execucao"], d["pausado"], d["total"], d["atraso"]), (10.0, 120.0, 20.0, 150.0, 30.0))
        self.assertEqual(d["prazo"], seg(13, 30))

    def test_no_prazo_util_nao_gera_atraso_nem_late(self):
        did = self.nova(self.tk_h, est=120)["id"]
        self.t = seg(11, 0)
        self.pes(self.tk_c, "demanda/aceitar", {"id": did})
        self.t = seg(13, 20)   # 12:30 corrido já passou, mas o prazo útil é 13:30
        self.pes(self.tk_c, "demanda/concluir", {"id": did})
        self.assertNotIn("late", self.evs(did))
        self.assertEqual(self.dem(did)["util"]["atraso"], 0)

    def test_estender_soma_horas_de_trabalho(self):
        did = self.nova(self.tk_h, est=120)["id"]
        self.assertEqual(self.dem(did)["prazo_em"], seg(13, 30))
        self.adm("demanda/estender", {"id": did, "minutos": 60})
        r = self.dem(did)
        self.assertEqual((r["est"], r["prazo_em"]), (180, seg(14, 30)))

    def test_estender_que_nao_cabe_na_agenda_e_400_e_nao_grava(self):
        ag = __import__("demandas_agenda")
        v = self.disco()["agenda"]["v"]
        self.adm("agenda/salvar", {"agenda": {**ag.padrao(), "ativa": True, "v": v,
                                              "padrao": {"dias": [1], "turnos": [["07:00", "07:15"]]}}})
        did = self.nova(self.tk_h, est=30)["id"]
        antes = self.disco()
        self.assertEqual(self.erro(self.adm, "demanda/estender", {"id": did, "minutos": 1440}), 400)
        self.assertEqual(self.disco(), antes)

    def test_pausa_fora_do_expediente_nao_conta(self):
        did = self.nova(self.tk_h, est=60)["id"]
        self.t = seg(10, 40)
        self.pes(self.tk_c, "demanda/aceitar", {"id": did})
        self.t = seg(16, 50)
        self.pes(self.tk_c, "demanda/pausar", {"id": did, "motivo": "Troca de turno ou intervalo"})
        self.t = loc(2026, 11, 17, 7, 10)   # terça de manhã: 10 min úteis de pausa na segunda + 10 na terça
        self.pes(self.tk_c, "demanda/retomar", {"id": did})
        d = next(x for x in self.adm("vista")["demandas"] if x["id"] == did)
        self.assertEqual(d["pausado"], 20.0)   # a noite não é pausa útil

    def test_cancelar_tambem_grava_util(self):
        did = self.nova(self.tk_h, est=60)["id"]
        self.t = seg(11, 30)
        self.pes(self.tk_h, "demanda/cancelar", {"id": did, "motivo": "não precisa"})
        r = self.dem(did)
        self.assertEqual((r["status"], r["util"]["total"], r["util"]["espera"]), ("canc", 60 * MIN, 60 * MIN))

    def test_demanda_criada_antes_de_ligar_continua_em_tempo_corrido(self):
        # a base do teste liga o horário no setUp; aqui o cenário é desligar, criar, ligar e fechar
        ag = __import__("demandas_agenda")
        v = self.disco()["agenda"]["v"]
        self.adm("agenda/salvar", {"agenda": {**ag.padrao(), "ativa": False, "v": v}})
        did = self.nova(self.tk_h, est=60)["id"]
        v = self.disco()["agenda"]["v"]
        self.adm("agenda/salvar", {"agenda": {**ag.padrao(), "ativa": True, "v": v}})
        self.t = seg(12, 30)
        self.pes(self.tk_c, "demanda/aceitar", {"id": did})
        self.pes(self.tk_c, "demanda/concluir", {"id": did})
        self.assertNotIn("util", self.dem(did))
        self.assertNotIn("agenda_v", self.dem(did))


# =====================================================================================================
# 7. Bugs confirmados (known-bug): ficam como falha esperada até serem corrigidos
# =====================================================================================================

class BugsConhecidos(Base):
    def test_known_bug_surrogate_solto_na_observacao_vira_erro_de_servidor(self):
        """QA-C-01: texto com meio emoji (surrogate solto, que a tela produz ao cortar com slice(0, 500)) passa na
        validação e a gravação estoura UnicodeEncodeError em vez de um 400. Esperado: 400 (ou aceitar e gravar)."""
        did = self.prepara("prog")
        try:
            self.pes(self.tk_c, "demanda/pausar", {"id": did, "motivo": "Máquina parada", "obs": "a\ud83d"})
        except api.ApiError as e:
            self.assertEqual(e.status, 400)
        else:
            self.assertEqual(self.dem(did)["status"], "pause")

    def test_known_bug_apagar_anexo_devolve_o_uso_de_antes(self):
        """QA-C-02: a vista que volta de anexo/apagar é montada antes de o arquivo sumir (o `depois` roda fora do LOCK,
        depois da vista), então `anexos_uso` ainda conta o anexo apagado. Esperado: 0 bytes na própria resposta."""
        did = self.nova()["id"]
        self.adm("anexo/enviar", {"id": did, "nome": "a.jpg", "dados": B64})
        v = self.adm("anexo/apagar", {"id": did, "aid": self.dem(did)["anexos"][0]["id"]})
        self.assertEqual(v["anexos_uso"]["bytes"], 0)

    def test_known_bug_surrogate_solto_no_comentario(self):
        """QA-C-01 (comentário): mesma falha em demanda/comentar."""
        did = self.prepara("prog")
        try:
            self.pes(self.tk_h, "demanda/comentar", {"id": did, "texto": "oi\ud83d"})
        except api.ApiError as e:
            self.assertEqual(e.status, 400)
        else:
            self.assertEqual(len(self.dem(did)["comentarios"]), 1)


if __name__ == "__main__":
    unittest.main()
