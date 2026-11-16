"""Modo demonstração: gera dados fictícios numa base de dados separada da real.

    py -3 demo.py seed [--refazer] [--rede] [--semente N]

A pasta de destino vem de DEMANDAS_DATA e nunca pode ser a base real (data/): o iniciar-demo.bat
define DEMANDAS_DATA=data-demo, DEMANDAS_PORT=8091 e DEMANDAS_MODO=demo.

Os dados saem pelas rotas de verdade do demandas/api.py, com o relógio das demandas (api._agora)
andando pelos últimos meses: eventos, pausas, avisos do sino, prazos, atrasos e métricas ficam
coerentes com as regras do programa, sem nenhum JSON escrito à mão.
"""

from __future__ import annotations

import importlib.util
import json
import os
import random
import shutil
import sys
import time
from pathlib import Path

import store

ROOT = Path(__file__).resolve().parent
MOD = ROOT / "demandas"
SEMENTE = 20261109
DIAS = 120                 # até onde o histórico vai para trás
QUANTAS = 150              # demandas geradas
MIN = 60_000
DIA = 24 * 60 * MIN
MARCADOR = "demo.json"     # só uma pasta com este arquivo pode ser apagada pelo --refazer
ADM = {"papel": "maquina"}
OPERADOR = {"papel": "operador"}

# Arquivos que a demonstração cria na pasta de dados (o --refazer apaga só estes).
ARQUIVOS = ("demandas.json", "demandas-arquivo.json", "pessoas-sessoes.json", "avisos.json",
            "backup.json", "backup-estado.json", "email.json", "email-fila.json", "email-log.json",
            "rede.json", "sessoes.json", "servidor.log", "servidor-saida.log", MARCADOR)
PASTAS = ("demandas-anexos",)

SETORES = (
    ("PCP", "Planejamento", "🗂️", "#6366F1", "planejamento@exemplo.com.br"),
    ("CNC", "Corte CNC", "🪚", "#3B82F6", "corte@exemplo.com.br"),
    ("ESP", "Espumação", "🧽", "#0D9488", "espumacao@exemplo.com.br"),
    ("COS", "Costura", "🧵", "#EC4899", "costura@exemplo.com.br"),
    ("MON", "Montagem", "🔩", "#D97706", "montagem@exemplo.com.br"),
    ("EXP", "Expedição", "🚚", "#10B981", "expedicao@exemplo.com.br"),
)

# nome, setor, código de 4 números (é o que o apresentador digita), e-mail
PESSOAS = (
    ("Helena Prado", "PCP", "1101", "helena.prado@exemplo.com.br"),
    ("Rafael Dias", "PCP", "1102", "rafael.dias@exemplo.com.br"),
    ("Carlos Souza", "CNC", "2201", "carlos.souza@exemplo.com.br"),
    ("Bruno Lima", "CNC", "2202", "bruno.lima@exemplo.com.br"),
    ("Tiago Moreira", "CNC", "2203", "tiago.moreira@exemplo.com.br"),
    ("Fernanda Rocha", "ESP", "3301", "fernanda.rocha@exemplo.com.br"),
    ("Patrícia Nunes", "ESP", "3302", "patricia.nunes@exemplo.com.br"),
    ("Juliana Alves", "COS", "4401", "juliana.alves@exemplo.com.br"),
    ("Marcos Vieira", "COS", "4402", "marcos.vieira@exemplo.com.br"),
    ("André Campos", "MON", "5501", "andre.campos@exemplo.com.br"),
    ("Letícia Barros", "MON", "5502", "leticia.barros@exemplo.com.br"),
    ("Sandra Melo", "EXP", "6601", "sandra.melo@exemplo.com.br"),
)

# Por setor responsável: título, tipo, motivo, tempo estipulado (minutos).
TRABALHOS = {
    "CNC": (
        ("Corte de 8 chapas de MDF 15mm para o lote L-0928", "dem", "Ajuste de planejamento", 180),
        ("Refazer o corte das laterais do sofá Ravena (medida errada)", "alt", "Retrabalho", 120),
        ("Usinar 24 bases de cama box casal do pedido 7741", "dem", "Solicitação do cliente", 480),
        ("Trocar a fresa da CNC 2 e refazer o teste de corte", "man", "Quebra de máquina", 90),
        ("Cortar 40 réguas de compensado para o protótipo da poltrona", "dem", "Mudança de projeto", 240),
        ("Separar sobras de MDF 18mm para o setor de montagem", "mat", "Falta de material", 45),
    ),
    "ESP": (
        ("Laminar 30 assentos D-28 do pedido 7698", "dem", "Solicitação do cliente", 300),
        ("Trocar a espuma dos encostos reprovados na qualidade", "alt", "Defeito de qualidade", 150),
        ("Cortar 60 placas de espuma D-33 para o colchão Sleep", "dem", "Ajuste de planejamento", 360),
        ("Revisar a colagem da serra de fita e limpar o bico de cola", "man", "Quebra de máquina", 60),
        ("Conferir o estoque de manta acrílica do lote 0912", "mat", "Falta de material", 40),
        ("Adequar a densidade do assento conforme o projeto novo", "alt", "Mudança de projeto", 120),
    ),
    "COS": (
        ("Costurar 18 capas do sofá Ravena cor grafite", "dem", "Solicitação do cliente", 420),
        ("Refazer as costuras abertas das 6 capas devolvidas", "alt", "Defeito de qualidade", 180),
        ("Pregar zíperes nas 24 capas do colchão Sleep", "dem", "Ajuste de planejamento", 240),
        ("Regular a máquina overloque 3 e trocar a agulha", "man", "Quebra de máquina", 60),
        ("Separar retalhos de tecido suede para amostra do cliente", "mat", "Solicitação do cliente", 45),
        ("Ajustar o molde do braço do sofá Ravena ao projeto 2.1", "alt", "Mudança de projeto", 150),
    ),
    "MON": (
        ("Montar 12 sofás Ravena 3 lugares do pedido 7741", "dem", "Ajuste de planejamento", 480),
        ("Reapertar a estrutura dos 5 sofás apontados na inspeção", "alt", "Defeito de qualidade", 120),
        ("Montar as 24 camas box do pedido 7698", "dem", "Solicitação do cliente", 600),
        ("Repor parafusos 4x40 na bancada de montagem", "mat", "Falta de material", 30),
        ("Trocar a mangueira da pistola pneumática da bancada 2", "man", "Quebra de máquina", 45),
        ("Montar o protótipo da poltrona para a reunião comercial", "dem", "Mudança de projeto", 240),
    ),
    "EXP": (
        ("Embalar e etiquetar os 12 sofás do pedido 7741", "dem", "Ajuste de planejamento", 180),
        ("Conferir a nota e carregar o caminhão da rota Sul", "dem", "Solicitação do cliente", 120),
        ("Reembalar os 3 volumes com o plástico rasgado", "alt", "Defeito de qualidade", 60),
        ("Repor filme stretch e fita de arquear no estoque", "mat", "Falta de material", 40),
        ("Separar os volumes da transportadora para coleta das 14h", "dem", "Ajuste de planejamento", 90),
        ("Organizar a doca para a chegada do lote L-0931", "set", "Ajuste de planejamento", 60),
    ),
    "PCP": (
        ("Refazer a sequência do lote L-0928 com a máquina parada", "set", "Quebra de máquina", 120),
        ("Confirmar a data de entrega do pedido 7741 com o comercial", "set", "Solicitação do cliente", 60),
        ("Replanejar a semana com a falta de MDF 18mm", "set", "Falta de material", 90),
        ("Abrir ordem de retrabalho do lote reprovado 0907", "set", "Retrabalho", 45),
    ),
}

PAUSAS = ("Aguardando material", "Aguardando outro setor", "Máquina parada", "Aguardando aprovação",
          "Troca de turno ou intervalo", "Informação incompleta")
OBS_PAUSA = ("Material chega amanhã pela manhã.", "Esperando a liberação da qualidade.",
             "Manutenção avisada, previsão de 1 hora.", "Aguardando o retorno do comercial.", "")
COMENTARIOS = ("Começando agora, vou atualizar ao terminar a primeira metade.",
               "Faltam 4 peças, o resto já está pronto.",
               "O material chegou, seguimos com o corte.",
               "Ajustei a medida conforme o desenho novo.",
               "Pode conferir, terminei e deixei na bancada de inspeção.",
               "Precisamos de mais 30 minutos: a máquina travou no meio.")
NOTAS_FIM = ("Entregue conforme o pedido.", "Concluído, sem sobras.", "Peças conferidas uma a uma.",
             "Terminado com 2 peças a mais de reserva.", "")
TITULO_MAX = 140   # o api.py recusa acima disso
COMPLEMENTOS = ("", "", "lote L-0928", "lote L-0931", "lote L-0934", "pedido 7741", "pedido 7698",
                "pedido 7812", "OP 4412", "OP 4417", "turno da tarde", "urgência do comercial",
                "conferir com o projeto 2.1", "cliente Móveis Aurora", "cliente Decorlar")
MOTIVOS_CANC = ("Pedido cancelado pelo cliente.", "Duplicada: já existe outra demanda igual.",
                "O projeto mudou e esta etapa saiu.", "Resolvido direto no setor.")


class DemoErro(Exception):
    """Mensagem pronta para a tela/console; nada de caminho interno."""


# ---------- pasta de dados ----------

def destino() -> Path:
    """A pasta da demonstração (DEMANDAS_DATA). Nunca a base real: ela é a única proteção dos dados de verdade."""
    bruto = os.environ.get("DEMANDAS_DATA") or ""
    if not bruto.strip():
        raise DemoErro("Defina DEMANDAS_DATA com a pasta da demonstração (o iniciar-demo.bat já faz isso).")
    alvo = Path(bruto.strip()).resolve()
    if alvo == (ROOT / "data").resolve():
        raise DemoErro("A demonstração nunca grava na base real (data/). Use outra pasta, como data-demo.")
    return alvo


def _p(nome: str) -> Path:
    return destino() / nome


def populada() -> bool:
    """Já tem demandas gravadas nesta pasta?"""
    try:
        raw = json.loads(_p("demandas.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(raw, dict) and bool(raw.get("demandas"))


def de_demonstracao() -> bool:
    """Pasta vazia, ou pasta que esta ferramenta mesma gerou (tem o marcador)."""
    return not populada() or _p(MARCADOR).exists()


def limpar() -> None:
    """Apaga os arquivos da demonstração. Pasta com dados e sem o marcador não é mexida."""
    alvo = destino()
    if not de_demonstracao():
        raise DemoErro("A pasta tem dados que não são da demonstração: apague-a à mão ou escolha outra.")
    for nome in ARQUIVOS:
        for p in (alvo / nome, alvo / (nome + ".bak"), alvo / (nome + ".tmp")):
            store._remove(p)
    for padrao in ("demandas.json.v*.bak", "demandas.json.corrompido-*"):
        for p in alvo.glob(padrao):
            store._remove(p)
    for nome in PASTAS:
        shutil.rmtree(alvo / nome, ignore_errors=True)


def ligada() -> bool:
    """Tem uma Central respondendo na porta da demonstração (DEMANDAS_PORT)? Apagar os dados embaixo dela
    deixaria o banco inconsistente: melhor pedir para fechar a janela."""
    porta = (os.environ.get("DEMANDAS_PORT") or "").strip()
    if not porta.isdigit():
        return False
    import servidor
    return servidor.ligado(int(porta))


# ---------- módulo das demandas ----------

def carrega_api():
    """demandas/api.py como o servidor carrega (a pasta entra no sys.path para os imports irmãos)."""
    if str(MOD) not in sys.path:
        sys.path.insert(0, str(MOD))
    spec = importlib.util.spec_from_file_location("demandas_api_demo", MOD / "api.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------- plano (puro: mesma semente e mesmo instante = mesmo plano) ----------

def _util(t: int) -> int:
    """Joga para trás até cair em dia de semana (sábado/domingo não têm produção na demonstração)."""
    while time.localtime(t / 1000).tm_wday >= 5:
        t -= DIA
    return t


def _hora(t: int, rnd: random.Random) -> int:
    """Um instante entre 07:00 e 16:59 do dia local de t."""
    lt = time.localtime(t / 1000)
    meia = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    return int((meia + rnd.randrange(7 * 3600, 17 * 3600)) * 1000)


def _criado(agora: int, dias: int, rnd: random.Random) -> int:
    return min(_hora(_util(agora - dias * DIA), rnd), agora - 5 * MIN)


def _passos(base: int, offsets, limite: int) -> list:
    """Instantes crescentes (base + minutos), parando no primeiro que passaria do limite."""
    out, ultimo = [], base
    for m in offsets:
        t = base + int(m) * MIN
        if t > limite or t <= ultimo:
            break
        out.append(t)
        ultimo = t
    return out


def _pessoas_de(pessoas: list, sid: str) -> list:
    return [p for p in pessoas if p["setor"] == sid]


def _elenco(rnd: random.Random, pessoas: list, setores: list, atende=None):
    """(setor responsável, pessoa que vai atender, quem pediu). Com atende, o setor é o dela (as demandas em
    aberto são repartidas entre todo mundo: na apresentação, cada pessoa tem o que mostrar na tela dela)."""
    alvo = atende["setor"] if atende else rnd.choice([s for s in setores if s in TRABALHOS and _pessoas_de(pessoas, s)])
    atende = atende or rnd.choice(_pessoas_de(pessoas, alvo))
    fora = [p for p in pessoas if p["setor"] != alvo]
    pede = rnd.choice(fora) if fora and rnd.random() < 0.7 else None
    return alvo, atende, pede


def _titulo(rnd: random.Random, titulo: str) -> str:
    """Um complemento de vez em quando: duas demandas do mesmo trabalho não aparecem com o texto igualzinho."""
    extra = rnd.choice(COMPLEMENTOS)
    return titulo + " — " + extra if extra and len(titulo) + len(extra) + 3 <= TITULO_MAX else titulo


def _criar(acoes, rnd: random.Random, did: str, t: int, alvo: str, atende, pede, trabalho, prio: str, fila: bool):
    titulo, tipo, motivo, est = trabalho
    body = {"titulo": _titulo(rnd, titulo), "tipo": tipo, "motivo": motivo, "prio": prio, "est": est,
            "para": {"s": alvo, "p": None if fila else atende["id"]}, "desc": ""}
    if pede is None:
        body["de_s"] = rnd_setor_de(alvo)
    acoes.append({"t": t, "como": None if pede is None else pede["id"], "rest": "demanda/criar",
                  "body": body, "did": did})
    return est


def rnd_setor_de(alvo: str) -> str:
    """Setor solicitante quando quem pede é o Escritório: PCP, ou o próprio alvo se ele for o PCP."""
    return "CNC" if alvo == "PCP" else "PCP"


def _acao(acoes, did: str, t: int, como, rest: str, body=None):
    acoes.append({"t": t, "como": como, "rest": rest, "body": dict(body or {}, id=did), "did": did})


def _dias_atras(rnd: random.Random) -> int:
    """Quando a demanda do histórico nasceu: mais perto de hoje do que do começo (o painel de 7 e 30 dias
    precisa de movimento recente), mas espalhado pelos meses todos."""
    return int(DIAS * rnd.random() ** 1.6)


def _fechada(acoes, rnd, pessoas, setores, did, agora, tipo: str):
    """Demanda do histórico: concluída (na hora, com pausa ou atrasada), cancelada ou repassada."""
    alvo, atende, pede = _elenco(rnd, pessoas, setores)
    prio = rnd.choices(("low", "norm", "high", "urg"), (1, 6, 3, 1))[0]
    trabalho = rnd.choice(TRABALHOS[alvo])
    est = trabalho[3]
    espera = rnd.randrange(3, max(4, int(est * 0.15)))
    outro = novo = None
    if tipo == "cancelada":
        offsets = [rnd.randrange(10, 90)]
    elif tipo == "repassada":
        outro = rnd.choice([s for s in setores if s != alvo and s in TRABALHOS and _pessoas_de(pessoas, s)])
        novo = rnd.choice(_pessoas_de(pessoas, outro))
        offsets = [espera, espera + rnd.randrange(10, 60),
                   espera + rnd.randrange(70, 180), espera + rnd.randrange(190, 400)]
    elif tipo == "concluida_pausa":
        pausa = espera + rnd.randrange(10, max(11, int(est * 0.35)))
        volta = pausa + rnd.randrange(15, max(16, int(est * 0.3)))
        offsets = [espera, pausa, volta, volta + rnd.randrange(10, max(11, int(est * 0.3)))]
    else:   # concluída dentro do prazo ou depois dele
        fim = est + rnd.randrange(30, 600) if tipo == "concluida_atrasada" \
            else espera + max(5, int(est * rnd.uniform(0.35, 0.7)))
        offsets = [espera, fim]
    # o roteiro inteiro tem de caber antes de agora: uma demanda de hoje nasce mais cedo para fechar hoje
    t0 = min(_criado(agora, _dias_atras(rnd), rnd), agora - (offsets[-1] + 10) * MIN)
    _criar(acoes, rnd, did, t0, alvo, atende, pede, trabalho, prio, rnd.random() < 0.55)
    quem = atende["id"]
    marcos = _passos(t0, offsets, agora)
    if len(marcos) < len(offsets):
        return   # não coube: a demanda fica em aberto, sem ação solta
    if tipo == "cancelada":
        _acao(acoes, did, marcos[0], None if pede is None else pede["id"], "demanda/cancelar",
              {"motivo": rnd.choice(MOTIVOS_CANC)})
        return
    _acao(acoes, did, marcos[0], quem, "demanda/aceitar")
    if tipo == "repassada":
        _acao(acoes, did, marcos[1], quem, "demanda/reatribuir",
              {"s": outro, "p": novo["id"], "nota": "Este serviço é do " + outro})
        _acao(acoes, did, marcos[2], novo["id"], "demanda/aceitar")
        _acao(acoes, did, marcos[3], novo["id"], "demanda/concluir", {"nota": rnd.choice(NOTAS_FIM)})
        return
    if tipo == "concluida_pausa":
        _acao(acoes, did, marcos[1], quem, "demanda/pausar",
              {"motivo": rnd.choice(PAUSAS), "obs": rnd.choice(OBS_PAUSA)})
        _acao(acoes, did, marcos[2], quem, "demanda/retomar")
        _acao(acoes, did, marcos[3], quem, "demanda/concluir", {"nota": rnd.choice(NOTAS_FIM)})
        return
    if rnd.random() < 0.35:
        meio = (marcos[0] + marcos[1]) // 2
        if marcos[0] < meio < marcos[1]:
            _acao(acoes, did, meio, quem, "demanda/comentar", {"texto": rnd.choice(COMENTARIOS)})
    _acao(acoes, did, marcos[1], quem, "demanda/concluir", {"nota": rnd.choice(NOTAS_FIM)})


def _aberta(acoes, rnd, pessoas, setores, did, agora, tipo: str, atende=None):
    """Demanda que a apresentação mostra no quadro: na fila, em andamento, pausada ou atrasada.

    O prazo é criado + tempo estipulado: aqui a criação é contada a partir de agora, uma fração do
    tempo estipulado para as que estão dentro do prazo e um múltiplo dele para as atrasadas."""
    atrasada = tipo == "atrasada"
    alvo, atende, pede = _elenco(rnd, pessoas, setores, atende)
    prio = rnd.choices(("high", "urg", "norm"), (3, 2, 2))[0] if atrasada \
        else rnd.choices(("low", "norm", "high", "urg"), (1, 6, 3, 1))[0]
    trabalho = rnd.choice(TRABALHOS[alvo])
    if atrasada:   # tempo estipulado curto e já faz horas: passou do prazo
        trabalho = (trabalho[0], trabalho[1], trabalho[2], rnd.choice((30, 45, 60, 90, 120)))
    est = trabalho[3]
    # dentro do prazo: a idade é uma fração do tempo estipulado (o prazo é criado + estipulado)
    idade = est * rnd.uniform(1.6, 6.0) + rnd.randrange(30, 600) if atrasada else est * rnd.uniform(0.25, 0.75)
    t0 = min(agora - int(idade) * MIN, agora - 5 * MIN)
    fila = tipo == "fila" and rnd.random() < 0.7
    _criar(acoes, rnd, did, t0, alvo, atende, pede, trabalho, prio, fila)
    quem = atende["id"]
    if tipo == "fila" or (atrasada and rnd.random() < 0.3):
        return   # ninguém aceitou ainda: é o que a tela mostra como "na fila"
    # a espera é uma fração da idade da demanda: os marcos sempre cabem antes de agora
    espera = max(2, int(idade * rnd.uniform(0.15, 0.5)))
    if tipo == "andamento" or atrasada:
        marcos = _passos(t0, (espera,), agora)
        if not marcos:
            return
        _acao(acoes, did, marcos[0], quem, "demanda/aceitar")
        if atrasada:
            # o que sobrou até agora, em minutos: a cobrança e a extensão caem dentro desse trecho
            resto = (agora - marcos[0]) // MIN
            if resto >= 4:
                _acao(acoes, did, marcos[0] + int(resto * 0.4) * MIN,
                      None if pede is None else pede["id"], "demanda/cobrar")
                if rnd.random() < 0.5:
                    _acao(acoes, did, marcos[0] + int(resto * 0.6) * MIN, None, "demanda/estender",
                          {"minutos": rnd.choice((60, 120, 240))})
                if prio != "urg" and rnd.random() < 0.4:
                    _acao(acoes, did, marcos[0] + int(resto * 0.8) * MIN, None, "demanda/prioridade",
                          {"prio": "urg"})
        elif rnd.random() < 0.5:
            fala = _passos(marcos[0], (rnd.randrange(20, 300),), agora)
            if fala:
                _acao(acoes, did, fala[0], quem, "demanda/comentar", {"texto": rnd.choice(COMENTARIOS)})
        return
    # pausada agora (a pausa fica aberta: é o que a tela mostra em "pausadas")
    marcos = _passos(t0, (espera, espera + max(5, int(idade * rnd.uniform(0.1, 0.4)))), agora)
    if len(marcos) < 2:
        return
    _acao(acoes, did, marcos[0], quem, "demanda/aceitar")
    _acao(acoes, did, marcos[1], quem, "demanda/pausar",
          {"motivo": rnd.choice(PAUSAS), "obs": rnd.choice(OBS_PAUSA)})


# quantas de cada tipo (o resto da mistura sai do sorteio dentro de cada um)
MISTURA = (("concluida", 60), ("concluida_pausa", 24), ("concluida_atrasada", 12), ("cancelada", 12),
           ("repassada", 10), ("fila", 10), ("andamento", 10), ("pausada", 4), ("atrasada", 8))
FECHADAS = ("concluida", "concluida_pausa", "concluida_atrasada", "cancelada", "repassada")


def plano(semente: int = SEMENTE, agora: int | None = None) -> dict:
    """Setores, pessoas e o roteiro de chamadas (ordenado no tempo) da demonstração. Função pura."""
    rnd = random.Random(semente)
    agora = int(time.time() * 1000) if agora is None else agora
    setores = [{"id": s, "nome": n, "icone": i, "cor": c, "email": e} for s, n, i, c, e in SETORES]
    pessoas = [{"id": "p%d" % n, "nome": nome, "setor": setor, "codigo": codigo, "email": email}
               for n, (nome, setor, codigo, email) in enumerate(PESSOAS)]
    sids = [s["id"] for s in setores]
    tipos = [t for t, n in MISTURA for _ in range(n)]
    rnd.shuffle(tipos)   # embaralha antes de cortar: a mistura não depende do tamanho pedido
    del tipos[QUANTAS:]
    acoes: list = []
    rodizio = list(pessoas)
    rnd.shuffle(rodizio)   # o que está em aberto é repartido entre todas as pessoas, uma por vez
    abertas = 0
    for n, tipo in enumerate(tipos):
        did = "SOL-%d" % (1001 + n)
        if tipo in FECHADAS:
            _fechada(acoes, rnd, pessoas, sids, did, agora, tipo)
        else:
            _aberta(acoes, rnd, pessoas, sids, did, agora, tipo, rodizio[abertas % len(rodizio)])
            abertas += 1
    for n, a in enumerate(acoes):
        a["ordem"] = n
    acoes.sort(key=lambda a: (a["t"], a["ordem"]))
    _numera(acoes)
    return {"agora": agora, "semente": semente, "setores": setores, "pessoas": pessoas, "acoes": acoes}


def _numera(acoes: list) -> None:
    """O id vem do api.py na ordem em que as demandas são criadas: depois de ordenar no tempo, renumera o roteiro."""
    mapa, n = {}, 1000
    for a in acoes:
        if a["rest"] == "demanda/criar":
            n += 1
            mapa[a["did"]] = "SOL-%d" % n
    for a in acoes:
        a["did"] = mapa[a["did"]]
        if "id" in a["body"]:
            a["body"]["id"] = a["did"]


# ---------- aplicação ----------

def aplicar(api, pl: dict) -> dict:
    """Roda o plano pelas rotas de verdade, com o relógio das demandas andando. Devolve o resumo."""
    relogio = {"t": pl["agora"]}
    agora_real = api._agora
    api._agora = lambda: relogio["t"]
    try:
        for s in pl["setores"]:
            api.handle("POST", "setor/salvar", dict(s, modo="novo", rev=0), ADM)
        for p in pl["pessoas"]:
            api.handle("POST", "pessoa/salvar",
                       {"modo": "novo", "nome": p["nome"], "setor": p["setor"], "codigo": p["codigo"],
                        "email": p["email"], "rev": 0}, ADM)
        tks, feitas, pulos = {}, 0, 0
        for a in pl["acoes"]:
            relogio["t"] = a["t"]
            try:
                if a["como"] is None:
                    api.handle("POST", a["rest"], dict(a["body"]), ADM)
                else:
                    api.handle("POST", a["rest"], dict(a["body"], tk=_tk(api, tks, pl, a["como"])), OPERADOR)
                feitas += 1
            except api.ApiError:
                pulos += 1   # roteiro sorteado que a regra do programa não aceita: a demanda fica como está
        api.tick(pl["agora"])   # marca os atrasos de quem passou do prazo e ainda está em aberto
    finally:
        api._agora = agora_real
        api.esquecer_pessoas()   # ninguém fica identificado: na apresentação cada um digita o código
    return {"acoes": feitas, "pulos": pulos}


def _tk(api, tks: dict, pl: dict, pid: str) -> str:
    if pid not in tks:
        p = next(p for p in pl["pessoas"] if p["id"] == pid)
        tks[pid] = api.handle("POST", "entrar", {"pessoa": pid, "codigo": p["codigo"]}, OPERADOR)["tk"]
    return tks[pid]


def _sem_backup() -> None:
    """A demonstração não faz cópia de segurança (o backup padrão gravaria .zip ao ligar)."""
    store.atomic_write(_p("backup.json"), json.dumps({"on": False, "ao_ligar": False}))


def _marcador(pl: dict, resumo: dict) -> None:
    store.atomic_write(_p(MARCADOR), json.dumps(
        {"demo": True, "gerado": pl["agora"], "semente": pl["semente"], "dias": DIAS,
         "demandas": QUANTAS, "acoes": resumo["acoes"]}, ensure_ascii=False))


def seed(refazer: bool = False, rede: bool = False, semente: int = SEMENTE, agora: int | None = None) -> dict:
    """Gera a base da demonstração. Já populada e sem refazer: não mexe em nada."""
    alvo = destino()
    alvo.mkdir(parents=True, exist_ok=True)
    if populada():
        if not refazer:
            return {"ja_existia": True, "pasta": alvo}
        if ligada():
            raise DemoErro("A demonstração está ligada: feche a janela dela antes de refazer os dados.")
        limpar()
    api = carrega_api()
    pl = plano(semente, agora)
    resumo = aplicar(api, pl)
    _sem_backup()
    _marcador(pl, resumo)
    if rede:
        import servidor
        servidor.net_save(True)
    doc = json.loads(_p("demandas.json").read_text(encoding="utf-8"))
    conta: dict = {}
    for d in doc["demandas"]:
        conta[d["status"]] = conta.get(d["status"], 0) + 1
    return {"ja_existia": False, "pasta": alvo, "pessoas": pl["pessoas"], "status": conta,
            "demandas": len(doc["demandas"]), "notas": len(doc["notas"]), "rede": rede, **resumo}


# ---------- linha de comando ----------

NOMES = {"new": "na fila", "prog": "em andamento", "pause": "pausadas", "done": "concluídas",
         "canc": "canceladas"}
AJUDA = __doc__


def _mostra(r: dict) -> None:
    if r["ja_existia"]:
        print("A base da demonstração já tem dados: %s" % r["pasta"])
        print("Para gerar tudo de novo: py -3 demo.py seed --refazer")
        return
    print("Demonstração pronta em %s" % r["pasta"])
    print("%d demandas (%s), %d avisos, %d ações aplicadas%s."
          % (r["demandas"], ", ".join("%d %s" % (n, NOMES.get(k, k)) for k, n in sorted(r["status"].items())),
             r["notas"], r["acoes"], " (%d puladas)" % r["pulos"] if r["pulos"] else ""))
    if r["rede"]:
        print("Acesso pela rede ligado: os PINs aparecem em ⚙ Configurações.")
    print("\nCódigos de 4 números para entrar como operador:")
    for p in r["pessoas"]:
        print("  %-16s %-4s %s" % (p["nome"], p["setor"], p["codigo"]))


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] != ["seed"]:
        print(AJUDA)
        return 0 if argv[:1] in ([], ["--ajuda"], ["-h"], ["--help"]) else 2
    resto, refazer, rede, semente = argv[1:], False, False, SEMENTE
    while resto:
        a = resto.pop(0)
        if a == "--refazer":
            refazer = True
        elif a == "--rede":
            rede = True
        elif a == "--semente" and resto and resto[0].lstrip("-").isdigit():
            semente = int(resto.pop(0))
        else:
            print("Opção desconhecida: %s" % a)
            return 2
    try:
        _mostra(seed(refazer=refazer, rede=rede, semente=semente))
    except DemoErro as exc:
        print("ERRO: %s" % exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
