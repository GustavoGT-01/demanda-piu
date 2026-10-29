"""demandas_avisos: padrão da central, diferenças por pessoa, "Voltar ao padrão", validação e arquivo ilegível.
Dados num diretório temporário (DEMANDAS_DATA).
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parents[1] / "demandas"
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import demandas_avisos as av  # noqa: E402

PADRAO = {"eventos": {e: True for e in av.EVENTOS}, "som": "curto", "vibrar": True, "agrupar_min": 10,
          "silencio": {"ligado": False, "ini": "22:00", "fim": "06:00"}, "urgente_fura": True}


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="dem-av-"))
        self._env = mock.patch.dict(os.environ, {"DEMANDAS_DATA": str(self.dir)})
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def disco(self):
        return json.loads((self.dir / "avisos.json").read_text(encoding="utf-8"))

    def erro(self, fn, *a):
        with self.assertRaises(av.AvisoErro) as c:
            fn(*a)
        return c.exception.status, str(c.exception)


class Padrao(Base):
    def test_sem_arquivo_e_o_padrao_da_tabela(self):
        self.assertEqual(av.PADRAO, PADRAO, "silêncio desligado por padrão (decisão do dono, 28/10/2026)")
        self.assertEqual(av.padrao(), PADRAO)
        self.assertEqual(av.de("p1"), dict(PADRAO, proprio=False))
        self.assertFalse((self.dir / "avisos.json").exists(), "ler não grava")

    def test_arquivo_ilegivel_ou_estranho_vira_padrao(self):
        for texto in ("{x", "[1, 2]", '{"padrao": 5, "pessoas": []}', '{"pessoas": {"p1": 7}}',
                      '{"padrao": {"som": "buzina", "agrupar_min": 3, "silencio": "sempre", "eventos": [1]}}'):
            (self.dir / "avisos.json").write_text(texto, encoding="utf-8")
            self.assertEqual(av.padrao(), PADRAO, texto)
            self.assertEqual(av.de("p1"), dict(PADRAO, proprio=False), texto)

    def test_salvar_padrao_so_o_que_veio(self):
        p = av.salvar_padrao({"som": "sino", "agrupar_min": 0, "silencio": {"ligado": True}, "eventos": {"fila": False}})
        esperado = json.loads(json.dumps(PADRAO))
        esperado.update(som="sino", agrupar_min=0)
        esperado["silencio"]["ligado"] = True
        esperado["eventos"]["fila"] = False
        self.assertEqual(p, esperado)
        self.assertEqual(self.disco(), {"v": 1, "padrao": esperado})
        p = av.salvar_padrao({"vibrar": False, "urgente_fura": False, "agrupar_min": 5})
        self.assertEqual((p["som"], p["vibrar"], p["urgente_fura"], p["agrupar_min"]), ("sino", False, False, 5))
        self.assertEqual(av.padrao(), p)

    def test_padrao_invalido_recusa_e_nao_grava(self):
        casos = [([], "Pedido inválido."), ({"som": "buzina"}, "Som inválido."), ({"som": 1}, "Som inválido."),
                 ({"agrupar_min": 3}, "Agrupamento inválido."), ({"agrupar_min": True}, "Agrupamento inválido."),
                 ({"agrupar_min": "10"}, "Agrupamento inválido."),
                 ({"vibrar": 1}, "Opção de vibração inválida."), ({"urgente_fura": None}, "Opção do urgente inválida."),
                 ({"eventos": []}, "Eventos inválidos."), ({"eventos": {"new": 1}}, "Eventos inválidos."),
                 ({"silencio": "22-06"}, "Horário de silêncio inválido: use HH:MM."),
                 ({"silencio": {"ligado": "sim"}}, "Horário de silêncio inválido: use HH:MM."),
                 ({"silencio": {"ini": "24:00"}}, "Horário de silêncio inválido: use HH:MM."),
                 ({"silencio": {"fim": "6:00"}}, "Horário de silêncio inválido: use HH:MM."),
                 ({"silencio": {"ini": "07:60"}}, "Horário de silêncio inválido: use HH:MM."),
                 ({"silencio": {"ini": 600}}, "Horário de silêncio inválido: use HH:MM."),
                 ({"silencio": {"ini": "22:00\n"}}, "Horário de silêncio inválido: use HH:MM.")]
        for body, msg in casos:
            self.assertEqual(self.erro(av.salvar_padrao, body), (400, msg), body)
        self.assertFalse((self.dir / "avisos.json").exists())

    def test_horas_validas_nos_limites(self):
        for h in ("00:00", "23:59", "19:05", "09:30"):
            self.assertEqual(av.salvar_padrao({"silencio": {"ini": h, "fim": h}})["silencio"], {"ligado": False, "ini": h, "fim": h})
        self.assertEqual(av.salvar_padrao({"silencio": {"fim": "07:15"}})["silencio"]["fim"], "07:15")

    def test_nomes_que_a_tela_usa(self):
        """Contrato com o demandas.js (tipos de nota, valores dos selects)."""
        self.assertEqual(av.EVENTOS, ("new", "fila", "accepted", "pause", "done", "canc", "nudge", "late", "comment"))
        for som in ("curto", "sino", "desligado"):
            self.assertEqual(av.salvar_padrao({"som": som})["som"], som)
        for m in (0, 5, 10):
            self.assertEqual(av.salvar_padrao({"agrupar_min": m})["agrupar_min"], m)

    def test_evento_desconhecido_e_ignorado(self):
        self.assertEqual(av.salvar_padrao({"eventos": {"xyz": False, "late": False}})["eventos"],
                         dict(PADRAO["eventos"], late=False))


class DaPessoa(Base):
    def test_so_as_diferencas_ficam_gravadas(self):
        out = av.salvar_de("p1", {"eventos": {"fila": False, "new": True}, "silencio": {"ligado": True, "ini": "22:00"},
                                  "urgente_fura": True, "som": "desligado", "vibrar": False, "agrupar_min": 0})
        self.assertEqual(self.disco()["pessoas"], {"p1": {"eventos": {"fila": False}, "silencio": {"ligado": True}}},
                         "igual ao padrão não grava; som, vibração e agrupamento são do aparelho e da central")
        self.assertEqual((out["eventos"]["fila"], out["silencio"], out["som"], out["proprio"]),
                         (False, {"ligado": True, "ini": "22:00", "fim": "06:00"}, "curto", True))
        self.assertEqual(av.de("p2"), dict(PADRAO, proprio=False), "uma pessoa não mexe na outra")

    def test_salvar_por_partes_mantem_o_resto(self):
        av.salvar_de("p1", {"eventos": {"done": False}})
        out = av.salvar_de("p1", {"urgente_fura": False})
        self.assertEqual((out["eventos"]["done"], out["urgente_fura"]), (False, False))
        self.assertEqual(self.disco()["pessoas"]["p1"], {"eventos": {"done": False}, "urgente_fura": False})

    def test_padrao_da_central_muda_quem_nao_mexeu(self):
        av.salvar_de("p1", {"eventos": {"late": False}})
        av.salvar_padrao({"eventos": {"comment": False}, "silencio": {"ligado": True, "ini": "23:00"}})
        p1, p2 = av.de("p1"), av.de("p2")
        self.assertEqual((p1["eventos"]["late"], p1["eventos"]["comment"], p1["silencio"]["ini"]), (False, False, "23:00"))
        self.assertEqual((p2["eventos"]["late"], p2["eventos"]["comment"], p2["proprio"]), (True, False, False))

    def test_voltar_igual_ao_padrao_apaga_a_pessoa(self):
        av.salvar_de("p1", {"eventos": {"late": False}})
        out = av.salvar_de("p1", {"eventos": {"late": True}})
        self.assertFalse(out["proprio"])
        self.assertEqual(self.disco()["pessoas"], {})

    def test_voltar_ao_padrao(self):
        av.salvar_de("p1", {"eventos": {"late": False}, "urgente_fura": False})
        av.salvar_de("adm", {"eventos": {"pause": False}})
        out = av.salvar_de("p1", {"padrao": True, "eventos": {"done": False}})
        self.assertEqual(out, dict(PADRAO, proprio=False), "padrão: true ignora o resto")
        self.assertEqual(self.disco()["pessoas"], {"adm": {"eventos": {"pause": False}}})

    def test_pessoa_com_diferenca_estranha_no_disco(self):
        (self.dir / "avisos.json").write_text(json.dumps({"pessoas": {"p1": {"eventos": {"late": "x", "done": False},
                                                                             "silencio": {"ini": "99:99"}}}}), encoding="utf-8")
        out = av.de("p1")
        self.assertEqual((out["eventos"]["late"], out["eventos"]["done"], out["silencio"]["ini"]), (True, False, "22:00"))
        out = av.salvar_de("p1", {"urgente_fura": False})
        self.assertEqual(self.disco()["pessoas"]["p1"], {"eventos": {"done": False}, "urgente_fura": False}, "o lixo sai ao gravar")

    def test_invalidos(self):
        self.assertEqual(self.erro(av.de, "p 1"), (400, "Pessoa inválida."))
        self.assertEqual(self.erro(av.de, None), (400, "Pessoa inválida."))
        self.assertEqual(self.erro(av.de, "x" * 41), (400, "Pessoa inválida."))
        self.assertEqual(self.erro(av.salvar_de, "p1", []), (400, "Pedido inválido."))
        self.assertEqual(self.erro(av.salvar_de, "p1", {"silencio": {"fim": "25:00"}}),
                         (400, "Horário de silêncio inválido: use HH:MM."))
        self.assertEqual(self.erro(av.salvar_de, "p1", {"eventos": {"late": "não"}}), (400, "Eventos inválidos."))
        self.assertEqual(av.de("x" * 40)["proprio"], False)
        self.assertEqual(av.de("adm")["proprio"], False)
        self.assertFalse((self.dir / "avisos.json").exists())

    def test_padrao_true_so_com_booleano(self):
        av.salvar_de("p1", {"eventos": {"late": False}})
        self.assertTrue(av.salvar_de("p1", {"padrao": 1})["proprio"])

    def test_padrao_da_central_preservado_ao_gravar_pessoa(self):
        av.salvar_padrao({"som": "sino"})
        av.salvar_de("p1", {"eventos": {"late": False}})
        self.assertEqual(self.disco()["padrao"]["som"], "sino")
        self.assertEqual(self.disco()["v"], 1)


if __name__ == "__main__":
    unittest.main()
