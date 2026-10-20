"""差异层（M2）：对齐三策略 + 单元格差异 + 四项结构差异。

分层纪律（`plan/02` §一）：本包只读 `csvio.CsvTable` 的**原始文本**视图，
不 import pandas、不读时钟、不读随机——差异必须是两份输入的确定函数（K5）。
"""

from tripwire.diff.align import STRATEGIES, align, row_fingerprint
from tripwire.diff.engine import DiffRecord, DiffResult, StructureRecord, diff_tables
from tripwire.diff.errors import (
    DiffError,
    DuplicateKey,
    MissingKeyColumn,
    NoKeyForAlign,
    UnknownStrategy,
)

__all__ = [
    "STRATEGIES",
    "DiffError",
    "DiffRecord",
    "DiffResult",
    "DuplicateKey",
    "MissingKeyColumn",
    "NoKeyForAlign",
    "StructureRecord",
    "UnknownStrategy",
    "align",
    "diff_tables",
    "row_fingerprint",
]
