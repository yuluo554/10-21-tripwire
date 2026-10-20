"""管线 IR：`StageMeta`（`plan/02` §二）的落盘形态。

字段口径的**唯一定义**在 `data/README.md` §6.5（`stages.json` 每阶段必填：
`stage_index` / `stage_name` / `columns` / `rows` / `cols` / `sha256` / `runtime`）。
本模块只负责"每个键永远在"——不适用写 `null`，不许省略键（省略与"不适用"在 JSON 里无法区分）。

`runtime` 的六个键同样**永远齐**：`pandas_version` / `dtypes` / `excel_version` /
`excel_build` / `openpyxl_version` / `sqlite_version`。缺键会让下游"M5 首屏括号"在
`runtime` 为空时无值可写，只能整行省略——而首屏三段是不许省略的。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

#: `stage-0` 是输入原文副本；它的 `stage_name` 用这个保留名（不得与四个通道名冲突）
INPUT_STAGE_NAME = "input"

#: runtime 的六个键（顺序即文档顺序；落盘按 key 排序，不依赖此序）
RUNTIME_KEYS = (
    "pandas_version",
    "dtypes",
    "excel_version",
    "excel_build",
    "openpyxl_version",
    "sqlite_version",
)

STATUS_OK = "ok"
STATUS_FAILED = "failed"


@dataclass(frozen=True)
class ColumnMeta:
    """一列：`name` + 该引擎**声明的**类型（无类型声明的格式写 `None`，不猜）。"""

    name: str
    declared_type: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "declared_type": self.declared_type}


@dataclass(frozen=True)
class RuntimeMeta:
    """运行时指纹。六个键恒定全在，不适用写 `None`。"""

    pandas_version: str | None = None
    dtypes: Mapping[str, str] | None = None
    excel_version: str | None = None
    excel_build: str | None = None
    openpyxl_version: str | None = None
    sqlite_version: str | None = None

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {key: None for key in RUNTIME_KEYS}
        for key in RUNTIME_KEYS:
            value = getattr(self, key)
            payload[key] = None if value is None else (dict(value) if key == "dtypes" else value)
        return payload


@dataclass(frozen=True)
class StageSnapshot:
    """逐段快照的元数据。`sha256` 对**原文**取，可独立复算（G2）。"""

    stage_index: int
    stage_name: str
    columns: tuple[ColumnMeta, ...] = ()
    rows: int | None = None
    cols: int | None = None
    sha256: str | None = None
    runtime: RuntimeMeta = field(default_factory=RuntimeMeta)
    status: str = STATUS_OK
    reason: str | None = None
    path: Path | None = None

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK

    def to_json(self) -> dict[str, Any]:
        return {
            "stage_index": self.stage_index,
            "stage_name": self.stage_name,
            "columns": [column.to_json() for column in self.columns],
            "rows": self.rows,
            "cols": self.cols,
            "sha256": self.sha256,
            "runtime": self.runtime.to_json(),
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class StageResult:
    """阶段实现的返回：只交**原始文本**与自报的类型（K1：不许交 DataFrame）。"""

    text: str
    columns: tuple[ColumnMeta, ...] = ()
    runtime: RuntimeMeta = field(default_factory=RuntimeMeta)


@dataclass(frozen=True)
class RunStages:
    """一次 `run` 的产物视图：输入 + 各阶段输出（`stages` 含 `stage_index=0` 的输入）。"""

    run_id: str
    pipeline_name: str
    input_sha256: str
    decl_sha256: str
    out_dir: Path
    stages: tuple[StageSnapshot, ...]
    reused: bool = False

    def stage(self, index: int) -> StageSnapshot:
        for snapshot in self.stages:
            if snapshot.stage_index == index:
                return snapshot
        raise KeyError(index)

    @property
    def outputs(self) -> tuple[StageSnapshot, ...]:
        """1-based 的输出阶段（`stage-1` 是第一份输出，与 M3 的 `first_seen_at` 一致）。"""
        return tuple(snapshot for snapshot in self.stages if snapshot.stage_index > 0)

    @property
    def stages_json(self) -> Path:
        return self.out_dir / "stages.json"

    def to_json(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "pipeline": self.pipeline_name,
            "input_sha256": self.input_sha256,
            "decl_sha256": self.decl_sha256,
            "stages": [snapshot.to_json() for snapshot in self.stages],
        }


__all__ = [
    "INPUT_STAGE_NAME",
    "RUNTIME_KEYS",
    "STATUS_FAILED",
    "STATUS_OK",
    "ColumnMeta",
    "RunStages",
    "RuntimeMeta",
    "StageResult",
    "StageSnapshot",
]
