"""`json_sqlite_csv` 阶段：CSV -> JSON 数组 -> SQLite 表 -> 查询 -> CSV（纯 stdlib）。

为什么这条通道有价值：SQLite 的**类型亲和**会按列声明把 `02114` 吃成 `2114`、`19.90` 吃成 `19.9`
（F8）。而且这不是"SQLite 的错"——F8 的反例证明 `affinity NONE` 的列原样保留文本，
所以差异必须归因到**具体列声明**，不能笼统说"SQLite 丢精度"。

列声明取 `NUMERIC`（不是 `TEXT`，也不是不给声明）：这是"把 CSV 当表灌进 SQLite"最常见的
默认写法，也是唯一能产生可观测亲和的写法。声明写死在本文件常量里，文档同步。

JSON 这一跳用 `json.dumps(ensure_ascii=False)` —— 中文与组合字符必须按原文进 JSON，
否则 `é`(NFC) 与 `e`+U+0301(NFD) 会在这一跳被"顺带"归一，归因就乱了。
"""

from __future__ import annotations

import json
import sqlite3

from tripwire.pipeline.errors import StageFailed
from tripwire.pipeline.model import ColumnMeta, RuntimeMeta, StageResult
from tripwire.pipeline.stages.common import rows_to_text

STAGE_NAME = "json_sqlite_csv"

#: 列声明（写死：改它等于改被测行为，必须同步 `docs/pipeline-schema.md`）
COLUMN_TYPE = "NUMERIC"


def _quote(name: str) -> str:
    """SQL 标识符引用：双引号，内部双引号翻倍（列名来自用户 CSV，不可拼接裸标识符）。"""
    return '"' + name.replace('"', '""') + '"'


def run(text: str) -> StageResult:
    """CSV -> JSON -> SQLite -> SELECT -> CSV，返回 SELECT 结果的原始文本。"""
    import csv
    import io

    records = [row for row in csv.reader(io.StringIO(text, newline=""))]
    if not records:
        return StageResult(text="", columns=(), runtime=RuntimeMeta(sqlite_version=sqlite3.sqlite_version))

    header = records[0]
    body = records[1:]

    # 一跳：CSV -> JSON 数组（保序、不推断类型；全部按字符串进 JSON）
    payload = json.loads(json.dumps([list(row) for row in body], ensure_ascii=False))

    connection = sqlite3.connect(":memory:")
    try:
        declarations = ", ".join(f"{_quote(name)} {COLUMN_TYPE}" for name in header)
        try:
            connection.execute(f"CREATE TABLE t ({declarations})")
        except sqlite3.Error as error:
            raise StageFailed(STAGE_NAME, f"建表失败: {error}") from error

        placeholders = ", ".join("?" for _ in header)
        try:
            connection.executemany(
                f"INSERT INTO t VALUES ({placeholders})",
                [tuple(row) for row in payload],  # 长度不符时 sqlite 会报错，如实暴露
            )
        except sqlite3.Error as error:
            raise StageFailed(STAGE_NAME, f"写入失败（行列数与表头不符）: {error}") from error

        select_list = ", ".join(
            # CAST(... AS TEXT) 让 SQLite 按**它自己的值模型**渲染（整数无小数、浮点最短表示），
            # 这正是要观测的亲和结果；直接取 Python 对象会在驱动层再格式化一次。
            f"CAST({_quote(name)} AS TEXT)" for name in header
        )
        try:
            cursor = connection.execute(f"SELECT {select_list} FROM t")
            rows = [tuple("" if value is None else str(value) for value in row) for row in cursor]
        except sqlite3.Error as error:
            raise StageFailed(STAGE_NAME, f"查询失败: {error}") from error
    finally:
        connection.close()

    columns = tuple(ColumnMeta(name=name, declared_type=COLUMN_TYPE) for name in header)
    return StageResult(
        text=rows_to_text([header, *rows]),
        columns=columns,
        runtime=RuntimeMeta(sqlite_version=sqlite3.sqlite_version),
    )


def available() -> tuple[bool, str]:
    return True, ""


__all__ = ["COLUMN_TYPE", "STAGE_NAME", "available", "run"]
