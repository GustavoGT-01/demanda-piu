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


if __name__ == "__main__":
    unittest.main()
