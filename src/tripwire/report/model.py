"""报告内存模型（M5）：**先算一次，再渲染三次**（`plan/02` §一 红线 4 / K9）。

`RunResult` 是唯一跨模块载体（`plan/02` §二）：MD / JSON / SARIF 三个渲染器只读它，
**不各自重算**、也不回头读 `runs/` 目录。判据 = "换一个格式，这一行的值会变吗？"
三个都从同一个 `RunResult` 取值，所以三份报告的 finding 集合按 `fingerprint` 恒等。

三条口径在这里落地（**别在渲染器里再实现一遍**）：

1. **首屏三段由本模块给出**（`first_screen()`），渲染器只按格式包裹它们：
   `VERDICT:` 行、`FIRST LOSS AT:` 行、`GATE:` 行。第三段的整行文本来自
   `Gate.line()`（M4 的唯一实现），本模块只把它放到第三行，不重拼格式串。
2. **`GATE:` 必须是 `Gate`**：recall / precision / unclassified 的定义只在
   `data/README.md` §6.2，`gate.py` 是实现。这里若手算一遍，就成了第二份口径。
3. **判定（0/1）与门禁（2）分开**：`verdict` 只说"有没有损失"，
   `exit_code` 才把门禁失败折进去（`gate.passed == False` → 2）。
   "有损" 不该被门禁失败盖住，"门禁失败" 也不该被说成"无损"。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tripwire import exitcodes
from tripwire.csvio import read_csv
from tripwire.diff import DiffError, DiffRecord, DiffResult, StructureRecord, diff_tables
from tripwire.gate import Gate, compute_gate
from tripwire.pipeline.model import INPUT_STAGE_NAME, RunStages, RuntimeMeta, StageSnapshot
from tripwire.report.errors import ReportError
from tripwire.rules.engine import Attribution, attribute

#: 判定字面（`plan/03` M5；`data/README` §6.3）
VERDICT_LOSSLESS = "LOSSLESS"
VERDICT_LOSSY = "LOSSY"

#: 三种合法报告格式（顺序 = `runs/<run_id>/` 里的落盘顺序）
FORMATS = ("md", "json", "sarif")

#: 每种格式的落盘文件名（`data/README` §6.5 的 `runs/` 布局）
REPORT_FILENAMES: Mapping[str, str] = {
    "md": "report.md",
    "json": "report.json",
    "sarif": "report.sarif",
}


def _build_text(value: str | None) -> str | None:
    """Excel 的 `Build` 经 COM 回来是**浮点读数**（`20326.0`）；Build 号是整数，显示时去掉 `.0`。

    规则刻意很窄：只对"整数值的十进制串"生效。版本号（`excel_version = "16.0"`）是**另一个字段**，
    它是真的 `16.0` 而不是整数被写成浮点，所以不动它。这是**显示层**的一处窄规则：
    `stages.json` 里记录的仍是 COM 原样读数（K1：不改证物，只改渲染）。
    """
    if value is None:
        return None
    if value.endswith(".0") and value[:-2].isdigit():
        return value[:-2]
    return value


def runtime_label(stage_name: str, runtime: RuntimeMeta) -> str:
    """首屏第二段括号里的**运行时指纹**（`plan/03` M5）。

    写法按通道分族（`Excel 16.0 Build 20326` / `pandas 3.0.6` / …），
    缺键或多出来的键都**不编**：一个能拼出来的部分都没有就写 `unknown`
    ——三段是固定的，**不省略整行**。
    """
    if stage_name == "excel_com_csv":
        parts = [
            f"Excel {runtime.excel_version}" if runtime.excel_version else None,
            f"Build {_build_text(runtime.excel_build)}" if runtime.excel_build else None,
        ]
    elif stage_name == "pandas_csv":
        parts = [f"pandas {runtime.pandas_version}" if runtime.pandas_version else None]
    elif stage_name == "openpyxl_csv":
        parts = [f"openpyxl {runtime.openpyxl_version}" if runtime.openpyxl_version else None]
    elif stage_name == "json_sqlite_csv":
        parts = [f"SQLite {runtime.sqlite_version}" if runtime.sqlite_version else None]
    else:
        # `input`（stage-0）与未知阶段名：不猜运行时，写 unknown
        parts = []
    kept = [part for part in parts if part]
    return " ".join(kept) if kept else "unknown"


def output_stages(run: RunStages) -> tuple[StageSnapshot, ...]:
    """该 run 的**成功输出**阶段（1-based；`stage-0` 是输入副本，不算输出）。"""
    return tuple(
        snapshot for snapshot in run.stages if snapshot.stage_index > 0 and snapshot.ok
    )


def select_stage(run: RunStages, stage_index: int | None) -> StageSnapshot:
    """选本次判定针对的输出阶段；不合法一律 `ReportError`（CLI 转 exit 3）。

    默认取**最后一份输出**：一条管线跑完，用户要的是"最终落盘的那份变成了什么"。
    """
    outputs = output_stages(run)
    if not outputs:
        raise ReportError(f"{run.out_dir} 里没有任何成功的输出阶段，无从判定。")
    available = [snapshot.stage_index for snapshot in outputs]
    target = stage_index if stage_index is not None else available[-1]
    if target not in available:
        raise ReportError(
            f"指定阶段 {target} 不在该 run 的输出里（可用: {', '.join(str(k) for k in available)}）。"
        )
    return run.stage(target)


def diff_for_stage(
    run: RunStages,
    stage: StageSnapshot,
    *,
    key: str | None,
    strategy: str,
) -> tuple[DiffResult, list[Attribution]]:
    """读 `stage-0` / `stage-<k>` 的**原始文本**做差异并归因（唯一实现）。

    读的是快照字节（K1），不是重新序列化的结果——报告要归因的是当时那份产物。
    返回 `(DiffResult, attributions)`；两张快照必须来自同一 run。
    """
    try:
        orig, _ = read_csv(run.out_dir / f"stage-{_input_index(run)}.csv")
        got, _ = read_csv(run.out_dir / f"stage-{stage.stage_index}.csv")
    except (FileNotFoundError, UnicodeDecodeError) as error:
        raise ReportError(f"快照不可读: {error}") from error

    try:
        result = diff_tables(
            orig, got, strategy=strategy, key=key, stage_index=stage.stage_index
        )
    except DiffError as error:
        raise ReportError(str(error)) from error

    return result, attribute(result.diffs, run, key=key, strategy=strategy)


def _input_index(run: RunStages) -> int:
    """输入副本的 `stage_index`（正常是 0；按 `stage_name` 兜底，不硬编码假设）。"""
    for snapshot in sorted(run.stages, key=lambda item: item.stage_index):
        if snapshot.stage_name == INPUT_STAGE_NAME:
            return snapshot.stage_index
    return 0


@dataclass(frozen=True)
class RunResult:
    """一次 run 的**完整内存结果**（`plan/02` §二 的 `RunResult`）。

    渲染器只读本对象；`gate` 由 `compute_gate` 得来（M4 的唯一实现）。
    """

    run_id: str
    pipeline: str
    stage_index: int
    stage_name: str
    stage_runtime: RuntimeMeta
    strategy: str
    key: str | None
    stages: tuple[StageSnapshot, ...]
    diffs: tuple[DiffRecord, ...]
    structures: tuple[StructureRecord, ...]
    attributions: tuple[Attribution, ...]
    gate: Gate
    rows_compared: int = 0
    cells_compared: int = 0

    # ── 派生结论（唯一实现，渲染器不许再算）───────────────────────────────

    @property
    def lossless(self) -> bool:
        """无单元格差异**且**无结构差异。空结果 ≠ "无损"——判定归门禁，不归这里。"""
        return not self.diffs and not self.structures

    @property
    def verdict(self) -> str:
        return VERDICT_LOSSLESS if self.lossless else VERDICT_LOSSY

    @property
    def unclassified_count(self) -> int:
        return sum(1 for item in self.attributions if item.unclassified)

    @property
    def rules_used(self) -> tuple[str, ...]:
        """本次真正命中的规则名（`unclassified` 不算规则，它单独计数）。"""
        return tuple(sorted({item.rule for item in self.attributions if not item.unclassified}))

    @property
    def exit_code(self) -> int:
        """判定通道出口：门禁失败优先（2），否则按有无损失给 0/1（`data/README` §6.3）。"""
        if not self.gate.passed:
            return exitcodes.GATE_FAILED
        return exitcodes.LOSSLESS if self.lossless else exitcodes.LOSSY

    def stage(self, index: int) -> StageSnapshot | None:
        for snapshot in self.stages:
            if snapshot.stage_index == index:
                return snapshot
        return None

    @property
    def first_loss_stage_index(self) -> int | None:
        """最早**首次观察到变化**的输出阶段序号（`Attribution.first_seen_at` 的最小值）。

        取"实际观察到的那一步"，不是规则候选里的那一个——首屏第二段要说的是
        "值在哪一步变了"，不是"规则认为最可能是哪一步"（`plan/03` M3 补充口径）。
        """
        seen = [item.first_seen_at for item in self.attributions if item.first_seen_at is not None]
        return min(seen) if seen else None

    def verdict_line(self) -> str:
        return (
            f"VERDICT: {self.verdict} "
            f"({len(self.diffs)}/{self.cells_compared} cells, {len(self.rules_used)} rules)"
        )

    def first_loss_line(self) -> str:
        """三种形态（`docs/report-schema.md` §三）：无损 `none` / 定位到 `stage k = name (runtime)` /
        有损失但没有任何阶段序列能指出位置 → `unknown (...)`。**任何情况都不省略整行。**
        """
        if self.lossless:
            return "FIRST LOSS AT: none"
        index = self.first_loss_stage_index
        if index is None:
            return "FIRST LOSS AT: unknown (no snapshot stage carried the change)"
        snapshot = self.stage(index)
        if snapshot is None:
            return f"FIRST LOSS AT: stage {index} = unknown (unknown)"
        return (
            f"FIRST LOSS AT: stage {snapshot.stage_index} = {snapshot.stage_name} "
            f"({runtime_label(snapshot.stage_name, snapshot.runtime)})"
        )

    def first_screen(self) -> tuple[str, str, str]:
        """首屏三段（顺序与字面固定，`plan/03` M5）。第三段整行来自 `Gate.line()`。"""
        return (self.verdict_line(), self.first_loss_line(), self.gate.line())

    def to_json(self) -> dict[str, Any]:
        """机读形态（`report.json` 的 `result` 段；`findings` 是**全部**归因含 unclassified）。"""
        return {
            "run_id": self.run_id,
            "pipeline": self.pipeline,
            "stage": {
                "index": self.stage_index,
                "name": self.stage_name,
                "artifact": f"stage-{self.stage_index}.csv",
                "runtime": runtime_label(self.stage_name, self.stage_runtime),
            },
            "strategy": self.strategy,
            "key": self.key,
            "verdict": self.verdict,
            "exit_code": self.exit_code,
            "first_screen": list(self.first_screen()),
            "counts": {
                "cell_diffs": len(self.diffs),
                "cells_compared": self.cells_compared,
                "rows_compared": self.rows_compared,
                "structures": len(self.structures),
                "rules": len(self.rules_used),
                "unclassified": self.unclassified_count,
            },
            "rules_used": list(self.rules_used),
            "first_loss_stage_index": self.first_loss_stage_index,
            "gate": self.gate.to_json(),
            "stages": [snapshot.to_json() for snapshot in self.stages],
            "findings": [item.to_json() for item in self.attributions],
            "structures": [item.to_json() for item in self.structures],
        }


def build_run_result(
    run: RunStages,
    expected: Sequence[Mapping[str, Any]],
    *,
    key: str | None = None,
    strategy: str = "key",
    stage_index: int | None = None,
) -> RunResult:
    """从一次 run 与真值算出**完整的内存结果**（M5 编排层的唯一入口）。

    `expected` = `expected.json` 的 `cells` 列表（不含真值就没有 recall/precision，
    **所以它是必填**：没有真值时报 0/1 就是把"没验过"写成"验过了"，见 D18）。
    """
    if strategy == "key" and not key:
        # K4/D3：拒绝运行要走 exit 3，且不产出任何差异结论（也不落报告）
        raise ReportError(
            "未声明主键：--align key 需要 --key <列名>；不猜对齐（若要按位置比，请显式 --align position）。"
        )

    stage = select_stage(run, stage_index)
    result, attributions = diff_for_stage(run, stage, key=key, strategy=strategy)
    gate = compute_gate(expected, attributions, stage_name=stage.stage_name)

    return RunResult(
        run_id=run.run_id,
        pipeline=run.pipeline_name,
        stage_index=stage.stage_index,
        stage_name=stage.stage_name,
        stage_runtime=stage.runtime,
        strategy=result.strategy,
        key=key,
        stages=tuple(run.stages),
        diffs=tuple(result.diffs),
        structures=tuple(result.structures),
        attributions=tuple(attributions),
        gate=gate,
        rows_compared=result.rows_compared,
        cells_compared=result.cells_compared,
    )


def load_expected(path: str | Path) -> list[Mapping[str, Any]]:
    """读 `expected.json` 的 `cells`（形状不对 → `ReportError`，不猜）。"""
    try:
        with open(path, "r", encoding="utf-8", newline="") as handle:
            payload = json.loads(handle.read())
    except (OSError, json.JSONDecodeError) as error:
        raise ReportError(f"真值文件不可读: {path}: {error}") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("cells"), list):
        raise ReportError(f"{path} 不是一份 expected.json（缺 cells 列表）")
    return payload["cells"]


__all__ = [
    "FORMATS",
    "REPORT_FILENAMES",
    "VERDICT_LOSSLESS",
    "VERDICT_LOSSY",
    "RunResult",
    "build_run_result",
    "diff_for_stage",
    "load_expected",
    "output_stages",
    "runtime_label",
    "select_stage",
]
