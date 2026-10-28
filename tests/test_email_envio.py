"""email_envio: configuração (senha nunca volta), DPAPI, montagem da mensagem (fio, escape), envio SMTP simulado,
classificação de erros, fila (espera crescente, 6ª falha, 535 pausa, teto), estado, registro e um servidor SMTP falso
de verdade numa porta livre (nunca a 8090). Dados num diretório temporário (DEMANDAS_DATA).
"""

import json
import os
import smtplib
import socketserver
import sys
import tempfile
import threading
import unittest
from email import message_from_bytes, policy
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import email_envio as mail  # noqa: E402

RODADA0 = dict(mail._RODADA)   # antes de qualquer teste mexer

T0 = 1_761_660_000_000
MIN = 60000
CFG_OK = {"ligado": True, "host": "smtp.empresa.com.br", "porta": 587, "seguranca": "starttls",
          "usuario": "demandas@empresa.com.br", "remetente": "Central de demandas <demandas@empresa.com.br>"}


def envio(dem="SOL-1043", ev="created", para=("joao@empresa.com.br",), **dados):
    d = {"titulo": "Corrigir solda", "de": "Montagem · Carlos", "para": "Solda · João", "prio": "Alta", "prazo": T0 + 60 * MIN,
         "motivo": "Defeito de qualidade", "tipo": "Demanda", "quem": "Carlos", "nota": "", "desc": "Trinca no cordão"}
    d.update(dados)
    return {"dem": dem, "ev": ev, "para": list(para), "cc": [], "dados": d}


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="dem-mail-"))
        self._env = mock.patch.dict(os.environ, {"DEMANDAS_DATA": str(self.dir)})
        self._env.start()
        mail._RODADA["t"] = None

    def tearDown(self):
        self._env.stop()

    def grava_cfg(self, **kw):
        cfg = dict(CFG_OK, v=1, instalacao="k7f3q9")
        cfg.update(kw)
        (self.dir / "email.json").write_text(json.dumps(cfg), encoding="utf-8")

    def fila(self):
        return json.loads((self.dir / "email-fila.json").read_text(encoding="utf-8"))

    def log(self):
        p = self.dir / "email-log.json"
        return json.loads(p.read_text(encoding="utf-8"))["itens"] if p.exists() else []

    def erro(self, fn, *a, **kw):
        with self.assertRaises(mail.EmailErro) as cm:
            fn(*a, **kw)
        self.assertEqual(cm.exception.status, 400)
        return str(cm.exception)


# ---------- configuração e senha ----------

class Config(Base):
    def test_padrao(self):
        c = mail.config()
        self.assertEqual((c["ligado"], c["porta"], c["seguranca"], c["fila_setor"], c["descricao"], c["copia_solicitante"]),
                         (False, 587, "starttls", "setor_ou_pessoas", True, False))
        self.assertEqual(c["eventos"], {"created": True, "started": False, "done": False, "nudge": False, "late": False,
                                        "comment": False, "canc": False})
        self.assertEqual((c["tem_senha"], c["senha_abre"], c["senha_texto"]), (False, False, False))
        self.assertNotIn("senha", c)
        self.assertNotIn("instalacao", c)

    def test_salvar_e_senha_nunca_volta(self):
        c = mail.salvar_config(dict(CFG_OK, senha="s3nha-secreta", link_base="http://192.168.0.20:8090",
                                    eventos={"done": True}, fila_setor="so_setor", descricao=False))
        self.assertEqual((c["ligado"], c["host"], c["link_base"], c["fila_setor"], c["descricao"]),
                         (True, "smtp.empresa.com.br", "http://192.168.0.20:8090", "so_setor", False))
        self.assertTrue(c["eventos"]["created"] and c["eventos"]["done"])
        self.assertTrue(c["tem_senha"] and c["senha_abre"])
        self.assertNotIn("s3nha-secreta", json.dumps(c))
        self.assertEqual(mail._desprotege(mail._bruta()["senha"]), "s3nha-secreta")
        if sys.platform == "win32":
            self.assertNotIn("s3nha-secreta", (self.dir / "email.json").read_text(encoding="utf-8"), "cifrada pelo Windows")
            self.assertFalse(c["senha_texto"])
        inst = mail._bruta()["instalacao"]
        self.assertRegex(inst, r"^[a-z0-9]{6}$")
        mail.salvar_config({"senha": None, "host": " smtp2.empresa.com "})   # None mantém; espaços saem
        self.assertEqual(mail._desprotege(mail._bruta()["senha"]), "s3nha-secreta")
        self.assertEqual((mail.config()["host"], mail._bruta()["instalacao"]), ("smtp2.empresa.com", inst))
        mail.salvar_config({"porta": 465})   # sem "senha" no pedido: mantém
        self.assertTrue(mail.config()["tem_senha"])
        mail.salvar_config({"senha": ""})
        self.assertFalse(mail.config()["tem_senha"])
        self.assertNotIn("senha", json.loads((self.dir / "email.json").read_text(encoding="utf-8")))

    def test_recusa(self):
        mail.salvar_config(CFG_OK)
        antes = (self.dir / "email.json").read_bytes()
        casos = {"ligado": ["sim", 1], "porta": [0, 65536, "587", True], "seguranca": ["tls", None],
                 "host": ["smtp empresa", "smtp/x", 5, "a" * 254], "usuario": ["a\nb", 5, "x" * 255],
                 "remetente": ["sem arroba", "a@b.com\r\nBcc: x@y.com", "Nome <ruim>", 5, "x" * 301],
                 "link_base": ["ftp://x", "http://a b", "javascript:alert(1)", 5], "fila_setor": ["todos"],
                 "eventos": ["x", {"created": "sim"}], "copia_solicitante": ["s"], "descricao": [None],
                 "senha": [5, "x" * 501]}
        for k, vs in casos.items():
            for v in vs:
                with self.subTest(k=k, v=v):
                    self.erro(mail.salvar_config, {k: v})
        self.assertEqual((self.dir / "email.json").read_bytes(), antes)
        for b in ([], None):
            self.assertEqual(self.erro(mail.salvar_config, b), "Pedido inválido.")
        self.assertEqual(self.erro(mail.salvar_config, {"porta": 0}), "Porta inválida: de 1 a 65535.")

    def test_ligar_exige_servidor_e_remetente(self):
        self.assertEqual(self.erro(mail.salvar_config, {"ligado": True}), "Para ligar o e-mail, preencha o servidor e o remetente.")
        self.erro(mail.salvar_config, dict(CFG_OK, remetente=""))
        self.erro(mail.salvar_config, dict(CFG_OK, host=" "))
        self.assertTrue(mail.salvar_config(CFG_OK)["ligado"])
        self.assertFalse(mail.salvar_config({"ligado": False, "host": ""})["ligado"], "desligado pode ficar sem servidor")

    def test_aceita_formatos(self):
        for r in ("demandas@empresa.com.br", "Central de demandas <demandas@empresa.com.br>", '"Central, PCP" <a@b.co>'):
            self.assertEqual(mail.salvar_config({"remetente": r})["remetente"], r)
        for link in ("http://192.168.0.20:8090", "https://central.empresa.com.br/", ""):
            self.assertEqual(mail.salvar_config({"link_base": link})["link_base"], link)
        for s in ("ssl", "nenhuma", "starttls"):
            self.assertEqual(mail.salvar_config({"seguranca": s})["seguranca"], s)

    def test_arquivo_ruim_fica_no_padrao(self):
        (self.dir / "email.json").write_text("{x", encoding="utf-8")
        self.assertFalse(mail.config()["ligado"])
        (self.dir / "email.json").write_text(json.dumps({"ligado": "sim", "porta": -1, "senha": "texto solto",
                                                         "instalacao": "AB"}), encoding="utf-8")
        b = mail._bruta()
        self.assertEqual((b["ligado"], b["porta"], b["senha"], b["instalacao"]), (False, 587, None, ""))
        (self.dir / "email.json").write_text("[1]", encoding="utf-8")
        self.assertEqual(mail._bruta()["porta"], 587)


class Senha(Base):
    @unittest.skipUnless(sys.platform == "win32", "DPAPI só existe no Windows")
    def test_dpapi_de_verdade(self):
        s = mail._protege("çãé senha")
        self.assertIn("dpapi", s)
        self.assertEqual(mail._desprotege(s), "çãé senha")

    def test_sem_dpapi_guarda_texto_e_avisa(self):
        with mock.patch.object(mail, "_dpapi", side_effect=AttributeError("windll")):
            self.assertEqual(mail._protege("abc"), {"texto": "abc"})
            mail.salvar_config({"senha": "abc"})
        c = mail.config()
        self.assertEqual((c["tem_senha"], c["senha_abre"], c["senha_texto"]), (True, True, True))

    def test_blob_que_nao_abre(self):
        self.assertIsNone(mail._desprotege({"dpapi": "não é base64!"}))
        with mock.patch.object(mail, "_dpapi", side_effect=OSError("outro usuário")):
            self.assertIsNone(mail._desprotege({"dpapi": "QUJD"}))
        for s in (None, "abc", {}, {"texto": 5}, {"dpapi": 5}):
            self.assertIsNone(mail._desprotege(s))
        self.assertEqual(mail._desprotege({"texto": "x"}), "x")
        (self.dir / "email.json").write_text(json.dumps({"senha": {"dpapi": "QUJD"}}), encoding="utf-8")
        with mock.patch.object(mail, "_dpapi", side_effect=OSError("outro PC")):
            c = mail.config()
        self.assertEqual((c["tem_senha"], c["senha_abre"]), (True, False), "a tela pede a senha de novo")


# ---------- mensagem ----------

class Montar(Base):
    CFG = dict(CFG_OK, instalacao="k7f3q9", link_base="http://192.168.0.20:8090/")

    def partes(self, msg):
        texto = msg.get_body(("plain",)).get_content()
        html = msg.get_body(("html",)).get_content()
        return texto, html

    def test_criada(self):
        item = dict(envio(), id="e1", cc=["carlos@empresa.com.br"])
        msg = mail.montar(item, self.CFG)
        self.assertEqual(msg["Subject"], "[SOL-1043] Corrigir solda")
        self.assertEqual(msg["From"], "Central de demandas <demandas@empresa.com.br>")
        self.assertEqual((msg["To"], msg["Cc"]), ("joao@empresa.com.br", "carlos@empresa.com.br"))
        self.assertEqual(msg["Message-ID"], "<SOL-1043.k7f3q9@empresa.com.br>")
        self.assertIsNone(msg["In-Reply-To"])
        self.assertEqual((msg["Auto-Submitted"], msg["X-Central-Demanda"]), ("auto-generated", "SOL-1043"))
        self.assertTrue(msg["Date"])
        texto, html = self.partes(msg)
        self.assertIn("Nova demanda para você", texto)
        self.assertIn("Prioridade: Alta", texto)
        self.assertIn("Prazo: " + mail._quando(T0 + 60 * MIN), texto)
        self.assertIn("Abrir a demanda: http://192.168.0.20:8090/#SOL-1043", texto)
        self.assertIn('href="http://192.168.0.20:8090/#SOL-1043"', html)
        self.assertIn("só abre dentro da rede da fábrica", texto)
        self.assertIn("Para não receber mais", html)

    def test_seguintes_no_mesmo_fio(self):
        msg = mail.montar(dict(envio(ev="done"), id="ab12cd34"), self.CFG)
        self.assertEqual(msg["Subject"], "[SOL-1043] Corrigir solda", "assunto idêntico")
        self.assertEqual(msg["Message-ID"], "<SOL-1043.ab12cd34.k7f3q9@empresa.com.br>")
        self.assertEqual((msg["In-Reply-To"], msg["References"]), ("<SOL-1043.k7f3q9@empresa.com.br>",) * 2)
        self.assertIsNone(msg["Cc"])
        self.assertIn("A demanda foi concluída", self.partes(msg)[0])
        for ev, frase in mail.EV_TEXTO.items():
            self.assertIn(frase, self.partes(mail.montar(dict(envio(ev=ev), id="x1"), self.CFG))[0])
        self.assertIn("Aviso da Central de demandas", self.partes(mail.montar(dict(envio(ev="outro"), id="x1"), self.CFG))[0])

    def test_escape_e_acentos(self):
        item = dict(envio(titulo='<script>alert("x")</script> & cia', desc="linha 1\nlinha <b>2</b>"), id="e1")
        msg = mail.montar(item, self.CFG)
        texto, html = self.partes(msg)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; cia", html)
        self.assertIn("linha 1<br>linha &lt;b&gt;2&lt;/b&gt;", html)
        self.assertIn('<script>alert("x")</script> & cia', texto, "o texto simples vai como está")
        bruto = mail.montar(dict(envio(titulo="Ação de manutenção"), id="e1"), self.CFG).as_bytes()
        self.assertIn(b"Subject: [SOL-1043] =?utf-8?", bruto, "assunto codificado (RFC 2047)")
        self.assertEqual(message_from_bytes(bruto, policy=policy.default)["Subject"], "[SOL-1043] Ação de manutenção")

    def test_sem_link_vazios_e_dominio(self):
        cfg = dict(self.CFG, link_base="")
        texto, html = self.partes(mail.montar(dict(envio(nota="", motivo=None, prazo=None), id="e1"), cfg))
        self.assertNotIn("Abrir a demanda", texto + html)
        self.assertNotIn("Observação", texto)
        self.assertNotIn("Motivo", texto)
        self.assertNotIn("Prazo", texto)
        self.assertEqual(mail._dominio({"remetente": ""}), "central-demandas.local")
        self.assertEqual(mail._dominio({}), "central-demandas.local")
        m = mail.montar(dict(envio(), id="e1"), dict(cfg, instalacao=""))
        self.assertEqual(m["Message-ID"], "<SOL-1043.central@empresa.com.br>")


# ---------- envio e erros ----------

class SMTPSimulado:
    def __init__(self):
        self.chamadas = []
        self.falha_envio = None
        self.falha_quit = None

    def _con(self, tipo, *a, **kw):
        s = mock.Mock()
        self.chamadas.append((tipo, a, kw, s))
        s.send_message.side_effect = self.falha_envio
        s.quit.side_effect = self.falha_quit
        return s

    def SMTP(self, *a, **kw):
        return self._con("SMTP", *a, **kw)

    def SMTP_SSL(self, *a, **kw):
        return self._con("SSL", *a, **kw)


class Enviar(Base):
    def test_starttls_login_e_quit(self):
        sim, msg = SMTPSimulado(), mail.montar(dict(envio(), id="e1"), CFG_OK)
        mail.enviar_um(msg, CFG_OK, "senha", smtp=sim)
        tipo, a, kw, s = sim.chamadas[0]
        self.assertEqual((tipo, a, kw), ("SMTP", ("smtp.empresa.com.br", 587), {"timeout": 20}))
        self.assertIsNotNone(s.starttls.call_args.kwargs["context"])
        s.login.assert_called_once_with("demandas@empresa.com.br", "senha")
        s.send_message.assert_called_once_with(msg)
        s.quit.assert_called_once_with()

    def test_ssl_nenhuma_e_sem_usuario(self):
        sim = SMTPSimulado()
        mail.enviar_um("m", dict(CFG_OK, seguranca="ssl", porta=465), None, smtp=sim)
        tipo, a, kw, s = sim.chamadas[0]
        self.assertEqual((tipo, a, kw["timeout"]), ("SSL", ("smtp.empresa.com.br", 465), 20))
        self.assertIsNotNone(kw["context"])
        s.login.assert_called_once_with("demandas@empresa.com.br", "")
        mail.enviar_um("m", dict(CFG_OK, seguranca="nenhuma", usuario=""), None, smtp=sim)
        s = sim.chamadas[1][3]
        s.starttls.assert_not_called()
        s.login.assert_not_called()
        s.send_message.assert_called_once_with("m")

    def test_quit_mesmo_com_erro(self):
        sim = SMTPSimulado()
        sim.falha_envio = smtplib.SMTPServerDisconnected("caiu")
        with self.assertRaises(smtplib.SMTPServerDisconnected):
            mail.enviar_um("m", CFG_OK, "x", smtp=sim)
        sim.chamadas[0][3].quit.assert_called_once_with()
        sim.falha_envio, sim.falha_quit = None, smtplib.SMTPServerDisconnected("já fechou")
        mail.enviar_um("m", CFG_OK, "x", smtp=sim)   # erro no quit não sobe
        sim.falha_quit = OSError("rede")
        mail.enviar_um("m", CFG_OK, "x", smtp=sim)

    def test_classifica(self):
        self.assertEqual(mail.classifica(smtplib.SMTPAuthenticationError(535, b"5.7.3 Authentication unsuccessful")),
                         ("auth", "535 5.7.3 Authentication unsuccessful"))
        self.assertEqual(mail.classifica(smtplib.SMTPRecipientsRefused({"a@x.com": (550, b"no such user")}))[0], "perm")
        self.assertEqual(mail.classifica(smtplib.SMTPRecipientsRefused({"a@x.com": (550, b"x"), "b@x.com": (451, b"y")}))[0], "temp")
        self.assertEqual(mail.classifica(smtplib.SMTPRecipientsRefused({}))[0], "temp")
        self.assertEqual(mail.classifica(smtplib.SMTPDataError(554, "rejeitada")), ("perm", "554 rejeitada"))
        self.assertEqual(mail.classifica(smtplib.SMTPResponseException(500, "x"))[0], "perm")
        self.assertEqual(mail.classifica(smtplib.SMTPResponseException(499, "x"))[0], "temp")
        self.assertEqual(mail.classifica(smtplib.SMTPDataError(421, "ocupado")), ("temp", "421 ocupado"))
        self.assertEqual(mail.classifica(TimeoutError("timed out")), ("temp", "TimeoutError: timed out"))
        self.assertEqual(mail.classifica(ConnectionRefusedError()), ("temp", "ConnectionRefusedError"))
        self.assertEqual(mail.classifica(smtplib.SMTPServerDisconnected()), ("temp", "SMTPServerDisconnected"))
        self.assertEqual(mail.classifica(ValueError("x")), ("temp", "ValueError"))
        self.assertEqual(len(mail.classifica(smtplib.SMTPDataError(554, "x" * 500))[1]), 200)
        self.assertEqual(mail.classifica(smtplib.SMTPDataError(554, "a\r\n  b"))[1], "554 a b")


# ---------- fila ----------

class Fila(Base):
    def test_desligado_ou_vazio_nao_guarda(self):
        self.assertEqual(mail.enfileirar([envio()], T0), 0)
        self.assertFalse((self.dir / "email-fila.json").exists())
        self.grava_cfg()
        self.assertEqual(mail.enfileirar([], T0), 0)
        self.assertFalse((self.dir / "email-fila.json").exists())

    def test_enfileira(self):
        self.grava_cfg()
        e = envio()
        e["cc"] = ["c@x.com"]
        self.assertEqual(mail.enfileirar([e, envio(dem="SOL-1044", para=())], T0), 1)
        f = self.fila()
        self.assertEqual(len(f["itens"]), 1)
        it = f["itens"][0]
        self.assertEqual({k: it[k] for k in ("dem", "ev", "para", "cc", "criado", "tent", "prox", "erro")},
                         {"dem": "SOL-1043", "ev": "created", "para": ["joao@empresa.com.br"], "cc": ["c@x.com"],
                          "criado": T0, "tent": 0, "prox": T0, "erro": ""})
        self.assertRegex(it["id"], r"^[0-9a-f]{8}$")
        self.assertEqual(it["dados"]["titulo"], "Corrigir solda")
        self.assertIsNone(f["pausada"])
        self.assertEqual(self.log(), [{"t": T0, "dem": "SOL-1044", "ev": "created", "para": [], "status": "sem_destinatario",
                                       "tent": 0, "erro": ""}])

    def test_so_sem_destinatario_nao_cria_fila(self):
        self.grava_cfg()
        self.assertEqual(mail.enfileirar([envio(para=())], T0), 0)
        self.assertFalse((self.dir / "email-fila.json").exists())
        self.assertEqual(len(self.log()), 1)

    def test_teto_da_fila(self):
        self.grava_cfg()
        with mock.patch.object(mail, "FILA_MAX", 2):
            mail.enfileirar([envio(dem="SOL-1"), envio(dem="SOL-2")], T0)
            mail.enfileirar([envio(dem="SOL-3")], T0 + 1)
        self.assertEqual([i["dem"] for i in self.fila()["itens"]], ["SOL-2", "SOL-3"])
        self.assertEqual([(i["dem"], i["status"], i["erro"]) for i in self.log()], [("SOL-1", "descartado", "fila cheia")])

    def test_teto_do_log(self):
        self.grava_cfg()
        with mock.patch.object(mail, "LOG_MAX", 3):
            for i in range(5):
                mail.enfileirar([envio(dem="SOL-%d" % i, para=())], T0)
        self.assertEqual([i["dem"] for i in self.log()], ["SOL-2", "SOL-3", "SOL-4"])

    def test_erro_de_disco_nao_sobe(self):
        self.grava_cfg()
        with mock.patch.object(mail.store, "atomic_write", side_effect=PermissionError("travado")), \
                mock.patch("sys.stderr") as err:
            self.assertEqual(mail.enfileirar([envio()], T0), 0)
        self.assertIn("não enfileirou", "".join(str(c) for c in err.write.call_args_list))

    def test_arquivos_ruins(self):
        (self.dir / "email-fila.json").write_text('{"itens": [1, {"sem": "id"}, {"id": "a1"}], "pausada": "x"}', encoding="utf-8")
        f = mail._le_fila()
        self.assertEqual((f["itens"], f["pausada"]), ([{"id": "a1"}], None))
        (self.dir / "email-log.json").write_text('{"itens": "x"}', encoding="utf-8")
        self.assertEqual(mail.estado(T0)["log"], [])
        self.assertEqual(mail.do_log(["SOL-1"]), {})


class Tarefa(Base):
    def setUp(self):
        super().setUp()
        self.grava_cfg(senha={"texto": "s3nha"})
        self.enviados = []
        self.falha = None

    def enviar(self, msg, cfg, senha):
        self.enviados.append((msg["X-Central-Demanda"], senha))
        if self.falha is not None:
            raise self.falha

    def roda(self, agora):
        mail.tarefa(agora, enviar=self.enviar)

    def test_envia_e_registra(self):
        mail.enfileirar([envio()], T0)
        self.roda(T0)
        self.assertEqual(self.enviados, [("SOL-1043", "s3nha")])
        self.assertEqual(self.fila()["itens"], [])
        self.assertEqual([(i["dem"], i["status"], i["tent"], i["t"]) for i in self.log()], [("SOL-1043", "ok", 1, T0)])
        self.assertEqual(mail._RODADA["t"], T0)

    def test_espera_crescente_e_desiste_na_sexta(self):
        mail.enfileirar([envio()], T0)
        self.falha = TimeoutError("timed out")
        agora = T0
        for n, espera in enumerate((1, 5, 15, 60, 180), 1):
            self.roda(agora)
            it = self.fila()["itens"][0]
            self.assertEqual((it["tent"], it["prox"], it["erro"]), (n, agora + espera * MIN, "TimeoutError: timed out"))
            self.roda(it["prox"] - 1)   # ainda não venceu
            self.assertEqual(len(self.enviados), n)
            agora = it["prox"]
        self.roda(agora)
        self.assertEqual(self.fila()["itens"], [])
        self.assertEqual([(i["status"], i["tent"], i["erro"]) for i in self.log()], [("falhou", 6, "TimeoutError: timed out")])

    def test_erro_permanente_sai_na_hora(self):
        mail.enfileirar([envio()], T0)
        self.falha = smtplib.SMTPRecipientsRefused({"joao@empresa.com.br": (550, b"no such user")})
        self.roda(T0)
        self.assertEqual(self.fila()["itens"], [])
        self.assertEqual([(i["status"], i["tent"]) for i in self.log()], [("falhou", 1)])

    def test_senha_recusada_pausa_a_fila(self):
        mail.enfileirar([envio(dem="SOL-1"), envio(dem="SOL-2")], T0)
        self.falha = smtplib.SMTPAuthenticationError(535, b"Authentication unsuccessful")
        self.roda(T0)
        self.assertEqual(len(self.enviados), 1, "não insiste com a senha errada")
        f = self.fila()
        self.assertEqual(f["pausada"], {"t": T0, "erro": "535 Authentication unsuccessful"})
        self.assertEqual([(i["dem"], i["tent"], i["erro"]) for i in f["itens"]],
                         [("SOL-1", 0, "535 Authentication unsuccessful"), ("SOL-2", 0, "")])
        self.falha = None
        self.roda(T0 + 10 * MIN)
        self.assertEqual(len(self.enviados), 1, "pausada: nada sai até retomar")
        self.assertEqual(mail.estado(T0)["pausada"]["erro"], "535 Authentication unsuccessful")

    def test_ritmo_por_rodada(self):
        mail.enfileirar([envio(dem="SOL-%d" % i) for i in range(3)], T0)
        with mock.patch.object(mail, "RITMO", 2):
            self.roda(T0)
        self.assertEqual([e[0] for e in self.enviados], ["SOL-0", "SOL-1"])
        self.assertEqual([i["dem"] for i in self.fila()["itens"]], ["SOL-2"])

    def test_desligado_nao_envia(self):
        mail.enfileirar([envio()], T0)
        self.grava_cfg(ligado=False)
        self.roda(T0)
        self.assertEqual(self.enviados, [])
        self.assertEqual(mail._RODADA["t"], T0)

    def test_item_limpo_durante_o_envio(self):
        mail.enfileirar([envio()], T0)

        def limpa(msg, cfg, senha):
            (self.dir / "email-fila.json").write_text('{"v": 1, "itens": []}', encoding="utf-8")

        mail.tarefa(T0, enviar=limpa)
        self.assertEqual(self.log(), [], "o que a tela limpou não vira registro")

    def test_estado_e_do_log(self):
        mail.enfileirar([envio(dem="SOL-1"), envio(dem="SOL-2"), envio(dem="SOL-3")], T0)
        self.falha = smtplib.SMTPDataError(554, "spam")
        with mock.patch.object(mail, "RITMO", 1):
            self.roda(T0)
        self.falha = TimeoutError()
        with mock.patch.object(mail, "RITMO", 1):
            self.roda(T0)
        e = mail.estado(T0 + 1000)
        self.assertEqual((e["pendentes"], e["tentando"], e["proxima"], e["falhas_24h"], e["pausada"], e["ultima_rodada"]),
                         (2, 1, T0, 1, None, T0))
        self.assertEqual([(i["dem"], i["status"]) for i in e["log"]], [("SOL-1", "falhou")])
        self.assertEqual(mail.estado(T0 + 86400000)["falhas_24h"], 0, "falha de mais de 24 h não conta")
        self.assertEqual(mail.do_log(["SOL-1", "SOL-9"]), {"SOL-1": [{"t": T0, "ev": "created",
                                                                    "para": ["joao@empresa.com.br"], "status": "falhou"}]})
        with mock.patch.object(mail, "_agora", return_value=T0 + 5):
            self.assertEqual(mail.estado()["falhas_24h"], 1)

    def test_log_do_estado_mais_novo_primeiro(self):
        for i in range(25):
            mail.enfileirar([envio(dem="SOL-%d" % i, para=())], T0 + i)
        log = mail.estado(T0)["log"]
        self.assertEqual((len(log), log[0]["dem"], log[-1]["dem"]), (20, "SOL-24", "SOL-5"))


class Contrato(Base):
    """Constantes, textos e limites que a mutação mostrou sem teste."""

    def test_constantes(self):
        self.assertEqual((mail.FILA_MAX, mail.LOG_MAX, mail.RITMO, mail.DESC_MAX, mail.PARA_MAX, mail.TIMEOUT, mail.ERRO_MAX),
                         (500, 2000, 20, 400, 20, 20, 200))
        self.assertEqual(mail.ESPERAS_MIN, (1, 5, 15, 60, 180))
        self.assertEqual(mail.FILA_SETOR, ("setor_ou_pessoas", "so_setor", "pessoas"))
        self.assertEqual(mail.EV_TEXTO, {
            "created": "Nova demanda para você", "started": "A demanda foi aceita e começou",
            "done": "A demanda foi concluída", "nudge": "Cobrança: pediram atenção a esta demanda",
            "late": "A demanda passou do prazo", "comment": "Novo comentário na demanda",
            "canc": "A demanda foi cancelada"})
        self.assertEqual({k: v for k, v in mail.config().items() if k in ("host", "usuario", "remetente", "link_base")},
                         {"host": "", "usuario": "", "remetente": "", "link_base": ""})
        self.assertEqual(RODADA0, {"t": None})
        outro = mail.montar(dict(envio(ev="outro"), id="x1"), CFG_OK).get_body(("plain",)).get_content()
        self.assertTrue(outro.startswith("Aviso da Central de demandas\n\nSolicitação:"))

    def test_mensagens_de_erro(self):
        casos = [({"ligado": 1}, "Ligado/desligado inválido."), ({"copia_solicitante": 1}, "Opção de cópia inválida."),
                 ({"descricao": 1}, "Opção da descrição inválida."),
                 ({"host": "a b"}, "Servidor inválido: use só o nome, como smtp.empresa.com.br."),
                 ({"seguranca": "x"}, "Segurança inválida."), ({"usuario": 5}, "Usuário inválido."),
                 ({"remetente": "x"}, "Remetente inválido: use demandas@empresa.com.br ou Central de demandas "
                                      "<demandas@empresa.com.br>."),
                 ({"link_base": "x"}, "Endereço da Central inválido: use algo como http://192.168.0.20:8090."),
                 ({"fila_setor": "x"}, "Destino da fila do setor inválido."), ({"eventos": 1}, "Eventos inválidos."),
                 ({"eventos": {"done": 1}}, "Eventos inválidos."), ({"senha": 1}, "Senha inválida.")]
        for body, msg in casos:
            self.assertEqual(self.erro(mail.salvar_config, body), msg)

    def test_limites_aceitos(self):
        for porta in (1, 65535):
            self.assertEqual(mail.salvar_config({"porta": porta})["porta"], porta)
        for fila in mail.FILA_SETOR:
            self.assertEqual(mail.salvar_config({"fila_setor": fila})["fila_setor"], fila)
        self.assertEqual(mail.salvar_config({"usuario": "u" * 254})["usuario"], "u" * 254)
        self.assertEqual(mail.salvar_config({"usuario": "nome com espaço"})["usuario"], "nome com espaço")
        self.erro(mail.salvar_config, {"usuario": "a\tb"})
        r = "Xavier " + "x" * (300 - 7 - 12) + " <x@a.co.br>"
        self.assertEqual(len(r), 300)
        self.assertEqual(mail.salvar_config({"remetente": r})["remetente"], r)
        self.erro(mail.salvar_config, {"remetente": "X" + r})
        self.assertTrue(mail.salvar_config({"senha": "s" * 500})["tem_senha"])
        self.assertEqual(json.loads((self.dir / "email.json").read_text(encoding="utf-8"))["v"], 1)

    def test_instalacao_sorteada_so_com_letras_e_numeros(self):
        with mock.patch.object(mail.secrets, "choice", side_effect=lambda s: s[0]):
            mail.salvar_config({"host": "smtp.x.com"})
        self.assertEqual(mail._bruta()["instalacao"], "aaaaaa")

    def test_quando_e_relogio(self):
        ms = int(__import__("time").mktime((2026, 10, 28, 15, 40, 0, 0, 0, -1)) * 1000)
        self.assertEqual(mail._quando(ms), "28/10/2026 15:40")
        self.assertEqual(mail._quando(None), "")
        self.grava_cfg()
        antes = int(__import__("time").time() * 1000)
        mail.enfileirar([envio()])
        self.assertTrue(antes <= self.fila()["itens"][0]["criado"] <= antes + 5000)

    @unittest.skipUnless(sys.platform == "win32", "DPAPI só existe no Windows")
    def test_dpapi_recusa_blob_ruim(self):
        with self.assertRaisesRegex(OSError, "^DPAPI recusou$"):
            mail._dpapi(b"isto nao e um blob", False)

    def test_corta_bytes_ruins(self):
        self.assertEqual(mail._corta(b"\xff abc"), "� abc")
        self.assertEqual(mail.classifica(smtplib.SMTPRecipientsRefused({"a@x.com": (550, b"um"), "b@x.com": (500, b"dois")})),
                         ("perm", "a@x.com: 550 um; b@x.com: 500 dois"))


class Corpo(Base):
    CFG = dict(CFG_OK, instalacao="k7f3q9", link_base="http://central.example/BOX")

    def test_texto_exato(self):
        item = dict(envio(prazo=None, desc="linha 1\nlinha 2"), id="e1", cc=["c@x.com", "d@x.com"],
                    para=["a@x.com", "b@x.com"])
        msg = mail.montar(item, self.CFG)
        self.assertEqual((msg["To"], msg["Cc"]), ("a@x.com, b@x.com", "c@x.com, d@x.com"))
        self.assertEqual(msg.get_body(("plain",)).get_content(),
                         "Nova demanda para você\n\nSolicitação: SOL-1043\nTítulo: Corrigir solda\nDe: Montagem · Carlos\n"
                         "Para: Solda · João\nPrioridade: Alta\nMotivo: Defeito de qualidade\nTipo: Demanda\nPor: Carlos\n"
                         "Descrição: linha 1\nlinha 2\n\nAbrir a demanda: http://central.example/BOX/#SOL-1043\n"
                         "(o link só abre dentro da rede da fábrica)\n\nE-mail automático da Central de demandas. Para não "
                         "receber mais, peça ao escritório para tirar seu e-mail do cadastro.\n")
        texto = mail.montar(dict(envio(nota="feito"), id="e1"), dict(self.CFG, link_base="")).get_body(("plain",)).get_content()
        self.assertIn("\nObservação: feito\n", texto)
        self.assertTrue(texto.endswith("Descrição: Trinca no cordão\n\nE-mail automático da Central de demandas. Para não "
                                       "receber mais, peça ao escritório para tirar seu e-mail do cadastro.\n"))

    def test_html_partes(self):
        html = mail.montar(dict(envio(), id="e1"), self.CFG).get_body(("html",)).get_content()
        self.assertTrue(html.startswith('<!doctype html><html><body style="margin:0;padding:16px;background:#f3f5f9;'
                                        'font-family:Segoe UI,Arial,sans-serif"><table role="presentation" width="600"'))
        self.assertTrue(html.rstrip("\n").endswith("</p></td></tr></table></body></html>"))
        for trecho in ('border-radius:12px;padding:20px"><tr><td><p style="margin:0 0 4px;color:#5b6478;font-size:13px">'
                       'Central de demandas</p><h1 style="margin:0 0 14px;font-size:20px;color:#111827">Nova demanda para '
                       'você</h1><table role="presentation" style="font-size:14px',
                       '<table role="presentation" style="font-size:14px;border-collapse:collapse"><tr><td style="padding:4px'
                       ' 12px 4px 0;color:#5b6478;vertical-align:top;white-space:nowrap">Solicitação</td><td style="padding'
                       ':4px 0;color:#111827">SOL-1043</td></tr><tr><td',
                       '</td></tr></table><p style="margin:18px 0 4px"><a href="http://central.example/BOX/#SOL-1043" '
                       'style="background:#0C1224;color:#ffffff;padding:10px 16px;border-radius:8px;text-decoration:none;'
                       'font-weight:bold">Abrir a demanda</a></p><p style="margin:0;color:#8a93a6;font-size:12px">O link só'
                       ' abre dentro da rede da fábrica.</p><p style="margin:20px 0 0;color:#8a93a6;font-size:12px">E-mail '
                       'automático da Central de demandas.'):
            self.assertIn(trecho, html)
        sem = mail.montar(dict(envio(), id="e1"), dict(self.CFG, link_base="")).get_body(("html",)).get_content()
        self.assertIn('</td></tr></table><p style="margin:20px 0 0;color:#8a93a6;font-size:12px">E-mail', sem)

    def test_assunto_sem_titulo_e_data_local(self):
        from email.utils import parsedate_to_datetime
        import datetime
        msg = mail.montar(dict(envio(titulo=None), id="e1"), self.CFG)
        self.assertEqual(msg["Subject"].rstrip(), "[SOL-1043]")
        self.assertNotIn("X", msg["Subject"])
        self.assertEqual(parsedate_to_datetime(msg["Date"]).utcoffset(), datetime.datetime.now().astimezone().utcoffset())


class FilaDetalhes(Base):
    def setUp(self):
        super().setUp()
        self.grava_cfg(senha={"texto": "x"})

    def test_enfileira_varios_e_sem_destinatario_no_meio(self):
        self.assertEqual(mail.enfileirar([envio(dem="SOL-1", para=()), envio(dem="SOL-2"), envio(dem="SOL-3")], T0), 2)
        self.assertEqual([i["dem"] for i in self.fila()["itens"]], ["SOL-2", "SOL-3"])
        self.assertEqual((self.fila()["v"], json.loads((self.dir / "email-log.json").read_text(encoding="utf-8"))["v"]), (1, 1))
        e = envio(dem="SOL-4")
        e["cc"] = ["c@x.com"]
        e["para"] = []
        mail.enfileirar([e], T0)
        self.assertEqual(self.log()[-1]["para"], ["c@x.com"], "o registro mostra para quem iria, cópia inclusive")

    def test_mensagem_de_erro_de_disco(self):
        import io
        with mock.patch.object(mail.store, "atomic_write", side_effect=PermissionError("travado")), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            mail.enfileirar([envio()], T0)
        self.assertEqual(err.getvalue(), "[e-mail] não enfileirou: PermissionError('travado')\n")

    def test_ok_registra_sem_erro_e_segue_depois_de_um_limpo(self):
        mail.enfileirar([envio(dem="SOL-1"), envio(dem="SOL-2")], T0)
        primeiro = self.fila()["itens"][0]["id"]
        enviados = []

        def enviar(msg, cfg, senha):
            enviados.append(msg["X-Central-Demanda"])
            if msg["X-Central-Demanda"] == "SOL-1":   # a tela limpou este enquanto ele saía
                f = self.fila()
                f["itens"] = [i for i in f["itens"] if i["id"] != primeiro]
                (self.dir / "email-fila.json").write_text(json.dumps(f), encoding="utf-8")

        mail.tarefa(T0, enviar=enviar)
        self.assertEqual(enviados, ["SOL-1", "SOL-2"])
        self.assertEqual([(i["dem"], i["status"], i["erro"]) for i in self.log()], [("SOL-2", "ok", "")])

    def test_duas_falhas_temporarias_na_mesma_rodada(self):
        mail.enfileirar([envio(dem="SOL-1"), envio(dem="SOL-2")], T0)

        def falha(msg, cfg, senha):
            raise TimeoutError()

        mail.tarefa(T0, enviar=falha)
        self.assertEqual([(i["dem"], i["tent"]) for i in self.fila()["itens"]], [("SOL-1", 1), ("SOL-2", 1)])

    def test_do_log_so_das_pedidas(self):
        mail.enfileirar([envio(dem="SOL-1", para=()), envio(dem="SOL-2", para=())], T0)
        self.assertEqual(list(mail.do_log(["SOL-1"])), ["SOL-1"])


# ---------- servidor SMTP falso de verdade ----------

class Atende(socketserver.StreamRequestHandler):
    def handle(self):
        def w(s):
            self.wfile.write((s + "\r\n").encode("ascii"))

        w("220 falso ESMTP")
        dados, buf, rcpts = False, [], []
        for raw in self.rfile:
            linha = raw.decode("utf-8", "replace").rstrip("\r\n")
            if dados:
                if linha == ".":
                    self.server.msgs.append({"rcpts": list(rcpts), "dados": "\r\n".join(buf)})
                    dados, buf, rcpts = False, [], []
                    w("250 aceito")
                else:
                    buf.append(linha[1:] if linha.startswith("..") else linha)
                continue
            cmd = linha[:4].upper()
            if cmd in ("EHLO", "HELO"):
                w("250 falso")
            elif cmd in ("MAIL", "RSET", "NOOP"):
                w("250 OK")
            elif cmd == "RCPT":
                rcpts.append(linha)
                w(self.server.rcpt)
            elif cmd == "DATA":
                dados = True
                w("354 manda")
            elif cmd == "QUIT":
                w("221 tchau")
                return
            else:
                w("502 não sei")


class SMTPFalso(socketserver.ThreadingTCPServer):
    daemon_threads = True

    def __init__(self, rcpt="250 OK"):
        super().__init__(("127.0.0.1", 0), Atende)
        self.msgs, self.rcpt = [], rcpt


class Integracao(Base):
    def setUp(self):
        super().setUp()
        self.smtp = SMTPFalso()
        threading.Thread(target=self.smtp.serve_forever, daemon=True).start()
        self.grava_cfg(host="127.0.0.1", porta=self.smtp.server_address[1], seguranca="nenhuma", usuario="")

    def tearDown(self):
        self.smtp.shutdown()
        self.smtp.server_close()
        super().tearDown()

    def test_fluxo_completo(self):
        self.assertNotEqual(self.smtp.server_address[1], 8090)
        mail.enfileirar([envio(titulo="Solda <urgente> ç")], T0)
        mail.tarefa(T0)
        self.assertEqual(len(self.smtp.msgs), 1)
        m = message_from_bytes(self.smtp.msgs[0]["dados"].encode("utf-8"), policy=policy.default)
        self.assertEqual(m["Subject"], "[SOL-1043] Solda <urgente> ç")
        self.assertEqual(m["Message-ID"], "<SOL-1043.k7f3q9@empresa.com.br>")
        self.assertIn("joao@empresa.com.br", self.smtp.msgs[0]["rcpts"][0])
        self.assertEqual([i["status"] for i in self.log()], ["ok"])

    def test_destinatario_recusado(self):
        self.smtp.rcpt = "550 no such user"
        mail.enfileirar([envio()], T0)
        mail.tarefa(T0)
        self.assertEqual([(i["status"], i["erro"][:3]) for i in self.log()], [("falhou", "joa")])

    def test_servidor_fora_tenta_de_novo(self):
        porta = self.smtp.server_address[1]
        self.smtp.shutdown()
        self.smtp.server_close()
        self.smtp = SMTPFalso()
        threading.Thread(target=self.smtp.serve_forever, daemon=True).start()
        self.grava_cfg(host="127.0.0.1", porta=porta, seguranca="nenhuma", usuario="")   # porta antiga: ninguém ouvindo
        mail.enfileirar([envio()], T0)
        mail.tarefa(T0)
        it = self.fila()["itens"][0]
        self.assertEqual((it["tent"], it["prox"]), (1, T0 + MIN))


if __name__ == "__main__":
    unittest.main()
