"""demandas_backup: configuração, estado e aviso, quando rodar, retenção, instantâneo, zip, verificação, cópia
completa e cópia com gravações acontecendo ao mesmo tempo.

Dados em <tmp>/data (DEMANDAS_DATA) por teste; a pasta padrão das cópias fica em <tmp>/backup. Relógio sempre injetado.
"""

import hashlib
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parents[1] / "demandas"
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import demandas_backup as bk  # noqa: E402
import demandas_store as ds  # noqa: E402

INICIO0 = dict(bk._INICIO)   # antes de qualquer teste mexer
JPG = b"\xff\xd8\xff\xe0" + b"j" * 40
PNG = b"\x89PNG\r\n\x1a\n" + b"p" * 40
H = 3600 * 1000


def ms(ano, mes, dia, h=0, m=0):
    """Instante local em ms (o horário do backup é o do relógio do PC)."""
    return int(time.mktime((ano, mes, dia, h, m, 0, 0, 0, -1)) * 1000)


def nome(ano, mes, dia, h=3, m=0, tipo="auto"):
    return "central-demandas_%04d%02d%02d-%02d%02d_%s.zip" % (ano, mes, dia, h, m, tipo)


def dem(n, status="done", anexos=()):
    return {"id": "SOL-%d" % n, "titulo": "D%d" % n, "status": status, "de": {"s": "PCP", "p": None},
            "para": {"s": "CNC", "p": None}, "criado": n, "fim": n if status in ds.FIM else None,
            "anexos": [{"id": a, "nome": "x", "tipo": "jpg", "bytes": 1} for a in anexos]}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def zip_feito(caminho, membros, manifesto=None, mexe=None):
    """Zip à mão: membros {nome: bytes}; o manifesto confere com eles, salvo se vier pronto ou mexe(manifesto) mudar."""
    man = manifesto if manifesto is not None else {
        "programa": "Central de demandas", "formato_backup": 1, "v_dados": 1, "criado": 0, "tipo": "manual", "rev": 1,
        "arquivos": {n: {"bytes": len(b), "sha256": sha(b)} for n, b in membros.items()}, "faltando": []}
    if mexe:
        mexe(man)
    with zipfile.ZipFile(caminho, "w") as z:
        for n, b in membros.items():
            z.writestr(n, b)
        z.writestr("manifesto.json", man if isinstance(man, bytes) else json.dumps(man))
    return caminho


class Base(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="dem-bk-"))
        self.dir = self.root / "data"
        self.dir.mkdir()
        self._env = mock.patch.dict(os.environ, {"DEMANDAS_DATA": str(self.dir)})
        self._env.start()
        ds._CACHE.update(key=None, texto=None)
        ds._ARQ.update(key=None, demandas=[])
        bk._INICIO["t"] = None

    def tearDown(self):
        self._env.stop()
        self.assertFalse(bk._BACKUP.locked(), "teste deixou _BACKUP preso")

    def grava(self, raw, nome="demandas.json"):
        (self.dir / nome).write_text(raw if isinstance(raw, str) else json.dumps(raw), encoding="utf-8")

    def anexo(self, aid, dados=JPG, ext="jpg"):
        ds.anexos_dir().mkdir(exist_ok=True)
        (ds.anexos_dir() / ("%s.%s" % (aid, ext))).write_bytes(dados)

    def pasta(self):
        return self.root / "backup"

    def zips(self):
        return sorted(p.name for p in self.pasta().iterdir()) if self.pasta().is_dir() else []

    def erro(self, status, fn, *a, **kw):
        with self.assertRaises(ds.StoreError) as cm:
            fn(*a, **kw)
        self.assertEqual(cm.exception.status, status)
        return str(cm.exception)


A1, A2, A3 = "a" + "1" * 16, "a" + "2" * 16, "a" + "3" * 16


# ---------- configuração ----------

class Constantes(unittest.TestCase):
    def test_limites_e_inicio(self):
        self.assertEqual(bk.JSON_MAX, 200 * 1024 * 1024)
        self.assertEqual(bk.MANIFESTO_MAX, 16 * 1024 * 1024)
        self.assertEqual(INICIO0, {"t": None})


class Config(Base):
    def test_mensagens(self):
        casos = [({"on": 1}, "Ligado/desligado inválido."), ({"ao_ligar": 1}, "Opção \"ao ligar\" inválida."),
                 ({"hora": "x"}, "Horário inválido: use HH:MM, de 00:00 a 23:59."),
                 ({"local": "x"}, "Pasta inválida: use uma pasta que exista, fora da pasta data e que não seja a raiz "
                                  "do disco."),
                 ({"ret": 1}, "Retenção inválida."), ({"ret": {"diarias": 0}}, "Retenção inválida: de 1 a 60 cópias."),
                 ({"limite_mb": 0}, "Limite de espaço inválido: de 50 MB a 1000000 MB.")]
        for body, msg in casos:
            self.assertEqual(self.erro(400, bk.salvar_config, body), msg)

    def test_caminho_de_260_caracteres(self):
        base = str(self.root) + "\\"
        self.assertIsNotNone(bk._pasta_ok(base + "x" * (260 - len(base))))
        self.assertIsNone(bk._pasta_ok(base + "x" * (261 - len(base))))

    def test_padrao_sem_arquivo(self):
        self.assertEqual(bk.config(), {"on": True, "hora": "03:00", "ao_ligar": True, "local": "",
                                       "ret": {"diarias": 7, "semanais": 4, "mensais": 12, "manuais": 5},
                                       "limite_mb": 5000})
        self.assertIsNot(bk.config()["ret"], bk.PADRAO["ret"])
        self.assertEqual(bk.pasta_local(bk.config()), self.root / "backup")
        self.assertEqual(bk.pasta_padrao(), self.root / "backup")

    def test_arquivo_ruim_ou_campos_ruins_ficam_no_padrao(self):
        self.grava("{ruim", "backup.json")
        self.assertEqual(bk.config(), bk._campos({}, bk.PADRAO, False))
        self.grava([1, 2], "backup.json")
        self.assertEqual(bk.config()["hora"], "03:00")
        self.grava({"on": "sim", "hora": "25:00", "ao_ligar": 1, "local": "relativo", "ret": {"diarias": 0, "mensais": 3},
                    "limite_mb": True}, "backup.json")
        cfg = bk.config()
        self.assertEqual((cfg["on"], cfg["hora"], cfg["ao_ligar"], cfg["local"], cfg["limite_mb"]),
                         (True, "03:00", True, "", 5000))
        self.assertEqual(cfg["ret"], {"diarias": 7, "semanais": 4, "mensais": 3, "manuais": 5})
        self.grava({"ret": "x"}, "backup.json")
        self.assertEqual(bk.config()["ret"], bk.PADRAO["ret"])

    def test_salvar_muda_so_o_enviado_e_grava(self):
        cfg = bk.salvar_config({"hora": "12:30", "ret": {"manuais": 2}})
        self.assertEqual((cfg["hora"], cfg["ret"]["manuais"], cfg["ret"]["diarias"], cfg["on"]), ("12:30", 2, 7, True))
        disco = json.loads((self.dir / "backup.json").read_text(encoding="utf-8"))
        self.assertEqual(disco["v"], 1)
        self.assertEqual(bk.config(), cfg)
        cfg = bk.salvar_config({"on": False, "ao_ligar": False, "limite_mb": 50})
        self.assertEqual((cfg["on"], cfg["ao_ligar"], cfg["limite_mb"], cfg["hora"]), (False, False, 50, "12:30"))
        self.assertEqual(bk.salvar_config({"limite_mb": 1000000, "ret": {"diarias": 60, "semanais": 1}})["limite_mb"],
                         1000000)
        self.assertEqual(bk.config()["ret"], {"diarias": 60, "semanais": 1, "mensais": 12, "manuais": 2})
        for h in ("00:00", "23:59", "09:05"):
            self.assertEqual(bk.salvar_config({"hora": h})["hora"], h)

    def test_salvar_recusa_invalidos_sem_gravar(self):
        bk.salvar_config({"hora": "12:00"})
        antes = (self.dir / "backup.json").read_bytes()
        ruins = [{"hora": h} for h in ("24:00", "7:5", "", "12:60", "12h00", " 12:00", 1200, None)]
        ruins += [{"ret": {"diarias": n}} for n in (0, 61, True, "7", 1.5, None)]
        ruins += [{"ret": []}, {"limite_mb": 49}, {"limite_mb": 1000001}, {"limite_mb": True}, {"limite_mb": "100"},
                  {"on": 1}, {"on": None}, {"ao_ligar": "sim"}]
        for b in ruins:
            with self.subTest(b=b):
                self.erro(400, bk.salvar_config, b)
        for b in ([], "x", None):
            self.assertEqual(self.erro(400, bk.salvar_config, b), "Pedido inválido.")
        self.assertEqual((self.dir / "backup.json").read_bytes(), antes)
        self.assertIn("HH:MM", self.erro(400, bk.salvar_config, {"hora": "24:00"}))
        self.assertIn("de 1 a 60", self.erro(400, bk.salvar_config, {"ret": {"mensais": 0}}))
        self.assertIn("de 50 MB a 1000000 MB", self.erro(400, bk.salvar_config, {"limite_mb": 1}))

    def test_pasta_escolhida(self):
        destino = self.root / "copias"
        cfg = bk.salvar_config({"local": str(destino)})
        self.assertEqual(cfg["local"], str(destino.resolve()))
        self.assertTrue(destino.is_dir())
        self.assertEqual(list(destino.iterdir()), [], "o arquivo de teste não fica")
        self.assertEqual(bk.pasta_local(bk.config()), destino.resolve())
        self.assertEqual(bk.salvar_config({"local": ""})["local"], "")
        self.assertEqual(bk.salvar_config({"local": "  %s  " % destino})["local"], str(destino.resolve()))

    def test_pasta_recusada(self):
        raiz = Path(self.root.anchor)
        ruins = ["relativo/pasta", str(self.dir), str(self.dir / "sub"), str(raiz), str(self.root / "nao" / "existe"),
                 "C:" + "\\x" * 200, "   ", 5, None, ["x"]]
        for v in ruins:
            with self.subTest(v=v):
                self.assertIn("Pasta inválida", self.erro(400, bk.salvar_config, {"local": v}))
        self.assertIsNone(bk._pasta_ok(str(self.dir)))
        with mock.patch.object(Path, "resolve", side_effect=OSError("x")):
            self.assertIsNone(bk._pasta_ok(str(self.root / "copias")))

    def test_pasta_sem_permissao_de_gravar(self):
        with mock.patch.object(Path, "write_bytes", side_effect=PermissionError("x")):
            self.assertEqual(self.erro(400, bk.salvar_config, {"local": str(self.root / "copias")}),
                             "Não foi possível gravar na pasta escolhida.")
        self.assertFalse((self.dir / "backup.json").exists())


# ---------- estado e aviso ----------

class Resumo(Base):
    AGORA = ms(2026, 10, 28, 12)

    def est(self, ok_h=None, falha_h=None, erro="Sem espaço no disco para o backup"):
        return {"ultimo_ok": None if ok_h is None else {"t": self.AGORA - ok_h * H},
                "ultima_falha": None if falha_h is None else {"t": self.AGORA - falha_h * H, "erro": erro},
                "falhas_seguidas": 0}

    def test_estado_padrao_e_arquivo_ruim(self):
        vazio = {"v": 1, "ultimo_ok": None, "ultima_falha": None, "falhas_seguidas": 0, "restaurado": None}
        self.assertEqual(bk.estado(), vazio)
        self.grava("{x", "backup-estado.json")
        self.assertEqual(bk.estado(), vazio)
        self.grava({"ultimo_ok": {"t": "1"}, "ultima_falha": [], "falhas_seguidas": -1}, "backup-estado.json")
        self.assertEqual(bk.estado(), vazio)
        self.grava({"ultimo_ok": {"t": 5}, "ultima_falha": {"t": 6}, "falhas_seguidas": 2}, "backup-estado.json")
        self.assertEqual(bk.estado(), {"v": 1, "ultimo_ok": {"t": 5}, "ultima_falha": {"t": 6}, "falhas_seguidas": 2,
                                       "restaurado": None})
        for n, esperado in ((10 ** 9, 10 ** 9), (10 ** 9 + 1, 0), (91, 91)):
            self.grava({"falhas_seguidas": n}, "backup-estado.json")
            self.assertEqual(bk.estado()["falhas_seguidas"], esperado)

    def test_falha_no_mesmo_instante_da_copia_boa_nao_conta(self):
        est = self.est(ok_h=30, falha_h=30)
        self.assertEqual(bk.resumo(self.AGORA, bk.PADRAO, est)["texto"], "Último backup há 30 h.")

    def test_desligado_e_aviso(self):
        cfg = {**bk.PADRAO, "on": False}
        self.assertEqual(bk.resumo(self.AGORA, cfg, self.est(ok_h=1)),
                         {"alerta": "aviso", "texto": "Backup automático desligado.", "ultimo_ok_t": self.AGORA - H,
                          "restaurado": None})

    def test_em_dia_sem_aviso_ate_26h(self):
        for h in (0, 25, 26):
            self.assertEqual(bk.resumo(self.AGORA, bk.PADRAO, self.est(ok_h=h, falha_h=0.5)),
                             {"alerta": None, "texto": "", "ultimo_ok_t": self.AGORA - h * H, "restaurado": None})

    def test_velho_e_grave(self):
        r = bk.resumo(self.AGORA, bk.PADRAO, self.est(ok_h=27))
        self.assertEqual(r, {"alerta": "grave", "texto": "Último backup há 27 h.", "ultimo_ok_t": self.AGORA - 27 * H,
                             "restaurado": None})
        self.assertEqual(bk.resumo(self.AGORA, bk.PADRAO, self.est(ok_h=47))["texto"], "Último backup há 47 h.")
        self.assertEqual(bk.resumo(self.AGORA, bk.PADRAO, self.est(ok_h=48))["texto"], "Último backup há 2 dias.")
        self.assertEqual(bk.resumo(self.AGORA, bk.PADRAO, self.est(ok_h=80, falha_h=1))["texto"],
                         "Último backup há 3 dias: Sem espaço no disco para o backup")
        # falha mais velha que a última cópia boa não é o motivo
        self.assertEqual(bk.resumo(self.AGORA, bk.PADRAO, self.est(ok_h=30, falha_h=40))["texto"],
                         "Último backup há 30 h.")
        self.assertEqual(bk.resumo(self.AGORA, bk.PADRAO, self.est(ok_h=30, falha_h=1, erro=""))["texto"],
                         "Último backup há 30 h.")

    def test_nunca_feito(self):
        self.assertEqual(bk.resumo(self.AGORA, bk.PADRAO, self.est()),
                         {"alerta": "grave", "texto": "Nenhum backup feito ainda.", "ultimo_ok_t": None, "restaurado": None})
        self.assertEqual(bk.resumo(self.AGORA, bk.PADRAO, self.est(falha_h=1))["texto"],
                         "Nenhum backup feito ainda: Sem espaço no disco para o backup")

    def test_le_do_disco_sem_argumentos(self):
        self.grava({"ultimo_ok": {"t": self.AGORA - H}}, "backup-estado.json")
        self.assertIsNone(bk.resumo(self.AGORA)["alerta"])
        bk.salvar_config({"on": False})
        self.assertEqual(bk.resumo(self.AGORA)["alerta"], "aviso")


# ---------- quando rodar ----------

class DeveRodar(Base):
    def roda(self, agora, ok=None, falha=None, inicio=None, **cfg):
        est = {"ultimo_ok": None if ok is None else {"t": ok}, "ultima_falha": None if falha is None else {"t": falha},
               "falhas_seguidas": 0}
        return bk.deve_rodar(agora, {**bk.PADRAO, **cfg}, est, inicio if inicio is not None else agora - 10 * H)

    def test_horario(self):
        ontem = ms(2026, 10, 27, 3)
        self.assertIsNone(self.roda(ms(2026, 10, 28, 2, 59), ok=ontem))
        self.assertEqual(self.roda(ms(2026, 10, 28, 3, 0), ok=ontem), "auto")
        self.assertEqual(self.roda(ms(2026, 10, 28, 3, 1), ok=ontem), "auto")
        self.assertIsNone(self.roda(ms(2026, 10, 28, 3, 1), ok=ms(2026, 10, 28, 3, 0)), "já rodou hoje")
        self.assertIsNone(self.roda(ms(2026, 10, 28, 23, 59), ok=ms(2026, 10, 28, 3, 0)))
        self.assertEqual(self.roda(ms(2026, 10, 28, 3, 1), ok=ms(2026, 10, 28, 2, 59)), "auto",
                         "cópia manual antes da hora não conta como a de hoje")
        self.assertEqual(self.roda(ms(2026, 10, 28, 12, 0), ok=ontem, hora="12:00"), "auto")
        self.assertIsNone(self.roda(ms(2026, 10, 28, 11, 59), ok=ms(2026, 10, 27, 12, 0), hora="12:00"))

    def test_pc_desligado_na_hora_faz_ao_voltar(self):
        agora = ms(2026, 10, 28, 8)
        self.assertEqual(self.roda(agora, ok=ms(2026, 10, 27, 3), inicio=agora - 3 * 60000), "auto")

    def test_espera_2_minutos_depois_de_ligar(self):
        agora = ms(2026, 10, 28, 8)
        self.assertIsNone(self.roda(agora, ok=ms(2026, 10, 25, 3), inicio=agora - 119999))
        self.assertEqual(self.roda(agora, ok=ms(2026, 10, 25, 3), inicio=agora - 120000), "auto")

    def ligou(self, inicio, ok, **cfg):
        """Decisão 2 minutos depois de ligar o programa em inicio."""
        return self.roda(inicio + 2 * 60000, ok=ok, inicio=inicio, **cfg)

    def test_ao_ligar_19h_e_21h(self):
        ok = ms(2026, 10, 28, 3)
        self.assertIsNone(self.ligou(ms(2026, 10, 28, 22), ok), "19 h: espera o horário")
        self.assertIsNone(self.ligou(ok + 20 * H, ok), "20 h exatas ainda não")
        self.assertEqual(self.ligou(ok + 20 * H + 1, ok), "inicio")
        self.assertEqual(self.ligou(ms(2026, 10, 29, 0, 30), ok), "inicio", "21,5 h, antes das 03:00")
        self.assertIsNone(self.ligou(ms(2026, 10, 29, 0, 30), ok, ao_ligar=False))

    def test_pc_ligado_direto_nao_ganha_copia_de_inicio(self):
        ok = ms(2026, 10, 28, 3)
        for agora in (ms(2026, 10, 28, 23, 30), ms(2026, 10, 29, 2, 59)):
            self.assertIsNone(self.roda(agora, ok=ok, inicio=ms(2026, 10, 20)))
        self.assertIsNone(self.roda(ms(2026, 10, 29, 0, 30), ok=ms(2026, 10, 29, 0, 2),
                                    inicio=ms(2026, 10, 29, 0)), "a de início já foi feita")

    def test_nunca_feito(self):
        self.assertEqual(self.roda(ms(2026, 10, 28, 1)), "inicio")
        self.assertIsNone(self.roda(ms(2026, 10, 28, 1), ao_ligar=False))
        self.assertEqual(self.roda(ms(2026, 10, 28, 4), ao_ligar=False), "auto")

    def test_desligado(self):
        self.assertIsNone(self.roda(ms(2026, 10, 28, 4), on=False))
        self.assertIsNone(self.roda(ms(2026, 10, 28, 4), ok=ms(2026, 10, 20), on=False))

    def test_espera_30_min_depois_de_falha(self):
        agora, ontem = ms(2026, 10, 28, 4), ms(2026, 10, 27, 3)
        self.assertIsNone(self.roda(agora, ok=ontem, falha=agora - 10 * 60000))
        self.assertIsNone(self.roda(agora, ok=ontem, falha=agora - 30 * 60000 + 1))
        self.assertEqual(self.roda(agora, ok=ontem, falha=agora - 30 * 60000), "auto")
        self.assertIsNone(self.roda(agora, falha=agora - 60000), "falha sem nenhuma cópia boa também espera")
        self.assertEqual(self.roda(agora, ok=agora - 25 * H, falha=agora - 25 * H), "auto", "mesmo instante: vale a boa")
        cedo = ms(2026, 10, 28, 2, 55)
        self.assertEqual(self.roda(ms(2026, 10, 28, 3, 5), ok=cedo, falha=cedo), "auto",
                         "falha no mesmo instante da cópia boa não segura a das 03:00")
        # falha mais velha que a cópia boa não segura nada
        self.assertEqual(self.roda(ms(2026, 10, 28, 3), ok=ms(2026, 10, 27, 3), falha=ms(2026, 10, 27, 2, 59)), "auto")


# ---------- retenção ----------

class Reter(Base):
    RET = {"diarias": 7, "semanais": 4, "mensais": 12, "manuais": 5}
    SEM_LIMITE = 10 ** 15

    def apaga(self, nomes, ret=None, limite=None, tam=10):
        return bk.reter([(n, tam) for n in nomes], {**self.RET, **(ret or {})}, self.SEM_LIMITE if limite is None else limite)

    def test_vazio_um_e_fora_do_padrao(self):
        self.assertEqual(self.apaga([]), [])
        self.assertEqual(self.apaga([nome(2026, 1, 1)]), [])
        estranhos = ["central-demandas_20260101-0300_auto.zip.part", "foto.zip", "central-demandas_2026-0101_auto.zip",
                     "central-demandas_20260101-0300_outro.zip", "CENTRAL-DEMANDAS_20260101-0300_auto.zip"]
        self.assertEqual(self.apaga(estranhos + [nome(2026, 1, 1)], ret={"diarias": 1, "semanais": 1, "mensais": 1}), [])

    def test_gfs_feito_a_mao_com_semana_iso_na_virada_do_ano(self):
        # 2026-01-12 é segunda (semana ISO 3); 2025-12-31 é da semana ISO 1 de 2026
        dias = [(2026, 1, 13), (2026, 1, 12), (2026, 1, 10), (2026, 1, 9), (2026, 1, 5), (2025, 12, 31)]
        nomes = [nome(*d) for d in dias]
        self.assertEqual(sorted(self.apaga(nomes, ret={"diarias": 2, "semanais": 2, "mensais": 2})),
                         sorted([nome(2026, 1, 9), nome(2026, 1, 5)]))
        self.assertEqual(sorted(self.apaga(nomes, ret={"diarias": 2, "semanais": 3, "mensais": 1})),
                         sorted([nome(2026, 1, 9), nome(2026, 1, 5)]))
        self.assertEqual(sorted(self.apaga(nomes, ret={"diarias": 1, "semanais": 1, "mensais": 1})),
                         sorted(nomes[1:]))
        self.assertEqual(sorted(self.apaga(nomes, ret={"diarias": 6, "semanais": 1, "mensais": 1})), [])

    def test_virada_de_mes(self):
        nomes = [nome(2026, 3, 1), nome(2026, 2, 28), nome(2026, 2, 27), nome(2026, 1, 31)]
        self.assertEqual(sorted(self.apaga(nomes, ret={"diarias": 1, "semanais": 1, "mensais": 3})), [nome(2026, 2, 27)])

    def test_duas_no_mesmo_dia_fica_a_mais_nova(self):
        nomes = [nome(2026, 1, 13, 3, 0), nome(2026, 1, 13, 15, 0, "inicio"), nome(2026, 1, 12)]
        self.assertEqual(self.apaga(nomes, ret={"diarias": 2, "semanais": 1, "mensais": 1}), [nome(2026, 1, 13, 3, 0)])

    def test_manuais_e_antes_restaurar_contadas_a_parte(self):
        manuais = [nome(2026, 1, d, 10, 0, "manual") for d in range(1, 8)]
        antes = [nome(2026, 1, d, 11, 0, "antes-restaurar") for d in range(1, 4)]
        auto = [nome(2025, 6, 1)]
        apaga = self.apaga(manuais + antes + auto, ret={"diarias": 1, "semanais": 1, "mensais": 1})
        self.assertEqual(sorted(apaga), sorted(manuais[:2]))
        self.assertEqual(sorted(self.apaga(antes + manuais, ret={"manuais": 1})),
                         sorted(antes[:2] + manuais[:6]))

    def test_manual_nao_ocupa_a_vaga_da_diaria(self):
        nomes = [nome(2026, 1, 13, 20, 0, "manual"), nome(2026, 1, 13), nome(2026, 1, 12)]
        self.assertEqual(self.apaga(nomes, ret={"diarias": 1, "semanais": 1, "mensais": 1}), [nome(2026, 1, 12)])

    def test_400_copias_diarias(self):
        t0 = ms(2025, 9, 1, 3)
        nomes = [time.strftime("central-demandas_%Y%m%d-%H%M_auto.zip", time.localtime((t0 + i * 24 * H) / 1000))
                 for i in range(400)]
        apaga = set(self.apaga(nomes))
        fica = [n for n in nomes if n not in apaga]
        self.assertEqual(set(nomes), apaga | set(fica))
        self.assertLessEqual(len(fica), 23)
        self.assertGreaterEqual(len(fica), 12)
        self.assertEqual(fica[-7:], nomes[-7:], "os 7 dias mais novos")
        meses = {}
        for n in nomes:
            meses[n[17:23]] = n   # o último de cada mês (nomes em ordem)
        for mes in sorted(meses)[-12:]:
            self.assertIn(meses[mes], fica)
        self.assertEqual(len([m for m in meses if meses[m] in fica]), 12)

    def test_limite_de_espaco(self):
        nomes = [nome(2026, 1, d) for d in (10, 11, 12, 13)]
        self.assertEqual(sorted(self.apaga(nomes, limite=25)), sorted(nomes[:2]))
        self.assertEqual(sorted(self.apaga(nomes, limite=40)), [])
        self.assertEqual(sorted(self.apaga(nomes, limite=39)), [nomes[0]])
        self.assertEqual(sorted(self.apaga(nomes, limite=0)), sorted(nomes[:3]), "a mais nova nunca sai")
        self.assertEqual(sorted(self.apaga(nomes + [nome(2026, 1, 14, 9, 0, "manual")], limite=0)), sorted(nomes))

    def test_a_mais_nova_de_todas_pela_data_mesmo_com_tipos_misturados(self):
        auto, manual = nome(2026, 1, 14), nome(2026, 1, 13, 9, 0, "manual")
        self.assertEqual(self.apaga([manual, auto], limite=0), [manual])
        # mesmo minuto: desempate pelo nome, não pelo tamanho
        a, m = nome(2026, 1, 14, 3, 0, "auto"), nome(2026, 1, 14, 3, 0, "manual")
        self.assertEqual(bk.reter([(a, 99), (m, 1)], self.RET, 0), [a])

    def test_tamanhos_diferentes(self):
        itens = [(nome(2026, 1, 10), 100), (nome(2026, 1, 11), 1), (nome(2026, 1, 12), 1)]
        self.assertEqual(bk.reter(itens, self.RET, 50), [nome(2026, 1, 10)])

    def test_listar(self):
        p = self.root / "lista"
        self.assertEqual(bk.listar(p), [])
        p.mkdir()
        (p / nome(2026, 1, 2)).write_bytes(b"12345")
        (p / nome(2026, 1, 1)).write_bytes(b"1")
        (p / "outro.txt").write_bytes(b"x")
        (p / (nome(2026, 1, 3) + ".part")).write_bytes(b"x")
        (p / nome(2026, 1, 4)).mkdir()
        self.assertEqual(bk.listar(p), [(nome(2026, 1, 1), 1), (nome(2026, 1, 2), 5)])
        sumiu = mock.Mock()
        sumiu.name = nome(2026, 1, 5)
        sumiu.is_file.side_effect = FileNotFoundError("sumiu")
        with mock.patch.object(bk.os, "scandir", return_value=[sumiu]):
            self.assertEqual(bk.listar(p), [])


# ---------- instantâneo ----------

class Instantaneo(Base):
    def test_sem_dados(self):
        inst = bk.instantaneo()
        self.assertEqual(json.loads(inst["jsons"]["demandas.json"]), ds.empty())
        self.assertNotIn("demandas-arquivo.json", inst["jsons"])
        self.assertEqual((inst["anexos"], inst["rev"], inst["v"]), ([], 0, ds.V))
        self.assertEqual(ds.V, 2)
        self.assertEqual(inst["contagem"], {"demandas": 0, "arquivo": 0, "pessoas": 0, "setores": 0})

    def test_bytes_iguais_ao_disco_e_anexos_citados(self):
        doc = {"v": 1, "rev": 9, "pessoas": [{"id": "p1"}], "setores": [{"id": "PCP"}, {"id": "CNC"}],
               "demandas": [dem(1, "new", [A1, A2]), dem(2, "new", [A1]), "lixo",
                            {**dem(3), "anexos": [{"id": "../x"}, "y", {"id": 5}]}, {**dem(4), "anexos": "x"}]}
        texto = json.dumps(doc, indent=1) + "\n"
        self.grava(texto)
        self.grava({"v": 1, "demandas": [dem(5, "done", [A3])]}, "demandas-arquivo.json")
        inst = bk.instantaneo()
        self.assertEqual(inst["jsons"]["demandas.json"], (self.dir / "demandas.json").read_bytes())
        self.assertIn(b'"rev": 9', inst["jsons"]["demandas.json"])
        self.assertEqual(inst["jsons"]["demandas-arquivo.json"], (self.dir / "demandas-arquivo.json").read_bytes())
        self.assertEqual(inst["anexos"], [A1, A2, A3])
        self.assertEqual(inst["rev"], 9)
        self.assertEqual(inst["contagem"], {"demandas": 4, "arquivo": 1, "pessoas": 1, "setores": 2})

    def test_rev_estranho_vira_0(self):
        for rev in ("9", True, None):
            self.grava({"v": 1, "rev": rev})
            self.assertEqual(bk.instantaneo()["rev"], 0)

    def test_sem_o_principal_usa_o_bak(self):
        (self.dir / "demandas.json.bak").write_text('{"v": 1, "rev": 3}', encoding="utf-8")
        self.assertEqual(bk.instantaneo()["jsons"]["demandas.json"], b'{"v": 1, "rev": 3}')

    def test_principal_ilegivel_usa_o_bak(self):
        for ruim in ("{x", "[1]", "\xff"):
            self.grava(ruim)
            (self.dir / "demandas.json.bak").write_text('{"v": 1, "rev": 4}', encoding="utf-8")
            self.assertEqual(bk.instantaneo()["rev"], 4)
        (self.dir / "demandas.json").write_bytes(b"\xff\xfe")
        self.assertEqual(bk.instantaneo()["rev"], 4)

    def test_ilegivel_sem_bak_valido_falha(self):
        self.grava("{x")
        self.assertEqual(self.erro(500, bk.instantaneo), "Arquivo de dados ilegível: demandas.json.")
        (self.dir / "demandas.json").unlink()
        (self.dir / "demandas.json.bak").write_text("{x", encoding="utf-8")
        self.erro(500, bk.instantaneo)
        self.grava({"v": 1})
        self.grava("{x", "demandas-arquivo.json")
        self.assertIn("demandas-arquivo.json", self.erro(500, bk.instantaneo))

    def test_le_sob_o_lock(self):
        self.grava({"v": 1, "rev": 1})
        feito = threading.Event()
        with ds.LOCK:
            t = threading.Thread(target=lambda: (bk.instantaneo(), feito.set()))
            t.start()
            self.assertFalse(feito.wait(0.3), "leu sem esperar o LOCK")
        self.assertTrue(feito.wait(5))
        t.join()


# ---------- zip e verificação ----------

class Zip(Base):
    def setUp(self):
        super().setUp()
        self.zp = self.root / "z.zip"

    def membros(self):
        return {"demandas.json": b'{"v": 1, "rev": 2}', "demandas-arquivo.json": b'{"v": 1, "demandas": []}',
                "demandas-anexos/%s.jpg" % A1: JPG}

    def defeito(self, caminho=None):
        return self.erro(400, bk.verificar, caminho or self.zp)

    def test_zip_bom(self):
        man = bk.verificar(zip_feito(self.zp, self.membros()))
        self.assertEqual(set(man["arquivos"]), set(self.membros()))
        sem_arquivo = {"demandas.json": b'{"rev": 1}'}   # sem "v" = versão 0, aceito (a migração roda ao ler)
        bk.verificar(zip_feito(self.zp, sem_arquivo))

    def test_nao_e_zip_ou_nao_existe(self):
        self.zp.write_bytes(b"isto nao e zip")
        self.assertEqual(self.defeito(), "Cópia com defeito: não é um zip válido.")
        self.assertEqual(self.defeito(self.root / "nada.zip"), "Cópia com defeito: não foi possível ler o arquivo.")

    def test_byte_trocado(self):
        zip_feito(self.zp, self.membros())
        raw = bytearray(self.zp.read_bytes())
        i = raw.index(JPG)
        raw[i + 10] ^= 0xFF
        self.zp.write_bytes(bytes(raw))
        self.assertEqual(self.defeito(), "Cópia com defeito: arquivo corrompido.")

    def test_byte_trocado_no_comprimido(self):
        grande = {"demandas.json": json.dumps({"v": 1, "x": "abc" * 5000}).encode()}
        with zipfile.ZipFile(self.zp, "w", zipfile.ZIP_DEFLATED) as z:
            for n, b in grande.items():
                z.writestr(n, b)
            z.writestr("manifesto.json", json.dumps({"formato_backup": 1, "arquivos": {
                n: {"bytes": len(b), "sha256": sha(b)} for n, b in grande.items()}}))
        bk.verificar(self.zp)
        raw = bytearray(self.zp.read_bytes())
        for i in (60, 80, 100):
            raw[i] ^= 0x55
        self.zp.write_bytes(bytes(raw))
        self.assertTrue(self.defeito().startswith("Cópia com defeito: "))

    def test_nomes_fora_da_lista(self):
        for n in ("../x", "C:\\x", "C:/x", "/demandas.json", "outro.txt", "demandas-anexos/a1.jpg",
                  "demandas-anexos/%s.exe" % A1, "demandas-anexos/../demandas.json", "rede.json", "sessoes.json"):
            with self.subTest(n=n):
                zip_feito(self.zp, {**self.membros(), n: b"x"})
                self.assertEqual(self.defeito(), "Cópia com defeito: arquivo inesperado.")

    def test_nome_repetido(self):
        with zipfile.ZipFile(self.zp, "w") as z:
            z.writestr("demandas.json", b"{}")
            with self.assertWarns(UserWarning):
                z.writestr("demandas.json", b"{}")
        self.assertEqual(self.defeito(), "Cópia com defeito: nome repetido.")

    def test_grande_demais(self):
        with mock.patch.object(ds, "ANEXO_MAX", len(JPG) - 1):
            zip_feito(self.zp, self.membros())
            self.assertEqual(self.defeito(), "Cópia com defeito: arquivo grande demais.")
        with mock.patch.object(ds, "ANEXO_MAX", len(JPG)):
            bk.verificar(self.zp)
        with mock.patch.object(bk, "JSON_MAX", 10):
            self.assertEqual(self.defeito(), "Cópia com defeito: arquivo grande demais.")
        with mock.patch.object(bk, "MANIFESTO_MAX", 10):
            self.assertEqual(self.defeito(), "Cópia com defeito: arquivo grande demais.")
        tam = sum(len(b) for b in self.membros().values()) + len(zipfile.ZipFile(self.zp).read("manifesto.json"))
        with mock.patch.object(bk, "JSON_MAX", 30), mock.patch.object(bk, "MANIFESTO_MAX", 1000), \
                mock.patch.object(ds, "COTA", tam - 1061):
            self.assertEqual(self.defeito(), "Cópia com defeito: grande demais.")
        with mock.patch.object(bk, "JSON_MAX", 30), mock.patch.object(bk, "MANIFESTO_MAX", 1000), \
                mock.patch.object(ds, "COTA", tam - 1060):
            bk.verificar(self.zp)

    def test_falta_manifesto_ou_principal(self):
        with zipfile.ZipFile(self.zp, "w") as z:
            z.writestr("demandas.json", b"{}")
        self.assertEqual(self.defeito(), "Cópia com defeito: falta o manifesto ou o demandas.json.")
        m = self.membros()
        del m["demandas.json"]
        zip_feito(self.zp, m)
        self.assertEqual(self.defeito(), "Cópia com defeito: falta o manifesto ou o demandas.json.")

    def test_manifesto_ruim(self):
        zip_feito(self.zp, self.membros(), manifesto=b"{x")
        self.assertEqual(self.defeito(), "Cópia com defeito: manifesto ilegível.")
        for man in ([], {"formato_backup": 1}, {"formato_backup": 1, "arquivos": []}):
            zip_feito(self.zp, self.membros(), manifesto=man)
            self.assertEqual(self.defeito(), "Cópia com defeito: manifesto não confere com o conteúdo.")
        zip_feito(self.zp, self.membros(), mexe=lambda m: m["arquivos"].pop("demandas.json"))
        self.assertEqual(self.defeito(), "Cópia com defeito: manifesto não confere com o conteúdo.")
        zip_feito(self.zp, self.membros(), mexe=lambda m: m["arquivos"].update({"demandas-anexos/%s.png" % A2: {}}))
        self.assertEqual(self.defeito(), "Cópia com defeito: manifesto não confere com o conteúdo.")

    def test_formato_mais_novo(self):
        for fmt in (2, "1", None, True):
            zip_feito(self.zp, self.membros(), mexe=lambda m: m.update(formato_backup=fmt))
            self.assertEqual(self.defeito(), "Cópia com defeito: feita por uma versão mais nova da Central de demandas.")

    def test_hash_ou_tamanho_diferente(self):
        n = "demandas-anexos/%s.jpg" % A1
        for mexe in (lambda m: m["arquivos"][n].update(sha256="0" * 64), lambda m: m["arquivos"][n].update(bytes=1),
                     lambda m: m["arquivos"].update({n: "x"})):
            zip_feito(self.zp, self.membros(), mexe=mexe)
            self.assertEqual(self.defeito(), "Cópia com defeito: conteúdo diferente do manifesto.")

    def test_json_ilegivel_ou_versao_mais_nova(self):
        for nome_json in bk.JSONS:
            for ruim in (b"{x", b"\xff", b"[1]", b'{"v": "1"}', b'{"v": true}'):
                with self.subTest(nome_json=nome_json, ruim=ruim):
                    zip_feito(self.zp, {**self.membros(), nome_json: ruim})
                    self.assertEqual(self.defeito(), "Cópia com defeito: %s ilegível." % nome_json)
            zip_feito(self.zp, {**self.membros(), nome_json: b'{"v": 3}'})
            self.assertEqual(self.defeito(), "Cópia com defeito: dados de uma versão mais nova da Central de demandas.")
        # a cópia feita antes do horário de serviço (v1) e a de agora (v2) continuam valendo
        for v in (b'{"v": 1}', b'{"v": 2}'):
            zip_feito(self.zp, {**self.membros(), "demandas.json": v})
            bk.verificar(self.zp)

    def test_nome_zip(self):
        self.assertEqual(bk.nome_zip(ms(2026, 10, 28, 3, 0), "auto"), "central-demandas_20261028-0300_auto.zip")
        self.assertEqual(bk.nome_zip(ms(2026, 1, 2, 23, 59), "antes-restaurar"),
                         "central-demandas_20260102-2359_antes-restaurar.zip")
        for t in ("auto", "inicio", "manual", "antes-restaurar"):
            self.assertTrue(bk.NOME_RE.fullmatch(bk.nome_zip(0, t)))


# ---------- cópia completa ----------

class Fazer(Base):
    AGORA = ms(2026, 10, 28, 3)

    def dados(self):
        self.grava({"v": 1, "rev": 7, "setores": [{"id": "PCP"}], "pessoas": [],
                    "demandas": [dem(1, "new", [A1]), dem(2, "done", [A2])]})
        self.grava({"v": 1, "demandas": [dem(3, "done", [A3])]}, "demandas-arquivo.json")
        self.anexo(A1)
        self.anexo(A2, PNG, "png")
        self.anexo(A3)
        self.anexo("a" + "9" * 16)   # órfão: sem metadado

    def test_copia_inteira_verificada(self):
        self.dados()
        info = bk.fazer("manual", self.AGORA)
        n = "central-demandas_20261028-0300_manual.zip"
        self.assertEqual(self.zips(), [n])
        zp = self.pasta() / n
        raw = zp.read_bytes()
        self.assertEqual(info, {"t": self.AGORA, "nome": n, "tipo": "manual", "bytes": len(raw), "sha256": sha(raw),
                                "rev": 7, "verificado": True, "faltando": 0})
        man = bk.verificar(zp)
        with zipfile.ZipFile(zp) as z:
            self.assertEqual(sorted(z.namelist()), sorted(["demandas.json", "demandas-arquivo.json", "manifesto.json",
                                                           "demandas-anexos/%s.jpg" % A1, "demandas-anexos/%s.png" % A2,
                                                           "demandas-anexos/%s.jpg" % A3]))
            self.assertEqual(z.read("demandas.json"), (self.dir / "demandas.json").read_bytes())
            self.assertEqual(z.read("demandas-anexos/%s.png" % A2), PNG)
            tipos = {i.filename: i.compress_type for i in z.infolist()}
        self.assertEqual(tipos["demandas.json"], zipfile.ZIP_DEFLATED)
        self.assertEqual(tipos["manifesto.json"], zipfile.ZIP_DEFLATED)
        self.assertEqual(tipos["demandas-anexos/%s.jpg" % A1], zipfile.ZIP_STORED)
        self.assertEqual((man["programa"], man["formato_backup"], man["v_dados"], man["criado"], man["tipo"], man["rev"]),
                         ("Central de demandas", 1, 1, self.AGORA, "manual", 7))
        self.assertEqual(man["contagem"], {"demandas": 2, "arquivo": 1, "pessoas": 0, "setores": 1, "anexos": 3})
        self.assertEqual(man["faltando"], [])
        self.assertTrue(man["maquina"])
        est = bk.estado()
        self.assertEqual(est["ultimo_ok"], info)
        self.assertEqual(est["falhas_seguidas"], 0)
        self.assertFalse([p for p in self.pasta().iterdir() if p.suffix == ".part"])
        self.assertFalse((self.dir / "backup").exists(), "nada de cópia dentro de data/")

    def test_rede_e_sessoes_nunca_entram(self):
        self.dados()
        self.grava({"on": True, "pin": "123456", "pin_op": "654321"}, "rede.json")
        self.grava({}, "sessoes.json")
        bk.fazer("manual", self.AGORA)
        with zipfile.ZipFile(self.pasta() / self.zips()[0]) as z:
            self.assertFalse({"rede.json", "sessoes.json", "backup.json", "backup-estado.json"} & set(z.namelist()))
            self.assertNotIn(b"123456", b"".join(z.read(n) for n in z.namelist()))

    def test_anexo_citado_que_sumiu_vai_em_faltando(self):
        self.dados()
        (ds.anexos_dir() / ("%s.jpg" % A3)).unlink()
        info = bk.fazer("auto", self.AGORA)
        self.assertEqual(info["faltando"], 1)
        man = bk.verificar(self.pasta() / info["nome"])
        self.assertEqual(man["faltando"], [A3])
        self.assertEqual(man["contagem"]["anexos"], 2)

    def test_anexo_removido_no_meio_da_copia(self):
        self.dados()
        ler = ds.ler_anexo

        def some(aid):
            if aid == A1:   # removido entre o instantâneo e a cópia
                (ds.anexos_dir() / ("%s.jpg" % A1)).unlink()
            return ler(aid)

        with mock.patch.object(ds, "ler_anexo", side_effect=some):
            info = bk.fazer("manual", self.AGORA)
        man = bk.verificar(self.pasta() / info["nome"])
        self.assertEqual(man["faltando"], [A1])
        self.assertEqual(man["contagem"]["anexos"], 2, "os anexos depois do que sumiu também entram")

    def test_grava_em_part_e_so_depois_vira_zip(self):
        vistos = []
        verificar = bk.verificar
        with mock.patch.object(bk, "verificar", side_effect=lambda p: (vistos.append(p.name), verificar(p))[1]):
            info = bk.fazer("manual", self.AGORA)
        self.assertEqual(vistos, [info["nome"] + ".part"])

    def test_limite_em_bytes_e_contador_zerado_no_disco(self):
        bk.salvar_config({"limite_mb": 70})
        with mock.patch.object(bk, "reter", return_value=[]) as reter:
            bk.fazer("manual", self.AGORA)
        self.assertEqual(reter.call_args.args[2], 70 * 1024 * 1024)
        self.assertEqual(json.loads((self.dir / "backup-estado.json").read_text(encoding="utf-8"))["falhas_seguidas"], 0)

    def test_detalhe_cortado_em_300(self):
        with mock.patch.object(bk, "instantaneo", side_effect=OSError("x" * 400)):
            with self.assertRaises(OSError):
                bk.fazer("auto", self.AGORA)
        self.assertEqual(bk.estado()["ultima_falha"]["detalhe"], str(OSError("x" * 400))[:300])
        self.assertEqual(len(bk.estado()["ultima_falha"]["detalhe"]), 300)

    def test_falha_no_meio_apaga_o_part_e_registra(self):
        self.dados()
        with mock.patch.object(ds, "ler_anexo", side_effect=OSError("disco caiu C:\\x")):
            with self.assertRaises(OSError):
                bk.fazer("auto", self.AGORA)
        self.assertEqual(self.zips(), [])
        est = bk.estado()
        self.assertIsNone(est["ultimo_ok"])
        self.assertEqual(est["ultima_falha"], {"t": self.AGORA, "destino": "local",
                                               "erro": "falha ao gravar a cópia (OSError)", "detalhe": "disco caiu C:\\x"})
        self.assertEqual(est["falhas_seguidas"], 1)
        with mock.patch.object(bk, "verificar", side_effect=ds.StoreError(400, "Cópia com defeito: x.")):
            self.erro(400, bk.fazer, "auto", self.AGORA + 60000)
        self.assertEqual(self.zips(), [])
        self.assertEqual(bk.estado()["falhas_seguidas"], 2)
        self.assertEqual(bk.estado()["ultima_falha"]["erro"], "Cópia com defeito: x")
        self.assertEqual(bk.resumo(self.AGORA + 60000)["texto"], "Nenhum backup feito ainda: Cópia com defeito: x")
        bk.fazer("auto", self.AGORA + 120000)
        self.assertEqual(bk.estado()["falhas_seguidas"], 0)
        self.assertEqual(bk.estado()["ultima_falha"]["t"], self.AGORA + 60000, "a falha fica no histórico")

    def test_sem_espaco(self):
        self.dados()
        uso = mock.Mock(free=0)
        with mock.patch.object(bk.shutil, "disk_usage", return_value=uso):
            self.assertEqual(self.erro(507, bk.fazer, "auto", self.AGORA), "Sem espaço no disco para o backup.")
        self.assertEqual(self.zips(), [])
        self.assertEqual(bk.estado()["ultima_falha"]["erro"], "Sem espaço no disco para o backup")
        precisa = 2 * (sum(len(b) for b in bk.instantaneo()["jsons"].values()) + ds.uso_anexos()["bytes"])
        with mock.patch.object(bk.shutil, "disk_usage", return_value=mock.Mock(free=precisa - 1)):
            self.erro(507, bk.fazer, "auto", self.AGORA)
        with mock.patch.object(bk.shutil, "disk_usage", return_value=mock.Mock(free=precisa)):
            bk.fazer("auto", self.AGORA)

    def test_pasta_sumiu(self):
        destino = self.root / "pen" / "copias"
        destino.parent.mkdir()
        bk.salvar_config({"local": str(destino)})
        destino.rmdir()
        destino.parent.rmdir()
        self.assertEqual(self.erro(500, bk.fazer, "auto", self.AGORA), "Pasta do backup não encontrada.")
        self.assertFalse(destino.parent.exists(), "não cria a letra do pen drive")
        destino.parent.mkdir()
        bk.fazer("auto", self.AGORA)
        self.assertEqual(len(list(destino.iterdir())), 1, "pasta do backup recriada dentro da mãe que existe")

    def test_part_velho_some_e_o_resto_fica(self):
        self.pasta().mkdir()
        velho = self.pasta() / (nome(2026, 10, 1) + ".part")
        velho.write_bytes(b"x")
        alheios = [self.pasta() / "notas.txt", self.pasta() / "outro.zip.part"]
        for a in alheios:
            a.write_bytes(b"x")
        bk.fazer("manual", self.AGORA)
        self.assertFalse(velho.exists())
        self.assertTrue(all(a.exists() for a in alheios))

    def test_retencao_na_pasta(self):
        self.pasta().mkdir()
        for d in (1, 2, 3):
            (self.pasta() / nome(2026, 10, d, 10, 0, "manual")).write_bytes(b"x")
        (self.pasta() / "notas.txt").write_bytes(b"x")
        bk.salvar_config({"ret": {"manuais": 2}})
        info = bk.fazer("manual", self.AGORA)
        self.assertEqual(self.zips(), sorted([nome(2026, 10, 3, 10, 0, "manual"), info["nome"], "notas.txt"]))

    def test_mesmo_minuto_substitui(self):
        bk.fazer("manual", self.AGORA)
        self.grava({"v": 1, "rev": 99})
        bk.fazer("manual", self.AGORA + 30000)
        self.assertEqual(len(self.zips()), 1)
        self.assertEqual(bk.verificar(self.pasta() / self.zips()[0])["rev"], 99)

    def test_uma_de_cada_vez_e_tipo(self):
        with bk._BACKUP:
            self.assertEqual(self.erro(409, bk.fazer, "manual", self.AGORA), "Já tem um backup em andamento.")
        self.assertEqual(self.erro(400, bk.fazer, "outro", self.AGORA), "Tipo de backup inválido.")
        self.assertEqual(self.zips(), [])
        self.assertIsNone(bk.estado()["ultima_falha"], "recusa não é falha do backup")

    def test_relogio_padrao(self):
        antes = int(time.time() * 1000)
        info = bk.fazer("manual")
        self.assertTrue(antes <= info["t"] <= int(time.time() * 1000))


class Painel(Base):
    AGORA = ms(2026, 10, 28, 12)

    def test_quando(self):
        self.assertEqual(bk.quando(nome(2026, 10, 28, 3, 7)), ms(2026, 10, 28, 3, 7))
        self.assertEqual(bk.quando(nome(2026, 1, 2, 23, 59, "antes-restaurar")), ms(2026, 1, 2, 23, 59))
        for n in ("outro.zip", nome(2026, 1, 1) + ".part", ""):
            self.assertIsNone(bk.quando(n))

    def test_sem_copias(self):
        p = bk.painel(self.AGORA)
        self.assertEqual((p["cfg"], p["padrao"], p["pasta"], p["pasta_ok"], p["copias"], p["usado"], p["rodando"]),
                         (bk.config(), bk.PADRAO, str(self.pasta()), False, [], 0, False))
        self.assertEqual(p["estado"], bk.estado())
        self.assertEqual(p["resumo"], bk.resumo(self.AGORA))
        self.assertIsInstance(p["livre"], int)
        self.assertGreater(p["livre"], 0)

    def test_copias_mais_novas_primeiro(self):
        self.pasta().mkdir()
        for n, tam in ((nome(2026, 10, 27), 3), (nome(2026, 10, 28, 3, 0, "manual"), 5), (nome(2026, 10, 28), 7)):
            (self.pasta() / n).write_bytes(b"x" * tam)
        (self.pasta() / "outro.txt").write_bytes(b"x")
        p = bk.painel(self.AGORA)
        self.assertEqual(p["copias"], [
            {"nome": nome(2026, 10, 28, 3, 0, "manual"), "tipo": "manual", "bytes": 5, "t": ms(2026, 10, 28, 3)},
            {"nome": nome(2026, 10, 28), "tipo": "auto", "bytes": 7, "t": ms(2026, 10, 28, 3)},
            {"nome": nome(2026, 10, 27), "tipo": "auto", "bytes": 3, "t": ms(2026, 10, 27, 3)}])
        self.assertEqual((p["usado"], p["pasta_ok"]), (15, True))
        with bk._BACKUP:
            self.assertTrue(bk.painel(self.AGORA)["rodando"])

    def test_usa_o_relogio_dado(self):
        self.grava({"ultimo_ok": {"t": self.AGORA - 30 * H}}, "backup-estado.json")
        self.assertEqual(bk.painel(self.AGORA)["resumo"]["texto"], "Último backup há 30 h.")
        self.assertEqual(bk.painel(self.AGORA - 29 * H)["resumo"]["alerta"], None)

    def test_disco_ilegivel_e_relogio_padrao(self):
        with mock.patch.object(bk.shutil, "disk_usage", side_effect=OSError("x")):
            self.assertIsNone(bk.painel(self.AGORA)["livre"])
        bk.salvar_config({"on": False})
        self.assertEqual(bk.painel()["resumo"]["alerta"], "aviso")


class Restaurar(Base):
    T1, T2 = ms(2026, 10, 27, 12), ms(2026, 10, 28, 9)

    def setUp(self):
        super().setUp()
        self.grava({"v": 1, "rev": 7, "seq": {"pessoa": 1, "demanda": 1002, "nota": 4}, "pessoas": [{"id": "p1"}],
                    "setores": [{"id": "PCP"}], "demandas": [dem(1001, "new", [A1]), dem(1002)]})
        self.grava({"v": 1, "demandas": [dem(900, "done", [A3])]}, "demandas-arquivo.json")
        self.anexo(A1)
        self.anexo(A3)
        self.copia = bk.fazer("manual", self.T1)["nome"]
        self.backup_principal = json.loads((self.dir / "demandas.json").read_text(encoding="utf-8"))
        # depois do backup: demanda nova com anexo novo, rev e seq andam
        self.grava({"v": 1, "rev": 12, "seq": {"pessoa": 3, "demanda": 1003, "nota": 2, "extra": 9},
                    "pessoas": [{"id": "p1"}, {"id": "p2"}], "setores": [{"id": "PCP"}],
                    "demandas": [dem(1001, "new", [A1]), dem(1002), dem(1003, "new", [A2])]})
        self.anexo(A2, PNG, "png")
        velho = time.time() - 60
        for f in ds.anexos_dir().iterdir():
            os.utime(f, (velho, velho))

    def disco(self, nome="demandas.json"):
        return json.loads((self.dir / nome).read_text(encoding="utf-8"))

    def foto(self):
        return {str(p.relative_to(self.dir)): p.read_bytes() for p in sorted(self.dir.rglob("*")) if p.is_file()}

    def test_dados_voltam_com_rev_e_seq_sem_voltar(self):
        feito = bk.restaurar(self.copia, self.T2)
        doc = self.disco()
        self.assertEqual([d["id"] for d in doc["demandas"]], ["SOL-1001", "SOL-1002"])
        self.assertEqual(doc["rev"], 13, "máximo entre 12 (agora) e 7 (cópia) + 1")
        self.assertEqual(doc["seq"], {"pessoa": 3, "demanda": 1003, "nota": 4, "extra": 9})
        self.assertEqual(doc["pessoas"], [{"id": "p1"}])
        self.assertEqual([d["id"] for d in self.disco("demandas-arquivo.json")["demandas"]], ["SOL-900"])
        self.assertEqual({k: v for k, v in doc.items() if k not in ("rev", "seq")},
                         {k: v for k, v in self.backup_principal.items() if k not in ("rev", "seq")})
        self.assertEqual(sorted(p.name for p in ds.anexos_dir().iterdir()), ["%s.jpg" % A1, "%s.jpg" % A3],
                         "o anexo que a cópia não cita sai (está no zip antes-restaurar)")
        self.assertEqual([d["id"] for d in ds.load()["demandas"]], ["SOL-1001", "SOL-1002"], "cache limpo")
        self.assertEqual([d["id"] for d in ds.load_arquivo()], ["SOL-900"])
        antes = nome(2026, 10, 28, 9, 0, "antes-restaurar")
        self.assertEqual(feito, {"t": self.T2, "nome": self.copia, "copia_t": self.T1, "rev": 13, "antes": antes})
        with zipfile.ZipFile(self.pasta() / antes) as z:
            self.assertEqual(json.loads(z.read("demandas.json"))["rev"], 12, "a cópia de antes tem o estado de agora")
            self.assertIn("demandas-anexos/%s.png" % A2, z.namelist())
        bk.verificar(self.pasta() / antes)
        self.assertEqual(bk.estado()["restaurado"], feito)
        self.assertEqual(bk.resumo(self.T2)["restaurado"], {"t": self.T2, "copia_t": self.T1})
        self.assertFalse((self.dir / ".restaurar-tmp").exists())

    def test_extrai_em_data_restaurar_tmp_antes_da_copia_de_antes(self):
        uma = bk._uma_copia
        vistos = []

        def confere(tipo, agora):
            tmp = self.dir / ".restaurar-tmp"
            vistos.append(((tmp / "demandas.json").is_file(), (tmp / "demandas-anexos" / ("%s.jpg" % A1)).is_file()))
            return uma(tipo, agora)

        with mock.patch.object(bk, "_uma_copia", side_effect=confere):
            bk.restaurar(self.copia, self.T2)
        self.assertEqual(vistos, [(True, True)])
        self.assertFalse((self.dir / ".restaurar-tmp").exists())

    def test_sem_rev_em_nenhum_dos_dois(self):
        self.pasta().mkdir(exist_ok=True)
        n = nome(2026, 1, 1, 10, 0, "manual")
        zip_feito(self.pasta() / n, {"demandas.json": b'{"v": 1}'})
        self.grava({"v": 1})
        bk.restaurar(n, self.T2)
        self.assertEqual(self.disco()["rev"], 1)

    def test_anexo_do_mesmo_instante_da_restauracao_fica(self):
        marco = time.time() + 30
        os.utime(ds.anexos_dir() / ("%s.png" % A2), (marco, marco))
        with mock.patch.object(bk.time, "time", return_value=marco):
            bk.restaurar(self.copia, self.T2)
        self.assertTrue((ds.anexos_dir() / ("%s.png" % A2)).exists(), "pode ter chegado durante a restauração")

    def test_rev_da_copia_maior(self):
        doc = self.disco()
        doc["rev"] = 3
        self.grava(doc)
        bk.restaurar(self.copia, self.T2)
        self.assertEqual(self.disco()["rev"], 8)

    def test_seq_estranho(self):
        doc = self.disco()
        doc["seq"] = {"demanda": True, "nota": "9", "pessoa": 0}
        self.grava(doc)
        bk.restaurar(self.copia, self.T2)
        self.assertEqual(self.disco()["seq"], {"pessoa": 1, "demanda": 1002, "nota": 4})
        doc = self.disco()
        doc["seq"] = []
        self.grava(doc)
        bk.fazer("manual", self.T2 + 60000)
        sem_seq = dict(self.backup_principal)
        del sem_seq["seq"]
        self.grava(sem_seq)
        copia = bk.fazer("manual", self.T2 + 120000)["nome"]
        self.grava({"v": 1, "rev": 1, "seq": {"demanda": 1500}})
        bk.restaurar(copia, self.T2 + 180000)
        self.assertEqual(self.disco()["seq"], {"demanda": 1500})

    def test_anexo_que_sumiu_volta_e_o_enviado_agora_fica(self):
        (ds.anexos_dir() / ("%s.jpg" % A1)).unlink()
        novo = "a" + "4" * 16
        self.anexo(novo)   # mtime de agora: enviado durante a restauração
        futuro = time.time() + 60
        os.utime(ds.anexos_dir() / ("%s.jpg" % novo), (futuro, futuro))
        bk.restaurar(self.copia, self.T2)
        self.assertEqual((ds.anexos_dir() / ("%s.jpg" % A1)).read_bytes(), JPG)
        self.assertTrue((ds.anexos_dir() / ("%s.jpg" % novo)).exists())
        self.assertFalse((ds.anexos_dir() / ("%s.png" % A2)).exists())

    def test_anexo_que_chega_no_meio_da_copia(self):
        (ds.anexos_dir() / ("%s.jpg" % A1)).unlink()
        with mock.patch.object(ds, "_publica", side_effect=FileExistsError):
            bk.restaurar(self.copia, self.T2)
        self.assertEqual(self.disco()["rev"], 13)

    def test_anexo_some_durante_a_limpeza(self):
        real = os.scandir

        def falso(p):
            if Path(p) != ds.anexos_dir():
                return real(p)
            e = mock.Mock()
            e.name, e.path = "%s.png" % A2, str(ds.anexos_dir() / ("%s.png" % A2))
            e.stat.side_effect = FileNotFoundError("sumiu")
            return [e]

        with mock.patch.object(bk.os, "scandir", side_effect=falso):
            bk.restaurar(self.copia, self.T2)
        self.assertTrue((ds.anexos_dir() / ("%s.png" % A2)).exists())

    def test_copia_sem_arquivo_morto_esvazia_o_atual(self):
        (self.dir / "demandas-arquivo.json").unlink()
        sem = bk.fazer("manual", self.T2 - 60000)["nome"]
        self.grava({"v": 1, "demandas": [dem(901)]}, "demandas-arquivo.json")
        bk.restaurar(sem, self.T2)
        self.assertEqual(self.disco("demandas-arquivo.json"), {"v": ds.V, "demandas": []})

    def test_atual_ilegivel_tambem_restaura(self):
        self.grava("{quebrado")
        (self.dir / "demandas.json.bak").write_text("{ruim", encoding="utf-8")
        feito = bk.restaurar(self.copia, self.T2)
        self.assertEqual(self.disco()["rev"], 8)
        self.assertEqual(self.disco()["seq"]["demanda"], 1002)
        self.assertIsNone(feito["antes"])
        self.assertEqual((self.dir / ("demandas.json.ilegivel-%d" % self.T2)).read_text(encoding="utf-8"), "{quebrado")
        self.assertEqual((self.dir / ("demandas.json.bak.ilegivel-%d" % self.T2)).read_text(encoding="utf-8"), "{ruim")
        self.assertTrue((self.dir / ("demandas-arquivo.json.ilegivel-%d" % self.T2)).exists())
        self.assertFalse((self.dir / ("demandas-arquivo.json.bak.ilegivel-%d" % self.T2)).exists())

    def test_copia_com_defeito_nao_muda_nada(self):
        antes = self.foto()
        raw = bytearray((self.pasta() / self.copia).read_bytes())
        raw[raw.index(JPG) + 5] ^= 0xFF
        (self.pasta() / self.copia).write_bytes(bytes(raw))
        self.assertEqual(self.erro(400, bk.restaurar, self.copia, self.T2), "Cópia com defeito: arquivo corrompido.")
        self.assertEqual(self.foto(), antes, "data/ intacto, byte a byte")

    def test_sem_espaco_para_a_copia_de_antes_nao_muda_nada(self):
        antes = self.foto()
        with mock.patch.object(bk.shutil, "disk_usage", return_value=mock.Mock(free=0)):
            self.erro(507, bk.restaurar, self.copia, self.T2)
        depois = self.foto()
        for f in ("backup-estado.json", "backup-estado.json.bak"):   # só o registro da falha muda
            depois.pop(f, None)
            antes.pop(f, None)
        self.assertEqual(depois, antes)
        self.assertEqual(bk.estado()["ultima_falha"]["erro"], "Sem espaço no disco para o backup")
        self.assertIsNone(bk.estado()["restaurado"])

    def test_zip_mudou_entre_conferir_e_ler(self):
        verificar = bk.verificar

        def mexe(p):
            man = verificar(p)
            man["arquivos"]["demandas.json"]["sha256"] = "0" * 64
            return man

        antes = self.foto()
        with mock.patch.object(bk, "verificar", side_effect=mexe):
            self.assertEqual(self.erro(400, bk.restaurar, self.copia, self.T2),
                             "Cópia com defeito: conteúdo diferente do manifesto.")
        self.assertEqual(self.foto(), antes)
        self.assertFalse((self.dir / ".restaurar-tmp").exists())

    def test_so_copias_da_pasta(self):
        for n in ("..\\demandas.json", "../x.zip", str(self.pasta() / self.copia), nome(2020, 1, 1), "", None, 5, ["x"]):
            self.assertEqual(self.erro(404, bk.restaurar, n, self.T2), "Cópia não encontrada.")
            self.assertEqual(self.erro(404, bk.previa, n), "Cópia não encontrada.")

    def test_uma_de_cada_vez(self):
        with bk._BACKUP:
            self.assertEqual(self.erro(409, bk.restaurar, self.copia, self.T2), "Já tem um backup em andamento.")
        self.assertEqual(self.disco()["rev"], 12)

    def test_relogio_padrao_e_estado_guardado_depois_de_outra_copia(self):
        antes = int(time.time() * 1000)
        feito = bk.restaurar(self.copia)
        self.assertTrue(antes <= feito["t"] <= int(time.time() * 1000))
        bk.fazer("manual", feito["t"] + 120000)
        self.assertEqual(bk.estado()["restaurado"], feito, "uma cópia nova não apaga o registro da restauração")

    def test_previa(self):
        p = bk.previa(self.copia)
        self.assertEqual(p, {"nome": self.copia,
                             "copia": {"t": self.T1, "tipo": "manual", "rev": 7,
                                       "contagem": {"demandas": 2, "arquivo": 1, "pessoas": 1, "setores": 1, "anexos": 2}},
                             "agora": {"rev": 12, "contagem": {"demandas": 3, "arquivo": 1, "pessoas": 2, "setores": 1,
                                                               "anexos": 3}},
                             "proximo": "SOL-1004"})
        doc = self.disco()
        doc["seq"] = {"demanda": 900}
        self.grava(doc)
        self.assertEqual(bk.previa(self.copia)["proximo"], "SOL-1003")
        doc["seq"] = {}
        self.grava(doc)
        self.assertEqual(bk.previa(self.copia)["proximo"], "SOL-1003")
        self.assertEqual(self.disco()["rev"], 12, "a prévia não muda nada")

    def test_previa_de_zip_feito_a_mao(self):
        self.pasta().mkdir(exist_ok=True)
        n = nome(2026, 1, 1, 10, 0, "manual")
        zip_feito(self.pasta() / n, {"demandas.json": b'{"v": 1}'})
        p = bk.previa(n)
        self.assertEqual((p["copia"]["contagem"], p["copia"]["t"], p["proximo"]), ({}, 0, "SOL-1004"))
        zip_feito(self.pasta() / n, {"demandas.json": b'{"v": 1, "seq": {"demanda": 5000}}'},
                  mexe=lambda m: m.update(contagem=[]))
        self.assertEqual((bk.previa(n)["copia"]["contagem"], bk.previa(n)["proximo"]), ({}, "SOL-5001"))
        (self.pasta() / n).write_bytes(b"x")
        self.erro(400, bk.previa, n)

    def test_seq_demanda(self):
        self.assertEqual(bk._seq_demanda({"seq": {"demanda": 7}}), 7)
        for doc in ({}, [], None, {"seq": []}, {"seq": {"demanda": True}}, {"seq": {"demanda": "7"}}):
            self.assertEqual(bk._seq_demanda(doc), 1000)


class Tarefa(Base):
    AGORA = ms(2026, 10, 28, 10)

    def test_marca_o_inicio_e_espera(self):
        bk.tarefa(self.AGORA)
        self.assertEqual(bk._INICIO["t"], self.AGORA)
        self.assertEqual(self.zips(), [])
        bk.tarefa(self.AGORA + 60000)
        self.assertEqual(self.zips(), [])
        bk.tarefa(self.AGORA + 120000)
        self.assertEqual(self.zips(), [nome(2026, 10, 28, 10, 2, "auto")])
        bk.tarefa(self.AGORA + 180000)
        bk.tarefa(ms(2026, 10, 28, 23, 59))
        self.assertEqual(len(self.zips()), 1, "uma vez por dia")
        self.assertEqual(bk._INICIO["t"], self.AGORA)
        bk.tarefa(ms(2026, 10, 29, 3))
        self.assertEqual(self.zips()[-1], nome(2026, 10, 29, 3, 0, "auto"))

    def test_ao_ligar(self):
        bk._INICIO["t"] = ms(2026, 10, 29, 0)
        self.grava({"ultimo_ok": {"t": ms(2026, 10, 28, 3)}}, "backup-estado.json")
        bk.tarefa(ms(2026, 10, 29, 0, 2))
        self.assertEqual(self.zips(), [nome(2026, 10, 29, 0, 2, "inicio")])

    def test_desligado_nao_faz(self):
        bk.salvar_config({"on": False})
        bk._INICIO["t"] = 0
        bk.tarefa(self.AGORA)
        self.assertEqual(self.zips(), [])

    def test_409_calado_e_outro_erro_no_log(self):
        bk._INICIO["t"] = 0
        with bk._BACKUP, mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            bk.tarefa(self.AGORA)
        self.assertEqual(err.getvalue(), "")
        with mock.patch.object(bk.shutil, "disk_usage", return_value=mock.Mock(free=0)), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            bk.tarefa(self.AGORA)
        self.assertEqual(err.getvalue(), "[backup] Sem espaço no disco para o backup.\n")
        self.assertEqual(self.zips(), [])


# ---------- integração: gravações acontecendo durante as cópias ----------

class Concorrencia(Base):
    def test_par_principal_e_arquivo_morto_sempre_coerente(self):
        parar, erros, n = threading.Event(), [], [0]

        def escritor():
            try:
                while not parar.is_set():
                    with ds.LOCK:
                        doc = ds.load()
                        n[0] += 1
                        doc["demandas"].append(dem(1000 + doc["rev"] + 1))
                        ds.commit(doc)   # passa do teto de 20: _arquivar grava o arquivo morto antes do principal
            except Exception as exc:   # pragma: no cover - só aparece se quebrar
                erros.append(exc)

        with mock.patch.dict(ds.MAX, {"demandas": 20}):
            t = threading.Thread(target=escritor)
            t.start()
            try:
                infos = []
                for i in range(8):
                    infos.append(bk.fazer("manual", ms(2026, 10, 28, 3, i)))
                    time.sleep(0.01)
            finally:
                parar.set()
                t.join()
        self.assertEqual(erros, [])
        self.assertGreater(n[0], 20, "o escritor precisa ter passado do teto durante as cópias")
        revs = []
        for info in infos[-5:]:   # a retenção guarda as 5 manuais mais novas
            zp = self.pasta() / info["nome"]
            man = bk.verificar(zp)
            with zipfile.ZipFile(zp) as z:
                principal = json.loads(z.read("demandas.json"))
                arq = json.loads(z.read("demandas-arquivo.json"))["demandas"] if "demandas-arquivo.json" in z.namelist() else []
            ids_p = {d["id"] for d in principal["demandas"]}
            ids_a = {d["id"] for d in arq}
            self.assertFalse(ids_p & ids_a, "demanda nos dois arquivos")
            esperado = {"SOL-%d" % (1000 + r) for r in range(1, principal["rev"] + 1)}
            self.assertEqual(ids_p | ids_a, esperado, "demanda perdida entre o principal e o arquivo morto")
            self.assertEqual(man["rev"], principal["rev"])
            revs.append(principal["rev"])
        self.assertEqual(revs, sorted(revs))


if __name__ == "__main__":
    unittest.main()
