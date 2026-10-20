"""四个数据通道阶段。每个模块暴露同名接口：`run(text) -> StageResult` / `available() -> (bool, str)`。

**stage_name 与模块文件名严格一一对应**（K3 / D1）：
`pandas_csv` / `excel_com_csv` / `openpyxl_csv` / `json_sqlite_csv`。
报告只写实际跑的那个名字，任何"统称 Excel"的写法都在 `docs/pipeline-schema.md` 里被禁止。
"""

from __future__ import annotations

from typing import Callable

from tripwire.pipeline.model import StageResult
from tripwire.pipeline.stages import (
    excel_com_csv,
    json_sqlite_csv,
    openpyxl_csv,
    pandas_csv,
)

StageRunner = Callable[[str], StageResult]

#: stage_name -> 执行函数（调度表；`schema.STAGE_ENGINES` 是它的申报侧对应物）
RUNNERS: dict[str, StageRunner] = {
    pandas_csv.STAGE_NAME: pandas_csv.run,
    excel_com_csv.STAGE_NAME: excel_com_csv.run,
    openpyxl_csv.STAGE_NAME: openpyxl_csv.run,
    json_sqlite_csv.STAGE_NAME: json_sqlite_csv.run,
}

#: stage_name -> 可用性探针（便于测试决定"跳过并标注"而不是假绿）
PROBES: dict[str, Callable[[], tuple[bool, str]]] = {
    pandas_csv.STAGE_NAME: pandas_csv.available,
    excel_com_csv.STAGE_NAME: excel_com_csv.available,
    openpyxl_csv.STAGE_NAME: openpyxl_csv.available,
    json_sqlite_csv.STAGE_NAME: json_sqlite_csv.available,
}


def runner_for(stage_name: str) -> StageRunner:
    try:
        return RUNNERS[stage_name]
    except KeyError as error:
        raise KeyError(f"未知阶段名: {stage_name}") from error


def probe(stage_name: str) -> tuple[bool, str]:
    return PROBES[stage_name]()


__all__ = ["PROBES", "RUNNERS", "StageRunner", "probe", "runner_for"]
