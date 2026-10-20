"""差异层失败路径：全部映射到**用法通道 exit 3**，一条也不许降级成"0 差异"。

与 M1 的 `pipeline/errors.py` 同一套纪律（D1）：一条被吞掉的拒绝运行，会让报告显示
"无损"，而事实是**没比过**。所以"没主键 / 主键重复 / 主键列不存在"都必须响。
"""

from __future__ import annotations


class DiffError(Exception):
    """差异层的基类：全部走 exit 3。"""


class NoKeyForAlign(DiffError):
    """`--align key` 却没给 `--key`（K4 / D3）。**不产出任何 `diffs: []` 结论**。

    位置对齐遇插行会雪崩式误报，而工具仍会报一个漂亮的差异数——那比拒绝运行更糟。
    """


class UnknownStrategy(DiffError):
    """未知对齐策略。策略是**枚举**，不是可猜的字符串。"""


class MissingKeyColumn(DiffError):
    """`--key` 指定的列不在表头里。报列名，不猜"最像的那一列"。"""

    def __init__(self, column: str, side: str, header: tuple[str, ...]) -> None:
        self.column = column
        self.side = side
        self.header = header
        available = ", ".join(header) if header else "(空表头)"
        super().__init__(f"主键列 {column!r} 不在{side}表头里（可用列: {available}）")


class DuplicateKey(DiffError):
    """主键重复：无法建立一对一映射。**不"取第一个"**——那会把随机性藏进结论。"""

    def __init__(self, column: str, side: str, value: str, count: int) -> None:
        self.column = column
        self.side = side
        self.value = value
        self.count = count
        super().__init__(f"{side}的主键列 {column!r} 有重复值 {value!r}（出现 {count} 次），无法建立一对一映射")


__all__ = [
    "DiffError",
    "DuplicateKey",
    "MissingKeyColumn",
    "NoKeyForAlign",
    "UnknownStrategy",
]
