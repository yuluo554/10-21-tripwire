"""CSV 原文读取：只做文本切分，**不经 pandas**（K1）。

为什么不能经 pandas：存 DataFrame 或经 DataFrame 落盘，等于在比较之前先做了一次格式转换，
审计器自己就成了失真源。M1 的快照与 M2 的比对都只能看字节/字符。
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CsvTable:
    """一张 CSV 表的原文视图。`header` 与 `rows` 都是**原始字符串**，不做类型推断。

    `text` 保留"这张视图是从哪段原文切出来的"。M2 的 `--batch` 需要把**原文**交给
    分块读取器；若从 `rows` 重新序列化一遍，比较前就替它归一了一次（K1），
    所以原文必须随视图一起走，而不是回头再拼。
    """

    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    text: str | None = None

    @property
    def cols(self) -> int:
        return len(self.header)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def column_index(self, name: str) -> int:
        try:
            return self.header.index(name)
        except ValueError as error:
            raise KeyError(name) from error

    def cell(self, row_index: int, col_index: int) -> str:
        row = self.rows[row_index]
        return row[col_index] if col_index < len(row) else ""


def read_text(path: str | Path) -> str:
    """读原文（UTF-8 且保留 BOM 信息：`utf-8` 会把 BOM 读成 `\\ufeff`，这正是我们要检出的）。

    `newline=""` 不开通用换行翻译：CRLF 与 LF 在**快照字节**上是两回事，先归一就再也测不出
    "换行被改"这类差异。注意 `Path.read_text(newline=)` 是 3.13 才有的参数，本包承诺 3.10+，
    故必须走 `open()`。
    """
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return handle.read()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_csv_text(text: str) -> CsvTable:
    """按 RFC4180 切分，保留空串 / 缺格的区别（缺格 = 行短，空串 = `""`）。"""
    reader = csv.reader(io.StringIO(text, newline=""))
    records = [tuple(cell for cell in record) for record in reader]
    if not records:
        return CsvTable(header=(), rows=(), text=text)
    return CsvTable(header=records[0], rows=tuple(records[1:]), text=text)


def read_csv(path: str | Path) -> tuple[CsvTable, str]:
    """返回 (表视图, 原文)。调用方要哈希时用原文，不要重新序列化一遍。"""
    text = read_text(path)
    return parse_csv_text(text), text
