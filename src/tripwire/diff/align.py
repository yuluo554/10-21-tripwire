"""对齐三策略：`key`（默认）/ `position` / `lcs`。

**为什么默认必须是 `key`（D3/K4）**：位置对齐遇到"插了一行"会把后面所有行都算成差异，
工具却仍报出一个漂亮的差异数——那是**雪崩式误报**，比拒绝运行更糟。所以没有 `--key`
就拒绝运行（`NoKeyForAlign` → exit 3），不猜行对应关系。

`align()` 的返回值是**纯位置对** `(orig_row_index | None, got_row_index | None)`：
- 两侧都非 `None` = 配上的行；
- 只有一侧 = 多出来 / 消失的行（由 `engine` 落进 `row_count` 结构记录）。

`row_key` 不在这里返回，因为它是**策略的语义产物**而不是对齐结果：`engine.row_key_for()`
从对子和策略推出来（`key` → 主键文本；`position` → `#<row_index>`；`lcs` → 行指纹）。
"""

from __future__ import annotations

import hashlib

from tripwire.csvio import CsvTable
from tripwire.diff.errors import DuplicateKey, MissingKeyColumn, NoKeyForAlign, UnknownStrategy

#: 合法策略（CLI 的 `--align` 与这里同一套枚举，不接受别名）
STRATEGIES = ("key", "position", "lcs")

#: `lcs` 用完整 DP 表，内存 O(n·m)。超过这个格子数就显式拒绝，而不是悄悄降级成近似对齐
#: （近似对齐会让"精确 LCS"这条承诺在数据量一大就悄悄失效）。
LCS_MAX_CELLS = 25_000_000

Pair = tuple[int | None, int | None]


def row_fingerprint(row: tuple[str, ...]) -> str:
    """行内容指纹：只认**单元格文本序列**，不含行号、不含表头、不含时间（K10 同源纪律）。

    `\\x1f`（Unit Separator）是分隔符：CSV 单元格里可以出现逗号、制表符、甚至换行，
    但出现 `\\x1f` 的概率与"两列拼接撞车"的概率同一量级，且它是可打印文本里的非法字符。
    """
    material = "\x1f".join(row).encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:16]


def align(orig: CsvTable, got: CsvTable, strategy: str, key: str | None) -> list[Pair]:
    """把两张表对齐成行对子。顺序 = 先原始表行序，再"只在往返后出现"的行。"""
    if strategy not in STRATEGIES:
        raise UnknownStrategy(f"未知对齐策略 {strategy!r}（可用: {', '.join(STRATEGIES)}）")
    if strategy == "key":
        if not key:
            raise NoKeyForAlign(
                "--align key 需要 --key <列名>：默认策略按主键对齐；"
                "不猜对齐（若要按位置比，请显式 --align position）。"
            )
        return _align_by_key(orig, got, key)
    if strategy == "position":
        return _align_by_position(orig, got)
    return _align_by_lcs(orig, got)


def _align_by_key(orig: CsvTable, got: CsvTable, key: str) -> list[Pair]:
    orig_keys = _unique_key_index(orig, key, "原始表")
    got_keys = _unique_key_index(got, key, "往返后")
    pairs: list[Pair] = [(row_index, got_keys.get(value)) for value, row_index in orig_keys.items()]
    # 只在往返后出现的行（原表没有这个主键）→ 单边对子
    pairs.extend((None, row_index) for value, row_index in got_keys.items() if value not in orig_keys)
    # 稳定顺序：先按原表行序，再按"只在往返后出现"的行号（K5 的前半条）
    pairs.sort(key=lambda pair: (pair[0] is None, pair[0] if pair[0] is not None else pair[1]))
    return pairs


def _unique_key_index(table: CsvTable, key: str, side: str) -> dict[str, int]:
    """主键列 -> 行号。重复即拒绝（`DuplicateKey`）：重复键无法建立一对一映射。

    为什么不能"取第一个"：那样"哪一行代表这个主键"就成了实现细节，报告里的
    `row_key` 会指向一个**任意**选中的行——不确定性被藏进了结论里。
    """
    try:
        column_index = table.column_index(key)
    except KeyError as error:
        raise MissingKeyColumn(key, side, table.header) from error
    index: dict[str, int] = {}
    for row_index in range(table.row_count):
        value = table.cell(row_index, column_index)
        if value in index:
            count = sum(1 for i in range(table.row_count) if table.cell(i, column_index) == value)
            raise DuplicateKey(key, side, value, count)
        index[value] = row_index
    return index


def _align_by_position(orig: CsvTable, got: CsvTable) -> list[Pair]:
    """按行号配对：`i` ↔ `i`。行数不等时多出来的行走"单边"，由 `row_count` 记录承载。"""
    shared = min(orig.row_count, got.row_count)
    pairs: list[Pair] = [(index, index) for index in range(shared)]
    pairs.extend((index, None) for index in range(shared, orig.row_count))
    pairs.extend((None, index) for index in range(shared, got.row_count))
    return pairs


def _align_by_lcs(orig: CsvTable, got: CsvTable) -> list[Pair]:
    """行指纹的**精确** LCS：不做相似度、不做阈值（弃选项：文档去重/相似度对齐）。

    精确意味着"一个字符不同就是另一行"。这是刻意的：相似度阈值会让结论依赖阈值，
    而阈值一旦可调，"这条差异算不算"就不再是输入的函数。

    **锚点之间按位置补配**：只靠 LCS 锚点的话，配上的行按定义逐字节相同，
    于是 `lcs` 永远报不出单元格差异——那等于这条策略只报"行增删"，不报"值变了"。
    所以锚点只负责"哪些行确定没动"，锚点之间的空隙（改动的行块）按位置成对，
    让单元格差异落在它该落的地方（与 unified diff 的 hunk 语义同构）。
    """
    left = [row_fingerprint(row) for row in orig.rows]
    right = [row_fingerprint(row) for row in got.rows]
    if len(left) * len(right) > LCS_MAX_CELLS:
        raise UnknownStrategy(
            f"lcs 对齐上限 {LCS_MAX_CELLS} 格（本次 {len(left)}×{len(right)}）："
            "精确 LCS 的 DP 表放不下；请改用 --align key（不降级成近似对齐）。"
        )

    rows, cols = len(left) + 1, len(right) + 1
    table = [[0] * cols for _ in range(rows)]
    for i in range(len(left) - 1, -1, -1):
        for j in range(len(right) - 1, -1, -1):
            if left[i] == right[j]:
                table[i][j] = table[i + 1][j + 1] + 1
            else:
                table[i][j] = max(table[i + 1][j], table[i][j + 1])

    anchors: list[tuple[int, int]] = []
    i = j = 0
    while i < len(left) and j < len(right):
        if left[i] == right[j]:
            anchors.append((i, j))
            i += 1
            j += 1
        elif table[i + 1][j] >= table[i][j + 1]:
            i += 1
        else:
            j += 1

    pairs: list[Pair] = []
    previous_i = previous_j = 0
    for anchor_i, anchor_j in [*anchors, (len(left), len(right))]:
        pairs.extend(_pair_gap(previous_i, anchor_i, previous_j, anchor_j))
        if anchor_i < len(left):
            pairs.append((anchor_i, anchor_j))
        previous_i, previous_j = anchor_i + 1, anchor_j + 1
    return pairs


def _pair_gap(start_i: int, end_i: int, start_j: int, end_j: int) -> list[Pair]:
    """两个锚点之间的空隙：先按位置成对，多出来的单边（`row_count` 结构记录会点名）。"""
    pairs: list[Pair] = []
    index_i, index_j = start_i, start_j
    while index_i < end_i and index_j < end_j:
        pairs.append((index_i, index_j))
        index_i += 1
        index_j += 1
    pairs.extend((index, None) for index in range(index_i, end_i))
    pairs.extend((None, index) for index in range(index_j, end_j))
    return pairs


__all__ = ["LCS_MAX_CELLS", "STRATEGIES", "Pair", "align", "row_fingerprint"]
