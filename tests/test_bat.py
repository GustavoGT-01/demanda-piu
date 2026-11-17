"""Scripts .bat: um `)` solto num echo dentro de um bloco `if (...)` fecha o bloco antes da hora e o cmd.exe aborta
com "foi inesperado neste momento" (foi o que quebrou o iniciar.bat). O teste confere isso sem precisar do cmd."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOLTO = re.compile(r"(?<!\^)\)")


def echos_com_parentese_solto(texto: str) -> list:
    """(linha, texto) dos echo dentro de bloco com `)` sem `^`. Bloco = linha terminada em `(` até o `)` sozinho."""
    achados, fundo = [], 0
    for n, linha in enumerate(texto.splitlines(), 1):
        t = linha.strip()
        if fundo and re.match(r"echo\b", t, re.I) and SOLTO.search(t):
            achados.append((n, t))
        if t.endswith("(") and not t.lower().startswith("rem"):
            fundo += 1
        elif t.startswith(")") and fundo:
            fundo -= 1
    return achados


class Bat(unittest.TestCase):
    def test_nenhum_echo_com_parentese_solto_em_bloco(self):
        arquivos = sorted(ROOT.glob("*.bat"))
        self.assertTrue(arquivos)
        for f in arquivos:
            with self.subTest(arquivo=f.name):
                self.assertEqual(echos_com_parentese_solto(f.read_text(encoding="utf-8", errors="replace")), [])

    def test_o_detector_pega_o_caso_que_quebrou(self):
        ruim = 'if not errorlevel 1 (\n  echo ja esta ligada (tarefa). Abrindo...\n  exit /b 0\n)\n'
        self.assertEqual(echos_com_parentese_solto(ruim), [(2, "echo ja esta ligada (tarefa). Abrindo...")])
        bom = 'if not errorlevel 1 (\n  echo ligada ^(tarefa^). Abrindo...\n)\necho fora do bloco (vale)\n'
        self.assertEqual(echos_com_parentese_solto(bom), [])
        # o else conta como continuação do bloco, não como saída dele
        self.assertEqual(echos_com_parentese_solto("if x (\n  echo a\n) else (\n  echo b)\n)\n"), [(4, "echo b)")])


if __name__ == "__main__":
    unittest.main()
