"""Servidor local da Central de demandas: entrega a página, os arquivos do módulo e a API.

Acesso: o próprio computador entra direto (papel "maquina", o Escritório); pela rede,
com o acesso ligado, só com PIN. O PIN do escritório abre tudo ("completo"); o PIN dos operadores só alcança a tela
de operador das demandas ("operador"). O papel chega ao demandas/api.py em ctx["papel"].
Só biblioteca padrão. Rodar: py -3 servidor.py (ou iniciar.bat).
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import ipaddress
import json
import os
import platform
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

import store

ROOT = Path(__file__).resolve().parent
MOD = ROOT / "demandas"
WEB = ROOT / "web"
HOST = "127.0.0.1"
PORT = int(os.environ.get("DEMANDAS_PORT") or 8090)   # DEMANDAS_PORT troca a porta
VERSAO = "1.0.0"
INICIO_MS = int(time.time() * 1000)   # vai no /api/rev: mudou = o servidor reiniciou
LOG_MAX = 500                         # linhas guardadas em data/servidor.log
SAIDA_MAX = 1024 * 1024               # data/servidor-saida.log passa disto: vira .1 ao religar
MAX_BODY = 16 * 1024 * 1024   # anexo de 5 MB em base64 cabe com folga
MAX_BODY_ANON = 64 * 1024     # da rede sem sessão (só o PIN entra)
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".woff2": "font/woff2",
         ".html": "text/html; charset=utf-8"}

# Acesso pela rede (data/rede.json). Fora da máquina tudo exige o PIN; a própria máquina entra direto.
NET_ON = False          # estado em uso: só muda ao religar o servidor (é ele que escolhe a interface)
SESSIONS: dict = {}     # sha256 do cookie -> {"exp", "papel"}; cópia em data/sessoes.json (nunca o cookie)
PAPEIS = ("completo", "operador")   # PIN do escritório (tudo) ou PIN dos operadores (só a tela de operador)
FAILS: dict = {}        # IP -> [erros, bloqueado até]
NET_LOCK = threading.RLock()
SESSION_DAYS = 30
COOKIE = "demandas_s"
LOGIN_PAGE = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Central de demandas</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0C1224;color:#E7ECFA;font:16px system-ui,sans-serif}
form{background:#151E38;border:1px solid #263457;border-radius:18px;padding:28px;width:min(320px,calc(100vw - 32px));box-sizing:border-box;display:grid;gap:14px}
h1{font-size:20px;margin:0}p{margin:0;color:#93A0BF;font-size:14px}input{font:inherit;font-size:22px;letter-spacing:.3em;text-align:center;padding:10px;border-radius:10px;border:1px solid #263457;background:#0C1224;color:inherit}
button{font:inherit;font-weight:700;padding:11px;border:0;border-radius:10px;background:#FFFFFF;color:#0C1224;cursor:pointer}.e{color:#EF5B67}</style></head>
<body><form method="post" action="/api/login"><h1>Central de demandas</h1><p>Digite o PIN mostrado no computador principal, em ⚙ Configurações.</p>
%s<input name="pin" inputmode="numeric" autocomplete="one-time-code" maxlength="12" required autofocus aria-label="PIN"><button>Entrar</button></form></body></html>"""

# Sessão do PIN dos operadores: lista fechada, todo o resto é 403 (HEAD conta como GET). As rotas de ADM das demandas
# (setor/, pessoa/, prioridade, estender, crono, historico, GET anexo/<id>) ficam de fora; o api.py recusa de novo.
OPERADOR_ROTAS = frozenset({
    ("GET", "/"), ("GET", "/index.html"), ("GET", "/app.js"), ("GET", "/api/eu"), ("GET", "/api/rev"),
    ("GET", "/api/local/demandas"),
})
OPERADOR_RE = re.compile(r"GET /local/demandas/[A-Za-z0-9_-][A-Za-z0-9_.-]{0,59}"
                         r"|POST /api/local/demandas/(entrar|sair|vista|demanda/(criar|aceitar|pausar|retomar|concluir"
                         r"|cancelar|reatribuir|cobrar|comentar)|anexo/(enviar|ler|apagar)|nota/(lida|todas))")
OPERADOR_MSG = "Aparelho de operador: só a tela de operador das demandas."
FILE_RE = re.compile(r"^[A-Za-z0-9_-]{1,60}\.(js|css|woff2)$")


# ---------- módulo ----------
_API: list = []


def api_mod():
    """demandas/api.py, carregado uma vez (a pasta entra no sys.path para os imports irmãos do módulo)."""
    if not _API:
        if str(MOD) not in sys.path:
            sys.path.insert(0, str(MOD))
        spec = importlib.util.spec_from_file_location("demandas_api", MOD / "api.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _API.append(mod)
    return _API[0]


def backup_mod():
    """demandas/demandas_backup.py; mesmo demandas_store (e o mesmo LOCK) que o api.py usa."""
    api_mod()
    import demandas_backup
    return demandas_backup


def email_mod():
    """email_envio.py (raiz): a conta de envio é da máquina, como a rede; o api.py usa o mesmo módulo."""
    api_mod()
    import email_envio
    return email_envio


# ---------- thread de fundo ----------
def fundo(tarefas, parar: threading.Event, intervalo: float = 60, relogio=None) -> None:
    """Roda cada tarefa(agora em ms) logo ao ligar e depois a cada intervalo, até parar. A falha de uma tarefa não
    derruba as outras nem a thread."""
    relogio = relogio or (lambda: int(time.time() * 1000))
    while True:
        agora = relogio()
        for t in tarefas:
            try:
                t(agora)
            except Exception as exc:
                print("[fundo] %s: %r" % (getattr(t, "__name__", t), exc), file=sys.stderr)
        if parar.wait(intervalo):
            return


def iniciar_fundo(tarefas, intervalo: float = 60, relogio=None) -> threading.Event:
    """Uma só thread daemon para as tarefas periódicas (backup; depois atraso e e-mail). Devolve o Event que a para."""
    parar = threading.Event()
    threading.Thread(target=fundo, args=(list(tarefas), parar, intervalo, relogio), name="fundo", daemon=True).start()
    return parar


def static_files() -> tuple:
    return tuple(f for f in getattr(api_mod(), "STATIC", ()) if isinstance(f, str) and FILE_RE.match(f))


_REV: dict = {"key": None, "rev": 0}


def rev() -> int:
    """rev do demandas.json sem ler o arquivo a cada consulta (a tela pergunta a cada 3 s)."""
    p = store.data_dir() / getattr(api_mod(), "REV_FILE", "demandas.json")
    try:
        st = p.stat()
    except OSError:
        return 0
    key = (st.st_mtime_ns, st.st_size)
    if _REV["key"] != key:
        try:
            r = json.loads(p.read_text(encoding="utf-8")).get("rev")
        except (OSError, ValueError, AttributeError):
            return _REV["rev"]
        _REV.update(key=key, rev=r if isinstance(r, int) and not isinstance(r, bool) else 0)
    return _REV["rev"]


# ---------- rede e PIN ----------
def _net_path() -> Path:
    return store.data_dir() / "rede.json"


def _pin_ok(pin) -> bool:
    return isinstance(pin, str) and pin.isdigit() and len(pin) >= 6


def _pin_novo(outro: str = "") -> str:
    """6 dígitos aleatórios, nunca iguais ao outro PIN (senão o perfil do login seria ambíguo)."""
    while True:
        pin = "%06d" % secrets.randbelow(10**6)
        if pin != outro:
            return pin


def net_config() -> dict:
    """{"on": bool, "pin": "6 dígitos", "pin_op": "6 dígitos"}; cria os PINs aleatórios na primeira leitura."""
    with NET_LOCK:
        try:
            cfg = json.loads(_net_path().read_text(encoding="utf-8"))
            if isinstance(cfg, dict) and _pin_ok(cfg.get("pin")):
                out = {"on": cfg.get("on") is True, "pin": cfg["pin"], "pin_op": cfg.get("pin_op")}
                if _pin_ok(out["pin_op"]) and out["pin_op"] != out["pin"]:
                    return out
                out["pin_op"] = _pin_novo(out["pin"])
                store.atomic_write(_net_path(), json.dumps(out))
                return out
        except (OSError, ValueError):
            pass
        pin = _pin_novo()
        cfg = {"on": False, "pin": pin, "pin_op": _pin_novo(pin)}
        store.atomic_write(_net_path(), json.dumps(cfg))
        return cfg


def net_save(on=None, new_pin: bool = False, new_pin_op: bool = False) -> dict:
    with NET_LOCK:
        cfg = net_config()
        if on is not None:
            cfg["on"] = bool(on)
        if new_pin:
            cfg["pin"] = _pin_novo(cfg["pin_op"])
            SESSIONS.clear()  # PIN novo derruba quem entrou com o antigo
            _sessions_write()
        if new_pin_op:
            cfg["pin_op"] = _pin_novo(cfg["pin"])
            for h in [h for h, s in SESSIONS.items() if s["papel"] == "operador"]:   # só os aparelhos de operador saem
                del SESSIONS[h]
            _sessions_write()
        store.atomic_write(_net_path(), json.dumps(cfg))
    return cfg


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _sessions_write() -> None:
    """Chamar dentro de NET_LOCK. Só o hash: quem lê o arquivo não consegue entrar com ele."""
    store.atomic_write(store.data_dir() / "sessoes.json", json.dumps(SESSIONS))


def sessions_load() -> None:
    """Sessões do PIN sobrevivem ao reinício do servidor; arquivo ruim = ninguém logado."""
    with NET_LOCK:
        try:
            raw = json.loads((store.data_dir() / "sessoes.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        for h, val in raw.items():
            exp, papel = (val.get("exp"), val.get("papel")) if isinstance(val, dict) else (None, None)
            if isinstance(h, str) and re.fullmatch(r"[0-9a-f]{64}", h) and papel in PAPEIS \
                    and isinstance(exp, (int, float)) and not isinstance(exp, bool) and exp > time.time():
                SESSIONS[h] = {"exp": float(exp), "papel": papel}


def lan_addresses() -> list:
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return []
    return sorted({i[4][0] for i in infos if not i[4][0].startswith(("127.", "169.254."))})


def check_pin(ip: str, pin: str, now: float | None = None) -> str | None:
    """Token de sessão se um dos PINs confere; None se errado ou IP bloqueado (5 erros = 5 minutos parado).
    O PIN digitado decide o perfil: o do escritório dá tudo, o dos operadores só a tela de operador."""
    now = time.time() if now is None else now
    with NET_LOCK:
        cfg = net_config()
        count, until = FAILS.get(ip, [0, 0.0])
        if until > now:
            return None
        given = pin.encode("utf-8")
        completo = hmac.compare_digest(given, cfg["pin"].encode("utf-8"))
        oper = hmac.compare_digest(given, cfg["pin_op"].encode("utf-8"))   # sempre os dois: o tempo não diz qual errou
        if not (completo or oper):
            count += 1
            FAILS[ip] = [0, now + 300] if count >= 5 else [count, 0.0]
            return None
        FAILS.pop(ip, None)
        for tok in [t for t, s in SESSIONS.items() if s["exp"] < now]:
            del SESSIONS[tok]
        if len(SESSIONS) >= 200:  # teto: descarta a sessão mais antiga
            del SESSIONS[min(SESSIONS, key=lambda t: SESSIONS[t]["exp"])]
        token = secrets.token_urlsafe(32)
        SESSIONS[_token_hash(token)] = {"exp": now + SESSION_DAYS * 86400, "papel": "completo" if completo else "operador"}
        _sessions_write()
        return token


def session_ok(cookie_header: str | None) -> str | None:
    """Perfil da sessão do cookie ("completo" ou "operador"); None = sem sessão válida."""
    for part in (cookie_header or "").split(";"):
        name, _, value = part.strip().partition("=")
        if name == COOKIE and value:
            with NET_LOCK:
                s = SESSIONS.get(_token_hash(value))
            return s["papel"] if s is not None and s["exp"] > time.time() else None
    return None


def pode(papel, acao: str) -> bool:
    """Autorização das telas de sistema num lugar só. "configurar" (⚙ Configurações: rede, backup): só o computador
    principal. Na hospedagem, muda aqui e não em cada rota."""
    return acao == "configurar" and papel == "maquina"


def ip_host(host: str, port: int) -> bool:
    """Host "IPv4:porta": um IP literal não sofre DNS rebinding, por isso pode vir da rede."""
    name, _, p = host.rpartition(":")
    try:
        return p == str(port) and ipaddress.ip_address(name).version == 4
    except ValueError:
        return False


# ---------- HTTP ----------
class Handler(BaseHTTPRequestHandler):
    timeout = 60   # segundos sem receber nada: cliente lento ou parado não prende a thread para sempre
    papel = None

    def log_message(self, fmt, *args):   # sem eco de cada pedido no console
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")  # no-referrer faz o form de PIN mandar Origin: null
        self.send_header("Content-Security-Policy", CSP)
        super().end_headers()

    def _local(self) -> set:
        port = self.server.server_address[1]
        return {"127.0.0.1:%d" % port, "localhost:%d" % port}

    def _host_ok(self) -> bool:
        # Host estranho = outro site apontando um domínio para 127.0.0.1 (DNS rebinding)
        host = self.headers.get("Host")
        if host is None or host in self._local() or (NET_ON and ip_host(host, self.server.server_address[1])):
            return True
        self._fail(421, "Host não aceito.")
        return False

    def _remote(self) -> bool:
        try:
            return not ipaddress.ip_address(self.client_address[0]).is_loopback
        except ValueError:
            return True

    def _auth_ok(self) -> bool:
        """Quem vem da rede precisa da sessão aberta com o PIN; sem ela, a página de entrada.
        Guarda o perfil do pedido em self.papel: "maquina", "completo" ou "operador"."""
        self.papel = None
        if not self._remote():
            self.papel = "maquina"
            return True
        if not NET_ON:
            self._fail(403, "Acesso pela rede desligado.")
            return False
        self.papel = session_ok(self.headers.get("Cookie"))
        if self.papel:
            return True
        if self.command in ("GET", "HEAD") and self.path.split("?", 1)[0] in ("/", "/index.html"):
            self._login_page("")
        else:
            self._fail(401, "Entre com o PIN.")
        return False

    def _operador_ok(self, method: str, path: str) -> bool:
        """Logo depois de _auth_ok em todo verbo: a sessão de operador só alcança OPERADOR_ROTAS. False = já respondeu 403."""
        if self.papel in ("maquina", "completo"):
            return True
        m = "GET" if method == "HEAD" else method
        if self.papel == "operador" and ((m, path) in OPERADOR_ROTAS or OPERADOR_RE.fullmatch(m + " " + path)):
            return True
        self._fail(403, OPERADOR_MSG)   # perfil desconhecido também cai aqui: fecha em vez de abrir
        return False

    def _login_page(self, error: str) -> None:
        self._send(200, (LOGIN_PAGE % ('<p class="e">%s</p>' % error if error else "")).encode("utf-8"), TYPES[".html"])

    def _send(self, status: int, raw: bytes, mime: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)

    def _json(self, obj, status: int = 200) -> None:
        try:
            raw = json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError):
            return self._fail(500, "resposta inválida")
        self._send(status, raw, "application/json; charset=utf-8")

    def _fail(self, status: int, message: str) -> None:
        if status >= 400:
            self.close_connection = True  # o corpo do pedido pode ter ficado sem ler
        self._send(status, message.encode("utf-8"), "text/plain; charset=utf-8")

    def _file(self, path: Path) -> None:
        try:
            raw = path.read_bytes()
        except OSError:
            return self._fail(404, "Não encontrado.")
        self._send(200, raw, TYPES[path.suffix.lower()])

    def _static(self, path: str) -> bool:
        """Só a página, a casca e os arquivos do STATIC do módulo. Nada de pastas, .py ou dados."""
        if path in ("/", "/index.html"):
            self._file(WEB / "index.html")
        elif path == "/app.js":
            self._file(WEB / "app.js")
        elif path.startswith("/local/demandas/") and path[len("/local/demandas/"):] in static_files():
            self._file(MOD / path[len("/local/demandas/"):])
        else:
            return False
        return True

    def _api(self, method: str, path: str, raw: bytes) -> None:
        """/api/local/demandas/<resto> -> handle() do módulo; erro com status vira texto puro (a tela mostra)."""
        rest = path[len("/api/local/demandas"):].lstrip("/") if path != "/api/local/demandas" else ""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeError, ValueError):
            return self._fail(400, "JSON inválido.")
        if not isinstance(body, dict):
            return self._fail(400, "Pedido inválido.")
        try:
            out = api_mod().handle(method, rest, body, {"papel": self.papel, "tab": self.headers.get("X-Tab")})
        except Exception as exc:
            status = getattr(exc, "status", None)
            if isinstance(status, int) and 400 <= status < 600:
                return self._fail(status, str(exc))
            print("[erro] %s %s: %r" % (method, path, exc), file=sys.stderr)
            return self._fail(500, "Erro interno do servidor.")   # sem caminho nem texto do sistema
        if not isinstance(out, dict):
            return self._fail(500, "Resposta do módulo inválida.")
        self._json(out)

    def _backup(self, method: str, path: str, raw: bytes) -> None:
        """/api/backup (GET: painel; POST: salva a configuração), /api/backup/agora, /api/backup/abrir,
        /api/backup/previa {nome} e /api/backup/restaurar {nome, confirmo: "RESTAURAR"}."""
        if not pode(self.papel, "configurar"):
            return self._fail(403, "Só no computador principal.")
        bk = backup_mod()
        acao = path[len("/api/backup"):]
        if (method, acao) not in (("GET", ""), ("POST", ""), ("POST", "/agora"), ("POST", "/abrir"), ("POST", "/previa"),
                                  ("POST", "/restaurar")):
            return self._fail(404, "Não encontrado.")
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeError, ValueError):
            return self._fail(400, "JSON inválido.")
        if not isinstance(body, dict):
            return self._fail(400, "Pedido inválido.")
        try:
            if acao == "" and method == "POST":
                bk.salvar_config(body)
            elif acao == "/agora":
                bk.fazer("manual")
            elif acao == "/abrir":
                pasta = bk.pasta_local(bk.config())
                if not pasta.is_dir():
                    return self._fail(404, "A pasta do backup ainda não existe: faça um backup primeiro.")
                os.startfile(pasta)   # só a pasta configurada, nunca um caminho vindo do pedido
            elif acao == "/previa":
                return self._json(bk.previa(body.get("nome")))
            elif acao == "/restaurar":
                if body.get("confirmo") != "RESTAURAR":
                    return self._fail(400, "Para restaurar, digite RESTAURAR.")
                bk.restaurar(body.get("nome"))
                api_mod().esquecer_pessoas()   # todo mundo se identifica de novo
            return self._json(bk.painel())
        except bk.ds.StoreError as exc:
            return self._fail(exc.status, str(exc))
        except (OSError, AttributeError) as exc:   # AttributeError: os.startfile fora do Windows
            print("[backup] %s %s: %r" % (method, path, exc), file=sys.stderr)
            return self._fail(500, "Falha no backup: veja a janela do servidor.")

    def _email(self, method: str, path: str, raw: bytes) -> None:
        """/api/email (GET: configuração sem a senha e estado da fila; POST: salva), /api/email/teste {para, ...}
        (envia na hora) e /api/email/fila {acao}. Só o computador principal: a conta de envio é da empresa."""
        if not pode(self.papel, "configurar"):
            return self._fail(403, "Só no computador principal.")
        mail = email_mod()
        acao = path[len("/api/email"):]
        if (method, acao) not in (("GET", ""), ("POST", ""), ("POST", "/teste"), ("POST", "/fila")):
            return self._fail(404, "Não encontrado.")
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeError, ValueError):
            return self._fail(400, "JSON inválido.")
        if not isinstance(body, dict):
            return self._fail(400, "Pedido inválido.")
        porta = self.server.server_address[1]
        try:
            extra = {}
            if acao == "" and method == "POST":
                mail.salvar_config(body)
            elif acao == "/teste":
                extra = {"teste": mail.teste(body)}
            elif acao == "/fila":
                extra = {"mexeu": mail.fila_acao(body.get("acao"))}
            return self._json({"cfg": mail.config(), "estado": mail.estado(), **extra,
                               "sugestao_link": ("http://%s:%d" % (lan_addresses()[0], porta)) if NET_ON and lan_addresses()
                               else "http://127.0.0.1:%d" % porta})
        except mail.EmailErro as exc:
            return self._fail(exc.status, str(exc))
        except OSError as exc:
            print("[e-mail] %s %s: %r" % (method, path, exc), file=sys.stderr)
            return self._fail(500, "Falha ao gravar a configuração do e-mail: veja a janela do servidor.")

    def _rede(self) -> dict:
        cfg = net_config()
        port = self.server.server_address[1]
        return {"on": cfg["on"], "pin": cfg["pin"], "pin_op": cfg["pin_op"], "active": NET_ON,
                "urls": ["http://%s:%d" % (a, port) for a in lan_addresses()]}

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if not self._host_ok() or not self._auth_ok() or not self._operador_ok(self.command, path):
            return
        if path == "/api/eu":
            return self._json({"papel": self.papel})
        if path == "/api/rev":
            return self._json({"rev": rev(), "inicio": INICIO_MS})
        if path == "/api/rede":
            if not pode(self.papel, "configurar"):
                return self._fail(403, "Só no computador principal.")
            return self._json(self._rede())
        if path == "/api/backup" or path.startswith("/api/backup/"):
            return self._backup("GET", path, b"")
        if path == "/api/email" or path.startswith("/api/email/"):
            return self._email("GET", path, b"")
        if path == "/api/servidor":
            if not pode(self.papel, "configurar"):
                return self._fail(403, "Só no computador principal.")
            return self._json(saude(self.server.server_address[1]))
        if path == "/api/local/demandas" or path.startswith("/api/local/demandas/"):
            return self._api("GET", path, b"")
        if not self._static(path):
            self._fail(404, "Não encontrado.")

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length"))
        except (TypeError, ValueError):
            length = -1
        if length < 0:
            return self._fail(400, "Content-Length ausente ou inválido.")
        if length > MAX_BODY:
            return self._fail(413, "Arquivo grande demais.")
        if length > MAX_BODY_ANON and self._remote() and not (NET_ON and session_ok(self.headers.get("Cookie"))):
            return self._fail(413, "Entre com o PIN antes de enviar arquivos.")
        # o corpo é lido antes de qualquer recusa: fechar a conexão com dados por ler vira RST no Windows
        data = self.rfile.read(length) if length else b""
        if not self._host_ok():
            return
        origin = self.headers.get("Origin")
        allowed = {"http://" + h for h in self._local()} | {"http://" + (self.headers.get("Host") or "")}
        if origin is not None and origin not in allowed:
            return self._fail(403, "Origem não aceita.")  # outro site postando no servidor
        path = self.path.split("?", 1)[0]
        if path == "/api/login":
            if not (self._remote() and NET_ON):
                return self._fail(403, "Acesso pela rede desligado.")
            pin = (parse_qs(data.decode("utf-8", "replace")).get("pin") or [""])[0].strip()
            token = check_pin(self.client_address[0], pin)
            if token is None:
                return self._login_page("PIN errado. Depois de 5 erros, espere 5 minutos.")
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", "%s=%s; Path=/; HttpOnly; SameSite=Strict; Max-Age=%d" % (COOKIE, token, SESSION_DAYS * 86400))
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if not self._auth_ok() or not self._operador_ok("POST", path):
            return
        if path == "/api/rede":
            if not pode(self.papel, "configurar"):
                return self._fail(403, "Só no computador principal.")
            try:
                body = json.loads(data.decode("utf-8") or "{}")
                net_save(body["on"] if isinstance(body.get("on"), bool) else None, body.get("newpin") is True,
                         body.get("newpin_op") is True)
            except (ValueError, AttributeError, OSError):
                return self._fail(400, "Falha ao gravar a configuração da rede.")
            return self._json(self._rede())
        if path == "/api/backup" or path.startswith("/api/backup/"):
            return self._backup("POST", path, data)
        if path == "/api/email" or path.startswith("/api/email/"):
            return self._email("POST", path, data)
        if path.startswith("/api/local/demandas/"):
            return self._api("POST", path, data)
        self._fail(404, "Não encontrado.")


class Server(ThreadingHTTPServer):
    # Sem reaproveitar a porta: no Windows um segundo servidor ligaria na mesma porta sem erro.
    allow_reuse_address = False
    allow_reuse_port = False
    daemon_threads = True

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


# ---------- ligar sozinho (tarefa agendada) ----------
def registra(texto: str, agora: float | None = None) -> None:
    """Uma linha em data/servidor.log (a seção Servidor mostra as últimas); guarda só as LOG_MAX mais novas."""
    p = store.data_dir() / "servidor.log"
    agora = time.time() if agora is None else agora
    try:
        antigas = p.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        antigas = []
    linha = time.strftime("%d/%m %H:%M", time.localtime(agora)) + "  " + texto
    p.write_text("\n".join((antigas + [linha])[-LOG_MAX:]) + "\n", encoding="utf-8")


def _roda_filho(cmd) -> int:
    """O servidor num processo filho; o que ele imprime vai para data/servidor-saida.log (sem janela na tarefa)."""
    saida = store.data_dir() / "servidor-saida.log"
    try:
        if saida.stat().st_size > SAIDA_MAX:
            os.replace(saida, saida.with_name(saida.name + ".1"))
    except OSError:
        pass
    with open(saida, "ab") as fh:
        return subprocess.call(cmd, stdout=fh, stderr=subprocess.STDOUT)


def sempre(cmd, rodar=_roda_filho, relogio=time.monotonic, dormir=time.sleep, limite: int = 10, janela: float = 120,
           espera: float = 5) -> int:
    """Laço da tarefa agendada: roda o servidor; se ele parar, anota e religa em `espera` s. Parou `limite` vezes em
    `janela` s (erro que se repete, como a porta ocupada por outro servidor): anota e desiste, devolvendo 1."""
    quedas: list = []
    registra("ligado com o Windows (tarefa agendada)")
    while True:
        cod = rodar(cmd)
        if isinstance(cod, int) and cod >= 2 ** 31:   # o Windows devolve o código sem sinal (encerrado = 4294967295)
            cod -= 2 ** 32
        t = relogio()
        quedas = [q for q in quedas if t - q < janela] + [t]
        if len(quedas) >= limite:
            registra("parou %d vezes em %d s (último código %s): desisti. Veja data/servidor-saida.log"
                     % (limite, janela, cod))
            return 1
        registra("parou (código %s) · religado em %d s" % (cod, espera))
        dormir(espera)


TAREFA = "Central de demandas"   # nome da tarefa agendada criada pelo instalar-inicio.ps1


def tarefa_instalada():
    """A tarefa "iniciar com o Windows" existe? None = não deu para saber (fora do Windows, schtasks travado)."""
    try:
        r = subprocess.run(["schtasks", "/query", "/tn", TAREFA], capture_output=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.returncode == 0


def _tamanho(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 0


def saude(porta: int, agora: float | None = None) -> dict:
    """O que a seção Servidor das Configurações mostra (só no computador principal)."""
    agora = time.time() if agora is None else agora
    dados = store.data_dir()
    ds = api_mod().ds
    try:
        uso = shutil.disk_usage(dados)
        disco = {"livre": uso.free, "total": uso.total}
    except OSError:
        disco = None
    try:
        log = (dados / "servidor.log").read_text(encoding="utf-8").splitlines()[-12:]
    except (OSError, ValueError):
        log = []
    bk = backup_mod()
    ok = bk.estado()["ultimo_ok"]
    with NET_LOCK:
        sessoes = sum(1 for s in SESSIONS.values() if s["exp"] > agora)
    anexos = ds.uso_anexos()
    return {"versao": VERSAO, "inicio": INICIO_MS, "python": platform.python_version(), "sistema": platform.platform(terse=True),
            "nome_pc": socket.gethostname(), "porta": porta, "rede": NET_ON, "sessoes_rede": sessoes,
            "urls": ["http://%s:%d" % (a, porta) for a in lan_addresses()] if NET_ON else [],
            "disco": disco, "dados": {"demandas": _tamanho(ds.path()), "arquivo": _tamanho(ds.arquivo_path()),
                                      "anexos": anexos["bytes"], "cota": anexos["cota"]},
            "backup": {"ultimo": ok["t"] if ok else None, "copias": len(bk.listar(bk.pasta_local(bk.config())))},
            "tarefa": tarefa_instalada(), "log": log}


def ligado(porta: int = PORT, timeout: float = 2) -> bool:
    """Já tem uma Central respondendo nesta porta? (o iniciar.bat só abre o navegador). Sem proxy do sistema."""
    abre = urllib.request.build_opener(urllib.request.ProxyHandler({})).open
    try:
        with abre("http://127.0.0.1:%d/api/rev" % porta, timeout=timeout) as r:
            return isinstance(json.loads(r.read()).get("rev"), int)
    except (OSError, ValueError, AttributeError):
        return False


def main(argv=None) -> None:
    """Sem argumento: liga o servidor. --ligado: sai com 0 se já tem um respondendo. --sempre: laço de reinício."""
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--ligado"]:
        sys.exit(0 if ligado() else 1)
    if argv[:1] == ["--sempre"]:
        sys.exit(sempre([sys.executable, str(ROOT / "servidor.py")]))
    global NET_ON
    NET_ON = net_config()["on"]
    sessions_load()
    api_mod()   # erro no módulo aparece já ao ligar, não no primeiro pedido
    try:
        server = Server(("0.0.0.0" if NET_ON else HOST, PORT), Handler)
    except OSError:
        print(f"Já existe um servidor na porta {PORT}: use a janela aberta ou feche-a")
        sys.exit(1)
    # só depois de abrir a porta: um segundo servidor não faz backup nem manda e-mail
    iniciar_fundo([backup_mod().tarefa, api_mod().tick, email_mod().tarefa])   # atraso antes do e-mail: sai na mesma rodada
    print(f"Central de demandas aberta em http://{HOST}:{PORT}")
    if NET_ON:
        print("Acesso pela rede ligado (com PIN): " + ", ".join("http://%s:%d" % (a, PORT) for a in lan_addresses()))
    server.serve_forever()


if __name__ == "__main__":
    main()
