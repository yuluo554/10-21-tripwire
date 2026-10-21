"""JSON 渲染（M5）：**只读** `RunResult`，不重算、不读 `runs/`。

落盘走 `serialization.write_json`（K11 的唯一写盘点），所以 `render()` 与
`write_json(payload())` 产出**同一串字节**：两处都用 `serialization.dumps_json`
（排序键 + `ensure_ascii=False` + LF + 结尾换行），不存在第二份 JSON 规范。
"""

from __future__ import annotations

from typing import Any

from tripwire import __version__
from tripwire import serialization
from tripwire.report.model import RunResult

#: `report.json` 的 schema 版本（形状变更时 +1；与 `expected.json` 的版本号各自独立）
SCHEMA_VERSION = 1


def payload(result: RunResult) -> dict[str, Any]:
    """机读载荷。`findings` 是**全部**归因（含 `unclassified`），按 `(row_key, col_index)` 有序。"""
    return {
        "schema_version": SCHEMA_VERSION,
        "generator": {"name": "tripwire", "version": __version__},
        **result.to_json(),
    }


def render(result: RunResult) -> str:
    """`RunResult` -> 规范 JSON 文本（与 `serialization.write_json` 同字节）。"""
    return serialization.dumps_json(payload(result))


__all__ = ["SCHEMA_VERSION", "payload", "render"]