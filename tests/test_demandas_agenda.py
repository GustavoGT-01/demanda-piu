"""demandas_agenda: validação do horário de serviço e tempo útil (funções puras; datas pela hora local da máquina)."""

import datetime
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1] / "demandas"
sys.path.insert(0, str(HERE))

import demandas_agenda as ag

MIN = 60000
HORA = 60 * MIN
DIA = 24 * HORA
VETORES = Path(__file__).with_name("vetores_agenda.json")


def ms(a, m, d, h=0, mi=0):
    """Instante local (ms), como a tela e o servidor enxergam o relógio."""
    return int(datetime.datetime(a, m, d, h, mi).timestamp() * 1000)


# 2026-11-09 é segunda-feira
SEG, TER, QUA, QUI, SEX, SAB, DOM = (ms(2026, 11, 9 + i) for i in range(7))
SEG2 = ms(2026, 11, 16)   # a segunda seguinte


def cfg(**kw):
    base = {**ag.padrao(), "ativa": True}
    base.update(kw)
    return base


def grade_padrao(**kw):
    return ag.grade(ag.normaliza(cfg(**kw)), "CNC")


class Padrao(unittest.TestCase):
    def test_desligado_e_comercial(self):
        p = ag.padrao()
        self.assertEqual((p["ativa"], p["v"], p["setores"], p["feriados"]), (False, 0, {}, []))
        self.assertEqual(p["padrao"], {"dias": [1, 2, 3, 4, 5], "turnos": [["07:00", "12:00"], ["13:00", "17:00"]]})
        self.assertIsNot(ag.padrao()["padrao"], ag.padrao()["padrao"])
        self.assertEqual(ag.normaliza(p), p)   # a configuração de fábrica já é válida

    def test_constantes(self):
        self.assertEqual((ag.SOMA_DIAS, ag.MEDE_DIAS, ag.SEMANA_MIN), (400, 3700, 15))
        self.assertEqual(ag.LIM, {"feriados": 400, "turnos": 6, "versoes": 50, "nome": 60})
        self.assertEqual((ag.MIN, ag.DIA_MS), (60000, 86400000))


class Validacao(unittest.TestCase):
    def erro(self, raw, setores=None):
        with self.assertRaises(ValueError) as c:
            ag.normaliza(raw, setores)
        return str(c.exception)

    def test_nao_objeto_e_ativa_booleano(self):
        for raw in (None, [], "x", 5):
            self.assertEqual(self.erro(raw), "Horário inválido.")
        for ativa in (None, 1, "sim"):
            self.assertEqual(self.erro({**ag.padrao(), "ativa": ativa}), "Informe se o horário de serviço está ligado.")

    def test_v_so_inteiro_nao_negativo(self):
        self.assertEqual(ag.normaliza({**ag.padrao(), "v": 7})["v"], 7)
        for v in (-1, "3", True, None, 1.5):
            self.assertEqual(ag.normaliza({**ag.padrao(), "v": v})["v"], 0, v)

    def test_dias(self):
        for dias in (None, "12345", [0], [8], [True], ["1"], [1.5]):
            self.assertEqual(self.erro(cfg(padrao={"dias": dias, "turnos": [["07:00", "08:00"]]})),
                             "Horário padrão: dias da semana inválidos.", dias)
        out = ag.normaliza(cfg(padrao={"dias": [5, 1, 1, 7], "turnos": [["07:00", "08:00"]]}))
        self.assertEqual(out["padrao"]["dias"], [1, 5, 7])   # ordenados, sem repetir

    def test_turnos(self):
        ruins = ["07:00", ["07:00"], ["07:00", "08:00", "09:00"], ["7:00", "08:00"], ["24:00", "08:00"],
                 ["07:60", "08:00"], [7, 8], None]
        for t in ruins:
            self.assertEqual(self.erro(cfg(padrao={"dias": [1], "turnos": [t]})),
                             "Horário padrão: horário do turno inválido (use HH:MM).", t)
        self.assertEqual(self.erro(cfg(padrao={"dias": [1], "turnos": [["07:00", "07:00"]]})),
                         "Horário padrão: o turno não pode começar e terminar na mesma hora.")
        self.assertEqual(self.erro(cfg(padrao={"dias": [1], "turnos": "x"})), "Horário padrão: no máximo 6 turnos.")
        seis = [["0%d:00" % i, "0%d:30" % i] for i in range(1, 7)]
        self.assertEqual(len(ag.normaliza(cfg(padrao={"dias": [1], "turnos": seis}))["padrao"]["turnos"]), 6)
        self.assertEqual(self.erro(cfg(padrao={"dias": [1], "turnos": seis + [["08:00", "09:00"]]})),
                         "Horário padrão: no máximo 6 turnos.")
        self.assertEqual(self.erro(cfg(padrao="x")), "Horário padrão: horário inválido.")

    def test_turnos_ordenados_e_sobreposicao(self):
        out = ag.normaliza(cfg(padrao={"dias": [1], "turnos": [["13:00", "17:00"], ["07:00", "12:00"]]}))
        self.assertEqual(out["padrao"]["turnos"], [["07:00", "12:00"], ["13:00", "17:00"]])
        # encostar não é sobrepor
        ag.normaliza(cfg(padrao={"dias": [1], "turnos": [["06:00", "14:00"], ["14:00", "22:00"]]}))
        sobrepoe = [[["07:00", "12:00"], ["11:59", "13:00"]],
                    [["22:00", "06:00"], ["05:00", "07:00"]],       # a noite invade a manhã seguinte
                    [["22:00", "06:00"], ["06:00", "23:00"], ["23:00", "07:00"]]]
        for ts in sobrepoe:
            self.assertEqual(self.erro(cfg(padrao={"dias": [1, 2, 3, 4, 5, 6, 7], "turnos": ts})),
                             "Horário padrão: dois turnos se sobrepõem.", ts)
        # a semana é circular: a noite de domingo invade a manhã de segunda
        self.assertEqual(self.erro(cfg(padrao={"dias": [7, 1], "turnos": [["22:00", "06:00"], ["05:00", "06:00"]]})),
                         "Horário padrão: dois turnos se sobrepõem.")
        ag.normaliza(cfg(padrao={"dias": [7, 1], "turnos": [["22:00", "06:00"], ["06:00", "07:00"]]}))
        # a mesma noite sem o dia seguinte configurado não sobrepõe nada
        ag.normaliza(cfg(padrao={"dias": [1, 3], "turnos": [["22:00", "06:00"], ["07:00", "08:00"]]}))

    def test_minimo_de_trabalho_por_semana(self):
        ok = cfg(padrao={"dias": [1], "turnos": [["07:00", "07:15"]]})
        self.assertEqual(ag.normaliza(ok)["padrao"]["turnos"], [["07:00", "07:15"]])
        curto = cfg(padrao={"dias": [1], "turnos": [["07:00", "07:14"]]})
        self.assertEqual(self.erro(curto), "Horário padrão: precisa de ao menos 15 minutos de trabalho por semana.")
        self.assertEqual(self.erro(cfg(padrao={"dias": [], "turnos": [["07:00", "12:00"]]})),
                         "Horário padrão: precisa de ao menos 15 minutos de trabalho por semana.")
        self.assertEqual(self.erro(cfg(padrao={"dias": [1], "turnos": []})),
                         "Horário padrão: precisa de ao menos 15 minutos de trabalho por semana.")
        # sete dias de 3 minutos passam de 15: a soma é a da semana
        ag.normaliza(cfg(padrao={"dias": [1, 2, 3, 4, 5, 6, 7], "turnos": [["07:00", "07:03"]]}))
        # desligado, a configuração pode estar vazia (o ADM está montando)
        self.assertFalse(ag.normaliza({**ag.padrao(), "padrao": {"dias": [], "turnos": []}})["ativa"])
        # e a exceção de um setor também precisa de trabalho
        self.assertEqual(self.erro(cfg(setores={"CNC": {"dias": [], "turnos": []}})),
                         "Setor CNC: precisa de ao menos 15 minutos de trabalho por semana.")

    def test_setores(self):
        grade = {"dias": [1, 2], "turnos": [["06:00", "14:00"]]}
        out = ag.normaliza(cfg(setores={"CNC": grade}), {"CNC", "ESP"})
        self.assertEqual(out["setores"], {"CNC": grade})
        self.assertEqual(self.erro(cfg(setores={"ZZ": grade}), {"CNC"}), "Setor inválido no horário por setor.")
        for sid in ("c", "cnc1x", "cnc", 5):
            self.assertEqual(self.erro(cfg(setores={sid: grade})), "Setor inválido no horário por setor.", sid)
        ag.normaliza(cfg(setores={"ZZ": grade}))   # sem a lista de setores não confere
        self.assertEqual(self.erro(cfg(setores=["CNC"])), "Horários por setor inválidos.")
        self.assertEqual(self.erro(cfg(setores={"CNC": 5})), "Setor CNC: horário inválido.")
        self.assertEqual(ag.normaliza(cfg(setores=None))["setores"], {})

    def test_feriados(self):
        f = [{"data": "2026-12-25", "nome": "  Natal ", "setores": ["ESP", "CNC", "CNC"]},
             {"data": "2026-11-15", "nome": "República"}, {"data": "2026-11-15", "nome": "Só CNC", "setores": ["CNC"]}]
        out = ag.normaliza(cfg(feriados=f), {"CNC", "ESP"})["feriados"]
        self.assertEqual(out, [{"data": "2026-11-15", "nome": "República", "setores": []},
                               {"data": "2026-11-15", "nome": "Só CNC", "setores": ["CNC"]},
                               {"data": "2026-12-25", "nome": "Natal", "setores": ["CNC", "ESP"]}])
        for ruim in ({"data": "2026-13-01"}, {"data": "2026-02-30"}, {"data": "25/12/2026"}, {"data": 5}, {}, "x"):
            self.assertIn("feriado", self.erro(cfg(feriados=[ruim])).lower(), ruim)
        self.assertEqual(self.erro(cfg(feriados=[{"data": "2026-02-30"}])), "Data de feriado inválida: 2026-02-30.")
        self.assertEqual(self.erro(cfg(feriados=[{"data": "2026-01-01", "nome": "x" * 61}])),
                         "Nome de feriado com mais de 60 letras.")
        ag.normaliza(cfg(feriados=[{"data": "2026-01-01", "nome": "x" * 60}]))
        self.assertEqual(self.erro(cfg(feriados=[{"data": "2026-01-01", "nome": 7}])),
                         "Nome de feriado com mais de 60 letras.")
        dup = [{"data": "2026-01-01", "setores": ["CNC"]}, {"data": "2026-01-01", "setores": ["CNC"]}]
        self.assertEqual(self.erro(cfg(feriados=dup)), "Feriado repetido em 2026-01-01.")
        for ss in ("CNC", ["zz"], [3]):
            self.assertEqual(self.erro(cfg(feriados=[{"data": "2026-01-01", "setores": ss}])),
                             "Setor inválido no feriado de 2026-01-01.", ss)
        self.assertEqual(self.erro(cfg(feriados=[{"data": "2026-01-01", "setores": ["ZZ"]}]), {"CNC"}),
                         "Setor inválido no feriado de 2026-01-01.")
        self.assertEqual(self.erro(cfg(feriados="x")), "No máximo 400 feriados.")
        muitos = [{"data": (datetime.date(2026, 1, 1) + datetime.timedelta(days=i)).isoformat()} for i in range(401)]
        self.assertEqual(self.erro(cfg(feriados=muitos)), "No máximo 400 feriados.")
        self.assertEqual(len(ag.normaliza(cfg(feriados=muitos[:400]))["feriados"]), 400)
        self.assertEqual(ag.normaliza(cfg(feriados=None))["feriados"], [])

    def test_sem_versao(self):
        a = ag.normaliza({**ag.padrao(), "v": 4})
        self.assertNotIn("v", ag.sem_versao(a))
        self.assertEqual(ag.sem_versao(a), ag.sem_versao({**a, "v": 9}))
        self.assertNotEqual(ag.sem_versao(a), ag.sem_versao({**a, "ativa": True}))
        self.assertEqual(a["v"], 4)   # não mexe no original


class Grade(unittest.TestCase):
    def test_desligada_e_ausente_sao_corridas(self):
        self.assertIsNone(ag.grade(None, "CNC"))
        self.assertIsNone(ag.grade("x", "CNC"))
        self.assertIsNone(ag.grade(ag.padrao(), "CNC"))   # ativa False

    def test_padrao_e_excecao_por_setor(self):
        excecao = {"dias": [6], "turnos": [["06:00", "10:00"]]}
        a = ag.normaliza(cfg(setores={"SLD": excecao}))
        self.assertEqual(ag.grade(a, "CNC")["dias"], frozenset({1, 2, 3, 4, 5}))
        self.assertEqual(ag.grade(a, "SLD")["dias"], frozenset({6}))
        self.assertEqual(ag.grade(a, "SLD")["faixas"], ((360, 600),))
        self.assertEqual(ag.grade(a, None)["dias"], frozenset({1, 2, 3, 4, 5}))

    def test_feriado_geral_e_por_setor(self):
        a = ag.normaliza(cfg(feriados=[{"data": "2026-11-15", "nome": "A"},
                                       {"data": "2026-11-20", "nome": "B", "setores": ["CNC"]}]))
        self.assertEqual(ag.grade(a, "CNC")["fer"], frozenset({"2026-11-15", "2026-11-20"}))
        self.assertEqual(ag.grade(a, "ESP")["fer"], frozenset({"2026-11-15"}))

    def test_faixa_que_cruza_a_meia_noite(self):
        a = ag.normaliza(cfg(padrao={"dias": [1], "turnos": [["22:00", "06:00"]]}))
        self.assertEqual(ag.grade(a, "CNC")["faixas"], ((1320, 1800),))


class UtilEntre(unittest.TestCase):
    def test_corrido_sem_grade(self):
        self.assertEqual(ag.util_entre(None, 100, 400), 300)
        self.assertEqual(ag.util_entre(None, 400, 100), 0)
        self.assertEqual(ag.util_entre(None, 100, 100), 0)

    def test_dentro_do_turno_e_pelo_almoco(self):
        g = grade_padrao()
        self.assertEqual(ag.util_entre(g, SEG + 8 * HORA, SEG + 9 * HORA), HORA)
        self.assertEqual(ag.util_entre(g, SEG + 11 * HORA, SEG + 14 * HORA), 2 * HORA)   # 11-12 e 13-14
        self.assertEqual(ag.util_entre(g, SEG, TER), 9 * HORA)   # o dia inteiro: 5 h + 4 h
        self.assertEqual(ag.util_entre(g, SEG + 12 * HORA, SEG + 13 * HORA), 0)           # almoço

    def test_fim_de_semana_e_borda_exata(self):
        g = grade_padrao()
        self.assertEqual(ag.util_entre(g, SAB, SAB + DIA), 0)
        self.assertEqual(ag.util_entre(g, SEX + 16 * HORA, SEG2 + 8 * HORA), 2 * HORA)    # 16-17 e 7-8
        self.assertEqual(ag.util_entre(g, SEG + 7 * HORA, SEG + 7 * HORA + 1), 1)
        self.assertEqual(ag.util_entre(g, SEG + 7 * HORA - 1, SEG + 7 * HORA), 0)
        self.assertEqual(ag.util_entre(g, SEG + 17 * HORA, SEG + 17 * HORA + 1), 0)
        self.assertEqual(ag.util_entre(g, SEG, SEG + 7 * 24 * HORA), 45 * HORA)           # uma semana: 5 x 9 h

    def test_feriado_pula_o_dia(self):
        g = ag.grade(ag.normaliza(cfg(feriados=[{"data": "2026-11-10", "nome": "x"}])), "CNC")
        self.assertEqual(ag.util_entre(g, SEG, QUA), 9 * HORA)   # terça não conta
        self.assertEqual(ag.util_entre(grade_padrao(), SEG, QUA), 18 * HORA)

    def test_turno_da_noite_atravessa_a_meia_noite(self):
        g = ag.grade(ag.normaliza(cfg(padrao={"dias": [1, 2, 3, 4, 5], "turnos": [["22:00", "06:00"]]})), "CNC")
        self.assertEqual(ag.util_entre(g, TER, TER + 12 * HORA), 6 * HORA)       # vem do turno de segunda
        self.assertEqual(ag.util_entre(g, SEG, SEG + 12 * HORA), 0)              # domingo à noite não trabalha
        self.assertEqual(ag.util_entre(g, SEX + 20 * HORA, SAB + 12 * HORA), 8 * HORA)   # sexta 22 até sábado 6
        self.assertEqual(ag.util_entre(g, SAB + 6 * HORA, SEG2 + 12 * HORA), 0)   # o fim de semana todo
        self.assertEqual(ag.util_entre(g, SEG + 23 * HORA, TER + 1 * HORA), 2 * HORA)

    def test_feriado_vale_para_o_dia_em_que_o_turno_comeca(self):
        g = ag.grade(ag.normaliza(cfg(padrao={"dias": [1, 2, 3, 4, 5], "turnos": [["22:00", "06:00"]]},
                                      feriados=[{"data": "2026-11-09", "nome": "x"}])), "CNC")
        # segunda é feriado: a noite de segunda (e a manhã de terça que vem dela) some; a de terça fica inteira
        self.assertEqual(ag.util_entre(g, SEG, QUA + 12 * HORA), 8 * HORA)

    def test_teto_do_percurso_nao_prende(self):
        g = grade_padrao()
        grande = ag.util_entre(g, SEG, SEG + 10 ** 13)   # ~316 anos: mede só os 3700 dias de teto
        self.assertTrue(0 < grande < 3700 * 9 * HORA)

    def test_varios_turnos_no_dia(self):
        g = ag.grade(ag.normaliza(cfg(padrao={"dias": [1], "turnos": [["06:00", "14:00"], ["14:00", "22:00"]]})), "CNC")
        self.assertEqual(ag.util_entre(g, SEG, TER), 16 * HORA)


class SomaUtil(unittest.TestCase):
    def test_corrido_sem_grade(self):
        self.assertEqual(ag.soma_util(None, 1000, 2), 1000 + 2 * MIN)
        self.assertEqual(ag.soma_util(None, 1000, 0), 1000)
        self.assertEqual(ag.soma_util(grade_padrao(), 1000, 0), 1000)

    def test_dentro_do_turno(self):
        g = grade_padrao()
        self.assertEqual(ag.soma_util(g, SEG + 8 * HORA, 30), SEG + 8 * HORA + 30 * MIN)
        self.assertEqual(ag.soma_util(g, SEG + 16 * HORA + 30 * MIN, 30), SEG + 17 * HORA)   # termina exatamente no fecho

    def test_sexta_1630_mais_60_cai_na_segunda_0730(self):
        self.assertEqual(ag.soma_util(grade_padrao(), SEX + 16 * HORA + 30 * MIN, 60), SEG2 + 7 * HORA + 30 * MIN)

    def test_fora_do_expediente_conta_da_proxima_abertura(self):
        g = grade_padrao()
        self.assertEqual(ag.soma_util(g, SEX + 20 * HORA, 60), SEG2 + 8 * HORA)          # sexta à noite
        self.assertEqual(ag.soma_util(g, SEG + 12 * HORA + 30 * MIN, 30), SEG + 13 * HORA + 30 * MIN)   # no almoço
        self.assertEqual(ag.soma_util(g, SAB + 10 * HORA, 1), SEG2 + 7 * HORA + MIN)

    def test_atravessa_o_almoco_e_varios_dias(self):
        g = grade_padrao()
        self.assertEqual(ag.soma_util(g, SEG + 11 * HORA, 120), SEG + 14 * HORA)         # 11-12 e 13-14
        self.assertEqual(ag.soma_util(g, SEG + 7 * HORA, 9 * 60), SEG + 17 * HORA)        # um dia útil inteiro: 9 h
        self.assertEqual(ag.soma_util(g, SEG + 7 * HORA, 10 * 60), TER + 8 * HORA)

    def test_feriado_na_segunda(self):
        g = ag.grade(ag.normaliza(cfg(feriados=[{"data": "2026-11-16", "nome": "x"}])), "CNC")
        self.assertEqual(ag.soma_util(g, SEX + 16 * HORA + 30 * MIN, 60), ms(2026, 11, 17, 7, 30))

    def test_turno_da_noite(self):
        g = ag.grade(ag.normaliza(cfg(padrao={"dias": [1, 2, 3, 4, 5], "turnos": [["22:00", "06:00"]]})), "CNC")
        self.assertEqual(ag.soma_util(g, SEG + 20 * HORA, 4 * 60), TER + 2 * HORA)       # 22h-24h e 0h-2h
        self.assertEqual(ag.soma_util(g, SEX + 23 * HORA, 3 * 60), SAB + 2 * HORA)       # entra pelo sábado: ainda é turno de sexta

    def test_soma_e_medida_andam_juntas(self):
        g = grade_padrao()
        for inicio in (SEG + 5 * HORA, SEG + 12 * HORA + 30 * MIN, SEX + 16 * HORA + 59 * MIN, SAB + 3 * HORA):
            for minutos in (1, 30, 59, 60, 541, 3000):
                fim = ag.soma_util(g, inicio, minutos)
                self.assertEqual(ag.util_entre(g, inicio, fim), minutos * MIN, (inicio, minutos))

    def test_sem_trabalho_em_400_dias(self):
        # a única segunda-feira trabalhada do ano é feriado em todas: a agenda nunca completa
        fer = [{"data": (datetime.date(2026, 11, 9) + datetime.timedelta(days=7 * i)).isoformat(), "nome": "x"}
               for i in range(60)]
        g = ag.grade(ag.normaliza(cfg(padrao={"dias": [1], "turnos": [["07:00", "08:00"]]}, feriados=fer)), "CNC")
        with self.assertRaises(ValueError) as c:
            ag.soma_util(g, SEG, 30)
        self.assertEqual(str(c.exception), "O horário de serviço não tem trabalho suficiente em 400 dias.")

    def test_acha_perto_do_limite_de_400_dias(self):
        g = ag.grade(ag.normaliza(cfg(padrao={"dias": [1, 2, 3, 4, 5, 6, 7], "turnos": [["07:00", "08:00"]]})), "CNC")
        # 399 dias de uma hora e mais 30 min: cabe dentro de 400 dias
        achou = ag.soma_util(g, SEG, 399 * 60 + 30)
        self.assertEqual(achou, ms(2027, 12, 13, 7, 30))
        self.assertEqual(ag.util_entre(g, SEG, achou), (399 * 60 + 30) * MIN)


class Expediente(unittest.TestCase):
    def test_sem_grade_e_tudo(self):
        self.assertEqual(ag.expediente(None, 10, 50), [[10, 50]])
        self.assertEqual(ag.expediente(None, 50, 50), [])
        self.assertEqual(ag.expediente(None, 60, 50), [])

    def test_recorta_na_janela(self):
        g = grade_padrao()
        self.assertEqual(ag.expediente(g, SEG + 8 * HORA, SEG + 15 * HORA),
                         [[SEG + 8 * HORA, SEG + 12 * HORA], [SEG + 13 * HORA, SEG + 15 * HORA]])
        self.assertEqual(ag.expediente(g, SAB, DOM), [])
        self.assertEqual(ag.expediente(g, SEG + 12 * HORA, SEG + 13 * HORA), [])

    def test_une_turnos_que_se_encostam(self):
        g = ag.grade(ag.normaliza(cfg(padrao={"dias": [1], "turnos": [["06:00", "14:00"], ["14:00", "22:00"]]})), "CNC")
        self.assertEqual(ag.expediente(g, SEG, TER), [[SEG + 6 * HORA, SEG + 22 * HORA]])

    def test_noite_que_vira_o_dia_aparece_na_janela_seguinte(self):
        g = ag.grade(ag.normaliza(cfg(padrao={"dias": [1], "turnos": [["22:00", "06:00"]]})), "CNC")
        self.assertEqual(ag.expediente(g, TER, TER + 12 * HORA), [[TER, TER + 6 * HORA]])

    def test_semana_confere_com_a_medida(self):
        g = grade_padrao()
        blocos = ag.expediente(g, SEG, SEG + 7 * DIA)
        self.assertEqual(sum(b - a for a, b in blocos), ag.util_entre(g, SEG, SEG + 7 * DIA))
        self.assertEqual(len(blocos), 10)   # 2 por dia útil


class Aberto(unittest.TestCase):
    def test_aberto(self):
        g = grade_padrao()
        self.assertTrue(ag.aberto(None, SAB))
        self.assertTrue(ag.aberto(g, SEG + 7 * HORA))                 # a abertura conta
        self.assertFalse(ag.aberto(g, SEG + 7 * HORA - 1))
        self.assertTrue(ag.aberto(g, SEG + 12 * HORA - 1))
        self.assertFalse(ag.aberto(g, SEG + 12 * HORA))               # o fecho não
        self.assertFalse(ag.aberto(g, SEG + 12 * HORA + 30 * MIN))    # almoço
        self.assertFalse(ag.aberto(g, SAB + 10 * HORA))
        gn = ag.grade(ag.normaliza(cfg(padrao={"dias": [1], "turnos": [["22:00", "06:00"]]})), "CNC")
        self.assertTrue(ag.aberto(gn, TER + 3 * HORA))


class Vetores(unittest.TestCase):
    """Os mesmos casos rodam na tela (jsdom) contra a porta em JavaScript: os dois lados têm de concordar."""

    def test_vetores_compartilhados(self):
        dados = json.loads(VETORES.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(dados["casos"]), 12)
        for c in dados["casos"]:
            a = ag.normaliza(dados["agendas"][c["agenda"]])
            g = ag.grade(a, c["setor"])
            ini, fim = ms(*c["de"]), ms(*c["ate"]) if "ate" in c else None
            if c["op"] == "util":
                self.assertEqual(ag.util_entre(g, ini, fim) // MIN, c["min"], c["nome"])
            else:
                self.assertEqual(ag.soma_util(g, ini, c["min"]), ms(*c["resp"]), c["nome"])


if __name__ == "__main__":
    unittest.main()
