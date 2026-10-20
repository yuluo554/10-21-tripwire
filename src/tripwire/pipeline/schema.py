"""管线声明：加载 + 校验（M1 实现执行器，本模块先定形状与失败路径）。

声明非法一律 `PipelineDeclError` -> CLI 转 exit 3（用法通道），**不产出任何"0 差异"结论**。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

#: 允许的阶段名（stage_name 是报告里的用户可见标识，改名即破坏跨 run 可比性）
KNOWN_STAGE_NAMES = ("pandas_csv", "excel_com_csv", "openpyxl_csv", "json_sqlite_csv")

#: stage_name -> 引擎标识。**一一对应**：禁止把 openpyxl 的结果标成 excel_com_csv（D1）。
STAGE_ENGINES = {
    "pandas_csv": "pandas",
    "excel_com_csv": "excel_com",
    "openpyxl_csv": "openpyxl",
    "json_sqlite_csv": "json_sqlite",
}

#: 允许的引擎标识（`libreoffice` 为二期预留，首期不实现、也不允许出现在声明里）
KNOWN_ENGINES = ("pandas", "excel_com", "openpyxl", "json_sqlite")

SCHEMA_VERSION = 1


class PipelineDeclError(ValueError):
    """声明非法（CLI 转 exit 3）。"""


@dataclass(frozen=True)
class StageDecl:
    stage_name: str
    engine: str


@dataclass(frozen=True)
class PipelineDecl:
    name: str
    input_format: str
    stages: tuple[StageDecl, ...]
    schema_version: int
    source: Path | None = None


def load_pipeline(path: str | Path) -> PipelineDecl:
    target = Path(path)
    if not target.is_file():
        raise PipelineDeclError(f"管线声明不存在: {target}")
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise PipelineDeclError(f"管线声明不是合法 JSON: {target}: {error}") from error
    if not isinstance(raw, dict):
        raise PipelineDeclError(f"管线声明顶层必须是对象: {target}")

    problems = validate_pipeline_dict(raw)
    if problems:
        raise PipelineDeclError("；".join(problems))

    stages = tuple(StageDecl(stage_name=s["stage_name"], engine=s["engine"]) for s in raw["stages"])
    return PipelineDecl(
        name=raw["name"],
        input_format=raw.get("input", "csv"),
        stages=stages,
        schema_version=raw["schema_version"],
        source=target,
    )


def validate_pipeline_dict(raw: dict) -> list[str]:
    """返回问题列表；空列表 = 合法。**永不抛异常**（校验器自己不能崩）。"""
    problems: list[str] = []

    version = raw.get("schema_version")
    if version != SCHEMA_VERSION:
        problems.append(f"schema_version 必须是 {SCHEMA_VERSION}，实际 {version!r}")

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        problems.append("name 必须是非空字符串")

    input_format = raw.get("input", "csv")
    if input_format != "csv":
        problems.append(f"首期只支持 csv 输入，实际 {input_format!r}")

    stages = raw.get("stages")
    if not isinstance(stages, list) or not stages:
        problems.append("stages 必须是非空数组")
        return problems

    seen: set[str] = set()
    for index, stage in enumerate(stages):
        where = f"stages[{index}]"
        if not isinstance(stage, dict):
            problems.append(f"{where} 必须是对象")
            continue
        stage_name = stage.get("stage_name")
        engine = stage.get("engine")
        if stage_name not in KNOWN_STAGE_NAMES:
            problems.append(f"{where}.stage_name 未知: {stage_name!r}（允许: {', '.join(KNOWN_STAGE_NAMES)}）")
        elif stage_name in seen:
            problems.append(f"{where}.stage_name 重复: {stage_name}")
        else:
            seen.add(stage_name)
        if engine not in KNOWN_ENGINES:
            problems.append(f"{where}.engine 未知: {engine!r}（允许: {', '.join(KNOWN_ENGINES)}）")
        elif stage_name in STAGE_ENGINES and engine != STAGE_ENGINES[stage_name]:
            # 禁止混称：stage_name 与 engine 必须一一对应
            problems.append(
                f"{where} stage_name={stage_name} 必须配 engine={STAGE_ENGINES[stage_name]}，实际 {engine}"
            )

    return problems


def load_pipeline_dict(path: str | Path) -> dict:
    """读原始声明（供 `validate-pipeline` 输出问题列表，不抛异常）。"""
    target = Path(path)
    if not target.is_file():
        return {}
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return raw if isinstance(raw, dict) else {}
