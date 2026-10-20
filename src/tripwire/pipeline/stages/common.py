"""阶段实现的公共件：文本 ↔ 表格的**互不共享**转换纪律与书写助手。

本模块刻意不含任何引擎 import：依赖在各自 stage 文件里**函数内**导入，
这样"缺 pandas 的机器上仍能 import 整个包并跑 json_sqlite 通道"成立。

三条共用的书写约定（各 stage 必须遵守，否则跨 stage 的文本比较会出现假差异）：
1. 输出行尾一律 LF（Excel 例外：它的 CRLF 是**被测行为本身**，不许替它归一）；
2. 引号按 RFC4180 最小引号（`csv.QUOTE_MINIMAL`）；
3. 浮点回写用**可逆最短表示**，整数型浮点写成整数——读取环节不许再引入一次格式化损失。
"""

from __future__ import annotations

import csv
import io
import math
import re
from typing import Iterable, Sequence

from tripwire.pipeline.model import ColumnMeta

#: 整数形（不认前导零，见 `cell_kind`）
_INT_RE = re.compile(r"^[+-]?[0-9]+$")
#: 小数 / 科学计数形
_NUM_RE = re.compile(r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$")


def rows_to_text(rows: Iterable[Sequence[str]]) -> str:
    """按 RFC4180 写 CSV 文本（LF 行尾、最小引号、UTF-8 由调用方保证）。"""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    for row in rows:
        writer.writerow(list(row))
    return buffer.getvalue()


def columns_from_header(header: Sequence[str], declared: Sequence[str | None] | None = None) -> tuple[ColumnMeta, ...]:
    """表头 -> `ColumnMeta`。`declared` 不给则该格式无类型声明（CSV 就是这种）。"""
    if not declared:
        return tuple(ColumnMeta(name=name, declared_type=None) for name in header)
    return tuple(
        ColumnMeta(name=name, declared_type=declared[index] if index < len(declared) else None)
        for index, name in enumerate(header)
    )


def format_float(value: float) -> str:
    """浮点回写：整数型浮点写整数，其余写**可逆最短表示**。

    为什么不统一用 `%.16g`：`%.16g` 会在**读取侧**再截一次有效位，
    于是"openpyxl 写盘时的损失"与"我们打印时的损失"混成一条，归因就假了。
    """
    if math.isfinite(value) and value == int(value) and abs(value) < 1e16:
        return str(int(value))
    return repr(value)


def cell_kind(text: str) -> str:
    """把单元格文本判成 `int` / `float` / `text` / `empty`（**写入容器前**的类型决策）。

    这条启发式是**我们自己的代码**，所以它必须在文档里写死、在测试里钉住：
    - `""` -> empty（不写值，留空格）
    - 整数形且**无前导零**（`007` 例外保留为文本）-> int
    - 小数 / 科学计数形 -> float
    - 其余（含 `02114`、`00123-4567`、`1900-02-29`）-> text，原样保留

    宁可把可疑值留成文本：把 `02114` 判成数字的损失属于**语料**，不属于被审计引擎。
    """
    if text == "":
        return "empty"
    if _INT_RE.match(text):
        digits = text.lstrip("+-")
        if len(digits) > 1 and digits[0] == "0":
            return "text"
        return "int"
    if _NUM_RE.match(text):
        return "float"
    return "text"


def coerce(text: str) -> int | float | str | None:
    """按 `cell_kind` 转成容器值（`empty` -> None）。"""
    kind = cell_kind(text)
    if kind == "empty":
        return None
    if kind == "int":
        return int(text)
    if kind == "float":
        return float(text)
    return text


def render_cell(value: object) -> str:
    """容器值 -> 单元格文本（`None` -> 空串）。与 `coerce` 互为逆，便于测试 round-trip。"""
    if value is None:
        return ""
    if isinstance(value, bool):  # bool 是 int 的子类，必须先挡
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format_float(value)
    return str(value)


__all__ = [
    "cell_kind",
    "coerce",
    "columns_from_header",
    "format_float",
    "render_cell",
    "rows_to_text",
]
