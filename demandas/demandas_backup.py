"""Backup automático: um .zip verificado de demandas.json, demandas-arquivo.json e dos anexos citados.

Configuração em data/backup.json e o que aconteceu em data/backup-estado.json (fora do zip, como rede.json e
sessoes.json, que nunca entram nele). As cópias vão para a pasta local (padrão: backup/ ao lado de data/).
O JSON é lido sob ds.LOCK (nunca pega o meio de uma gravação); os anexos, imutáveis, são lidos fora dele.
A thread de fundo do servidor chama tarefa(agora) a cada minuto. Estudo: docs/estudos/01-backup.md.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import sys
import threading
import time
import zipfile
import zlib
from datetime import datetime
from pathlib import Path

import demandas_store as ds
import store

FORMATO = 1
NOME_RE = re.compile(r"^central-demandas_(\d{8})-(\d{4})_(auto|inicio|manual|antes-restaurar)\.zip$")
AUTO = ("auto", "inicio")          # entram na regra 7 diárias / 4 semanais / 12 mensais
AVULSAS = ("manual", "antes-restaurar")   # só as últimas ret["manuais"] de cada
JSONS = ("demandas.json", "demandas-arquivo.json")
ANEXO_RE = re.compile(r"^demandas-anexos/a[0-9a-f]{16}\.(jpg|png|pdf)$")
JSON_MAX = 200 * 1024 * 1024
MANIFESTO_MAX = 16 * 1024 * 1024
HORA_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
PADRAO = {"on": True, "hora": "03:00", "ao_ligar": True, "local": "",
          "ret": {"diarias": 7, "semanais": 4, "mensais": 12, "manuais": 5}, "limite_mb": 5000}
RET_MAX = 60
LIMITE_MB = (50, 1000000)
HORA = 3600 * 1000
ESPERA_INICIO = 2 * 60 * 1000      # ao ligar, espera 2 min para não pesar a abertura
VELHO_INICIO = 20 * HORA           # ao ligar, faz backup se o último bom tem mais que isto
VELHO_ALERTA = 26 * HORA           # um dia mais folga: passou disto, aviso grave
ESPERA_FALHA = 30 * 60 * 1000      # depois de uma falha, não tenta de novo a cada minuto

_BACKUP = threading.Lock()         # uma cópia de cada vez (pego sem esperar)
_INICIO: dict = {"t": None}        # quando a thread de fundo rodou a primeira vez


def _agora() -> int:
    return int(time.time() * 1000)


def _cfg_path() -> Path:
    return store.data_dir() / "backup.json"


def _estado_path() -> Path:
    return store.data_dir() / "backup-estado.json"


def pasta_padrao() -> Path:
    return store.data_dir().parent / "backup"


def _ler_json(p: Path) -> dict:
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


# ---------- configuração ----------

def _inteiro(v, lo: int, hi: int):
    return v if isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi else None


def _pasta_ok(v) -> str | None:
    """Caminho absoluto aceito como pasta local, ou None. Nunca dentro de data/ (o backup entraria no backup) nem a
    raiz de um disco; a pasta mãe tem de existir (não inventa a letra de um pen drive que não está plugado)."""
    if not isinstance(v, str) or not v.strip() or len(v) > 260:
        return None
    p = Path(v.strip())
    if not p.is_absolute() or p.parent == p:
        return None
    try:
        p = p.resolve()
        dados = store.data_dir().resolve()
    except OSError:
        return None
    if p == dados or dados in p.parents or not p.parent.is_dir():
        return None
    return str(p)


def _campos(raw: dict, base: dict, estrito: bool) -> dict:
    """Junta raw sobre base campo a campo. Campo ruim: estrito -> 400; senão fica o de base."""
    out = json.loads(json.dumps(base))

    def ruim(msg):
        if estrito:
            raise ds.StoreError(400, msg)

    if "on" in raw:
        if isinstance(raw["on"], bool):
            out["on"] = raw["on"]
        else:
            ruim("Ligado/desligado inválido.")
    if "ao_ligar" in raw:
        if isinstance(raw["ao_ligar"], bool):
            out["ao_ligar"] = raw["ao_ligar"]
        else:
            ruim("Opção \"ao ligar\" inválida.")
    if "hora" in raw:
        if isinstance(raw["hora"], str) and HORA_RE.fullmatch(raw["hora"]):
            out["hora"] = raw["hora"]
        else:
            ruim("Horário inválido: use HH:MM, de 00:00 a 23:59.")
    if "local" in raw:
        v = raw["local"]
        if v == "":
            pasta = ""
        elif estrito:
            pasta = _pasta_ok(v)
        else:   # a gravada vale mesmo se sumiu (pen drive fora): a cópia falha e avisa, nunca vai para outra pasta
            pasta = v if isinstance(v, str) and Path(v).is_absolute() else None
        if pasta is not None:
            out["local"] = pasta
        else:
            ruim("Pasta inválida: use uma pasta que exista, fora da pasta data e que não seja a raiz do disco.")
    if "ret" in raw:
        ret = raw["ret"] if isinstance(raw["ret"], dict) else {}
        if not isinstance(raw["ret"], dict):
            ruim("Retenção inválida.")
        for k in PADRAO["ret"]:
            if k in ret:
                n = _inteiro(ret[k], 1, RET_MAX)
                if n is None:
                    ruim("Retenção inválida: de 1 a %d cópias." % RET_MAX)
                else:
                    out["ret"][k] = n
    if "limite_mb" in raw:
        n = _inteiro(raw["limite_mb"], *LIMITE_MB)
        if n is None:
            ruim("Limite de espaço inválido: de %d MB a %d MB." % LIMITE_MB)
        else:
            out["limite_mb"] = n
    return out


def config() -> dict:
    """Configuração em uso: o que está em backup.json e válido; o resto, o padrão."""
    return _campos(_ler_json(_cfg_path()), PADRAO, estrito=False)


def salvar_config(body: dict) -> dict:
    """Só os campos enviados mudam; qualquer um inválido recusa tudo (400). A pasta escolhida tem de aceitar gravação."""
    if not isinstance(body, dict):
        raise ds.StoreError(400, "Pedido inválido.")
    cfg = _campos(body, config(), estrito=True)
    if cfg["local"]:
        teste = Path(cfg["local"]) / ".teste-central-demandas"
        try:
            Path(cfg["local"]).mkdir(exist_ok=True)
            teste.write_bytes(b"ok")
            teste.unlink()
        except OSError:
            raise ds.StoreError(400, "Não foi possível gravar na pasta escolhida.") from None
    store.atomic_write(_cfg_path(), json.dumps({"v": 1, **cfg}, ensure_ascii=False))
    return cfg


def pasta_local(cfg: dict) -> Path:
    return Path(cfg["local"]) if cfg.get("local") else pasta_padrao()


# ---------- estado ----------

def estado() -> dict:
    raw = _ler_json(_estado_path())
    ok, falha = raw.get("ultimo_ok"), raw.get("ultima_falha")
    return {"v": 1,
            "ultimo_ok": ok if isinstance(ok, dict) and isinstance(ok.get("t"), int) else None,
            "ultima_falha": falha if isinstance(falha, dict) and isinstance(falha.get("t"), int) else None,
            "falhas_seguidas": _inteiro(raw.get("falhas_seguidas"), 0, 10**9) or 0}


def _grava_estado(est: dict) -> None:
    store.atomic_write(_estado_path(), json.dumps(est, ensure_ascii=False))


def _quanto_tempo(ms: int) -> str:
    h = ms // HORA
    return "%d h" % h if h < 48 else "%d dias" % (h // 24)


def resumo(agora: int, cfg: dict | None = None, est: dict | None = None) -> dict:
    """{"alerta": None | "aviso" | "grave", "texto", "ultimo_ok_t"} para o Painel do ADM. Sem caminho de pasta."""
    cfg = config() if cfg is None else cfg
    est = estado() if est is None else est
    ok, falha = est["ultimo_ok"], est["ultima_falha"]
    t_ok = ok["t"] if ok else None
    out = {"alerta": None, "texto": "", "ultimo_ok_t": t_ok}
    if not cfg["on"]:
        return {**out, "alerta": "aviso", "texto": "Backup automático desligado."}
    if t_ok is not None and agora - t_ok <= VELHO_ALERTA:
        return out
    motivo = falha.get("erro") if falha and (t_ok is None or falha["t"] > t_ok) else None
    texto = "Nenhum backup feito ainda" if t_ok is None else "Último backup há " + _quanto_tempo(agora - t_ok)
    return {**out, "alerta": "grave", "texto": texto + (": %s" % motivo if isinstance(motivo, str) and motivo else ".")}


# ---------- quando rodar ----------

def _hora_de_hoje(agora: int, hora: str) -> int:
    lt = time.localtime(agora / 1000)
    h, m = (int(x) for x in hora.split(":"))
    return int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, h, m, 0, 0, 0, -1)) * 1000)


def deve_rodar(agora: int, cfg: dict, est: dict, inicio: int) -> str | None:
    """Tipo da cópia a fazer agora ("auto" ou "inicio") ou None. Pura: o relógio vem de fora.
    - nada nos 2 primeiros minutos depois de ligar, nem 30 min depois de uma falha;
    - "auto": passou do horário de hoje e a última cópia boa é de antes dele (cobre o PC desligado na hora);
    - "inicio": com "ao ligar", a última cópia boa já tinha mais de 20 h quando o programa ligou (ou não existe).
      Conta a partir do início: com o PC ligado direto, a cópia das 03:00 não ganha outra às 23:00."""
    if not cfg["on"] or agora - inicio < ESPERA_INICIO:
        return None
    t_ok = est["ultimo_ok"]["t"] if est["ultimo_ok"] else None
    falha = est["ultima_falha"]
    if falha and (t_ok is None or falha["t"] > t_ok) and agora - falha["t"] < ESPERA_FALHA:
        return None
    marcada = _hora_de_hoje(agora, cfg["hora"])
    if agora >= marcada and (t_ok is None or t_ok < marcada):
        return "auto"
    if cfg["ao_ligar"] and (t_ok is None or inicio - t_ok > VELHO_INICIO):
        return "inicio"
    return None


# ---------- retenção ----------

def reter(itens, ret: dict, limite_bytes: int) -> list:
    """Nomes a apagar dentre itens [(nome, bytes)]. Pura. Só considera nomes do padrão (o resto nunca sai).
    Automáticas: a mais nova de cada um dos últimos ret["diarias"] dias, ret["semanais"] semanas ISO e
    ret["mensais"] meses que têm cópia. Manuais e antes-restaurar: as últimas ret["manuais"] de cada.
    Passou do limite de espaço: saem as mais velhas das que ficariam. A mais nova de todas nunca sai."""
    copias = []
    for nome, tam in itens:
        m = NOME_RE.fullmatch(nome)
        if m:
            copias.append((datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M"), m.group(3), nome, tam))
    copias.sort(key=lambda c: (c[0], c[2]), reverse=True)   # mais nova primeiro
    if not copias:
        return []
    fica = set()   # a mais nova entra por uma das regras abaixo (todas as retenções são de 1 cópia ou mais)
    autos = [c for c in copias if c[1] in AUTO]
    for chave, n in ((lambda d: d.date(), ret["diarias"]), (lambda d: tuple(d.isocalendar())[:2], ret["semanais"]),
                     (lambda d: (d.year, d.month), ret["mensais"])):
        vistos = set()
        for c in autos:
            k = chave(c[0])
            if k in vistos:
                continue
            if len(vistos) >= n:
                break
            vistos.add(k)
            fica.add(c[2])
    for tipo in AVULSAS:
        fica.update(c[2] for c in [c for c in copias if c[1] == tipo][:ret["manuais"]])
    total = sum(c[3] for c in copias if c[2] in fica)
    for c in reversed(copias):   # mais velha primeiro
        if total <= limite_bytes:
            break
        if c[2] in fica and c is not copias[0]:
            fica.discard(c[2])
            total -= c[3]
    return [c[2] for c in copias if c[2] not in fica]


def listar(pasta: Path) -> list:
    """[(nome, bytes)] das cópias do padrão na pasta (vazia se a pasta não existe)."""
    out = []
    try:
        itens = list(os.scandir(pasta))
    except OSError:
        return out
    for e in itens:
        try:
            if NOME_RE.fullmatch(e.name) and e.is_file():
                out.append((e.name, e.stat().st_size))
        except OSError:   # apagado no meio
            pass
    return sorted(out)


# ---------- cópia ----------

def _bytes_de(p: Path):
    """(bytes, doc) como estão no disco. Sem o principal (queda entre os dois renomes) ou ilegível, os do .bak, que é o
    que a leitura do programa usaria. (None, None) se não há nenhum dos dois."""
    bak = p.with_name(p.name + ".bak")
    for c in (p, bak):
        try:
            raw = c.read_bytes()
            doc = json.loads(raw.decode("utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict):
            return raw, doc
    if p.exists() or bak.exists():
        raise ds.StoreError(500, "Arquivo de dados ilegível: %s." % p.name)
    return None, None


def _demandas_de(doc) -> list:
    rows = doc.get("demandas") if isinstance(doc, dict) else None
    return [d for d in rows if isinstance(d, dict)] if isinstance(rows, list) else []


def instantaneo() -> dict:
    """Os dois JSON lidos juntos sob ds.LOCK (o par principal/arquivo morto fica coerente) e os anexos citados.
    O LOCK fica preso só pelas leituras."""
    with ds.LOCK:
        principal, doc = _bytes_de(ds.path())
        arquivo, arq = _bytes_de(ds.arquivo_path())
    if principal is None:
        doc = ds.empty()
        principal = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    anexos = []
    for d in _demandas_de(doc) + _demandas_de(arq):
        for a in d.get("anexos") if isinstance(d.get("anexos"), list) else []:
            aid = a.get("id") if isinstance(a, dict) else None
            if isinstance(aid, str) and ds.AID_RE.fullmatch(aid) and aid not in anexos:
                anexos.append(aid)
    rev = doc.get("rev")
    return {"jsons": {"demandas.json": principal, **({"demandas-arquivo.json": arquivo} if arquivo is not None else {})},
            "anexos": anexos, "rev": rev if isinstance(rev, int) and not isinstance(rev, bool) else 0,
            "v": doc.get("v"),
            "contagem": {"demandas": len(_demandas_de(doc)), "arquivo": len(_demandas_de(arq)),
                         "pessoas": len(doc.get("pessoas") or []), "setores": len(doc.get("setores") or [])}}


def nome_zip(agora: int, tipo: str) -> str:
    return "central-demandas_%s_%s.zip" % (time.strftime("%Y%m%d-%H%M", time.localtime(agora / 1000)), tipo)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def gravar_zip(inst: dict, pasta: Path, tipo: str, agora: int) -> dict:
    """Grava <nome>.zip.part fora do LOCK, verifica e só então renomeia para .zip. Anexo citado que sumiu no meio
    (removido depois do instantâneo) entra em "faltando"; não é falha. Qualquer erro apaga o .part."""
    final = pasta / nome_zip(agora, tipo)
    part = final.with_name(final.name + ".part")
    estimado = sum(len(b) for b in inst["jsons"].values()) + ds.uso_anexos()["bytes"]   # teto: todos os anexos
    if shutil.disk_usage(pasta).free < 2 * estimado:
        raise ds.StoreError(507, "Sem espaço no disco para o backup.")
    arquivos, faltando = {}, []
    try:
        with zipfile.ZipFile(part, "w") as z:
            for nome, raw in inst["jsons"].items():
                z.writestr(nome, raw, compress_type=zipfile.ZIP_DEFLATED)
                arquivos[nome] = {"bytes": len(raw), "sha256": _sha(raw)}
            for aid in inst["anexos"]:
                try:
                    dados, ext = ds.ler_anexo(aid)
                except ds.StoreError:
                    faltando.append(aid)
                    continue
                nome = "demandas-anexos/%s.%s" % (aid, ext)
                z.writestr(nome, dados, compress_type=zipfile.ZIP_STORED)   # JPG, PNG e PDF já vêm comprimidos
                arquivos[nome] = {"bytes": len(dados), "sha256": _sha(dados)}
            manifesto = {"programa": "Central de demandas", "formato_backup": FORMATO, "v_dados": inst["v"],
                         "criado": agora, "tipo": tipo, "rev": inst["rev"], "maquina": platform.node(),
                         "arquivos": arquivos, "contagem": {**inst["contagem"], "anexos": len(arquivos) - len(inst["jsons"])},
                         "faltando": faltando}
            z.writestr("manifesto.json", json.dumps(manifesto, ensure_ascii=False, indent=1),
                       compress_type=zipfile.ZIP_DEFLATED)
        with open(part, "rb+") as fh:
            os.fsync(fh.fileno())
        verificar(part)
        store._replace(part, final, temporario=True)
    except BaseException:
        store._remove(part)
        raise
    raw = final.read_bytes()
    return {"t": agora, "nome": final.name, "tipo": tipo, "bytes": len(raw), "sha256": _sha(raw), "rev": inst["rev"],
            "verificado": True, "faltando": len(faltando)}


def _defeito(msg: str):
    return ds.StoreError(400, "Cópia com defeito: " + msg)


def _limite(nome: str) -> int | None:
    if nome == "manifesto.json":
        return MANIFESTO_MAX
    if nome in JSONS:
        return JSON_MAX
    if ANEXO_RE.fullmatch(nome):
        return ds.ANEXO_MAX
    return None


def verificar(caminho: Path) -> dict:
    """Manifesto do zip se ele está inteiro; senão StoreError 400 "Cópia com defeito: …".
    Confere: só nomes da lista (nada de ../ nem C:\\), tamanhos máximos (contra zip bomb), CRC (testzip), JSON
    legíveis de versão que este programa abre e o sha256 de cada membro contra o manifesto."""
    try:
        with zipfile.ZipFile(caminho) as z:
            infos = z.infolist()
            nomes = [i.filename for i in infos]
            if len(set(nomes)) != len(nomes):
                raise _defeito("nome repetido.")
            total = 0
            for i in infos:
                lim = _limite(i.filename)
                if lim is None:
                    raise _defeito("arquivo inesperado.")
                if i.file_size > lim:
                    raise _defeito("arquivo grande demais.")
                total += i.file_size
            if total > 2 * JSON_MAX + MANIFESTO_MAX + ds.COTA:
                raise _defeito("grande demais.")
            if "manifesto.json" not in nomes or "demandas.json" not in nomes:
                raise _defeito("falta o manifesto ou o demandas.json.")
            if z.testzip() is not None:
                raise _defeito("arquivo corrompido.")
            try:
                man = json.loads(z.read("manifesto.json").decode("utf-8"))
            except ValueError:
                raise _defeito("manifesto ilegível.") from None
            arquivos = man.get("arquivos") if isinstance(man, dict) else None
            if not isinstance(arquivos, dict) or set(arquivos) != set(nomes) - {"manifesto.json"}:
                raise _defeito("manifesto não confere com o conteúdo.")
            fmt = man.get("formato_backup")
            if not isinstance(fmt, int) or isinstance(fmt, bool) or fmt > FORMATO:
                raise _defeito("feita por uma versão mais nova da Central de demandas.")
            for nome, info in arquivos.items():
                raw = z.read(nome)
                if not isinstance(info, dict) or info.get("sha256") != _sha(raw) or info.get("bytes") != len(raw):
                    raise _defeito("conteúdo diferente do manifesto.")
                if nome in JSONS:
                    try:
                        doc = json.loads(raw.decode("utf-8"))
                    except ValueError:
                        raise _defeito("%s ilegível." % nome) from None
                    v = doc.get("v", 0) if isinstance(doc, dict) else None
                    if not isinstance(v, int) or isinstance(v, bool):
                        raise _defeito("%s ilegível." % nome)
                    if v > ds.V:
                        raise _defeito("dados de uma versão mais nova da Central de demandas.")
    except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, zlib.error):
        raise _defeito("não é um zip válido.") from None
    except OSError:
        raise _defeito("não foi possível ler o arquivo.") from None
    return man


def quando(nome: str) -> int | None:
    """Instante (ms, hora local do nome) de uma cópia do padrão; None se o nome não é do padrão."""
    m = NOME_RE.fullmatch(nome)
    if not m:
        return None
    return int(time.mktime(time.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M")) * 1000)


def painel(agora: int | None = None) -> dict:
    """Tudo o que a seção Backup das Configurações mostra (só no computador principal: tem o caminho da pasta)."""
    agora = _agora() if agora is None else agora
    cfg = config()
    pasta = pasta_local(cfg)
    try:
        livre = shutil.disk_usage(pasta if pasta.is_dir() else pasta.parent).free
    except OSError:
        livre = None
    copias = [{"nome": n, "tipo": NOME_RE.fullmatch(n).group(3), "bytes": b, "t": quando(n)} for n, b in listar(pasta)]
    copias.sort(key=lambda c: (c["t"], c["nome"]), reverse=True)
    return {"cfg": cfg, "padrao": PADRAO, "pasta": str(pasta), "pasta_ok": pasta.is_dir(), "livre": livre,
            "estado": estado(), "resumo": resumo(agora, cfg), "copias": copias,
            "usado": sum(c["bytes"] for c in copias), "rodando": _BACKUP.locked()}


def fazer(tipo: str, agora: int | None = None) -> dict:
    """Uma cópia agora na pasta local, verificada, e a retenção. Registra o resultado em backup-estado.json.
    409 se já tem uma cópia em andamento."""
    if tipo not in AUTO + AVULSAS:
        raise ds.StoreError(400, "Tipo de backup inválido.")
    if not _BACKUP.acquire(blocking=False):
        raise ds.StoreError(409, "Já tem um backup em andamento.")
    try:
        agora = _agora() if agora is None else agora
        cfg = config()
        pasta = pasta_local(cfg)
        try:
            if not pasta.parent.is_dir():
                raise ds.StoreError(500, "Pasta do backup não encontrada.")
            pasta.mkdir(exist_ok=True)
            for e in os.scandir(pasta):   # .part de uma cópia que caiu no meio
                if e.name.endswith(".part") and NOME_RE.fullmatch(e.name[:-5]):
                    store._remove(Path(e.path))
            info = gravar_zip(instantaneo(), pasta, tipo, agora)
        except Exception as exc:
            est = estado()
            curto = str(exc) if isinstance(exc, ds.StoreError) else "falha ao gravar a cópia (%s)" % type(exc).__name__
            est["ultima_falha"] = {"t": agora, "destino": "local", "erro": curto.rstrip("."), "detalhe": str(exc)[:300]}
            est["falhas_seguidas"] += 1
            _grava_estado(est)
            raise
        for nome in reter(listar(pasta), cfg["ret"], cfg["limite_mb"] * 1024 * 1024):
            store._remove(pasta / nome)
        est = estado()
        est["ultimo_ok"] = info
        est["falhas_seguidas"] = 0
        _grava_estado(est)
        return info
    finally:
        _BACKUP.release()


def tarefa(agora: int) -> None:
    """Uma rodada da thread de fundo do servidor: faz a cópia se for a hora. A primeira rodada marca o início."""
    if _INICIO["t"] is None:
        _INICIO["t"] = agora
    tipo = deve_rodar(agora, config(), estado(), _INICIO["t"])
    if tipo:
        try:
            fazer(tipo, agora)
        except ds.StoreError as exc:
            if exc.status != 409:   # 409: uma cópia manual está rodando agora; a próxima rodada decide de novo
                print("[backup] %s" % exc, file=sys.stderr)
