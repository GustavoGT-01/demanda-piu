"""Preferências de aviso (estudo 02, fase 4): data/avisos.json, fora do demandas.json.

Fora do banco porque mudar preferência não deve mudar o rev (todas as telas recarregariam) e porque a normalização do
demandas.json descarta chaves novas. O padrão da central vale para quem nunca mexeu em "Meus avisos"; de cada pessoa
(ou do Escritório, chave "adm") só ficam as diferenças, e "Voltar ao padrão" apaga essas diferenças.

Som e vibração são do aparelho (localStorage da tela); aqui ficam só os padrões deles. Eventos, silêncio e "urgente
fura o silêncio" são da pessoa: valem em qualquer aparelho em que ela entrar.
"""
from __future__ import annotations

import json
import re
import threading

import store

# new = escolheram você; fila = nova na fila do seu setor (sem pessoa)
EVENTOS = ("new", "fila", "accepted", "pause", "done", "canc", "nudge", "late", "comment")
SONS = ("curto", "sino", "desligado")
AGRUPAR = (0, 5, 10)
PADRAO = {"eventos": {e: True for e in EVENTOS}, "som": "curto", "vibrar": True, "agrupar_min": 10,
          "silencio": {"ligado": False, "ini": "22:00", "fim": "06:00"}, "urgente_fura": True}
DA_PESSOA = ("eventos", "silencio", "urgente_fura")   # o resto é do aparelho ou só da central
CHAVE_RE = re.compile(r"^(adm|[A-Za-z0-9_-]{1,40})$")
HORA_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")

LOCK = threading.Lock()   # só o avisos.json; nunca junto com o LOCK do banco


class AvisoErro(Exception):
    def __init__(self, status: int, msg: str):
        self.status = status
        super().__init__(msg)


def _path():
    return store.data_dir() / "avisos.json"


def _le() -> dict:
    try:
        raw = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}   # sem arquivo ou ilegível: todo mundo no padrão
    return raw if isinstance(raw, dict) else {}


def _copia(d: dict) -> dict:
    return json.loads(json.dumps(d))


def _campos(raw, base: dict, chaves, estrito: bool) -> dict:
    """base com os campos válidos de raw por cima. estrito: campo inválido = erro 400; senão é ignorado."""
    out = _copia(base)

    def ruim(msg):
        if estrito:
            raise AvisoErro(400, msg)

    if not isinstance(raw, dict):
        ruim("Pedido inválido.")
        return out
    if "eventos" in chaves and "eventos" in raw:
        ev = raw["eventos"]
        if not isinstance(ev, dict) or any(k in ev and not isinstance(ev[k], bool) for k in EVENTOS):
            ruim("Eventos inválidos.")
        if isinstance(ev, dict):
            out["eventos"].update({k: ev[k] for k in EVENTOS if isinstance(ev.get(k), bool)})
    if "silencio" in chaves and "silencio" in raw:
        s = raw["silencio"]
        ok = (isinstance(s, dict) and isinstance(s.get("ligado", False), bool)
              and all(HORA_RE.fullmatch(s[k]) if isinstance(s.get(k), str) else k not in s for k in ("ini", "fim")))
        if not ok:
            ruim("Horário de silêncio inválido: use HH:MM.")
        else:
            out["silencio"].update({k: s[k] for k in ("ligado", "ini", "fim") if k in s})
    for k, ok, msg in (("urgente_fura", lambda v: isinstance(v, bool), "Opção do urgente inválida."),
                       ("vibrar", lambda v: isinstance(v, bool), "Opção de vibração inválida."),
                       ("som", lambda v: v in SONS, "Som inválido."),
                       ("agrupar_min", lambda v: not isinstance(v, bool) and v in AGRUPAR, "Agrupamento inválido.")):
        if k in chaves and k in raw:
            if ok(raw[k]):
                out[k] = raw[k]
            else:
                ruim(msg)
    return out


def _padrao(raw: dict) -> dict:
    return _campos(raw.get("padrao"), PADRAO, PADRAO, estrito=False)


def _diferencas(prefs: dict, padrao: dict) -> dict:
    """Só o que difere do padrão (por evento e por campo do silêncio). Vazio = a pessoa está no padrão."""
    out = {}
    ev = {k: v for k, v in prefs["eventos"].items() if v != padrao["eventos"][k]}
    if ev:
        out["eventos"] = ev
    si = {k: v for k, v in prefs["silencio"].items() if v != padrao["silencio"][k]}
    if si:
        out["silencio"] = si
    if prefs["urgente_fura"] != padrao["urgente_fura"]:
        out["urgente_fura"] = prefs["urgente_fura"]
    return out


def _chave(chave) -> str:
    if not isinstance(chave, str) or not CHAVE_RE.fullmatch(chave):
        raise AvisoErro(400, "Pessoa inválida.")
    return chave


def _grava(raw: dict) -> None:
    store.atomic_write(_path(), json.dumps(dict(raw, v=1), ensure_ascii=False))


def padrao() -> dict:
    """Padrões da central (seção Avisos das Configurações)."""
    with LOCK:
        return _padrao(_le())


def salvar_padrao(body) -> dict:
    """Só os campos enviados mudam. Quem tinha diferenças continua com elas."""
    with LOCK:
        raw = _le()
        novo = _campos(body, _padrao(raw), PADRAO, estrito=True)
        raw["padrao"] = novo
        _grava(raw)
        return novo


def de(chave: str) -> dict:
    """O que vale para esta pessoa ("adm" = o Escritório): o padrão com as diferenças dela por cima, e "proprio" =
    se ela tem alguma diferença guardada."""
    chave = _chave(chave)
    with LOCK:
        raw = _le()
        pessoas = raw.get("pessoas") if isinstance(raw.get("pessoas"), dict) else {}
        dif = pessoas.get(chave)
        out = _campos(dif, _padrao(raw), DA_PESSOA, estrito=False)
    out["proprio"] = bool(_diferencas(out, _padrao(raw)))
    return out


def salvar_de(chave: str, body) -> dict:
    """Grava as preferências da pessoa (só eventos, silêncio e urgente; o resto é ignorado). {"padrao": true} = volta
    ao padrão (apaga as diferenças)."""
    chave = _chave(chave)
    if not isinstance(body, dict):
        raise AvisoErro(400, "Pedido inválido.")
    with LOCK:
        raw = _le()
        base = _padrao(raw)
        pessoas = raw.get("pessoas") if isinstance(raw.get("pessoas"), dict) else {}
        if body.get("padrao") is True:
            dif = {}
        else:
            atual = _campos(pessoas.get(chave), base, DA_PESSOA, estrito=False)
            dif = _diferencas(_campos(body, atual, DA_PESSOA, estrito=True), base)
        if dif:
            pessoas[chave] = dif
        else:
            pessoas.pop(chave, None)
        raw["pessoas"] = pessoas
        _grava(raw)
    return de(chave)
