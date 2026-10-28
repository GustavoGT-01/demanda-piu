"""Aviso por e-mail das demandas: configuração da conta de envio, fila em disco, envio SMTP e registro.

A ação grava a demanda; depois, fora do LOCK do banco, o api.py chama enfileirar() (só grava a fila, milissegundos).
A thread de fundo do servidor chama tarefa(agora) a cada minuto e envia o que venceu, até RITMO por rodada, com
novas tentativas espaçadas. Nada daqui lê o demandas.json: cada item da fila leva uma foto dos dados da demanda.
Arquivos em data/: email.json (configuração; senha cifrada pelo Windows, DPAPI), email-fila.json, email-log.json.
Estudo: docs/estudos/04-email.md.
"""

from __future__ import annotations

import base64
import html
import json
import re
import secrets
import smtplib
import ssl
import sys
import threading
import time
from email.message import EmailMessage
from email.utils import formatdate, parseaddr

import store

EVENTOS = ("created", "started", "done", "nudge", "late", "comment", "canc")
SEGURANCA = ("starttls", "ssl", "nenhuma")
FILA_SETOR = ("setor_ou_pessoas", "so_setor", "pessoas")
PADRAO = {"ligado": False, "host": "", "porta": 587, "seguranca": "starttls", "usuario": "", "remetente": "",
          "link_base": "", "eventos": {e: e == "created" for e in EVENTOS}, "copia_solicitante": False,
          "fila_setor": "setor_ou_pessoas", "descricao": True}
EMAIL_RE = re.compile(r"^[^@\s,;<>\"]{1,64}@[A-Za-z0-9.-]{1,252}\.[A-Za-z]{2,}$")
HOST_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
LINK_RE = re.compile(r"^https?://[^\s<>\"']{1,200}$")
ESPERAS_MIN = (1, 5, 15, 60, 180)   # depois da 1ª, 2ª... falha temporária; a 6ª tira da fila
FILA_MAX = 500
LOG_MAX = 2000
RITMO = 20            # envios por rodada da thread (uma por minuto): abaixo dos 30/min do Microsoft 365
TIMEOUT = 20
DESC_MAX = 400
ERRO_MAX = 200
PARA_MAX = 20
EV_TEXTO = {"created": "Nova demanda para você", "started": "A demanda foi aceita e começou",
            "done": "A demanda foi concluída", "nudge": "Cobrança: pediram atenção a esta demanda",
            "late": "A demanda passou do prazo", "comment": "Novo comentário na demanda",
            "canc": "A demanda foi cancelada"}

FILA_LOCK = threading.Lock()   # fila e registro; nunca junto com o LOCK do banco
_RODADA: dict = {"t": None}    # quando a thread passou por aqui pela última vez


class EmailErro(Exception):
    def __init__(self, status: int, msg: str):
        self.status = status
        super().__init__(msg)


def _agora() -> int:
    return int(time.time() * 1000)


def _cfg_path():
    return store.data_dir() / "email.json"


def _fila_path():
    return store.data_dir() / "email-fila.json"


def _log_path():
    return store.data_dir() / "email-log.json"


def _le(p) -> dict:
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


# ---------- senha: DPAPI do Windows (presa ao usuário que roda o programa) ----------

def _dpapi(dados: bytes, cifra: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(dados, len(dados))
    entra, sai = Blob(len(dados), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), Blob()
    crypt32 = ctypes.windll.crypt32   # AttributeError fora do Windows
    f = crypt32.CryptProtectData if cifra else crypt32.CryptUnprotectData
    if not f(ctypes.byref(entra), None, None, None, None, 0x1, ctypes.byref(sai)):   # 0x1: nunca abrir janela
        raise OSError("DPAPI recusou")
    try:
        return ctypes.string_at(sai.pbData, sai.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(sai.pbData, ctypes.c_void_p))


def _protege(texto: str) -> dict:
    """{"dpapi": base64} no Windows; sem DPAPI, {"texto": ...} (a tela avisa)."""
    try:
        return {"dpapi": base64.b64encode(_dpapi(texto.encode("utf-8"), True)).decode("ascii")}
    except (OSError, AttributeError, ValueError):
        return {"texto": texto}


def _desprotege(s):
    """A senha guardada; None se não há ou não abre (outro usuário do Windows, outro PC: digitar de novo)."""
    if not isinstance(s, dict):
        return None
    if isinstance(s.get("dpapi"), str):
        try:
            return _dpapi(base64.b64decode(s["dpapi"], validate=True), False).decode("utf-8")
        except (OSError, AttributeError, ValueError):
            return None
    return s["texto"] if isinstance(s.get("texto"), str) else None


# ---------- configuração ----------

def _remetente_ok(v) -> bool:
    if not isinstance(v, str) or len(v) > 300 or any(c in v for c in "\r\n"):
        return False
    nome, addr = parseaddr(v)
    return bool(addr) and EMAIL_RE.fullmatch(addr) is not None


def _campos(raw: dict, base: dict, estrito: bool) -> dict:
    out = json.loads(json.dumps(base))

    def ruim(msg):
        if estrito:
            raise EmailErro(400, msg)

    def campo(k, ok, msg):
        if k in raw:
            if ok(raw[k]):
                out[k] = raw[k].strip() if isinstance(raw[k], str) else raw[k]
            else:
                ruim(msg)

    eh_bool = lambda v: isinstance(v, bool)   # noqa: E731
    campo("ligado", eh_bool, "Ligado/desligado inválido.")
    campo("copia_solicitante", eh_bool, "Opção de cópia inválida.")
    campo("descricao", eh_bool, "Opção da descrição inválida.")
    campo("host", lambda v: isinstance(v, str) and (not v.strip() or HOST_RE.fullmatch(v.strip()) is not None),
          "Servidor inválido: use só o nome, como smtp.empresa.com.br.")
    campo("porta", lambda v: isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 65535, "Porta inválida: de 1 a 65535.")
    campo("seguranca", lambda v: v in SEGURANCA, "Segurança inválida.")
    campo("usuario", lambda v: isinstance(v, str) and len(v) <= 254 and not any(ord(c) < 32 for c in v), "Usuário inválido.")
    campo("remetente", lambda v: isinstance(v, str) and (not v.strip() or _remetente_ok(v.strip())),
          "Remetente inválido: use demandas@empresa.com.br ou Central de demandas <demandas@empresa.com.br>.")
    campo("link_base", lambda v: isinstance(v, str) and (not v.strip() or LINK_RE.fullmatch(v.strip()) is not None),
          "Endereço da Central inválido: use algo como http://192.168.0.20:8090.")
    campo("fila_setor", lambda v: v in FILA_SETOR, "Destino da fila do setor inválido.")
    if "eventos" in raw:
        ev = raw["eventos"]
        if not isinstance(ev, dict):
            ruim("Eventos inválidos.")
        else:
            for k in EVENTOS:
                if k in ev:
                    if isinstance(ev[k], bool):
                        out["eventos"][k] = ev[k]
                    else:
                        ruim("Eventos inválidos.")
    return out


def _bruta() -> dict:
    """Configuração com a senha guardada (só para uso interno: nunca vai para a tela)."""
    raw = _le(_cfg_path())
    cfg = _campos(raw, PADRAO, estrito=False)
    cfg["senha"] = raw.get("senha") if isinstance(raw.get("senha"), dict) else None
    cfg["instalacao"] = raw["instalacao"] if isinstance(raw.get("instalacao"), str) and re.fullmatch(r"[a-z0-9]{6}", raw["instalacao"]) else ""
    return cfg


def config() -> dict:
    """Para a tela: sem a senha; diz só se há uma e se ela abre neste PC."""
    cfg = _bruta()
    s = cfg.pop("senha")
    cfg.pop("instalacao")
    cfg["tem_senha"] = s is not None
    cfg["senha_abre"] = s is not None and _desprotege(s) is not None
    cfg["senha_texto"] = isinstance(s, dict) and "texto" in s   # sem DPAPI: a tela avisa
    return cfg


def salvar_config(body: dict) -> dict:
    """Só os campos enviados mudam. "senha": ausente/None mantém, "" apaga, texto troca. Ligado exige servidor e
    remetente."""
    if not isinstance(body, dict):
        raise EmailErro(400, "Pedido inválido.")
    atual = _bruta()
    cfg = _campos(body, {k: v for k, v in atual.items() if k != "senha"}, estrito=True)   # instalação: abaixo
    senha = atual["senha"]
    if "senha" in body and body["senha"] is not None:
        if not isinstance(body["senha"], str) or len(body["senha"]) > 500:
            raise EmailErro(400, "Senha inválida.")
        senha = _protege(body["senha"]) if body["senha"] else None
    if cfg["ligado"] and (not cfg["host"] or not cfg["remetente"]):
        raise EmailErro(400, "Para ligar o e-mail, preencha o servidor e o remetente.")
    gravar = dict(cfg, v=1, instalacao=atual["instalacao"] or "".join(secrets.choice("abcdefghijkmnpqrstuvwxyz23456789")
                                                                       for _ in range(6)))
    if senha is not None:
        gravar["senha"] = senha
    store.atomic_write(_cfg_path(), json.dumps(gravar, ensure_ascii=False))
    return config()


# ---------- mensagem ----------

def _quando(ms) -> str:
    return time.strftime("%d/%m/%Y %H:%M", time.localtime(ms / 1000)) if isinstance(ms, (int, float)) else ""


def _dominio(cfg: dict) -> str:
    addr = parseaddr(cfg.get("remetente") or "")[1]
    return addr.rsplit("@", 1)[1] if "@" in addr else "central-demandas.local"


def _linhas(item: dict) -> list:
    """(rótulo, valor) do corpo; vazio sai."""
    d = item["dados"]
    pares = [("Solicitação", item["dem"]), ("Título", d.get("titulo")), ("De", d.get("de")), ("Para", d.get("para")),
             ("Prioridade", d.get("prio")), ("Prazo", _quando(d.get("prazo"))), ("Motivo", d.get("motivo")),
             ("Tipo", d.get("tipo")), ("Por", d.get("quem")), ("Observação", d.get("nota")), ("Descrição", d.get("desc"))]
    return [(k, str(v)) for k, v in pares if v not in (None, "")]


def montar(item: dict, cfg: dict) -> EmailMessage:
    """Um fio por demanda: assunto sempre "[SOL-n] título"; o 1º (created) tem Message-ID fixo e os outros
    respondem a ele (In-Reply-To/References). Texto e HTML; tudo que vem do usuário escapado no HTML."""
    dem, ev, d = item["dem"], item["ev"], item["dados"]
    inst, dom = cfg.get("instalacao") or "central", _dominio(cfg)
    raiz = "<%s.%s@%s>" % (dem, inst, dom)
    msg = EmailMessage()
    msg["Subject"] = "[%s] %s" % (dem, d.get("titulo") or "")
    msg["From"] = cfg["remetente"]
    msg["To"] = ", ".join(item["para"])
    if item.get("cc"):
        msg["Cc"] = ", ".join(item["cc"])
    msg["Date"] = formatdate(localtime=True)
    if ev == "created":
        msg["Message-ID"] = raiz
    else:
        msg["Message-ID"] = "<%s.%s.%s@%s>" % (dem, item["id"], inst, dom)
        msg["In-Reply-To"] = raiz
        msg["References"] = raiz
    msg["Auto-Submitted"] = "auto-generated"   # RFC 3834: resposta automática de férias não responde
    msg["X-Central-Demanda"] = dem
    linhas, titulo = _linhas(item), EV_TEXTO.get(ev, "Aviso da Central de demandas")
    link = cfg.get("link_base", "").rstrip("/") + "/#" + dem if cfg.get("link_base") else ""
    rodape = ("E-mail automático da Central de demandas. Para não receber mais, peça ao escritório para tirar seu "
              "e-mail do cadastro.")
    texto = [titulo, ""] + ["%s: %s" % kv for kv in linhas]
    if link:
        texto += ["", "Abrir a demanda: " + link, "(o link só abre dentro da rede da fábrica)"]
    msg.set_content("\n".join(texto + ["", rodape]) + "\n")
    e = lambda s: html.escape(s, quote=True)   # noqa: E731
    tabela = "".join('<tr><td style="padding:4px 12px 4px 0;color:#5b6478;vertical-align:top;white-space:nowrap">%s</td>'
                     '<td style="padding:4px 0;color:#111827">%s</td></tr>' % (e(k), e(v).replace("\n", "<br>"))
                     for k, v in linhas)
    botao = ('<p style="margin:18px 0 4px"><a href="%s" style="background:#0C1224;color:#ffffff;padding:10px 16px;'
             'border-radius:8px;text-decoration:none;font-weight:bold">Abrir a demanda</a></p>'
             '<p style="margin:0;color:#8a93a6;font-size:12px">O link só abre dentro da rede da fábrica.</p>' % e(link)) if link else ""
    msg.add_alternative(
        '<!doctype html><html><body style="margin:0;padding:16px;background:#f3f5f9;font-family:Segoe UI,Arial,sans-serif">'
        '<table role="presentation" width="600" style="max-width:600px;background:#ffffff;border-radius:12px;padding:20px">'
        '<tr><td><p style="margin:0 0 4px;color:#5b6478;font-size:13px">Central de demandas</p>'
        '<h1 style="margin:0 0 14px;font-size:20px;color:#111827">%s</h1>'
        '<table role="presentation" style="font-size:14px;border-collapse:collapse">%s</table>%s'
        '<p style="margin:20px 0 0;color:#8a93a6;font-size:12px">%s</p></td></tr></table></body></html>'
        % (e(titulo), tabela, botao, e(rodape)), subtype="html")
    return msg


# ---------- envio ----------

def enviar_um(msg: EmailMessage, cfg: dict, senha, smtp=smtplib) -> None:
    """Uma conexão por mensagem; STARTTLS na 587 ou SSL na 465 com o certificado conferido. Sempre fecha."""
    ctx = ssl.create_default_context()
    if cfg["seguranca"] == "ssl":
        s = smtp.SMTP_SSL(cfg["host"], cfg["porta"], timeout=TIMEOUT, context=ctx)
    else:
        s = smtp.SMTP(cfg["host"], cfg["porta"], timeout=TIMEOUT)
        if cfg["seguranca"] == "starttls":
            s.starttls(context=ctx)
    try:
        if cfg["usuario"]:
            s.login(cfg["usuario"], senha or "")
        s.send_message(msg)
    finally:
        try:
            s.quit()
        except (smtplib.SMTPException, OSError):
            pass


def _corta(v) -> str:
    if isinstance(v, bytes):
        v = v.decode("utf-8", "replace")
    return " ".join(str(v).split())[:ERRO_MAX]


def _resposta(code, texto) -> str:
    """ "535 5.7.3 Authentication unsuccessful": o servidor manda bytes."""
    return _corta("%s %s" % (code, _corta(texto)))


def classifica(exc) -> tuple:
    """("auth" | "perm" | "temp", texto curto do servidor, sem senha nem conversa)."""
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "auth", _resposta(exc.smtp_code, exc.smtp_error)
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        codes = [c for c, _m in exc.recipients.values()]
        txt = "; ".join("%s: %s" % (r, _resposta(c, m)) for r, (c, m) in exc.recipients.items())
        return ("perm" if codes and all(c >= 500 for c in codes) else "temp"), _corta(txt)
    if isinstance(exc, smtplib.SMTPResponseException):
        return ("perm" if exc.smtp_code >= 500 else "temp"), _resposta(exc.smtp_code, exc.smtp_error)
    if isinstance(exc, (smtplib.SMTPException, OSError)):
        return "temp", _corta(type(exc).__name__ + (": " + str(exc) if str(exc) else ""))
    return "temp", _corta(type(exc).__name__)


# ---------- fila e registro ----------

def _le_fila() -> dict:
    raw = _le(_fila_path())
    itens = raw.get("itens") if isinstance(raw.get("itens"), list) else []
    pausada = raw.get("pausada") if isinstance(raw.get("pausada"), dict) else None
    return {"v": 1, "itens": [i for i in itens if isinstance(i, dict) and isinstance(i.get("id"), str)], "pausada": pausada}


def _grava_fila(f: dict) -> None:
    store.atomic_write(_fila_path(), json.dumps(f, ensure_ascii=False))


def _registra(itens: list) -> None:
    """Com FILA_LOCK: acrescenta ao email-log.json, só os LOG_MAX mais novos."""
    raw = _le(_log_path())
    velhos = raw.get("itens") if isinstance(raw.get("itens"), list) else []
    store.atomic_write(_log_path(), json.dumps({"v": 1, "itens": (velhos + itens)[-LOG_MAX:]}, ensure_ascii=False))


def _linha_log(item: dict, status: str, t: int, erro: str = "") -> dict:
    linha = {"t": t, "dem": item["dem"], "ev": item["ev"], "para": item["para"] + item["cc"], "status": status,
             "tent": item["tent"], "erro": erro}
    if status == "falhou":   # guarda o item: "Reenviar as falhas" põe de volta na fila
        linha["item"] = item
    return linha


def enfileirar(envios: list, agora: int | None = None) -> int:
    """Chamado pelo api.py depois de gravar, fora do LOCK do banco. E-mail desligado: não guarda nada para depois.
    Sem destinatário: só anota no registro. Fila cheia: a mais antiga sai para o registro como "descartado".
    Erro de disco não sobe: a demanda já foi gravada e o aviso não pode derrubar a resposta."""
    agora = _agora() if agora is None else agora
    try:
        if not envios or not _bruta()["ligado"]:
            return 0
        with FILA_LOCK:
            f, log, n = _le_fila(), [], 0
            for e in envios:
                item = {"id": secrets.token_hex(4), "dem": e["dem"], "ev": e["ev"], "para": list(e["para"]),
                        "cc": list(e.get("cc") or []), "dados": e["dados"], "criado": agora, "tent": 0, "prox": agora, "erro": ""}
                if not item["para"]:
                    log.append(_linha_log(item, "sem_destinatario", agora))
                    continue
                f["itens"].append(item)
                n += 1
            while len(f["itens"]) > FILA_MAX:
                log.append(_linha_log(f["itens"].pop(0), "descartado", agora, "fila cheia"))
            if n:
                _grava_fila(f)
            if log:
                _registra(log)
            return n
    except (OSError, ValueError) as exc:
        print("[e-mail] não enfileirou: %r" % exc, file=sys.stderr)
        return 0


def tarefa(agora: int, enviar=enviar_um) -> None:
    """Uma rodada da thread de fundo: manda até RITMO itens vencidos, um de cada vez. Falha temporária volta para a
    fila com espera crescente; a 6ª, ou erro permanente (5xx), sai para o registro como "falhou". Usuário ou senha
    recusados (535) pausam a fila inteira: insistir pode bloquear a conta."""
    _RODADA["t"] = agora
    cfg = _bruta()
    if not cfg["ligado"]:
        return
    with FILA_LOCK:
        f = _le_fila()
        if f["pausada"]:
            return
        vez = [i for i in f["itens"] if isinstance(i.get("prox"), (int, float)) and i["prox"] <= agora][:RITMO]
    senha = _desprotege(cfg["senha"])
    for item in vez:
        try:
            enviar(montar(item, cfg), cfg, senha)
            tipo, erro = "ok", ""
        except Exception as exc:
            tipo, erro = classifica(exc)
        with FILA_LOCK:
            f = _le_fila()
            atual = next((i for i in f["itens"] if i["id"] == item["id"]), None)
            if atual is None:   # limpo pela tela enquanto enviava
                continue
            if tipo == "auth":
                atual["erro"] = erro
                f["pausada"] = {"t": agora, "erro": erro}
                _grava_fila(f)
                return
            atual["tent"] += 1
            if tipo == "temp" and atual["tent"] <= len(ESPERAS_MIN):
                atual["prox"] = agora + ESPERAS_MIN[atual["tent"] - 1] * 60000
                atual["erro"] = erro
                _grava_fila(f)
                continue
            f["itens"].remove(atual)
            _grava_fila(f)
            _registra([_linha_log(atual, "ok" if tipo == "ok" else "falhou", agora, erro)])


def _falha_aberta(i: dict) -> bool:
    """Falha que ainda conta: nem reenviada nem limpa pela tela."""
    return i.get("status") == "falhou" and not i.get("reenviado") and not i.get("limpa")


def _dia(ms) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ms / 1000))


def estado(agora: int | None = None) -> dict:
    """Para a seção E-mail: fila, falhas, pausa, enviados hoje e os últimos do registro (sem o item guardado)."""
    agora = _agora() if agora is None else agora
    with FILA_LOCK:
        f = _le_fila()
        raw = _le(_log_path())
    log = [i for i in raw.get("itens") if isinstance(i, dict)] if isinstance(raw.get("itens"), list) else []
    com_t = [i for i in log if isinstance(i.get("t"), int)]
    return {"pendentes": len(f["itens"]), "tentando": sum(1 for i in f["itens"] if i.get("tent")),
            "proxima": min((i["prox"] for i in f["itens"] if isinstance(i.get("prox"), (int, float))), default=None),
            "pausada": f["pausada"], "falhas_24h": sum(1 for i in com_t if _falha_aberta(i) and agora - i["t"] < 86400000),
            "enviados_hoje": sum(1 for i in com_t if i.get("status") == "ok" and _dia(i["t"]) == _dia(agora)),
            "ultima_rodada": _RODADA["t"], "log": [{k: v for k, v in i.items() if k != "item"} for i in log[-20:][::-1]]}


def fila_acao(acao, agora: int | None = None) -> int:
    """Botões da seção E-mail. "retomar": tira a pausa (depois de corrigir a senha) e manda tudo na próxima rodada;
    "reenviar_falhas": as falhas guardadas voltam para a fila do zero; "limpar_falhas": deixam de contar como falha.
    Devolve quantos itens a ação mexeu."""
    agora = _agora() if agora is None else agora
    if acao not in ("retomar", "reenviar_falhas", "limpar_falhas"):
        raise EmailErro(400, "Ação da fila inválida.")
    with FILA_LOCK:
        f = _le_fila()
        if acao == "retomar":
            f["pausada"] = None
            for i in f["itens"]:
                i["prox"] = agora
            _grava_fila(f)
            return len(f["itens"])
        raw = _le(_log_path())
        log = [i for i in raw.get("itens") if isinstance(i, dict)] if isinstance(raw.get("itens"), list) else []
        abertas = [i for i in log if _falha_aberta(i)]
        for i in abertas:
            if acao == "limpar_falhas":
                i["limpa"] = True
            elif isinstance(i.get("item"), dict):
                f["itens"].append(dict(i["item"], id=secrets.token_hex(4), tent=0, prox=agora, erro=""))
                i["reenviado"] = True
        if acao == "reenviar_falhas":
            del f["itens"][:-FILA_MAX]
            _grava_fila(f)
        store.atomic_write(_log_path(), json.dumps({"v": 1, "itens": log}, ensure_ascii=False))
        return len(abertas)


def _traduz(tipo: str, txt: str) -> str:
    if tipo == "auth":
        return "Conectou, mas o usuário ou a senha foram recusados (%s)." % txt
    if tipo == "perm":
        return "O servidor de e-mail recusou: %s." % txt
    return "Não deu para enviar (%s). Confira o servidor, a porta e a segurança." % txt


def teste(body: dict, enviar=enviar_um, relogio=time.monotonic) -> dict:
    """"Enviar teste" na hora, com os dados do formulário (mesmo sem salvar). A senha digitada vale só para o
    teste; sem ela, usa a guardada. {"ok": True, "msg"} ou {"ok": False, "erro"} já em português."""
    if not isinstance(body, dict):
        raise EmailErro(400, "Pedido inválido.")
    para = body.get("para").strip().lower() if isinstance(body.get("para"), str) else ""
    if len(para) > 254 or not EMAIL_RE.fullmatch(para):
        raise EmailErro(400, "E-mail do teste inválido.")
    atual = _bruta()
    cfg = _campos(body, atual, estrito=True)   # só lê os campos conhecidos: "para" e "senha" ficam de fora
    if not cfg["host"] or not cfg["remetente"]:
        raise EmailErro(400, "Para testar, preencha o servidor e o remetente.")
    senha = body["senha"] if isinstance(body.get("senha"), str) and body["senha"] else _desprotege(atual["senha"])
    msg = EmailMessage()
    msg["Subject"] = "Teste da Central de demandas"
    msg["From"] = cfg["remetente"]
    msg["To"] = para
    msg["Date"] = formatdate(localtime=True)
    msg["Auto-Submitted"] = "auto-generated"
    msg.set_content("Se você recebeu este e-mail, a Central de demandas consegue mandar avisos por esta conta.\n")
    t0 = relogio()
    try:
        enviar(msg, cfg, senha)
    except Exception as exc:
        return {"ok": False, "erro": _traduz(*classifica(exc))}
    modo = {"starttls": "com STARTTLS", "ssl": "com SSL/TLS", "nenhuma": "sem criptografia"}[cfg["seguranca"]]
    return {"ok": True, "msg": "Enviado para %s · conectou em %s:%d %s em %s s. Confira a caixa de entrada (e o spam)."
            % (para, cfg["host"], cfg["porta"], modo, ("%.1f" % (relogio() - t0)).replace(".", ","))}


def do_log(dems) -> dict:
    """{SOL-n: [{t, ev, para, status}]} do registro, para as linhas ✉ na gaveta do ADM."""
    alvo = set(dems)
    raw = _le(_log_path())
    out: dict = {}
    for i in raw.get("itens") if isinstance(raw.get("itens"), list) else []:
        if isinstance(i, dict) and i.get("dem") in alvo:
            out.setdefault(i["dem"], []).append({k: i.get(k) for k in ("t", "ev", "para", "status")})
    return out
