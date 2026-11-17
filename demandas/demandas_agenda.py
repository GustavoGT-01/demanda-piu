"""Horário de serviço (expediente): funções puras de tempo útil e a validação da configuração.

A configuração (formato em CONTRATO.md) tem um horário padrão, exceções por setor e feriados. `grade` a compila
para um setor; `util_entre` e `soma_util` medem e somam só o tempo dentro dos turnos. Grade None = tempo corrido
(agenda desligada ou demanda de antes do horário): as mesmas funções devolvem o resultado de sempre.
Dias ISO (1 = segunda ... 7 = domingo). Turno que cruza a meia-noite pertence ao dia em que começa.
"""

from __future__ import annotations

import datetime
import re

MIN = 60000
DIA_MS = 86400000
SOMA_DIAS = 400        # quantos dias soma_util procura antes de desistir
MEDE_DIAS = 3700       # teto do percurso de util_entre (uma data absurda não prende o servidor)
SEMANA_MIN = 15        # o horário precisa ter ao menos isto de trabalho por semana (minutos)
LIM = {"feriados": 400, "turnos": 6, "versoes": 50, "nome": 60}
HHMM_RE = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")
DATA_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
SETOR_RE = re.compile(r"^[A-Z0-9]{2,4}$")


def padrao() -> dict:
    """A configuração de fábrica: desligada, com o comercial de segunda a sexta já preenchido para o ADM editar."""
    return {"ativa": False, "v": 0,
            "padrao": {"dias": [1, 2, 3, 4, 5], "turnos": [["07:00", "12:00"], ["13:00", "17:00"]]},
            "setores": {}, "feriados": []}


# ---------- configuração ----------

def _minutos(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


def _faixas(turnos) -> list:
    """Turnos [ini, fim] em minutos desde a meia-noite do dia de início; fim <= ini cruza a meia-noite."""
    out = []
    for ini, fim in turnos:
        a, b = _minutos(ini), _minutos(fim)
        out.append((a, b if b > a else b + 1440))
    return sorted(out)


def _grade_valida(raw, onde: str) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("%s: horário inválido." % onde)
    dias = raw.get("dias")
    if not isinstance(dias, list) or any(isinstance(x, bool) or not isinstance(x, int) or not 1 <= x <= 7 for x in dias):
        raise ValueError("%s: dias da semana inválidos." % onde)
    turnos = raw.get("turnos")
    if not isinstance(turnos, list) or len(turnos) > LIM["turnos"]:
        raise ValueError("%s: no máximo %d turnos." % (onde, LIM["turnos"]))
    limpos = []
    for t in turnos:
        if not (isinstance(t, list) and len(t) == 2 and all(isinstance(x, str) and HHMM_RE.match(x) for x in t)):
            raise ValueError("%s: horário do turno inválido (use HH:MM)." % onde)
        if t[0] == t[1]:
            raise ValueError("%s: o turno não pode começar e terminar na mesma hora." % onde)
        limpos.append([t[0], t[1]])
    dias = sorted(set(dias))
    # nenhum turno pode se sobrepor a outro, nem o da noite ao da manhã seguinte (a semana é circular)
    marcas = sorted(((d - 1) * 1440 + a, (d - 1) * 1440 + b) for d in dias for a, b in _faixas(limpos))
    semana = 7 * 1440
    for i, (_, b) in enumerate(marcas):
        prox = marcas[i + 1][0] if i + 1 < len(marcas) else marcas[0][0] + semana
        if b > prox:
            raise ValueError("%s: dois turnos se sobrepõem." % onde)
    return {"dias": dias, "turnos": sorted(limpos)}


def _trabalho_semana(g: dict) -> int:
    return len(g["dias"]) * sum(b - a for a, b in _faixas(g["turnos"]))


def normaliza(raw, setores=None) -> dict:
    """A configuração limpa e ordenada, ou ValueError com a frase para a tela. `setores` (ids existentes) confere as
    exceções e os feriados por setor; None não confere. `v` segue como veio: quem versiona é a API."""
    if not isinstance(raw, dict):
        raise ValueError("Horário inválido.")
    ativa = raw.get("ativa")
    if not isinstance(ativa, bool):
        raise ValueError("Informe se o horário de serviço está ligado.")
    v = raw.get("v")
    out = {"ativa": ativa, "v": v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0,
           "padrao": _grade_valida(raw.get("padrao"), "Horário padrão"), "setores": {}, "feriados": []}
    exc = raw.get("setores") if raw.get("setores") is not None else {}
    if not isinstance(exc, dict):
        raise ValueError("Horários por setor inválidos.")
    for sid, g in exc.items():
        if not isinstance(sid, str) or not SETOR_RE.match(sid) or (setores is not None and sid not in setores):
            raise ValueError("Setor inválido no horário por setor.")
        out["setores"][sid] = _grade_valida(g, "Setor " + sid)
    fer = raw.get("feriados") if raw.get("feriados") is not None else []
    if not isinstance(fer, list) or len(fer) > LIM["feriados"]:
        raise ValueError("No máximo %d feriados." % LIM["feriados"])
    vistos = set()
    for f in fer:
        if not isinstance(f, dict) or not isinstance(f.get("data"), str) or not DATA_RE.match(f["data"]):
            raise ValueError("Data de feriado inválida.")
        try:
            datetime.date.fromisoformat(f["data"])
        except ValueError:
            raise ValueError("Data de feriado inválida: %s." % f["data"]) from None
        nome = f.get("nome", "")
        if not isinstance(nome, str) or len(nome.strip()) > LIM["nome"]:
            raise ValueError("Nome de feriado com mais de %d letras." % LIM["nome"])
        ss = f.get("setores", [])
        if not isinstance(ss, list) or any(not isinstance(s, str) or not SETOR_RE.match(s) or
                                           (setores is not None and s not in setores) for s in ss):
            raise ValueError("Setor inválido no feriado de %s." % f["data"])
        chave = (f["data"], tuple(sorted(set(ss))))
        if chave in vistos:
            raise ValueError("Feriado repetido em %s." % f["data"])
        vistos.add(chave)
        out["feriados"].append({"data": f["data"], "nome": nome.strip(), "setores": sorted(set(ss))})
    out["feriados"].sort(key=lambda f: (f["data"], f["setores"]))
    if ativa:
        for onde, g in [("Horário padrão", out["padrao"])] + [("Setor " + s, g) for s, g in out["setores"].items()]:
            if _trabalho_semana(g) < SEMANA_MIN:
                raise ValueError("%s: precisa de ao menos %d minutos de trabalho por semana." % (onde, SEMANA_MIN))
    return out


def sem_versao(ag: dict) -> dict:
    """A configuração sem o número da versão (para saber se salvar mudou algo)."""
    return {k: v for k, v in ag.items() if k != "v"}


# ---------- tempo útil ----------

def grade(ag, setor):
    """A grade compilada do setor, ou None (tempo corrido) se não há agenda ou ela está desligada."""
    if not isinstance(ag, dict) or not ag.get("ativa"):
        return None
    base = (ag.get("setores") or {}).get(setor) or ag["padrao"]
    fer = {f["data"] for f in ag.get("feriados") or [] if not f.get("setores") or setor in f["setores"]}
    return {"dias": frozenset(base["dias"]), "faixas": tuple(_faixas(base["turnos"])), "fer": frozenset(fer)}


def _ms(dia: datetime.date, minutos: int) -> int:
    """O instante (ms) de `minutos` desde a meia-noite local de `dia`; passa de 1440 = dia seguinte. Montado pela
    data local, então um dia de horário de verão não escorrega uma hora."""
    d = dia + datetime.timedelta(days=minutos // 1440)
    r = minutos % 1440
    return int(datetime.datetime(d.year, d.month, d.day, r // 60, r % 60).timestamp() * 1000)


def _dia(ms: int) -> datetime.date:
    return datetime.datetime.fromtimestamp(ms / 1000).date()


def _blocos(g: dict, a: int, b: int, dias: int):
    """Os turnos (ini, fim) em ms que podem tocar [a, b), em ordem. Começa um dia antes: o turno da véspera pode
    atravessar a meia-noite até `a`. No máximo `dias` + 2 dias de percurso."""
    d = _dia(a) - datetime.timedelta(days=1)
    ultimo = _dia(b)
    for _ in range(dias + 2):
        if d > ultimo:
            return
        if d.isoweekday() in g["dias"] and d.isoformat() not in g["fer"]:
            for ini, fim in g["faixas"]:
                yield _ms(d, ini), _ms(d, fim)
        d += datetime.timedelta(days=1)


def util_entre(g, a: int, b: int) -> int:
    """Milissegundos de trabalho entre a e b (0 se b <= a). Grade None: o tempo corrido."""
    if b <= a:
        return 0
    if g is None:
        return b - a
    b = min(b, a + MEDE_DIAS * DIA_MS)
    total = 0
    for s, e in _blocos(g, a, b, MEDE_DIAS):
        s, e = max(s, a), min(e, b)
        if e > s:
            total += e - s
    return total


def soma_util(g, ini: int, minutos) -> int:
    """O instante em que `minutos` de trabalho se completam a partir de `ini` (se já está no expediente, conta dali;
    se está fora, conta da próxima abertura). Grade None: ini + minutos. ValueError se não achar em 400 dias."""
    falta = int(minutos * MIN)
    if g is None or falta <= 0:
        return ini + max(0, falta)
    for s, e in _blocos(g, ini, ini + (SOMA_DIAS + 2) * DIA_MS, SOMA_DIAS):
        s = max(s, ini)
        if e <= s:
            continue
        if e - s >= falta:
            return s + falta
        falta -= e - s
    raise ValueError("O horário de serviço não tem trabalho suficiente em %d dias." % SOMA_DIAS)


def expediente(g, a: int, b: int) -> list:
    """Os intervalos [ini, fim] de trabalho dentro de [a, b], já recortados e sem emendas. Grade None: tudo."""
    if g is None:
        return [[a, b]] if b > a else []
    out: list = []
    for s, e in _blocos(g, a, b, min(MEDE_DIAS, max(0, b - a) // DIA_MS + 2)):
        s, e = max(s, a), min(e, b)
        if e <= s:
            continue
        if out and out[-1][1] >= s:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def aberto(g, t: int) -> bool:
    """t está dentro de um turno? Grade None: sempre."""
    return g is None or any(s <= t < e for s, e in _blocos(g, t, t + 1, 1))
