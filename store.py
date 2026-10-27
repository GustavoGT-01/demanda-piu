"""Gravação segura dos arquivos de dados (JSON) em data/.

Funções de gravação que o demandas_store.py usa: temporário com fsync,
o atual vira .bak, e a leitura recupera do .bak se o principal estiver corrompido. Só isso fica aqui.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def data_dir() -> Path:
    path = Path(os.environ.get("DEMANDAS_DATA") or ROOT / "data")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _replace(src: Path, dst: Path, temporario: bool = False) -> None:
    """temporario=True: src é um .tmp, apagado se a troca falhar. Arquivo de dados nunca é apagado aqui."""
    # No Windows, antivírus/indexador segurando o arquivo dá PermissionError passageiro.
    for wait in (0.05, 0.1, 0.2, 0.2, None):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if wait is None:
                if temporario:
                    _remove(src)  # não deixa .tmp órfão
                raise
            time.sleep(wait)


def _remove(path: Path) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _tmp_file(path: Path, data: bytes) -> Path:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    return tmp


def _write_file(path: Path, data: bytes) -> None:
    _replace(_tmp_file(path, data), path, temporario=True)


def atomic_write(path: Path, text: str) -> None:
    """Temporário com fsync; o atual vira .bak e o temporário vira o atual. Dois renomes, sem copiar o antigo.
    Entre os dois o principal não existe: _read_safe então lê o .bak sem gravar nada."""
    tmp = _tmp_file(path, text.encode("utf-8"))
    if path.exists():
        try:
            _replace(path, path.with_name(path.name + ".bak"))
        except OSError:
            _remove(tmp)
            raise
    _replace(tmp, path, temporario=True)


def _read_safe(path: Path):
    """None só quando não há arquivo nenhum. Corrompido sem .bak válido levanta erro (nunca vazio em silêncio)."""
    bak = path.with_name(path.name + ".bak")
    if not path.exists() and not bak.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        try:
            text = bak.read_text(encoding="utf-8")
            doc = json.loads(text)
        except (OSError, ValueError):
            # o arquivo ruim fica no lugar: renomear faria a próxima leitura achar "vazio"
            raise ValueError("Arquivo de dados corrompido e sem cópia válida: %s" % path.name)
        if not path.exists():
            # entre os dois renomes do atomic_write (ou queda ali): vale o .bak, e gravar aqui pisaria no .tmp
            # do escritor; a próxima gravação recria o principal
            return doc
        try:
            path.rename(path.with_name("%s.corrompido-%d" % (path.name, int(time.time()))))
        except FileNotFoundError:
            return doc   # um escritor trocou o arquivo agora mesmo
        # promove a cópia a principal: sem isso a 2ª leitura veria rev 0 e o .bak seria sobrescrito
        _write_file(path, text.encode("utf-8"))
        return doc


