"""Banco das Demandas: data/demandas.json, arquivo morto (demandas-arquivo.json) e anexos (demandas-anexos/).

Formato e limites em CONTRATO.md. load()/commit() não pegam o LOCK: quem chama (api.py) segura o LOCK em toda
leitura+escrita. salvar_anexo pode rodar fora dele (nome inédito, cota sob trava própria).
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import threading
import unicodedata
from pathlib import Path

import demandas_agenda as ag
import store

V = 2
LOCK = threading.Lock()
MAX = {"setores": 60, "pessoas": 500, "demandas": 5000, "arquivo": 50000,
       "pausas": 200, "eventos": 500, "comentarios": 300, "notas": 1000, "cids": 500,
       "feriados": ag.LIM["feriados"], "versoes": ag.LIM["versoes"]}
ANEXO_MAX = 5 * 1024 * 1024
ANEXOS_POR_DEMANDA = 5
COTA = 300 * 1024 * 1024
AID_RE = re.compile(r"^a[0-9a-f]{16}$")
MAGICO = {"jpg": b"\xff\xd8\xff", "png": b"\x89PNG\r\n\x1a\n", "pdf": b"%PDF-"}
NOME_MAX = 120
STATUS = ("new", "prog", "pause", "done", "canc")
FIM = ("done", "canc")
SUB = ("pausas", "eventos", "comentarios", "anexos")
UTIL = ("espera", "execucao", "pausado", "total")
SETOR_RE = re.compile(r"^[A-Z0-9]{2,4}$")
PESSOA_RE = re.compile(r"^p[0-9]{1,9}$")
DEMANDA_RE = re.compile(r"^SOL-([0-9]{1,9})$")


class StoreError(Exception):
    def __init__(self, status: int, msg: str):
        self.status = status
        super().__init__(msg)


def path() -> Path:
    return store.data_dir() / "demandas.json"


def arquivo_path() -> Path:
    return store.data_dir() / "demandas-arquivo.json"


def anexos_dir() -> Path:
    return store.data_dir() / "demandas-anexos"


def empty() -> dict:
    return {"v": V, "rev": 0, "seq": {"pessoa": 0, "demanda": 1000, "nota": 0},
            "setores": [], "pessoas": [], "demandas": [], "notas": [], "cids": [],
            "agenda": ag.padrao(), "agendas": {}}


# ---------- normalização ----------
# Linha ilegível sai sem derrubar a tela; o resto do arquivo segue.

def _int(v, padrao):
    return v if isinstance(v, int) and not isinstance(v, bool) else padrao


def _bool(v, padrao: bool) -> bool:
    return v if isinstance(v, bool) else padrao


def _str(v):
    return v if isinstance(v, str) else None


def _unicos(rows, ok) -> list:
    out, vistos = [], set()
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict) and ok(r.get("id")) and r["id"] not in vistos:
            vistos.add(r["id"])
            out.append(r)
    return out


def _re_ok(rx):
    return lambda v: isinstance(v, str) and rx.fullmatch(v) is not None


def _ponta(v) -> dict | None:
    if not isinstance(v, dict) or not isinstance(v.get("s"), str):
        return None
    return {"s": v["s"], "p": _str(v.get("p"))}


def _demanda(d: dict) -> dict | None:
    de, para = _ponta(d.get("de")), _ponta(d.get("para"))
    if de is None or para is None or d.get("status") not in STATUS:
        return None
    d["de"], d["para"] = de, para
    d["est"] = _int(d.get("est"), 60)
    d["criado"] = _int(d.get("criado"), 0)
    for k in ("iniciado", "fim"):
        d[k] = _int(d.get(k), None)
    d["atraso_avisado"] = _bool(d.get("atraso_avisado"), False)
    for k in ("agenda_v", "prazo_em"):   # só as demandas criadas com o horário de serviço ligado têm
        if _int(d.get(k), None) is None:
            d.pop(k, None)
    if not (isinstance(d.get("agenda_s"), str) and SETOR_RE.fullmatch(d["agenda_s"])):
        d.pop("agenda_s", None)   # o setor cuja grade a demanda usa (o da criação)
    u = d.get("util")   # durações úteis gravadas ao fechar (ms); "atraso" é opcional
    if isinstance(u, dict) and all(_int(u.get(k), None) is not None for k in UTIL):
        d["util"] = {k: u[k] for k in UTIL}
        if _int(u.get("atraso"), None) is not None:
            d["util"]["atraso"] = u["atraso"]
    else:
        d.pop("util", None)
    d["_rv"] = _int(d.get("_rv"), 0)
    for k in SUB:
        rows = d.get(k)
        d[k] = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    d["anexos"] = _unicos(d["anexos"], _re_ok(AID_RE))
    return d


def _demandas(rows) -> list:
    return [d for d in (_demanda(r) for r in _unicos(rows, _re_ok(DEMANDA_RE))) if d is not None]


def _agendas(raw: dict) -> tuple:
    """O horário de serviço vigente e as versões que as demandas em andamento ainda usam. Gravação ilegível não
    derruba a tela: a agenda volta desligada (as demandas com `agenda_v` sem versão medem em tempo corrido)."""
    try:
        atual = ag.normaliza(raw.get("agenda"))
    except ValueError:
        atual = ag.padrao()
    brutas = raw.get("agendas") if isinstance(raw.get("agendas"), dict) else {}
    versoes = {}
    for v, a in brutas.items():
        try:
            if isinstance(v, str) and v.isdigit():
                versoes[v] = ag.normaliza(a)
        except ValueError:
            continue
    return atual, versoes


def _poda_versoes(doc: dict) -> None:
    """No máximo MAX["versoes"] cópias, as mais novas; nunca some uma versão que demanda ativa ainda usa."""
    em_uso = {str(d["agenda_v"]) for d in doc["demandas"] if d.get("status") in ("new", "prog", "pause")
              and d.get("agenda_v") is not None}
    novas = set(sorted(doc["agendas"], key=int)[-MAX["versoes"]:])
    doc["agendas"] = {v: a for v, a in doc["agendas"].items() if v in novas or v in em_uso}


def _normaliza(raw: dict) -> dict:
    doc = empty()
    doc["rev"] = max(0, _int(raw.get("rev"), 0))
    seq = raw.get("seq") if isinstance(raw.get("seq"), dict) else {}
    doc["seq"] = {k: max(0, _int(seq.get(k), padrao)) for k, padrao in doc["seq"].items()}
    for s in _unicos(raw.get("setores"), _re_ok(SETOR_RE)):
        s["ativo"] = _bool(s.get("ativo"), True)
        s["_rv"] = _int(s.get("_rv"), 0)
        doc["setores"].append(s)
    for p in _unicos(raw.get("pessoas"), _re_ok(PESSOA_RE)):
        p["ativo"] = _bool(p.get("ativo"), True)
        p["_rv"] = _int(p.get("_rv"), 0)
        doc["pessoas"].append(p)
    doc["demandas"] = _demandas(raw.get("demandas"))
    for n in _unicos(raw.get("notas"), lambda v: _int(v, None) is not None):
        n["lida"] = _bool(n.get("lida"), False)
        lidas = n.get("lidas")
        n["lidas"] = [x for x in lidas if isinstance(x, str)] if isinstance(lidas, list) else []
        if "pid" in n and not isinstance(n["pid"], str):   # sem "pid" = nota de antes dos avisos por pessoa
            n["pid"] = None
        doc["notas"].append(n)
    doc["agenda"], doc["agendas"] = _agendas(raw)
    _poda_versoes(doc)
    # [chave do pedido, o que ele gravou]: pedido repetido pela tela (resposta perdida) não grava duas vezes
    cids = raw.get("cids") if isinstance(raw.get("cids"), list) else []
    doc["cids"] = [c for c in cids if isinstance(c, list) and len(c) == 2 and all(isinstance(x, str) for x in c)
                   ][-MAX["cids"]:]
    return doc


# ---------- principal ----------

_CACHE: dict = {"key": None, "texto": None}       # texto já normalizado: cada load devolve um doc próprio
_ARQ: dict = {"key": None, "demandas": []}


def _chave(p: Path):
    try:
        st = p.stat()
    except OSError:
        return None
    return (str(p), st.st_mtime_ns, st.st_size)


def _ler(p: Path):
    try:
        return store._read_safe(p)
    except ValueError as exc:   # corrompido e sem .bak válido: o arquivo ruim fica no lugar
        raise StoreError(500, str(exc)) from None


def _migra(raw: dict, de: int) -> None:
    """Grava o formato novo depois de guardar o antigo (demandas.json.v<n>.bak, que nenhuma gravação pisa)."""
    copia = path().with_name("%s.v%d.bak" % (path().name, de))
    if not copia.exists() and path().exists():   # sem o principal, o .bak lido já é a cópia
        shutil.copy2(path(), copia)
    raw["v"] = V   # v0 -> v1 e v1 -> v2 (horário de serviço, desligado por padrão): só ganham o número
    store.atomic_write(path(), json.dumps(raw, ensure_ascii=False))


def load(cache: bool = True) -> dict:
    """Documento normalizado e próprio do chamador (pode alterar e passar ao commit)."""
    key = _chave(path())
    if cache and key is not None and _CACHE["key"] == key:
        return json.loads(_CACHE["texto"])
    raw = _ler(path())
    if not isinstance(raw, dict):
        return empty()   # ausente ou sem forma de objeto: só grava na primeira alteração
    v = _int(raw.get("v"), 0)
    if v > V:   # normalizar descartaria o que esta versão não conhece e o commit gravaria por cima
        raise StoreError(500, "Demandas gravadas por uma versão mais nova da Central de demandas: atualize o programa.")
    if v < V:
        _migra(raw, v)
        key = _chave(path())
    doc = _normaliza(raw)
    texto = json.dumps(doc, ensure_ascii=False)
    _CACHE.update(key=key, texto=texto)
    return json.loads(texto) if cache else doc


def _num(d: dict) -> int:
    m = DEMANDA_RE.fullmatch(str(d.get("id")))
    return int(m.group(1)) if m else 0


def _quando(d: dict):
    """Ordem de saída: a que terminou antes (sem fim, a criação), desempate pelo número."""
    fim = _int(d.get("fim"), None)
    return (_int(d.get("criado"), 0) if fim is None else fim, _num(d))


def _arquivar(doc: dict) -> None:
    """Passou do teto: concluídas/canceladas mais antigas vão para o arquivo morto até 90% do teto (folga para não
    reescrever o arquivo morto a cada demanda nova). Aberta nunca sai."""
    teto = MAX["demandas"]
    if len(doc["demandas"]) <= teto:
        return
    sobra = len(doc["demandas"]) - (teto - teto // 10)
    sai = sorted((d for d in doc["demandas"] if d.get("status") in FIM), key=_quando)[:sobra]
    if not sai:
        return
    ids = {d.get("id") for d in sai}
    velho = [d for d in load_arquivo() if d["id"] not in ids]   # sem repetir: gravação que caiu antes do principal
    novo = sorted(velho + sai, key=_quando)[-MAX["arquivo"]:]   # acima do teto, as mais antigas se perdem
    store.atomic_write(arquivo_path(), json.dumps({"v": V, "demandas": novo}, ensure_ascii=False))  # antes do principal
    _ARQ.update(key=_chave(arquivo_path()), demandas=novo)
    doc["demandas"] = [d for d in doc["demandas"] if d.get("id") not in ids]


def commit(doc: dict) -> dict:
    doc["v"] = V
    doc["rev"] = _int(doc.get("rev"), 0) + 1
    _arquivar(doc)
    texto = json.dumps(doc, ensure_ascii=False)
    store.atomic_write(path(), texto)
    _CACHE.update(key=_chave(path()), texto=texto)
    return doc


def load_arquivo() -> list:
    """Demandas do arquivo morto. Lista compartilhada (cache por mtime): só leitura."""
    key = _chave(arquivo_path())
    if key is not None and _ARQ["key"] == key:
        return _ARQ["demandas"]
    raw = _ler(arquivo_path())
    rows = _demandas(raw.get("demandas")) if isinstance(raw, dict) else []
    _ARQ.update(key=key, demandas=rows)
    return rows


# ---------- anexos ----------

_ANEXOS = threading.Lock()   # cota + gravação: dois envios juntos não passam da cota


def _tipo(dados: bytes):
    return next((t for t, m in MAGICO.items() if dados.startswith(m)), None)


def _limpa_nome(nome, tipo: str) -> str:
    # controle e formatação (ex.: U+202E, que inverte o texto e disfarça a extensão) saem; só vira metadado
    s = "".join(c for c in nome if unicodedata.category(c) not in ("Cc", "Cf")) if isinstance(nome, str) else ""
    s = s.strip()[:NOME_MAX].strip()
    return s or "anexo." + tipo


def uso_anexos() -> dict:
    total = 0
    try:
        itens = list(os.scandir(anexos_dir()))
    except OSError:   # pasta ainda não criada
        itens = []
    for e in itens:
        try:
            if e.is_file():
                total += e.stat().st_size
        except OSError:   # apagado no meio da soma
            pass
    return {"bytes": total, "cota": COTA}


def _publica(tmp: Path, dst: Path) -> None:
    """Sem sobrescrever: link falha se o destino existe; sem link (FAT), rename no Windows também falha."""
    try:
        os.link(tmp, dst)
    except FileExistsError:
        raise
    except OSError:
        os.rename(tmp, dst)
        return
    os.remove(tmp)


def salvar_anexo(dados: bytes, nome: str) -> dict:
    if not isinstance(dados, (bytes, bytearray)):
        raise StoreError(400, "Anexo inválido.")
    if not dados:
        raise StoreError(400, "Anexo vazio.")
    if len(dados) > ANEXO_MAX:
        raise StoreError(413, "Anexo maior que 5 MB.")
    tipo = _tipo(dados)
    if tipo is None:
        raise StoreError(400, "Tipo de arquivo não aceito: use JPG, PNG ou PDF.")
    with _ANEXOS:
        if uso_anexos()["bytes"] + len(dados) > COTA:
            raise StoreError(507, "Espaço dos anexos esgotado (300 MB). Apague anexos antigos.")
        anexos_dir().mkdir(parents=True, exist_ok=True)
        while True:
            aid = "a" + secrets.token_hex(8)
            dst = anexos_dir() / ("%s.%s" % (aid, tipo))
            if any((anexos_dir() / ("%s.%s" % (aid, t))).exists() for t in MAGICO):
                continue
            tmp = store._tmp_file(dst, bytes(dados))
            try:
                _publica(tmp, dst)
            except FileExistsError:
                store._remove(tmp)
                continue
            except OSError:
                store._remove(tmp)
                raise
            break
    return {"id": aid, "nome": _limpa_nome(nome, tipo), "tipo": tipo, "bytes": len(dados)}


def _arquivo_anexo(aid):
    if not isinstance(aid, str) or not AID_RE.fullmatch(aid):
        raise StoreError(404, "Anexo não encontrado.")
    return [(anexos_dir() / ("%s.%s" % (aid, t)), t) for t in MAGICO]


def ler_anexo(aid: str) -> tuple:
    for p, tipo in _arquivo_anexo(aid):
        try:
            dados = p.read_bytes()
        except OSError:
            continue
        if dados.startswith(MAGICO[tipo]):   # arquivo trocado à mão não sai com o tipo errado
            return dados, tipo
    raise StoreError(404, "Anexo não encontrado.")


def apagar_anexo(aid: str) -> None:
    """Some com o arquivo; já apagado não é erro (o api.py apaga órfão sem saber se gravou)."""
    for p, _tipo in _arquivo_anexo(aid):
        store._remove(p)
