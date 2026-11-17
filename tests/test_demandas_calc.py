"""demandas_calc: regras de tempo, vista por ator, feed, atenção e cronoanálise (funções puras, agora em ms)."""

import datetime
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1] / "demandas"   # pasta do módulo
sys.path.insert(0, str(HERE))

import demandas_calc as calc

MIN = 60000
HORA = 60 * MIN
T0 = 1_800_000_000_000   # um instante qualquer (ms)


def dem(n=1, status="new", criado=T0, est=60, iniciado=None, fim=None, pausas=None, prio="norm", **kw):
    d = {"id": "SOL-%d" % n, "titulo": "Demanda %d" % n, "tipo": "dem", "motivo": "Outro", "prio": prio, "est": est,
         "de": {"s": "PCP", "p": "p1"}, "para": {"s": "CNC", "p": None}, "desc": "x", "status": status,
         "criado": criado, "iniciado": iniciado, "fim": fim, "atraso_avisado": False,
         "pausas": pausas or [], "eventos": [], "comentarios": [], "anexos": [], "_rv": 3}
    d.update(kw)
    return d


def pz(ini, fim=None, motivo="Máquina parada"):
    return {"ini": ini, "fim": fim, "motivo": motivo, "obs": "", "por": "Carlos"}


class Dur(unittest.TestCase):
    def test_faixas(self):
        casos = {0: "0 min", 59: "59 min", 60: "1h", 61: "1h 01min", 90: "1h 30min", 120: "2h",
                 47 * 60 + 59: "47h 59min", 48 * 60: "2d 0h", 50 * 60 + 5: "2d 2h", -5: "0 min", 59.9: "59 min"}
        for m, txt in casos.items():
            self.assertEqual(calc.dur(m), txt, m)


class Tempo(unittest.TestCase):
    def test_ativa_e_prazo(self):
        self.assertEqual([calc.ativa(dem(status=s)) for s in ("new", "prog", "pause", "done", "canc")],
                         [True, True, True, False, False])
        self.assertFalse(calc.ativa({}))
        self.assertEqual(calc.prazo(dem(est=90)), T0 + 90 * MIN)

    def test_pausado(self):
        agora = T0 + 100 * MIN
        d = dem(status="pause", iniciado=T0, pausas=[pz(T0 + MIN, T0 + 3 * MIN), pz(T0 + 10 * MIN)])
        self.assertEqual(calc.pausado_ms(d, agora), 2 * MIN + 90 * MIN)   # a aberta vai até agora
        d["fim"] = T0 + 20 * MIN   # encerrada: a aberta vai até o fim da demanda
        self.assertEqual(calc.pausado_ms(d, agora), 2 * MIN + 10 * MIN)
        ruins = dem(pausas=[{"ini": None}, {"ini": True, "fim": T0}, {"ini": "x"}, pz(T0 + 5 * MIN, T0)])
        self.assertEqual(calc.pausado_ms(ruins, agora), 0)   # sem início ou fim antes do início não soma
        self.assertEqual(calc.pausado_ms({"criado": T0}, agora), 0)
        self.assertEqual(calc.pausado_ms(dem(pausas=[pz(0, 0)]), agora), 0)

    def test_espera(self):
        agora = T0 + 50 * MIN
        self.assertEqual(calc.espera_ms(dem(), agora), 50 * MIN)
        self.assertEqual(calc.espera_ms(dem(iniciado=T0 + 7 * MIN), agora), 7 * MIN)
        self.assertEqual(calc.espera_ms(dem(status="canc", fim=T0 + 4 * MIN), agora), 4 * MIN)
        self.assertEqual(calc.espera_ms(dem(iniciado=0, fim=T0 + 4 * MIN), T0), 0)   # 0 é um valor, não vazio
        self.assertEqual(calc.espera_ms(dem(), T0 - MIN), 0)

    def test_execucao(self):
        agora = T0 + 60 * MIN
        self.assertEqual(calc.execucao_ms(dem(), agora), 0)
        self.assertEqual(calc.execucao_ms(dem(iniciado=T0 + 10 * MIN), agora), 50 * MIN)
        d = dem(status="pause", iniciado=T0 + 10 * MIN, pausas=[pz(T0 + 20 * MIN, T0 + 25 * MIN), pz(T0 + 40 * MIN)])
        self.assertEqual(calc.execucao_ms(d, agora), 25 * MIN)   # 50 - 5 - 20
        antiga = dem(iniciado=T0 + 30 * MIN, pausas=[pz(T0 + 5 * MIN, T0 + 10 * MIN), pz(T0 + 25 * MIN, T0 + 35 * MIN)])
        self.assertEqual(calc.execucao_ms(antiga, agora), 25 * MIN)   # pausa de antes do início não conta, a cortada conta 5
        fora = dem(status="done", iniciado=T0, fim=T0 + 10 * MIN, pausas=[pz(T0 + 8 * MIN, T0 + 30 * MIN)])
        self.assertEqual(calc.execucao_ms(fora, agora), 8 * MIN)
        self.assertEqual(calc.execucao_ms(dem(iniciado=T0 + 10 * MIN), T0), 0)
        self.assertEqual(calc.execucao_ms(dem(iniciado=0, fim=5 * MIN, criado=0), agora), 5 * MIN)

    def test_total_e_atraso(self):
        self.assertEqual(calc.total_ms(dem(), T0 + 9 * MIN), 9 * MIN)
        self.assertEqual(calc.total_ms(dem(status="done", fim=T0 + 3 * MIN), T0 + 9 * MIN), 3 * MIN)
        self.assertEqual(calc.total_ms(dem(), T0 - 1), 0)
        d = dem(est=10)
        self.assertFalse(calc.atrasada(d, T0 + 10 * MIN))
        self.assertTrue(calc.atrasada(d, T0 + 10 * MIN + 1))
        self.assertFalse(calc.atrasada(dem(est=10, status="done", fim=T0), T0 + HORA))
        self.assertTrue(calc.atrasou_concluida(dem(est=10, status="done", fim=T0 + 10 * MIN + 1)))
        self.assertFalse(calc.atrasou_concluida(dem(est=10, status="done", fim=T0 + 10 * MIN)))
        self.assertFalse(calc.atrasou_concluida(dem(est=10, status="canc", fim=T0 + HORA)))
        self.assertFalse(calc.atrasou_concluida(dem(est=10, status="done", fim=None)))

    def test_metricas(self):
        d = dem(status="pause", est=40, iniciado=T0 + 90000, pausas=[pz(T0 + 3 * MIN)])
        m = calc.metricas(d, T0 + 10 * MIN)
        self.assertEqual(m, {"prazo": T0 + 40 * MIN, "atrasada": False, "espera": 1.5, "execucao": 1.5,
                             "pausado": 7.0, "total": 10.0, "sla": 25.0})
        self.assertEqual(calc.metricas(dem(est=7), T0 + 10 * MIN)["sla"], 142.9)
        self.assertTrue(calc.metricas(dem(est=7), T0 + 10 * MIN)["atrasada"])
        self.assertIsNone(calc.metricas(dem(est=0), T0 + MIN)["sla"])
        self.assertIsNone(calc.metricas(dem(est=-3), T0 + MIN)["sla"])
        self.assertEqual(calc.metricas(dem(), T0 + 3)["total"], 0.0)   # arredonda a 0,1 min


class Vista(unittest.TestCase):
    def doc(self):
        d1 = dem(1, para={"s": "CNC", "p": "p2"}, eventos=[{"t": T0, "ev": "created", "quem": "Helena", "nota": ""}],
                 anexos=[{"id": "a0123456789abcdef", "nome": "f.pdf", "tipo": "pdf", "bytes": 3, "por": "Helena",
                          "t": T0, "_p": "p1"}], _interno="x")
        d2 = dem(2, de={"s": "ESP", "p": "p3"}, para={"s": "PCP", "p": None})
        d3 = dem(3, de={"s": "CNC", "p": "p2"}, para={"s": "ESP", "p": None})
        return {"rev": 7, "setores": [{"id": "PCP", "nome": "P", "icone": "🗂️", "cor": "#6366F1", "ativo": True, "_rv": 1},
                                      {"id": "CNC", "nome": "C"}],
                "pessoas": [{"id": "p2", "nome": "Carlos", "setor": "CNC", "mat": "M102", "ativo": True,
                             "sal": "s" * 32, "hash": "h", "_rv": 2},
                            {"id": "p9", "nome": "Velho", "setor": "CNC", "mat": "M109"}],
                "demandas": [d1, d2, d3],
                "notas": [{"id": 1, "aud": "adm", "t": T0}, {"id": 2, "aud": "CNC", "t": T0},
                          {"id": 3, "aud": "adm", "t": T0 + 5}, {"id": 4, "aud": "adm", "t": T0}]}

    def test_publica(self):
        d = self.doc()["demandas"][0]
        p = calc.publica(d, T0 + MIN)
        self.assertNotIn("_interno", p)
        self.assertEqual(p["_rv"], 3)
        self.assertEqual(p["anexos"], [{"id": "a0123456789abcdef", "nome": "f.pdf", "tipo": "pdf", "bytes": 3,
                                        "por": "Helena", "t": T0}])
        self.assertEqual(d["anexos"][0]["_p"], "p1")   # o gravado não muda
        self.assertNotIn("prazo", d)
        for k in ("prazo", "atrasada", "espera", "execucao", "pausado", "total", "sla"):
            self.assertIn(k, p)
        self.assertEqual(calc.publica({**dem(), "anexos": None}, T0)["anexos"], [])

    def test_publicos(self):
        self.assertEqual(calc.pessoa_publica({"id": "p9", "nome": "V", "sal": "x", "hash": "y"}),
                         {"id": "p9", "nome": "V", "setor": None, "mat": None, "ativo": True, "_rv": 0})
        self.assertEqual(calc.setor_publico({"id": "AB", "extra": 1}),
                         {"id": "AB", "nome": None, "icone": None, "cor": None, "ativo": True, "_rv": 0})
        self.assertFalse(calc.pessoa_publica({"id": "p1", "ativo": False})["ativo"])
        self.assertFalse(calc.setor_publico({"id": "AB", "ativo": False})["ativo"])

    def test_vista_adm(self):
        v = calc.vista(self.doc(), T0 + MIN, anexos_uso={"bytes": 3, "cota": 9})
        self.assertEqual((v["rev"], v["agora"], v["papel"], v["eu"]), (7, T0 + MIN, "adm", None))
        self.assertEqual([d["id"] for d in v["demandas"]], ["SOL-1", "SOL-2", "SOL-3"])
        self.assertEqual([n["id"] for n in v["notas"]], [3, 4, 1])   # da mais nova; no empate, o id maior
        self.assertEqual(v["anexos_uso"], {"bytes": 3, "cota": 9})
        self.assertNotIn("sal", str(v["pessoas"]))
        self.assertEqual(v["setores"][1]["ativo"], True)
        self.assertEqual(v["feed"][0]["dem"], "SOL-1")

    def test_vista_pessoa(self):
        eu = {"id": "p2", "nome": "Carlos", "setor": "CNC", "mat": "M102", "sal": "s" * 32, "hash": "h"}
        v = calc.vista(self.doc(), T0, eu, anexos_uso={"bytes": 1})
        self.assertEqual(v["papel"], "pessoa")
        self.assertEqual(v["eu"], {"id": "p2", "nome": "Carlos", "setor": "CNC", "mat": "M102"})
        self.assertEqual([d["id"] for d in v["demandas"]], ["SOL-1", "SOL-3"])   # do setor dela e a que ela pediu
        self.assertEqual([n["id"] for n in v["notas"]], [2])
        self.assertNotIn("anexos_uso", v)
        self.assertNotIn("hash", str(v))
        self.assertTrue(calc.ve(dem(para={"s": "X", "p": None}, de={"s": "Y", "p": "p2"}), eu))
        self.assertFalse(calc.ve(dem(para={"s": "X", "p": "p2"}, de={"s": "Y", "p": "p5"}), eu))

    def test_notas_sem_t_ou_id(self):
        doc = self.doc()
        doc["notas"] = [{"aud": "adm", "id": 5}, {"aud": "adm", "t": T0}]
        self.assertEqual(calc.vista(doc, T0)["notas"], [{"aud": "adm", "t": T0}, {"aud": "adm", "id": 5}])


class Email(unittest.TestCase):
    """O e-mail de pessoa e setor só vai para a tela do ADM."""
    P = {"id": "p1", "nome": "Ana", "setor": "CNC", "mat": "M101", "ativo": True, "_rv": 3, "email": "ana@x.com"}
    S = {"id": "CNC", "nome": "Corte", "icone": "⚙️", "cor": "#3B82F6", "ativo": True, "_rv": 2, "email": "corte@x.com"}

    def test_publica_com_e_sem_adm(self):
        self.assertEqual(calc.pessoa_publica(self.P, True)["email"], "ana@x.com")
        self.assertEqual(calc.setor_publico(self.S, True)["email"], "corte@x.com")
        for f, row in ((calc.pessoa_publica, self.P), (calc.setor_publico, self.S)):
            self.assertNotIn("email", f(row))
            self.assertNotIn("email", f(row, False))
            self.assertNotIn("email", f(dict(row, email=None), True))
            self.assertNotIn("email", f({k: v for k, v in row.items() if k != "email"}, True))
            self.assertEqual(set(f(row, True)) - set(f(row)), {"email"})

    def test_vista(self):
        doc = {"rev": 1, "setores": [self.S], "pessoas": [self.P], "demandas": [], "notas": []}
        adm = calc.vista(doc, T0)
        self.assertEqual((adm["setores"][0]["email"], adm["pessoas"][0]["email"]), ("corte@x.com", "ana@x.com"))
        eu = {"id": "p1", "nome": "Ana", "setor": "CNC", "mat": "M101"}
        pes = calc.vista(doc, T0, eu)
        self.assertNotIn("email", pes["setores"][0])
        self.assertNotIn("email", pes["pessoas"][0])


class NotasPorPessoa(unittest.TestCase):
    EU = {"id": "p1", "setor": "CNC"}

    def doc(self):
        n = lambda i, **kw: dict({"id": i, "aud": "CNC", "pid": None, "t": i, "lida": False, "lidas": []}, **kw)  # noqa: E731
        return {"notas": [n(1), n(2, pid="p1"), n(3, pid="p2"), n(4, aud="PCP"), n(5, aud="adm", lida=True),
                          n(6, lidas=["p1"]), {"id": 7, "aud": "CNC", "t": 7, "lida": True},
                          {"id": 8, "aud": "CNC", "t": 8, "lida": False}, n(9, lida=True)]}

    def test_pessoa(self):
        sel = calc.notas_de(self.doc(), self.EU)
        self.assertEqual([(x["id"], x["lida"]) for x in sel], [(9, False), (8, False), (7, True), (6, True), (2, False), (1, False)])
        self.assertTrue(all("lidas" not in x for x in sel))

    def test_adm(self):
        sel = calc.notas_de(self.doc(), None)
        self.assertEqual([(x["id"], x["lida"]) for x in sel], [(5, True)])
        self.assertNotIn("lidas", sel[0])

    def test_nao_mexe_no_doc(self):
        doc = self.doc()
        calc.notas_de(doc, self.EU)
        self.assertEqual(doc["notas"][5]["lidas"], ["p1"])
        self.assertFalse(doc["notas"][8]["lida"] is not True)

    def test_nota_lida(self):
        self.assertTrue(calc.nota_lida({"lidas": ["p1"], "pid": None}, "p1"))
        self.assertFalse(calc.nota_lida({"lidas": ["p2"], "pid": None, "lida": True}, "p1"), "a do ADM não conta para a pessoa")
        self.assertTrue(calc.nota_lida({"lida": True}, "p1"))
        self.assertFalse(calc.nota_lida({"lida": 1}, "p1"))
        self.assertFalse(calc.nota_lida({}, "p1"))
        self.assertFalse(calc.nota_lida({"lidas": None}, "p1"))


class Feed(unittest.TestCase):
    def test_ordem_tipo_e_texto(self):
        a = dem(1, eventos=[{"t": T0, "ev": "created", "quem": "H", "nota": ""},
                            {"t": T0 + 1, "ev": "assigned", "quem": "H", "nota": "Responsável: C"},
                            {"t": T0 + 2, "ev": "paused", "quem": "C", "nota": "Máquina parada — x"},
                            {"t": T0 + 5, "ev": "done", "quem": "C", "nota": "entregue"}])
        b = dem(2, eventos=[{"t": T0 + 2, "ev": "started", "quem": "C", "nota": ""},
                            {"t": T0 + 3, "ev": "late", "quem": "Sistema"},
                            {"t": T0 + 4, "ev": "nudge", "quem": "H", "nota": ""},
                            {"t": T0 + 6, "ev": "estranho", "quem": "H", "nota": "z"},
                            {"t": "x", "ev": "created"}, "lixo"])
        f = calc.feed([a, b])
        self.assertEqual(f, [
            {"t": T0 + 6, "tipo": "", "dem": "SOL-2", "msg": "SOL-2 · estranho (z)"},
            {"t": T0 + 5, "tipo": "ok", "dem": "SOL-1", "msg": "SOL-1 · Concluída"},
            {"t": T0 + 4, "tipo": "", "dem": "SOL-2", "msg": "SOL-2 · Cobrança enviada"},
            {"t": T0 + 3, "tipo": "warn", "dem": "SOL-2", "msg": "SOL-2 · Prazo estourado"},
            {"t": T0 + 2, "tipo": "ok", "dem": "SOL-2", "msg": "SOL-2 · Iniciada"},   # empate: o gravado depois vem antes
            {"t": T0 + 2, "tipo": "warn", "dem": "SOL-1", "msg": "SOL-1 · Pausada (Máquina parada — x)"},
            {"t": T0, "tipo": "", "dem": "SOL-1", "msg": "SOL-1 · Solicitação criada"}])

    def test_limite(self):
        d = dem(eventos=[{"t": T0 + i, "ev": "nudge", "quem": "H", "nota": ""} for i in range(20)])
        f = calc.feed([d])
        self.assertEqual(len(f), 14)
        self.assertEqual((f[0]["t"], f[-1]["t"]), (T0 + 19, T0 + 6))
        self.assertEqual(len(calc.feed([d], 3)), 3)
        self.assertEqual(calc.feed([{**dem(), "eventos": None}]), [])


class Atencao(unittest.TestCase):
    def test_chave(self):
        agora = T0 + 30 * MIN
        late = dem(1, est=10, prio="low")
        urg = dem(2, prio="urg", est=600)
        norm_cedo = dem(3, est=100)
        norm_tarde = dem(4, est=200)
        estranha = dem(5, prio="??", est=150)
        ordem = sorted([norm_tarde, urg, estranha, norm_cedo, late], key=lambda d: calc.chave_atencao(d, agora))
        self.assertEqual([d["id"] for d in ordem], ["SOL-1", "SOL-2", "SOL-3", "SOL-5", "SOL-4"])

    def test_pausa_aberta(self):
        self.assertIsNone(calc.pausa_aberta(dem()))
        self.assertIsNone(calc.pausa_aberta(dem(pausas=[pz(T0, T0 + 1)])))
        p = pz(T0)
        self.assertIs(calc.pausa_aberta(dem(pausas=[pz(T0 - 5, T0 - 1), p])), p)

    def test_marcas(self):
        agora = T0 + 25 * MIN
        sem = dem(1, est=600, criado=agora - 25 * MIN + 1)
        espera = dem(2, est=600)                                        # 25 min sem aceite
        pausada = dem(3, status="pause", est=600, iniciado=T0, pausas=[pz(agora - 20 * MIN)])
        pouco = dem(4, status="pause", est=600, iniciado=T0, pausas=[pz(agora - 20 * MIN + 1)])
        tudo = dem(5, est=10, prio="urg")
        feita = dem(6, status="done", est=1, prio="urg", fim=T0)
        ruim = dem(7, status="pause", est=600, iniciado=T0, pausas=[{"ini": None, "fim": None}])
        out = calc.atencao([sem, espera, pausada, pouco, tudo, feita, ruim], agora)
        self.assertEqual([(a["id"], a["score"]) for a in out], [("SOL-5", 190), ("SOL-3", 40), ("SOL-2", 30)])
        self.assertEqual(out[0]["tags"], [{"k": "late", "min": 15.0}, {"k": "urg", "min": None},
                                          {"k": "wait", "min": 25.0}])
        self.assertEqual(out[1]["tags"], [{"k": "pause", "min": 20.0}])

    def test_pausa_tambem_espera_nao(self):
        agora = T0 + 40 * MIN
        d = dem(status="prog", est=600, iniciado=T0)
        self.assertEqual(calc.atencao([d], agora), [])


class Segs(unittest.TestCase):
    def test_sem_inicio(self):
        self.assertEqual(calc.segs(dem(), T0 + 5), [{"k": "wait", "a": T0, "b": T0 + 5}])
        self.assertEqual(calc.segs(dem(status="canc", fim=T0 + 3), T0 + 9), [{"k": "wait", "a": T0, "b": T0 + 3}])

    def test_pausas(self):
        d = dem(status="done", iniciado=T0 + 10, fim=T0 + 100,
                pausas=[pz(T0 + 50, T0 + 60), pz(T0 + 20, T0 + 30), pz(T0 + 1, T0 + 5)])
        self.assertEqual(calc.segs(d, T0 + 500), [
            {"k": "wait", "a": T0, "b": T0 + 10}, {"k": "exec", "a": T0 + 10, "b": T0 + 20},
            {"k": "pause", "a": T0 + 20, "b": T0 + 30}, {"k": "exec", "a": T0 + 30, "b": T0 + 50},
            {"k": "pause", "a": T0 + 50, "b": T0 + 60}, {"k": "exec", "a": T0 + 60, "b": T0 + 100}])

    def test_pausa_cortada_e_aberta(self):
        d = dem(status="pause", iniciado=T0 + 10, pausas=[pz(T0 + 5, T0 + 15), pz(T0 + 40)])
        self.assertEqual(calc.segs(d, T0 + 60), [
            {"k": "wait", "a": T0, "b": T0 + 10}, {"k": "pause", "a": T0 + 10, "b": T0 + 15},
            {"k": "exec", "a": T0 + 15, "b": T0 + 40}, {"k": "pause", "a": T0 + 40, "b": T0 + 60}])
        colada = dem(status="prog", iniciado=T0 + 10, pausas=[pz(T0 + 10, T0 + 20)])
        self.assertEqual(calc.segs(colada, T0 + 20), [{"k": "wait", "a": T0, "b": T0 + 10},
                                                      {"k": "pause", "a": T0 + 10, "b": T0 + 20}])
        alem = dem(status="done", iniciado=T0 + 10, fim=T0 + 30, pausas=[pz(T0 + 20, T0 + 90)])
        self.assertEqual(calc.segs(alem, T0 + 99)[-1], {"k": "pause", "a": T0 + 20, "b": T0 + 30})
        inicio_zero = dem(criado=0, iniciado=0, fim=10, status="done")
        self.assertEqual(calc.segs(inicio_zero, 99), [{"k": "wait", "a": 0, "b": 0}, {"k": "exec", "a": 0, "b": 10}])


class Crono(unittest.TestCase):
    def test_inicio_do_dia(self):
        meio = datetime.datetime(2026, 10, 26, 0, 0, 0)
        ms = int(meio.timestamp() * 1000)
        self.assertEqual(calc.inicio_do_dia(ms + 13 * HORA + 1234), ms)
        self.assertEqual(calc.inicio_do_dia(ms), ms)

    def test_vazio(self):
        c = calc.crono([], T0, 7)
        self.assertEqual(c["kpis"], {"abertas": 0, "concluidas": 0, "no_prazo": 0, "pct_prazo": None,
                                     "espera": None, "execucao": None, "pausado": None, "estimado": None})
        self.assertEqual((c["setores"], c["motivos"], c["ranking"]), ([], [], []))
        self.assertEqual(c["gantt"], {"ini": T0 - 10 * HORA, "fim": T0 + 3 * HORA, "linhas": []})
        self.assertEqual((c["dias"], c["desde"]), (7, T0 - 7 * 86400000))
        self.assertEqual(calc.crono([], T0, 30)["desde"], T0 - 30 * 86400000)
        self.assertEqual(calc.crono([], T0, 1)["desde"], calc.inicio_do_dia(T0))

    def test_completo(self):
        agora = T0 + 10 * HORA
        desde = agora - 7 * 86400000

        def feita(n, s, p, espera, execu, est, motivo="Outro", criado=T0, pausa=0):
            ini = criado + espera * MIN
            ps = [pz(ini + MIN, ini + MIN + pausa * MIN)] if pausa else []
            return dem(n, status="done", criado=criado, iniciado=ini, fim=ini + (execu + pausa) * MIN, est=est,
                       para={"s": s, "p": p}, motivo=motivo, pausas=ps)

        rows = [
            feita(1, "CNC", "p1", 10, 30, 60, "Retrabalho", pausa=4),   # total 44 ≤ 60: no prazo
            feita(2, "CNC", "p1", 20, 50, 60, "Retrabalho"),            # 70 > 60: atrasada
            feita(3, "ESP", "p2", 5, 10, 60),
            feita(4, "ESP", None, 5, 10, 60),
            feita(5, "PIN", "p3", 1, 1, 60, criado=desde - 2 * MIN),    # criada antes, concluída no limite
            dem(6, status="done", criado=desde - 3 * HORA, iniciado=desde - 2 * HORA, fim=desde - HORA),   # fora
            dem(7, status="new", criado=T0 + HORA, motivo="Retrabalho"),
            dem(8, status="canc", criado=T0, fim=T0 + MIN, motivo="Falta de material"),
        ]
        c = calc.crono(rows, agora, 7)
        k = c["kpis"]
        self.assertEqual((k["abertas"], k["concluidas"], k["no_prazo"], k["pct_prazo"]), (6, 5, 4, 80))
        self.assertEqual((k["espera"], k["execucao"], k["pausado"], k["estimado"]), (8.2, 20.2, 0.8, 60.0))
        self.assertEqual(c["setores"], [
            {"s": "CNC", "n": 2, "espera": 15.0, "execucao": 40.0, "pausado": 2.0, "estimado": 60.0, "sla": 50},
            {"s": "ESP", "n": 2, "espera": 5.0, "execucao": 10.0, "pausado": 0.0, "estimado": 60.0, "sla": 100},
            {"s": "PIN", "n": 1, "espera": 1.0, "execucao": 1.0, "pausado": 0.0, "estimado": 60.0, "sla": 100}])
        self.assertEqual(c["motivos"], [{"motivo": "Retrabalho", "n": 3}, {"motivo": "Outro", "n": 2},
                                        {"motivo": "Falta de material", "n": 1}])
        self.assertEqual(c["ranking"], [{"p": "p1", "n": 2, "sla": 50}, {"p": "p2", "n": 1, "sla": 100},
                                        {"p": "p3", "n": 1, "sla": 100}])

    def test_topos_e_desempates(self):
        agora = T0 + HORA
        rows = [dem(i, criado=T0, motivo="M%02d" % i) for i in range(10)]
        rows += [dem(20, criado=T0, motivo="M05")]
        mot = calc.crono(rows, agora, 7)["motivos"]
        self.assertEqual(len(mot), 8)
        self.assertEqual(mot[0], {"motivo": "M05", "n": 2})
        self.assertEqual([m["motivo"] for m in mot[1:]], ["M00", "M01", "M02", "M03", "M04", "M06", "M07"])
        feitas = [dem(30 + i, status="done", criado=T0, iniciado=T0, fim=T0 + (5 if i % 2 else 120) * MIN,
                      para={"s": "CNC", "p": "p%d" % (i % 8)}) for i in range(16)]
        rk = calc.crono(feitas, agora, 7)["ranking"]
        self.assertEqual(len(rk), 6)
        self.assertEqual([r["p"] for r in rk], ["p1", "p3", "p5", "p7", "p0", "p2"])   # n igual: sla maior, depois id
        self.assertEqual(rk[0]["sla"], 100)
        self.assertEqual(rk[4]["sla"], 0)
        st = calc.crono([dem(50, status="done", criado=T0, iniciado=T0, fim=T0 + MIN, para={"s": "B", "p": None}),
                         dem(51, status="done", criado=T0, iniciado=T0, fim=T0 + MIN, para={"s": "A", "p": None}),
                         dem(52, status="done", criado=T0, iniciado=T0, fim=T0 + MIN, para={"s": "C", "p": None}),
                         dem(53, status="done", criado=T0, iniciado=T0, fim=T0 + MIN, para={"s": "C", "p": None})],
                        agora, 7)["setores"]
        self.assertEqual([s["s"] for s in st], ["C", "A", "B"])   # sla igual: n maior, depois a sigla

    def test_concluida_sem_fim_nao_conta(self):
        c = calc.crono([dem(1, status="done", fim=None)], T0 + MIN, 7)
        self.assertEqual(c["kpis"]["concluidas"], 0)
        self.assertEqual(c["gantt"]["linhas"], [])

    def test_gantt(self):
        agora = T0 + 20 * HORA
        ativas = [dem(i, criado=T0 + i * MIN, est=60 * 30) for i in range(1, 17)]   # nenhuma atrasada
        ativas[15]["prio"] = "urg"
        ativas.append(dem(40, status="pause", criado=T0, est=1, iniciado=T0, pausas=[pz(T0 + MIN)]))   # atrasada
        feitas = [dem(50 + i, status="done", criado=T0 + i, iniciado=T0 + i, fim=agora - i * HORA, est=60 * 30)
                  for i in range(6)]
        feitas.append(dem(70, status="done", criado=T0, fim=agora - 11 * HORA, iniciado=T0))   # antes da janela
        feitas.append(dem(71, status="done", criado=T0 - 1, iniciado=T0, fim=T0 + MIN, est=0))
        g = calc.gantt(ativas + feitas, agora)
        ids = [r["id"] for r in g["linhas"]]
        self.assertEqual(len(ids), 18)
        self.assertIn("SOL-40", ids)
        self.assertIn("SOL-16", ids)          # a urgente entra
        self.assertNotIn("SOL-15", ids)       # as mais folgadas ficam de fora
        self.assertNotIn("SOL-14", ids)
        self.assertEqual([i for i in ids if len(i) == 6 and i.startswith("SOL-5")], ["SOL-50", "SOL-51", "SOL-52", "SOL-53"])
        self.assertNotIn("SOL-70", ids)
        self.assertEqual(ids[:2], ["SOL-40", "SOL-50"])   # pela criação
        linha = next(r for r in g["linhas"] if r["id"] == "SOL-40")
        self.assertEqual(linha, {"id": "SOL-40", "de": "PCP", "para": "CNC", "titulo": "Demanda 40",
                                 "segs": calc.segs(ativas[16], agora), "prazo": T0 + MIN, "atrasada": True,
                                 "viva": True})
        f = next(r for r in g["linhas"] if r["id"] == "SOL-50")
        self.assertEqual((f["viva"], f["atrasada"]), (False, False))
        tarde = calc.gantt([dem(80, status="done", criado=agora - HORA, iniciado=agora - HORA, fim=agora, est=1)], agora)
        self.assertTrue(tarde["linhas"][0]["atrasada"])


class Sobreviventes(unittest.TestCase):
    """Casos que a mutação mostrou sem teste."""

    def test_pesos_de_prioridade(self):
        agora = T0
        def par(alta, baixa):
            a = dem(1, prio=alta, est=200)
            b = dem(2, prio=baixa, est=100)   # prazo antes, mas prioridade menor
            return [d["id"] for d in sorted([b, a], key=lambda d: calc.chave_atencao(d, agora))]
        self.assertEqual(par("norm", "low"), ["SOL-1", "SOL-2"])
        self.assertEqual(par("high", "norm"), ["SOL-1", "SOL-2"])
        self.assertEqual(par("urg", "high"), ["SOL-1", "SOL-2"])
        self.assertEqual(par("high", "estranha"), ["SOL-1", "SOL-2"])
        self.assertEqual(par("estranha", "low"), ["SOL-1", "SOL-2"])

    def test_textos_do_feed(self):
        evs = ["created", "started", "paused", "resumed", "done", "canc", "reassigned", "prio", "deadline", "nudge",
               "late", "attach"]
        d = dem(eventos=[{"t": T0 + i, "ev": e, "quem": "H", "nota": ""} for i, e in enumerate(evs)])
        msgs = [f["msg"][len("SOL-1 · "):] for f in reversed(calc.feed([d], 20))]
        self.assertEqual(msgs, ["Solicitação criada", "Iniciada", "Pausada", "Retomada", "Concluída", "Cancelada",
                                "Reatribuída", "Prioridade alterada", "Prazo ajustado", "Cobrança enviada",
                                "Prazo estourado", "Anexo enviado"])

    def test_arredondamentos(self):
        d = dem(est=1, iniciado=T0 + 75000)
        m = calc.metricas(d, T0 + 75000)
        self.assertEqual((m["espera"], m["total"], m["sla"]), (1.2, 1.2, 125.0))
        k = calc.crono([dem(1, status="done", criado=T0, iniciado=T0 + 75000, fim=T0 + 75000, est=1),
                        dem(2, status="done", criado=T0, iniciado=T0 + 60000, fim=T0 + 60000, est=2)],
                       T0 + MIN * 10, 7)["kpis"]
        self.assertEqual((k["espera"], k["estimado"]), (1.1, 1.5))

    def test_publicos_completos(self):
        p = {"id": "p1", "nome": "N", "setor": "CNC", "mat": "M101", "ativo": False, "_rv": 4, "sal": "x"}
        self.assertEqual(calc.pessoa_publica(p), {"id": "p1", "nome": "N", "setor": "CNC", "mat": "M101",
                                                  "ativo": False, "_rv": 4})
        s = {"id": "CNC", "nome": "C", "icone": "⚙️", "cor": "#3B82F6", "ativo": False, "_rv": 9}
        self.assertEqual(calc.setor_publico(s), s)

    def test_ordem_das_notas_sem_campos(self):
        doc = {"rev": 0, "setores": [], "pessoas": [], "demandas": [],
               "notas": [{"aud": "adm", "id": 9}, {"aud": "adm", "id": 2, "t": 1}]}
        self.assertEqual([n["id"] for n in calc.vista(doc, T0)["notas"]], [2, 9])
        doc["notas"] = [{"aud": "adm", "t": 5}, {"aud": "adm", "id": 1, "t": 5}]
        self.assertEqual(calc.vista(doc, T0)["notas"][0], {"aud": "adm", "id": 1, "t": 5})

    def test_atencao_inativa_no_inicio_e_soma(self):
        agora = T0 + 60 * MIN
        feita = dem(1, status="done", fim=T0)
        tudo = dem(2, status="pause", est=10, prio="urg", iniciado=T0, pausas=[pz(T0 + 30 * MIN)])
        out = calc.atencao([feita, tudo], agora)
        self.assertEqual([(a["id"], a["score"]) for a in out], [("SOL-2", 200)])

    def test_pausa_que_termina_no_inicio(self):
        d = dem(status="prog", iniciado=T0 + 10, pausas=[pz(T0 + 5, T0 + 10)])
        self.assertEqual(calc.segs(d, T0 + 20), [{"k": "wait", "a": T0, "b": T0 + 10},
                                                 {"k": "exec", "a": T0 + 10, "b": T0 + 20}])

    def test_limites_da_janela(self):
        agora = T0 + 30 * 86400000
        desde = agora - 7 * 86400000
        c = calc.crono([dem(1, criado=desde), dem(2, criado=desde - 1)], agora, 7)
        self.assertEqual(c["kpis"]["abertas"], 1)
        ini = agora - 10 * 3600000
        g = calc.gantt([dem(3, status="done", criado=T0, iniciado=T0, fim=ini),
                        dem(4, status="done", criado=T0, iniciado=T0, fim=ini - 1)], agora)
        self.assertEqual([r["id"] for r in g["linhas"]], ["SOL-3"])

    def test_desempate_dos_motivos_fora_da_ordem_de_entrada(self):
        rows = [dem(i, motivo=m) for i, m in enumerate(["Outro", "Retrabalho", "Falta de material"])]
        self.assertEqual([m["motivo"] for m in calc.crono(rows, T0 + MIN, 7)["motivos"]],
                         ["Falta de material", "Outro", "Retrabalho"])


class GanttJanela(unittest.TestCase):
    """A janela do cronograma: cálculo de tempo, por isso meta de 90% de cobertura e de mutação."""

    LINHA = {"id", "de", "para", "titulo", "segs", "prazo", "atrasada", "viva"}

    def test_janela_de_hoje_inalterada(self):
        """Sem `por`, a saída é a de sempre: nem chave nova no objeto, nem na linha."""
        g = calc.gantt([dem(1)], T0 + MIN)
        self.assertEqual(set(g), {"ini", "fim", "linhas"})
        self.assertEqual(set(g["linhas"][0]), self.LINHA)
        self.assertEqual((g["ini"], g["fim"]), (T0 + MIN - 10 * HORA, T0 + MIN + 3 * HORA))

    def test_janela_explicita_sem_agrupar(self):
        """ini/fim valem sem `por`, e a seleção de 14 ativas + 4 concluídas continua a mesma."""
        rows = [dem(i) for i in range(20)] + [dem(100 + i, status="done", fim=T0 + MIN) for i in range(6)]
        g = calc.gantt(rows, T0 + MIN, T0 - 2 * HORA, T0 + 2 * HORA)
        self.assertEqual((g["ini"], g["fim"]), (T0 - 2 * HORA, T0 + 2 * HORA))
        self.assertEqual(set(g), {"ini", "fim", "linhas"})
        self.assertEqual(len(g["linhas"]), calc.GANTT_ATIVAS + calc.GANTT_FEITAS)

    def test_janela(self):
        self.assertEqual(calc._janela(T0), (T0 - 10 * HORA, T0 + 3 * HORA))
        self.assertEqual(calc._janela(T0, T0 + HORA, T0 - HORA), (T0 - HORA, T0 + HORA))   # invertida, ordenada
        self.assertEqual(calc._janela(T0, T0, T0), (T0, T0))                               # vazia, não estoura
        self.assertEqual(calc._janela(T0, T0 + HORA, None), (T0 + HORA, T0 + 3 * HORA))
        self.assertEqual(calc._janela(T0, None, T0 - HORA), (T0 - 10 * HORA, T0 - HORA))
        self.assertEqual(calc._janela(T0, 0, 0), (0, 0))   # 0 é limite, não "não informado"

    def test_na_janela_um_caso_por_ramo(self):
        j = (T0, T0 + 4 * HORA)
        # prazo dentro da janela, trechos fora: entra pelo prazo
        self.assertIs(calc._na_janela(dem(1, criado=T0 - 10 * HORA, est=11 * 60, fim=T0 - 9 * HORA, status="done"),
                                      *j, T0 + 5 * HORA), True)
        # concluída inteiramente antes: sai
        self.assertIs(calc._na_janela(dem(2, criado=T0 - 10 * HORA, est=60, fim=T0 - 9 * HORA, status="done"),
                                      *j, T0 + 5 * HORA), False)
        # concluída com um trecho cruzando o começo da janela: entra
        self.assertIs(calc._na_janela(dem(3, criado=T0 - HORA, est=60, iniciado=T0 - HORA, fim=T0 + HORA,
                                          status="done"), *j, T0 + 5 * HORA), True)
        # engloba a janela inteira: entra
        self.assertIs(calc._na_janela(dem(4, criado=T0 - 10 * HORA, est=60, iniciado=T0 - 10 * HORA,
                                          fim=T0 + 10 * HORA, status="done"), *j, T0 + 20 * HORA), True)
        # toda depois: sai
        self.assertIs(calc._na_janela(dem(5, criado=T0 + 9 * HORA, est=60, fim=T0 + 10 * HORA, status="done"),
                                      *j, T0 + 11 * HORA), False)
        # encosta na borda sem cruzar: sai (fim exatamente em ini)
        self.assertIs(calc._na_janela(dem(6, criado=T0 - HORA, est=600, fim=T0, status="done"),
                                      *j, T0 + 5 * HORA), False)

    def test_por_setor(self):
        rows = [dem(1, para={"s": "CNC", "p": "a"}), dem(2, para={"s": "CNC", "p": "b"}),
                dem(3, para={"s": "ALM", "p": "c"}, status="done", fim=T0 + MIN),
                dem(4, para={"s": "SLD", "p": "d"})]
        g = calc.gantt(rows, T0 + MIN, T0 - HORA, T0 + 2 * HORA, "setor")
        self.assertEqual(set(g), {"ini", "fim", "por", "agora", "cortado", "grupos"})
        self.assertEqual((g["por"], g["agora"], g["cortado"]), ("setor", T0 + MIN, False))
        # CNC tem 2 ativas, SLD 1 ativa, ALM nenhuma: ativas desc, depois total desc, depois a sigla
        self.assertEqual([x["chave"] for x in g["grupos"]], ["CNC", "SLD", "ALM"])
        self.assertEqual([(x["n"], x["ativas"]) for x in g["grupos"]], [(2, 2), (1, 1), (1, 0)])
        ids = [ln["id"] for x in g["grupos"] for ln in x["linhas"]]
        self.assertEqual(sorted(ids), ["SOL-1", "SOL-2", "SOL-3", "SOL-4"])   # nenhuma repetida entre grupos
        self.assertEqual(len(ids), len(set(ids)))

    def test_por_setor_desempata_pela_sigla(self):
        rows = [dem(1, para={"s": "ZZZ", "p": "a"}), dem(2, para={"s": "AAA", "p": "b"})]
        g = calc.gantt(rows, T0 + MIN, T0 - HORA, T0 + 2 * HORA, "setor")
        self.assertEqual([x["chave"] for x in g["grupos"]], ["AAA", "ZZZ"])

    def test_por_pessoa(self):
        rows = [dem(1, para={"s": "CNC", "p": "ana"}), dem(2, para={"s": "CNC", "p": "ana"}),
                dem(3, para={"s": "CNC", "p": None}), dem(4, para={"s": "ALM", "p": None})]
        g = calc.gantt(rows, T0 + MIN, T0 - HORA, T0 + 2 * HORA, "pessoa")
        chaves = [x["chave"] for x in g["grupos"]]
        self.assertEqual(sorted(chaves, key=str), [None, "ana"])   # a fila do setor é um grupo só
        porc = {x["chave"]: x for x in g["grupos"]}
        self.assertEqual(porc["ana"]["n"], 2)   # duas da mesma pessoa no mesmo grupo
        self.assertEqual(porc[None]["n"], 2)    # SOL-3 e SOL-4 juntas, sem pessoa
        self.assertEqual([ln["id"] for ln in porc["ana"]["linhas"]], ["SOL-1", "SOL-2"])   # por criação

    def test_plano_e_pessoa_so_no_multidia(self):
        d = dem(1, criado=T0, est=90, para={"s": "CNC", "p": "ana"})
        ln = calc.gantt([d], T0 + MIN, T0 - HORA, T0 + 4 * HORA, "setor")["grupos"][0]["linhas"][0]
        self.assertEqual(set(ln), self.LINHA | {"p", "plano"})
        self.assertEqual(ln["plano"], {"a": T0, "b": T0 + 90 * MIN})
        self.assertEqual(ln["p"], "ana")
        self.assertNotIn("plano", calc.gantt([d], T0 + MIN)["linhas"][0])   # ausente na janela de hoje
        self.assertNotIn("p", calc.gantt([d], T0 + MIN)["linhas"][0])

    def test_plano_com_est_grande_e_pequeno(self):
        grande = dem(1, criado=T0, est=calc.DIA // MIN)   # prazo muito depois do fim da janela
        ln = calc.gantt([grande], T0 + MIN, T0 - HORA, T0 + HORA, "setor")["grupos"][0]["linhas"][0]
        self.assertEqual(ln["plano"], {"a": T0, "b": T0 + calc.DIA})
        curto = dem(2, criado=T0, est=0)
        ln2 = calc.gantt([curto], T0 + MIN, T0 - HORA, T0 + HORA, "setor")["grupos"][0]["linhas"][0]
        self.assertEqual(ln2["plano"], {"a": T0, "b": T0})   # est=0: plano de duração zero, sem estourar

    def test_limite_e_cortado(self):
        rows = [dem(i, criado=T0 + i * MIN) for i in range(5)]
        j = (T0 - HORA, T0 + 6 * HORA)
        g = calc.gantt(rows, T0 + MIN, *j, "setor", limite=2)
        self.assertIs(g["cortado"], True)
        self.assertEqual(sum(len(x["linhas"]) for x in g["grupos"]), 2)
        cabe = calc.gantt(rows, T0 + MIN, *j, "setor", limite=5)
        self.assertIs(cabe["cortado"], False)
        self.assertEqual(sum(len(x["linhas"]) for x in cabe["grupos"]), 5)
        zero = calc.gantt(rows, T0 + MIN, *j, "setor", limite=0)
        self.assertEqual((zero["grupos"], zero["cortado"]), ([], True))

    def test_teto_padrao(self):
        rows = [dem(i, criado=T0 + i * MIN) for i in range(calc.GANTT_MULTI + 30)]
        g = calc.gantt(rows, T0 + MIN, T0 - HORA, T0 + 200 * HORA, "setor")
        self.assertEqual(sum(len(x["linhas"]) for x in g["grupos"]), calc.GANTT_MULTI)
        self.assertIs(g["cortado"], True)

    def test_corte_respeita_a_atencao(self):
        """Com o teto estourado, a atrasada e a urgente ficam; a tranquila sai."""
        j = (T0 - 10 * HORA, T0 + 10 * HORA)
        agora = T0 + 5 * HORA
        atras = dem(1, criado=T0, est=60)                      # prazo T0+1h, já estourado em agora
        urg = dem(2, criado=T0 + 4 * HORA, est=600, prio="urg")
        calma = dem(3, criado=T0 + 4 * HORA, est=600, prio="low")
        g = calc.gantt([calma, urg, atras], agora, *j, "setor", limite=2)
        self.assertEqual(sorted(ln["id"] for x in g["grupos"] for ln in x["linhas"]), ["SOL-1", "SOL-2"])
        self.assertIs(g["cortado"], True)

    def test_cancelada_nunca_entra(self):
        """O multidia mostra ativas e concluídas; cancelada fica fora mesmo dentro da janela."""
        c = dem(1, status="canc", criado=T0, est=60, fim=T0 + MIN)
        self.assertEqual(calc.gantt([c], T0 + MIN, T0 - HORA, T0 + 2 * HORA, "setor")["grupos"], [])

    def test_janela_nao_usa_fuso(self):
        """A janela é só aritmética de ms: o mesmo instante dá o mesmo resultado em qualquer fuso."""
        rows = [dem(1, criado=T0, est=60)]
        a = calc.gantt(rows, T0 + MIN, T0 - 31 * calc.DIA, T0, "setor")
        b = calc.gantt(rows, T0 + MIN, T0 - 31 * calc.DIA, T0, "setor")
        self.assertEqual(a, b)
        self.assertEqual((a["ini"], a["fim"]), (T0 - 31 * calc.DIA, T0))

    def test_constantes(self):
        """Os números são contrato com a tela e com o CONTRATO.md; um teste que os lesse não os travaria."""
        self.assertEqual((calc.GANTT_ATIVAS, calc.GANTT_FEITAS), (14, 4))
        self.assertEqual((calc.GANTT_ATRAS, calc.GANTT_FRENTE), (10 * HORA, 3 * HORA))
        self.assertEqual(calc.GANTT_MULTI, 120)

    def test_na_janela_nas_bordas_exatas(self):
        j = (T0, T0 + 4 * HORA)
        agora = T0 + 10 * HORA
        # prazo exatamente no começo da janela: entra
        self.assertIs(calc._na_janela(dem(1, criado=T0 - HORA, est=60, fim=T0 - 30 * MIN, status="done"),
                                      *j, agora), True)
        # prazo exatamente no fim da janela: entra
        self.assertIs(calc._na_janela(dem(2, criado=T0 + 3 * HORA, est=60, fim=T0 + 3 * HORA + MIN,
                                          status="done"), *j, agora), True)
        # um trecho que começa exatamente no fim da janela, com o prazo depois: não entra
        self.assertIs(calc._na_janela(dem(3, criado=T0 + 4 * HORA, est=60, fim=T0 + 6 * HORA, status="done"),
                                      *j, agora), False)
        # um trecho que termina exatamente no começo da janela: não entra
        self.assertIs(calc._na_janela(dem(4, criado=T0 - 2 * HORA, est=600, fim=T0, status="done"),
                                      *j, agora), False)
        # prazo exatamente no fim da janela e nenhum trecho cruzando: entra só pelo prazo. Isola o ramo do
        # prazo do ramo dos trechos, que no caso acima respondia pelos dois.
        so_prazo = dem(5, criado=T0 + 4 * HORA, est=0, fim=T0 + 4 * HORA, status="done")
        self.assertEqual([(s["a"], s["b"]) for s in calc.segs(so_prazo, agora)], [(T0 + 4 * HORA, T0 + 4 * HORA)])
        self.assertIs(calc._na_janela(so_prazo, *j, agora), True)

    def test_grupos_desempatam_pelo_total_antes_da_chave(self):
        """Com as mesmas ativas, ganha quem tem mais linhas — e isso vem antes da ordem alfabética."""
        rows = [dem(1, para={"s": "ZZZ", "p": "a"}),
                dem(2, para={"s": "ZZZ", "p": "b"}, status="done", fim=T0 + MIN),
                dem(3, para={"s": "ZZZ", "p": "c"}, status="done", fim=T0 + MIN),
                dem(4, para={"s": "AAA", "p": "d"})]
        g = calc.gantt(rows, T0 + MIN, T0 - HORA, T0 + 2 * HORA, "setor")
        self.assertEqual([(x["chave"], x["n"], x["ativas"]) for x in g["grupos"]], [("ZZZ", 3, 1), ("AAA", 1, 1)])

    def test_crono_continua_chamando_a_janela_de_hoje(self):
        g = calc.crono([dem(1)], T0 + MIN, 7)["gantt"]
        self.assertEqual(set(g), {"ini", "fim", "linhas"})


# ---------- horário de serviço ----------

import demandas_agenda as ag


def loc(a, m, d, h=0, mi=0):
    """Instante local em ms: o horário de serviço é da hora do relógio, não de um T0 qualquer."""
    return int(datetime.datetime(a, m, d, h, mi).timestamp() * 1000)


SEXTA, SEG2 = loc(2026, 11, 13), loc(2026, 11, 16)   # sexta e a segunda seguinte
AGENDA = {"ativa": True, "v": 1, "padrao": {"dias": [1, 2, 3, 4, 5], "turnos": [["07:00", "12:00"], ["13:00", "17:00"]]},
          "setores": {}, "feriados": []}
AGENDAS = {"1": AGENDA}


def hora(d):
    """Demanda criada na sexta às 16:00, com estimativa de 60 min, no horário de serviço da versão 1 (prazo gravado
    na segunda às 12:00, longe: os testes de atenção não querem 'atrasada' por acidente)."""
    return dem(1, **{"criado": SEXTA + 16 * HORA, "est": 60, "agenda_v": 1, "prazo_em": SEG2 + 12 * HORA, **d})


class Util(unittest.TestCase):
    def test_prazo_gravado_vence_o_corrido(self):
        self.assertEqual(calc.prazo(dem(est=90)), T0 + 90 * MIN)
        self.assertEqual(calc.prazo(dem(est=90, prazo_em=T0 + 5)), T0 + 5)
        self.assertEqual(calc.prazo(dem(est=90, prazo_em=0)), 0)                     # 0 é um valor
        for ruim in (None, "9", 1.5, True):
            self.assertEqual(calc.prazo(dem(est=90, prazo_em=ruim)), T0 + 90 * MIN, ruim)

    def test_grade_de(self):
        self.assertIsNone(calc.grade_de(dem(), AGENDAS))                              # sem agenda_v: corrido
        self.assertIsNone(calc.grade_de(dem(agenda_v=1), None))
        self.assertIsNone(calc.grade_de(dem(agenda_v=1), {}))
        self.assertIsNone(calc.grade_de(dem(agenda_v=2), AGENDAS))                    # versão que já não existe
        g = calc.grade_de(dem(agenda_v=1), AGENDAS)
        self.assertEqual(g["dias"], frozenset({1, 2, 3, 4, 5}))
        sld = {"1": {**AGENDA, "setores": {"CNC": {"dias": [6], "turnos": [["06:00", "10:00"]]}}}}
        self.assertEqual(calc.grade_de(dem(agenda_v=1), sld)["dias"], frozenset({6}))   # o setor destino manda

    def test_duracoes_so_no_expediente(self):
        d = hora({"iniciado": SEG2 + 9 * HORA, "fim": SEG2 + 11 * HORA, "status": "done",
                  "pausas": [pz(SEG2 + 9 * HORA + 30 * MIN, SEG2 + 10 * HORA)]})
        agora = SEG2 + 12 * HORA
        self.assertEqual(calc.espera_ms(d, agora, AGENDAS), 3 * HORA)       # sexta 16-17 e segunda 7-9
        self.assertEqual(calc.pausado_ms(d, agora, AGENDAS), 30 * MIN)
        self.assertEqual(calc.execucao_ms(d, agora, AGENDAS), 90 * MIN)
        self.assertEqual(calc.total_ms(d, agora, AGENDAS), 5 * HORA)
        # sem as agendas: tempo corrido como sempre
        self.assertEqual(calc.total_ms(d, agora), SEG2 + 11 * HORA - (SEXTA + 16 * HORA))
        self.assertEqual(calc.espera_ms(d, agora), SEG2 + 9 * HORA - (SEXTA + 16 * HORA))

    def test_pausa_que_atravessa_o_fim_de_semana(self):
        d = hora({"iniciado": SEXTA + 16 * HORA, "status": "pause",
                  "pausas": [pz(SEXTA + 16 * HORA, SEG2 + 8 * HORA)]})
        self.assertEqual(calc.pausado_ms(d, SEG2 + 9 * HORA, AGENDAS), 2 * HORA)   # 16-17 e 7-8
        self.assertEqual(calc.execucao_ms(d, SEG2 + 9 * HORA, AGENDAS), HORA)      # 3 h úteis (16-17, 7-9) menos 2 h

    def test_pausa_aberta_vai_ate_agora_util(self):
        d = hora({"iniciado": SEXTA + 16 * HORA, "status": "pause", "pausas": [pz(SEXTA + 16 * HORA + 30 * MIN)]})
        self.assertEqual(calc.pausado_ms(d, SEG2 + 7 * HORA + 30 * MIN, AGENDAS), 60 * MIN)   # 30 min de sexta + 30 de segunda

    def test_ativa_mede_ate_agora(self):
        d = hora({})
        self.assertEqual(calc.espera_ms(d, SEXTA + 18 * HORA, AGENDAS), HORA)      # a noite não conta
        self.assertEqual(calc.espera_ms(d, SEG2 + 7 * HORA + 15 * MIN, AGENDAS), HORA + 15 * MIN)
        self.assertEqual(calc.execucao_ms(d, SEG2, AGENDAS), 0)                    # não iniciada

    def test_fechada_usa_o_fim_e_nao_o_agora(self):
        d = hora({"status": "canc", "fim": SEXTA + 16 * HORA + 30 * MIN})
        self.assertEqual(calc.total_ms(d, SEG2 + 20 * HORA, AGENDAS), 30 * MIN)

    def test_versao_ausente_cai_no_corrido(self):
        d = hora({"fim": SEG2 + HORA, "status": "done"})
        self.assertEqual(calc.total_ms(d, SEG2, {"9": AGENDA}), SEG2 + HORA - (SEXTA + 16 * HORA))

    def test_congela_grava_e_vale_sem_agenda(self):
        d = hora({"iniciado": SEG2 + 9 * HORA, "fim": SEG2 + 11 * HORA, "status": "done",
                  "pausas": [pz(SEG2 + 9 * HORA + 30 * MIN, SEG2 + 10 * HORA)]})
        calc.congela(d, SEG2 + 11 * HORA, AGENDAS)
        self.assertEqual(d["util"], {"espera": 3 * HORA, "execucao": 90 * MIN, "pausado": 30 * MIN, "total": 5 * HORA,
                                     "atraso": 0})
        for nome, esperado in (("espera_ms", 3 * HORA), ("execucao_ms", 90 * MIN),
                               ("pausado_ms", 30 * MIN), ("total_ms", 5 * HORA)):
            self.assertEqual(getattr(calc, nome)(d, SEG2 + 99 * HORA), esperado, nome)   # sem agendas: o gravado
        d["util"]["total"] = 7
        calc.congela(d, SEG2 + 11 * HORA, AGENDAS)
        self.assertEqual(d["util"]["total"], 5 * HORA, "mede de novo, não repete o valor antigo")

    def test_atraso_util_gravado_e_publicado(self):
        # prazo segunda 07:30; concluída terça 08:00: 8,5 h úteis de segunda + 1 h de terça = 9,5 h de atraso útil
        base = {"prazo_em": SEG2 + 7 * HORA + 30 * MIN, "fim": SEG2 + 24 * HORA + 8 * HORA, "status": "done"}
        d = hora(base)
        self.assertEqual(calc.publica(d, SEG2 + 99 * HORA, AGENDAS)["atraso"], 570.0)   # 07:30-12:00 e 13:00-17:00 de segunda, mais 07:00-08:00 de terça
        calc.congela(d, d["fim"], AGENDAS)
        self.assertEqual(d["util"]["atraso"], 570 * MIN)
        self.assertEqual(calc.publica(d, SEG2 + 99 * HORA)["atraso"], 570.0)    # sem agendas: lê o gravado
        no_prazo = hora({"prazo_em": SEG2 + 12 * HORA, "fim": SEG2 + 10 * HORA, "status": "done"})
        self.assertEqual(calc.publica(no_prazo, SEG2 + 99 * HORA, AGENDAS)["atraso"], 0.0)
        for chave in (hora({"status": "canc", "fim": SEG2 + HORA}), dem(status="done", fim=T0 + 5 * MIN)):
            self.assertNotIn("atraso", calc.publica(chave, SEG2 + 99 * HORA, AGENDAS))   # só concluída de horário de serviço
        self.assertNotIn("atraso", calc.publica(hora({}), SEG2, AGENDAS))

    def test_congela_so_de_demanda_com_horario(self):
        d = dem(status="done", fim=T0 + MIN)
        calc.congela(d, T0 + MIN, AGENDAS)
        self.assertNotIn("util", d)

    def test_util_gravado_so_vale_para_fechada(self):
        viva = hora({"util": {"espera": 1, "execucao": 2, "pausado": 3, "total": 4}})
        self.assertEqual(calc.total_ms(viva, SEXTA + 18 * HORA, AGENDAS), HORA)
        feita = hora({"status": "done", "fim": SEG2, "util": {"espera": 1, "execucao": 2, "pausado": 3, "total": 4}})
        self.assertEqual(calc.espera_ms(feita, SEG2 + HORA), 1)
        for ruim in (None, "x", {"espera": "1"}, {}):
            f = hora({"status": "done", "fim": SEXTA + 17 * HORA, "util": ruim})
            self.assertEqual(calc.total_ms(f, SEG2, AGENDAS), HORA, ruim)

    def test_metricas_e_sla_em_tempo_util(self):
        d = hora({"status": "done", "fim": SEG2 + 7 * HORA + 30 * MIN})   # criada sexta 16:00, est 60 min
        m = calc.metricas(d, SEG2 + 12 * HORA, AGENDAS)
        self.assertEqual((m["total"], m["sla"]), (90.0, 150.0))
        corrido = calc.metricas(d, SEG2 + 12 * HORA)["total"]
        self.assertEqual(corrido, round((SEG2 + 7.5 * HORA - SEXTA - 16 * HORA) / MIN, 1))
        self.assertEqual(calc.publica(d, SEG2 + 12 * HORA, AGENDAS)["total"], 90.0)

    def test_atrasada_usa_o_prazo_gravado(self):
        prazo_em = ag.soma_util(ag.grade(AGENDA, "CNC"), SEXTA + 16 * HORA + 30 * MIN, 60)
        d = dem(criado=SEXTA + 16 * HORA + 30 * MIN, est=60, prazo_em=prazo_em, agenda_v=1)
        self.assertFalse(calc.atrasada(d, SEXTA + 23 * HORA))                       # a noite de sexta não atrasa
        self.assertFalse(calc.atrasada(d, SEG2 + 7 * HORA + 30 * MIN))              # no prazo exato ainda não
        self.assertTrue(calc.atrasada(d, SEG2 + 7 * HORA + 30 * MIN + 1))


class AtencaoUtil(unittest.TestCase):
    def test_espera_e_pausa_so_contam_no_expediente(self):
        sem_aceite = hora({})
        sem_aceite["criado"] = SEXTA + 16 * HORA + 55 * MIN
        agora = SEXTA + 22 * HORA
        self.assertEqual(calc.atencao([sem_aceite], agora, AGENDAS), [])           # 5 min úteis
        self.assertEqual([t["k"] for t in calc.atencao([sem_aceite], agora)[0]["tags"]], ["wait"])   # corrido: 5 h
        tags = calc.atencao([sem_aceite], SEG2 + 7 * HORA + 20 * MIN, AGENDAS)[0]["tags"]
        self.assertEqual([(t["k"], t["min"]) for t in tags], [("wait", 25.0)])      # 5 + 20 min úteis
        pausada = hora({"status": "pause", "iniciado": SEXTA + 16 * HORA, "pausas": [pz(SEXTA + 16 * HORA + 50 * MIN)]})
        self.assertEqual(calc.atencao([pausada], SEG2 + 7 * HORA + 9 * MIN, AGENDAS), [])      # 10 + 9 min
        tags = calc.atencao([pausada], SEG2 + 7 * HORA + 10 * MIN, AGENDAS)[0]["tags"]
        self.assertEqual([(t["k"], t["min"]) for t in tags], [("pause", 20.0)])


class VistaUtil(unittest.TestCase):
    def doc(self, **kw):
        return {"rev": 1, "setores": [], "pessoas": [], "notas": [], "demandas": [], **kw}

    def test_vista_leva_a_agenda_e_so_as_versoes_em_uso(self):
        viva = dem(1, agenda_v=2)
        feita = dem(2, status="done", fim=T0 + MIN, agenda_v=3)
        doc = self.doc(demandas=[viva, feita], agenda={**AGENDA, "v": 4},
                       agendas={"1": AGENDA, "2": {**AGENDA, "v": 2}, "3": {**AGENDA, "v": 3}})
        v = calc.vista(doc, T0)
        self.assertEqual(v["agenda"]["v"], 4)
        self.assertEqual(list(v["agendas"]), ["2"])     # a 1 ninguém usa; a 3 é de demanda fechada
        self.assertEqual(calc.vista(self.doc(), T0)["agenda"], ag.padrao())
        self.assertEqual(calc.vista(self.doc(), T0)["agendas"], {})

    def test_vista_mede_com_as_versoes_do_doc(self):
        d = hora({})
        doc = self.doc(demandas=[d], agendas=AGENDAS)
        out = calc.vista(doc, SEXTA + 18 * HORA)["demandas"][0]
        self.assertEqual(out["total"], 60.0)


class GanttUtil(unittest.TestCase):
    def test_sem_horario_a_saida_nao_muda(self):
        self.assertNotIn("expediente", calc.gantt([dem(1)], T0 + MIN))
        self.assertNotIn("expediente", calc.gantt([dem(1)], T0 + MIN, T0 - HORA, T0 + HORA, "setor"))
        self.assertNotIn("expediente", calc.gantt([dem(1)], T0 + MIN, agenda=ag.padrao()))   # desligada

    def test_expediente_da_janela_de_hoje_e_do_multidia(self):
        agora = SEG2 + 10 * HORA
        g = calc.gantt([], agora, agenda=AGENDA)   # agora-10h a agora+3h: segunda 00:00 a 13:00
        self.assertEqual(g["expediente"]["geral"], [[SEG2 + 7 * HORA, SEG2 + 12 * HORA]])
        self.assertEqual(g["expediente"]["setores"], {})
        m = calc.gantt([], agora, SEG2, SEG2 + 2 * 86400000, "setor", agenda=AGENDA)
        self.assertEqual(len(m["expediente"]["geral"]), 4)
        self.assertEqual(m["grupos"], [])

    def test_setor_com_horario_ou_feriado_proprio_ganha_o_seu(self):
        a = {**AGENDA, "setores": {"SLD": {"dias": [1], "turnos": [["06:00", "08:00"]]}},
             "feriados": [{"data": "2026-11-16", "nome": "x", "setores": ["CNC"]}]}
        g = calc.gantt([], SEG2 + HORA, SEG2, SEG2 + 86400000, agenda=a)["expediente"]
        self.assertEqual(sorted(g["setores"]), ["CNC", "SLD"])
        self.assertEqual(g["setores"]["CNC"], [])                                       # feriado só dele
        self.assertEqual(g["setores"]["SLD"], [[SEG2 + 6 * HORA, SEG2 + 8 * HORA]])
        self.assertEqual(len(g["geral"]), 2)

    def test_crono_leva_horario_ate_o_gantt_e_mede_util(self):
        d = hora({"iniciado": SEG2 + 7 * HORA, "fim": SEG2 + 8 * HORA, "status": "done"})
        c = calc.crono([d], SEG2 + 9 * HORA, 7, AGENDAS, AGENDA)
        self.assertIn("expediente", c["gantt"])
        self.assertEqual(c["kpis"]["espera"], 60.0)     # 1 h de sexta; a noite e o fim de semana não contam
        self.assertEqual(c["kpis"]["execucao"], 60.0)
        corrido = calc.crono([d], SEG2 + 9 * HORA, 7)
        self.assertGreater(corrido["kpis"]["espera"], 60.0 * 60)
        self.assertNotIn("expediente", corrido["gantt"])


if __name__ == "__main__":
    unittest.main()
