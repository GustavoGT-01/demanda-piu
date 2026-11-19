"""QA das regras de tempo e do horário de serviço (sessão E da bateria de testes).

Cobre o que `test_demandas_calc.py`, `test_demandas_agenda.py` e a classe `Horario` de `test_demandas_api.py` não
cobrem: o limite exato (1 ms antes, no ponto, 1 ms depois) de cada regra, propriedades com semente fixa
(soma↔medida, monotonia, aditividade), turno noturno e feriado, versões da agenda com demanda em andamento, estender,
tick, expediente do crono, horário de verão simulado (TZ trocada num subprocesso) e os vetores de paridade JS×Python
(`tests/vetores_qa.json`, conferidos no jsdom por `tests/check_tempo.js`).

Cada teste leva o código da regra na primeira linha da docstring (ex.: "[T01]"): é a chave da matriz em
`docs/qa/tempo.md`. Os testes marcados com `expectedFailure` expõem bug confirmado (ver "Bugs encontrados" lá):
quando o bug for corrigido o teste passa de "falha esperada" para "sucesso inesperado" e deve perder a marca.

Regerar os vetores (só quando a regra de tempo muda de propósito): `QA_GERAR_VETORES=1 py -3 -m unittest
tests.test_qa_tempo.Vetores`.
"""

import datetime
import importlib.util
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parents[1]
HERE = RAIZ / "demandas"
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(HERE))

import demandas_agenda as ag
import demandas_calc as calc
import demandas_store as ds

_spec = importlib.util.spec_from_file_location("demandas_api_qa_tempo", HERE / "api.py")
api = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(api)
ITER_REAL = api.ITER

MIN = 60000
HORA = 60 * MIN
DIA = 24 * HORA
VETORES = Path(__file__).with_name("vetores_qa.json")
SEMENTE = 20261117


def ms(a, m, d, h=0, mi=0, s=0, milis=0):
    """Instante local (ms), como a tela e o servidor enxergam o relógio."""
    return int(datetime.datetime(a, m, d, h, mi, s, milis * 1000).timestamp() * 1000)


# 2026-11-09 é segunda-feira
SEG, TER, QUA, QUI, SEX, SAB, DOM = (ms(2026, 11, 9 + i) for i in range(7))
SEG2 = ms(2026, 11, 16)
TER2 = SEG2 + DIA
SEX2 = ms(2026, 11, 20)


def cfg(**kw):
    base = {**ag.padrao(), "ativa": True, "v": 1}
    base.update(kw)
    return ag.normaliza(base)


def grade(setor="CNC", **kw):
    return ag.grade(cfg(**kw), setor)


COMERCIAL = {"dias": [1, 2, 3, 4, 5], "turnos": [["07:00", "12:00"], ["13:00", "17:00"]]}
NOITE = {"dias": [1, 2, 3, 4, 5], "turnos": [["22:00", "06:00"]]}
AGENDAS = {"1": cfg()}


def dem(**kw):
    d = {"id": "SOL-1001", "titulo": "Cortar chapas", "tipo": "dem", "motivo": "Outro", "prio": "norm", "est": 60,
         "de": {"s": "PCP", "p": None}, "para": {"s": "CNC", "p": None}, "status": "new",
         "criado": SEX + 16 * HORA + 30 * MIN, "iniciado": None, "fim": None, "pausas": [], "atraso_avisado": False,
         "agenda_v": 1, "prazo_em": SEG2 + 7 * HORA + 30 * MIN}
    d.update(kw)
    return d


def pz(ini, fim=None):
    return {"ini": ini, "fim": fim, "motivo": "Máquina parada", "obs": "", "por": "Carlos"}


# ---------------------------------------------------------------------------------------------------------------
# Limites de atraso, prazo e SLA
# ---------------------------------------------------------------------------------------------------------------

class LimitesDeAtraso(unittest.TestCase):
    def test_T01_atrasada_no_prazo_exato_nao_e_atrasada(self):
        """[T01] ativa: prazo-1 e prazo exato não atrasam; prazo+1 ms atrasa; fechada nunca."""
        p = SEG2 + 7 * HORA + 30 * MIN
        for st in ("new", "prog", "pause"):
            d = dem(status=st, prazo_em=p)
            self.assertFalse(calc.atrasada(d, p - 1), st)
            self.assertFalse(calc.atrasada(d, p), st)
            self.assertTrue(calc.atrasada(d, p + 1), st)
            self.assertTrue(calc.atrasada(d, p + 10 * DIA), st)
            self.assertFalse(calc.metricas(d, p, AGENDAS)["atrasada"])
            self.assertTrue(calc.metricas(d, p + 1, AGENDAS)["atrasada"])
        for st in ("done", "canc"):
            self.assertFalse(calc.atrasada(dem(status=st, prazo_em=p), p + 10 * DIA), st)

    def test_T02_atrasou_concluida_no_prazo_exato_nao_atrasou(self):
        """[T02] concluída: fim == prazo no prazo; fim == prazo+1 ms atrasou; cancelada e sem fim nunca."""
        p = SEG2 + 7 * HORA + 30 * MIN
        self.assertFalse(calc.atrasou_concluida(dem(status="done", fim=p - 1)))
        self.assertFalse(calc.atrasou_concluida(dem(status="done", fim=p)))
        self.assertTrue(calc.atrasou_concluida(dem(status="done", fim=p + 1)))
        self.assertFalse(calc.atrasou_concluida(dem(status="canc", fim=p + DIA)))
        self.assertFalse(calc.atrasou_concluida(dem(status="done", fim=None)))
        self.assertFalse(calc.atrasou_concluida(dem(status="prog", fim=p + DIA)))

    def test_T03_prazo_gravado_vence_o_corrido_e_o_valor_ruim_cai_no_corrido(self):
        """[T03] prazo_em inteiro vale (inclusive 0); bool, float, texto e None caem em criado + est·60000."""
        d = dem(criado=1000, est=2)
        self.assertEqual(calc.prazo(dict(d, prazo_em=5)), 5)
        self.assertEqual(calc.prazo(dict(d, prazo_em=0)), 0)
        for ruim in (True, False, None, "5", 5.5):
            self.assertEqual(calc.prazo(dict(d, prazo_em=ruim)), 1000 + 2 * MIN, ruim)
        sem = dem(criado=1000, est=2)
        del sem["prazo_em"]
        self.assertEqual(calc.prazo(sem), 1000 + 2 * MIN)

    def test_T04_sla_em_tempo_util_chega_a_100_no_prazo_exato(self):
        """[T04] criada sex 16:30 com est 60: no prazo (seg 07:30) o SLA é 100,0 e não está atrasada; 1 ms depois atrasa."""
        d = dem()
        p = d["prazo_em"]
        self.assertEqual(calc.metricas(d, p - 30 * MIN, AGENDAS)["sla"], 50.0)   # seg 07:00: 30 min úteis
        m = calc.metricas(d, p, AGENDAS)
        self.assertEqual((m["total"], m["sla"], m["atrasada"]), (60.0, 100.0, False))
        m = calc.metricas(d, p + 1, AGENDAS)
        self.assertEqual((m["total"], m["sla"], m["atrasada"]), (60.0, 100.0, True))
        self.assertEqual(calc.metricas(d, p + HORA, AGENDAS)["sla"], 200.0)       # além: 120 min úteis
        # fim de semana inteiro não anda o SLA
        self.assertEqual(calc.metricas(d, SAB + 12 * HORA, AGENDAS)["sla"], 50.0)
        self.assertEqual(calc.metricas(d, DOM + 23 * HORA, AGENDAS)["sla"], 50.0)

    def test_T04b_sla_sem_estimativa_e_none(self):
        """[T04] est <= 0 não divide: sla None."""
        self.assertIsNone(calc.metricas(dem(est=0), SEG2, AGENDAS)["sla"])
        self.assertIsNone(calc.metricas(dem(est=-5), SEG2, AGENDAS)["sla"])

    def test_T05_atraso_util_da_concluida(self):
        """[T05] atraso (min úteis): fim == prazo → 0; 1 min depois → 1; vem do congelado; sem `util` recalcula."""
        p = SEG2 + 7 * HORA + 30 * MIN
        for fim, esperado in ((p, 0.0), (p + MIN, 1.0), (p + 90 * MIN, 90.0), (p + 5 * HORA, 270.0)):
            d = dem(status="done", iniciado=SEG2 + 7 * HORA, fim=fim)   # p+5h cai no almoço (12:30): 07:30-12:00 = 270 min
            calc.congela(d, fim, AGENDAS)
            self.assertEqual(d["util"]["atraso"], int(esperado * MIN), fim)
            self.assertEqual(calc.metricas(d, fim + DIA, None)["atraso"], esperado, fim)   # sem agendas: o gravado
        antiga = dem(status="done", iniciado=SEG2 + 7 * HORA, fim=p + 90 * MIN)   # fechada sem `util`
        self.assertEqual(calc.metricas(antiga, p + DIA, AGENDAS)["atraso"], 90.0)
        self.assertNotIn("atraso", calc.metricas(dem(status="prog"), p + DIA, AGENDAS))   # só concluída leva atraso
        sem_agenda = dem(status="done", fim=p + 90 * MIN)
        sem_agenda.pop("agenda_v")
        self.assertNotIn("atraso", calc.metricas(sem_agenda, p + DIA, AGENDAS))


# ---------------------------------------------------------------------------------------------------------------
# Espera, execução, pausa e total
# ---------------------------------------------------------------------------------------------------------------

class Duracoes(unittest.TestCase):
    def setUp(self):
        self.g = grade()

    def test_T10_fronteira_de_turno_abertura_conta_fecho_nao(self):
        """[T10] cada borda do comercial (07, 12, 13, 17): 1 ms dentro conta, 1 ms fora não."""
        for borda, abre in ((7, True), (12, False), (13, True), (17, False)):
            b = SEG + borda * HORA
            antes, depois = ag.util_entre(self.g, b - 1, b), ag.util_entre(self.g, b, b + 1)
            self.assertEqual((antes, depois), (0, 1) if abre else (1, 0), borda)
            self.assertEqual(ag.aberto(self.g, b), abre, borda)
            self.assertEqual(ag.aberto(self.g, b - 1), not abre, borda)

    def test_T10b_espera_criada_no_fecho_ou_na_abertura(self):
        """[T10] criada no fecho (sex 17:00) → 0 até a abertura de seg 07:00; 1 ms depois → 1 ms; criada na abertura conta."""
        d = dem(criado=SEX + 17 * HORA, status="prog", iniciado=SEG2 + 7 * HORA)
        self.assertEqual(calc.espera_ms(d, SEG2 + DIA, AGENDAS), 0)
        d["iniciado"] = SEG2 + 7 * HORA + 1
        self.assertEqual(calc.espera_ms(d, SEG2 + DIA, AGENDAS), 1)
        d = dem(criado=SEG2 + 7 * HORA, status="prog", iniciado=SEG2 + 7 * HORA + 1)
        self.assertEqual(calc.espera_ms(d, SEG2 + DIA, AGENDAS), 1)
        d = dem(criado=SEG2 + 12 * HORA - 1, status="prog", iniciado=SEG2 + 13 * HORA + 1)   # 1 ms antes do almoço + 1 ms depois
        self.assertEqual(calc.espera_ms(d, SEG2 + DIA, AGENDAS), 2)

    def test_T11_espera_sem_inicio_usa_fim_e_depois_agora(self):
        """[T11] sem `iniciado`: espera vai até o fim (fechada) ou até agora (ativa)."""
        d = dem(criado=SEG2 + 8 * HORA)
        self.assertEqual(calc.espera_ms(d, SEG2 + 9 * HORA, AGENDAS), HORA)
        self.assertEqual(calc.espera_ms(d, SEG2 + 12 * HORA + 30 * MIN, AGENDAS), 4 * HORA)   # almoço não conta
        d = dem(criado=SEG2 + 8 * HORA, status="canc", fim=SEG2 + 10 * HORA)
        self.assertEqual(calc.espera_ms(d, SEG2 + 99 * HORA, AGENDAS), 2 * HORA)
        self.assertEqual(calc.execucao_ms(d, SEG2 + 99 * HORA, AGENDAS), 0)

    def test_T12_pausa_que_atravessa_a_noite_e_o_fim_de_semana(self):
        """[T12] pausa sex 16:00 → seg 08:00 conta só 16-17 e 07-08: 2 h; a execução desconta só isso."""
        d = dem(status="done", criado=SEX + 8 * HORA, iniciado=SEX + 8 * HORA, fim=SEG2 + 10 * HORA,
                pausas=[pz(SEX + 16 * HORA, SEG2 + 8 * HORA)])
        self.assertEqual(calc.pausado_ms(d, SEG2 + 99 * HORA, AGENDAS), 2 * HORA)
        self.assertEqual(calc.execucao_ms(d, SEG2 + 99 * HORA, AGENDAS), 9 * HORA)   # 8+3 de trabalho − 2 de pausa
        self.assertEqual(calc.total_ms(d, SEG2 + 99 * HORA, AGENDAS), 11 * HORA)
        self.assertEqual(calc.espera_ms(d, SEG2 + 99 * HORA, AGENDAS), 0)
        # a noite de quarta para quinta (sem trabalho) dentro de uma pausa: nada
        n = dem(status="pause", criado=QUA + 8 * HORA, iniciado=QUA + 8 * HORA, pausas=[pz(QUA + 17 * HORA)])
        self.assertEqual(calc.pausado_ms(n, QUI + 7 * HORA, AGENDAS), 0)             # abre às 07:00: ainda 0
        self.assertEqual(calc.pausado_ms(n, QUI + 7 * HORA + 1, AGENDAS), 1)         # 1 ms depois da abertura: 1 ms

    def test_T13_pausa_aberta_vai_ate_agora_ou_ate_o_fim(self):
        """[T13] pausa aberta: ativa conta até agora (em horas úteis); demanda fechada, até o fim dela."""
        d = dem(status="pause", criado=SEX + 8 * HORA, iniciado=SEX + 8 * HORA, pausas=[pz(SEX + 16 * HORA)])
        self.assertEqual(calc.pausado_ms(d, SEG2 + 7 * HORA + 30 * MIN, AGENDAS), 90 * MIN)
        self.assertEqual(calc.pausado_ms(d, SAB + 3 * HORA, AGENDAS), HORA)          # sábado: só a sexta 16-17
        fechada = dem(status="done", criado=SEX + 8 * HORA, iniciado=SEX + 8 * HORA, fim=SEG2 + 9 * HORA,
                      pausas=[pz(SEX + 16 * HORA)])
        self.assertEqual(calc.pausado_ms(fechada, SEG2 + 99 * HORA, AGENDAS), 3 * HORA)   # 16-17 e 07-09
        self.assertEqual(calc.pausado_ms(fechada, SEG2 + 9 * HORA, AGENDAS), 3 * HORA)    # o "agora" não importa

    def test_T14_pausa_de_antes_da_reatribuicao_nao_desconta_a_nova_execucao(self):
        """[T14] pausa seg 09-10, reatribuída (volta a `new`, sem início), reaceita 14:00 e conclui 16:00."""
        d = dem(status="done", criado=SEG2 + 8 * HORA, iniciado=SEG2 + 14 * HORA, fim=SEG2 + 16 * HORA,
                pausas=[pz(SEG2 + 9 * HORA, SEG2 + 10 * HORA)])
        self.assertEqual(calc.execucao_ms(d, SEG2 + DIA, AGENDAS), 2 * HORA)   # a pausa de antes fica fora do trecho
        self.assertEqual(calc.pausado_ms(d, SEG2 + DIA, AGENDAS), HORA)        # mas segue contada como pausa
        reaberta = dem(status="new", criado=SEG2 + 8 * HORA, iniciado=None, pausas=[pz(SEG2 + 9 * HORA, SEG2 + 10 * HORA)])
        self.assertEqual(calc.execucao_ms(reaberta, SEG2 + 11 * HORA, AGENDAS), 0)
        # pausa que atravessa o novo início (dado inconsistente): só o que cai depois do início desconta
        d2 = dem(status="done", criado=SEG2 + 8 * HORA, iniciado=SEG2 + 14 * HORA, fim=SEG2 + 16 * HORA,
                 pausas=[pz(SEG2 + 13 * HORA, SEG2 + 15 * HORA)])
        self.assertEqual(calc.execucao_ms(d2, SEG2 + DIA, AGENDAS), HORA)

    def test_T15_pausa_inteira_fora_do_expediente_vale_zero(self):
        """[T15] pausa só na madrugada, no almoço ou no domingo: 0; no limite 1 ms dentro do turno: 1 ms."""
        base = dict(status="prog", criado=SEG2 + 8 * HORA, iniciado=SEG2 + 8 * HORA)
        for ini, fim in ((SEG2 + 12 * HORA, SEG2 + 13 * HORA), (DOM + 2 * HORA, DOM + 20 * HORA), (SEG2 + 17 * HORA, TER2 + 7 * HORA)):
            self.assertEqual(calc.pausado_ms(dem(pausas=[pz(ini, fim)], **base), TER2 + DIA, AGENDAS), 0, (ini, fim))
        self.assertEqual(calc.pausado_ms(dem(pausas=[pz(SEG2 + 12 * HORA, SEG2 + 13 * HORA + 1)], **base), TER2, AGENDAS), 1)

    def test_T16_espera_mais_execucao_mais_pausa_fecha_o_total(self):
        """[T16] propriedade (semente fixa): com pausas dentro do trecho, espera+execução+pausado == total."""
        rng = random.Random(SEMENTE)
        for _ in range(300):
            g = gerar_grade(rng)
            agendas = {"1": g["agenda"]}
            criado = SEG + rng.randrange(0, 5 * DIA, MIN)
            ini = criado + rng.randrange(0, 2 * DIA, MIN)
            fim = ini + rng.randrange(0, 4 * DIA, MIN)
            pausas, cur = [], ini
            for _ in range(rng.randrange(0, 4)):
                a = cur + rng.randrange(0, max(MIN, (fim - cur) // 2), MIN) if fim - cur > 2 * MIN else cur
                b = a + rng.randrange(0, max(MIN, (fim - a) // 2), MIN) if fim - a > 2 * MIN else a
                if b > a:
                    pausas.append(pz(a, b))
                cur = b
            d = dem(status="done", criado=criado, iniciado=ini, fim=fim, pausas=pausas, para={"s": g["setor"], "p": None})
            t = fim + DIA
            soma = calc.espera_ms(d, t, agendas) + calc.execucao_ms(d, t, agendas) + calc.pausado_ms(d, t, agendas)
            self.assertEqual(soma, calc.total_ms(d, t, agendas), (g["agenda"], criado, ini, fim, pausas))

    def test_T17_congela_grava_na_fechada_e_vale_sem_agenda(self):
        """[T17] concluída/cancelada guardam `util`; depois valem sem agenda; ativa ignora `util`; recongelar mede de novo."""
        for st in ("done", "canc"):
            d = dem(status=st, criado=SEX + 16 * HORA, iniciado=SEX + 16 * HORA + 30 * MIN, fim=SEG2 + 9 * HORA,
                    pausas=[pz(SEX + 16 * HORA + 40 * MIN, SEG2 + 8 * HORA)])
            calc.congela(d, d["fim"], AGENDAS)
            u = d["util"]
            self.assertEqual(set(u), {"espera", "execucao", "pausado", "total", "atraso"})
            self.assertEqual(u["total"], u["espera"] + u["execucao"] + u["pausado"], st)
            for nome, chave in (("espera_ms", "espera"), ("execucao_ms", "execucao"), ("pausado_ms", "pausado"), ("total_ms", "total")):
                self.assertEqual(getattr(calc, nome)(d, SEG2 + 99 * DIA), u[chave], (st, nome))   # sem agendas: o gravado
            u1 = dict(u)
            d["util"] = {"espera": 1, "execucao": 1, "pausado": 1, "total": 1, "atraso": 1}      # valor velho
            calc.congela(d, d["fim"], AGENDAS)
            self.assertEqual(d["util"], u1, st)
        ativa = dem(status="prog", criado=SEG2 + 8 * HORA, iniciado=SEG2 + 8 * HORA,
                    util={"espera": 7, "execucao": 7, "pausado": 7, "total": 7, "atraso": 7})
        self.assertEqual(calc.total_ms(ativa, SEG2 + 9 * HORA, AGENDAS), HORA)   # o util de uma ativa é lixo: não vale
        sem = dem(status="done", fim=SEG2 + 9 * HORA)
        sem.pop("agenda_v")
        calc.congela(sem, SEG2 + 9 * HORA, AGENDAS)
        self.assertNotIn("util", sem)


# ---------------------------------------------------------------------------------------------------------------
# Atenção (Python) — a tela real usa a do JS, mas a regra é a mesma
# ---------------------------------------------------------------------------------------------------------------

class Atencao(unittest.TestCase):
    def tags(self, d, agora, agendas=AGENDAS):
        a = calc.atencao([d], agora, agendas)
        return {t["k"]: t["min"] for t in a[0]["tags"]} if a else {}

    def test_T60_sem_aceite_25_minutos_uteis_no_ponto_exato(self):
        """[T60] new: 24:59,999 não marca; 25:00 marca "wait" com 25,0 min; em tempo útil (cruza o fim de semana)."""
        d = dem(criado=SEG2 + 9 * HORA, prazo_em=SEG2 + 99 * HORA)
        self.assertEqual(self.tags(d, SEG2 + 9 * HORA + 25 * MIN - 1), {})
        self.assertEqual(self.tags(d, SEG2 + 9 * HORA + 25 * MIN), {"wait": 25.0})
        self.assertEqual(self.tags(d, SEG2 + 9 * HORA + 26 * MIN), {"wait": 26.0})
        fim_de_semana = dem(criado=SEX + 16 * HORA + 50 * MIN, prazo_em=SEG2 + 99 * HORA)   # 10 min na sexta
        self.assertEqual(self.tags(fim_de_semana, SEG2 + 7 * HORA + 15 * MIN - 1), {})
        self.assertEqual(self.tags(fim_de_semana, SEG2 + 7 * HORA + 15 * MIN), {"wait": 25.0})
        self.assertEqual(self.tags(fim_de_semana, DOM + 10 * HORA), {})                        # domingo: só 10 min úteis

    def test_T60b_sem_aceite_so_vale_para_aberta(self):
        """[T60] a espera longa não marca demanda em andamento ou pausada (sem pausa aberta)."""
        for st in ("prog", "pause"):
            d = dem(status=st, criado=SEG2 + 8 * HORA, iniciado=SEG2 + 8 * HORA + MIN, prazo_em=SEG2 + 99 * HORA)
            self.assertEqual(self.tags(d, SEG2 + 11 * HORA), {}, st)

    def test_T61_pausada_20_minutos_uteis_no_ponto_exato(self):
        """[T61] pausa aberta: 19:59,999 não marca; 20:00 marca "pause" com 20,0 min; cruza a noite em tempo útil."""
        d = dem(status="pause", criado=SEG2 + 8 * HORA, iniciado=SEG2 + 8 * HORA, pausas=[pz(SEG2 + 10 * HORA)],
                prazo_em=SEG2 + 99 * HORA)
        self.assertEqual(self.tags(d, SEG2 + 10 * HORA + 20 * MIN - 1), {})
        self.assertEqual(self.tags(d, SEG2 + 10 * HORA + 20 * MIN), {"pause": 20.0})
        noite = dem(status="pause", criado=SEX + 8 * HORA, iniciado=SEX + 8 * HORA, pausas=[pz(SEX + 16 * HORA + 50 * MIN)],
                    prazo_em=SEG2 + 99 * HORA)
        self.assertEqual(self.tags(noite, SEG2 + 7 * HORA + 10 * MIN - 1), {})
        self.assertEqual(self.tags(noite, SEG2 + 7 * HORA + 10 * MIN), {"pause": 20.0})
        fechada = dem(status="pause", criado=SEG2 + 8 * HORA, iniciado=SEG2 + 8 * HORA,
                      pausas=[pz(SEG2 + 10 * HORA, SEG2 + 10 * HORA + MIN)], prazo_em=SEG2 + 99 * HORA)
        self.assertEqual(self.tags(fechada, SEG2 + 12 * HORA), {})   # pausa já fechada não marca

    def test_T62_atrasada_marca_no_prazo_mais_1ms_e_so_ativa(self):
        """[T62] "late" só depois do prazo exato; concluída e cancelada não aparecem."""
        p = SEG2 + 7 * HORA + 30 * MIN
        d = dem(status="prog", iniciado=SEX + 16 * HORA + 30 * MIN)
        self.assertEqual(self.tags(d, p), {})
        self.assertIn("late", self.tags(d, p + 1))
        for st in ("done", "canc"):
            self.assertEqual(calc.atencao([dem(status=st, fim=p + HORA)], p + DIA, AGENDAS), [], st)

    def test_T63_known_bug_atencao_late_deveria_medir_em_tempo_util(self):
        """[T63] BUG B2 (baixo): o "late.min" do Python é corrido; o JS mostra "Atrasada há" em tempo útil.

        Prazo sexta 17:00, agora seg 07:30: 30 min úteis de atraso (é o que `attention()` do JS mostra), mas
        `calc.atencao` devolve 3750 min (62,5 h corridas). Hoje `calc.atencao` só é chamada pelos testes.
        """
        d = dem(status="prog", iniciado=SEX + 16 * HORA, prazo_em=SEX + 17 * HORA)
        self.assertEqual(self.tags(d, SEG2 + 7 * HORA + 30 * MIN)["late"], 30.0)


# ---------------------------------------------------------------------------------------------------------------
# Turno noturno, feriado e horário por setor (funções puras)
# ---------------------------------------------------------------------------------------------------------------

class TurnoNoturnoEFeriado(unittest.TestCase):
    def test_T41_noturno_abertura_22_conta_fecho_06_nao(self):
        """[T41] turno 22→06: bordas exatas de abertura e fecho (e a madrugada que vem da véspera)."""
        g = grade(padrao=NOITE)
        self.assertEqual((ag.util_entre(g, SEG + 22 * HORA - 1, SEG + 22 * HORA), ag.util_entre(g, SEG + 22 * HORA, SEG + 22 * HORA + 1)), (0, 1))
        self.assertEqual((ag.util_entre(g, TER + 6 * HORA - 1, TER + 6 * HORA), ag.util_entre(g, TER + 6 * HORA, TER + 6 * HORA + 1)), (1, 0))
        self.assertTrue(ag.aberto(g, SEG + 22 * HORA))
        self.assertFalse(ag.aberto(g, SEG + 22 * HORA - 1))
        self.assertTrue(ag.aberto(g, TER + 6 * HORA - 1))
        self.assertFalse(ag.aberto(g, TER + 6 * HORA))
        self.assertEqual(ag.soma_util(g, SEG + 22 * HORA, 8 * 60), TER + 6 * HORA)          # o turno inteiro: 8 h
        self.assertEqual(ag.soma_util(g, SEG + 22 * HORA, 8 * 60 + 1), TER + 22 * HORA + MIN)   # 1 min além: o turno seguinte

    def test_T41b_sexta_a_noite_vai_ate_sabado_e_domingo_nao_trabalha(self):
        """[T41] a noite de sexta invade o sábado até as 06:00; a de sábado e a de domingo não existem."""
        g = grade(padrao=NOITE)
        self.assertEqual(ag.util_entre(g, SAB, SAB + DIA), 6 * HORA)
        self.assertEqual(ag.util_entre(g, SAB + 6 * HORA, SEG2 + 22 * HORA), 0)
        self.assertEqual(ag.util_entre(g, SEX + 22 * HORA, SEG2 + 22 * HORA), 8 * HORA)
        self.assertEqual(ag.soma_util(g, SAB + 3 * HORA, 4 * 60), SEG2 + 22 * HORA + HORA)   # 3 h do sábado + 1 h da segunda

    def test_T42_feriado_vale_para_o_dia_em_que_o_turno_comeca(self):
        """[T42] feriado na terça (turno 22→06): some a noite de terça e a manhã de quarta; a manhã de terça fica."""
        g = grade(padrao=NOITE, feriados=[{"data": "2026-11-10", "nome": "x"}])
        self.assertEqual(ag.util_entre(g, TER, TER + 6 * HORA), 6 * HORA)         # vem da noite de segunda
        self.assertEqual(ag.util_entre(g, TER + 6 * HORA, QUA + 12 * HORA), 0)    # noite de terça e manhã de quarta: feriado
        self.assertEqual(ag.util_entre(g, QUA + 22 * HORA, QUI + 6 * HORA), 8 * HORA)
        # feriado no sábado não tira o turno que começou na sexta
        g2 = grade(padrao=NOITE, feriados=[{"data": "2026-11-14", "nome": "x"}])
        self.assertEqual(ag.util_entre(g2, SAB, SAB + 6 * HORA), 6 * HORA)
        # feriado na sexta tira a noite de sexta e a madrugada de sábado, mas não a madrugada de sexta (vem de quinta)
        g3 = grade(padrao=NOITE, feriados=[{"data": "2026-11-13", "nome": "x"}])
        self.assertEqual(ag.util_entre(g3, SEX, SEX + 6 * HORA), 6 * HORA)
        self.assertEqual(ag.util_entre(g3, SEX + 6 * HORA, SAB + 12 * HORA), 0)

    def test_T43_feriado_geral_e_feriado_de_um_setor(self):
        """[T43] feriado geral vale para todos; o de setor só para ele; duas datas no mesmo dia somam."""
        a = cfg(feriados=[{"data": "2026-11-16", "nome": "geral"}, {"data": "2026-11-17", "nome": "so CNC", "setores": ["CNC"]},
                          {"data": "2026-11-17", "nome": "so ESP", "setores": ["ESP"]}])
        cnc, esp, pcp = ag.grade(a, "CNC"), ag.grade(a, "ESP"), ag.grade(a, "PCP")
        for g, esperado in ((cnc, 3 * 9 * HORA), (esp, 3 * 9 * HORA), (pcp, 4 * 9 * HORA)):   # 4 dias úteis de 16 a 20 menos feriados
            self.assertEqual(ag.util_entre(g, SEG2, SEG2 + 5 * DIA), esperado)
        self.assertEqual(ag.soma_util(cnc, SEX + 16 * HORA + 30 * MIN, 60), ms(2026, 11, 18, 7, 30))
        self.assertEqual(ag.soma_util(esp, SEX + 16 * HORA + 30 * MIN, 60), ms(2026, 11, 18, 7, 30))
        self.assertEqual(ag.soma_util(pcp, SEX + 16 * HORA + 30 * MIN, 60), ms(2026, 11, 17, 7, 30))

    def test_T44_feriado_em_dia_sem_expediente_nao_muda_nada(self):
        """[T44] feriado no sábado/domingo (já sem trabalho) não altera a medida; feriado no limite do mês e do ano."""
        com, sem = grade(), grade(feriados=[{"data": "2026-11-14", "nome": "x"}, {"data": "2026-11-15", "nome": "y"}])
        self.assertEqual(ag.util_entre(com, SEG, SEG2 + 8 * HORA), ag.util_entre(sem, SEG, SEG2 + 8 * HORA))
        ano = grade(feriados=[{"data": "2026-12-31", "nome": "x"}, {"data": "2027-01-01", "nome": "y"}])
        self.assertEqual(ag.soma_util(ano, ms(2026, 12, 30, 16, 30), 60), ms(2027, 1, 4, 7, 30))   # qui 16:30 + 30 min; sex 31 e sex 1 feriado; seg 4 07:30

    def test_T45_horario_proprio_por_setor_e_padrao_dos_outros(self):
        """[T45] setor com grade própria usa só a dela; os outros, o padrão; feriado de setor soma ao horário próprio."""
        a = cfg(setores={"SLD": {"dias": [6], "turnos": [["06:00", "10:00"]]}},
                feriados=[{"data": "2026-11-21", "nome": "x", "setores": ["SLD"]}])
        sld, cnc = ag.grade(a, "SLD"), ag.grade(a, "CNC")
        self.assertEqual(ag.util_entre(sld, SEG, SEG2), 4 * HORA)          # só o sábado 14
        self.assertEqual(ag.util_entre(cnc, SEG, SEG2), 45 * HORA)
        self.assertEqual(ag.soma_util(sld, SAB + 9 * HORA, 120), ms(2026, 11, 28, 7, 0))   # sáb 21 é feriado do SLD: pula para 28
        self.assertEqual(ag.util_entre(sld, DOM, DOM + 7 * DIA), 0)      # de dom 15 a dom 22: o único sábado (21) é feriado do SLD

    def test_T46_dia_inteiro_24h_por_turnos_encostados(self):
        """[T46] três turnos de 8 h encostados (06-14, 14-22, 22-06), sete dias: o tempo útil é o tempo corrido."""
        g = grade(padrao={"dias": [1, 2, 3, 4, 5, 6, 7], "turnos": [["06:00", "14:00"], ["14:00", "22:00"], ["22:00", "06:00"]]})
        for a, b in ((SEG, SEG + 3 * DIA), (SEG + 5 * HORA + 17 * MIN, SEG2 + 3 * HORA + 1), (SEG + 1, SEG + 2)):
            self.assertEqual(ag.util_entre(g, a, b), b - a, (a, b))
        self.assertEqual(ag.soma_util(g, SEG + 5 * HORA, 100 * 60), SEG + 5 * HORA + 100 * HORA)
        self.assertEqual(ag.expediente(g, SEG, SEG + 3 * DIA), [[SEG, SEG + 3 * DIA]])   # uma faixa só, sem emendas


class Tetos(unittest.TestCase):
    def test_T80_soma_util_procura_ate_400_dias(self):
        """[T80] 1 h/dia: dá para somar 401 dias de trabalho a partir da abertura; 402 estoura com a frase do contrato."""
        g = grade(padrao={"dias": [1, 2, 3, 4, 5, 6, 7], "turnos": [["07:00", "08:00"]]})
        for n in (399, 400, 401):
            fim = ag.soma_util(g, SEX + 7 * HORA, n * 60)
            self.assertEqual(ag.util_entre(g, SEX + 7 * HORA, fim), n * HORA, n)
        for n in (402, 403, 1000):
            with self.assertRaises(ValueError) as c:
                ag.soma_util(g, SEX + 7 * HORA, n * 60)
            self.assertEqual(str(c.exception), "O horário de serviço não tem trabalho suficiente em 400 dias.")
        # o limite é de calendário (402 dias de percurso), não de horas: com 8 h/dia cabem só ~50 dias de 8 h... e 400 dias de 1 h
        g8 = grade(padrao={"dias": [1, 2, 3, 4, 5, 6, 7], "turnos": [["00:00", "08:00"]]})
        self.assertEqual(ag.soma_util(g8, SEX, 400 * 8 * 60), SEX + 399 * DIA + 8 * HORA)
        with self.assertRaises(ValueError):
            ag.soma_util(g8, SEX, 402 * 8 * 60 + 1)

    def test_T81_util_entre_mede_no_maximo_3700_dias(self):
        """[T81] 1 h/dia: 3699 e 3700 dias medem 3699/3700 h; 3701 e um século medem só 3700 h (teto)."""
        g = grade(padrao={"dias": [1, 2, 3, 4, 5, 6, 7], "turnos": [["07:00", "08:00"]]})
        self.assertEqual(ag.util_entre(g, SEX, SEX + 3699 * DIA) // HORA, 3699)
        self.assertEqual(ag.util_entre(g, SEX, SEX + 3700 * DIA) // HORA, 3700)
        self.assertEqual(ag.util_entre(g, SEX, SEX + 3701 * DIA) // HORA, 3700)
        self.assertEqual(ag.util_entre(g, SEX, SEX + 36500 * DIA) // HORA, 3700)

    def test_T82_grade_none_nunca_estoura(self):
        """[T82] sem grade (tempo corrido) nenhuma das duas funções tem teto."""
        self.assertEqual(ag.util_entre(None, 0, 10 ** 15), 10 ** 15)
        self.assertEqual(ag.soma_util(None, 0, 10 ** 7), 10 ** 7 * MIN)


class VersoesEGradeDaDemanda(unittest.TestCase):
    def test_T36_demanda_antiga_sem_agenda_v_mede_sempre_em_tempo_corrido(self):
        """[T36] sem `agenda_v` (criada antes do horário): grade None mesmo com agenda ativa e `agendas` cheia."""
        d = dem(criado=SEX + 16 * HORA + 30 * MIN, est=60)
        d.pop("agenda_v")
        d.pop("prazo_em")
        self.assertIsNone(calc.grade_de(d, AGENDAS))
        self.assertEqual(calc.prazo(d), SEX + 17 * HORA + 30 * MIN)
        m = calc.metricas(d, SAB + 12 * HORA, AGENDAS)
        self.assertEqual((m["total"], m["atrasada"]), (19.5 * 60, True))
        self.assertFalse(calc.atrasada(d, SEX + 17 * HORA + 30 * MIN))
        self.assertTrue(calc.atrasada(d, SEX + 17 * HORA + 30 * MIN + 1))

    def test_T37_versao_que_sumiu_cai_no_corrido(self):
        """[T37] `agenda_v` sem a versão correspondente em `agendas`: tempo corrido, prazo gravado preservado."""
        d = dem(agenda_v=7)
        self.assertIsNone(calc.grade_de(d, AGENDAS))
        self.assertEqual(calc.espera_ms(d, SAB + 12 * HORA, AGENDAS), SAB + 12 * HORA - d["criado"])
        self.assertEqual(calc.prazo(d), SEG2 + 7 * HORA + 30 * MIN)

    def test_T38_o_setor_destino_manda_na_grade(self):
        """[T38] a mesma demanda mede com a grade do setor em `para.s` (padrão se o setor não tem exceção)."""
        agendas = {"1": cfg(setores={"SLD": {"dias": [6], "turnos": [["06:00", "10:00"]]}})}
        d = dem(para={"s": "SLD", "p": None})
        self.assertEqual(calc.grade_de(d, agendas)["dias"], frozenset({6}))
        self.assertEqual(calc.grade_de(dem(), agendas)["dias"], frozenset({1, 2, 3, 4, 5}))
        self.assertEqual(calc.total_ms(dem(para={"s": "SLD", "p": None}, criado=SAB), SAB + DIA, agendas), 4 * HORA)


# ---------------------------------------------------------------------------------------------------------------
# Crono, gantt e expediente
# ---------------------------------------------------------------------------------------------------------------

class CronoEExpediente(unittest.TestCase):
    def test_T70_expediente_da_janela_e_so_dos_setores_com_horario_proprio(self):
        """[T70] `expediente` só com agenda ativa; `setores` só traz os que têm horário ou feriado próprio, ordenados."""
        a = cfg(setores={"SLD": {"dias": [6], "turnos": [["06:00", "10:00"]]}},
                feriados=[{"data": "2026-11-16", "nome": "x", "setores": ["CNC"]}, {"data": "2026-11-17", "nome": "y"}])
        agora = SEG2 + 10 * HORA
        for out in (calc.gantt([], agora, SEG2, SEG2 + 2 * DIA, "setor", agenda=a), calc.gantt([], agora, SEG2, SEG2 + 2 * DIA, agenda=a)):
            self.assertEqual(list(out["expediente"]["setores"]), ["CNC", "SLD"])
        # o geral trabalha na segunda 16 (a terça 17 é feriado geral); o CNC tem feriado na 16 e na 17: nada; o SLD só trabalha sábado
        out = calc.gantt([], agora, SEG2, SEG2 + 2 * DIA, "setor", agenda=a)
        self.assertEqual(out["expediente"]["geral"], [[SEG2 + 7 * HORA, SEG2 + 12 * HORA], [SEG2 + 13 * HORA, SEG2 + 17 * HORA]])
        self.assertEqual(out["expediente"]["setores"]["CNC"], [])
        self.assertEqual(out["expediente"]["setores"]["SLD"], [])
        self.assertNotIn("expediente", calc.gantt([], agora, SEG2, SEG2 + DIA, agenda=dict(a, ativa=False)))
        self.assertNotIn("expediente", calc.gantt([], agora, SEG2, SEG2 + DIA, agenda=None))
        self.assertNotIn("expediente", calc.gantt([], agora, SEG2, SEG2 + DIA, agenda="x"))

    def test_T71_crono_mede_cada_demanda_na_agenda_da_sua_versao(self):
        """[T71] médias do crono: uma demanda na versão comercial (v1), outra na 24 h (v2): médias das duas medidas."""
        v1 = cfg(v=1)
        v2 = cfg(v=2, padrao={"dias": [1, 2, 3, 4, 5, 6, 7], "turnos": [["00:00", "12:00"], ["12:00", "00:00"]]})
        agendas = {"1": v1, "2": v2}
        a = dem(id="SOL-1001", status="done", criado=SEX + 16 * HORA, iniciado=SEG2 + 8 * HORA, fim=SEG2 + 9 * HORA, agenda_v=1)
        b = dem(id="SOL-1002", status="done", criado=SEX + 16 * HORA, iniciado=SEG2 + 8 * HORA, fim=SEG2 + 9 * HORA, agenda_v=2)
        calc.congela(a, a["fim"], agendas)
        calc.congela(b, b["fim"], agendas)
        c = calc.crono([a, b], SEG2 + 10 * HORA, 30, agendas, v2)
        esp_a = (1 + 1) * 60            # sex 16-17 + seg 07-08
        esp_b = (SEG2 + 8 * HORA - (SEX + 16 * HORA)) // MIN   # corrido de verdade
        self.assertEqual(c["kpis"]["espera"], round((esp_a + esp_b) / 2, 1))
        self.assertEqual(c["kpis"]["execucao"], 60.0)
        self.assertEqual(c["kpis"]["concluidas"], 2)

    def test_T72_expediente_e_fora_cobrem_a_janela_sem_sobrepor(self):
        """[T72] propriedade (semente fixa): os intervalos do expediente são ordenados, separados, e somam a medida."""
        rng = random.Random(SEMENTE)
        for _ in range(120):
            g = gerar_grade(rng)["grade"]
            a = SEG + rng.randrange(0, 20 * DIA, MIN)
            b = a + rng.randrange(0, 12 * DIA, MIN)
            blocos = ag.expediente(g, a, b)
            self.assertEqual(sum(y - x for x, y in blocos), ag.util_entre(g, a, b))
            for (x, y), (x2, y2) in zip(blocos, blocos[1:]):
                self.assertTrue(a <= x < y < x2 < y2 <= b)      # separados por pelo menos 1 ms de folga
            for x, y in blocos:
                self.assertTrue(a <= x < y <= b)
                self.assertTrue(ag.aberto(g, x) and ag.aberto(g, y - 1))
                if y < b:
                    self.assertFalse(ag.aberto(g, y))      # o fecho não conta
                if x > a:
                    self.assertFalse(ag.aberto(g, x - 1))  # um ms antes da abertura está fechado

    def test_T73_janela_vazia_ou_invertida_nao_tem_expediente(self):
        """[T73] expediente de janela com b <= a devolve lista vazia (com e sem grade)."""
        g = grade()
        self.assertEqual(ag.expediente(g, SEG + 8 * HORA, SEG + 8 * HORA), [])
        self.assertEqual(ag.expediente(g, SEG + 9 * HORA, SEG + 8 * HORA), [])


# ---------------------------------------------------------------------------------------------------------------
# Propriedades (semente fixa)
# ---------------------------------------------------------------------------------------------------------------

def gerar_grade(rng):
    """Uma agenda válida aleatória (1 a 3 turnos de 15 em 15 min, dias e feriados sorteados) e a grade de um setor."""
    for _ in range(200):
        dias = sorted(rng.sample(range(1, 8), rng.randrange(1, 8)))
        turnos = []
        for _ in range(rng.randrange(1, 4)):
            a = rng.randrange(0, 96) * 15
            b = rng.randrange(0, 96) * 15
            if a == b:
                continue
            turnos.append(["%02d:%02d" % divmod(a, 60), "%02d:%02d" % divmod(b, 60)])
        feriados = [{"data": (datetime.date(2026, 11, 9) + datetime.timedelta(days=rng.randrange(0, 40))).isoformat(), "nome": "f",
                     "setores": rng.choice([[], ["CNC"], ["ESP"]])} for _ in range(rng.randrange(0, 5))]
        try:
            agenda = cfg(padrao={"dias": dias, "turnos": turnos}, feriados=feriados)
        except ValueError:
            continue
        setor = rng.choice(["CNC", "ESP"])
        return {"agenda": agenda, "setor": setor, "grade": ag.grade(agenda, setor)}
    raise AssertionError("não achou agenda válida")


class Propriedades(unittest.TestCase):
    def sorteio(self, n=40):
        rng = random.Random(SEMENTE)
        for _ in range(n):
            yield rng, gerar_grade(rng)["grade"]

    def test_T95_soma_e_medida_andam_juntas(self):
        """[T95] util_entre(ini, soma_util(ini, m)) == m; um ms antes ainda falta 1 ms e o instante está aberto."""
        for rng, g in self.sorteio():
            for _ in range(25):
                ini = SEG + rng.randrange(0, 15 * DIA, MIN) + rng.choice([0, 0, 1, 777])
                m = rng.choice([1, 15, 60, 61, 480, 540, 2000]) + rng.randrange(0, 30)
                try:
                    fim = ag.soma_util(g, ini, m)
                except ValueError:
                    continue   # feriados + poucos dias de trabalho: não achou em 400 dias (já tem teste próprio)
                self.assertEqual(ag.util_entre(g, ini, fim), m * MIN, (ini, m))
                self.assertEqual(ag.util_entre(g, ini, fim - 1), m * MIN - 1, (ini, m))   # minimalidade
                self.assertTrue(ag.aberto(g, fim - 1), (ini, m))

    def test_T96_monotonia(self):
        """[T96] util_entre cresce com o fim; soma_util cresce com os minutos e com o início."""
        for rng, g in self.sorteio():
            for _ in range(15):
                a = SEG + rng.randrange(0, 15 * DIA, MIN)
                b1 = a + rng.randrange(0, 6 * DIA, MIN)
                b2 = b1 + rng.randrange(0, 3 * DIA, MIN)
                self.assertLessEqual(ag.util_entre(g, a, b1), ag.util_entre(g, a, b2))
                m1 = rng.randrange(1, 600)
                m2 = m1 + rng.randrange(0, 600)
                a2 = a + rng.randrange(0, 2 * DIA, MIN)
                try:
                    self.assertLessEqual(ag.soma_util(g, a, m1), ag.soma_util(g, a, m2))
                    self.assertLessEqual(ag.soma_util(g, a, m1), ag.soma_util(g, a2, m1))
                except ValueError:
                    continue

    def test_T97_aditividade(self):
        """[T97] util(a,c) == util(a,b) + util(b,c) para a <= b <= c; 0 <= util <= corrido; util(a,a) = 0."""
        for rng, g in self.sorteio():
            for _ in range(20):
                a = SEG + rng.randrange(0, 15 * DIA, MIN) + rng.choice([0, 1, 12345])
                b = a + rng.randrange(0, 5 * DIA, MIN) + rng.choice([0, 1])
                c = b + rng.randrange(0, 5 * DIA, MIN) + rng.choice([0, 1])
                self.assertEqual(ag.util_entre(g, a, c), ag.util_entre(g, a, b) + ag.util_entre(g, b, c), (a, b, c))
                self.assertTrue(0 <= ag.util_entre(g, a, c) <= c - a)
                self.assertEqual(ag.util_entre(g, a, a), 0)
                self.assertEqual(ag.util_entre(g, c, a), 0 if c > a else ag.util_entre(g, c, a))

    def test_T98_composicao_da_soma(self):
        """[T98] somar m1+m2 de uma vez == somar m1 e continuar de onde parou somando m2."""
        for rng, g in self.sorteio(25):
            for _ in range(15):
                ini = SEG + rng.randrange(0, 12 * DIA, MIN)
                m1, m2 = rng.randrange(1, 700), rng.randrange(1, 700)
                try:
                    inteiro = ag.soma_util(g, ini, m1 + m2)
                    meio = ag.soma_util(g, ini, m1)
                    self.assertEqual(ag.soma_util(g, meio, m2), inteiro, (ini, m1, m2))
                except ValueError:
                    continue

    def test_T99_prazo_gravado_e_a_estimativa_em_tempo_util(self):
        """[T99] invariante de criação: util_entre(grade, criado, prazo_em) == est·60000 (SLA 100% no prazo)."""
        for rng, g in self.sorteio():
            for _ in range(15):
                criado = SEG + rng.randrange(0, 15 * DIA, MIN)
                est = rng.randrange(1, 1500)
                try:
                    p = ag.soma_util(g, criado, est)
                except ValueError:
                    continue
                self.assertEqual(ag.util_entre(g, criado, p), est * MIN)
                self.assertFalse(calc.atrasada(dem(criado=criado, est=est, prazo_em=p), p))


# ---------------------------------------------------------------------------------------------------------------
# API: criar, estender, versões da agenda, reatribuir e tick (dados num diretório temporário)
# ---------------------------------------------------------------------------------------------------------------

ADM = {"papel": "maquina"}
OP = {"papel": "operador"}
SEX_1630 = SEX + 16 * HORA + 30 * MIN
SEG2_0730 = SEG2 + 7 * HORA + 30 * MIN


class Base(unittest.TestCase):
    def setUp(self):
        self._data = os.environ.get("DEMANDAS_DATA")
        self.dir = Path(tempfile.mkdtemp(prefix="qa-tempo-"))
        os.environ["DEMANDAS_DATA"] = str(self.dir)
        ds._CACHE.update(key=None, texto=None)
        ds._ARQ.update(key=None, demandas=[])
        api._TK.clear()
        api._FAILS.clear()
        self.t = SEX_1630
        self.clk = 1000.0
        api._clock = lambda: self.clk
        api._parede = lambda: self.clk
        api._agora = lambda: self.t
        api.ITER = 1000
        fs = mock.patch("os.fsync", lambda fd: None)
        fs.start()
        self.addCleanup(fs.stop)
        for sid, nome in (("PCP", "Planejamento"), ("CNC", "Corte CNC"), ("ESP", "Espumação"), ("SLD", "Solda")):
            self.adm("setor/salvar", {"modo": "novo", "id": sid, "nome": nome, "icone": "⚙️", "cor": "#3B82F6", "rev": 0})
        self.carlos = self.pessoa("Carlos", "CNC", "2222")
        self.fer = self.pessoa("Fernanda", "ESP", "4444")
        self.tk_c = api.handle("POST", "entrar", {"pessoa": self.carlos, "codigo": "2222"}, OP)["tk"]
        self.tk_f = api.handle("POST", "entrar", {"pessoa": self.fer, "codigo": "4444"}, OP)["tk"]

    def tearDown(self):
        api.ITER = ITER_REAL
        if self._data is None:
            os.environ.pop("DEMANDAS_DATA", None)
        else:
            os.environ["DEMANDAS_DATA"] = self._data

    def adm(self, rest, body=None):
        return api.handle("POST", rest, dict(body or {}), ADM)

    def pes(self, tk, rest, body=None):
        return api.handle("POST", rest, dict(body or {}, tk=tk), OP)

    def pessoa(self, nome, setor, codigo):
        return self.adm("pessoa/salvar", {"modo": "novo", "nome": nome, "setor": setor, "codigo": codigo, "rev": 0})["pessoas"][-1]["id"]

    def erro(self, fn, *a):
        with self.assertRaises(api.ApiError) as c:
            fn(*a)
        return c.exception.status

    def disco(self):
        return json.loads((self.dir / "demandas.json").read_text(encoding="utf-8"))

    def d(self, did):
        return next(x for x in self.disco()["demandas"] if x["id"] == did)

    def liga(self, **kw):
        v = self.disco()["agenda"]["v"]
        return self.adm("agenda/salvar", {"agenda": {**ag.padrao(), "ativa": True, "v": v, **kw}})

    def nova(self, est=60, setor="CNC", **kw):
        body = {"titulo": "Cortar chapas", "tipo": "dem", "motivo": "Outro", "prio": "norm", "est": est,
                "para": {"s": setor, "p": None}, "desc": "", "de_s": "PCP"}
        body.update(kw)
        v = self.adm("demanda/criar", body)
        return max(v["demandas"], key=lambda x: int(x["id"][4:]))["id"]

    def vd(self, did):
        v = self.adm("vista")
        return next(x for x in v["demandas"] if x["id"] == did)

    def medida(self, did):
        """A demanda gravada e as agendas, como o servidor as mede."""
        doc = self.disco()
        return next(x for x in doc["demandas"] if x["id"] == did), doc["agendas"]

    def eventos(self, did, ev):
        return [e for e in self.d(did)["eventos"] if e["ev"] == ev]


class Estender(Base):
    def test_T20_estender_soma_horas_de_trabalho_a_partir_do_prazo(self):
        """[T20] prazo no fecho (17:00) + 30 min cai na abertura seguinte + 30; pelo almoço; 24 h de trabalho atravessam três dias úteis."""
        self.liga()
        a = self.nova(est=30)
        self.assertEqual(self.d(a)["prazo_em"], SEX + 17 * HORA)             # termina exatamente no fecho
        self.adm("demanda/estender", {"id": a, "minutos": 30})
        self.assertEqual(self.d(a)["prazo_em"], SEG2 + 7 * HORA + 30 * MIN)
        self.assertEqual(self.vd(a)["prazo"], SEG2 + 7 * HORA + 30 * MIN)
        self.adm("demanda/estender", {"id": a, "minutos": 1440})              # 24 h de trabalho a partir de seg 07:30: 8,5 + 9 + 6,5
        self.assertEqual(self.d(a)["prazo_em"], ms(2026, 11, 18, 14, 30))
        self.assertEqual(self.d(a)["est"], 30 + 30 + 1440)
        self.t = SEG2 + 11 * HORA + 30 * MIN
        b = self.nova(est=30)
        self.assertEqual(self.d(b)["prazo_em"], SEG2 + 12 * HORA)
        self.adm("demanda/estender", {"id": b, "minutos": 30})                # o almoço não conta
        self.assertEqual(self.d(b)["prazo_em"], SEG2 + 13 * HORA + 30 * MIN)

    def test_T21_estender_prazo_ja_vencido_soma_a_partir_do_prazo_vigente(self):
        """[T21] atrasada há dias: +60 vai de prazo a prazo+60 úteis (não de agora); segue atrasada e avisada."""
        self.liga()
        a = self.nova(est=60)
        self.t = TER2 + 10 * HORA
        self.adm("demanda/estender", {"id": a, "minutos": 60})
        self.assertEqual(self.d(a)["prazo_em"], SEG2 + 8 * HORA + 30 * MIN)
        self.assertTrue(self.d(a)["atraso_avisado"])
        self.assertTrue(self.vd(a)["atrasada"])
        self.assertEqual(len(self.eventos(a, "late")), 1)

    def test_T22_estender_so_rearma_o_aviso_se_o_novo_prazo_e_futuro(self):
        """[T22] novo prazo == agora: continua avisada; 1 ms no futuro: rearma, e o tick avisa de novo ao passar."""
        self.liga()
        a, b = self.nova(est=60), self.nova(est=60)
        for did in (a, b):
            self.assertEqual(self.d(did)["prazo_em"], SEG2_0730)
        novo = SEG2 + 8 * HORA + 30 * MIN
        self.t = novo
        self.assertTrue(api.tick(self.t))
        self.assertTrue(self.d(a)["atraso_avisado"] and self.d(b)["atraso_avisado"])
        self.adm("demanda/estender", {"id": a, "minutos": 60})        # novo prazo == agora
        self.assertEqual(self.d(a)["prazo_em"], novo)
        self.assertTrue(self.d(a)["atraso_avisado"])
        self.t = novo - 1
        self.adm("demanda/estender", {"id": b, "minutos": 60})        # novo prazo 1 ms depois de agora
        self.assertFalse(self.d(b)["atraso_avisado"])
        self.assertFalse(api.tick(novo))                              # no prazo exato ainda não atrasa
        self.assertTrue(api.tick(novo + 1))
        self.assertTrue(self.d(b)["atraso_avisado"])
        self.assertEqual(len(self.eventos(b, "late")), 2)

    def test_T23_estender_sem_horario_de_servico_segue_o_est_corrido(self):
        """[T23] demanda sem `agenda_v` (horário desligado): prazo = criado + est, sem `prazo_em` gravado."""
        a = self.nova(est=60)
        self.adm("demanda/estender", {"id": a, "minutos": 30})
        self.assertNotIn("prazo_em", self.d(a))
        self.assertEqual(self.vd(a)["prazo"], SEX_1630 + 90 * MIN)

    def test_T24_estender_usa_a_grade_da_versao_da_demanda(self):
        """[T24] a agenda mudou depois da criação: a extensão soma na versão antiga (a demanda "fica" nela)."""
        self.liga()
        a = self.nova(est=30)
        self.liga(padrao={"dias": [1, 2, 3, 4, 5], "turnos": [["09:00", "18:00"]]})    # v2
        b = self.nova(est=60)
        self.assertEqual(self.d(b)["prazo_em"], SEX + 17 * HORA + 30 * MIN)              # v2 fecha às 18:00
        self.adm("demanda/estender", {"id": a, "minutos": 30})
        self.assertEqual(self.d(a)["prazo_em"], SEG2 + 7 * HORA + 30 * MIN)              # v1 abre às 07:00 (v2 abriria às 09:00)
        self.assertEqual(self.d(a)["agenda_v"], 1)

    def test_T25_estender_no_limite_de_30_dias(self):
        """[T25] est+minutos == 43200 passa; 43201 é recusado (400) sem mudar est, prazo nem rev."""
        self.liga()
        a = self.nova(est=43190)
        antes = self.disco()
        self.assertEqual(self.erro(self.adm, "demanda/estender", {"id": a, "minutos": 11}), 400)
        depois = self.disco()
        self.assertEqual((depois["rev"], self.d(a)["est"], self.d(a)["prazo_em"]), (antes["rev"], 43190, antes["demandas"][0]["prazo_em"]))
        self.adm("demanda/estender", {"id": a, "minutos": 10})
        self.assertEqual(self.d(a)["est"], 43200)
        self.assertEqual(ag.util_entre(ag.grade(self.disco()["agenda"], "CNC"), SEX_1630, self.d(a)["prazo_em"]), 43200 * MIN)

    def test_T26_estender_mantem_a_invariante_util_igual_est(self):
        """[T26] depois de criar e de estender várias vezes, util(criado, prazo) == est·60000 na grade da demanda."""
        self.liga(setores={"ESP": {"dias": [1, 2, 3, 4, 5, 6], "turnos": [["06:00", "14:00"], ["14:00", "22:00"]]}})
        for setor in ("CNC", "ESP"):
            a = self.nova(est=90, setor=setor)
            for m in (1, 59, 600, 1440):
                self.adm("demanda/estender", {"id": a, "minutos": m})
            d, agendas = self.medida(a)
            g = calc.grade_de(d, agendas)
            self.assertEqual(ag.util_entre(g, d["criado"], calc.prazo(d)), d["est"] * MIN, setor)


class VersoesDaAgenda(Base):
    def test_T30_mudar_a_agenda_nao_mexe_nas_demandas_em_andamento(self):
        """[T30] A criada na v1, B na v2 (06–10): mesma hora, medidas diferentes; a vista leva as duas versões."""
        self.t = SEG2 + 8 * HORA
        self.liga()
        a = self.nova(est=60)
        self.liga(padrao={"dias": [1, 2, 3, 4, 5], "turnos": [["06:00", "10:00"]]})
        b = self.nova(est=60)
        self.assertEqual((self.d(a)["agenda_v"], self.d(b)["agenda_v"]), (1, 2))
        self.assertEqual((self.d(a)["prazo_em"], self.d(b)["prazo_em"]), (SEG2 + 9 * HORA, SEG2 + 9 * HORA))
        self.t = SEG2 + 11 * HORA + 30 * MIN
        va, vb = self.vd(a), self.vd(b)
        self.assertEqual((va["espera"], vb["espera"]), (210.0, 120.0))      # v1 trabalha até 12:00; v2 fechou às 10:00
        self.assertEqual(sorted(self.adm("vista")["agendas"]), ["1", "2"])
        self.assertEqual(sorted(self.disco()["agendas"]), ["1", "2"])

    def test_T31_concluir_libera_a_versao_e_o_util_gravado_continua(self):
        """[T31] A concluída: a v1 sai no próximo salvar; a espera de A (gravada) não depende mais da agenda."""
        self.t = SEG2 + 8 * HORA
        self.liga()
        a = self.nova(est=60)
        self.liga(padrao={"dias": [1, 2, 3, 4, 5], "turnos": [["06:00", "10:00"]]})
        b = self.nova(est=60)
        self.t = SEG2 + 11 * HORA + 30 * MIN
        self.pes(self.tk_c, "demanda/aceitar", {"id": a})
        self.pes(self.tk_c, "demanda/concluir", {"id": a})
        self.assertEqual(self.d(a)["util"]["espera"], 210 * MIN)
        self.liga(padrao={"dias": [1, 2, 3, 4, 5], "turnos": [["05:00", "10:00"]]})
        self.assertEqual(sorted(self.disco()["agendas"]), ["2", "3"])
        self.assertEqual(self.vd(a)["espera"], 210.0)                         # gravado: sem a v1 na vista
        self.assertEqual(self.vd(b)["espera"], 120.0)
        self.assertEqual(sorted(self.adm("vista")["agendas"]), ["2"])         # a vista só leva as versões das ativas

    def test_T33_snapshots_sao_copias_independentes(self):
        """[T33] salvar uma versão nova não altera o conteúdo da anterior guardada para a demanda em andamento."""
        self.liga()
        self.nova(est=60)
        self.liga(feriados=[{"data": "2026-12-25", "nome": "Natal", "setores": []}])
        doc = self.disco()
        self.assertEqual(doc["agendas"]["1"]["feriados"], [])
        self.assertEqual(doc["agendas"]["2"]["feriados"][0]["data"], "2026-12-25")
        self.assertEqual(doc["agendas"]["2"], doc["agenda"])
        self.assertEqual((doc["agendas"]["1"]["v"], doc["agendas"]["2"]["v"]), (1, 2))

    def test_T34_agenda_desligada_depois_mantem_as_demandas_em_horario_e_as_novas_correm(self):
        """[T34] desligar: a antiga segue em tempo útil (v1); a nova nasce em tempo corrido, sem `agenda_v`."""
        self.liga()
        a = self.nova(est=60)
        self.liga(ativa=False)
        b = self.nova(est=60)
        self.assertNotIn("agenda_v", self.d(b))
        self.assertEqual(self.d(b).get("prazo_em"), None)
        self.t = SAB + 12 * HORA
        va, vb = self.vd(a), self.vd(b)
        self.assertEqual((va["total"], va["atrasada"]), (30.0, False))             # sex 16:30-17:00; prazo seg 07:30
        self.assertEqual((vb["total"], vb["atrasada"]), (19.5 * 60, True))         # corrido; prazo sex 17:30
        self.assertEqual(sorted(self.adm("vista")["agendas"]), ["1"])

    def test_T35_criada_antes_de_ligar_continua_em_tempo_corrido(self):
        """[T35] demanda criada com o horário desligado: ligar depois não muda nada nela (prazo, atraso e tick corridos)."""
        a = self.nova(est=60)
        self.liga()
        self.assertEqual(self.vd(a)["prazo"], SEX_1630 + HORA)
        self.t = SEX_1630 + HORA
        self.assertFalse(api.tick(self.t))
        self.assertTrue(api.tick(self.t + 1))                                       # corrido: 17:30 de sexta, sem esperar segunda
        self.assertTrue(self.d(a)["atraso_avisado"])

    def test_T32_a_poda_nunca_derruba_a_versao_de_demanda_ativa(self):
        """[T32] com 51+ versões usadas por demandas ativas, nenhuma versão em uso some (o teto de 50 vale só para as sem uso).

        Cada salvar com uma demanda ativa na versão anterior mantém essa versão; ao passar de 50, a poda
        (`[:-MAX["versoes"]]` em `api._agenda_salvar`) apaga as versões mais velhas mesmo com demanda ativa nelas, e
        essas demandas passam a medir em tempo corrido (`grade_de` → None) sem aviso.
        """
        for i in range(52):
            self.liga(feriados=[{"data": (datetime.date(2027, 1, 1) + datetime.timedelta(days=i)).isoformat(), "nome": "f", "setores": []}])
            self.nova(est=60)
        doc = self.disco()
        ativas = {str(d["agenda_v"]) for d in doc["demandas"] if calc.ativa(d)}
        self.assertEqual(len(ativas), 52)
        self.assertEqual(ativas - set(doc["agendas"]), set())                # mas nenhuma versão em uso pode sumir


class Reatribuicao(Base):
    SETORES = {"ESP": {"dias": [6], "turnos": [["06:00", "10:00"]]}}

    def test_T47_reatribuir_para_setor_de_mesma_grade_mantem_a_invariante(self):
        """[T47] CNC → PCP (ambos no padrão): `prazo_em` segue válido: util(criado, prazo) == est."""
        self.liga(setores=self.SETORES)
        a = self.nova(est=60)
        self.t = SEX + 16 * HORA + 45 * MIN
        self.adm("demanda/reatribuir", {"id": a, "s": "PCP", "p": None, "nota": ""})
        d, agendas = self.medida(a)
        self.assertEqual(d["para"]["s"], "PCP")
        self.assertEqual(ag.util_entre(calc.grade_de(d, agendas), d["criado"], calc.prazo(d)), d["est"] * MIN)

    def test_T47b_reatribuir_entre_setores_mantem_o_prazo_e_a_grade_do_setor_da_criacao(self):
        """[T47] o prazo continua o calculado no CNC e a medida segue na grade do CNC (`agenda_s`)."""
        self.liga(setores=self.SETORES)
        a = self.nova(est=60)
        prazo = self.d(a)["prazo_em"]
        self.assertEqual(prazo, SEG2_0730)
        self.t = SEX + 16 * HORA + 45 * MIN
        self.adm("demanda/reatribuir", {"id": a, "s": "ESP", "p": None, "nota": ""})
        d, agendas = self.medida(a)
        self.assertEqual((d["para"]["s"], d["prazo_em"], d["agenda_v"]), ("ESP", prazo, 1))
        self.assertEqual(calc.grade_de(d, agendas)["dias"], frozenset({1, 2, 3, 4, 5}))   # a grade do CNC, a da criação

    def test_T47c_known_bug_prazo_e_medida_em_grades_diferentes_apos_reatribuir(self):
        """[T47] BUG B1 (médio): reatribuir entre setores com horários diferentes deixa `prazo_em` e as durações em grades distintas.

        Passos: horário ligado, ESP só trabalha sábado 06–10; demanda de 60 min criada sexta 16:30 no CNC (prazo seg
        07:30); sexta 16:45 o ADM reatribui para o ESP. Esperado: prazo e medidas na mesma grade, de modo que no
        prazo o tempo útil gasto seja a estimativa (SLA 100%). Obtido: o tempo útil do ESP entre a criação e o prazo
        é 240 min (sábado 06–10) para uma demanda de 60 min — no sábado 10:00 o SLA já é 400% e ela ainda não está
        atrasada; na prática o aviso de atraso só dispara na segunda 07:30. Suspeita: `api._reatribuir` não recalcula
        `prazo_em` (api.py ~l.545) enquanto `calc.grade_de` lê `para.s`.
        """
        self.liga(setores=self.SETORES)
        a = self.nova(est=60)
        self.t = SEX + 16 * HORA + 45 * MIN
        self.adm("demanda/reatribuir", {"id": a, "s": "ESP", "p": None, "nota": ""})
        d, agendas = self.medida(a)
        self.assertEqual(ag.util_entre(calc.grade_de(d, agendas), d["criado"], calc.prazo(d)), d["est"] * MIN)

    def test_T48_pausa_antes_da_reatribuicao_pelo_fluxo_completo(self):
        """[T48] aceita, pausa e reatribui: a pausa fecha no instante da reatribuição; depois de reaceita, a execução não a desconta."""
        self.liga()
        self.t = SEG2 + 8 * HORA
        a = self.nova(est=240)
        self.t = SEG2 + 9 * HORA
        self.pes(self.tk_c, "demanda/aceitar", {"id": a})
        self.t = SEG2 + 10 * HORA
        self.pes(self.tk_c, "demanda/pausar", {"id": a, "motivo": "Máquina parada", "obs": ""})
        self.t = SEG2 + 10 * HORA + 30 * MIN
        self.adm("demanda/reatribuir", {"id": a, "s": "ESP", "p": None, "nota": ""})
        d = self.d(a)
        self.assertEqual((d["status"], d["iniciado"], d["pausas"][0]["fim"]), ("new", None, SEG2 + 10 * HORA + 30 * MIN))
        self.assertEqual(self.vd(a)["execucao"], 0.0)
        self.t = SEG2 + 11 * HORA
        self.pes(self.tk_f, "demanda/aceitar", {"id": a})
        self.t = SEG2 + 12 * HORA            # fecha exatamente às 12:00: o fecho não conta
        self.pes(self.tk_f, "demanda/concluir", {"id": a})
        u = self.d(a)["util"]
        self.assertEqual((u["espera"], u["execucao"], u["pausado"], u["total"]), (180 * MIN, 60 * MIN, 30 * MIN, 240 * MIN))
        # a pausa de antes da reatribuição fica dentro da espera nova e também em "pausado": a soma passa do total
        self.assertEqual(u["espera"] + u["execucao"] + u["pausado"] - u["total"], 30 * MIN)


class Tick(Base):
    def test_T50_tick_marca_no_prazo_util_exato_mais_1ms_e_uma_vez(self):
        """[T50] A (prazo 07:30) e B (08:30): nada antes do prazo de cada uma; marca no ms seguinte; não repete."""
        self.liga()
        a, b = self.nova(est=60), self.nova(est=120)
        pa, pb = self.d(a)["prazo_em"], self.d(b)["prazo_em"]
        self.assertEqual((pa, pb), (SEG2_0730, SEG2 + 8 * HORA + 30 * MIN))
        for quando in (SEX + 20 * HORA, SAB + 12 * HORA, DOM + 3 * HORA, SEG2 + 7 * HORA, pa - 1, pa):
            self.assertFalse(api.tick(quando), quando)
        self.assertTrue(api.tick(pa + 1))
        self.assertEqual((self.d(a)["atraso_avisado"], self.d(b)["atraso_avisado"]), (True, False))
        self.assertFalse(api.tick(pa + 2))                                           # a mesma demanda não avisa de novo
        self.assertFalse(api.tick(pb))
        self.assertTrue(api.tick(pb + 1))
        self.assertTrue(self.d(b)["atraso_avisado"])
        self.assertEqual((len(self.eventos(a, "late")), len(self.eventos(b, "late"))), (1, 1))
        notas = [n for n in self.disco()["notas"] if n["tipo"] == "late"]
        self.assertEqual(sorted(n["aud"] for n in notas if n["dem"] == a), ["CNC", "adm"])

    def test_T51_tick_nao_conta_o_tempo_corrido_da_estimativa(self):
        """[T51] est de 10 h: depois de 10 h corridas (sábado de manhã) a demanda ainda não está atrasada."""
        self.liga()
        a = self.nova(est=600)
        self.assertFalse(api.tick(SEX_1630 + 10 * HORA + 1))                          # passou da estimativa corrida
        self.assertFalse(api.tick(SAB + 12 * HORA))
        self.assertTrue(api.tick(self.d(a)["prazo_em"] + 1))

    def test_T52_tick_ignora_fechadas_e_nao_mexe_no_rev_sem_atraso(self):
        """[T52] concluída e cancelada nunca ganham "late"; tick sem atraso não grava (rev igual); com atraso, rev+1."""
        self.liga()
        feita, cancelada, viva = self.nova(est=60), self.nova(est=60), self.nova(est=60)
        self.pes(self.tk_c, "demanda/aceitar", {"id": feita})
        self.pes(self.tk_c, "demanda/concluir", {"id": feita})
        self.adm("demanda/cancelar", {"id": cancelada, "motivo": ""})
        r = self.disco()["rev"]
        self.assertFalse(api.tick(SEG2_0730))
        self.assertEqual(self.disco()["rev"], r)
        self.assertTrue(api.tick(SEG2_0730 + 1))
        self.assertEqual(self.disco()["rev"], r + 1)
        self.assertEqual([self.d(x)["atraso_avisado"] for x in (feita, cancelada, viva)], [False, False, True])

    def test_T53_feriado_adia_o_atraso(self):
        """[T53] feriado geral na segunda: o prazo cai na terça 07:30 e o tick só avisa depois dele."""
        self.liga(feriados=[{"data": "2026-11-16", "nome": "x", "setores": []}])
        a = self.nova(est=60)
        self.assertEqual(self.d(a)["prazo_em"], ms(2026, 11, 17, 7, 30))
        self.assertFalse(api.tick(SEG2 + 12 * HORA))
        self.assertFalse(api.tick(ms(2026, 11, 17, 7, 30)))
        self.assertTrue(api.tick(ms(2026, 11, 17, 7, 30) + 1))

    def test_T54_demanda_noturna_atrasa_so_dentro_do_turno(self):
        """[T54] setor no turno 22→06: criada às 21:00 de segunda (est 120) vence na terça 00:00; tick no ms seguinte."""
        self.liga(setores={"SLD": {"dias": [1, 2, 3, 4, 5], "turnos": [["22:00", "06:00"]]}})
        self.t = SEG2 + 21 * HORA
        a = self.nova(est=120, setor="SLD")
        self.assertEqual(self.d(a)["prazo_em"], TER2)
        self.assertFalse(api.tick(TER2))
        self.assertTrue(api.tick(TER2 + 1))


class ConcluidaForaDoExpediente(Base):
    def test_T49_known_bug_concluida_depois_do_prazo_fora_do_expediente_diz_no_prazo(self):
        """[T49] BUG B4 (baixo): concluída fora do expediente depois do prazo é "atrasou" para o KPI e "no prazo" no cartão.

        Passos: horário ligado; demanda de 30 min criada sexta 16:30 (prazo sexta 17:00, o fecho); o responsável
        aceita às 16:40 e conclui no sábado 10:00. Esperado: as duas leituras concordarem. Obtido: `atrasou_concluida`
        é True (fim > prazo: conta como atrasada no crono, SLA do setor e barra vermelha) mas `util.atraso` é 0, e a
        tela escreve "Concluída … · no prazo". Suspeita: `calc.atrasou_concluida` compara o relógio, `calc.congela`
        mede o atraso em tempo útil (demandas_calc.py ~l.132 e ~l.139).
        """
        self.liga()
        a = self.nova(est=30)
        self.t = SEX + 16 * HORA + 40 * MIN
        self.pes(self.tk_c, "demanda/aceitar", {"id": a})
        self.t = SAB + 10 * HORA
        self.pes(self.tk_c, "demanda/concluir", {"id": a})
        d, agendas = self.medida(a)
        self.assertEqual(d["util"]["atraso"], 0)
        self.assertEqual(calc.atrasou_concluida(d), self.vd(a)["atraso"] > 0)

    def test_T49b_concluida_no_prazo_dentro_do_expediente_e_coerente(self):
        """[T49] (controle, passa) concluída 1 min depois do prazo, dentro do turno: atraso 1,0 e atrasou_concluida True."""
        self.liga()
        self.t = SEG2 + 7 * HORA
        a = self.nova(est=30)
        self.pes(self.tk_c, "demanda/aceitar", {"id": a})
        self.t = SEG2 + 7 * HORA + 31 * MIN
        self.pes(self.tk_c, "demanda/concluir", {"id": a})
        d, _ = self.medida(a)
        self.assertEqual((self.vd(a)["atraso"], calc.atrasou_concluida(d)), (1.0, True))
        self.assertEqual(d["util"]["atraso"], MIN)


class Migracao(Base):
    def escreve(self, doc):
        (self.dir / "demandas.json").write_text(json.dumps(doc), encoding="utf-8")
        ds._CACHE.update(key=None, texto=None)

    def antigo(self, v):
        self.nova(est=60)
        doc = self.disco()
        for k in ("agenda", "agendas"):
            doc.pop(k)
        for d in doc["demandas"]:
            for k in ("agenda_v", "prazo_em"):
                d.pop(k, None)
        doc["v"] = v
        self.escreve(doc)
        return doc

    def confere_migracao(self, v):
        self.antigo(v)
        vista = self.adm("vista")
        self.assertEqual(vista["agenda"], ag.padrao())
        self.assertEqual(vista["agendas"], {})
        d = vista["demandas"][0]
        self.assertEqual(d["prazo"], d["criado"] + 60 * MIN)
        self.assertNotIn("agenda_v", d)
        self.assertEqual(self.disco()["v"], 2)
        self.assertTrue((self.dir / ("demandas.json.v%d.bak" % v)).exists())
        self.t = SAB + 12 * HORA
        self.assertEqual(self.vd(d["id"])["total"], 19.5 * 60)       # corrido: sex 16:30 a sáb 12:00

    def test_T39_migra_v1_para_v2_sem_horario_e_guarda_a_copia(self):
        """[T39] arquivo v1: vira v2, agenda desligada de fábrica, `.v1.bak` guardado; a demanda mede em tempo corrido."""
        self.confere_migracao(1)

    def test_T39a_migra_v0_para_v2(self):
        """[T39] arquivo sem versão (v0) também vira v2 e guarda `.v0.bak`."""
        self.confere_migracao(0)

    def test_T39b_recusa_arquivo_v3_sem_mexer_nele(self):
        """[T39] arquivo gravado por versão mais nova (v3): 500 com a frase para a tela e o arquivo fica como está."""
        self.nova(est=60)
        doc = self.disco()
        doc["v"] = 3
        doc["agenda"]["campo_do_futuro"] = True
        self.escreve(doc)
        antes = (self.dir / "demandas.json").read_bytes()
        for rest in ("vista", "demanda/criar"):
            with self.assertRaises(api.ApiError) as c:
                self.adm(rest, {"titulo": "Cortar chapas", "tipo": "dem", "motivo": "Outro", "prio": "norm", "est": 60,
                                "para": {"s": "CNC", "p": None}, "desc": "", "de_s": "PCP"})
            self.assertEqual(c.exception.status, 500, rest)
            self.assertIn("versão mais nova", str(c.exception), rest)
        self.assertEqual((self.dir / "demandas.json").read_bytes(), antes)

    def test_T39c_agenda_ilegivel_volta_desligada_e_a_demanda_cai_no_corrido(self):
        """[T39] `agenda` corrompida no arquivo: carrega desligada; `agenda_v` sem a versão → tempo corrido, sem derrubar a tela."""
        self.liga()
        a = self.nova(est=60)
        doc = self.disco()
        doc["agenda"] = {"ativa": "sim"}
        doc["agendas"] = {"1": {"ativa": "sim"}, "x": cfg(), "2": cfg(v=2)}
        self.escreve(doc)
        v = self.adm("vista")
        self.assertEqual(v["agenda"], ag.padrao())
        self.assertEqual(sorted(ds.load()["agendas"]), ["2"])                    # só sobra a versão legível e numérica
        self.assertIsNone(calc.grade_de(self.d(a), ds.load()["agendas"]))      # a versão 1 estava ilegível: some
        self.t = SAB + 12 * HORA
        self.assertEqual(self.vd(a)["total"], 19.5 * 60)                        # corrido

    def test_T39d_ao_carregar_so_ficam_as_50_versoes_mais_novas(self):
        """[T39] arquivo com 53 versões guardadas: o carregamento fica com as 50 maiores (números 4 a 53)."""
        doc = self.disco()
        doc["agendas"] = {str(i): cfg(v=i) for i in range(1, 54)}
        self.escreve(doc)
        self.assertEqual(sorted(ds.load()["agendas"], key=int), [str(i) for i in range(4, 54)])


# ---------------------------------------------------------------------------------------------------------------
# Horário de verão simulado e vetores de paridade (a TZ do processo é trocada num subprocesso)
# ---------------------------------------------------------------------------------------------------------------

# alias -> TZ do Python (POSIX, a única que o Windows entende) e TZ do Node (IANA); "dst" = regras dos EUA, como o
# runtime de C do Windows as aplica: 8/3/2026 (23 h) e 1/11/2026 (25 h).
TZ_PY = {"semdst": "BRT3", "dst": "EST5EDT"}
TZ_JS = {"semdst": "Etc/GMT+3", "dst": "EST5EDT"}

SUB = r'''
import datetime, json, sys
sys.path.insert(0, sys.argv[1])
import demandas_agenda as ag
MIN = 60000


def ms(c, off=0):
    y, m, d, h, mi = (list(c) + [0] * 5)[:5]
    return int(datetime.datetime(y, m, d, h, mi).timestamp() * 1000) + off


def local(t):
    x = datetime.datetime.fromtimestamp(t / 1000)
    return [x.year, x.month, x.day, x.hour, x.minute, x.second]


dados = json.load(sys.stdin)
saida = []
for q in dados["consultas"]:
    g = ag.grade(ag.normaliza(dados["agendas"][q["agenda"]]), q["setor"])
    a, op = ms(q["de"], q.get("de_off", 0)), q["op"]
    b = ms(q["ate"], q.get("ate_off", 0)) if "ate" in q else None
    if op == "util":
        r = ag.util_entre(g, a, b)
    elif op == "expediente":
        r = [[x - a, y - a] for x, y in ag.expediente(g, a, b)]
    elif op == "aberto":
        r = ag.aberto(g, a)
    elif op == "soma":
        try:
            f = ag.soma_util(g, a, q["min"])
            r = {"dur": f - a, "local": local(f)}
        except ValueError:
            r = "erro"
    elif op == "ida_e_volta":
        try:
            f = ag.soma_util(g, a, q["min"])
            r = [ag.util_entre(g, a, f) - q["min"] * MIN, ag.util_entre(g, a, f - 1) - (q["min"] * MIN - 1)]
        except ValueError:
            r = "erro"
    elif op == "aditiva":
        c = ms(q["meio"], q.get("meio_off", 0))
        r = ag.util_entre(g, a, b) - ag.util_entre(g, a, c) - ag.util_entre(g, c, b)
    saida.append(r)
print(json.dumps(saida))
'''


def avalia(alias, agendas, consultas):
    """Roda as consultas no Python com a TZ do alias e devolve os resultados (um por consulta)."""
    env = {**os.environ, "TZ": TZ_PY[alias]}
    p = subprocess.run([sys.executable, "-c", SUB, str(HERE)], input=json.dumps({"agendas": agendas, "consultas": consultas}),
                       capture_output=True, text=True, encoding="utf-8", env=env, timeout=600)
    if p.returncode:
        raise AssertionError("subprocesso (%s) falhou:\n%s" % (alias, p.stderr[-2000:]))
    return json.loads(p.stdout)


def q(agenda, op, de, **kw):
    return {"agenda": agenda, "setor": kw.pop("setor", "CNC"), "op": op, "de": de, **kw}


AG_VERAO = {
    "noite_sabado": cfg(padrao={"dias": [6], "turnos": [["22:00", "06:00"]]}),
    "dia_24h": cfg(padrao={"dias": [1, 2, 3, 4, 5, 6, 7], "turnos": [["00:00", "12:00"], ["12:00", "00:00"]]}),
    "domingo_curto": cfg(padrao={"dias": [7], "turnos": [["01:00", "04:00"]]}),
    "domingo_no_vazio": cfg(padrao={"dias": [7], "turnos": [["02:30", "03:30"]]}),
    "comercial": cfg(),
}


class HorarioDeVerao(unittest.TestCase):
    """A máquina do dono está num fuso sem horário de verão, mas o cálculo usa a hora local: se a TZ tiver, o dia de
    23 h ou de 25 h tem de contar como é (a regra: tempo útil = tempo decorrido real dentro do turno)."""

    def corre(self, alias, consulta):
        return avalia(alias, AG_VERAO, [consulta])[0]

    def test_T90_turno_da_noite_na_virada_para_o_horario_de_verao_tem_7_horas(self):
        """[T90] sáb 7/3 22:00 → dom 8/3 06:00 pula a hora 02→03: 7 h reais (8 h sem horário de verão)."""
        c = q("noite_sabado", "util", [2026, 3, 7, 22, 0], ate=[2026, 3, 8, 6, 0])
        self.assertEqual(self.corre("dst", c), 7 * HORA)
        self.assertEqual(self.corre("semdst", c), 8 * HORA)
        soma = q("noite_sabado", "soma", [2026, 3, 7, 22, 0], min=480)
        self.assertEqual(self.corre("dst", soma)["local"][:5], [2026, 3, 14, 23, 0])      # 7 h na noite + 1 h no sábado seguinte
        self.assertEqual(self.corre("semdst", soma)["local"][:5], [2026, 3, 8, 6, 0])

    def test_T91_turno_da_noite_na_volta_do_horario_de_verao_tem_9_horas(self):
        """[T91] sáb 31/10 22:00 → dom 1/11 06:00 repete a hora 01→02: 9 h reais."""
        c = q("noite_sabado", "util", [2026, 10, 31, 22, 0], ate=[2026, 11, 1, 6, 0])
        self.assertEqual(self.corre("dst", c), 9 * HORA)
        self.assertEqual(self.corre("semdst", c), 8 * HORA)
        soma = q("noite_sabado", "soma", [2026, 10, 31, 22, 0], min=540)
        self.assertEqual(self.corre("dst", soma)["local"][:5], [2026, 11, 1, 6, 0])

    def test_T92_dia_de_24_horas_de_expediente_tem_o_tamanho_real_do_dia(self):
        """[T92] expediente 24 h: o dia da virada tem 23 h (primavera) e 25 h (outono); 24 h de trabalho avançam 25 h/23 h no relógio."""
        d = lambda y, m, dia: q("dia_24h", "util", [y, m, dia, 0, 0], ate=[y, m, dia + 1, 0, 0])   # noqa: E731
        self.assertEqual(self.corre("dst", d(2026, 3, 8)), 23 * HORA)
        self.assertEqual(self.corre("dst", d(2026, 11, 1)), 25 * HORA)
        self.assertEqual(self.corre("semdst", d(2026, 3, 8)), 24 * HORA)
        self.assertEqual(self.corre("dst", q("dia_24h", "soma", [2026, 3, 7, 12, 0], min=1440))["local"][:5], [2026, 3, 8, 13, 0])
        self.assertEqual(self.corre("dst", q("dia_24h", "soma", [2026, 10, 31, 12, 0], min=1440))["local"][:5], [2026, 11, 1, 11, 0])

    def test_T93_turno_que_cobre_a_hora_pulada_tem_a_duracao_real(self):
        """[T93] domingo 01:00–04:00 em 8/3: 2 h reais com horário de verão, 3 h sem; sem erro."""
        c = q("domingo_curto", "util", [2026, 3, 8, 0, 0], ate=[2026, 3, 9, 0, 0])
        self.assertEqual(self.corre("dst", c), 2 * HORA)
        self.assertEqual(self.corre("semdst", c), 3 * HORA)

    def test_T94_turno_inteiro_dentro_da_hora_inexistente_nao_quebra(self):
        """[T94] caracterização: turno 02:30–03:30 em 8/3 (02:30 não existe): resposta entre 0 e 1 h, expediente coerente."""
        c = q("domingo_no_vazio", "util", [2026, 3, 8, 0, 0], ate=[2026, 3, 9, 0, 0])
        r = self.corre("dst", c)
        self.assertTrue(0 <= r <= HORA, r)
        exp = self.corre("dst", q("domingo_no_vazio", "expediente", [2026, 3, 8, 0, 0], ate=[2026, 3, 9, 0, 0]))
        self.assertEqual(sum(y - x for x, y in exp), r)

    def test_T94b_comercial_nao_sente_a_virada(self):
        """[T94] turnos diurnos: o horário de verão não mexe em nada (9 h na segunda 9/3; sexta 16:30 + 60 → seg 07:30)."""
        self.assertEqual(self.corre("dst", q("comercial", "util", [2026, 3, 9, 0, 0], ate=[2026, 3, 10, 0, 0])), 9 * HORA)
        self.assertEqual(self.corre("dst", q("comercial", "soma", [2026, 3, 6, 16, 30], min=60))["local"][:5], [2026, 3, 9, 7, 30])
        self.assertEqual(self.corre("dst", q("comercial", "soma", [2026, 10, 30, 16, 30], min=60))["local"][:5], [2026, 11, 2, 7, 30])

    def test_T94c_propriedades_valem_no_fuso_com_horario_de_verao(self):
        """[T94] soma↔medida (ida e volta) e aditividade em 120 agendas aleatórias com a janela cruzando as duas viradas."""
        rng = random.Random(SEMENTE + 1)
        agendas, consultas = {}, []
        for i in range(120):
            g = gerar_grade(rng)
            agendas["a%d" % i] = g["agenda"]
            base = rng.choice([datetime.date(2026, 3, 5), datetime.date(2026, 10, 29)]) + datetime.timedelta(days=rng.randrange(0, 7))
            de = [base.year, base.month, base.day, rng.randrange(0, 24), rng.randrange(0, 60)]
            fim = base + datetime.timedelta(days=rng.randrange(1, 8))
            meio = base + datetime.timedelta(days=rng.randrange(0, 4))
            consultas.append(q("a%d" % i, "ida_e_volta", de, setor=g["setor"], min=rng.choice([1, 30, 60, 540, 1500])))
            consultas.append(q("a%d" % i, "aditiva", de, setor=g["setor"], ate=[fim.year, fim.month, fim.day, rng.randrange(0, 24), 0],
                               meio=[meio.year, meio.month, meio.day, rng.randrange(0, 24), 0]))
        for alias in ("dst", "semdst"):
            for c, r in zip(consultas, avalia(alias, agendas, consultas)):
                if c["op"] == "ida_e_volta":
                    self.assertIn(r, ([0, 0], "erro"), (alias, c))
                elif ms_ordenado(c):
                    self.assertEqual(r, 0, (alias, c))


def ms_ordenado(c):
    """A aditividade só vale com de <= meio <= ate."""
    return tuple(c["de"]) <= tuple(c["meio"]) <= tuple(c["ate"])


# ---------------------------------------------------------------------------------------------------------------
# Vetores de paridade JS × Python
# ---------------------------------------------------------------------------------------------------------------

def _comp(dia, minutos):
    """[a, m, d, h, mi] de `minutos` desde a meia-noite local de `dia` (passa de 1440 = dia seguinte)."""
    d = dia + datetime.timedelta(days=minutos // 1440)
    r = minutos % 1440
    return [d.year, d.month, d.day, r // 60, r % 60]


def agendas_dos_vetores(rng):
    ag24 = [["06:00", "14:00"], ["14:00", "22:00"], ["22:00", "06:00"]]
    ags = {
        "comercial": cfg(),
        "noturno": cfg(padrao=NOITE),
        "tres_turnos": cfg(padrao={"dias": [1, 2, 3, 4, 5, 6, 7], "turnos": ag24}),
        "manha_tarde_e_noite": cfg(padrao={"dias": [1, 2, 3, 4, 5, 6], "turnos": [["06:00", "12:00"], ["13:00", "17:00"], ["22:00", "02:00"]]}),
        "setor_e_feriados": cfg(setores={"SLD": {"dias": [6], "turnos": [["06:00", "10:00"]]}},
                                feriados=[{"data": "2026-11-16", "nome": "geral"}, {"data": "2026-11-17", "nome": "CNC", "setores": ["CNC"]},
                                          {"data": "2026-11-21", "nome": "SLD", "setores": ["SLD"]}, {"data": "2026-12-25", "nome": "Natal"}]),
        "noturno_com_feriados": cfg(padrao=NOITE, feriados=[{"data": "2026-11-10", "nome": "x"}, {"data": "2026-11-13", "nome": "y", "setores": ["ESP"]}]),
        "madrugada": cfg(padrao={"dias": [1, 2, 3, 4, 5, 6, 7], "turnos": [["00:00", "06:00"]]}),
        "fim_de_semana": cfg(padrao={"dias": [6, 7], "turnos": [["08:00", "20:00"]]}),
        "virada_do_ano": cfg(padrao={"dias": [1, 2, 3, 4, 5], "turnos": [["22:00", "06:00"]]},
                             feriados=[{"data": "2026-12-31", "nome": "x"}, {"data": "2027-01-01", "nome": "y"}]),
    }
    for i in range(6):
        ags["aleatoria%d" % i] = gerar_grade(rng)["agenda"]
    ags.update({n: a for n, a in AG_VERAO.items() if n not in ags})
    return ags


def montar_vetores():
    """As entradas dos vetores (sem as respostas), determinísticas pela semente."""
    rng = random.Random(SEMENTE)
    agendas = agendas_dos_vetores(rng)
    casos = []
    for alias in ("semdst", "dst"):
        for nome, agenda in agendas.items():
            for setor in ("CNC", "SLD", "ESP"):
                g = ag.grade(agenda, setor)
                if alias == "dst":
                    inicio = rng.choice([datetime.date(2026, 3, 4), datetime.date(2026, 10, 28)])
                    dias = 10
                else:
                    inicio, dias = datetime.date(2026, 11, 1), 45
                for _ in range(3):
                    dia = inicio + datetime.timedelta(days=rng.randrange(dias))
                    ate = dia + datetime.timedelta(days=rng.randrange(0, 9))
                    casos.append({"tz": alias, "agenda": nome, "setor": setor, "op": "util",
                                  "de": _comp(dia, rng.randrange(0, 1440, 5)), "ate": _comp(ate, rng.randrange(0, 1440, 5))})
                dia = inicio + datetime.timedelta(days=rng.randrange(dias))
                casos.append({"tz": alias, "agenda": nome, "setor": setor, "op": "expediente",
                              "de": _comp(dia, rng.randrange(0, 1440, 15)), "ate": _comp(dia + datetime.timedelta(days=rng.randrange(1, 5)), rng.randrange(0, 1440, 15))})
                for _ in range(2):
                    casos.append({"tz": alias, "agenda": nome, "setor": setor, "op": "aberto",
                                  "de": _comp(inicio + datetime.timedelta(days=rng.randrange(dias)), rng.randrange(0, 1440, 5))})
                # as bordas do primeiro turno do setor num dia sorteado: 1 ms antes, no ponto e 1 ms depois
                a, b = g["faixas"][0]
                dia = inicio + datetime.timedelta(days=rng.randrange(dias))
                for borda in (a, b):
                    c = _comp(dia, borda)
                    casos.append({"tz": alias, "agenda": nome, "setor": setor, "op": "aberto", "de": c, "de_off": -1})
                    casos.append({"tz": alias, "agenda": nome, "setor": setor, "op": "aberto", "de": c})
                    casos.append({"tz": alias, "agenda": nome, "setor": setor, "op": "util", "de": c, "de_off": -1, "ate": c})
                    casos.append({"tz": alias, "agenda": nome, "setor": setor, "op": "util", "de": c, "ate": c, "ate_off": 1})
    # a virada do horário de verão, com as agendas feitas para ela
    for nome, de, ate in (("noite_sabado", [2026, 3, 7, 22, 0], [2026, 3, 8, 6, 0]), ("noite_sabado", [2026, 10, 31, 22, 0], [2026, 11, 1, 6, 0]),
                          ("dia_24h", [2026, 3, 8, 0, 0], [2026, 3, 9, 0, 0]), ("dia_24h", [2026, 11, 1, 0, 0], [2026, 11, 2, 0, 0]),
                          ("domingo_curto", [2026, 3, 8, 0, 0], [2026, 3, 9, 0, 0]), ("comercial", [2026, 3, 6, 0, 0], [2026, 3, 14, 0, 0])):
        for alias in ("dst", "semdst"):
            casos.append({"tz": alias, "agenda": nome, "setor": "CNC", "op": "util", "de": de, "ate": ate})
            casos.append({"tz": alias, "agenda": nome, "setor": "CNC", "op": "expediente", "de": de, "ate": ate})
    return {"semente": SEMENTE, "tz": TZ_JS, "agendas": agendas, "casos": casos}


def responde_vetores(dados):
    """As respostas do Python para cada caso, na TZ do caso."""
    esp = [None] * len(dados["casos"])
    for alias in ("semdst", "dst"):
        idx = [i for i, c in enumerate(dados["casos"]) if c["tz"] == alias]
        saida = avalia(alias, dados["agendas"], [dados["casos"][i] for i in idx])
        for i, r in zip(idx, saida):
            esp[i] = r
    return esp


def grava_vetores(dados, esp):
    linhas = ['{"semente": %d,' % dados["semente"], ' "tz": %s,' % json.dumps(dados["tz"]), ' "agendas": {']
    nomes = list(dados["agendas"])
    for i, n in enumerate(nomes):
        linhas.append('  %s: %s%s' % (json.dumps(n), json.dumps(dados["agendas"][n], ensure_ascii=False), "," if i < len(nomes) - 1 else ""))
    linhas += [" },", ' "casos": [']
    for i, (c, r) in enumerate(zip(dados["casos"], esp)):
        linhas.append("  %s%s" % (json.dumps({**c, "esp": r}, ensure_ascii=False), "," if i < len(esp) - 1 else ""))
    linhas += [" ]", "}", ""]
    VETORES.write_text("\n".join(linhas), encoding="utf-8")


class Vetores(unittest.TestCase):
    """O arquivo `vetores_qa.json` é a resposta do Python; `check_tempo.js` confere a mesma coisa no jsdom."""

    def test_T100_vetores_do_arquivo_sao_os_que_o_python_gera_e_calcula(self):
        """[T100] entradas == regeradas pela semente; respostas == as do Python agora (nas duas TZ); QA_GERAR_VETORES=1 regrava."""
        novos = montar_vetores()
        if os.environ.get("QA_GERAR_VETORES") == "1":
            grava_vetores(novos, responde_vetores(novos))
        dados = json.loads(VETORES.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(dados["casos"]), 1000)
        self.assertEqual({k: dados[k] for k in ("semente", "tz", "agendas")}, {k: novos[k] for k in ("semente", "tz", "agendas")})
        self.assertEqual([{k: v for k, v in c.items() if k != "esp"} for c in dados["casos"]], novos["casos"])
        esp = responde_vetores(dados)
        for c, r in zip(dados["casos"], esp):
            self.assertEqual(c["esp"], r, c)

    def test_T101_vetores_cobrem_as_operacoes_e_as_duas_tz(self):
        """[T101] há util, expediente e aberto nas duas TZ, com bordas de ±1 ms e respostas verdadeiras e falsas."""
        dados = json.loads(VETORES.read_text(encoding="utf-8"))
        casos = dados["casos"]
        for alias in ("semdst", "dst"):
            for op in ("util", "expediente", "aberto"):
                self.assertGreaterEqual(sum(1 for c in casos if c["tz"] == alias and c["op"] == op), 40, (alias, op))
        abertos = [c["esp"] for c in casos if c["op"] == "aberto"]
        self.assertTrue(any(abertos) and not all(abertos))
        self.assertTrue(any(c["esp"] for c in casos if c["op"] == "util") and any(c["esp"] == 0 for c in casos if c["op"] == "util"))
        self.assertTrue(any(c.get("de_off") == -1 for c in casos) and any(c.get("ate_off") == 1 for c in casos))
        self.assertEqual(dados["tz"], TZ_JS)


if __name__ == "__main__":
    unittest.main()
