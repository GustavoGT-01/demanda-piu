"""QA das visões: histórico (com arquivo morto), cronoanálise, cronograma multidia, feed do painel e vista do operador.

Só as regras de servidor (rotas `historico`, `crono`, `cronograma` e a vista por papel) ficam aqui; a tela de cada uma
é conferida em tests/check_visoes.js (jsdom contra o servidor real). Matriz em docs/qa/visoes.md.
Reaproveita o cenário e os auxiliares do test_demandas_api.py (PCP: Helena; CNC: Carlos, Bruno; ESP: Fernanda).
"""

import datetime
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_demandas_api as T  # noqa: E402  (põe a pasta demandas/ no sys.path)
import demandas_agenda as ag  # noqa: E402
import demandas_calc as calc  # noqa: E402
import demandas_store as ds  # noqa: E402

MIN, HORA, DIA = 60000, 3600000, 86400000


def local(y, m, d, h=0, mi=0):
    """Instante (ms) no horário local do computador: o crono "Hoje" usa a meia-noite local."""
    return int(datetime.datetime(y, m, d, h, mi).timestamp() * 1000)


QUA = local(2026, 3, 18, 15)   # uma quarta-feira, 15:00


class Cena(T.Base):
    """Auxiliares para montar demandas em instantes escolhidos."""

    def em(self, t):
        self.t = t
        return self

    def cria(self, t, tk=None, **kw):
        self.t = t
        return self.nova(tk, **kw)["id"]

    def aceita(self, t, did, tk=None):
        self.t = t
        self.pes(tk or self.tk_c, "demanda/aceitar", {"id": did})

    def conclui(self, t, did, tk=None):
        self.t = t
        self.pes(tk or self.tk_c, "demanda/concluir", {"id": did})

    def cancela(self, t, did):
        self.t = t
        self.adm("demanda/cancelar", {"id": did, "motivo": "teste"})

    def feita(self, criada, aceita, concluida, tk=None, **kw):
        """Cria em `criada`, aceita em `aceita` e conclui em `concluida` (o destino padrão é o CNC)."""
        did = self.cria(criada, **kw)
        self.aceita(aceita, did, tk)
        self.conclui(concluida, did, tk)
        return did

    def arquiva(self, did, novo_id, **mudancas):
        """Copia a demanda do principal para o arquivo morto com outro id (e tira nada do principal)."""
        d = self.dem(did)
        d.update(id=novo_id, **mudancas)
        p = ds.arquivo_path()
        antes = json.loads(p.read_text(encoding="utf-8"))["demandas"] if p.exists() else []
        p.write_text(json.dumps({"v": ds.V, "demandas": antes + [d]}), encoding="utf-8")
        ds._ARQ.update(key=None, demandas=[])
        return novo_id

    def ids(self, r):
        return [d["id"] for d in r["demandas"]]

    def linhas(self, r):
        return [ln["id"] for g in r["grupos"] for ln in g["linhas"]]


# ---------------------------------------------------------------- histórico

class Historico(Cena):
    def test_so_o_adm_le(self):
        self.cria(QUA)
        corpo = {"de": 0, "ate": 10 ** 15}
        self.assertEqual(self.erro(self.pes, self.tk_c, "historico", corpo), 403)     # pessoa com tk
        self.assertEqual(self.erro(self.adm, "historico", corpo, ctx=T.OP), 403)       # operador sem tk
        self.assertEqual(self.erro(self.adm, "historico", corpo, ctx={}), 403)         # sem papel
        self.assertEqual(len(self.adm("historico", corpo)["demandas"]), 1)             # ADM completo
        self.assertEqual(len(self.adm("historico", corpo, ctx={"papel": "completo"})["demandas"]), 1)

    def test_corpo_invalido(self):
        for corpo in ({}, {"de": 0}, {"ate": 5}, {"de": "0", "ate": 5}, {"de": 0.5, "ate": 5}, {"de": True, "ate": 5},
                      {"de": None, "ate": 5}, {"de": -1, "ate": 5}, {"de": 5, "ate": 4}, {"de": 0, "ate": "9"},
                      {"de": 0, "ate": 10 ** 15 + 1}, {"de": 10 ** 15 + 1, "ate": 10 ** 15 + 2}, {"de": 0, "ate": None},
                      {"de": 0, "ate": False}):
            with self.subTest(corpo=corpo):
                self.assertEqual(self.erro(self.adm, "historico", corpo), 400)

    def test_limites_da_janela_sao_inclusivos(self):
        a = self.cria(QUA)
        b = self.cria(QUA + 1000)
        c = self.cria(QUA + 2000)
        h = lambda de, ate: self.ids(self.adm("historico", {"de": de, "ate": ate}))   # noqa: E731
        self.assertEqual(h(QUA + 1000, QUA + 1000), [b])                 # de == ate: só o instante
        self.assertEqual(h(QUA + 1000, QUA + 2000), [c, b])              # as duas pontas entram
        self.assertEqual(h(QUA + 1001, QUA + 2000), [c])                 # 1 ms depois de b
        self.assertEqual(h(QUA, QUA + 1999), [b, a])                     # 1 ms antes de c
        self.assertEqual(h(0, 10 ** 15), [c, b, a])                      # o teto do contrato
        self.assertEqual(h(QUA + 3000, QUA + 4000), [])                  # nada no recorte: lista vazia, não erro
        self.assertEqual(self.adm("historico", {"de": 0, "ate": 1}), {"demandas": []})

    def test_mais_nova_primeiro_e_todos_os_status(self):
        n1 = self.cria(QUA)                      # fica aberta
        n2 = self.feita(QUA + MIN, QUA + 2 * MIN, QUA + 3 * MIN)
        n3 = self.cria(QUA + 4 * MIN)
        self.cancela(QUA + 5 * MIN, n3)
        r = self.adm("historico", {"de": 0, "ate": 10 ** 15})
        self.assertEqual(self.ids(r), [n3, n2, n1])
        self.assertEqual([d["status"] for d in r["demandas"]], ["canc", "done", "new"])

    def test_inclui_o_arquivo_morto_e_o_principal_vence(self):
        novo = self.cria(QUA)
        velha = self.cria(QUA - 40 * DIA)
        self.arquiva(velha, "SOL-500", titulo="Só no arquivo", status="done", criado=QUA - 60 * DIA, fim=QUA - 59 * DIA)
        igual = self.arquiva(novo, novo, titulo="Cópia velha no arquivo")            # mesmo id nos dois
        r = self.adm("historico", {"de": 0, "ate": 10 ** 15})
        self.assertEqual(sorted(self.ids(r)), sorted([novo, velha, "SOL-500"]))       # sem repetir o id
        por_id = {d["id"]: d for d in r["demandas"]}
        self.assertEqual(igual, novo)
        self.assertNotEqual(por_id[novo]["titulo"], "Cópia velha no arquivo")        # o principal vence
        self.assertEqual(por_id["SOL-500"]["titulo"], "Só no arquivo")
        # a janela vale também para o arquivo
        r = self.adm("historico", {"de": QUA - 41 * DIA, "ate": QUA - 30 * DIA})
        self.assertEqual(self.ids(r), [velha])
        self.assertEqual(self.ids(self.adm("historico", {"de": QUA - 61 * DIA, "ate": QUA - 59 * DIA})), ["SOL-500"])
        self.assertEqual(self.ids(self.adm("historico", {"de": QUA - 100 * DIA, "ate": QUA - 90 * DIA})), [])

    def test_a_vista_nao_traz_o_arquivo(self):
        velha = self.cria(QUA - 40 * DIA)
        self.arquiva(velha, "SOL-500", titulo="Só no arquivo", status="done", fim=QUA - 39 * DIA)
        self.assertNotIn("SOL-500", [d["id"] for d in self.get()["demandas"]])

    def test_teto_do_pedido_mantem_as_mais_novas(self):
        ids = [self.cria(QUA + i * MIN) for i in range(5)]
        with mock.patch.object(api_(), "HIST_MAX", 3):
            r = self.adm("historico", {"de": 0, "ate": 10 ** 15})
        self.assertEqual(self.ids(r), ids[::-1][:3])

    def test_teto_real_e_5000(self):
        self.assertEqual(api_().HIST_MAX, 5000)

    def test_saida_publica_com_derivados_e_sem_internos(self):
        did = self.cria(QUA)
        self.adm("anexo/enviar", {"id": did, "nome": "a.jpg", "dados": T.B64})
        d = self.adm("historico", {"de": 0, "ate": 10 ** 15})["demandas"][0]
        for chave in ("prazo", "atrasada", "espera", "execucao", "pausado", "total", "sla"):
            self.assertIn(chave, d)
        self.assertEqual(d["anexos"][0]["nome"], "a.jpg")
        self.assertFalse([k for k in d if k.startswith("_") and k != "_rv"])
        self.assertFalse([k for a in d["anexos"] for k in a if k.startswith("_")])

    def test_leitura_nao_muda_o_rev_nem_grava(self):
        self.cria(QUA)
        r = self.rev()
        self.adm("historico", {"de": 0, "ate": 10 ** 15})
        self.assertEqual(self.rev(), r)


def api_():
    return T.api


# ---------------------------------------------------------------- cronoanálise

class Crono(Cena):
    def test_so_o_adm_le(self):
        self.assertEqual(self.erro(self.pes, self.tk_c, "crono", {"dias": 7}), 403)
        self.assertEqual(self.erro(self.adm, "crono", {"dias": 7}, ctx=T.OP), 403)
        self.assertEqual(self.adm("crono", {"dias": 7})["dias"], 7)

    def test_periodo_valido_so_1_7_30(self):
        for dias in (1, 7, 30):
            self.assertEqual(self.adm("crono", {"dias": dias})["dias"], dias)
        for dias in (0, 2, 6, 8, 29, 31, 365, -1, "7", None, True, False, [7], {"x": 1}):
            with self.subTest(dias=dias):
                self.assertEqual(self.erro(self.adm, "crono", {"dias": dias}), 400)
        self.assertEqual(self.erro(self.adm, "crono", {}), 400)

    def test_vazio_tem_nulos_e_listas_vazias(self):
        self.t = QUA
        r = self.adm("crono", {"dias": 7})
        self.assertEqual(r["kpis"], {"abertas": 0, "concluidas": 0, "no_prazo": 0, "pct_prazo": None, "espera": None,
                                     "execucao": None, "pausado": None, "estimado": None})
        self.assertEqual((r["setores"], r["motivos"], r["ranking"]), ([], [], []))
        self.assertEqual(r["gantt"]["linhas"], [])
        self.assertEqual(r["desde"], QUA - 7 * DIA)

    def test_medias_de_uma_concluida(self):
        # criada 15:00, aceita 15:10, concluída 16:10 (estimado 60): espera 10, execução 60, pausa 0
        self.feita(QUA, QUA + 10 * MIN, QUA + 70 * MIN)
        self.t = QUA + 2 * HORA
        k = self.adm("crono", {"dias": 7})["kpis"]
        self.assertEqual((k["abertas"], k["concluidas"], k["no_prazo"], k["pct_prazo"]), (1, 1, 0, 0))   # 70 > 60: atrasou
        self.assertEqual((k["espera"], k["execucao"], k["pausado"], k["estimado"]), (10.0, 60.0, 0.0, 60.0))

    def test_pausa_entra_na_media_de_pausa_e_sai_da_execucao(self):
        did = self.cria(QUA, est=240)
        self.aceita(QUA + 10 * MIN, did)
        self.t = QUA + 30 * MIN
        self.pes(self.tk_c, "demanda/pausar", {"id": did, "motivo": "Máquina parada"})
        self.t = QUA + 50 * MIN
        self.pes(self.tk_c, "demanda/retomar", {"id": did})
        self.conclui(QUA + 70 * MIN, did)
        self.t = QUA + 2 * HORA
        k = self.adm("crono", {"dias": 7})["kpis"]
        self.assertEqual((k["espera"], k["pausado"], k["execucao"]), (10.0, 20.0, 40.0))

    def test_prazo_exato_conta_no_prazo_e_1_ms_depois_nao(self):
        a = self.feita(QUA, QUA + MIN, QUA + 60 * MIN)            # fim == prazo (criado + 60 min)
        b = self.feita(QUA, QUA + MIN, QUA + 60 * MIN + 1)        # 1 ms depois
        self.t = QUA + 3 * HORA
        k = self.adm("crono", {"dias": 7})["kpis"]
        self.assertEqual((k["concluidas"], k["no_prazo"], k["pct_prazo"]), (2, 1, 50))
        pub = {d["id"]: d for d in self.adm("historico", {"de": 0, "ate": 10 ** 15})["demandas"]}
        self.assertEqual((pub[a]["status"], pub[b]["status"]), ("done", "done"))

    def test_canceladas_entram_em_abertas_e_nao_em_concluidas(self):
        a = self.cria(QUA)
        self.cancela(QUA + MIN, a)
        self.cria(QUA)                                            # aberta
        self.t = QUA + HORA
        k = self.adm("crono", {"dias": 7})["kpis"]
        self.assertEqual((k["abertas"], k["concluidas"], k["pct_prazo"]), (2, 0, None))

    def test_hoje_comeca_na_meia_noite_local(self):
        meia = local(2026, 3, 18)
        ontem = self.cria(meia - 1)
        hoje = self.cria(meia)
        self.t = QUA
        r = self.adm("crono", {"dias": 1})
        self.assertEqual(r["desde"], meia)
        self.assertEqual(r["kpis"]["abertas"], 1)                 # só a de 00:00 em ponto
        self.assertEqual(r["motivos"], [{"motivo": "Outro", "n": 1}])
        self.assertNotEqual(ontem, hoje)

    def test_concluida_hoje_de_demanda_criada_ontem_conta_so_em_concluidas(self):
        meia = local(2026, 3, 18)
        self.feita(meia - HORA, meia - HORA + MIN, QUA - HORA, est=60 * 24)
        self.t = QUA
        k = self.adm("crono", {"dias": 1})["kpis"]
        self.assertEqual((k["abertas"], k["concluidas"]), (0, 1))

    def test_janela_rolante_de_7_e_30_dias_e_inclusiva(self):
        for dias in (7, 30):
            with self.subTest(dias=dias):
                self.dir_limpo()
                self.cria(QUA - dias * DIA)                       # exatamente no limite: entra
                self.cria(QUA - dias * DIA - 1)                   # 1 ms antes: fica fora
                self.t = QUA
                r = self.adm("crono", {"dias": dias})
                self.assertEqual(r["desde"], QUA - dias * DIA)
                self.assertEqual(r["kpis"]["abertas"], 1)

    def dir_limpo(self):
        """Volta ao cenário inicial (apaga as demandas) sem refazer as pessoas."""
        doc = ds.load()
        doc["demandas"], doc["notas"] = [], []
        ds.commit(doc)

    def test_motivos_por_contagem_e_depois_nome(self):
        for motivo in ("Retrabalho", "Outro", "Retrabalho", "Falta de material", "Outro", "Retrabalho"):
            self.cria(QUA, motivo=motivo)
        self.t = QUA
        r = self.adm("crono", {"dias": 7})["motivos"]
        self.assertEqual(r, [{"motivo": "Retrabalho", "n": 3}, {"motivo": "Outro", "n": 2},
                             {"motivo": "Falta de material", "n": 1}])

    def test_setores_por_cumprimento_do_prazo_e_ranking_por_pessoa(self):
        self.feita(QUA, QUA + MIN, QUA + 90 * MIN)                                # CNC/Carlos: atrasou
        self.feita(QUA, QUA + MIN, QUA + 10 * MIN, para={"s": "ESP", "p": None}, tk=self.tk_f)   # ESP/Fernanda: no prazo
        self.feita(QUA, QUA + MIN, QUA + 20 * MIN, para={"s": "ESP", "p": None}, tk=self.tk_f)
        self.t = QUA + 2 * HORA
        r = self.adm("crono", {"dias": 7})
        self.assertEqual([(s["s"], s["n"], s["sla"]) for s in r["setores"]], [("CNC", 1, 0), ("ESP", 2, 100)])
        self.assertEqual([(x["p"], x["n"], x["sla"]) for x in r["ranking"]],
                         [(self.fer, 2, 100), (self.carlos, 1, 0)])

    def test_ranking_corta_em_6(self):
        pessoas = [self.carlos, self.bruno] + [self.pessoa("Extra %d" % i, "CNC", "5%03d" % i) for i in range(5)]
        for i, pid in enumerate(pessoas):
            tk = self.entrar(pid, "2222" if pid == self.carlos else "3333" if pid == self.bruno else "5%03d" % (i - 2))
            self.feita(QUA, QUA + MIN, QUA + 10 * MIN, tk=tk)
        self.t = QUA + HORA
        r = self.adm("crono", {"dias": 7})
        self.assertEqual(len(r["ranking"]), 6)
        self.assertEqual(r["kpis"]["concluidas"], 7)

    def test_gantt_de_hoje_tem_14_ativas_e_4_concluidas_e_as_8_chaves(self):
        for _ in range(16):
            self.cria(QUA)
        for i in range(6):
            self.feita(QUA, QUA + MIN, QUA + (10 + i) * MIN)
        self.t = QUA + HORA
        g = self.adm("crono", {"dias": 7})["gantt"]
        self.assertEqual(sum(1 for ln in g["linhas"] if ln["viva"]), 14)
        self.assertEqual(sum(1 for ln in g["linhas"] if not ln["viva"]), 4)
        self.assertEqual(set(g["linhas"][0]), {"id", "de", "para", "titulo", "segs", "prazo", "atrasada", "viva"})
        self.assertFalse({"por", "agora", "grupos", "cortado"} & set(g))
        self.assertEqual((g["ini"], g["fim"]), (self.t - 10 * HORA, self.t + 3 * HORA))

    def test_expediente_so_com_o_horario_de_servico_ligado(self):
        self.t = QUA
        self.assertNotIn("expediente", self.adm("crono", {"dias": 7})["gantt"])
        self.adm("agenda/salvar", {"agenda": {**ag.padrao(), "ativa": True, "v": 0}})
        g = self.adm("crono", {"dias": 7})["gantt"]
        self.assertEqual(set(g["expediente"]), {"geral", "setores"})
        self.assertEqual(g["expediente"]["setores"], {})
        self.assertTrue(g["expediente"]["geral"])

    def test_leitura_nao_muda_o_rev(self):
        self.cria(QUA)
        r = self.rev()
        self.adm("crono", {"dias": 30})
        self.assertEqual(self.rev(), r)


# ---------------------------------------------------------------- cronograma multidia

class Cronograma(Cena):
    DE, ATE = QUA - DIA, QUA + DIA

    def cg(self, por="setor", de=None, ate=None):
        return self.adm("cronograma", {"de": self.DE if de is None else de, "ate": self.ATE if ate is None else ate,
                                       "por": por})

    def test_so_o_adm_le(self):
        corpo = {"de": self.DE, "ate": self.ATE, "por": "setor"}
        self.assertEqual(self.erro(self.pes, self.tk_c, "cronograma", corpo), 403)
        self.assertEqual(self.erro(self.adm, "cronograma", corpo, ctx=T.OP), 403)
        self.assertEqual(self.adm("cronograma", corpo)["por"], "setor")

    def test_corpo_invalido(self):
        base = {"de": self.DE, "ate": self.ATE, "por": "setor"}
        for ruim in ({"de": None}, {"de": "x"}, {"de": True}, {"de": -1}, {"de": 1.5}, {"ate": None}, {"ate": self.DE},
                     {"ate": 10 ** 15 + 1, "de": 10 ** 15 - 1}, {"por": "dia"}, {"por": None},
                     {"por": "Setor"}, {"por": ["setor"]}):
            with self.subTest(ruim=ruim):
                self.assertEqual(self.erro(self.adm, "cronograma", {**base, **ruim}), 400)
        self.assertEqual(self.erro(self.adm, "cronograma", {"de": self.DE, "ate": self.ATE}), 400)   # sem "por"

    def test_janela_maxima_de_31_dias_e_exata(self):
        self.assertEqual(self.cg(de=self.DE, ate=self.DE + 31 * DIA)["fim"], self.DE + 31 * DIA)     # o maior mês passa
        self.assertEqual(self.erro(self.cg, de=self.DE, ate=self.DE + 31 * DIA + 1), 400)            # 1 ms a mais não
        self.assertEqual(self.msg(self.cg, de=self.DE, ate=self.DE + 32 * DIA), "Período de até 31 dias.")
        self.assertEqual(self.cg(de=self.DE, ate=self.DE + 1)["ini"], self.DE)                       # janela mínima: 1 ms

    def test_known_bug_janela_invertida_deveria_ser_ordenada_como_diz_o_contrato(self):
        """CONTRATO.md: "{de, ate} em ms (até 31 dias; invertida é ordenada)". A rota devolve 400 ("Fim inválido.")."""
        r = self.cg(de=self.ATE, ate=self.DE)
        self.assertEqual((r["ini"], r["fim"]), (self.DE, self.ATE))

    def test_vazio(self):
        r = self.cg()
        self.assertEqual((r["grupos"], r["cortado"], r["agora"]), ([], False, self.t))
        self.assertNotIn("expediente", r)

    def test_agrupa_por_setor_e_ordena_os_grupos(self):
        a = self.cria(QUA)                                                    # CNC ativa
        b = self.cria(QUA, para={"s": "CNC", "p": None})                      # CNC ativa
        c = self.cria(QUA, para={"s": "ESP", "p": None})                      # ESP ativa
        d = self.feita(QUA, QUA + MIN, QUA + 10 * MIN, para={"s": "PCP", "p": None}, tk=self.tk_h)   # PCP concluída
        self.t = QUA + HORA
        r = self.cg()
        self.assertEqual([(g["chave"], g["n"], g["ativas"]) for g in r["grupos"]],
                         [("CNC", 2, 2), ("ESP", 1, 1), ("PCP", 1, 0)])       # ativas desc, n desc
        self.assertEqual([ln["id"] for ln in r["grupos"][0]["linhas"]], [a, b])   # linhas por criação
        self.assertEqual(sorted(self.linhas(r)), sorted([a, b, c, d]))
        ln = r["grupos"][0]["linhas"][0]
        self.assertEqual(set(ln), {"id", "de", "para", "titulo", "segs", "prazo", "atrasada", "viva", "p", "plano"})
        self.assertEqual(ln["plano"], {"a": QUA, "b": QUA + 60 * MIN})
        self.assertEqual(ln["segs"], [{"k": "wait", "a": QUA, "b": self.t}])
        self.assertTrue(ln["viva"])

    def test_agrupa_por_pessoa_e_a_fila_do_setor_e_um_grupo_so(self):
        fila1 = self.cria(QUA)
        fila2 = self.cria(QUA, para={"s": "ESP", "p": None})
        com = self.cria(QUA, para={"s": "CNC", "p": self.carlos})
        self.t = QUA + HORA
        r = self.cg("pessoa")
        chaves = {g["chave"]: [ln["id"] for ln in g["linhas"]] for g in r["grupos"]}
        self.assertEqual(chaves, {None: [fila1, fila2], self.carlos: [com]})
        self.assertEqual(r["grupos"][0]["chave"], None)                       # 2 ativas contra 1
        self.assertEqual(r["por"], "pessoa")

    def test_cancelada_nao_entra_e_concluida_so_se_cruza_a_janela(self):
        canc = self.cria(QUA)
        self.cancela(QUA + MIN, canc)
        velha = self.feita(QUA - 10 * DIA, QUA - 10 * DIA + MIN, QUA - 10 * DIA + 10 * MIN)   # termina muito antes
        atual = self.feita(QUA, QUA + MIN, QUA + 10 * MIN)
        self.t = QUA + HORA
        r = self.cg()
        self.assertEqual(self.linhas(r), [atual])
        self.assertNotIn(canc, self.linhas(r))
        self.assertNotIn(velha, self.linhas(r))

    def test_entra_pelo_prazo_mesmo_sem_trecho_na_janela(self):
        # criada e ainda aberta, com prazo dentro da janela; janela inteira no futuro: o trecho de espera vai até
        # "agora" e não a cruza, mas o prazo cai nela
        did = self.cria(QUA, est=60 * 24 * 3)                                  # prazo em QUA + 3 dias
        self.t = QUA + HORA
        r = self.cg(de=QUA + 2 * DIA, ate=QUA + 4 * DIA)
        self.assertEqual(self.linhas(r), [did])
        self.assertEqual(self.linhas(self.cg(de=QUA + 5 * DIA, ate=QUA + 6 * DIA)), [])

    def test_teto_de_120_linhas_pela_atencao_e_cortado(self):
        atrasada = self.cria(QUA - 3 * HORA, est=30)                           # já passou do prazo
        normais = [self.cria(QUA) for _ in range(118)]
        ultima_normal = self.cria(QUA)                                         # a 120ª; a urgente a empurra
        urgente = self.cria(QUA, prio="urg")
        self.t = QUA + HORA
        r = self.cg()
        linhas = self.linhas(r)
        self.assertEqual(len(linhas), calc.GANTT_MULTI)
        self.assertEqual(calc.GANTT_MULTI, 120)
        self.assertTrue(r["cortado"])
        self.assertIn(atrasada, linhas)
        self.assertIn(urgente, linhas)
        self.assertNotIn(ultima_normal, linhas)                                # o corte é por atenção, não pela ordem
        self.assertEqual(set(linhas), {atrasada, urgente, *normais})
        self.assertEqual(r["grupos"][0]["n"], 120)

    def test_known_bug_corte_deveria_preferir_as_em_aberto_as_concluidas_antigas(self):
        """V-06: o corte usa chave_atencao (prazo mais perto) também nas concluídas; com mais em aberto do que vagas,
        concluídas antigas tomam o lugar de solicitações em aberto."""
        for i in range(3):
            self.feita(QUA - 5 * DIA + i * MIN, QUA - 5 * DIA + i * MIN + MIN, QUA - 5 * DIA + i * MIN + 2 * MIN)
        abertas = [self.cria(QUA) for _ in range(4)]
        self.t = QUA + HORA
        with mock.patch.object(calc, "GANTT_MULTI", 4):
            r = self.cg(de=QUA - 6 * DIA, ate=QUA + DIA - 1 * DIA + DIA)
        self.assertEqual(sorted(self.linhas(r)), sorted(abertas))

    def test_exatamente_120_nao_corta(self):
        for _ in range(120):
            self.cria(QUA)
        self.t = QUA + HORA
        r = self.cg()
        self.assertEqual((len(self.linhas(r)), r["cortado"]), (120, False))

    def test_teto_configuravel_no_calc(self):
        for _ in range(4):
            self.cria(QUA)
        with mock.patch.object(calc, "GANTT_MULTI", 3):
            r = self.cg()
        self.assertEqual((len(self.linhas(r)), r["cortado"]), (3, True))

    def test_expediente_acompanha_o_horario_de_servico(self):
        self.adm("agenda/salvar", {"agenda": {**ag.padrao(), "ativa": True, "v": 0,
                                              "setores": {"ESP": {"dias": [1, 2], "turnos": [["08:00", "12:00"]]}}}})
        self.t = QUA
        r = self.cg()
        self.assertEqual(set(r["expediente"]["setores"]), {"ESP"})             # só quem tem horário próprio
        self.assertTrue(r["expediente"]["geral"])

    def test_leitura_nao_muda_o_rev(self):
        self.cria(QUA)
        r = self.rev()
        self.cg()
        self.assertEqual(self.rev(), r)


# ---------------------------------------------------------------- painel (feed) e vista do operador

class PainelEOperador(Cena):
    def test_feed_14_mais_novos_sem_assigned(self):
        for i in range(10):
            did = self.cria(QUA + i * MIN, para={"s": "CNC", "p": self.carlos})     # gera "assigned" (não entra no feed)
            self.aceita(QUA + i * MIN + 1, did)
        self.t = QUA + HORA
        feed = self.get()["feed"]
        self.assertEqual(len(feed), 14)
        self.assertTrue(all("Responsável" not in f["msg"] for f in feed))
        ts = [f["t"] for f in feed]
        self.assertEqual(ts, sorted(ts, reverse=True))
        self.assertTrue(feed[0]["msg"].endswith("Iniciada") and feed[0]["tipo"] == "ok")

    def test_feed_tipos(self):
        did = self.cria(QUA)
        self.aceita(QUA + MIN, did)
        self.t = QUA + 2 * MIN
        self.pes(self.tk_c, "demanda/pausar", {"id": did, "motivo": "Máquina parada", "obs": "x"})
        self.t = QUA + HORA * 5   # estoura o prazo: o servidor marca "late" na gravação seguinte
        self.cria(QUA + HORA * 5)
        tipos = {f["msg"].split(" · ")[1].split(" (")[0]: f["tipo"] for f in self.get()["feed"]}
        self.assertEqual(tipos["Pausada"], "warn")
        self.assertEqual(tipos["Iniciada"], "ok")
        self.assertEqual(tipos["Prazo estourado"], "warn")
        self.assertEqual(tipos["Solicitação criada"], "")

    def test_vista_do_operador_so_o_do_setor_dele_e_o_que_ele_pediu(self):
        d1 = self.cria(QUA)                                                        # ADM -> CNC
        d2 = self.cria(QUA, tk=self.tk_h)                                          # Helena -> CNC
        d3 = self.cria(QUA, tk=self.tk_c, para={"s": "ESP", "p": None})            # Carlos -> ESP
        ids = lambda tk: sorted(d["id"] for d in self.pes(tk, "vista")["demandas"])  # noqa: E731
        self.assertEqual(ids(self.tk_c), sorted([d1, d2, d3]))     # as do setor dele e a que ele pediu
        self.assertEqual(ids(self.tk_b), sorted([d1, d2]))         # colega de setor: não vê a que o Carlos pediu
        self.assertEqual(ids(self.tk_f), [d3])                     # só a do setor dela
        self.assertEqual(ids(self.tk_h), [d2])                     # quem pediu vê o próprio pedido; não a do ADM
        self.assertEqual(sorted(d["id"] for d in self.get()["demandas"]), sorted([d1, d2, d3]))   # ADM vê tudo

    def test_operador_nao_recebe_dados_de_adm(self):
        v = self.pes(self.tk_c, "vista")
        self.assertEqual(v["papel"], "pessoa")
        self.assertNotIn("anexos_uso", v)
        self.assertNotIn("backup", v)
        self.assertNotIn("emails", v)
        self.assertEqual(v["eu"]["id"], self.carlos)
        self.assertFalse([p for p in v["pessoas"] if "email" in p])


if __name__ == "__main__":
    unittest.main()
