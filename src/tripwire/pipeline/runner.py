"""管线执行器：`run_pipeline(decl, input_csv, out_dir) -> RunStages`（M1 主线）。

三条纪律贯穿本文件：
- **K1**：`stage-<k>.csv` 写**原始文本**（`write_text_raw`），本模块内不出现 DataFrame；
- **K2**：`run_id = sha256(pipeline_name | input_sha256 | decl_sha256)[:16]`，**不含时间戳**；
- **D1**：任一步失败 → 先往 `stages.json` 落 `failed` 记录，再抛 → exit 3，**终止整条管线**。

`stages.json` 是**完全确定性**的：不含时间戳、不含耗时。`data/README` §6.5 列出的字段里没有
时间类字段，而 G9 要求"同输入双跑逐字节一致"——加一个 `generated_at` 会让这条承诺只在同一天内
成立，等于把确定性挂在日历上。需要运行台账时，`run_id` 本身就是可复算的凭证。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tripwire import serialization
from tripwire.csvio import parse_csv_text, sha256_text
from tripwire.pipeline import stages
from tripwire.pipeline.errors import (
    InputNotUtf8,
    RunIdCollision,
    StageFailed,
    StageUnavailable,
)
from tripwire.pipeline.model import (
    INPUT_STAGE_NAME,
    STATUS_FAILED,
    STATUS_OK,
    ColumnMeta,
    RunStages,
    RuntimeMeta,
    StageSnapshot,
)
from tripwire.pipeline.schema import PipelineDecl

RUN_ID_LENGTH = 16
STAGES_JSON = "stages.json"


def compute_run_id(pipeline_name: str, input_sha256: str, decl_sha256: str) -> str:
    """K2：内容派生，不含时间戳。同输入 + 同声明 → 同 id（可跨机对账）。"""
    material = f"{pipeline_name}|{input_sha256}|{decl_sha256}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:RUN_ID_LENGTH]


def decl_fingerprint(decl: PipelineDecl) -> str:
    """声明指纹：只认**语义字段**（名称 / 输入格式 / 阶段序列 / schema 版本），不认文件路径。

    为什么不直接哈希声明文件字节：同一份语义声明换个文件名或缩进就换 `run_id`，
    跨机对账的承诺就挂在"文件恰好长得一样"上，而不是挂在"跑的管线一样"上。
    """
    payload = {
        "name": decl.name,
        "input": decl.input_format,
        "schema_version": decl.schema_version,
        "stages": [{"stage_name": s.stage_name, "engine": s.engine} for s in decl.stages],
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _read_input_text(path: Path) -> str:
    try:
        with open(path, "r", encoding="utf-8", newline="") as handle:
            return handle.read()
    except UnicodeDecodeError as error:
        raise InputNotUtf8(f"输入不是合法 UTF-8 文本: {path}: {error}") from error
    except FileNotFoundError as error:
        raise InputNotUtf8(f"输入文件不存在: {path}") from error


def _snapshot(index: int, name: str, text: str, columns, runtime: RuntimeMeta) -> StageSnapshot:
    table = parse_csv_text(text)
    declared = tuple(columns) if columns else tuple(ColumnMeta(name=n) for n in table.header)
    return StageSnapshot(
        stage_index=index,
        stage_name=name,
        columns=declared,
        rows=table.row_count,
        cols=table.cols,
        sha256=sha256_text(text),
        runtime=runtime,
        status=STATUS_OK,
    )


def _payload(decl: PipelineDecl, run_id: str, input_sha: str, decl_sha: str, snapshots) -> dict:
    return {
        "run_id": run_id,
        "pipeline": decl.name,
        "input_sha256": input_sha,
        "decl_sha256": decl_sha,
        "stages": [snapshot.to_json() for snapshot in snapshots],
    }


def _payload_is_reusable(existing: dict, decl: PipelineDecl, run_id: str, input_sha: str, decl_sha: str) -> bool:
    """复用判据：同 id 且**声明/输入指纹一致**且全部阶段成功。

    为什么可以只看这几个字段就复用：`run_id` 是 `(name, input_sha, decl_sha)` 的哈希，
    这三者一致 + stage 序列与声明一致，就说明这次要跑的东西与目录里已有的完全同一件事；
    阶段产物 sha256 由内容决定，无需重跑复算（要复算也只是再次确认）。
    """
    if existing.get("run_id") != run_id:
        return False
    if existing.get("pipeline") != decl.name:
        return False
    if existing.get("input_sha256") != input_sha or existing.get("decl_sha256") != decl_sha:
        return False
    items = existing.get("stages")
    if not isinstance(items, list) or not items:
        return False
    if any(item.get("status") != STATUS_OK for item in items):
        return False  # 上次有失败 → 不复用，重跑（失败可能是环境性的：Excel 被占用等）
    declared = [INPUT_STAGE_NAME, *(stage.stage_name for stage in decl.stages)]
    actual = [item.get("stage_name") for item in items]
    return actual == declared


def _collides(existing: dict, decl: PipelineDecl, run_id: str, input_sha: str, decl_sha: str) -> bool:
    """同 id 但**声明/输入指纹对不上** → 目录里的东西不是按规则写出来的（篡改或手编）。"""
    if existing.get("run_id") != run_id:
        return False
    return (
        existing.get("pipeline") != decl.name
        or existing.get("input_sha256") != input_sha
        or existing.get("decl_sha256") != decl_sha
    )


def _load_existing(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _from_json(decl: PipelineDecl, run_id: str, input_sha: str, decl_sha: str, run_dir: Path, data: dict) -> RunStages:
    snapshots = tuple(
        StageSnapshot(
            stage_index=item["stage_index"],
            stage_name=item["stage_name"],
            columns=tuple(
                ColumnMeta(name=c["name"], declared_type=c.get("declared_type")) for c in item["columns"]
            ),
            rows=item["rows"],
            cols=item["cols"],
            sha256=item["sha256"],
            runtime=RuntimeMeta(**{key: item["runtime"].get(key) for key in RuntimeMeta.__dataclass_fields__}),
            status=item.get("status", STATUS_OK),
            reason=item.get("reason"),
        )
        for item in data["stages"]
    )
    return RunStages(
        run_id=run_id,
        pipeline_name=decl.name,
        input_sha256=input_sha,
        decl_sha256=decl_sha,
        out_dir=run_dir,
        stages=snapshots,
        reused=True,
    )


def run_pipeline(decl: PipelineDecl, input_csv: str | Path, out_dir: str | Path) -> RunStages:
    """跑一条声明。四条通道都经这里，没有第二条执行路径。"""
    input_path = Path(input_csv)
    if not input_path.is_file():
        raise InputNotUtf8(f"输入文件不存在: {input_path}")

    input_text = _read_input_text(input_path)
    input_sha = sha256_text(input_text)
    decl_sha = decl_fingerprint(decl)
    run_id = compute_run_id(decl.name, input_sha, decl_sha)
    run_dir = Path(out_dir) / run_id
    stages_json = run_dir / STAGES_JSON

    existing = _load_existing(stages_json)
    if existing is not None:
        if _payload_is_reusable(existing, decl, run_id, input_sha, decl_sha):
            return _from_json(decl, run_id, input_sha, decl_sha, run_dir, existing)
        if _collides(existing, decl, run_id, input_sha, decl_sha):
            raise RunIdCollision(
                f"run_id {run_id} 已存在但其 pipeline/input_sha256/decl_sha256 与本次不符："
                f"{stages_json}（同 id 必须同内容）"
            )
        # 上次失败 / 半成品 → 重跑覆盖，不复用也不报错

    run_dir.mkdir(parents=True, exist_ok=True)

    snapshots: list[StageSnapshot] = [_snapshot(0, INPUT_STAGE_NAME, input_text, None, RuntimeMeta())]
    serialization.write_text_raw(run_dir / "stage-0.csv", input_text)  # 输入原文副本，不改源文件

    current_text = input_text
    for index, stage_decl in enumerate(decl.stages, start=1):
        runner = stages.runner_for(stage_decl.stage_name)
        try:
            result = runner(current_text)
        except (StageUnavailable, StageFailed) as error:
            record_stage_failure(stages_json, decl, run_id, input_sha, decl_sha, snapshots, error)
            raise
        except Exception as error:  # 引擎任意异常都算阶段失败，不让管线半途消失
            wrapped = StageFailed(stage_decl.stage_name, f"阶段抛出未预期异常: {error}")
            record_stage_failure(stages_json, decl, run_id, input_sha, decl_sha, snapshots, wrapped)
            raise wrapped from error

        snapshot = _snapshot(index, stage_decl.stage_name, result.text, result.columns, result.runtime)
        serialization.write_text_raw(run_dir / f"stage-{index}.csv", result.text)
        snapshots.append(snapshot)
        current_text = result.text

    serialization.write_json(stages_json, _payload(decl, run_id, input_sha, decl_sha, snapshots))
    return RunStages(
        run_id=run_id,
        pipeline_name=decl.name,
        input_sha256=input_sha,
        decl_sha256=decl_sha,
        out_dir=run_dir,
        stages=tuple(snapshots),
    )


def record_stage_failure(
    stages_json: Path,
    decl: PipelineDecl,
    run_id: str,
    input_sha: str,
    decl_sha: str,
    snapshots: list[StageSnapshot],
    error: StageUnavailable | StageFailed,
) -> Path:
    """失败留痕：已完成阶段 + 一条 `failed` 记录（D1 的可审计面）。

    不做这一步，失败就只活在终端里：报告目录一片空白，读起来像"没跑过"，
    而不是"跑到 stage k 被挡住了"。
    """
    failed = StageSnapshot(
        stage_index=len(snapshots),
        stage_name=error.stage_name,
        status=STATUS_FAILED,
        reason=error.reason,
    )
    path = serialization.write_json(
        stages_json, _payload(decl, run_id, input_sha, decl_sha, [*snapshots, failed])
    )
    error.stages_path = path
    return path


__all__ = [
    "RUN_ID_LENGTH",
    "STAGES_JSON",
    "compute_run_id",
    "decl_fingerprint",
    "record_stage_failure",
    "run_pipeline",
]