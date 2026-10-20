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
    """一张 CSV 表的原文视图。`header` 与 `rows` 都是**原始字符串**，不做类型推断。"""

    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

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
    """读原文（UTF-8 且保留 BOM 信息：`utf-8` 会把 BOM 读成 `\\ufeff`，这正是我们要检出的）。"""
    return Path(path).read_text(encoding="utf-8", newline="")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_csv_text(text: str) -> CsvTable:
    """按 RFC4180 切分，保留空串 / 缺格的区别（缺格 = 行短，空串 = `""`）。"""
    reader = csv.reader(io.StringIO(text, newline=""))
    records = [tuple(cell for cell in record) for record in reader]
    if not records:
        return CsvTable(header=(), rows=())
    return CsvTable(header=records[0], rows=tuple(records[1:]))


def read_csv(path: str | Path) -> tuple[CsvTable, str]:
    """返回 (表视图, 原文)。调用方要哈希时用原文，不要重新序列化一遍。"""
    text = read_text(path)
    return parse_csv_text(text), text
