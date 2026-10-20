"""序列化单点：一切 JSON / 文本产物落盘只经这里（K11）。

为什么必须单点：多个子命令各写各的 `open()+json.dump()`，迟早出现"一个带 BOM 一个不带"
"一个排序一个不排"的漂移，"逐字节一致"的承诺就挂在默认值上而不是我们的决定上。

冻结约定（任何产物都必须满足）：
- `json.dumps(sort_keys=True, ensure_ascii=False, indent=2)` —— `ensure_ascii=False` 是中文项目的必选项
- LF 行尾（显式 `newline="\\n"`，不交给平台默认）
- 结尾换行恰好一个
- 原子写（临时文件 + `os.replace`），中断不留半个产物

例外只有一个，且是**有意的**：`write_text_raw` 用于 M1 的逐段快照。快照是**被审计的对象**，
把它的 CRLF 归一成 LF 就等于在比较之前先替它"修好"了一次——那正是 D6/K1 要禁止的失真。
所以快照走 raw，报告与元数据走上面的冻结约定。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

ENCODING = "utf-8"
NEWLINE = "\n"


def dumps_json(data: Any) -> str:
    """规范 JSON 文本（唯一实现）。"""
    return json.dumps(data, sort_keys=True, ensure_ascii=False, indent=2) + NEWLINE


def _atomic_write(path: Path, text: str, *, newline: str = NEWLINE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=path.suffix or ".tmp")
    try:
        with os.fdopen(fd, "w", encoding=ENCODING, newline=newline) as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json(path: str | os.PathLike[str], data: Any) -> Path:
    target = Path(path)
    _atomic_write(target, dumps_json(data))
    return target


def write_text(path: str | os.PathLike[str], text: str) -> Path:
    """写文本产物：行尾归一为 LF，结尾恰好一个换行。"""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.endswith("\n"):
        normalized += "\n"
    target = Path(path)
    _atomic_write(target, normalized)
    return target


def write_text_raw(path: str | os.PathLike[str], text: str) -> Path:
    """逐字节写文本，**不做任何归一**（快照专用，K1）。

    与 `write_text` 的唯一区别是"一个字节都不许动"：CRLF / 结尾无换行 / 尾随空格
    都可能正是被审计的失真形态本身。`newline=""` 关掉平台翻译，编码仍固定 UTF-8。
    """
    target = Path(path)
    _atomic_write(target, text, newline="")
    return target
