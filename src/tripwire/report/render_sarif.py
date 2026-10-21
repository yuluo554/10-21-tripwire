"""SARIF 2.1.0 渲染（M5）：**只读** `RunResult`，不重算、不读 `runs/`。

形状按 `plan/03` M5 写死：

- `version = "2.1.0"`；
- 每条 finding 一个 `result`：`ruleId = 规则名`、`level = "warning"`、
  `partialFingerprints.primaryLocationLineHash = fingerprint`、
  `locations[0].physicalLocation.artifactLocation.uri = "stage-<k>.csv"`；
- **不写绝对路径**（uri 只有快照文件名），否则报告换台机器就不可比，
  而 `fingerprint` 正是为了让"同一输入在不同机器上"能对上。

两处"不发明第二份口径"的落法：
1. `artifactLocation.uri` 指向**本次判定阶段**的快照（`stage-<k>.csv`），
   "值第一次在哪一步变的"放在 `properties.firstSeenStage` —— 二者不同时，
   前者说"审的是哪份产物"，后者说"哪一步引入的"。
2. `runs[0].properties.firstScreen` 原样放首屏三段（来自 `RunResult.first_screen()`），
   三格式拿的是同一份字符串，不在这里重拼。
"""

from __future__ import annotations

from typing import Any

from tripwire import __version__
from tripwire import serialization
from tripwire.report.model import RunResult, runtime_label

SCHEMA_URI = "https://json.schemastore.org/sarif-2.1.0.json"
SARIF_VERSION = "2.1.0"
INFORMATION_URI = "https://github.com/yuluo554/10-21-tripwire"


def _rule_id(result: RunResult, rule: str) -> str:
    """`ruleId` = 规则名（`unclassified` 也是一等公民，照样是 ruleId）。"""
    return rule


def payload(result: RunResult) -> dict[str, Any]:
    """SARIF 载荷。`results` 与 MD/JSON 的 finding 集合按 `fingerprint` 一一对应。"""
    artifact = f"stage-{result.stage_index}.csv"
    artifact_stage = result.stage(result.stage_index)
    results: list[dict[str, Any]] = []
    for item in result.attributions:
        seen_snapshot = result.stage(item.first_seen_at) if item.first_seen_at else None
        properties: dict[str, Any] = {
            "runId": result.run_id,
            "rule": item.rule,
            "unclassified": item.unclassified,
            "rowKey": item.diff.row_key,
            "col": item.diff.col,
            "colIndex": item.diff.col_index,
            "stageIndex": result.stage_index,
            "stageName": result.stage_name,
            "firstSeenStageIndex": item.first_seen_at,
            "firstSeenStageName": seen_snapshot.stage_name if seen_snapshot else item.first_seen_stage,
            "resolvedStage": item.resolved_stage,
            "candidates": list(item.candidates),
            "alsoMatched": list(item.also_matched),
        }
        results.append(
            {
                "ruleId": _rule_id(result, item.rule),
                "level": "warning",
                "message": {
                    "text": (
                        f"{item.diff.col} @ {item.diff.row_key}: "
                        f"{item.diff.orig_text!r} -> {item.diff.got_text!r}"
                        f"（规则 {item.rule}）"
                    )
                },
                "partialFingerprints": {"primaryLocationLineHash": item.fingerprint},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": artifact},
                        }
                    }
                ],
                "properties": properties,
            }
        )

    return {
        "$schema": SCHEMA_URI,
        "version": SARIF_VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "tripwire",
                        "version": __version__,
                        "informationUri": INFORMATION_URI,
                        "rules": [
                            {
                                "id": rule,
                                "name": rule,
                                "shortDescription": {"text": f"tripwire 归因规则 {rule}"},
                            }
                            for rule in _rule_descriptors(result)
                        ],
                    }
                },
                "artifacts": [
                    {
                        "location": {
                            "uri": artifact,
                            "properties": {
                                "stageName": result.stage_name,
                                "runtime": runtime_label(result.stage_name, result.stage_runtime),
                            },
                        }
                    }
                ],
                "invocations": [
                    {
                        "executionSuccessful": result.gate.passed,
                        "exitCode": result.exit_code,
                        "properties": {
                            "pipeline": result.pipeline,
                            "runId": result.run_id,
                            "strategy": result.strategy,
                            "cellDiffs": len(result.diffs),
                            "cellsCompared": result.cells_compared,
                            "structures": len(result.structures),
                            "gatePassed": result.gate.passed,
                            "vacuous": result.gate.vacuous,
                        },
                    }
                ],
                "properties": {
                    "verdict": result.verdict,
                    "firstScreen": list(result.first_screen()),
                    "gateLine": result.gate.line(),
                    "unclassified": result.unclassified_count,
                    "rulesUsed": list(result.rules_used),
                },
                "results": results,
            }
        ],
    }


def _rule_descriptors(result: RunResult) -> list[str]:
    """`ruleId` 必须能在 `tool.driver.rules` 里找到（含 `unclassified`），保持确定性顺序。"""
    names = set(result.rules_used)
    if result.unclassified_count:
        names.add("unclassified")
    return sorted(names)


def render(result: RunResult) -> str:
    """`RunResult` -> 规范 JSON 文本（SARIF 也是 JSON，走同一套序列化）。"""
    return serialization.dumps_json(payload(result))


__all__ = ["INFORMATION_URI", "SARIF_VERSION", "SCHEMA_URI", "payload", "render"]