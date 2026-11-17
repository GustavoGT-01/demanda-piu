"""demandas_store: vazio, normalização, migração com cópia, corrompido, cache, commit/rev, arquivo morto e anexos.

Dados num diretório temporário (DEMANDAS_DATA) por teste.
"""

import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parents[1] / "demandas"   # pasta do módulo
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import store
import demandas_agenda as ag
import demandas_store as ds

JPG = b"\xff\xd8\xff\xe0" + b"j" * 20
PNG = b"\x89PNG\r\n\x1a\n" + b"p" * 20
PDF = b"%PDF-1.7\n" + b"d" * 20


def dem(n, status="new", fim=None, criado=0, **kw):
    d = {"id": "SOL-%d" % n, "titulo": "Demanda %d" % n, "tipo": "dem", "motivo": "Outro", "prio": "norm", "est": 60,
         "de": {"s": "PCP", "p": "p1"}, "para": {"s": "CNC", "p": None}, "desc": "x", "status": status,
         "criado": criado, "iniciado": None, "fim": fim, "atraso_avisado": False,
         "pausas": [], "eventos": [], "comentarios": [], "anexos": [], "_rv": 0}
    d.update(kw)
    return d


class Base(unittest.TestCase):
    def setUp(self):
        self._data = os.environ.get("DEMANDAS_DATA")
        self.dir = Path(tempfile.mkdtemp(prefix="dem-store-"))
        os.environ["DEMANDAS_DATA"] = str(self.dir)
        ds._CACHE.update(key=None, texto=None)
        ds._ARQ.update(key=None, demandas=[])

    def tearDown(self):
        if self._data is None:
            os.environ.pop("DEMANDAS_DATA", None)
        else:
            os.environ["DEMANDAS_DATA"] = self._data

    def grava(self, raw, nome="demandas.json"):
        (self.dir / nome).write_text(raw if isinstance(raw, str) else json.dumps(raw), encoding="utf-8")

    def disco(self, nome="demandas.json"):
        return json.loads((self.dir / nome).read_text(encoding="utf-8"))


class Carga(Base):
    def test_caminhos(self):
        self.assertEqual(ds.path(), self.dir / "demandas.json")
        self.assertEqual(ds.anexos_dir(), self.dir / "demandas-anexos")
        self.assertEqual(ds.arquivo_path(), self.dir / "demandas-arquivo.json")

    def test_ausente_e_vazio_sem_gravar(self):
        doc = ds.load()
        self.assertEqual(doc, ds.empty())
        self.assertEqual(doc, {"v": 2, "rev": 0, "seq": {"pessoa": 0, "demanda": 1000, "nota": 0},
                               "setores": [], "pessoas": [], "demandas": [], "notas": [], "cids": [],
                               "agenda": ag.padrao(), "agendas": {}})
        self.assertFalse(ds.path().exists())
        self.assertEqual(ds.load(cache=False), ds.empty())
        self.assertIsNot(ds.empty()["seq"], ds.empty()["seq"])

    def test_nao_objeto_vira_vazio(self):
        for raw in ("[1, 2]", "null", '"texto"', "7"):
            self.grava(raw)
            self.assertEqual(ds.load(cache=False), ds.empty(), raw)

    def test_notas_por_pessoa(self):
        self.grava({"v": 1, "notas": [{"id": 1, "aud": "CNC", "lida": True},
                                      {"id": 2, "aud": "CNC", "pid": "p1", "lidas": ["p2", 3, None]},
                                      {"id": 3, "aud": "CNC", "pid": 5, "lidas": "p1"},
                                      {"id": 4, "aud": "CNC", "pid": None}]})
        n = {x["id"]: x for x in ds.load()["notas"]}
        self.assertNotIn("pid", n[1], "nota antiga continua sem pid (vale para o setor todo)")
        self.assertEqual((n[1]["lidas"], n[2]["pid"], n[2]["lidas"], n[3]["pid"], n[3]["lidas"], n[4]["pid"]),
                         ([], "p1", ["p2"], None, [], None))

    def test_cids(self):
        boas = [["c%07d" % i, "SOL-%d" % i] for i in range(ds.MAX["cids"] + 2)]
        ruins = ["x", ["so-um"], ["a", "b", "c"], ["a", 1], [1, "b"], {"a": "b"}]
        self.grava({"v": 1, "cids": ruins + boas})
        self.assertEqual(ds.load()["cids"], boas[-ds.MAX["cids"]:], "as mais novas, só pares de texto")
        ds._CACHE.update(key=None, texto=None)
        self.grava({"v": 1, "cids": [boas[0]] + ruins + [boas[1]]})
        self.assertEqual(ds.load()["cids"], boas[:2], "linha estranha sai mesmo longe do teto")
        for raw in ({"v": 1}, {"v": 1, "cids": "x"}, {"v": 1, "cids": {"a": "b"}}):
            ds._CACHE.update(key=None, texto=None)
            self.grava(raw)
            self.assertEqual(ds.load()["cids"], [])

    def test_normaliza_tipos_e_descarta_linhas(self):
        boa = dem(1001, est="60", criado=True, iniciado=5, fim="x", atraso_avisado=1, _rv=None,
                  pausas={"a": 1}, eventos=[{"t": 1, "ev": "created"}, "lixo", 3],
                  anexos=[{"id": "a0123456789abcdef", "nome": "f.jpg"}, {"id": "a0123456789abcdef"},
                          {"id": "../x"}, {"id": "a0123456789abcdef\n"}, "x"])
        boa.pop("comentarios")
        self.grava({
            "v": 1, "rev": "9", "seq": {"pessoa": -3, "demanda": 1500, "nota": "x"},
            "setores": [{"id": "CNC", "nome": "CNC"}, {"id": "CNC", "nome": "duplicado"}, {"id": "cnc"},
                        {"id": "ABCDE"}, {"id": "A"}, {"id": "PCP\n"}, "lixo",
                        {"id": "PCP", "ativo": False, "_rv": 3}, {"id": "MAN", "ativo": "sim", "_rv": 1.5}],
            "pessoas": [{"id": "p0", "nome": "Ana"}, {"id": "p1", "ativo": False, "_rv": 2}, {"id": "x1"},
                        {"id": 5}, {"id": "p"}, {"id": "p0"}],
            "demandas": [boa, dem(1002, status="zzz"), dem(1003, de=None), dem(1004, para={"s": 3}),
                         dem(1005, para={"s": "CNC", "p": 7}), {"id": "SOL-x"}, dem(1001), "lixo",
                         dem(1006, status="done", fim=10, _rv=4)],
            "notas": [{"id": 1, "lida": "não"}, {"id": True}, {"id": "2"}, {"id": 1}, {"id": 3, "lida": True}],
        })
        doc = ds.load()
        self.assertEqual(doc["rev"], 0)
        self.assertEqual(doc["seq"], {"pessoa": 0, "demanda": 1500, "nota": 0})
        self.assertEqual([(s["id"], s["ativo"], s["_rv"]) for s in doc["setores"]],
                         [("CNC", True, 0), ("PCP", False, 3), ("MAN", True, 0)])
        self.assertEqual(doc["setores"][0]["nome"], "CNC")
        self.assertEqual([(p["id"], p["ativo"], p["_rv"]) for p in doc["pessoas"]], [("p0", True, 0), ("p1", False, 2)])
        self.assertEqual([d["id"] for d in doc["demandas"]], ["SOL-1001", "SOL-1005", "SOL-1006"])
        d = doc["demandas"][0]
        self.assertEqual((d["est"], d["criado"], d["iniciado"], d["fim"], d["atraso_avisado"], d["_rv"]),
                         (60, 0, 5, None, False, 0))
        self.assertEqual(d["pausas"], [])
        self.assertEqual(d["comentarios"], [])
        self.assertEqual(d["eventos"], [{"t": 1, "ev": "created"}])
        self.assertEqual(d["anexos"], [{"id": "a0123456789abcdef", "nome": "f.jpg"}])
        self.assertEqual(doc["demandas"][1]["para"], {"s": "CNC", "p": None})
        self.assertEqual(doc["demandas"][1]["de"], {"s": "PCP", "p": "p1"})
        self.assertEqual((doc["demandas"][2]["fim"], doc["demandas"][2]["_rv"]), (10, 4))
        self.assertEqual([(n["id"], n["lida"]) for n in doc["notas"]], [(1, False), (3, True)])

    def test_valores_bons_ficam(self):
        d = dem(1001, est=90, criado=5, iniciado=6, fim=7, atraso_avisado=True, status="done", _rv=2)
        self.grava({"v": 1, "rev": 4, "seq": {"pessoa": 2, "demanda": 1001, "nota": 3}, "demandas": [d],
                    "setores": [], "pessoas": [], "notas": []})
        doc = ds.load()
        self.assertEqual(doc["rev"], 4)
        self.assertEqual(doc["seq"], {"pessoa": 2, "demanda": 1001, "nota": 3})
        self.assertEqual(doc["demandas"], [d])

    def test_listas_ausentes_ou_de_tipo_errado(self):
        self.grava({"v": 1, "rev": -5, "seq": [1], "setores": {"id": "CNC"}, "pessoas": "x", "demandas": None})
        doc = ds.load()
        self.assertEqual(doc, ds.empty())

    def test_corrompido_usa_bak(self):
        self.grava({"v": 1, "rev": 7, "demandas": [dem(1001)]}, "demandas.json.bak")
        self.grava("{quebrado")
        doc = ds.load()
        self.assertEqual(doc["rev"], 7)
        self.assertEqual(len(doc["demandas"]), 1)
        self.assertTrue(any(p.name.startswith("demandas.json.corrompido-") for p in self.dir.iterdir()))
        self.assertEqual(self.disco()["rev"], 7)   # a cópia virou o principal

    def test_corrompido_sem_bak_recusa(self):
        self.grava("{quebrado")
        with self.assertRaises(ds.StoreError) as cm:
            ds.load()
        self.assertEqual(cm.exception.status, 500)
        self.assertIn("corrompido", str(cm.exception))
        self.assertEqual((self.dir / "demandas.json").read_text(encoding="utf-8"), "{quebrado")

    def test_versao_mais_nova_recusa_sem_gravar(self):
        self.grava({"v": 3, "rev": 3, "demandas": []})
        antes = (self.dir / "demandas.json").read_bytes()
        with self.assertRaises(ds.StoreError) as cm:
            ds.load()
        self.assertEqual(cm.exception.status, 500)
        self.assertEqual((self.dir / "demandas.json").read_bytes(), antes)


class Sobreviventes(Base):
    """Casos que a mutação mostrou sem teste."""

    def test_todos_os_status_validos_ficam(self):
        self.grava({"v": 1, "demandas": [dem(1000 + i, status=s) for i, s in enumerate(ds.STATUS)]})
        self.assertEqual([d["status"] for d in ds.load()["demandas"]], ["new", "prog", "pause", "done", "canc"])

    def test_modulo_novo_sem_reset_do_cache(self):
        # primeira carga do processo: o cache vem do próprio módulo, não do setUp
        import importlib.util
        spec = importlib.util.spec_from_file_location("demandas_store_novo", HERE / "demandas_store.py")
        novo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(novo)
        self.grava({"v": 1, "rev": 2})
        self.grava({"v": 1, "demandas": []}, "demandas-arquivo.json")
        self.assertEqual(novo.load()["rev"], 2)
        self.assertEqual(novo.load_arquivo(), [])

    def test_grava_acentos_sem_escapar(self):
        self.grava({"rev": 1, "x": "ação"})   # migração
        ds.load()
        self.assertIn("ação", (self.dir / "demandas.json").read_text(encoding="utf-8"))
        doc = ds.load()
        doc["setores"].append({"id": "CNC", "nome": "Usinagem é"})
        ds.commit(doc)
        self.assertIn("Usinagem é", (self.dir / "demandas.json").read_text(encoding="utf-8"))
        with mock.patch.dict(ds.MAX, demandas=1):
            doc = ds.load()
            doc["demandas"] = [dem(1001, status="done", fim=1, titulo="Peça"), dem(1002)]
            ds.commit(doc)
        self.assertIn("Peça", (self.dir / "demandas-arquivo.json").read_text(encoding="utf-8"))

    def test_migracao_deixa_cache_valido(self):
        self.grava({"rev": 3})
        ds.load()
        with mock.patch.object(store, "_read_safe", side_effect=AssertionError("releu")):
            self.assertEqual(ds.load()["rev"], 3)

    def test_quando(self):
        self.assertEqual(ds._quando({"id": "SOL-7"}), (0, 7))
        self.assertEqual(ds._quando({"id": "SOL-7", "criado": 50}), (50, 7))
        self.assertEqual(ds._quando({"id": "SOL-7", "criado": 50, "fim": 80}), (80, 7))

    def test_mensagens(self):
        casos = [(b"", 400, "Anexo vazio."), (JPG + b"\0" * ds.ANEXO_MAX, 413, "Anexo maior que 5 MB."),
                 (b"GIF89a", 400, "Tipo de arquivo não aceito: use JPG, PNG ou PDF.")]
        for dados, st, msg in casos:
            with self.assertRaises(ds.StoreError) as cm:
                ds.salvar_anexo(dados, "x")
            self.assertEqual((cm.exception.status, str(cm.exception)), (st, msg))
        with mock.patch.object(ds, "COTA", 1):
            with self.assertRaises(ds.StoreError) as cm:
                ds.salvar_anexo(JPG, "x")
        self.assertEqual(str(cm.exception), "Espaço dos anexos esgotado (300 MB). Apague anexos antigos.")
        self.grava({"v": 3})
        with self.assertRaises(ds.StoreError) as cm:
            ds.load()
        self.assertEqual(str(cm.exception), "Demandas gravadas por uma versão mais nova da Central de demandas: atualize o programa.")


class Migracao(Base):
    def test_sem_v_migra_com_copia(self):
        raw = {"rev": 2, "demandas": [dem(1001)], "extra": "fica"}
        self.grava(raw)
        antes = (self.dir / "demandas.json").read_bytes()
        doc = ds.load()
        self.assertEqual(doc["v"], 2)
        self.assertEqual(doc["rev"], 2)
        self.assertEqual((self.dir / "demandas.json.v0.bak").read_bytes(), antes)
        self.assertEqual((self.dir / "demandas.json.bak").read_bytes(), antes)
        gravado = self.disco()
        self.assertEqual(gravado["v"], 2)
        self.assertEqual(gravado["extra"], "fica")   # migrar não joga fora campo desconhecido
        # a próxima carga não migra de novo nem pisa na cópia
        (self.dir / "demandas.json.v0.bak").write_bytes(b"guardada")
        ds.commit(ds.load())
        ds.load(cache=False)
        self.assertEqual((self.dir / "demandas.json.v0.bak").read_bytes(), b"guardada")

    def test_v_invalido_conta_como_zero(self):
        for v in ("1", True, None, 0, 1.0):
            self.grava({"v": v, "rev": 1})
            for p in self.dir.glob("*.bak"):
                p.unlink()
            ds.load(cache=False)
            self.assertTrue((self.dir / "demandas.json.v0.bak").exists(), v)
            self.assertEqual(self.disco()["v"], 2)

    def test_v1_migra_para_v2_sem_mexer_nas_demandas(self):
        # o horário de serviço nasce desligado: demanda sem agenda_v segue em tempo corrido, sem backfill
        self.grava({"v": 1, "rev": 5, "demandas": [dem(1001, est=30)]})
        antes = (self.dir / "demandas.json").read_bytes()
        doc = ds.load()
        self.assertEqual((doc["v"], doc["rev"]), (2, 5))
        self.assertEqual((self.dir / "demandas.json.v1.bak").read_bytes(), antes)
        self.assertFalse(doc["agenda"]["ativa"])
        self.assertEqual(doc["agendas"], {})
        d = doc["demandas"][0]
        self.assertNotIn("agenda_v", d)
        self.assertNotIn("prazo_em", d)
        self.assertEqual(self.disco()["v"], 2)

    def test_v2_nao_migra(self):
        self.grava({"v": 2, "rev": 1})
        mt = (self.dir / "demandas.json").stat().st_mtime_ns
        ds.load()
        self.assertFalse(list(self.dir.glob("*.bak")))
        self.assertEqual((self.dir / "demandas.json").stat().st_mtime_ns, mt)

    def test_migra_lido_do_bak_sem_principal(self):
        # entre os dois renomes do atomic_write só existe o .bak: migra sem copiar o principal ausente
        self.grava({"rev": 4}, "demandas.json.bak")
        doc = ds.load()
        self.assertEqual(doc["rev"], 4)
        self.assertFalse((self.dir / "demandas.json.v0.bak").exists())
        self.assertEqual(self.disco()["v"], 2)


class Cache(Base):
    def test_cache_por_mtime_e_tamanho(self):
        ds.commit(ds.empty())
        with mock.patch.object(store, "_read_safe", side_effect=AssertionError("releu")):
            a = ds.load()
            b = ds.load()
        self.assertEqual(a, b)
        self.assertIsNot(a, b)   # cada carga é do chamador: alterar uma não muda a outra
        a["setores"].append({"id": "XX"})
        self.assertEqual(ds.load()["setores"], [])
        # outro processo mudou o arquivo: a chave muda e relê
        self.grava({"v": 1, "rev": 50})
        self.assertEqual(ds.load()["rev"], 50)

    def test_sem_cache_sempre_le(self):
        ds.commit(ds.empty())
        real = store._read_safe
        with mock.patch.object(store, "_read_safe", side_effect=real) as m:
            ds.load(cache=False)
            ds.load(cache=False)
        self.assertEqual(m.call_count, 2)

    def test_mesma_chave_outro_arquivo_nao_confunde(self):
        ds.commit(ds.empty())
        k = ds._CACHE["key"]
        self.assertEqual(k[0], str(ds.path()))
        self.assertEqual(k, ds._chave(ds.path()))

    def test_chave_ausente(self):
        self.assertIsNone(ds._chave(self.dir / "nada.json"))


class Commit(Base):
    def test_rev_e_gravacao(self):
        doc = ds.load()
        doc["setores"].append({"id": "CNC", "nome": "CNC", "ativo": True, "_rv": 0})
        out = ds.commit(doc)
        self.assertIs(out, doc)
        self.assertEqual(out["rev"], 1)
        self.assertEqual(self.disco()["rev"], 1)
        self.assertEqual(self.disco()["setores"][0]["id"], "CNC")
        doc2 = ds.load()
        self.assertEqual(ds.commit(doc2)["rev"], 2)
        self.assertEqual(ds.load()["rev"], 2)
        self.assertTrue((self.dir / "demandas.json.bak").exists())
        self.assertEqual(json.loads((self.dir / "demandas.json.bak").read_text(encoding="utf-8"))["rev"], 1)

    def test_rev_ruim_e_v_corrigidos(self):
        out = ds.commit({"rev": "x", "v": 9, "demandas": []})
        self.assertEqual((out["rev"], out["v"]), (1, 2))

    def test_commit_atualiza_cache(self):
        doc = ds.load()
        doc["notas"].append({"id": 1, "lida": False})
        ds.commit(doc)
        with mock.patch.object(store, "_read_safe", side_effect=AssertionError("releu")):
            self.assertEqual(ds.load()["notas"], [{"id": 1, "lida": False}])

    def test_falha_na_gravacao_nao_suja_cache(self):
        ds.commit(ds.empty())
        doc = ds.load()
        doc["rev"] = 40
        with mock.patch.object(store, "atomic_write", side_effect=OSError("disco cheio")):
            with self.assertRaises(OSError):
                ds.commit(doc)
        self.assertEqual(ds.load()["rev"], 1)

    def test_dois_commits_sob_lock(self):
        ds.commit(ds.empty())
        erros = []

        def um(sid):
            try:
                with ds.LOCK:
                    doc = ds.load()
                    doc["setores"].append({"id": sid, "nome": sid, "ativo": True, "_rv": 0})
                    ds.commit(doc)
            except Exception as exc:   # noqa: BLE001 (falha aparece no assert)
                erros.append(exc)

        ts = [threading.Thread(target=um, args=(s,)) for s in ("AA", "BB", "CC", "DD")]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(erros, [])
        doc = ds.load(cache=False)
        self.assertEqual(doc["rev"], 5)
        self.assertEqual(sorted(s["id"] for s in doc["setores"]), ["AA", "BB", "CC", "DD"])


class Arquivo(Base):
    def setUp(self):
        super().setUp()
        self._max = dict(ds.MAX)
        ds.MAX["demandas"] = 10
        ds.MAX["arquivo"] = 6

    def tearDown(self):
        ds.MAX.clear()
        ds.MAX.update(self._max)
        super().tearDown()

    def test_teto_nao_passou_nao_arquiva(self):
        doc = ds.empty()
        doc["demandas"] = [dem(1000 + i, status="done", fim=i) for i in range(10)]
        ds.commit(doc)
        self.assertEqual(len(ds.load()["demandas"]), 10)
        self.assertFalse(ds.arquivo_path().exists())
        self.assertEqual(ds.load_arquivo(), [])

    def test_passou_do_teto_arquiva_as_mais_antigas_fechadas(self):
        doc = ds.empty()
        # 11 > teto 10: sai até 9 (90%), ou seja 2; abertas nunca saem, mesmo sendo as mais antigas
        doc["demandas"] = ([dem(1001 + i, status=s, criado=0) for i, s in enumerate(("new", "prog", "pause"))]
                           + [dem(1010, status="done", fim=500), dem(1011, status="canc", fim=100),
                              dem(1012, status="done", fim=None, criado=50), dem(1013, status="done", fim=300),
                              dem(1014, status="canc", fim=300), dem(1015, status="done", fim=900),
                              dem(1016, status="new", criado=1), dem(1017, status="done", fim=950)])
        ds.commit(doc)
        ficou = [d["id"] for d in ds.load()["demandas"]]
        self.assertEqual(len(ficou), 9)
        self.assertNotIn("SOL-1012", ficou)   # sem fim: conta a criação (50)
        self.assertNotIn("SOL-1011", ficou)   # fim 100
        for aberta in ("SOL-1001", "SOL-1002", "SOL-1003", "SOL-1016"):
            self.assertIn(aberta, ficou)
        self.assertEqual([d["id"] for d in ds.load_arquivo()], ["SOL-1012", "SOL-1011"])
        arq = self.disco("demandas-arquivo.json")
        self.assertEqual(arq["v"], 2)
        self.assertEqual([d["id"] for d in arq["demandas"]], ["SOL-1012", "SOL-1011"])
        self.assertEqual(len(doc["demandas"]), 9)   # o doc devolvido já está enxuto

    def test_empate_no_fim_sai_o_menor_numero(self):
        doc = ds.empty()
        doc["demandas"] = [dem(1000 + i, status="new") for i in range(9)] + [
            dem(1020, status="done", fim=5), dem(1019, status="done", fim=5)]
        ds.commit(doc)
        self.assertEqual([d["id"] for d in ds.load_arquivo()], ["SOL-1019", "SOL-1020"])

    def test_so_abertas_acima_do_teto(self):
        doc = ds.empty()
        doc["demandas"] = [dem(1000 + i, status="prog") for i in range(12)]
        ds.commit(doc)
        self.assertEqual(len(ds.load()["demandas"]), 12)
        self.assertFalse(ds.arquivo_path().exists())

    def test_arquivo_acumula_sem_repetir_e_corta_no_teto(self):
        doc = ds.empty()
        doc["demandas"] = [dem(2000 + i, status="new") for i in range(8)]
        for n in range(1, 6):   # cada rodada: 8 abertas + 3 fechadas = 11 -> 2 saem
            doc["demandas"] += [dem(1000 + 10 * n + j, status="done", fim=10 * n + j) for j in range(3)]
            doc = ds.commit(doc)
            self.assertEqual(len(doc["demandas"]), 9)
        ids = [d["id"] for d in ds.load_arquivo()]
        self.assertEqual(len(ids), 6)   # teto do arquivo: as mais antigas se perdem
        self.assertEqual(len(set(ids)), 6)
        fins = [d["fim"] for d in ds.load_arquivo()]
        self.assertEqual(fins, sorted(fins))
        self.assertEqual(fins[-1], 51)   # sobra a mais nova fechada no principal (52)
        # gravação que caiu depois do arquivo e antes do principal: repetir não duplica
        doc2 = ds.load()
        ultimo = ds.load_arquivo()[-1]
        doc2["demandas"] += [dict(ultimo), dem(3000, status="new"), dem(3001, status="new")]
        ds.commit(doc2)
        ids = [d["id"] for d in ds.load_arquivo()]
        self.assertEqual(ids.count(ultimo["id"]), 1)

    def test_arquivo_corrompido_ou_estranho(self):
        self.grava("[1]", "demandas-arquivo.json")
        self.assertEqual(ds.load_arquivo(), [])
        self.grava({"v": 1, "demandas": [dem(1001, status="done"), "lixo", {"id": "x"}]}, "demandas-arquivo.json")
        self.assertEqual([d["id"] for d in ds.load_arquivo()], ["SOL-1001"])
        self.grava("{ruim", "demandas-arquivo.json")
        with self.assertRaises(ds.StoreError):
            ds.load_arquivo()

    def test_arquivo_cache_por_mtime(self):
        self.grava({"v": 1, "demandas": [dem(1001, status="done")]}, "demandas-arquivo.json")
        a = ds.load_arquivo()
        with mock.patch.object(store, "_read_safe", side_effect=AssertionError("releu")):
            self.assertIs(ds.load_arquivo(), a)
        self.grava({"v": 1, "demandas": [dem(1001, status="done"), dem(1002, status="canc")]}, "demandas-arquivo.json")
        self.assertEqual(len(ds.load_arquivo()), 2)

    def test_teto_real(self):
        self.assertEqual(self._max["demandas"], 5000)
        self.assertEqual(self._max["arquivo"], 50000)
        self.assertEqual(self._max, {"setores": 60, "pessoas": 500, "demandas": 5000, "arquivo": 50000,
                                     "pausas": 200, "eventos": 500, "comentarios": 300, "notas": 1000, "cids": 500,
                                     "feriados": 400, "versoes": 50})

    def test_num_sem_id_valido(self):
        self.assertEqual(ds._num({"id": "SOL-42"}), 42)
        self.assertEqual(ds._num({"id": "x"}), 0)
        self.assertEqual(ds._num({}), 0)


class Anexos(Base):
    def test_constantes(self):
        self.assertEqual(ds.ANEXO_MAX, 5 * 1024 * 1024)
        self.assertEqual(ds.COTA, 300 * 1024 * 1024)
        self.assertEqual(ds.ANEXOS_POR_DEMANDA, 5)
        self.assertEqual(ds.V, 2)

    def test_cada_tipo_aceito(self):
        for dados, tipo in ((JPG, "jpg"), (PNG, "png"), (PDF, "pdf")):
            info = ds.salvar_anexo(dados, "foto.%s" % tipo)
            self.assertRegex(info["id"], r"^a[0-9a-f]{16}$")
            self.assertEqual(info, {"id": info["id"], "nome": "foto.%s" % tipo, "tipo": tipo, "bytes": len(dados)})
            f = self.dir / "demandas-anexos" / ("%s.%s" % (info["id"], tipo))
            self.assertEqual(f.read_bytes(), dados)
            self.assertEqual(ds.ler_anexo(info["id"]), (dados, tipo))
        self.assertEqual(sorted(p.suffix for p in ds.anexos_dir().iterdir()), [".jpg", ".pdf", ".png"])

    def test_bytearray(self):
        info = ds.salvar_anexo(bytearray(PNG), "x.png")
        self.assertEqual(ds.ler_anexo(info["id"]), (PNG, "png"))

    def test_tipo_falso(self):
        for dados in (b"GIF89a" + b"x" * 10, b"MZ\x90\x00", b"\xff\xd8", b"\x89PNG\r\n\x1a", b"%PDF", b"<html>",
                      b"x" + JPG):
            with self.assertRaises(ds.StoreError) as cm:
                ds.salvar_anexo(dados, "foto.jpg")
            self.assertEqual(cm.exception.status, 400)
        self.assertFalse(ds.anexos_dir().exists())

    def test_vazio_e_tipo_errado(self):
        for dados, status in ((b"", 400), (None, 400), ("texto", 400), ([1], 400)):
            with self.assertRaises(ds.StoreError) as cm:
                ds.salvar_anexo(dados, "x.jpg")
            self.assertEqual(cm.exception.status, status)
        self.assertEqual(str(cm.exception), "Anexo inválido.")

    def test_limite_de_5mb(self):
        exato = JPG + b"\0" * (ds.ANEXO_MAX - len(JPG))
        self.assertEqual(len(exato), 5 * 1024 * 1024)
        info = ds.salvar_anexo(exato, "grande.jpg")
        self.assertEqual(info["bytes"], ds.ANEXO_MAX)
        with self.assertRaises(ds.StoreError) as cm:
            ds.salvar_anexo(exato + b"\0", "grande.jpg")
        self.assertEqual(cm.exception.status, 413)
        self.assertEqual(len(list(ds.anexos_dir().iterdir())), 1)

    def test_cota(self):
        with mock.patch.object(ds, "COTA", 3 * len(PNG)):
            ds.salvar_anexo(PNG, "1.png")
            ds.salvar_anexo(PNG, "2.png")
            ds.salvar_anexo(PNG, "3.png")   # exatamente na cota
            self.assertEqual(ds.uso_anexos(), {"bytes": 3 * len(PNG), "cota": 3 * len(PNG)})
            with self.assertRaises(ds.StoreError) as cm:
                ds.salvar_anexo(PNG, "4.png")
            self.assertEqual(cm.exception.status, 507)
            self.assertEqual(len(list(ds.anexos_dir().iterdir())), 3)

    def test_cota_soma_a_pasta_inteira(self):
        ds.anexos_dir().mkdir()
        (ds.anexos_dir() / "outro.bin").write_bytes(b"x" * 100)
        (ds.anexos_dir() / "sub").mkdir()
        self.assertEqual(ds.uso_anexos(), {"bytes": 100, "cota": ds.COTA})
        with mock.patch.object(ds, "COTA", 100 + len(JPG) - 1):
            with self.assertRaises(ds.StoreError):
                ds.salvar_anexo(JPG, "x.jpg")

    def test_uso_sem_pasta(self):
        self.assertEqual(ds.uso_anexos(), {"bytes": 0, "cota": 300 * 1024 * 1024})

    def test_uso_arquivo_sumiu_no_meio(self):
        ds.salvar_anexo(JPG, "x.jpg")
        real = os.scandir

        class Some:
            def is_file(self):
                return True

            def stat(self):
                raise FileNotFoundError

        with mock.patch.object(ds.os, "scandir", lambda p: list(real(p)) + [Some()]):
            self.assertEqual(ds.uso_anexos()["bytes"], len(JPG))

    def test_nome_so_metadado(self):
        casos = {"../../etc/passwd": "../../etc/passwd", "a\x00b\nc\x7fd.jpg": "abcd.jpg",
                 "foto‮gpj.exe": "fotogpj.exe", "   ": "anexo.jpg", None: "anexo.jpg", 5: "anexo.jpg",
                 "x" * 200: "x" * 120, "  nome  ": "nome", "é ç ã.jpg": "é ç ã.jpg", "\x01\x02": "anexo.jpg",
                 " " * 119 + "ab": "ab", "x" * 119 + " y": "x" * 119}
        for nome, esperado in casos.items():
            info = ds.salvar_anexo(JPG, nome)
            self.assertEqual(info["nome"], esperado, repr(nome))
        # nenhum arquivo ganhou o nome enviado
        self.assertTrue(all(len(p.stem) == 17 and p.stem.startswith("a") for p in ds.anexos_dir().iterdir()))
        self.assertFalse((self.dir.parent / "etc").exists())

    def test_nunca_sobrescreve(self):
        primeiro = ds.salvar_anexo(JPG, "a.jpg")
        ocupado = primeiro["id"][1:]
        ids = iter([ocupado, ocupado, "fedcba9876543210"])
        with mock.patch.object(ds.secrets, "token_hex", lambda n: next(ids)):
            info = ds.salvar_anexo(PNG, "b.png")
        self.assertEqual(info["id"], "afedcba9876543210")
        self.assertEqual(ds.ler_anexo(primeiro["id"]), (JPG, "jpg"))

    def test_mesmo_id_com_outra_extensao_tambem_conta(self):
        ds.anexos_dir().mkdir()
        (ds.anexos_dir() / "a1111111111111111.pdf").write_bytes(PDF)
        ids = iter(["1111111111111111", "2222222222222222"])
        with mock.patch.object(ds.secrets, "token_hex", lambda n: next(ids)):
            info = ds.salvar_anexo(JPG, "x.jpg")
        self.assertEqual(info["id"], "a2222222222222222")

    def test_corrida_no_link_tenta_outro_id(self):
        ids = iter(["3333333333333333", "4444444444444444"])
        real = os.link
        chamadas = []

        def link(a, b):
            chamadas.append(b)
            if len(chamadas) == 1:
                raise FileExistsError
            return real(a, b)

        with mock.patch.object(ds.secrets, "token_hex", lambda n: next(ids)), mock.patch.object(ds.os, "link", link):
            info = ds.salvar_anexo(JPG, "x.jpg")
        self.assertEqual(info["id"], "a4444444444444444")
        self.assertEqual([p.name for p in ds.anexos_dir().iterdir()], ["a4444444444444444.jpg"])   # sem .tmp

    def test_sem_link_usa_rename(self):
        with mock.patch.object(ds.os, "link", side_effect=OSError("FAT")):
            info = ds.salvar_anexo(PDF, "x.pdf")
        self.assertEqual(ds.ler_anexo(info["id"]), (PDF, "pdf"))
        self.assertEqual(len(list(ds.anexos_dir().iterdir())), 1)

    def test_falha_de_disco_nao_deixa_tmp(self):
        with mock.patch.object(ds.os, "link", side_effect=OSError("FAT")), \
                mock.patch.object(ds.os, "rename", side_effect=PermissionError("negado")):
            with self.assertRaises(PermissionError):
                ds.salvar_anexo(PDF, "x.pdf")
        self.assertEqual(list(ds.anexos_dir().iterdir()), [])

    def test_id_invalido_e_traversal(self):
        info = ds.salvar_anexo(JPG, "x.jpg")
        (self.dir / "segredo.jpg").write_bytes(JPG)
        ruins = ["", "a", "a0123", "A0123456789abcdef", "a0123456789ABCDEF", "a0123456789abcdeg",
                 "a0123456789abcdef0", info["id"] + "\n", info["id"] + ".jpg", "../segredo", "..\\segredo",
                 "a0123456789abcd/.", "/etc/passwd", None, 5, ["a"], info["id"][:-1]]
        for aid in ruins:
            with self.assertRaises(ds.StoreError, msg=repr(aid)) as cm:
                ds.ler_anexo(aid)
            self.assertEqual(cm.exception.status, 404)
            self.assertEqual(str(cm.exception), "Anexo não encontrado.")
            with self.assertRaises(ds.StoreError):
                ds.apagar_anexo(aid)
        self.assertTrue((self.dir / "segredo.jpg").exists())
        self.assertEqual(ds.ler_anexo(info["id"])[1], "jpg")

    def test_inexistente(self):
        with self.assertRaises(ds.StoreError) as cm:
            ds.ler_anexo("a0123456789abcdef")
        self.assertEqual(cm.exception.status, 404)
        self.assertEqual(str(cm.exception), "Anexo não encontrado.")

    def test_arquivo_trocado_a_mao(self):
        ds.anexos_dir().mkdir()
        (ds.anexos_dir() / "a0123456789abcdef.png").write_bytes(JPG)   # extensão não bate com os bytes
        with self.assertRaises(ds.StoreError):
            ds.ler_anexo("a0123456789abcdef")
        (ds.anexos_dir() / "a0123456789abcdef.pdf").write_bytes(PDF)
        self.assertEqual(ds.ler_anexo("a0123456789abcdef"), (PDF, "pdf"))

    def test_apagar(self):
        a = ds.salvar_anexo(JPG, "a.jpg")
        b = ds.salvar_anexo(PNG, "b.png")
        ds.apagar_anexo(a["id"])
        with self.assertRaises(ds.StoreError):
            ds.ler_anexo(a["id"])
        self.assertEqual(ds.ler_anexo(b["id"]), (PNG, "png"))
        self.assertEqual(ds.uso_anexos()["bytes"], len(PNG))
        ds.apagar_anexo(a["id"])   # já apagado: não é erro
        ds.apagar_anexo("a0000000000000000")


class Horario(Base):
    """Horário de serviço no arquivo: a agenda vigente, as versões em uso e os campos novos da demanda."""

    def agenda(self, **kw):
        return {**ag.padrao(), "ativa": True, "v": 3, **kw}

    def test_agenda_e_versoes_sobrevivem_ao_ciclo(self):
        a = self.agenda(feriados=[{"data": "2026-12-25", "nome": "Natal", "setores": []}])
        self.grava({"v": 2, "agenda": a, "agendas": {"3": a, "2": {**a, "v": 2}}})
        doc = ds.load()
        self.assertEqual(doc["agenda"], a)
        self.assertEqual(sorted(doc["agendas"]), ["2", "3"])
        ds.commit(doc)
        self.assertEqual(self.disco()["agenda"], a)
        self.assertEqual(ds.load(cache=False)["agendas"]["3"], a)

    def test_agenda_ausente_ou_ilegivel_volta_desligada(self):
        for ruim in (None, "x", [], {"ativa": "sim"}, {**ag.padrao(), "padrao": {"dias": [9], "turnos": []}}):
            self.grava({"v": 2, "agenda": ruim})
            doc = ds.load(cache=False)
            self.assertEqual(doc["agenda"], ag.padrao(), ruim)
            self.assertEqual(doc["agendas"], {})

    def test_versoes_ilegiveis_ficam_de_fora(self):
        a = self.agenda()
        self.grava({"v": 2, "agenda": a, "agendas": {"1": a, "x": a, "2": {"ativa": 5}, "-3": a, " 5": a}})
        self.assertEqual(list(ds.load()["agendas"]), ["1"])
        self.grava({"v": 2, "agendas": ["x"]})
        self.assertEqual(ds.load(cache=False)["agendas"], {})

    def test_so_as_50_versoes_mais_novas(self):
        a = self.agenda()
        self.grava({"v": 2, "agenda": a, "agendas": {str(i): {**a, "v": i} for i in range(1, 61)}})
        versoes = sorted(ds.load()["agendas"], key=int)
        self.assertEqual((len(versoes), versoes[0], versoes[-1]), (50, "11", "60"))   # a 10 e as menores saem

    def test_campos_da_demanda(self):
        util = {"espera": 1, "execucao": 2, "pausado": 3, "total": 6}
        bom = dem(1001, agenda_v=2, prazo_em=1234, util={**util, "atraso": 5})
        ruins = [dem(1002, agenda_v="2", prazo_em=1.5, util={"espera": 1}), dem(1003, agenda_v=True, prazo_em=None, util="x"),
                 dem(1004, util={**util, "total": "6"}), dem(1005, util={**util, "espera": True})]
        self.grava({"v": 2, "demandas": [bom] + ruins})
        d = {x["id"]: x for x in ds.load()["demandas"]}
        self.assertEqual((d["SOL-1001"]["agenda_v"], d["SOL-1001"]["prazo_em"], d["SOL-1001"]["util"]),
                         (2, 1234, {**util, "atraso": 5}))
        for n in (1002, 1003, 1004, 1005):
            for k in ("agenda_v", "prazo_em", "util"):
                self.assertNotIn(k, d["SOL-%d" % n], (n, k))
        extra = dem(1006, util={**util, "lixo": 9, "atraso": "x"})
        self.grava({"v": 2, "demandas": [extra]})
        self.assertEqual(ds.load(cache=False)["demandas"][0]["util"], util)   # só as chaves conhecidas, atraso válido ou fora

    def test_empty_ja_traz_a_agenda_desligada(self):
        e = ds.empty()
        self.assertEqual((e["agenda"], e["agendas"]), (ag.padrao(), {}))
        self.assertIsNot(ds.empty()["agenda"], ds.empty()["agenda"])


if __name__ == "__main__":
    unittest.main()
