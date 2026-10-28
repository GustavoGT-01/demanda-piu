"""Demandas: rotas, autorização e regras (porte de DEMANDA/src/models/requests.js e factory.js).

Contrato em CONTRATO.md. Banco em demandas_store (o LOCK dele é segurado aqui em toda leitura+escrita);
cálculos de tempo e vista em demandas_calc. Pessoa age com um token (tk) que só existe em memória.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
import secrets
import threading
import time
from collections import OrderedDict

import demandas_backup as bk
import demandas_calc as calc
import demandas_store as ds

LOCK = ds.LOCK
CODE_RE = re.compile(r"^[0-9]{4}$")
SAL_RE = re.compile(r"^[0-9a-f]{32}$")
CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
CTRL_NL_RE = re.compile(r"[\x00-\x09\x0b-\x1f\x7f]")   # descrição e comentário aceitam \n
TIPOS = ("dem", "alt", "set", "man", "mat")
MOTIVOS = ("Falta de material", "Quebra de máquina", "Defeito de qualidade", "Mudança de projeto",
           "Ajuste de planejamento", "Retrabalho", "Solicitação do cliente", "Outro")
PAUSAS = ("Aguardando material", "Aguardando outro setor", "Máquina parada", "Aguardando aprovação",
          "Troca de turno ou intervalo", "Informação incompleta")
PRIO = {"low": "Baixa", "norm": "Normal", "high": "Alta", "urg": "Urgente"}
ICONES = ("🗂️", "⚙️", "🔩", "🪵", "🪚", "🧽", "🛠️", "🧵", "✂️", "🪡", "📦", "✅", "🔧", "🏷️", "🚚", "🎨", "🧪", "🖥️",
          "🧰", "🏭")
CORES = ("#6366F1", "#3B82F6", "#0EA5E9", "#06B6D4", "#0D9488", "#10B981", "#65A30D", "#D97706", "#E4572E",
         "#EC4899", "#8B5CF6", "#64748B")
EST_MAX = 43200
ESTENDER_MAX = 1440
HIST_MAX = 5000            # demandas por pedido de histórico (a tela mostra 400)
ITER = 100_000             # pbkdf2-sha256, igual à Produção: o bloqueio online é a defesa principal
TENTATIVAS = 5
BLOQUEIO_S = 60
TK_VIDA_S = 12 * 3600
TK_MAX = 500
ADM = "Escritório"
SISTEMA = "Sistema"
PAPEIS_ADM = ("maquina", "completo")


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(message)


def _agora() -> int:
    return int(time.time() * 1000)


# Relógio do bloqueio e dos tokens; os testes trocam.
_clock = time.monotonic


# ---------- entradas ----------

def _texto(v, nome: str, lo: int, hi: int, nl: bool = False) -> str:
    if not isinstance(v, str) or (CTRL_NL_RE if nl else CTRL_RE).search(v):
        raise ApiError(400, nome + ": texto com caractere não permitido.")
    s = v.strip()
    if not lo <= len(s) <= hi:
        raise ApiError(400, "%s: de %d a %d caracteres." % (nome, lo, hi))
    return s


def _opcional(v):
    return "" if v is None else v


def _int(v, nome: str, lo: int, hi: int) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise ApiError(400, nome + " inválido.")
    return v


def _de(v, opcoes, nome: str):
    if not isinstance(v, str) or v not in opcoes:
        raise ApiError(400, nome + " inválido.")
    return v


def _find(rows: list, rid):
    return next((r for r in rows if r.get("id") == rid), None)


_RV = [0]   # rev que a gravação em curso recebe; só muda sob LOCK


def _stamp(row: dict) -> dict:
    row["_rv"] = _RV[0]
    return row


def _rev(body: dict, row) -> None:
    """Cadastro: a tela manda o _rv do registro que viu (0 no novo); outro aparelho mexeu nele depois = 409."""
    rev = body.get("rev")
    if isinstance(rev, bool) or not isinstance(rev, int):
        raise ApiError(400, "Versão do registro inválida.")
    if row is not None and rev != row["_rv"]:   # o banco garante _rv em todo registro
        raise ApiError(409, "Alterado em outro aparelho. Atualize a tela e tente de novo.")


# ---------- código da pessoa e tokens ----------

_FAILS: dict = {}   # pessoa -> [erros, bloqueado_ate, em_curso]. Em memória: reinício zera.
_FAILS_LOCK = threading.Lock()   # o pbkdf2 roda fora do LOCK do banco


def _hash(codigo: str, sal: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", codigo.encode(), bytes.fromhex(sal), ITER).hex()


def _check_code(pid: str, sal: str, hsh: str, codigo) -> None:
    """A tentativa entra na conta antes do hash (em_curso): palpites em paralelo não passam de TENTATIVAS."""
    with _FAILS_LOCK:
        st = _FAILS.setdefault(pid, [0, 0.0, 0])
        if st[1] > _clock() or st[0] + st[2] >= TENTATIVAS:
            raise ApiError(429, "Bloqueado por 1 minuto: muitos códigos errados.")
        st[2] += 1
    ok = False
    try:
        ok = isinstance(codigo, str) and bool(CODE_RE.match(codigo)) and hmac.compare_digest(_hash(codigo, sal), hsh)
    finally:
        with _FAILS_LOCK:
            st[2] -= 1
            if ok:
                st[0], st[1] = 0, 0.0
            else:
                st[0] += 1
                if st[0] >= TENTATIVAS:
                    st[0], st[1] = 0, _clock() + BLOQUEIO_S
            if st == [0, 0.0, 0] and _FAILS.get(pid) is st:
                del _FAILS[pid]
    if not ok:
        raise ApiError(403, "Código errado.")


_TK: OrderedDict = OrderedDict()   # tk -> (pessoa, vence); o mais antigo sai primeiro
_TK_LOCK = threading.Lock()


def _tk_novo(pid: str) -> str:
    tk = secrets.token_urlsafe(24)
    with _TK_LOCK:
        _TK[tk] = (pid, _clock() + TK_VIDA_S)
        while len(_TK) > TK_MAX:
            _TK.popitem(last=False)
    return tk


def _tk_pessoa(tk):
    with _TK_LOCK:
        hit = _TK.get(tk) if isinstance(tk, str) else None
        if hit is None:
            return None
        if hit[1] <= _clock():
            del _TK[tk]
            return None
        return hit[0]


def esquecer_pessoas() -> None:
    """Depois de restaurar um backup: todo mundo se identifica de novo (a pessoa pode não existir na cópia, ou ter
    outro código)."""
    with _TK_LOCK:
        _TK.clear()


def _tk_revoga(pid: str) -> None:
    with _TK_LOCK:
        for k in [k for k, v in _TK.items() if v[0] == pid]:
            del _TK[k]


def _setor_ok(doc: dict, sid, nome: str) -> str:
    s = _find(doc["setores"], sid) if isinstance(sid, str) else None
    if s is None or not s.get("ativo"):
        raise ApiError(400, nome + " inválido.")
    return s["id"]


def _pessoa_entrar(doc: dict, body: dict) -> dict:
    pid = body.get("pessoa")
    p = _find(doc["pessoas"], pid) if isinstance(pid, str) else None
    s = _find(doc["setores"], p.get("setor")) if p else None
    if p is None or not p.get("ativo") or s is None or not s.get("ativo") \
            or not isinstance(p.get("sal"), str) or not SAL_RE.match(p["sal"]) or not isinstance(p.get("hash"), str):
        raise ApiError(404, "Pessoa não encontrada.")
    return p


def _codigo_fora(body: dict) -> tuple:
    """Confere o código sem segurar o LOCK durante o pbkdf2. Devolve o que foi conferido."""
    with LOCK:
        p = _pessoa_entrar(ds.load(), body)
    conferido = (p["id"], p["sal"], p["hash"])
    _check_code(*conferido, body.get("codigo"))
    return conferido


def _ator(doc: dict, body: dict, papel):
    """None = ADM (Escritório, papel maquina/completo sem tk); dict = a pessoa do tk."""
    tk = body.get("tk")
    if tk is not None:
        p = _find(doc["pessoas"], _tk_pessoa(tk))
        s = _find(doc["setores"], p.get("setor")) if p else None
        if p is None or not p.get("ativo") or s is None or not s.get("ativo"):
            raise ApiError(401, "Identifique-se de novo.")
        return p
    if papel in PAPEIS_ADM:
        return None
    raise ApiError(403, "Identifique-se para usar as demandas.")


def _quem(ator) -> str:
    return ADM if ator is None else ator["nome"]


def _so_adm(ator) -> None:
    if ator is not None:
        raise ApiError(403, "Só o escritório pode fazer isso.")


# ---------- registros auxiliares ----------

def _evento(d: dict, ev: str, quem: str, nota: str, t: int) -> None:
    d["eventos"].append({"t": t, "ev": ev, "quem": quem, "nota": nota})
    if len(d["eventos"]) > ds.MAX["eventos"]:
        del d["eventos"][1]   # o "created" fica; sai o mais antigo depois dele


def _nota(doc: dict, aud: str, tipo: str, dem: str, texto: str, quem: str, t: int) -> None:
    nid = max([doc["seq"]["nota"]] + [n["id"] for n in doc["notas"]]) + 1
    doc["seq"]["nota"] = nid
    doc["notas"].append({"id": nid, "aud": aud, "tipo": tipo, "dem": dem, "texto": texto, "quem": quem, "t": t,
                         "lida": False})
    del doc["notas"][:-ds.MAX["notas"]]   # as mais antigas saem


def _fecha_pausa(d: dict, t: int) -> None:
    for p in d["pausas"]:
        if p.get("fim") is None:
            p["fim"] = t


def _num(d: dict) -> int:
    return int(d["id"][4:])   # o banco só carrega ids SOL-<n>


def _dem(doc: dict, body: dict) -> dict:
    did = body.get("id")
    if not isinstance(did, str) or not ds.DEMANDA_RE.fullmatch(did):
        raise ApiError(400, "Demanda inválida.")
    d = _find(doc["demandas"], did)
    if d is None:
        raise ApiError(404, "Demanda não encontrada.")
    return d


def _ativa(d: dict) -> None:
    if not calc.ativa(d):
        raise ApiError(409, "A demanda já foi encerrada.")


def _responsavel(d: dict, ator) -> None:
    if ator is None or d["para"]["p"] != ator["id"]:
        raise ApiError(403, "Só o responsável pela demanda pode fazer isso.")


def _pessoa_do_setor(doc: dict, pid, sid: str):
    """None (fila do setor) ou o id de uma pessoa ativa daquele setor."""
    if pid is None or pid == "":
        return None
    p = _find(doc["pessoas"], pid) if isinstance(pid, str) else None
    if p is None or not p.get("ativo") or p.get("setor") != sid:
        raise ApiError(400, "Pessoa responsável inválida.")
    return p["id"]


def _nome_pessoa(doc: dict, pid) -> str:
    return _find(doc["pessoas"], pid)["nome"]   # só para pessoa já conferida


def marcar_atrasos(doc: dict, agora: int) -> bool:
    """Ativa que passou do prazo ganha o evento "late" e as notas (adm e destino) uma vez só."""
    mudou = False
    for d in doc["demandas"]:
        if calc.ativa(d) and not d["atraso_avisado"] and agora > calc.prazo(d):
            d["atraso_avisado"] = True
            _evento(d, "late", SISTEMA, "", agora)
            _nota(doc, "adm", "late", d["id"], "", SISTEMA, agora)
            _nota(doc, d["para"]["s"], "late", d["id"], "", SISTEMA, agora)
            _stamp(d)
            mudou = True
    return mudou


def _devolve(doc: dict, pid: str, porque: str, t: int) -> None:
    """unassignUser do DEMANDA: as ativas da pessoa voltam para a fila do setor (abertas, sem início)."""
    for d in doc["demandas"]:
        if d["para"]["p"] != pid or not calc.ativa(d):
            continue
        _fecha_pausa(d, t)
        d["status"], d["iniciado"] = "new", None
        d["para"]["p"] = None
        _evento(d, "reassigned", ADM, porque + " — voltou para a fila do setor", t)
        _nota(doc, d["para"]["s"], "new", d["id"], "", ADM, t)
        _stamp(d)


def _todas(doc: dict) -> list:
    """Principal + arquivo morto, sem repetir (o principal vence)."""
    ids = {d["id"] for d in doc["demandas"]}
    return doc["demandas"] + [d for d in ds.load_arquivo() if d["id"] not in ids]


# ---------- demandas ----------

def _criar(doc: dict, ator, body: dict, t: int):
    titulo = _texto(body.get("titulo"), "Título", 5, 140)
    tipo = _de(body.get("tipo"), TIPOS, "Tipo")
    motivo = _de(body.get("motivo"), MOTIVOS, "Motivo")
    prio = _de(body.get("prio"), PRIO, "Prioridade")
    est = _int(body.get("est"), "Tempo estipulado", 1, EST_MAX)
    desc = _texto(_opcional(body.get("desc")), "Descrição", 0, 2000, nl=True) or "Sem descrição adicional."
    para = body.get("para")
    if not isinstance(para, dict):
        raise ApiError(400, "Setor responsável inválido.")
    s = _setor_ok(doc, para.get("s"), "Setor responsável")
    p = _pessoa_do_setor(doc, para.get("p"), s)
    de = {"s": _setor_ok(doc, body.get("de_s"), "Setor solicitante"), "p": None} if ator is None \
        else {"s": ator["setor"], "p": ator["id"]}
    if sum(1 for d in doc["demandas"] if calc.ativa(d)) >= ds.MAX["demandas"]:
        raise ApiError(400, "Limite de demandas em aberto atingido.")
    n = max([doc["seq"]["demanda"]] + [_num(d) for d in doc["demandas"]] + [_num(d) for d in ds.load_arquivo()]) + 1
    quem = _quem(ator)
    d = {"id": "SOL-%d" % n, "titulo": titulo, "tipo": tipo, "motivo": motivo, "prio": prio, "est": est,
         "de": de, "para": {"s": s, "p": p}, "desc": desc, "status": "new", "criado": t, "iniciado": None,
         "fim": None, "atraso_avisado": False, "pausas": [], "eventos": [], "comentarios": [], "anexos": []}
    _evento(d, "created", quem, "", t)
    if p is not None:
        _evento(d, "assigned", quem, "Responsável: " + _nome_pessoa(doc, p), t)
    doc["demandas"].append(_stamp(d))
    doc["seq"]["demanda"] = n
    _nota(doc, s, "new", d["id"], "", quem, t)
    if prio == "urg":
        _nota(doc, "adm", "urg", d["id"], "", quem, t)


def _aceitar(doc: dict, ator, body: dict, t: int):
    d = _dem(doc, body)
    if ator is None or ator["setor"] != d["para"]["s"]:
        raise ApiError(403, "Só quem é do setor responsável pode aceitar.")
    if d["status"] != "new":
        raise ApiError(409, "A demanda não está mais aberta.")
    nome = ator["nome"]
    if d["para"]["p"] != ator["id"]:
        d["para"]["p"] = ator["id"]
        _evento(d, "assigned", nome, "Responsável: " + nome, t)
    d["status"], d["iniciado"] = "prog", t
    _evento(d, "started", nome, "", t)
    if d["de"]["s"] != d["para"]["s"]:
        _nota(doc, d["de"]["s"], "accepted", d["id"], "", nome, t)
    _stamp(d)


def _pausar(doc: dict, ator, body: dict, t: int):
    d = _dem(doc, body)
    _responsavel(d, ator)
    if d["status"] != "prog":
        raise ApiError(409, "Só uma demanda em andamento pode ser pausada.")
    motivo = _de(body.get("motivo"), PAUSAS, "Motivo da pausa")
    obs = _texto(_opcional(body.get("obs")), "Observação", 0, 500)
    if len(d["pausas"]) >= ds.MAX["pausas"]:
        raise ApiError(400, "Limite de pausas desta demanda atingido.")
    nome = ator["nome"]
    d["status"] = "pause"
    d["pausas"].append({"ini": t, "fim": None, "motivo": motivo, "obs": obs, "por": nome})
    _evento(d, "paused", nome, motivo + (" — " + obs if obs else ""), t)
    _nota(doc, "adm", "pause", d["id"], motivo, nome, t)
    if d["de"]["s"] != d["para"]["s"]:
        _nota(doc, d["de"]["s"], "pause", d["id"], motivo, nome, t)
    _stamp(d)


def _retomar(doc: dict, ator, body: dict, t: int):
    d = _dem(doc, body)
    _responsavel(d, ator)
    if d["status"] != "pause":
        raise ApiError(409, "A demanda não está pausada.")
    _fecha_pausa(d, t)
    d["status"] = "prog"
    _evento(d, "resumed", ator["nome"], "", t)
    _stamp(d)


def _concluir(doc: dict, ator, body: dict, t: int):
    d = _dem(doc, body)
    _responsavel(d, ator)
    _ativa(d)
    nota = _texto(_opcional(body.get("nota")), "Observação", 0, 500)
    _fecha_pausa(d, t)
    if d["iniciado"] is None:
        d["iniciado"] = t
    d["status"], d["fim"] = "done", t
    _evento(d, "done", ator["nome"], nota, t)
    if d["de"]["s"] != d["para"]["s"]:
        _nota(doc, d["de"]["s"], "done", d["id"], "", ator["nome"], t)
    _stamp(d)


def _cancelar(doc: dict, ator, body: dict, t: int):
    d = _dem(doc, body)
    if ator is not None and d["de"]["p"] != ator["id"]:
        raise ApiError(403, "Só quem pediu ou o escritório pode cancelar.")
    _ativa(d)
    motivo = _texto(_opcional(body.get("motivo")), "Motivo", 0, 500)
    _fecha_pausa(d, t)
    d["status"], d["fim"] = "canc", t
    _evento(d, "canc", _quem(ator), motivo, t)
    _nota(doc, d["para"]["s"], "canc", d["id"], motivo, _quem(ator), t)
    _stamp(d)


def _reatribuir(doc: dict, ator, body: dict, t: int):
    d = _dem(doc, body)
    if ator is not None and (ator["setor"] != d["para"]["s"] or (d["status"] != "new" and d["para"]["p"] != ator["id"])):
        raise ApiError(403, "Só o responsável (ou o setor, enquanto aberta) pode repassar.")
    _ativa(d)
    s = _setor_ok(doc, body.get("s"), "Setor")
    p = _pessoa_do_setor(doc, body.get("p"), s)
    nota = _texto(_opcional(body.get("nota")), "Observação", 0, 500)
    mudou = s != d["para"]["s"]
    if mudou or p is None:   # outro setor, ou sem responsável: volta à fila (aberta, sem início)
        _fecha_pausa(d, t)
        d["status"], d["iniciado"] = "new", None
    d["para"] = {"s": s, "p": p}
    _evento(d, "reassigned", _quem(ator), "Para " + s + (" · " + _nome_pessoa(doc, p) if p else "")
            + (" — " + nota if nota else ""), t)
    if mudou:
        _nota(doc, s, "new", d["id"], "", _quem(ator), t)
    _stamp(d)


def _cobrar(doc: dict, ator, body: dict, t: int):
    d = _dem(doc, body)
    if ator is not None and d["de"]["p"] != ator["id"]:
        raise ApiError(403, "Só quem pediu ou o escritório pode cobrar.")
    _ativa(d)
    _evento(d, "nudge", _quem(ator), "", t)
    _nota(doc, d["para"]["s"], "nudge", d["id"], "", _quem(ator), t)
    _stamp(d)


def _prioridade(doc: dict, ator, body: dict, t: int):
    _so_adm(ator)
    d = _dem(doc, body)
    _ativa(d)
    prio = _de(body.get("prio"), PRIO, "Prioridade")
    if prio == d["prio"]:
        return False
    _evento(d, "prio", ADM, PRIO.get(d["prio"], str(d["prio"])) + " → " + PRIO[prio], t)
    d["prio"] = prio
    if prio == "urg":
        _nota(doc, d["para"]["s"], "nudge", d["id"], "Prioridade elevada para URGENTE", ADM, t)
    _stamp(d)


def _estender(doc: dict, ator, body: dict, t: int):
    _so_adm(ator)
    d = _dem(doc, body)
    _ativa(d)
    minutos = _int(body.get("minutos"), "Minutos", 1, ESTENDER_MAX)
    if d["est"] + minutos > EST_MAX:
        raise ApiError(400, "O tempo estipulado passaria de 30 dias.")
    d["est"] += minutos
    if calc.prazo(d) > t:
        d["atraso_avisado"] = False
    _evento(d, "deadline", ADM, "+" + calc.dur(minutos), t)
    _stamp(d)


def _comentar(doc: dict, ator, body: dict, t: int):
    d = _dem(doc, body)
    if ator is not None and ator["setor"] not in (d["de"]["s"], d["para"]["s"]):
        raise ApiError(403, "Só os setores da demanda podem comentar.")
    texto = _texto(body.get("texto"), "Comentário", 1, 1000, nl=True)
    if len(d["comentarios"]) >= ds.MAX["comentarios"]:
        raise ApiError(400, "Limite de comentários desta demanda atingido.")
    d["comentarios"].append({"quem": _quem(ator), "t": t, "texto": texto})
    _stamp(d)


# ---------- anexos ----------

def _pode_anexar(doc: dict, ator, body: dict) -> dict:
    d = _dem(doc, body)
    if ator is not None and d["de"]["p"] != ator["id"] and ator["setor"] != d["para"]["s"]:
        raise ApiError(403, "Só quem pediu ou o setor responsável pode anexar.")
    if d["status"] == "canc":
        raise ApiError(409, "Demanda cancelada não recebe anexo.")
    if len(d["anexos"]) >= ds.ANEXOS_POR_DEMANDA:
        raise ApiError(400, "No máximo %d anexos por demanda." % ds.ANEXOS_POR_DEMANDA)
    return d


def _b64(v) -> bytes:
    """Base64 estrito; o tamanho é conferido pelo texto antes de decodificar."""
    if not isinstance(v, str) or not v:
        raise ApiError(400, "Anexo inválido.")
    if len(v) > (ds.ANEXO_MAX + 2) // 3 * 4:
        raise ApiError(413, "Anexo maior que 5 MB.")
    try:
        return base64.b64decode(v, validate=True)
    except (binascii.Error, ValueError):
        raise ApiError(400, "Anexo inválido.") from None


def _anexo_de(demandas: list, aid: str, ator):
    for d in demandas:
        for a in d["anexos"]:
            if a.get("id") == aid:
                if ator is not None and not calc.ve(d, ator):
                    raise ApiError(403, "Sem acesso a este anexo.")
                return a
    raise ApiError(404, "Anexo não encontrado.")


def _ler_anexo(aid, papel, body: dict) -> dict:
    if not isinstance(aid, str) or not ds.AID_RE.fullmatch(aid):
        raise ApiError(404, "Anexo não encontrado.")
    with LOCK:
        doc = ds.load()
        ator = _ator(doc, body, papel)
        a = _anexo_de(doc["demandas"] if ator is not None else _todas(doc), aid, ator)
        nome = a.get("nome")
    dados, tipo = ds.ler_anexo(aid)   # fora do LOCK: só lê um arquivo de nome fixo
    return {"id": aid, "nome": nome, "tipo": tipo, "dados": base64.b64encode(dados).decode("ascii")}


def _anexo_apagar(doc: dict, ator, body: dict, t: int):
    d = _dem(doc, body)
    aid = body.get("aid")
    a = next((x for x in d["anexos"] if x.get("id") == aid), None)
    if a is None:
        raise ApiError(404, "Anexo não encontrado.")
    if ator is not None and a.get("_p") != ator["id"]:
        raise ApiError(403, "Só quem enviou ou o escritório pode remover o anexo.")
    _ativa(d)
    d["anexos"].remove(a)
    _stamp(d)
    return lambda: ds.apagar_anexo(aid)   # o arquivo some depois de gravar: falha antes deixa os dois


# ---------- notas ----------

def _aud(ator) -> str:
    return "adm" if ator is None else ator["setor"]


def _nota_lida(doc: dict, ator, body: dict, t: int):
    nid = body.get("nid")
    n = _find(doc["notas"], nid) if isinstance(nid, int) and not isinstance(nid, bool) else None
    if n is None:
        raise ApiError(404, "Notificação não encontrada.")
    if n.get("aud") != _aud(ator):
        raise ApiError(403, "Notificação de outra pessoa.")
    if n["lida"]:
        return False
    n["lida"] = True


def _notas_todas(doc: dict, ator, body: dict, t: int):
    novas = [n for n in doc["notas"] if n.get("aud") == _aud(ator) and not n["lida"]]
    for n in novas:
        n["lida"] = True
    if not novas:
        return False


# ---------- cadastros ----------

def _usado(doc: dict, chave: str, valor: str) -> bool:
    """Alguma demanda (principal ou arquivo morto) tem o setor (chave "s") ou a pessoa (chave "p") de origem ou destino."""
    return any(d["de"][chave] == valor or d["para"][chave] == valor for d in _todas(doc))


def _setor_salvar(doc: dict, ator, body: dict, t: int):
    _so_adm(ator)
    modo = _de(body.get("modo"), ("novo", "editar"), "Modo")
    nome = _texto(body.get("nome"), "Nome do setor", 3, 40)
    icone = _de(body.get("icone"), ICONES, "Ícone")
    cor = _de(body.get("cor"), CORES, "Cor")
    sid = body.get("id")
    if modo == "novo":
        if not isinstance(sid, str) or not ds.SETOR_RE.fullmatch(sid):
            raise ApiError(400, "Sigla: de 2 a 4 letras maiúsculas ou números.")
        _rev(body, None)
        if _find(doc["setores"], sid) is not None:
            raise ApiError(400, "Esta sigla já está em uso.")
        if len(doc["setores"]) >= ds.MAX["setores"]:
            raise ApiError(400, "Limite de setores atingido.")
        doc["setores"].append(_stamp({"id": sid, "nome": nome, "icone": icone, "cor": cor, "ativo": True}))
        return
    s = _find(doc["setores"], sid)
    if s is None:
        raise ApiError(404, "Setor não encontrado.")
    _rev(body, s)
    s.update(nome=nome, icone=icone, cor=cor)
    _stamp(s)


def _setor(doc: dict, body: dict) -> dict:
    s = _find(doc["setores"], body.get("id"))
    if s is None:
        raise ApiError(404, "Setor não encontrado.")
    _rev(body, s)
    return s


def _setor_ativar(doc: dict, ator, body: dict, t: int):
    _so_adm(ator)
    s = _setor(doc, body)
    if s.get("ativo"):
        abertas = sum(1 for d in doc["demandas"] if calc.ativa(d) and d["para"]["s"] == s["id"])
        if abertas:
            raise ApiError(400, "Setor com %d demanda(s) em aberto: conclua ou reatribua antes de desativar." % abertas)
    s["ativo"] = not s.get("ativo")
    _stamp(s)


def _setor_apagar(doc: dict, ator, body: dict, t: int):
    _so_adm(ator)
    s = _setor(doc, body)
    gente = [p for p in doc["pessoas"] if p.get("setor") == s["id"]]
    if _usado(doc, "s", s["id"]) or any(_usado(doc, "p", p["id"]) for p in gente):
        raise ApiError(400, "Setor com histórico de demandas: desative em vez de excluir.")
    for p in gente:
        doc["pessoas"].remove(p)
        _tk_revoga(p["id"])
    doc["setores"].remove(s)


def _novo_codigo(p: dict, codigo) -> None:
    if not isinstance(codigo, str) or not CODE_RE.match(codigo):
        raise ApiError(400, "O código tem exatamente 4 números.")
    p["sal"] = secrets.token_hex(16)
    p["hash"] = _hash(codigo, p["sal"])
    _tk_revoga(p["id"])
    with _FAILS_LOCK:
        _FAILS.pop(p["id"], None)


def _pessoa_num(p: dict) -> int:
    return int(p["id"][1:])


def _pessoa_salvar(doc: dict, ator, body: dict, t: int):
    _so_adm(ator)
    modo = _de(body.get("modo"), ("novo", "editar"), "Modo")
    nome = _texto(body.get("nome"), "Nome", 2, 60)
    setor = body.get("setor")
    if modo == "novo":
        _rev(body, None)
        setor = _setor_ok(doc, setor, "Setor")
        if len(doc["pessoas"]) >= ds.MAX["pessoas"]:
            raise ApiError(400, "Limite de pessoas atingido.")
        n = max([doc["seq"]["pessoa"]] + [_pessoa_num(p) + 1 for p in doc["pessoas"]])
        p = {"id": "p%d" % n, "nome": nome, "setor": setor, "mat": "M%d" % (100 + n), "ativo": True}
        _novo_codigo(p, body.get("codigo"))
        doc["pessoas"].append(_stamp(p))
        doc["seq"]["pessoa"] = n + 1
        return
    p = _find(doc["pessoas"], body.get("id"))
    if p is None:
        raise ApiError(404, "Pessoa não encontrada.")
    _rev(body, p)
    if setor != p.get("setor"):
        setor = _setor_ok(doc, setor, "Setor")
        _devolve(doc, p["id"], "Usuário transferido de setor", t)
    if body.get("codigo") not in (None, ""):
        _novo_codigo(p, body.get("codigo"))
    p.update(nome=nome, setor=setor)
    _stamp(p)


def _pessoa(doc: dict, body: dict) -> dict:
    p = _find(doc["pessoas"], body.get("id"))
    if p is None:
        raise ApiError(404, "Pessoa não encontrada.")
    _rev(body, p)
    return p


def _pessoa_ativar(doc: dict, ator, body: dict, t: int):
    _so_adm(ator)
    p = _pessoa(doc, body)
    if p.get("ativo"):
        _devolve(doc, p["id"], "Usuário desativado", t)
        _tk_revoga(p["id"])
    p["ativo"] = not p.get("ativo")
    _stamp(p)


def _pessoa_apagar(doc: dict, ator, body: dict, t: int):
    _so_adm(ator)
    p = _pessoa(doc, body)
    if _usado(doc, "p", p["id"]):
        raise ApiError(400, "Pessoa com histórico de demandas: desative em vez de excluir.")
    doc["pessoas"].remove(p)
    _tk_revoga(p["id"])


# ---------- leituras de ADM ----------

def _historico(doc: dict, ator, body: dict, t: int) -> dict:
    _so_adm(ator)
    de = _int(body.get("de"), "Início", 0, 10 ** 15)
    ate = _int(body.get("ate"), "Fim", de, 10 ** 15)
    rows = sorted((d for d in _todas(doc) if de <= d["criado"] <= ate), key=lambda d: -d["criado"])[:HIST_MAX]
    return {"demandas": [calc.publica(d, t) for d in rows]}


def _crono(doc: dict, ator, body: dict, t: int) -> dict:
    _so_adm(ator)
    dias = body.get("dias")
    if isinstance(dias, bool) or dias not in (1, 7, 30):
        raise ApiError(400, "Período inválido.")
    return calc.crono(_todas(doc), t, dias)


def _vista_de(doc: dict, ator, t: int) -> dict:
    if ator is not None:
        return calc.vista(doc, t, ator)
    v = calc.vista(doc, t, None, ds.uso_anexos())
    v["backup"] = bk.resumo(t)   # só o aviso e a frase curta, sem caminho de pasta: o ADM pela rede também vê
    return v


def _vista(doc: dict, ator, body: dict, t: int) -> dict:
    return _vista_de(doc, ator, t)


ESCRITAS = {
    "demanda/criar": _criar, "demanda/aceitar": _aceitar, "demanda/pausar": _pausar, "demanda/retomar": _retomar,
    "demanda/concluir": _concluir, "demanda/cancelar": _cancelar, "demanda/reatribuir": _reatribuir,
    "demanda/cobrar": _cobrar, "demanda/prioridade": _prioridade, "demanda/estender": _estender,
    "demanda/comentar": _comentar, "anexo/apagar": _anexo_apagar, "nota/lida": _nota_lida, "nota/todas": _notas_todas,
    "setor/salvar": _setor_salvar, "setor/ativar": _setor_ativar, "setor/apagar": _setor_apagar,
    "pessoa/salvar": _pessoa_salvar, "pessoa/ativar": _pessoa_ativar, "pessoa/apagar": _pessoa_apagar,
}
LEITURAS = {"vista": _vista, "historico": _historico, "crono": _crono}


def _gravar(doc: dict, ator, t: int, acao, body: dict) -> tuple:
    """Sob o LOCK: aplica a ação, marca atrasos e grava se algo mudou. Devolve (vista, depois)."""
    _RV[0] = doc["rev"] + 1
    r = acao(doc, ator, body, t)
    if marcar_atrasos(doc, t) or r is not False:
        ds.commit(doc)
    return _vista_de(doc, ator, t), r if callable(r) else None


def _entrar(body: dict, t: int) -> dict:
    conferido = _codigo_fora(body)
    with LOCK:
        doc = ds.load()
        p = _pessoa_entrar(doc, body)
        if (p["id"], p["sal"], p["hash"]) != conferido:
            raise ApiError(409, "O código desta pessoa mudou. Tente de novo.")
        v = calc.vista(doc, t, p)
    return {"tk": _tk_novo(p["id"]), "eu": v["eu"], "vista": v}


def _anexo_enviar(body: dict, papel, t: int) -> dict:
    """Confere a permissão, grava o arquivo fora do LOCK e o metadado sob ele; falhou depois = arquivo apagado."""
    with LOCK:
        doc = ds.load()
        _pode_anexar(doc, _ator(doc, body, papel), body)
    nome = _texto(body.get("nome"), "Nome do anexo", 1, ds.NOME_MAX)
    meta = ds.salvar_anexo(_b64(body.get("dados")), nome)
    gravado = False
    try:
        with LOCK:
            doc = ds.load()
            ator = _ator(doc, body, papel)
            d = _pode_anexar(doc, ator, body)
            _RV[0] = doc["rev"] + 1
            d["anexos"].append(dict(meta, por=_quem(ator), t=t, _p=None if ator is None else ator["id"]))
            _evento(d, "attach", _quem(ator), meta["nome"], t)
            _stamp(d)
            marcar_atrasos(doc, t)
            ds.commit(doc)
            gravado = True
            return _vista_de(doc, ator, t)
    finally:
        if not gravado:
            ds.apagar_anexo(meta["id"])


# Contrato com o server.py do núcleo (módulo local genérico).
# api.py, cálculo, contrato e testes não saem. As fontes saem, mas não entram no PAGE: o app.js carrega como
# <script> todo item do PAGE que não é .css.
STATIC = ("demandas-fontes.css", "demandas.css", "demandas.js", "bricolage-grotesque.woff2", "figtree.woff2")
PAGE = ("demandas-fontes.css", "demandas.css", "demandas.js")
REV_FILE = "demandas.json"


def handle(method: str, rest: str, body: dict, ctx: dict) -> dict:
    """/api/local/demandas/<rest>. GET: "" (vista ou lista pública) e anexo/<aid>. O resto é POST."""
    try:
        return _handle(method, rest, body, ctx)
    except ds.StoreError as exc:   # mensagem do banco já é para a tela (sem caminho de arquivo)
        raise ApiError(exc.status, str(exc)) from None


def _handle(method: str, rest: str, body: dict, ctx: dict) -> dict:
    if not isinstance(body, dict):
        raise ApiError(400, "Pedido inválido.")
    papel = ctx.get("papel")
    t = _agora()
    if method == "GET":
        if rest == "":
            with LOCK:
                doc = ds.load()
                if papel == "operador":   # tela "quem é você?" do tablet: só o necessário para escolher
                    return {"setores": [calc.setor_publico(s) for s in doc["setores"] if s.get("ativo")],
                            "pessoas": [calc.pessoa_publica(p) for p in doc["pessoas"] if p.get("ativo")]}
                return _vista_de(doc, _ator(doc, {}, papel), t)
        if rest.startswith("anexo/"):
            return _ler_anexo(rest[len("anexo/"):], papel, {})
        raise ApiError(404, "Caminho das demandas desconhecido.")
    if method != "POST":
        raise ApiError(404, "Caminho das demandas desconhecido.")
    if rest == "entrar":
        return _entrar(body, t)
    if rest == "sair":
        with _TK_LOCK:
            if isinstance(body.get("tk"), str):
                _TK.pop(body["tk"], None)
        return {"ok": True}
    if rest == "anexo/enviar":
        return _anexo_enviar(body, papel, t)
    if rest == "anexo/ler":
        return _ler_anexo(body.get("aid"), papel, body)
    acao = ESCRITAS.get(rest)
    leitura = LEITURAS.get(rest)
    if acao is None and leitura is None:
        raise ApiError(404, "Caminho das demandas desconhecido.")
    with LOCK:
        doc = ds.load()
        ator = _ator(doc, body, papel)
        if leitura is not None:
            return leitura(doc, ator, body, t)
        out, depois = _gravar(doc, ator, t, acao, body)
    if depois is not None:
        depois()
    return out
