"""单元格级差异引擎（M2）：`diff_tables(...) -> DiffResult(diffs, structures)`。

四条硬纪律：
- **K4**：`--align key` 缺 `--key` → `NoKeyForAlign`（exit 3），**不产出 `diffs: []`**；
- **K5**：差异按 `(row_key, col_index)` 排序，两次运行逐字节一致；
- **结构差异不折算**：`row_count` / `col_count` / `col_order` / `header` 各自独立成记录，
  不混进单元格差异数（否则"列名改了"会被读成"1200 个单元格都变了"）；
- **K1**：只读 `CsvTable` 的原始文本，不 import pandas、不读时钟、不读随机。

`--batch` 的类型推断用 `common.cell_kind` 而**不是 pandas**：差异层必须能在没装 pandas 的
机器上跑（`plan/02` §三只允许**阶段**因缺依赖失败），且必须与时钟/随机无关。
见 `plan/06` §六 D16。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from tripwire.csvio import CsvTable
from tripwire.diff.align import STRATEGIES, align, row_fingerprint
from tripwire.diff.errors import UnknownStrategy
from tripwire.pipeline.stages.common import cell_kind

#: 结构记录的 `kind` 枚举（顺序即落盘顺序，不依赖字典序）
STRUCTURE_KINDS = ("row_count", "col_count", "col_order", "header", "dtype_drift")


@dataclass(frozen=True)
class DiffRecord:
    """一条单元格差异。`row_key` 的语义**随对齐策略变**（见 `plan/03` M2）。

    `col_index` 参与排序（K5），`col` 是给人看的列名；两者都在记录里，
    因为"按列名排序"会让 `col_order` 变化时排序跟着变，而 `col_index` 只跟表头位置走。

    `orig_missing` / `got_missing` 区分**缺格**（行短于表头）与**空串**（`""`）。
    没有这两个字段，M3 的 `empty_vs_null_vs_missing` 规则无法成立：两者在文本上
    都是 `""`，只比值会把"格没了"读成"值空了"——那正是这条规则要抓的形态之一。
    """

    row_key: str
    col: str
    col_index: int
    orig_text: str
    got_text: str
    declared_type: str | None = None
    stage_index: int | None = None
    orig_missing: bool = False
    got_missing: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "row_key": self.row_key,
            "col": self.col,
            "col_index": self.col_index,
            "orig_text": self.orig_text,
            "got_text": self.got_text,
            "orig_missing": self.orig_missing,
            "got_missing": self.got_missing,
            "declared_type": self.declared_type,
            "stage_index": self.stage_index,
        }


@dataclass(frozen=True)
class StructureRecord:
    """一条结构差异。`detail` 的形状随 `kind` 变，但每个 `kind` 的形状是**写死**的。"""

    kind: str
    detail: Mapping[str, Any]
    stage_index: int | None = None

    def to_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "detail": dict(self.detail), "stage_index": self.stage_index}


@dataclass(frozen=True)
class DiffResult:
    """一次差异的完整结果。`diffs` 与 `structures` 都**已排序**，可直接序列化。"""

    strategy: str
    diffs: tuple[DiffRecord, ...] = ()
    structures: tuple[StructureRecord, ...] = ()
    rows_compared: int = 0
    cells_compared: int = 0

    @property
    def lossless(self) -> bool:
        """无单元格差异**且**无结构差异。空结果不等于"无损"——判定归 M4 的门禁，不归这里。"""
        return not self.diffs and not self.structures

    def to_json(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "rows_compared": self.rows_compared,
            "cells_compared": self.cells_compared,
            "diffs": [record.to_json() for record in self.diffs],
            "structures": [record.to_json() for record in self.structures],
        }


def diff_tables(
    orig: CsvTable,
    got: CsvTable,
    *,
    strategy: str = "key",
    key: str | None = None,
    batch: int | None = None,
    declared_types: Mapping[str, str | None] | None = None,
    stage_index: int | None = None,
) -> DiffResult:
    """比较两张表。`orig` = 原表，`got` = 往返后的表。"""
    if strategy not in STRATEGIES:
        raise UnknownStrategy(f"未知对齐策略 {strategy!r}（可用: {', '.join(STRATEGIES)}）")
    if batch is not None and batch <= 0:
        raise UnknownStrategy(f"--batch 必须是正整数（收到 {batch}）")

    pairs = align(orig, got, strategy, key)
    compared_pairs = [(left, right) for left, right in pairs if left is not None and right is not None]

    diffs = _cell_diffs(orig, got, compared_pairs, strategy, key, declared_types, stage_index)
    structures = _structures(orig, got, pairs, strategy, key, batch, stage_index)
    return DiffResult(
        strategy=strategy,
        diffs=tuple(sorted(diffs, key=lambda record: (record.row_key, record.col_index))),
        structures=tuple(structures),
        rows_compared=len(compared_pairs),
        cells_compared=_cells_compared(orig, got, compared_pairs, strategy),
    )


# ── 单元格差异 ────────────────────────────────────────────────────────────

def _cell_diffs(
    orig: CsvTable,
    got: CsvTable,
    pairs: Iterable[tuple[int, int]],
    strategy: str,
    key: str | None,
    declared_types: Mapping[str, str | None] | None,
    stage_index: int | None,
) -> list[DiffRecord]:
    """按列配对逐格比较。**未配上的行不产单元格差异**——它们归 `row_count` 结构记录。

    为什么不让"整行消失"变成 N 条单元格差异：那会把一个结构事实（行没了）膨胀成
    N 条单元格事实，而差异率的分母是单元格数——同一个问题被计两次。
    """
    columns = _column_pairs(orig, got, strategy)
    records: list[DiffRecord] = []
    for left, right in pairs:
        row_key = _row_key(orig, got, left, right, strategy, key)
        for orig_col, got_col in columns:
            name = orig.header[orig_col] if orig_col is not None else got.header[got_col]
            orig_text, orig_missing = _cell(orig, left, orig_col)
            got_text, got_missing = _cell(got, right, got_col)
            if orig_text == got_text and orig_missing == got_missing:
                continue
            records.append(
                DiffRecord(
                    row_key=row_key,
                    col=name,
                    col_index=orig_col if orig_col is not None else got_col,
                    orig_text=orig_text,
                    got_text=got_text,
                    orig_missing=orig_missing,
                    got_missing=got_missing,
                    declared_type=(declared_types or {}).get(name),
                    stage_index=stage_index,
                )
            )
    return records


def _cell(table: CsvTable, row_index: int | None, col_index: int | None) -> tuple[str, bool]:
    """读一格：返回 `(文本, 是否缺格)`。

    缺格 = 这一行比表头短（`csvio.CsvTable.cell` 对越界列返回 `""`）。它与"空串"
    在文本上无法区分，但**在语义上是两件事**：`NULL`/`''`/缺格 三态是本项目要抓的
    第 9 条规则。所以差异层把标记带上，让 M3 有证据可用，而不是等到 M3 再改 IR。
    """
    if row_index is None or col_index is None:
        return "", False
    row = table.rows[row_index]
    if col_index >= len(row):
        return "", True
    return row[col_index], False


def _column_pairs(orig: CsvTable, got: CsvTable, strategy: str) -> list[tuple[int | None, int | None]]:
    """列配对：`position` 按序号，`key` / `lcs` 按**列名**。

    按名配列是刻意的：列顺序变化属于 `col_order` 结构记录，不该在单元格层再报一遍。
    """
    if strategy == "position":
        shared = min(orig.cols, got.cols)
        return [(index, index) for index in range(shared)]
    got_positions = {name: index for index, name in enumerate(got.header)}
    return [(index, got_positions[name]) for index, name in enumerate(orig.header) if name in got_positions]


def _cells_compared(
    orig: CsvTable, got: CsvTable, pairs: list[tuple[int, int]], strategy: str
) -> int:
    return len(pairs) * len(_column_pairs(orig, got, strategy))


def _row_key(
    orig: CsvTable,
    got: CsvTable,
    left: int | None,
    right: int | None,
    strategy: str,
    key: str | None,
) -> str:
    """`row_key` 的语义随策略变（`plan/03` M2 表格）：

    - `key` → 主键值文本；
    - `position` → `#<row_index>`（原表行号优先；只有往返后才有的行用它的行号，两侧不会撞号）；
    - `lcs` → 匹配到的**原行**指纹；只在往返后出现的行没有原行，用 `~` + 自身指纹标记，
      以免看起来像一条原表行。
    """
    if strategy == "key":
        assert key is not None  # align() 已挡过；这里只是把契约写明
        source = orig if left is not None else got
        index = left if left is not None else right
        assert index is not None
        return source.cell(index, source.column_index(key))
    if strategy == "position":
        return f"#{left if left is not None else right}"
    if left is not None:
        return row_fingerprint(orig.rows[left])
    assert right is not None
    return "~" + row_fingerprint(got.rows[right])


# ── 结构差异 ──────────────────────────────────────────────────────────────

def _structures(
    orig: CsvTable,
    got: CsvTable,
    pairs: list[tuple[int | None, int | None]],
    strategy: str,
    key: str | None,
    batch: int | None,
    stage_index: int | None,
) -> list[StructureRecord]:
    records: list[StructureRecord] = []

    if orig.row_count != got.row_count:
        missing = [
            _row_key(orig, got, left, None, strategy, key) for left, right in pairs if right is None and left is not None
        ]
        extra = [
            _row_key(orig, got, None, right, strategy, key) for left, right in pairs if left is None and right is not None
        ]
        records.append(
            StructureRecord(
                kind="row_count",
                detail={"orig": orig.row_count, "got": got.row_count, "missing_rows": sorted(missing), "extra_rows": sorted(extra)},
                stage_index=stage_index,
            )
        )

    if orig.cols != got.cols:
        records.append(
            StructureRecord(
                kind="col_count",
                detail={"orig": orig.cols, "got": got.cols},
                stage_index=stage_index,
            )
        )

    # 列序只比**两侧都有的列**的先后：`c` 改名成 `d` 是 header 事实，不该同时算成"列序变了"；
    # 而 `a`/`b` 互换是独立的一条事实，两者可以同时成立（各自一条记录）。
    common_orig = [name for name in orig.header if name in set(got.header)]
    common_got = [name for name in got.header if name in set(orig.header)]
    if common_orig != common_got:
        records.append(
            StructureRecord(
                kind="col_order",
                detail={"orig": common_orig, "got": common_got},
                stage_index=stage_index,
            )
        )

    if set(orig.header) != set(got.header):
        added = [name for name in got.header if name not in set(orig.header)]
        removed = [name for name in orig.header if name not in set(got.header)]
        records.append(
            StructureRecord(
                kind="header",
                detail={"orig": list(orig.header), "got": list(got.header), "added": added, "removed": removed},
                stage_index=stage_index,
            )
        )

    if batch is not None:
        records.extend(_dtype_drift(orig, got, batch, stage_index))

    order = {kind: index for index, kind in enumerate(STRUCTURE_KINDS)}
    return sorted(records, key=lambda record: (order.get(record.kind, len(order)), record.kind, str(record.detail.get("col", ""))))


def _dtype_drift(orig: CsvTable, got: CsvTable, batch: int, stage_index: int | None) -> list[StructureRecord]:
    """`--batch N`：把表切成 N 行的 chunk，逐 chunk 推断每列类型；不一致即结构差异。

    为什么值得单列一条：pandas 的 `low_memory` 分块读取会让**同一列**在不同 chunk 推断成
    不同类型（文档原文 "possibly mixed type inference"，本机实测同列 6 个 chunk 里 1 个是 `str`）。
    这是"读取方式"造成的差异，不是"某个单元格"的差异，所以进结构记录。
    """
    records: list[StructureRecord] = []
    for side, table in (("orig", orig), ("got", got)):
        for col_index, name in enumerate(table.header):
            labels = [_chunk_label(table, col_index, start, batch) for start in range(0, table.row_count, batch)]
            distinct = sorted({label for label in labels if label is not None})
            if len(distinct) <= 1:
                continue
            records.append(
                StructureRecord(
                    kind="dtype_drift",
                    detail={
                        "side": side,
                        "col": name,
                        "col_index": col_index,
                        "types": distinct,
                        "chunks": [
                            {"chunk": chunk, "type": label}
                            for chunk, label in enumerate(labels)
                            if label is not None
                        ],
                    },
                    stage_index=stage_index,
                )
            )
    return records


def _chunk_label(table: CsvTable, col_index: int, start: int, batch: int) -> str | None:
    """一个 chunk 里某列的推断类型。全空 chunk 返回 `None`（不参与漂移判定）。

    判据刻意贴 pandas 的真实行为：**只要 chunk 里出现非数字文本，整块就落回文本**
    （pandas 的 `object` 回退），而不是"多数表决"——多数表决会造出 pandas 不会产出的标签，
    那样这条结构记录就不再对应真实的引擎行为。
    """
    kinds = {cell_kind(table.cell(row, col_index)) for row in range(start, min(start + batch, table.row_count))}
    kinds.discard("empty")
    if not kinds:
        return None
    if "text" in kinds:
        return "text"
    if kinds == {"int"}:
        return "int"
    return "float"


__all__ = [
    "STRUCTURE_KINDS",
    "DiffRecord",
    "DiffResult",
    "StructureRecord",
    "diff_tables",
]
