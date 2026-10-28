"""跨模块共享的文件存储工具：原子写，断电/崩溃不产生半截文件。"""

from __future__ import annotations

import json
from pathlib import Path


def atomic_write_text(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def atomic_write_json(path: Path, payload) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


def read_json(path: Path, default):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
