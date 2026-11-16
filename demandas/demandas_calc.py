"""Demandas: regras de tempo (puras, com `agora` em ms como parâmetro), vista por ator e cronoanálise.

As regras de tempo (espera, execução, pausa, total, cumprimento do prazo, atenção, trechos da linha do tempo,
cronoanálise e feed) vieram portadas de um projeto anterior e hoje vivem aqui. Formatos em CONTRATO.md.
"""

from __future__ import annotations

import datetime

MIN = 60000
HORA = 3600000
DIA = 86400000
ATIVAS = ("new", "prog", "pause")
PESO = {"low": 0, "norm": 1, "high": 2, "urg": 3}
EVL = {"created": "Solicitação criada", "started": "Iniciada",   # "assigned" não entra no feed
       "paused": "Pausada", "resumed": "Retomada", "done": "Concluída", "canc": "Cancelada",
       "reassigned": "Reatribuída", "prio": "Prioridade alterada", "deadline": "Prazo ajustado",
       "nudge": "Cobrança enviada", "late": "Prazo estourado", "attach": "Anexo enviado"}
FEED_N = 14
GANTT_ATIVAS, GANTT_FEITAS = 14, 4
GANTT_ATRAS, GANTT_FRENTE = 10 * HORA, 3 * HORA   # a janela de hoje da linha do tempo
GANTT_MULTI = 120   # teto de linhas do cronograma multidia (o mês cheio encheria a tela)


def dur(m: int) -> str:
    """Minutos por extenso, como o dur() do DEMANDA (vai na nota do evento "deadline")."""
    m = max(0, int(m))
    if m < 60:
        return "%d min" % m
    h, r = divmod(m, 60)
    if h >= 48:
        return "%dd %dh" % divmod(h, 24)
    return "%dh" % h + (" %02dmin" % r if r else "")


def ativa(d: dict) -> bool:
    return d.get("status") in ATIVAS


def prazo(d: dict) -> int:
    return d["criado"] + d["est"] * MIN


def _ou(*vals):
    """Primeiro valor que não é None (o `||` do DEMANDA, sem tratar 0 como vazio)."""
    return next(v for v in vals if v is not None)


def _fim(d: dict, agora: int) -> int:
    return _ou(d.get("fim"), agora)


def _pausas(d: dict, agora: int) -> list:
    """(início, fim) de cada pausa; a aberta vai até o fim da demanda ou agora."""
    out = []
    for p in d.get("pausas") or []:
        ini = p.get("ini")
        if isinstance(ini, int) and not isinstance(ini, bool):
            out.append((ini, _ou(p.get("fim"), d.get("fim"), agora)))
    return out


def pausado_ms(d: dict, agora: int) -> int:
    return sum(max(0, b - a) for a, b in _pausas(d, agora))


def espera_ms(d: dict, agora: int) -> int:
    return max(0, _ou(d.get("iniciado"), d.get("fim"), agora) - d["criado"])


def execucao_ms(d: dict, agora: int) -> int:
    """Do início ao fim, menos as pausas dentro desse trecho (uma pausa de antes de uma reatribuição não conta)."""
    ini = d.get("iniciado")
    if ini is None:
        return 0
    fim = _fim(d, agora)
    parado = sum(max(0, min(b, fim) - max(a, ini)) for a, b in _pausas(d, agora))
    return max(0, fim - ini - parado)


def total_ms(d: dict, agora: int) -> int:
    return max(0, _fim(d, agora) - d["criado"])


def atrasada(d: dict, agora: int) -> bool:
    return ativa(d) and agora > prazo(d)


def atrasou_concluida(d: dict) -> bool:
    return d.get("status") == "done" and d.get("fim") is not None and d["fim"] > prazo(d)


def _min(ms) -> float:
    return round(ms / MIN, 1)


def metricas(d: dict, agora: int) -> dict:
    total = total_ms(d, agora)
    return {"prazo": prazo(d), "atrasada": atrasada(d, agora), "espera": _min(espera_ms(d, agora)),
            "execucao": _min(execucao_ms(d, agora)), "pausado": _min(pausado_ms(d, agora)), "total": _min(total),
            "sla": round(total / MIN / d["est"] * 100, 1) if d["est"] > 0 else None}


# ---------- vista ----------

def _sem_interno(row: dict) -> dict:
    return {k: v for k, v in row.items() if not k.startswith("_") or k == "_rv"}


def publica(d: dict, agora: int) -> dict:
    """Demanda como sai da API: sem campos internos (_p dos anexos), com os derivados de tempo."""
    out = _sem_interno(d)
    out["anexos"] = [{k: v for k, v in a.items() if not k.startswith("_")} for a in d.get("anexos") or []]
    out.update(metricas(d, agora))
    return out


def _com_email(out: dict, row: dict, adm: bool) -> dict:
    """O e-mail só vai para a tela do ADM: a lista de pessoas e setores também chega aos operadores."""
    if adm and isinstance(row.get("email"), str):
        out["email"] = row["email"]
    return out


def pessoa_publica(p: dict, adm: bool = False) -> dict:
    return _com_email({"id": p["id"], "nome": p.get("nome"), "setor": p.get("setor"), "mat": p.get("mat"),
                       "ativo": p.get("ativo", True), "_rv": p.get("_rv", 0)}, p, adm)


def setor_publico(s: dict, adm: bool = False) -> dict:
    return _com_email({"id": s["id"], "nome": s.get("nome"), "icone": s.get("icone"), "cor": s.get("cor"),
                       "ativo": s.get("ativo", True), "_rv": s.get("_rv", 0)}, s, adm)


def ve(d: dict, pessoa: dict) -> bool:
    """Pessoa vê as demandas do setor dela (destino) e as que ela pediu."""
    return d["para"]["s"] == pessoa.get("setor") or d["de"]["p"] == pessoa["id"]


def feed(demandas: list, n: int = FEED_N) -> list:
    """Os n eventos mais recentes (sem "assigned"); no empate, o gravado depois vem antes."""
    evs = []
    for d in demandas:
        for e in d.get("eventos") or []:
            if isinstance(e, dict) and e.get("ev") != "assigned" and isinstance(e.get("t"), int):
                evs.append((e, d["id"]))
    evs.reverse()
    evs.sort(key=lambda x: -x[0]["t"])
    out = []
    for e, did in evs[:n]:
        ev, nota = e.get("ev"), e.get("nota") or ""
        tipo = "warn" if ev in ("paused", "late") else "ok" if ev in ("done", "started") else ""
        msg = did + " · " + EVL.get(ev, str(ev)) + (" (" + nota + ")" if nota and ev != "done" else "")
        out.append({"t": e["t"], "tipo": tipo, "dem": did, "msg": msg})
    return out


def nota_lida(n: dict, pid: str) -> bool:
    """Lida por esta pessoa. Nota de antes dos avisos por pessoa (sem "pid") que o setor já leu conta como lida."""
    return pid in (n.get("lidas") or []) or (n.get("lida") is True and "pid" not in n)


def notas_de(doc: dict, pessoa: dict | None) -> list:
    """O sino de quem vê: ADM, as notas "adm"; pessoa, as do setor dela para o setor todo ou só para ela, com "lida"
    dela. Quem mais leu ("lidas") não sai daqui. Mais novas primeiro."""
    if pessoa is None:
        sel = [dict(n) for n in doc["notas"] if n.get("aud") == "adm"]
    else:
        sel = [dict(n, lida=nota_lida(n, pessoa["id"])) for n in doc["notas"]
               if n.get("aud") == pessoa.get("setor") and n.get("pid") in (None, pessoa["id"])]
    for n in sel:
        n.pop("lidas", None)
    return sorted(sel, key=lambda n: (n.get("t") or 0, n.get("id") or 0), reverse=True)


def vista(doc: dict, agora: int, pessoa: dict | None = None, anexos_uso: dict | None = None) -> dict:
    """pessoa=None: ADM (tudo do principal, notas "adm", uso dos anexos). Pessoa: só o que ela vê."""
    dems = doc["demandas"] if pessoa is None else [d for d in doc["demandas"] if ve(d, pessoa)]
    notas = notas_de(doc, pessoa)
    out = {"rev": doc["rev"], "agora": agora, "papel": "adm" if pessoa is None else "pessoa",
           "eu": None if pessoa is None else {k: pessoa.get(k) for k in ("id", "nome", "setor", "mat")},
           "setores": [setor_publico(s, pessoa is None) for s in doc["setores"]],
           "pessoas": [pessoa_publica(p, pessoa is None) for p in doc["pessoas"]],
           "demandas": [publica(d, agora) for d in dems],
           "notas": notas, "feed": feed(dems)}
    if pessoa is None:
        out["anexos_uso"] = anexos_uso
    return out


# ---------- atenção ----------

def chave_atencao(d: dict, agora: int) -> tuple:
    """sortAtt do DEMANDA: atrasadas primeiro, depois prioridade maior, depois o prazo mais perto."""
    return (not atrasada(d, agora), -PESO.get(d.get("prio"), 1), prazo(d))


def pausa_aberta(d: dict):
    ps = d.get("pausas") or []
    return ps[-1] if ps and ps[-1].get("fim") is None else None


def atencao(demandas: list, agora: int) -> list:
    """Ativas que pedem atenção, com as marcas e a pontuação do DEMANDA (atraso 100, urgente 60,
    pausada há 20 min 40, sem aceite há 25 min 30), da maior pontuação para a menor."""
    out = []
    for d in demandas:
        if not ativa(d):
            continue
        tags, score = [], 0
        if atrasada(d, agora):
            tags.append({"k": "late", "min": _min(agora - prazo(d))})
            score += 100
        if d.get("prio") == "urg":
            tags.append({"k": "urg", "min": None})
            score += 60
        op = pausa_aberta(d)
        if op is not None and isinstance(op.get("ini"), int) and agora - op["ini"] >= 20 * MIN:
            tags.append({"k": "pause", "min": _min(agora - op["ini"])})
            score += 40
        if d.get("status") == "new" and agora - d["criado"] >= 25 * MIN:
            tags.append({"k": "wait", "min": _min(agora - d["criado"])})
            score += 30
        if tags:
            out.append({"id": d["id"], "tags": tags, "score": score})
    out.sort(key=lambda a: -a["score"])
    return out


# ---------- cronoanálise ----------

def segs(d: dict, agora: int) -> list:
    """Trechos da linha do tempo: espera até o início, execução e pausas (segsOf do DEMANDA)."""
    fim = _fim(d, agora)
    ini = d.get("iniciado")
    out = [{"k": "wait", "a": d["criado"], "b": _ou(ini, fim)}]
    if ini is None:
        return out
    cur = ini
    for a, b in sorted(_pausas(d, agora)):
        pe = min(b, fim)
        if pe <= cur:
            continue
        pa = max(a, cur)
        if pa > cur:
            out.append({"k": "exec", "a": cur, "b": pa})
        out.append({"k": "pause", "a": pa, "b": pe})
        cur = pe
    if cur < fim:
        out.append({"k": "exec", "a": cur, "b": fim})
    return out


def inicio_do_dia(agora: int) -> int:
    dt = datetime.datetime.fromtimestamp(agora / 1000).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(dt.timestamp() * 1000)


def _media(vals: list):
    return round(sum(vals) / len(vals) / MIN, 1) if vals else None


def _pct(n: int, de: int):
    return round(n / de * 100) if de else None


def crono(demandas: list, agora: int, dias: int) -> dict:
    desde = inicio_do_dia(agora) if dias == 1 else agora - dias * DIA
    criadas = [d for d in demandas if d["criado"] >= desde]
    feitas = [d for d in demandas if d.get("status") == "done" and d.get("fim") is not None and d["fim"] >= desde]
    no_prazo = sum(1 for d in feitas if not atrasou_concluida(d))

    def resumo(lista):
        return {"espera": _media([espera_ms(d, agora) for d in lista]),
                "execucao": _media([execucao_ms(d, agora) for d in lista]),
                "pausado": _media([pausado_ms(d, agora) for d in lista]),
                "estimado": _media([d["est"] * MIN for d in lista])}

    kpis = {"abertas": len(criadas), "concluidas": len(feitas), "no_prazo": no_prazo,
            "pct_prazo": _pct(no_prazo, len(feitas)), **resumo(feitas)}

    por_setor: dict = {}
    for d in feitas:
        por_setor.setdefault(d["para"]["s"], []).append(d)
    setores = [{"s": s, "n": len(l), **resumo(l), "sla": _pct(sum(1 for d in l if not atrasou_concluida(d)), len(l))}
               for s, l in por_setor.items()]
    setores.sort(key=lambda x: (x["sla"], -x["n"], x["s"]))

    cont: dict = {}
    for d in criadas:
        cont[d.get("motivo")] = cont.get(d.get("motivo"), 0) + 1
    motivos = [{"motivo": m, "n": n} for m, n in sorted(cont.items(), key=lambda x: (-x[1], str(x[0])))[:8]]

    por_pessoa: dict = {}
    for d in feitas:
        if d["para"]["p"] is not None:
            por_pessoa.setdefault(d["para"]["p"], []).append(d)
    ranking = [{"p": p, "n": len(l), "sla": _pct(sum(1 for d in l if not atrasou_concluida(d)), len(l))}
               for p, l in por_pessoa.items()]
    ranking.sort(key=lambda x: (-x["n"], -x["sla"], x["p"]))

    return {"dias": dias, "desde": desde, "kpis": kpis, "setores": setores, "motivos": motivos,
            "ranking": ranking[:6], "gantt": gantt(demandas, agora)}


def _janela(agora: int, ini=None, fim=None) -> tuple:
    """A janela em ms. Sem limites, a de hoje (agora-10h a agora+3h); invertida, ordenada."""
    a = agora - GANTT_ATRAS if ini is None else ini
    b = agora + GANTT_FRENTE if fim is None else fim
    return (a, b) if a <= b else (b, a)


def _na_janela(d: dict, ini: int, fim: int, agora: int) -> bool:
    """A demanda tem o que mostrar nesta janela: o prazo cai dentro, ou algum trecho a cruza."""
    if ini <= prazo(d) <= fim:
        return True
    return any(s["a"] < fim and s["b"] > ini for s in segs(d, agora))


def _linha(d: dict, agora: int, plano: bool = False) -> dict:
    """Uma linha da linha do tempo. `plano` acrescenta a pessoa e a barra criado->prazo, que só o
    cronograma multidia desenha: a linha da janela de hoje mantém exatamente as chaves de sempre."""
    ln = {"id": d["id"], "de": d["de"]["s"], "para": d["para"]["s"], "titulo": d.get("titulo"),
          "segs": segs(d, agora), "prazo": prazo(d),
          "atrasada": atrasada(d, agora) or atrasou_concluida(d), "viva": ativa(d)}
    if plano:
        ln["p"] = d["para"]["p"]
        ln["plano"] = {"a": d["criado"], "b": prazo(d)}
    return ln


def gantt(demandas: list, agora: int, ini=None, fim=None, por=None, limite=None) -> dict:
    """A linha do tempo. Sem `por`: a janela de hoje (agora-10h a agora+3h), com as 14 ativas mais
    urgentes e as 4 concluídas mais recentes nela, pela criação — a saída de sempre, inalterada.

    Com `por` ("setor" ou "pessoa"): o cronograma multidia da janela pedida, agrupado, com no máximo
    `limite` linhas (padrão GANTT_MULTI) e `cortado` dizendo se sobrou gente de fora. Só este modo
    acrescenta `por`, `agora`, `grupos`, `cortado` e, em cada linha, `p` e `plano`.
    """
    ini, fim = _janela(agora, ini, fim)
    if por is None:
        vivas = sorted((d for d in demandas if ativa(d)), key=lambda d: chave_atencao(d, agora))[:GANTT_ATIVAS]
        feitas = sorted((d for d in demandas if d.get("status") == "done" and d.get("fim") is not None and d["fim"] >= ini),
                        key=lambda d: -d["fim"])[:GANTT_FEITAS]
        linhas = [_linha(d, agora) for d in sorted(vivas + feitas, key=lambda d: d["criado"])]
        return {"ini": ini, "fim": fim, "linhas": linhas}
    teto = GANTT_MULTI if limite is None else limite
    elegiveis = [d for d in demandas
                 if (ativa(d) or d.get("status") == "done") and _na_janela(d, ini, fim, agora)]
    # O corte segue a atenção (atrasada e urgente primeiro), nunca a ordem do arquivo.
    escolhidas = sorted(elegiveis, key=lambda d: chave_atencao(d, agora))[:max(0, teto)]
    por_chave: dict = {}
    for d in escolhidas:
        por_chave.setdefault(d["para"]["p"] if por == "pessoa" else d["para"]["s"], []).append(d)
    grupos = [{"chave": k, "n": len(l), "ativas": sum(1 for x in l if ativa(x)),
               "linhas": [_linha(d, agora, plano=True) for d in sorted(l, key=lambda d: d["criado"])]}
              for k, l in por_chave.items()]
    grupos.sort(key=lambda g: (-g["ativas"], -g["n"], str(g["chave"])))
    return {"ini": ini, "fim": fim, "por": por, "agora": agora,
            "cortado": len(elegiveis) > len(escolhidas), "grupos": grupos}
