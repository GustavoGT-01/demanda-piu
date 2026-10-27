"""Comandos de qualidade da Central de demandas (regra em docs/QUALIDADE.md). Só biblioteca padrão + requirements-dev.txt.

    py -3 qa.py unit | js | lint | cover | all [-j N]
    py -3 qa.py mutate                       o que mudou desde o último commit, no escopo crítico
    py -3 qa.py mutate --tudo                o escopo crítico inteiro (só quando pedido: demora)
    py -3 qa.py mutate arquivo [--funcoes f1,f2]

unit/cover rodam todos os arquivos tests/test_*.py, um processo por arquivo, em paralelo. all = lint + js + cover (os testes
rodam uma vez só). mutate usa o motor de mutação do mutmut numa cópia do projeto, nunca nos arquivos de verdade,
roda em cada mutante só os testes que executam a linha dele e grava o resultado em .qa/mutacao*.json.
"""

from __future__ import annotations

import argparse
import ast
import concurrent.futures as cf
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / ".qa"
PY = sys.executable
META = 80.0   # % mínimo de cobertura de linhas e de mutação no escopo crítico (docs/QUALIDADE.md)

# Escopo crítico: arquivo -> (testes que o exercitam, funções a mutar ou None = arquivo inteiro).
# Os testes de cada alvo são os rápidos e diretos: o mutante roda contra eles, não contra a suíte inteira.
CRITICO = {
    "servidor.py": (["tests/test_servidor.py"],
                    ["_pin_ok", "_pin_novo", "net_config", "net_save", "sessions_load", "check_pin", "session_ok", "ip_host",
                     "rev", "static_files", "_host_ok", "_remote", "_auth_ok", "_operador_ok", "end_headers", "_static", "_api",
                     "do_GET", "do_POST"]),
    "store.py": (["tests/test_store.py", "tests/test_demandas_store.py"], None),
    "demandas/demandas_store.py": (["tests/test_demandas_store.py"], None),
    "demandas/demandas_calc.py": (["tests/test_demandas_calc.py"], None),
    "demandas/api.py": (["tests/test_demandas_api.py", "tests/test_servidor.py"], None),
}
# o que não entra na cópia usada pela mutação (pesado ou fora do código)
NAO_COPIA = {".git", ".qa", "data", "node_modules", "docs", "__pycache__", ".mutmut-cache", ".claude"}


def arquivos_de_teste() -> list:
    """Cada arquivo de teste: a unidade que roda em paralelo (unit, cover e mutação)."""
    return [f.relative_to(ROOT).as_posix() for f in sorted((ROOT / "tests").glob("test_*.py"))]


# arquivos de teste que não podem rodar junto com outros: rodam no fim, sozinhos.
SERIAL: set = set()


def _le_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _unittest(t: str) -> list:
    d, n = os.path.split(t)
    return ["-m", "unittest", "discover", "-s", d, "-p", n]


def _roda_testes(testes, j: int, banco: Path | None = None) -> list:
    """Roda cada arquivo num processo, j de cada vez, os mais lentos primeiro (.qa/tempos.json da última vez).
    Com banco, mede a cobertura: cada processo grava o próprio <banco>.* com o arquivo de teste como contexto
    (para a mutação saber quem executa cada linha). Saída só aparece se falhar. Devolve os arquivos que falharam."""
    OUT.mkdir(exist_ok=True)
    tempos = _le_json(OUT / "tempos.json")
    env = env_utf8({"COVERAGE_FILE": str(banco)} if banco else None)

    def um(t):
        cmd = [PY, *_unittest(t)]
        if banco:
            cmd = [PY, "-m", "coverage", "run", "-p", "--branch", "--rcfile", str(ROOT / ".coveragerc"), "--context", t,
                   *_unittest(t)]
        t0 = time.monotonic()
        p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        return t, p.returncode, time.monotonic() - t0, p.stdout + p.stderr

    ordem = sorted((t for t in testes if t not in SERIAL), key=lambda t: -tempos.get(t, 999))
    falhas, total, t0 = [], 0, time.monotonic()

    def anota(res):
        nonlocal total
        t, rc, seg, saida = res
        tempos[t] = round(seg, 1)
        ran = [int(ln.split()[1]) for ln in saida.splitlines() if ln.startswith("Ran ") and ln.split()[1].isdigit()]
        total += sum(ran)
        print("%s %6.1fs  %-46s %4d testes" % ("ok   " if rc == 0 else "FALHA", seg, t, sum(ran)), flush=True)
        if rc:
            falhas.append(t)
            print("\n".join(saida.splitlines()[-60:]), flush=True)

    with cf.ThreadPoolExecutor(max(1, j)) as ex:
        for f in cf.as_completed([ex.submit(um, t) for t in ordem]):
            anota(f.result())
    for t in sorted(t for t in testes if t in SERIAL):
        anota(um(t))
    (OUT / "tempos.json").write_text(json.dumps(tempos, indent=1, sort_keys=True), encoding="utf-8")
    print("%d testes em %d arquivos, %.0f s" % (total, len(testes), time.monotonic() - t0), flush=True)
    return falhas


def run(cmd, **kw) -> int:
    print("$", " ".join(map(str, cmd)), flush=True)
    return subprocess.call(cmd, cwd=kw.pop("cwd", ROOT), **kw)


def env_utf8(extra=None) -> dict:
    return {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", **(extra or {})}


# ---------- unit / lint / js ----------

def cmd_unit(a) -> int:
    falhas = _roda_testes(arquivos_de_teste(), a.j)
    print("unit:", "OK" if not falhas else "FALHOU em " + ", ".join(falhas))
    return 1 if falhas else 0


def cmd_lint(_a) -> int:
    return run([PY, "-m", "ruff", "check", "."])


def _js() -> tuple:
    """(código, linhas do resultado). Os checks de tela rodam juntos: cada um sobe o próprio servidor (porta 0)."""
    node = shutil.which("node")
    if not node:
        return 1, ["js: node não encontrado"]
    arquivos = [ROOT / "web" / "app.js", *sorted((ROOT / "demandas").glob("*.js")), *sorted((ROOT / "tests").glob("*.js"))]
    # jsdom instalado em tests/node_modules (npm install jsdom dentro de tests/) vale sem configurar NODE_PATH
    os.environ.setdefault("NODE_PATH", str(ROOT / "tests" / "node_modules"))
    linhas = []
    for f in arquivos:
        p = subprocess.run([node, "--check", str(f)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        if p.returncode:
            linhas.append("%s: sintaxe\n%s" % (f.relative_to(ROOT).as_posix(), p.stderr.strip()))
    erro = len(linhas)
    linhas.append("js: sintaxe de %d arquivos %s" % (len(arquivos), "OK" if not erro else "com erro"))
    tem_jsdom = subprocess.call([node, "-e", "require.resolve('jsdom')"], cwd=ROOT, env=os.environ,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0
    checks = ["tests/demandas_check.js"] if tem_jsdom else []
    if not tem_jsdom:
        linhas.append("js: jsdom não encontrado (NODE_PATH); checks de tela pulados")

    def um(c):
        try:   # check travado vira falha; sem limite, o qa.py esperava para sempre
            p = subprocess.run([node, c], cwd=ROOT, env={**os.environ, "PYTHON": PY}, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=JS_TIMEOUT)
        except subprocess.TimeoutExpired:
            return False, "%s: FALHOU (passou de %d s)" % (c, JS_TIMEOUT)
        falhas = [ln for ln in (p.stdout + p.stderr).splitlines() if ln.startswith("FAIL")]
        ok = p.returncode == 0 and not falhas
        return ok, "%s: %s" % (c, "OK" if ok else "FALHOU (%d) %s" % (p.returncode, " | ".join(falhas[:5])))

    with cf.ThreadPoolExecutor(len(checks)) as ex:
        for ok, ln in ex.map(um, checks):
            linhas.append(ln)
            erro += not ok
    return (1 if erro else 0), linhas


def cmd_js(_a) -> int:
    code, linhas = _js()
    print("\n".join(linhas))
    return code


# ---------- cobertura ----------

def critico_existente() -> list:
    return [f for f in CRITICO if (ROOT / f).is_file()]


def cmd_cover(a) -> int:
    OUT.mkdir(exist_ok=True)
    env = env_utf8({"COVERAGE_FILE": str(OUT / ".coverage")})
    for f in OUT.glob(".coverage*"):
        f.unlink()
    falhou = _roda_testes(arquivos_de_teste(), a.j, banco=OUT / ".coverage")
    (OUT / "ultima-cobertura.json").write_text(json.dumps({"falhas": falhou}), encoding="utf-8")
    run([PY, "-m", "coverage", "combine", "-q", "--rcfile", str(ROOT / ".coveragerc")], env=env)
    run([PY, "-m", "coverage", "report", "--rcfile", str(ROOT / ".coveragerc"), "--skip-empty"], env=env)
    run([PY, "-m", "coverage", "json", "--rcfile", str(ROOT / ".coveragerc"), "-q", "-o", str(OUT / "cobertura.json")], env=env)
    dados = json.loads((OUT / "cobertura.json").read_text(encoding="utf-8"))["files"]
    por_nome = {Path(k).resolve(): v["summary"] for k, v in dados.items()}
    print("\nEscopo crítico (meta %.0f%% de linhas):" % META)
    abaixo = []
    for f in critico_existente():
        s = por_nome.get((ROOT / f).resolve())
        if s is None:
            print("  %-42s sem dados" % f)
            abaixo.append(f)
            continue
        linhas = 100.0 * s["covered_lines"] / max(1, s["num_statements"])
        ramos = 100.0 * s.get("covered_branches", 0) / max(1, s.get("num_branches", 0)) if s.get("num_branches") else 100.0
        print("  %-42s linhas %5.1f%%  branches %5.1f%%" % (f, linhas, ramos))
        if linhas < META:
            abaixo.append(f)
    if falhou:
        print("cover: testes falharam em " + ", ".join(falhou))
    if abaixo:
        print("cover: abaixo da meta: " + ", ".join(abaixo))
    return 1 if falhou or (abaixo and a.estrito) else 0


# ---------- mutação ----------
#
# Três atalhos que não mudam quem morre:
# - escopo padrão = o que mudou desde o último commit (--tudo para o escopo crítico inteiro);
# - cada mutante roda só os arquivos de teste que executam a linha dele (contextos da cobertura), e mutante em
#   linha que nenhum teste executa nem roda: já é sobrevivente ("sem_teste");
# - função cujo código e testes não mudaram reaproveita o resultado da última vez (.qa/mutacao-cache.json).

CACHE_VERSAO = 1   # sobe quando o jeito de mutar muda: invalida o cache inteiro


def _linhas_das_funcoes(src: str, nomes) -> set | None:
    if not nomes:
        return None
    linhas = set()
    for no in ast.walk(ast.parse(src)):
        if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)) and no.name in nomes:
            linhas.update(range(no.lineno, no.end_lineno + 1))
    return linhas


def _instrucoes(src: str) -> dict:
    """linha -> (início, fim) da instrução mais interna que a contém (a cobertura só anota o início). De um if,
    for, def etc. conta só o cabeçalho: o corpo são outras instruções."""
    m = {}
    for no in ast.walk(ast.parse(src)):   # em largura: a mais interna vem depois e sobrescreve
        if isinstance(no, ast.stmt):
            corpo = getattr(no, "body", None)
            fim = max(no.lineno, corpo[0].lineno - 1) if corpo else no.end_lineno
            for ln in range(no.lineno, no.end_lineno + 1):
                m[ln] = (no.lineno, fim)
    return m


def _funcoes(src: str) -> dict:
    """linha -> (chave, início, fim) da função mais interna; chave = nome qualificado (#n se repetido)."""
    m, vistos = {}, {}

    def visita(no, prefixo):
        for filho in ast.iter_child_nodes(no):
            nome = prefixo
            if isinstance(filho, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                nome = (prefixo + "." if prefixo else "") + filho.name
            if isinstance(filho, (ast.FunctionDef, ast.AsyncFunctionDef)):
                vistos[nome] = vistos.get(nome, 0) + 1
                chave = nome + ("#%d" % vistos[nome] if vistos[nome] > 1 else "")
                for ln in range(filho.lineno, filho.end_lineno + 1):
                    m[ln] = (chave, filho.lineno, filho.end_lineno)
            visita(filho, nome)

    visita(ast.parse(src), "")
    return m


def _linhas_do_diff(src: str, diff: str) -> set:
    """Linhas a mutar a partir de um `git diff -U0`: as instruções que tocam alguma linha mudada."""
    mudadas = set()
    for m in re.finditer(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", diff, re.M):
        ini, n = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
        mudadas.update(range(ini, ini + n) if n else (ini, ini + 1))   # só remoção: as linhas em volta
    inst, out = _instrucoes(src), set()
    for ln in mudadas:
        if ln in inst:
            out.update(range(inst[ln][0], inst[ln][1] + 1))
    return out


def _hashes(src: str, h_testes: str) -> dict:
    """{chave da função: (início, fim, hash)} + "<módulo>" (o que está fora de função, hash do arquivo todo).
    O hash junta o código da função, os testes do alvo e CACHE_VERSAO: muda qualquer um, a função é mutada de novo."""
    linhas, funcs = src.splitlines(), _funcoes(src)
    out = {"<módulo>": (1, len(linhas), _hash(str(CACHE_VERSAO), src, h_testes))}
    for chave, ini, fim in set(funcs.values()):
        out[chave] = (ini, fim, _hash(str(CACHE_VERSAO), "\n".join(linhas[ini - 1:fim]), h_testes))
    return out


def _h_testes(testes) -> str:
    return _hash(*[(ROOT / t).read_text(encoding="utf-8") for t in testes if (ROOT / t).is_file()])


def _git(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")


def _linhas_alteradas(alvo: str, cache_alvo: dict) -> set:
    """O que mudou em alvo desde o último commit. Fora do Git e ignorado (módulo local): desde a última mutação,
    pelo cache — a função cujo hash mudou entra inteira. Novo e ainda não commitado: ele todo."""
    src = (ROOT / alvo).read_text(encoding="utf-8")
    if not _git("ls-files", "--error-unmatch", alvo).returncode:
        return _linhas_do_diff(src, _git("diff", "-U0", "HEAD", "--", alvo).stdout)
    if _git("check-ignore", "-q", alvo).returncode:
        return set(range(1, len(src.splitlines()) + 1))
    funcs, out = _funcoes(src), set()
    for chave, (ini, fim, h) in _hashes(src, _h_testes(CRITICO[alvo][0])).items():
        if cache_alvo.get(chave, {}).get("hash") != h:
            out.update(ln for ln in range(ini, fim + 1) if chave != "<módulo>" or ln not in funcs)
    return out


def _quem_cobre(banco: Path, alvo: str, testes) -> dict | None:
    """{linha: arquivos de teste (dentre testes) que a executam}, do banco de cobertura com contextos.
    None se o banco não existe, é mais velho que o alvo ou os testes, ou não tem contextos."""
    if not banco.is_file():
        return None
    quando = banco.stat().st_mtime
    if any((ROOT / f).stat().st_mtime > quando for f in (alvo, *testes) if (ROOT / f).is_file()):
        return None
    from coverage import CoverageData
    dados = CoverageData(basename=str(banco))
    dados.read()
    caminho = (ROOT / alvo).resolve()
    nome = next((f for f in dados.measured_files() if Path(f).resolve() == caminho), None)
    if nome is None:
        return None
    por_linha = dados.contexts_by_lineno(nome)
    if not any(c for cs in por_linha.values() for c in cs):
        return None
    return {ln: set(cs) & set(testes) for ln, cs in por_linha.items()}


def _hash(*partes: str) -> str:
    return hashlib.sha256("\0".join(partes).encode("utf-8")).hexdigest()[:16]


def _copia(destino: Path) -> Path:
    shutil.copytree(ROOT, destino, ignore=lambda d, nomes: [n for n in nomes if n in NAO_COPIA or n.endswith(".cfmod")])
    return destino


def _testa(copia: Path, testes) -> tuple:
    """(ok, segundos, arquivo que falhou). Cada arquivo roda no próprio processo, na ordem dada; para no primeiro
    que falhar."""
    t0 = time.monotonic()
    for t in testes:
        # sem o CorelDRAW real (segundos por mutante); o simulado cobre a lógica do servidor
        p = subprocess.run([PY, *_unittest(t)], cwd=copia, env=env_utf8(),
                           capture_output=True, timeout=MUT_TIMEOUT)
        if p.returncode:
            return False, time.monotonic() - t0, t
    return True, time.monotonic() - t0, None


MUT_TIMEOUT = 600
JS_TIMEOUT = 900   # por check de tela (jsdom)


def _escopo(a) -> list:
    """[(alvo, linhas ou None = arquivo inteiro)] conforme a linha de comando."""
    if a.arquivos or a.tudo:
        alvos = a.arquivos or critico_existente()
        out = []
        for alvo in alvos:
            funcoes = a.funcoes or CRITICO[alvo][1]
            out.append((alvo, _linhas_das_funcoes((ROOT / alvo).read_text(encoding="utf-8"), funcoes)))
        return out
    out, cache = [], _le_json(OUT / "mutacao-cache.json")
    for alvo in critico_existente():
        linhas = _linhas_alteradas(alvo, cache.get(alvo, {}))
        if linhas:
            out.append((alvo, linhas))
    return out


def _mapa(alvo: str, testes, j: int):
    """(mapa linha -> testes, falhou). Usa o banco do último `cover` se estiver em dia; senão roda a cobertura só
    dos testes do alvo (em paralelo) num banco próprio."""
    ult = _le_json(OUT / "ultima-cobertura.json")
    mapa = _quem_cobre(OUT / ".coverage", alvo, testes)
    if mapa is not None and not set(ult.get("falhas", [])) & set(testes):
        return mapa, False
    banco = OUT / (".mut-" + alvo.replace("/", "_"))
    for f in OUT.glob(banco.name + "*"):
        f.unlink()
    if _roda_testes(testes, j, banco=banco):
        return None, True
    subprocess.run([PY, "-m", "coverage", "combine", "-q", "--rcfile", str(ROOT / ".coveragerc")], cwd=ROOT,
                   env=env_utf8({"COVERAGE_FILE": str(banco)}))
    mapa = _quem_cobre(banco, alvo, testes)
    if mapa is None:   # alvo não medido (ex.: omit do .coveragerc): sem mapa, todos os testes para todo mutante
        print("%s: sem dados de cobertura por teste; cada mutante roda todos os testes do alvo" % alvo)
        return {"*": set(testes)}, False
    return mapa, False


def cmd_mutate(a) -> int:
    import mutmut   # dev: requirements-dev.txt
    desconhecidos = [f for f in a.arquivos if f not in CRITICO]
    if desconhecidos:
        print("mutate: sem testes definidos em CRITICO para " + ", ".join(desconhecidos))
        return 2
    OUT.mkdir(exist_ok=True)
    escopo = _escopo(a)
    if not escopo:
        print("mutate: nada mudou no escopo crítico desde o último commit (--tudo muta o escopo inteiro)")
        return 0
    cache = _le_json(OUT / "mutacao-cache.json") if not a.sem_cache else {}
    tempos = _le_json(OUT / "tempos.json")
    base = Path(tempfile.mkdtemp(prefix="demandas-mut-"))
    copias = []   # só copia o projeto se algum mutante precisar rodar (tudo do cache: nada a copiar)
    relatorio, total_ok = {}, True
    try:
        for alvo, faixa in escopo:
            testes = CRITICO[alvo][0]
            src = (ROOT / alvo).read_text(encoding="utf-8")
            if faixa is not None and not faixa:
                print("mutate: nenhuma função %s em %s" % (", ".join(a.funcoes or []), alvo))
                relatorio[alvo] = {"erro": "funções não encontradas"}
                total_ok = False
                continue
            ids = [m for m in mutmut.list_mutations(mutmut.Context(source=src, filename=alvo))
                   if faixa is None or m.line_number + 1 in faixa]   # line_number do mutmut começa em 0
            funcs, inst = _funcoes(src), _instrucoes(src)
            hashes = _hashes(src, _h_testes(testes))
            linhas_src = src.splitlines()

            def onde(mid):
                """(função, chave do mutante dentro dela): a posição é relativa ao início da função, para o
                resultado valer mesmo se a função mudar de linha no arquivo."""
                f = funcs.get(mid.line_number + 1)
                k = f[0] if f else "<módulo>"
                return k, "%d:%d" % (mid.line_number + 1 - hashes[k][0], mid.index)

            antigo = cache.setdefault(alvo, {})
            res, pendentes = [], []
            for mid in ids:
                k, m = onde(mid)
                c = antigo.get(k, {})
                if c.get("hash") == hashes[k][2] and m in c.get("res", {}):
                    res.append((mid, c["res"][m]))
                else:
                    pendentes.append(mid)
            reaproveitados = len(res)
            print("%s: %d mutantes (%d do cache) em %d funções" % (alvo, len(ids), reaproveitados,
                                                                   len({onde(m)[0] for m in ids})), flush=True)
            if pendentes:
                mapa, falhou = _mapa(alvo, testes, a.j)
                if falhou:
                    print("%s: testes já falham sem mutação; alvo pulado" % alvo)
                    relatorio[alvo] = {"erro": "testes falham sem mutação"}
                    total_ok = False
                    continue
                global MUT_TIMEOUT
                MUT_TIMEOUT = max(30, int(5 * max([tempos.get(t, 60) for t in testes] or [60])) + 10)
                if not copias:
                    copias = [_copia(base / ("w%d" % i)) for i in range(a.j)]
                livres = list(copias)
                from threading import Lock
                trava = Lock()
                mortes = {t: 0 for t in testes}

                def um(mid):
                    linha = mid.line_number + 1
                    quem = mapa.get("*") or mapa.get(inst.get(linha, (linha,))[0]) or mapa.get(linha) or set()
                    novo, n = mutmut.mutate(mutmut.Context(source=src, mutation_id=mid, filename=alvo))
                    if n == 0 or novo == src:
                        return mid, "invalido"
                    if not quem:
                        return mid, "sem_teste"
                    with trava:   # quem já matou vem primeiro; depois o mais rápido
                        ordem = sorted(quem, key=lambda t: (-mortes[t], tempos.get(t, 60)))
                        w = livres.pop()
                    arq = w / alvo
                    try:
                        arq.write_text(novo, encoding="utf-8")
                        try:
                            vivo, _, matador = _testa(w, ordem)
                        except subprocess.TimeoutExpired:
                            return mid, "timeout"
                        if matador:
                            with trava:
                                mortes[matador] += 1
                        return mid, "sobreviveu" if vivo else "morto"
                    finally:
                        arq.write_text(src, encoding="utf-8")
                        with trava:
                            livres.append(w)

                t0 = time.monotonic()
                with cf.ThreadPoolExecutor(a.j) as ex:
                    feitos = dict(ex.map(um, pendentes))
                seg = time.monotonic() - t0
                res += list(feitos.items())
                hoje = time.strftime("%Y-%m-%d %H:%M")
                for mid, st in feitos.items():
                    k, m = onde(mid)
                    c = antigo.get(k, {})
                    if c.get("hash") != hashes[k][2]:   # função mudou: o que estava guardado dela não vale mais
                        c = antigo[k] = {"hash": hashes[k][2], "res": {}}
                    c["data"] = hoje
                    c["res"][m] = st
            else:
                seg = 0
            cont = {k: sum(1 for _, s in res if s == k) for k in ("morto", "timeout", "sobreviveu", "sem_teste", "invalido")}
            validos = cont["morto"] + cont["timeout"] + cont["sobreviveu"] + cont["sem_teste"]
            nota = 100.0 * (cont["morto"] + cont["timeout"]) / validos if validos else 100.0
            sobre = []
            for mid, st in sorted(res, key=lambda r: r[0].line_number):
                if st in ("sobreviveu", "sem_teste"):
                    novo, _ = mutmut.mutate(mutmut.Context(source=src, mutation_id=mid, filename=alvo))
                    b_ln = novo.splitlines()[mid.line_number] if mid.line_number < len(novo.splitlines()) else ""
                    sobre.append({"linha": mid.line_number + 1, "antes": linhas_src[mid.line_number].strip(),
                                  "depois": b_ln.strip(), **({"sem_teste": True} if st == "sem_teste" else {})})
            relatorio[alvo] = {**cont, "do_cache": reaproveitados, "pontuacao": round(nota, 1), "segundos": round(seg),
                               "sobreviventes": sobre}
            print("%-42s mutantes %4d  mortos %4d  timeout %3d  sobreviventes %3d  sem teste %3d  inválidos %3d"
                  "  cache %4d  -> %5.1f%%  (%.0f s)"
                  % (alvo, len(ids), cont["morto"], cont["timeout"], cont["sobreviveu"], cont["sem_teste"],
                     cont["invalido"], reaproveitados, nota, seg), flush=True)
            if nota < META:
                total_ok = False
    finally:
        shutil.rmtree(base, ignore_errors=True)
        (OUT / "mutacao-cache.json").write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    destino = OUT / ("mutacao.json" if a.tudo and not a.arquivos else "mutacao-parcial.json")
    destino.write_text(json.dumps(relatorio, ensure_ascii=False, indent=1), encoding="utf-8")
    print("relatório:", destino)
    return 0 if total_ok else 1


def cmd_all(a) -> int:
    """lint, depois js (em segundo plano) junto com a cobertura, que já roda todos os testes uma vez só."""
    lint = cmd_lint(a)
    with cf.ThreadPoolExecutor(1) as ex:
        js = ex.submit(_js)
        cover = cmd_cover(a)
        code_js, linhas = js.result()
    print("\n".join(linhas))
    return max(lint, code_js, cover)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # console do Windows em cp1252
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["unit", "js", "lint", "cover", "mutate", "all"])
    ap.add_argument("arquivos", nargs="*", help="mutate: arquivos do escopo crítico (padrão: o que mudou desde o último commit)")
    ap.add_argument("-j", type=int, default=max(1, (os.cpu_count() or 2) - 1), help="processos em paralelo (testes e mutação)")
    ap.add_argument("--funcoes", type=lambda s: [x for x in s.split(",") if x.strip()], default=None,
                    help="mutate: só estas funções (separadas por vírgula), em vez do escopo do CRITICO")
    ap.add_argument("--tudo", action="store_true", help="mutate: o escopo crítico inteiro, não só o que mudou")
    ap.add_argument("--sem-cache", action="store_true", help="mutate: ignora .qa/mutacao-cache.json")
    ap.add_argument("--estrito", action="store_true", help="cover: falha se o escopo crítico ficar abaixo da meta")
    a = ap.parse_args()
    return {"unit": cmd_unit, "js": cmd_js, "lint": cmd_lint, "cover": cmd_cover, "mutate": cmd_mutate, "all": cmd_all}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
