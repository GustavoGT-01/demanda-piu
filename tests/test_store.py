"""store.py: gravação segura (temporário + .bak) e leitura que recupera do .bak."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import store  # noqa: E402

NEGADO = PermissionError(5, "Acesso negado")


class Store(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="dem-store-"))
        self._env = mock.patch.dict(os.environ, {"DEMANDAS_DATA": str(self.d / "dados")})
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def test_data_dir(self):
        self.assertEqual(store.data_dir(), self.d / "dados")
        self.assertTrue((self.d / "dados").is_dir())   # criada na primeira chamada
        with mock.patch.dict(os.environ, {"DEMANDAS_DATA": ""}):
            self.assertEqual(store.data_dir(), store.ROOT / "data")

    def test_atomic_write_renomeia_sem_copiar(self):
        p = self.d / "x.json"
        store.atomic_write(p, '{"v": 1}')
        self.assertFalse(p.with_name("x.json.bak").exists())   # primeira gravação: nada a guardar
        with mock.patch("store.os.fsync", wraps=os.fsync) as fs:
            store.atomic_write(p, '{"v": 2}')
        self.assertEqual(fs.call_count, 1)   # só o temporário; o .bak é o arquivo antigo renomeado
        self.assertEqual(json.loads(p.read_text("utf-8")), {"v": 2})
        self.assertEqual(json.loads(p.with_name("x.json.bak").read_text("utf-8")), {"v": 1})
        self.assertFalse(list(self.d.glob("*.tmp")))

    def test_ler(self):
        p = self.d / "x.json"
        self.assertIsNone(store._read_safe(p))   # sem arquivo nenhum
        store.atomic_write(p, '{"v": 1}')
        self.assertEqual(store._read_safe(p), {"v": 1})

    def test_corrompido_recupera_do_bak(self):
        p = self.d / "x.json"
        store.atomic_write(p, '{"v": 1}')
        store.atomic_write(p, '{"v": 2}')
        p.write_text("{quebrado", encoding="utf-8")
        self.assertEqual(store._read_safe(p), {"v": 1})
        self.assertEqual(json.loads(p.read_text("utf-8")), {"v": 1})   # a cópia virou o principal
        self.assertEqual(len(list(self.d.glob("x.json.corrompido-*"))), 1)   # o ruim fica guardado ao lado
        self.assertEqual(store._read_safe(p), {"v": 1})

    def test_os_dois_corrompidos_levantam(self):
        p = self.d / "x.json"
        for name in ("x.json", "x.json.bak"):
            (self.d / name).write_text("{quebrado", encoding="utf-8")
        for _ in range(2):
            with self.assertRaises(ValueError):
                store._read_safe(p)
        self.assertTrue(p.exists())   # o arquivo ruim fica no lugar: nunca "vazio" em silêncio

    def test_replace_tenta_de_novo_no_permission_error(self):
        real, calls = os.replace, []

        def instavel(src, dst):
            calls.append(src)
            if len(calls) < 3:
                raise NEGADO
            real(src, dst)
        p = self.d / "x.json"
        with mock.patch("store.os.replace", instavel), mock.patch("store.time.sleep") as dorme:
            store._write_file(p, b"1")
        self.assertEqual(p.read_text("utf-8"), "1")
        self.assertEqual([c.args[0] for c in dorme.call_args_list], [0.05, 0.1])

    def test_queda_entre_os_dois_renomes(self):
        p = self.d / "x.json"
        store.atomic_write(p, '{"v": 1}')
        store.atomic_write(p, '{"v": 2}')
        real = os.replace

        def cai(src, dst):   # o 1º renome passa, o 2º (tmp -> principal) não
            if str(src).endswith(".tmp"):
                raise NEGADO
            real(src, dst)
        with mock.patch("store.os.replace", cai), mock.patch("store.time.sleep"):
            with self.assertRaises(PermissionError):
                store.atomic_write(p, '{"v": 3}')
        self.assertFalse(p.exists())
        self.assertFalse(list(self.d.glob("*.tmp")))
        self.assertEqual(store._read_safe(p), {"v": 2})   # vale o .bak...
        self.assertFalse(p.exists())                       # ...sem gravar (não pisa no .tmp de um escritor)
        self.assertFalse(list(self.d.glob("*.corrompido-*")))
        store.atomic_write(p, '{"v": 4}')                  # a próxima gravação recria o principal
        self.assertEqual(store._read_safe(p), {"v": 4})
        self.assertEqual(json.loads(p.with_name("x.json.bak").read_text("utf-8")), {"v": 2})

    def test_primeiro_renome_falha_principal_intacto(self):
        p = self.d / "x.json"
        store.atomic_write(p, '{"v": 1}')
        with mock.patch("store.os.replace", side_effect=NEGADO), mock.patch("store.time.sleep"):
            with self.assertRaises(PermissionError):
                store.atomic_write(p, '{"v": 2}')
        self.assertEqual(json.loads(p.read_text("utf-8")), {"v": 1})   # dado nunca apagado pela limpeza
        self.assertFalse(list(self.d.glob("*.tmp")))

    def test_replace_de_arquivo_de_dados_nao_apaga_origem(self):
        p = self.d / "x.json"
        p.write_text("1", encoding="utf-8")
        with mock.patch("store.os.replace", side_effect=NEGADO), mock.patch("store.time.sleep"):
            with self.assertRaises(PermissionError):
                store._replace(p, self.d / "y.json")
        self.assertTrue(p.exists())

    def test_write_file_falhou_apaga_o_tmp(self):
        p = self.d / "x.json"
        with mock.patch("store.os.replace", side_effect=NEGADO), mock.patch("store.time.sleep"):
            with self.assertRaises(PermissionError):
                store._write_file(p, b"1")
        self.assertFalse(list(self.d.glob("*.tmp")))

    def test_corrompido_some_durante_a_leitura(self):
        p = self.d / "x.json"
        store.atomic_write(p, '{"v": 1}')
        store.atomic_write(p, '{"v": 2}')
        p.write_text("{quebrado", encoding="utf-8")
        with mock.patch.object(Path, "rename", side_effect=FileNotFoundError):
            self.assertEqual(store._read_safe(p), {"v": 1})

    def test_remove_ignora_arquivo_que_nao_existe(self):
        store._remove(self.d / "nada.json")   # não levanta


if __name__ == "__main__":
    unittest.main()
