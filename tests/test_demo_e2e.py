"""demo.py de ponta a ponta: o seed rodando pelas rotas de verdade e o que ele deixa na pasta de dados.

Mistura reduzida (poucas demandas de cada fluxo), pbkdf2 curto e sem fsync: o teste fica rápido sem
deixar de exercitar o caminho inteiro (api.handle real, demandas.json real).
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import demo  # noqa: E402

api = demo.carrega_api()
import demandas_calc as calc  # noqa: E402
import demandas_store as ds  # noqa: E402

AGORA = 1_762_700_000_000
MISTURA = (("concluida", 3), ("concluida_pausa", 2), ("concluida_atrasada", 2), ("cancelada", 2),
           ("repassada", 2), ("fila", 2), ("andamento", 2), ("pausada", 2), ("atrasada", 2))
QUANTAS = sum(n for _, n in MISTURA)


def prepara(dir_dados: Path, registra) -> None:
    """Pasta de dados própria, pbkdf2 curto, sem fsync e mistura reduzida. registra(fn, *a) desfaz no fim."""
    env = mock.patch.dict(os.environ, {"DEMANDAS_DATA": str(dir_dados)})
    env.start()
    registra(env.stop)
    ds._CACHE.update(key=None, texto=None)
    ds._ARQ.update(key=None, demandas=[])
    api._TK.clear()
    api._FAILS.clear()
    api.ITER = 1000   # o valor real (100 000) é conferido no test_demo.py
    registra(setattr, api, "ITER", 100_000)
    patches = [mock.patch.object(demo, "carrega_api", lambda: api),
               mock.patch.object(demo, "MISTURA", MISTURA),
               mock.patch.object(demo, "QUANTAS", QUANTAS),
               mock.patch("os.fsync", lambda fd: None)]   # durabilidade é do store (testada lá); aqui só atrasa
    for p in patches:
        p.start()
        registra(p.stop)


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="dem-demo-e2e-"))
        prepara(self.dir, self.addCleanup)

    def doc(self) -> dict:
        return json.loads((self.dir / "demandas.json").read_text(encoding="utf-8"))

    def arq(self, nome: str) -> dict:
        return json.loads((self.dir / nome).read_text(encoding="utf-8"))


class Seed(unittest.TestCase):
    """Uma geração só, conferida de vários ângulos (nenhum destes testes altera o banco)."""

    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp(prefix="dem-demo-seed-"))
        prepara(cls.dir, cls.addClassCleanup)
        cls.resumo = demo.seed(agora=AGORA)
        cls.banco = json.loads((cls.dir / "demandas.json").read_text(encoding="utf-8"))
        cls.sessoes = json.loads((cls.dir / "pessoas-sessoes.json").read_text(encoding="utf-8"))["sessoes"]
        cls.relogio = (api._agora,)   # em tupla: atributo de classe com função viraria método

    def setUp(self):
        self.r, self.d = self.resumo, self.banco
        ds._CACHE.update(key=None, texto=None)

    def arq(self, nome: str) -> dict:
        return json.loads((self.dir / nome).read_text(encoding="utf-8"))

    def test_resumo_bate_com_o_arquivo(self):
        self.assertFalse(self.r["ja_existia"])
        self.assertEqual(self.r["pasta"], self.dir.resolve())
        self.assertEqual(self.r["demandas"], QUANTAS)
        self.assertEqual(len(self.d["demandas"]), QUANTAS)
        self.assertEqual(self.r["notas"], len(self.d["notas"]))
        self.assertEqual(sum(self.r["status"].values()), QUANTAS)
        self.assertEqual(self.r["acoes"] + self.r["pulos"], len(demo.plano(agora=AGORA)["acoes"]))

    def test_nenhuma_acao_recusada_pelas_regras(self):
        self.assertEqual(self.r["pulos"], 0)

    def test_demandas_gravadas_com_os_campos_da_tela(self):
        for d in self.d["demandas"]:
            self.assertEqual(d["desc"], "Sem descrição adicional.")   # o seed não manda descrição
            self.assertIsInstance(d["criado"], int)
            self.assertTrue(5 <= len(d["titulo"]) <= demo.TITULO_MAX)
            self.assertTrue(d["eventos"] and d["eventos"][0]["ev"] == "created")

    def test_cadastro_gravado(self):
        self.assertEqual([s["id"] for s in self.d["setores"]], [s[0] for s in demo.SETORES])
        self.assertEqual([p["nome"] for p in self.d["pessoas"]], [p[0] for p in demo.PESSOAS])
        for p in self.d["pessoas"]:
            self.assertTrue(p["ativo"])
            self.assertRegex(p["sal"], api.SAL_RE)
            self.assertIn("email", p)

    def test_todos_os_status_no_quadro(self):
        self.assertEqual(set(self.r["status"]), {"new", "prog", "pause", "done", "canc"})

    def test_tem_atrasada_aberta_e_dentro_do_prazo(self):
        ativas = [d for d in self.d["demandas"] if calc.ativa(d)]
        self.assertTrue([d for d in ativas if calc.atrasada(d, AGORA)])
        self.assertTrue([d for d in ativas if not calc.atrasada(d, AGORA)])

    def test_atraso_foi_avisado_pelo_programa(self):
        for d in self.d["demandas"]:
            if calc.ativa(d) and calc.atrasada(d, AGORA):
                self.assertTrue(d["atraso_avisado"], d["id"])
                self.assertIn("late", [e["ev"] for e in d["eventos"]])
        self.assertTrue([n for n in self.d["notas"] if n["tipo"] == "late"])

    def test_historico_rico(self):
        self.assertTrue([d for d in self.d["demandas"] if d["pausas"]])
        self.assertTrue([d for d in self.d["demandas"] if d["comentarios"]])
        self.assertTrue([d for d in self.d["demandas"] if len(d["eventos"]) >= 3])
        evs = {e["ev"] for d in self.d["demandas"] for e in d["eventos"]}
        for ev in ("created", "started", "done", "canc", "paused", "resumed", "reassigned"):
            self.assertIn(ev, evs)

    def test_pausa_aberta_nas_pausadas(self):
        for d in self.d["demandas"]:
            abertas = [p for p in d["pausas"] if p["fim"] is None]
            self.assertEqual(bool(abertas), d["status"] == "pause", d["id"])

    def test_meses_de_historico(self):
        criados = [d["criado"] for d in self.d["demandas"]]
        self.assertLess(min(criados), AGORA - 30 * demo.DIA)
        self.assertLessEqual(max(criados), AGORA)

    def test_ninguem_fica_identificado(self):
        self.assertEqual(self.sessoes, {})   # como ficou no fim do seed, antes de qualquer teste entrar

    def test_relogio_devolvido(self):
        self.assertEqual(self.relogio[0].__name__, "_agora")   # o relógio injetado saiu no fim do seed
        self.assertGreater(self.relogio[0](), AGORA)           # é o relógio de verdade

    def test_os_codigos_entram_de_verdade(self):
        for n, (nome, _setor, codigo, _email) in enumerate(demo.PESSOAS):
            v = api.handle("POST", "entrar", {"pessoa": "p%d" % n, "codigo": codigo}, demo.OPERADOR)
            self.assertEqual(v["eu"]["nome"], nome)

    def test_codigo_errado_nao_entra(self):
        with self.assertRaises(api.ApiError):
            api.handle("POST", "entrar", {"pessoa": "p0", "codigo": "0000"}, demo.OPERADOR)

    def test_a_vista_do_escritorio_abre(self):
        v = api.handle("GET", "", {}, demo.ADM)
        self.assertEqual(len(v["demandas"]), QUANTAS)
        self.assertTrue(v["setores"])

    def test_backup_desligado_e_sem_email(self):
        self.assertEqual(self.arq("backup.json")["on"], False)
        self.assertFalse((self.dir / "email.json").exists())
        self.assertFalse((self.dir / "email-fila.json").exists())

    def test_marcador_gravado(self):
        m = self.arq(demo.MARCADOR)
        self.assertEqual((m["demo"], m["gerado"], m["semente"]), (True, AGORA, demo.SEMENTE))
        self.assertTrue(demo.de_demonstracao())

    def test_rede_desligada_por_padrao(self):
        self.assertFalse(self.r["rede"])
        self.assertFalse((self.dir / "rede.json").exists())

    def test_nenhum_teto_do_banco_estourado(self):
        self.assertLessEqual(len(self.d["setores"]), ds.MAX["setores"])
        self.assertLessEqual(len(self.d["pessoas"]), ds.MAX["pessoas"])
        self.assertLessEqual(len(self.d["demandas"]), ds.MAX["demandas"])
        self.assertLessEqual(len(self.d["notas"]), ds.MAX["notas"])
        for d in self.d["demandas"]:
            self.assertLessEqual(len(d["eventos"]), ds.MAX["eventos"])
            self.assertLessEqual(len(d["pausas"]), ds.MAX["pausas"])
            self.assertLessEqual(len(d["comentarios"]), ds.MAX["comentarios"])
        self.assertFalse((self.dir / "demandas-arquivo.json").exists())

    def test_so_grava_na_pasta_da_demonstracao(self):
        esperado = {"demandas.json", "demandas.json.bak", "pessoas-sessoes.json", "pessoas-sessoes.json.bak",
                    "backup.json", demo.MARCADOR}
        self.assertTrue({p.name for p in self.dir.iterdir()} <= esperado)


class Repetir(Base):
    def test_segunda_vez_nao_mexe_em_nada(self):
        demo.seed(agora=AGORA)
        antes = (self.dir / "demandas.json").read_text(encoding="utf-8")
        r = demo.seed(agora=AGORA + demo.DIA)
        self.assertTrue(r["ja_existia"])
        self.assertEqual(r["pasta"], self.dir.resolve())
        self.assertNotIn("demandas", r)
        self.assertEqual((self.dir / "demandas.json").read_text(encoding="utf-8"), antes)

    def test_refazer_gera_de_novo(self):
        demo.seed(agora=AGORA)
        rev1, m1 = self.doc()["rev"], self.arq(demo.MARCADOR)["gerado"]
        r = demo.seed(refazer=True, agora=AGORA + demo.DIA)
        self.assertFalse(r["ja_existia"])
        self.assertEqual(len(self.doc()["demandas"]), QUANTAS)     # não acumulou
        self.assertLess(self.doc()["rev"], rev1 * 2)               # base nova, do zero
        self.assertEqual(self.arq(demo.MARCADOR)["gerado"], m1 + demo.DIA)

    def test_refazer_recusa_pasta_que_nao_e_da_demonstracao(self):
        demo.seed(agora=AGORA)
        (self.dir / demo.MARCADOR).unlink()   # como se fosse uma base de verdade
        antes = (self.dir / "demandas.json").read_text(encoding="utf-8")
        with self.assertRaises(demo.DemoErro):
            demo.seed(refazer=True, agora=AGORA)
        self.assertEqual((self.dir / "demandas.json").read_text(encoding="utf-8"), antes)

    def test_semente_diferente_muda_as_demandas(self):
        demo.seed(agora=AGORA)
        titulos1 = [d["titulo"] for d in self.doc()["demandas"]]
        demo.seed(refazer=True, semente=99, agora=AGORA)
        self.assertNotEqual([d["titulo"] for d in self.doc()["demandas"]], titulos1)

    def test_rede_ligada_com_pins(self):
        r = demo.seed(rede=True, agora=AGORA)
        self.assertTrue(r["rede"])
        cfg = self.arq("rede.json")
        self.assertTrue(cfg["on"])
        self.assertRegex(cfg["pin"], r"^[0-9]{6}$")
        self.assertRegex(cfg["pin_op"], r"^[0-9]{6}$")
        self.assertNotEqual(cfg["pin"], cfg["pin_op"])

    def test_pasta_criada_se_nao_existir(self):
        nova = self.dir / "sub" / "data-demo"
        with mock.patch.dict(os.environ, {"DEMANDAS_DATA": str(nova)}):
            demo.seed(agora=AGORA)
            self.assertTrue((nova / "demandas.json").exists())


class Recusada(Base):
    """Ação que a regra do programa não aceita: o seed conta como pulo e segue (a demanda fica como está)."""

    def test_acoes_recusadas_sao_puladas(self):
        real = demo.plano

        def com_intrusas(*a, **kw):
            pl = real(*a, **kw)
            criar = next(x for x in pl["acoes"] if x["rest"] == "demanda/criar")
            de_outro = next(p for p in pl["pessoas"] if p["setor"] != criar["body"]["para"]["s"])
            for n in range(2):   # duas recusadas: o contador soma, não fica em 1
                pl["acoes"].append({"t": pl["agora"], "como": de_outro["id"], "did": criar["did"],
                                    "rest": "demanda/aceitar", "body": {"id": criar["did"]}, "ordem": 900 + n})
            return pl

        with mock.patch.object(demo, "plano", com_intrusas):
            r = demo.seed(agora=AGORA)
        self.assertEqual(r["pulos"], 2)
        self.assertEqual(r["acoes"] + r["pulos"], len(demo.plano(agora=AGORA)["acoes"]) + 2)
        self.assertEqual(r["demandas"], QUANTAS)   # o resto foi gravado normalmente


class Linha(Base):
    def test_main_roda_o_seed(self):
        import io
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            r = demo.main(["seed"])
        self.assertEqual(r, 0)
        self.assertIn("Demonstração pronta", buf.getvalue())
        self.assertIn("1101", buf.getvalue())
        self.assertEqual(len(self.doc()["demandas"]), QUANTAS)


if __name__ == "__main__":
    unittest.main()
