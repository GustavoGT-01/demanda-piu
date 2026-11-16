"""demo.py: a guarda da pasta de dados, a limpeza, o plano (função pura) e a linha de comando.

Aqui nada roda o seed de verdade (isso é o test_demo_e2e.py): estes testes são rápidos e são os que a
mutação usa. O plano é conferido contra as constantes do demandas/api.py: título, tipo, motivo,
prioridade, tempo estipulado, ícone, cor e código têm de ser aceitos pelas rotas.
"""

import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import demo  # noqa: E402

api = demo.carrega_api()
import demandas_store as ds  # noqa: E402

AGORA = 1_762_700_000_000   # 2025-11-09 ~13:33 (fixo: o plano é determinístico)
TRABALHOS_TOTAL = [t for lista in demo.TRABALHOS.values() for t in lista]


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="dem-demo-"))
        self._env = mock.patch.dict(os.environ, {"DEMANDAS_DATA": str(self.dir)})
        self._env.start()
        self.addCleanup(self._env.stop)

    def grava(self, nome: str, conteudo) -> Path:
        p = self.dir / nome
        p.write_text(json.dumps(conteudo) if not isinstance(conteudo, str) else conteudo, encoding="utf-8")
        return p

    def saida(self, fn, *a, **kw):
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            r = fn(*a, **kw)
        return r, buf.getvalue()


class Guarda(Base):
    def test_destino_e_a_pasta_do_ambiente(self):
        self.assertEqual(demo.destino(), self.dir.resolve())

    def test_sem_ambiente_recusa(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(demo.DemoErro):
                demo.destino()

    def test_ambiente_em_branco_recusa(self):
        for v in ("", "   ", "\t"):
            with mock.patch.dict(os.environ, {"DEMANDAS_DATA": v}):
                with self.assertRaises(demo.DemoErro):
                    demo.destino()

    def test_base_real_recusa(self):
        for caminho in (str(ROOT / "data"), str(ROOT / "data") + os.sep,
                        str(ROOT / "demandas" / ".." / "data"), " %s " % (ROOT / "data")):
            with mock.patch.dict(os.environ, {"DEMANDAS_DATA": caminho}):
                with self.assertRaises(demo.DemoErro) as c:
                    demo.destino()
                self.assertIn("data", str(c.exception))

    def test_pasta_parecida_com_a_real_vale(self):
        with mock.patch.dict(os.environ, {"DEMANDAS_DATA": str(ROOT / "data-demo")}):
            self.assertEqual(demo.destino(), (ROOT / "data-demo").resolve())


class Pasta(Base):
    def test_vazia_nao_esta_populada(self):
        self.assertFalse(demo.populada())
        self.assertTrue(demo.de_demonstracao())

    def test_arquivo_ruim_ou_vazio_nao_esta_populado(self):
        for conteudo in ("", "{", "[]", {"demandas": []}, {"rev": 3}):
            self.grava("demandas.json", conteudo)
            self.assertFalse(demo.populada(), conteudo)

    def test_com_demandas_esta_populada(self):
        self.grava("demandas.json", {"demandas": [{"id": "SOL-1001"}]})
        self.assertTrue(demo.populada())
        self.assertFalse(demo.de_demonstracao())

    def test_com_marcador_e_de_demonstracao(self):
        self.grava("demandas.json", {"demandas": [{"id": "SOL-1001"}]})
        self.grava(demo.MARCADOR, {"demo": True})
        self.assertTrue(demo.de_demonstracao())

    def test_limpar_recusa_pasta_de_outro(self):
        p = self.grava("demandas.json", {"demandas": [{"id": "SOL-1001"}]})
        with self.assertRaises(demo.DemoErro):
            demo.limpar()
        self.assertTrue(p.exists())   # nada foi apagado

    def test_limpar_apaga_todos_os_arquivos_da_lista(self):
        self.grava(demo.MARCADOR, {"demo": True})
        criados = []
        for nome in demo.ARQUIVOS:
            for sufixo in ("", ".bak", ".tmp"):
                criados.append(self.grava(nome + sufixo, "x"))
        for pasta in demo.PASTAS:
            (self.dir / pasta).mkdir(exist_ok=True)
            (self.dir / pasta / "a0.jpg").write_bytes(b"x")
        demo.limpar()
        sobrou = [p.name for p in criados if p.exists()]
        self.assertEqual(sobrou, [])
        for pasta in demo.PASTAS:
            self.assertFalse((self.dir / pasta).exists(), pasta)

    def test_limpar_apaga_so_o_que_e_da_demonstracao(self):
        self.grava("demandas.json", {"demandas": [{"id": "SOL-1001"}]})
        self.grava("demandas.json.bak", {"demandas": []})
        self.grava("demandas.json.v0.bak", {"demandas": []})
        self.grava(demo.MARCADOR, {"demo": True})
        self.grava("rede.json", {"on": True})
        (self.dir / "demandas-anexos").mkdir()
        (self.dir / "demandas-anexos" / "a0.jpg").write_bytes(b"x")
        meu = self.grava("anotacoes.txt", "nao e da demonstracao")
        demo.limpar()
        for nome in ("demandas.json", "demandas.json.bak", "demandas.json.v0.bak", demo.MARCADOR, "rede.json"):
            self.assertFalse((self.dir / nome).exists(), nome)
        self.assertFalse((self.dir / "demandas-anexos").exists())
        self.assertTrue(meu.exists())

    def test_limpar_apaga_arquivo_marcado_como_corrompido(self):
        self.grava(demo.MARCADOR, {"demo": True})
        self.grava("demandas.json.corrompido-123", {"demandas": []})
        demo.limpar()
        self.assertFalse(list(self.dir.glob("demandas.json.corrompido-*")))

    def test_limpar_pasta_vazia_nao_reclama(self):
        demo.limpar()
        self.assertTrue(self.dir.exists())

    def test_sem_backup_desliga_a_copia(self):
        demo._sem_backup()
        cfg = json.loads((self.dir / "backup.json").read_text(encoding="utf-8"))
        self.assertEqual((cfg["on"], cfg["ao_ligar"]), (False, False))

    def test_marcador_guarda_a_origem(self):
        pl = {"agora": AGORA, "semente": 7}
        demo._marcador(pl, {"acoes": 42})
        m = json.loads((self.dir / demo.MARCADOR).read_text(encoding="utf-8"))
        self.assertEqual(m, {"demo": True, "gerado": AGORA, "semente": 7, "dias": demo.DIAS,
                             "demandas": demo.QUANTAS, "acoes": 42})


class Ligada(Base):
    """Refazer os dados com a demonstração aberta deixaria o banco inconsistente: o seed recusa antes."""

    def test_sem_porta_no_ambiente_nao_pergunta_nada(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(demo.ligada())
        for valor in ("", "  ", "porta", "80a90"):
            with mock.patch.dict(os.environ, {"DEMANDAS_PORT": valor}):
                self.assertFalse(demo.ligada(), valor)

    def test_pergunta_na_porta_do_ambiente(self):
        import servidor
        with mock.patch.dict(os.environ, {"DEMANDAS_PORT": "8091"}), \
                mock.patch.object(servidor, "ligado", return_value=True) as lig:
            self.assertTrue(demo.ligada())
        lig.assert_called_once_with(8091)
        with mock.patch.dict(os.environ, {"DEMANDAS_PORT": "8091"}), \
                mock.patch.object(servidor, "ligado", return_value=False):
            self.assertFalse(demo.ligada())

    def test_refazer_recusa_com_a_demonstracao_ligada(self):
        self.grava("demandas.json", {"demandas": [{"id": "SOL-1001"}]})
        self.grava(demo.MARCADOR, {"demo": True})
        with mock.patch.object(demo, "ligada", return_value=True), \
                mock.patch.object(demo, "limpar", side_effect=AssertionError("não devia apagar")):
            with self.assertRaises(demo.DemoErro) as c:
                demo.seed(refazer=True)
        self.assertIn("feche a janela", str(c.exception))
        self.assertTrue((self.dir / "demandas.json").exists())

    def test_sem_refazer_nao_pergunta_pela_porta(self):
        self.grava("demandas.json", {"demandas": [{"id": "SOL-1001"}]})
        with mock.patch.object(demo, "ligada", side_effect=AssertionError("não precisa perguntar")):
            self.assertTrue(demo.seed()["ja_existia"])


class Tempo(unittest.TestCase):
    def test_util_cai_em_dia_de_semana(self):
        for n in range(14):
            t = demo._util(AGORA - n * demo.DIA)
            self.assertLess(time.localtime(t / 1000).tm_wday, 5)
            self.assertLessEqual(t, AGORA - n * demo.DIA)

    def test_util_nao_mexe_em_dia_util(self):
        t = demo._util(AGORA)
        self.assertEqual(demo._util(t), t)

    def test_hora_fica_no_horario_de_trabalho(self):
        import random
        rnd = random.Random(1)
        horas = {time.localtime(demo._hora(AGORA, rnd) / 1000).tm_hour for _ in range(400)}
        self.assertEqual(horas, set(range(7, 17)), "das 07:00 às 16:59, o dia de produção")
        dia = time.localtime(AGORA / 1000)
        for _ in range(20):
            lt = time.localtime(demo._hora(AGORA, rnd) / 1000)
            self.assertEqual((lt.tm_year, lt.tm_mon, lt.tm_mday), (dia.tm_year, dia.tm_mon, dia.tm_mday))

    def test_criado_nunca_passa_de_agora(self):
        import random
        rnd = random.Random(2)
        for dias in range(0, 30):
            self.assertLessEqual(demo._criado(AGORA, dias, rnd), AGORA - 5 * demo.MIN)

    def test_criado_recua_quando_a_hora_sorteada_seria_no_futuro(self):
        import random
        with mock.patch.object(demo, "_hora", return_value=AGORA + demo.DIA):
            self.assertEqual(demo._criado(AGORA, 0, random.Random(1)), AGORA - 5 * demo.MIN)
        with mock.patch.object(demo, "_hora", return_value=AGORA - demo.DIA):
            self.assertEqual(demo._criado(AGORA, 1, random.Random(1)), AGORA - demo.DIA)

    def test_dias_atras_cobre_o_periodo_e_puxa_para_hoje(self):
        import random
        rnd = random.Random(4)
        dias = [demo._dias_atras(rnd) for _ in range(400)]
        self.assertTrue(0 <= min(dias) and max(dias) < demo.DIAS)
        self.assertGreater(sum(1 for d in dias if d <= 30), sum(1 for d in dias if d > 90))

    def test_passos_crescentes_e_dentro_do_limite(self):
        base = 1000 * demo.MIN
        self.assertEqual(demo._passos(base, (1, 2, 3), base + 10 * demo.MIN),
                         [base + 1 * demo.MIN, base + 2 * demo.MIN, base + 3 * demo.MIN])
        self.assertEqual(demo._passos(base, (1, 20, 3), base + 10 * demo.MIN), [base + demo.MIN])
        self.assertEqual(demo._passos(base, (10,), base + 10 * demo.MIN),
                         [base + 10 * demo.MIN])                                    # bem em cima do limite: vale
        self.assertEqual(demo._passos(base, (10, 11), base + 10 * demo.MIN), [base + 10 * demo.MIN])
        self.assertEqual(demo._passos(base, (0, 1), base + 10 * demo.MIN), [])      # 0 não cresce
        self.assertEqual(demo._passos(base, (2, 2), base + 10 * demo.MIN), [base + 2 * demo.MIN])
        self.assertEqual(demo._passos(base, (), base), [])

    def test_setor_solicitante_do_escritorio(self):
        self.assertEqual(demo.rnd_setor_de("PCP"), "CNC")
        for s in ("CNC", "ESP", "COS", "MON", "EXP"):
            self.assertEqual(demo.rnd_setor_de(s), "PCP")


class Plano(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pl = demo.plano(agora=AGORA)
        cls.criar = [a for a in cls.pl["acoes"] if a["rest"] == "demanda/criar"]

    def test_mesma_semente_mesmo_plano(self):
        self.assertEqual(json.dumps(demo.plano(agora=AGORA)), json.dumps(demo.plano(agora=AGORA)))

    def test_semente_diferente_plano_diferente(self):
        self.assertNotEqual(json.dumps(demo.plano(semente=1, agora=AGORA)),
                            json.dumps(demo.plano(semente=2, agora=AGORA)))

    def test_agora_padrao_e_o_relogio(self):
        with mock.patch("time.time", lambda: AGORA / 1000):
            self.assertEqual(demo.plano()["agora"], AGORA)

    def test_cadastro_completo_e_valido(self):
        self.assertEqual(len(self.pl["setores"]), 6)
        self.assertEqual(len(self.pl["pessoas"]), 12)
        for s in self.pl["setores"]:
            self.assertRegex(s["id"], ds.SETOR_RE)
            self.assertIn(s["icone"], api.ICONES)
            self.assertIn(s["cor"], api.CORES)
            self.assertRegex(s["email"], api.EMAIL_RE)
            self.assertTrue(3 <= len(s["nome"]) <= 40)
        codigos = [p["codigo"] for p in self.pl["pessoas"]]
        self.assertEqual(len(set(codigos)), len(codigos))
        sids = {s["id"] for s in self.pl["setores"]}
        for n, p in enumerate(self.pl["pessoas"]):
            self.assertEqual(p["id"], "p%d" % n)   # é o id que o api.py vai dar, na mesma ordem
            self.assertRegex(p["codigo"], api.CODE_RE)
            self.assertRegex(p["email"], api.EMAIL_RE)
            self.assertIn(p["setor"], sids)
            self.assertTrue(2 <= len(p["nome"]) <= 60)

    def test_demandas_pedidas_sao_criadas(self):
        self.assertEqual(len(self.criar), demo.QUANTAS)
        self.assertEqual([a["did"] for a in self.criar],
                         ["SOL-%d" % (1001 + n) for n in range(demo.QUANTAS)])

    def test_acoes_em_ordem_de_tempo(self):
        ts = [a["t"] for a in self.pl["acoes"]]
        self.assertEqual(ts, sorted(ts))

    def test_acao_nunca_antes_da_criacao_da_demanda(self):
        criadas = set()
        for a in self.pl["acoes"]:
            if a["rest"] == "demanda/criar":
                criadas.add(a["did"])
            else:
                self.assertIn(a["did"], criadas, a)
                self.assertEqual(a["body"]["id"], a["did"])

    def test_cada_demanda_tem_so_uma_criacao(self):
        dids = [a["did"] for a in self.criar]
        self.assertEqual(len(set(dids)), len(dids))

    def test_tempos_dentro_da_janela(self):
        for a in self.pl["acoes"]:
            self.assertIsInstance(a["t"], int)   # milissegundo inteiro: é o que vai para o banco
            self.assertLessEqual(a["t"], AGORA)
            self.assertGreater(a["t"], AGORA - (demo.DIAS + 1) * demo.DIA)

    def test_historico_em_dia_util_e_horario_de_trabalho(self):
        antigas = [a for a in self.criar if a["t"] < AGORA - 12 * demo.DIA]
        self.assertTrue(antigas)
        for a in antigas:
            lt = time.localtime(a["t"] / 1000)
            self.assertLess(lt.tm_wday, 5, a["did"])
            self.assertTrue(7 <= lt.tm_hour <= 16, a["did"])

    def test_pedido_valido_para_as_rotas(self):
        sids = {s["id"] for s in self.pl["setores"]}
        pids = {p["id"] for p in self.pl["pessoas"]}
        for a in self.criar:
            b = a["body"]
            self.assertTrue(5 <= len(b["titulo"]) <= 140, b["titulo"])
            self.assertIn(b["tipo"], api.TIPOS)
            self.assertIn(b["motivo"], api.MOTIVOS)
            self.assertIn(b["prio"], api.PRIO)
            self.assertTrue(1 <= b["est"] <= api.EST_MAX)
            self.assertIn(b["para"]["s"], sids)
            self.assertTrue(b["para"]["p"] is None or b["para"]["p"] in pids)
            if a["como"] is None:
                self.assertIn(b["de_s"], sids)   # pedido do Escritório: precisa do setor solicitante
            else:
                self.assertNotIn("de_s", b)

    def test_quem_age_existe_e_cabe_na_regra(self):
        pessoas = {p["id"]: p for p in self.pl["pessoas"]}
        para: dict = {}
        for a in self.pl["acoes"]:
            self.assertTrue(a["como"] is None or a["como"] in pessoas, a)
            if a["rest"] == "demanda/criar":
                para[a["did"]] = a["body"]["para"]["s"]
            if a["rest"] == "demanda/reatribuir":
                para[a["did"]] = a["body"]["s"]
            if a["rest"] == "demanda/aceitar":   # só gente do setor responsável aceita
                self.assertEqual(pessoas[a["como"]]["setor"], para[a["did"]], a["did"])
            if a["rest"] in ("demanda/estender", "demanda/prioridade"):
                self.assertIsNone(a["como"])     # só o Escritório

    def test_pausas_e_comentarios_validos(self):
        for a in self.pl["acoes"]:
            if a["rest"] == "demanda/pausar":
                self.assertIn(a["body"]["motivo"], api.PAUSAS)
                self.assertLessEqual(len(a["body"]["obs"]), 500)
            if a["rest"] == "demanda/comentar":
                self.assertTrue(1 <= len(a["body"]["texto"]) <= 1000)
            if a["rest"] == "demanda/estender":
                self.assertTrue(1 <= a["body"]["minutos"] <= api.ESTENDER_MAX)

    def test_a_mistura_cobre_os_fluxos(self):
        contas: dict = {}
        for a in self.pl["acoes"]:
            contas[a["rest"]] = contas.get(a["rest"], 0) + 1
        for rest in ("demanda/criar", "demanda/aceitar", "demanda/concluir", "demanda/cancelar",
                     "demanda/pausar", "demanda/retomar", "demanda/reatribuir", "demanda/comentar",
                     "demanda/cobrar", "demanda/estender", "demanda/prioridade"):
            self.assertGreater(contas.get(rest, 0), 0, rest)

    def test_o_que_esta_em_aberto_e_repartido_entre_todos(self):
        """Na apresentação, entrar com qualquer código tem de mostrar trabalho na tela daquela pessoa."""
        criar = {a["did"]: a for a in self.criar}
        encerradas = {a["did"] for a in self.pl["acoes"]
                      if a["rest"] in ("demanda/concluir", "demanda/cancelar")}
        responsavel: dict = {}
        for a in self.pl["acoes"]:
            if a["did"] in encerradas:
                continue
            if a["rest"] == "demanda/criar":
                responsavel[a["did"]] = a["body"]["para"]["p"]
            elif a["rest"] == "demanda/aceitar":
                responsavel[a["did"]] = a["como"]
        por_pessoa: dict = {}
        for did, pid in responsavel.items():
            por_pessoa.setdefault(pid, []).append(did)
        for p in self.pl["pessoas"]:
            self.assertGreaterEqual(len(por_pessoa.get(p["id"], [])), 1, p["nome"])
        self.assertTrue(por_pessoa.get(None), "e alguma coisa na fila do setor")
        self.assertEqual(len(responsavel), len(criar) - len(encerradas))

    def test_quantidade_menor_mantem_a_mistura(self):
        with mock.patch.object(demo, "QUANTAS", 30):
            pl = demo.plano(agora=AGORA)
        self.assertEqual(sum(1 for a in pl["acoes"] if a["rest"] == "demanda/criar"), 30)
        self.assertGreater(len({a["rest"] for a in pl["acoes"]}), 4)

    def test_numera_segue_a_ordem_do_tempo(self):
        acoes = [{"t": 10, "rest": "demanda/criar", "did": "y", "body": {}},
                 {"t": 20, "rest": "demanda/criar", "did": "x", "body": {}},
                 {"t": 30, "rest": "demanda/aceitar", "did": "y", "body": {"id": "y"}}]
        demo._numera(acoes)
        self.assertEqual([a["did"] for a in acoes], ["SOL-1001", "SOL-1002", "SOL-1001"])
        self.assertEqual(acoes[2]["body"]["id"], "SOL-1001")   # o id acompanha a demanda, não a ordem

    def test_titulos_pouco_repetidos(self):
        titulos = [a["body"]["titulo"] for a in self.criar]
        self.assertGreater(len(set(titulos)), len(TRABALHOS_TOTAL) * 2)
        mais_repetido = max(titulos.count(t) for t in set(titulos))
        self.assertLessEqual(mais_repetido, 8)

    def test_complemento_so_quando_cabe(self):
        import random
        rnd = random.Random(5)
        longo = "x" * demo.TITULO_MAX
        self.assertEqual(demo._titulo(rnd, longo), longo)
        maior = max(demo.COMPLEMENTOS, key=len)
        with mock.patch.object(demo, "COMPLEMENTOS", (maior,)):
            cabe = "y" * (demo.TITULO_MAX - len(maior) - 3)        # título + " — " + complemento = o teto
            self.assertEqual(demo._titulo(rnd, cabe), cabe + " — " + maior)
            self.assertEqual(len(demo._titulo(rnd, cabe)), demo.TITULO_MAX)
            self.assertEqual(demo._titulo(rnd, cabe + "y"), cabe + "y")   # um caractere a mais não cabe
        with mock.patch.object(demo, "COMPLEMENTOS", ("",)):
            self.assertEqual(demo._titulo(rnd, "Cortar chapas"), "Cortar chapas")
        curtos = {demo._titulo(rnd, "Cortar chapas") for _ in range(60)}
        self.assertIn("Cortar chapas", curtos)                       # às vezes sai sem complemento
        self.assertTrue([t for t in curtos if t.startswith("Cortar chapas — ")])
        for t in curtos:
            self.assertLessEqual(len(t), demo.TITULO_MAX)

    def test_numera_a_partir_de_1001(self):
        acoes = [{"t": 1, "rest": "demanda/criar", "did": "z", "body": {}}]
        demo._numera(acoes)
        self.assertEqual(acoes[0]["did"], "SOL-1001")


class Fluxos(unittest.TestCase):
    """Cada tipo da mistura tem de virar a sequência de ações daquele fluxo: é o que dá à apresentação
    demandas concluídas, canceladas, repassadas, na fila, em andamento, pausadas e atrasadas."""

    PESSOAS = [{"id": "p%d" % n, "nome": nome, "setor": setor, "codigo": codigo, "email": email}
               for n, (nome, setor, codigo, email) in enumerate(demo.PESSOAS)]
    SIDS = [s[0] for s in demo.SETORES]

    def acoes(self, tipo: str, semente: int) -> list:
        import random
        out: list = []
        fn = demo._fechada if tipo in demo.FECHADAS else demo._aberta
        fn(out, random.Random(semente), self.PESSOAS, self.SIDS, "SOL-1001", AGORA, tipo)
        return out

    def rests(self, tipo: str, semente: int) -> list:
        return [a["rest"].replace("demanda/", "") for a in self.acoes(tipo, semente)]

    def amostra(self, tipo: str, n: int = 25) -> list:
        return [self.rests(tipo, s) for s in range(n)]

    def test_concluida(self):
        for r in self.amostra("concluida"):
            self.assertEqual(r[0], "criar")
            self.assertEqual(r[1], "aceitar")
            self.assertEqual(r[-1], "concluir")
            self.assertFalse({"pausar", "retomar", "cancelar", "reatribuir"} & set(r))
        comentarios = [r for r in self.amostra("concluida") if "comentar" in r]
        self.assertTrue(comentarios)                               # às vezes alguém comenta
        self.assertLess(len(comentarios), 25)                      # mas não em todas

    def test_concluida_com_pausa(self):
        for r in self.amostra("concluida_pausa"):
            self.assertEqual(r, ["criar", "aceitar", "pausar", "retomar", "concluir"])

    def test_concluida_atrasada_passa_do_prazo(self):
        for s in range(25):
            acoes = self.acoes("concluida_atrasada", s)
            self.assertEqual([a["rest"].replace("demanda/", "") for a in acoes][-1], "concluir")
            criar = acoes[0]["body"]
            prazo = acoes[0]["t"] + criar["est"] * demo.MIN
            self.assertGreater(acoes[-1]["t"], prazo, "concluída depois do prazo")

    def test_concluida_no_prazo(self):
        for s in range(25):
            acoes = self.acoes("concluida", s)
            prazo = acoes[0]["t"] + acoes[0]["body"]["est"] * demo.MIN
            self.assertLessEqual(acoes[-1]["t"], prazo, "concluída dentro do prazo")

    def test_repassada(self):
        for s in range(25):
            acoes = self.acoes("repassada", s)
            self.assertEqual([a["rest"].replace("demanda/", "") for a in acoes],
                             ["criar", "aceitar", "reatribuir", "aceitar", "concluir"])
            setor_novo = acoes[2]["body"]["s"]
            self.assertNotEqual(setor_novo, acoes[0]["body"]["para"]["s"])
            quem = {p["id"]: p["setor"] for p in self.PESSOAS}
            self.assertEqual(quem[acoes[3]["como"]], setor_novo)   # quem aceita depois é do setor novo
            self.assertEqual(quem[acoes[1]["como"]], acoes[0]["body"]["para"]["s"])

    def test_cancelada(self):
        for s in range(25):
            acoes = self.acoes("cancelada", s)
            self.assertEqual([a["rest"].replace("demanda/", "") for a in acoes], ["criar", "cancelar"])
            self.assertEqual(acoes[1]["como"], acoes[0]["como"])   # só quem pediu (ou o Escritório) cancela

    def test_fila(self):
        for r in self.amostra("fila"):
            self.assertEqual(r, ["criar"])
        fila = [a for s in range(25) for a in self.acoes("fila", s) if a["body"]["para"]["p"] is None]
        self.assertTrue(fila)                                      # algumas ficam na fila do setor
        self.assertLess(len(fila), 25)                             # outras já saem com responsável

    def test_andamento(self):
        for r in self.amostra("andamento"):
            self.assertEqual(r[:2], ["criar", "aceitar"])
            self.assertFalse({"pausar", "concluir", "cancelar"} & set(r))
        falantes = [r for r in self.amostra("andamento") if "comentar" in r]
        self.assertTrue(falantes)
        self.assertLess(len(falantes), 25)

    def test_pausada(self):
        for r in self.amostra("pausada"):
            self.assertEqual(r, ["criar", "aceitar", "pausar"])

    def test_atrasada(self):
        rs = self.amostra("atrasada")
        for r in rs:
            self.assertEqual(r[0], "criar")
            self.assertFalse({"concluir", "cancelar", "pausar"} & set(r))
        self.assertTrue([r for r in rs if r == ["criar"]], "algumas nem foram aceitas")
        self.assertTrue([r for r in rs if "aceitar" in r])
        self.assertTrue([r for r in rs if "cobrar" in r])
        self.assertTrue([r for r in rs if "estender" in r])
        self.assertTrue([r for r in rs if "prioridade" in r])
        for s in range(25):
            acoes = self.acoes("atrasada", s)
            prazo = acoes[0]["t"] + acoes[0]["body"]["est"] * demo.MIN
            self.assertLess(prazo, AGORA, "já passou do prazo e continua em aberto")

    def test_dentro_do_prazo_quando_nao_e_atrasada(self):
        for tipo in ("fila", "andamento", "pausada"):
            for s in range(25):
                acoes = self.acoes(tipo, s)
                prazo = acoes[0]["t"] + acoes[0]["body"]["est"] * demo.MIN
                self.assertGreater(prazo, AGORA, "%s/%d devia estar dentro do prazo" % (tipo, s))

    def test_instantes_sempre_crescentes(self):
        for tipo, _n in demo.MISTURA:
            for s in range(15):
                ts = [a["t"] for a in self.acoes(tipo, s)]
                self.assertEqual(ts, sorted(set(ts)), "%s/%d" % (tipo, s))
                self.assertLessEqual(ts[-1], AGORA)

    def test_corpo_de_cada_pedido(self):
        esperado = {"criar": {"titulo", "tipo", "motivo", "prio", "est", "para", "desc"},
                    "aceitar": {"id"}, "concluir": {"id", "nota"}, "cancelar": {"id", "motivo"},
                    "pausar": {"id", "motivo", "obs"}, "retomar": {"id"}, "cobrar": {"id"},
                    "reatribuir": {"id", "s", "p", "nota"}, "comentar": {"id", "texto"},
                    "estender": {"id", "minutos"}, "prioridade": {"id", "prio"}}
        for tipo, _n in demo.MISTURA:
            for s in range(15):
                for a in self.acoes(tipo, s):
                    rest = a["rest"].replace("demanda/", "")
                    chaves = set(a["body"]) - {"de_s"}
                    self.assertEqual(chaves, esperado[rest], rest)


class SemEspaco(unittest.TestCase):
    """Roteiro que não cabe antes de agora: a demanda é criada e nada mais entra (nunca uma ação solta)."""

    def roteiro(self, tipo: str, passos, semente: int = 3) -> list:
        import random
        acoes: list = []
        pessoas = [{"id": "p%d" % n, "nome": nome, "setor": setor, "codigo": codigo, "email": email}
                   for n, (nome, setor, codigo, email) in enumerate(demo.PESSOAS)]
        sids = [s[0] for s in demo.SETORES]
        fn = demo._fechada if tipo in demo.FECHADAS else demo._aberta
        with mock.patch.object(demo, "_passos", side_effect=passos):
            fn(acoes, random.Random(semente), pessoas, sids, "SOL-1001", AGORA, tipo)
        return acoes

    def rests(self, *a, **kw) -> list:
        return [x["rest"] for x in self.roteiro(*a, **kw)]

    def test_so_a_criacao_quando_nada_cabe(self):
        for tipo, _n in demo.MISTURA:
            self.assertEqual(self.rests(tipo, lambda *a: []), ["demanda/criar"], tipo)

    def test_fluxo_de_varios_passos_exige_todos(self):
        for tipo in ("concluida_pausa", "repassada"):
            self.assertEqual(self.rests(tipo, lambda base, o, lim: [base + 1, base + 2, base + 3]),
                             ["demanda/criar"], tipo)                     # faltou o 4º marco
        self.assertEqual(self.rests("concluida", lambda base, o, lim: [base + 1]),
                         ["demanda/criar"])                               # faltou a conclusão
        self.assertEqual(self.rests("pausada", lambda base, o, lim: [base + 1]),
                         ["demanda/criar"])                               # faltou a pausa

    def test_cobranca_e_extensao_precisam_de_tempo(self):
        curtos = [self.rests("atrasada", lambda *a: [AGORA - 2 * demo.MIN], s) for s in range(10)]
        self.assertTrue(any("demanda/aceitar" in r for r in curtos))
        for r in curtos:
            self.assertNotIn("demanda/cobrar", r)      # 2 minutos de atraso: nem dá para cobrar
            self.assertNotIn("demanda/estender", r)
        longos = [self.rests("atrasada", lambda *a: [AGORA - 600 * demo.MIN], s) for s in range(10)]
        self.assertTrue(any("demanda/cobrar" in r for r in longos))
        self.assertTrue(any("demanda/estender" in r for r in longos))
        self.assertTrue(any("demanda/prioridade" in r for r in longos))


class Linha(Base):
    def test_sem_argumento_mostra_a_ajuda(self):
        r, saida = self.saida(demo.main, [])
        self.assertEqual(r, 0)
        self.assertIn("demo.py seed", saida)

    def test_pedido_de_ajuda(self):
        for a in (["--ajuda"], ["-h"], ["--help"], ["--ajuda", "sobra"]):
            r, saida = self.saida(demo.main, a)
            self.assertEqual((r, "DEMANDAS_DATA" in saida), (0, True), a)

    def test_comando_desconhecido(self):
        r, _ = self.saida(demo.main, ["semear"])
        self.assertEqual(r, 2)

    def test_opcao_desconhecida(self):
        r, saida = self.saida(demo.main, ["seed", "--tudo"])
        self.assertEqual(r, 2)
        self.assertIn("--tudo", saida)

    def test_semente_sem_numero(self):
        for a in (["seed", "--semente"], ["seed", "--semente", "x7"], ["seed", "--semente", "X7"],
                  ["seed", "--semente", "7.5"], ["seed", "--semente", ""]):
            r, _ = self.saida(demo.main, a)
            self.assertEqual(r, 2, a)

    def test_semente_negativa_vale(self):
        with mock.patch.object(demo, "seed", return_value={"ja_existia": True, "pasta": "p"}) as m:
            r, _ = self.saida(demo.main, ["seed", "--semente", "-7"])
        self.assertEqual((r, m.call_args.kwargs["semente"]), (0, -7))

    def test_sem_argv_usa_a_linha_de_comando(self):
        with mock.patch.object(sys, "argv", ["demo.py", "seed", "--rede"]), \
                mock.patch.object(demo, "seed", return_value={"ja_existia": True, "pasta": "p"}) as m:
            r, _ = self.saida(demo.main)
        self.assertEqual(r, 0)
        self.assertEqual(m.call_args.kwargs["rede"], True)

    def test_opcoes_chegam_ao_seed(self):
        with mock.patch.object(demo, "seed", return_value={"ja_existia": True, "pasta": "p"}) as m:
            r, _ = self.saida(demo.main, ["seed", "--refazer", "--rede", "--semente", "77"])
        self.assertEqual(r, 0)
        self.assertEqual(m.call_args.kwargs, {"refazer": True, "rede": True, "semente": 77})

    def test_padroes_do_seed(self):
        with mock.patch.object(demo, "seed", return_value={"ja_existia": True, "pasta": "p"}) as m:
            self.saida(demo.main, ["seed"])
        self.assertEqual(m.call_args.kwargs, {"refazer": False, "rede": False, "semente": demo.SEMENTE})

    def test_erro_da_guarda_sai_com_1(self):
        with mock.patch.dict(os.environ, {"DEMANDAS_DATA": str(ROOT / "data")}):
            r, saida = self.saida(demo.main, ["seed"])
        self.assertEqual(r, 1)
        self.assertTrue(saida.startswith("ERRO: A demonstração nunca grava na base real"), saida)
        self.assertFalse((ROOT / "data" / demo.MARCADOR).exists())   # a base real não foi tocada

    def test_mostra_ja_existia(self):
        _, saida = self.saida(demo._mostra, {"ja_existia": True, "pasta": self.dir})
        self.assertEqual(saida.splitlines(), ["A base da demonstração já tem dados: %s" % self.dir,
                                              "Para gerar tudo de novo: py -3 demo.py seed --refazer"])

    def test_mostra_resumo_com_os_codigos(self):
        r = {"ja_existia": False, "pasta": self.dir, "demandas": 2, "notas": 5, "acoes": 9, "pulos": 1,
             "rede": True, "status": {"done": 1, "new": 1},
             "pessoas": [{"nome": "Helena Prado", "setor": "PCP", "codigo": "1101"}]}
        _, saida = self.saida(demo._mostra, r)
        linhas = saida.splitlines()
        self.assertEqual(linhas[0], "Demonstração pronta em %s" % self.dir)
        self.assertEqual(linhas[1], "2 demandas (1 concluídas, 1 na fila), 5 avisos, 9 ações aplicadas (1 puladas).")
        self.assertEqual(linhas[2], "Acesso pela rede ligado: os PINs aparecem em ⚙ Configurações.")
        self.assertEqual(linhas[4], "Códigos de 4 números para entrar como operador:")
        self.assertEqual(linhas[5].split(), ["Helena", "Prado", "PCP", "1101"])
        self.assertTrue(linhas[5].startswith("  "))

    def test_mostra_sem_pulos_nem_rede(self):
        r = {"ja_existia": False, "pasta": self.dir, "demandas": 1, "notas": 1, "acoes": 1, "pulos": 0,
             "rede": False, "status": {"prog": 1}, "pessoas": []}
        _, saida = self.saida(demo._mostra, r)
        self.assertEqual(saida.splitlines()[1], "1 demandas (1 em andamento), 1 avisos, 1 ações aplicadas.")
        self.assertNotIn("PINs", saida)

    def test_mostra_nomeia_todos_os_status(self):
        r = {"ja_existia": False, "pasta": self.dir, "demandas": 5, "notas": 0, "acoes": 0, "pulos": 0,
             "rede": False, "pessoas": [], "status": {"new": 1, "prog": 1, "pause": 1, "done": 1, "canc": 1}}
        _, saida = self.saida(demo._mostra, r)
        self.assertEqual(saida.splitlines()[1],
                         "5 demandas (1 canceladas, 1 concluídas, 1 na fila, 1 pausadas, 1 em andamento),"
                         " 0 avisos, 0 ações aplicadas.")


class Modulo(unittest.TestCase):
    def test_carrega_api_de_verdade(self):
        mod = demo.carrega_api()
        self.assertTrue(callable(mod.handle))
        self.assertEqual(mod.ITER, 100_000)   # a demonstração grava os códigos como a Produção

    def test_constantes_da_demonstracao(self):
        self.assertEqual((demo.MIN, demo.DIA), (60_000, 86_400_000))
        self.assertEqual((demo.DIAS, demo.QUANTAS, demo.TITULO_MAX), (120, 150, 140))
        self.assertEqual(demo.SEMENTE, 20261109)
        self.assertEqual(demo.ADM, {"papel": "maquina"})
        self.assertEqual(demo.OPERADOR, {"papel": "operador"})
        self.assertEqual(len(demo.SETORES), 6)
        self.assertEqual(len(demo.PESSOAS), 12)
        self.assertEqual(sum(n for _, n in demo.MISTURA), demo.QUANTAS)
        self.assertEqual(demo.MARCADOR, "demo.json")
        self.assertIn(demo.MARCADOR, demo.ARQUIVOS)
        self.assertIn("demandas.json", demo.ARQUIVOS)
        self.assertEqual(demo.PASTAS, ("demandas-anexos",))
        for tipo, _n in demo.MISTURA:
            self.assertIn(tipo, demo.FECHADAS + ("fila", "andamento", "pausada", "atrasada"))
        for sid, _nome, _icone, _cor, _email in demo.SETORES:
            self.assertIn(sid, demo.TRABALHOS)
        for _nome, setor, _codigo, _email in demo.PESSOAS:
            self.assertIn(setor, {s[0] for s in demo.SETORES})


if __name__ == "__main__":
    unittest.main()
