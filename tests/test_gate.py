"""M4 门禁测试（出口门 E4 的另一半：`pytest -q tests/test_gate.py`）。

这组测试的靶子是 **G6（control-lossless 零误报）+ 门禁三数 + D4（precision 硬约束）**：

- `control-lossless` 组**零差异**——它防的是"为清零 unclassified 而放宽规则导致的误报"，
  比 unclassified 更糟；
- 三数（recall / precision / unclassified）**打印在首屏**且字面写死；
- **任一不满足 → exit 2**，且 `missing` / `unexpected` / `wrong_rule` 分开列（能指向唯一样本）；
- **空跑不算通过**：`reported == 0` 时门禁只记 `vacuous`，不算"覆盖了样本"。

门禁跑**真机四条通道**（不可用时显式 skip 并标注），不是拿冻结字符串硬编码。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tripwire import exitcodes
from tripwire.cli import main
from tripwire.csvio import read_csv
from tripwire.diff import diff_tables
from tripwire.fixtures import ORIG_NAME, EXPECTED_NAME, POOL_CONTROL, POOL_PREFIX
from tripwire.gate import PASS_RATIO, compute_gate, expected_for_stage
from tripwire.pipeline import stages
from tripwire.pipeline.runner import run_pipeline
from tripwire.pipeline.schema import load_pipeline
from tripwire.rules.engine import UNCLASSIFIED, Attribution, attribute
from tripwire.rules.predicates import rules_by_id

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN = REPO_ROOT / "fixtures" / "golden"
PIPELINES = REPO_ROOT / "pipelines"

#: stage_name -> 管线声明（四条通道各一条）
PIPELINE_FILES = {
    "pandas_csv": "pandas.json",
    "json_sqlite_csv": "json_sqlite.json",
    "openpyxl_csv": "openpyxl.json",
    "excel_com_csv": "excel_com.json",
}


@pytest.fixture(scope="module")
def golden_cells() -> list[dict]:
    payload = json.loads((GOLDEN / EXPECTED_NAME).read_text(encoding="utf-8"))
    return payload["cells"]


def _channel_run(stage_name: str, tmp_path: Path):
    """真跑一条通道。不可用则**显式 skip 并标注**（不假绿）。"""
    available, reason = stages.probe(stage_name)
    if not available:
        pytest.skip(f"{stage_name} 不可用，跳过并标注: {reason}")
    return run_pipeline(
        load_pipeline(PIPELINES / PIPELINE_FILES[stage_name]), GOLDEN / ORIG_NAME, tmp_path / "runs"
    )


def _gate_for(run, golden_cells, stage_name: str):
    orig, _ = read_csv(run.out_dir / "stage-0.csv")
    got, _ = read_csv(run.out_dir / "stage-1.csv")
    result = diff_tables(orig, got, strategy="key", key="id", stage_index=1)
    attributions = attribute(result.diffs, run, key="id", strategy="key")
    return result, attributions, compute_gate(golden_cells, attributions, stage_name=stage_name)


# ── 单元：compute_gate 的判定语义（不依赖真机）────────────────────────────

def _attribution(row_key: str, col: str, rule: str, got: str = "x", orig_text: str = "y") -> Attribution:
    from tripwire.diff.engine import DiffRecord

    record = DiffRecord(row_key=row_key, col=col, col_index=0, orig_text=orig_text, got_text=got)
    return Attribution(diff=record, rule=rule)


def test_gate_passes_when_all_three_hold():
    cells = [{"cell": ["r1", "a"], "rule": "leading_zero_lost", "p_after": {"pandas_csv": "2114"}}]
    gate = compute_gate(cells, [_attribution("r1", "a", "leading_zero_lost", got="2114")], stage_name="pandas_csv")
    assert gate.passed is True
    assert gate.recall == 1.0 and gate.precision == 1.0 and gate.unclassified == 0
    assert gate.matched == 1 and gate.expected == 1 and gate.reported == 1


def test_gate_fails_on_unclassified():
    """`unclassified` 是**条数**不是比例：有一条就判失败。"""
    cells = [{"cell": ["r1", "a"], "rule": "leading_zero_lost", "p_after": {"pandas_csv": "2114"}}]
    gate = compute_gate(cells, [_attribution("r1", "a", UNCLASSIFIED, got="2114")], stage_name="pandas_csv")
    assert gate.passed is False
    assert gate.unclassified == 1


def test_gate_fails_on_missing_expected_diff():
    """recall 分母里的差异没上报 → `missing` 非空 + recall < 1。"""
    cells = [{"cell": ["r1", "a"], "rule": "leading_zero_lost", "p_after": {"pandas_csv": "2114"}}]
    gate = compute_gate(cells, [], stage_name="pandas_csv")
    assert gate.passed is False
    assert gate.recall == 0.0
    assert len(gate.missing) == 1
    assert gate.missing[0].row_key == "r1" and gate.missing[0].rule == "leading_zero_lost"


def test_gate_fails_on_unexpected_diff():
    """上报了真值里没有的差异（含控制组的任何差异）→ `unexpected` 非空 + precision < 1。"""
    cells = [{"cell": ["r1", "a"], "rule": "leading_zero_lost", "p_after": {"pandas_csv": "2114"}}]
    attributions = [
        _attribution("r1", "a", "leading_zero_lost", got="2114"),
        _attribution("ctl-9", "zip", "leading_zero_lost", orig_text="94016", got="94016.0"),
    ]
    gate = compute_gate(cells, attributions, stage_name="pandas_csv")
    assert gate.passed is False
    assert len(gate.unexpected) == 1
    assert gate.unexpected[0].row_key == "ctl-9"
    assert gate.precision < PASS_RATIO


def test_gate_fails_on_wrong_rule():
    """变化对上、规则名不对 → `wrong_rule`（既不是漏报也不是误报，是归因错）。"""
    cells = [{"cell": ["r1", "a"], "rule": "leading_zero_lost", "p_after": {"pandas_csv": "2114"}}]
    gate = compute_gate(cells, [_attribution("r1", "a", "int53_overflow", got="2114")], stage_name="pandas_csv")
    assert gate.passed is False
    assert len(gate.wrong_rule) == 1
    assert gate.wrong_rule[0].expected_rule == "leading_zero_lost"


def test_gate_fails_on_wrong_value():
    """变化值与真值不符 → 也算 `unexpected`（夹具/引擎两边必有一错）。"""
    cells = [{"cell": ["r1", "a"], "rule": "leading_zero_lost", "p_after": {"pandas_csv": "2114"}}]
    gate = compute_gate(cells, [_attribution("r1", "a", "leading_zero_lost", got="9999")], stage_name="pandas_csv")
    assert gate.passed is False
    assert len(gate.unexpected) == 1


def test_gate_marks_vacuous_when_nothing_reported():
    """`reported == 0` 时 precision 记 1.0（没有误报），但必须标 `vacuous`。

    否则"全绿"可以只是"什么都没查"——与 M0 门禁 token 集为空的前车之鉴同族。
    """
    gate = compute_gate([], [], stage_name="pandas_csv")
    assert gate.vacuous is True
    assert gate.passed is True
    assert gate.reported == 0


def test_expected_for_stage_filters_by_stage():
    """分母只取"本阶段真会变"的期望——同一形态在不同阶段的期望不同。"""
    cells = [
        {"cell": ["r1", "a"], "rule": "excel_15_digit_truncation", "p_after": {"excel_com_csv": "1.23457E+15"}},
        {"cell": ["r2", "a"], "rule": "leading_zero_lost",
         "p_after": {"pandas_csv": "2114", "excel_com_csv": "2114"}},
    ]
    assert set(expected_for_stage(cells, "excel_com_csv")) == {("r1", "a"), ("r2", "a")}
    assert set(expected_for_stage(cells, "pandas_csv")) == {("r2", "a")}
    assert expected_for_stage(cells, "openpyxl_csv") == {}


# ── 首屏三数（字面写死）───────────────────────────────────────────────────

def test_gate_line_is_frozen():
    """`GATE: recall 1.00 precision 1.00 unclassified 0` —— 字面与顺序写死（`data/README` §6.2）。"""
    cells = [{"cell": ["r1", "a"], "rule": "leading_zero_lost", "p_after": {"pandas_csv": "2114"}}]
    gate = compute_gate(cells, [_attribution("r1", "a", "leading_zero_lost", got="2114")], stage_name="pandas_csv")
    assert gate.line() == "GATE: recall 1.00 precision 1.00 unclassified 0"


def test_gate_three_numbers_printed_on_first_screen(golden_cells, tmp_path, capsys):
    """CLI 首屏必须含那三段字面（M5 报告的第一屏从这里接）。"""
    run = _channel_run("json_sqlite_csv", tmp_path)
    code = main([
        "gate", "--run-id", run.run_id, "--out-dir", str(tmp_path / "runs"),
        "--expected", str(GOLDEN / EXPECTED_NAME), "--key", "id",
    ])
    captured = capsys.readouterr()
    assert code in exitcodes.VERDICT_CODES
    first_lines = captured.out.splitlines()[:3]
    assert first_lines[1].strip().startswith("GATE: recall ")
    assert "precision " in first_lines[1] and "unclassified " in first_lines[1]


# ── 真机四通道：门禁必须全绿（G4 的延伸）────────────────────────────────

@pytest.mark.parametrize("stage_name", sorted(PIPELINE_FILES))
def test_gate_passes_on_real_channel(stage_name, golden_cells, tmp_path):
    """四条通道各自的 recall / precision / unclassified 都必须满足口径。

    不可用的通道**显式 skip 并标注**，不假绿（`plan/05` §四 登记的 Excel COM 只在 Windows）。
    """
    run = _channel_run(stage_name, tmp_path)
    result, _, gate = _gate_for(run, golden_cells, stage_name)
    assert gate.passed, (
        f"{stage_name}: recall {gate.recall} precision {gate.precision} "
        f"unclassified {gate.unclassified}；missing={[m.to_json() for m in gate.missing][:5]} "
        f"unexpected={[u.to_json() for u in gate.unexpected][:5]} "
        f"wrong_rule={[w.to_json() for w in gate.wrong_rule][:5]}"
    )
    assert gate.unclassified == 0
    assert gate.recall == 1.0 and gate.precision == 1.0
    assert not gate.vacuous, f"{stage_name} 空跑通过（reported == 0）"
    assert result.diffs, "金样本必须真的产出差异"


@pytest.mark.parametrize("stage_name", sorted(PIPELINE_FILES))
def test_control_lossless_zero_false_positive(stage_name, tmp_path):
    """**G6 / D4 硬约束**：`control-lossless` 组在四条通道上都是 **0 条差异**。

    它一旦报差异，precision 必失败——这正是它存在的意义：守住"不为清零 unclassified 放宽规则"。
    """
    run = _channel_run(stage_name, tmp_path)
    orig, _ = read_csv(run.out_dir / "stage-0.csv")
    got, _ = read_csv(run.out_dir / "stage-1.csv")
    result = diff_tables(orig, got, strategy="key", key="id", stage_index=1)

    prefix = POOL_PREFIX[POOL_CONTROL]
    key_index = orig.column_index("id")
    control_keys = {
        orig.cell(index, key_index) for index in range(orig.row_count)
        if orig.cell(index, key_index).startswith(prefix)
    }
    assert len(control_keys) == 60, "控制组行数应为 60（seed 42 / rows 200）"
    offenders = [record for record in result.diffs if record.row_key in control_keys]
    assert offenders == [], [record.to_json() for record in offenders]
    # 控制组也不许出现在结构差异里（整行消失/多出）
    for structure in result.structures:
        for value in structure.detail.values():
            if isinstance(value, list):
                assert not any(str(item).startswith(prefix) for item in value), structure.to_json()


def test_golden_expected_covers_every_rules_json_entry(golden_cells):
    """`expected.json` 里出现的规则与 `uncovered_rules` **合起来**覆盖 `rules.json` 的 18 条。

    这条把"覆盖情况"变成可复算的结论：不许有一条规则既没正例、又没被点名。
    """
    payload = json.loads((GOLDEN / EXPECTED_NAME).read_text(encoding="utf-8"))
    covered = {cell["rule"] for cell in golden_cells}
    uncovered = set(payload["uncovered_rules"])
    assert covered.isdisjoint(uncovered), "同一条规则既被覆盖又被点名"
    assert covered | uncovered == set(rule_names_all()), "18 条规则必须二选一被归类"


def rule_names_all() -> list[str]:
    return [rule["name"] for rule in rules_by_id()]


def test_uncovered_rules_are_documented(golden_cells):
    """点名的 `uncovered_rules` 必须在下游文档里有对应说明（不假装覆盖）。"""
    from tripwire.fixtures import KNOWN_UNCOVERABLE

    payload = json.loads((GOLDEN / EXPECTED_NAME).read_text(encoding="utf-8"))
    for name in payload["uncovered_rules"]:
        assert name in KNOWN_UNCOVERABLE, f"{name} 被点名但没登记理由"
    docs = (REPO_ROOT / "docs" / "fixture-pools.md").read_text(encoding="utf-8")
    for name in payload["uncovered_rules"]:
        assert name in docs, f"{name} 未写入 docs/fixture-pools.md"


# ── 退出码（M4 的判定通道首次接线）───────────────────────────────────────

def test_cli_gate_exits_1_when_lossy_but_gate_passes(golden_cells, tmp_path):
    """有差异且门禁通过 → **exit 1（有损）**——这是 M4 首次真正产出 0/1。"""
    run = _channel_run("json_sqlite_csv", tmp_path)
    code = main([
        "gate", "--run-id", run.run_id, "--out-dir", str(tmp_path / "runs"),
        "--expected", str(GOLDEN / EXPECTED_NAME), "--key", "id",
    ])
    assert code == exitcodes.LOSSY


def test_gate_failure_exits_2(golden_cells, tmp_path, capsys):
    """三数任一不满足 → **exit 2（门禁失败）**。用"删掉一半期望"制造 recall 不足。"""
    run = _channel_run("json_sqlite_csv", tmp_path)
    doctored = tmp_path / "doctored.json"
    payload = {"seed": 42, "rows": 200, "cells": golden_cells[:1]}  # 只留一条期望
    doctored.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    code = main([
        "gate", "--run-id", run.run_id, "--out-dir", str(tmp_path / "runs"),
        "--expected", str(doctored), "--key", "id",
    ])
    captured = capsys.readouterr()
    assert code == exitcodes.GATE_FAILED
    assert "GATE FAILED" in captured.err
    assert "UNEXPECTED" in captured.out or "MISSING" in captured.out


def test_cli_gate_exits_3_on_missing_truth_file(golden_cells, tmp_path, capsys):
    """读不到真值 → 用法通道 3（不是门禁失败 2，也不是有损 1）。"""
    run = _channel_run("json_sqlite_csv", tmp_path)
    code = main([
        "gate", "--run-id", run.run_id, "--out-dir", str(tmp_path / "runs"),
        "--expected", str(tmp_path / "nope.json"), "--key", "id",
    ])
    assert code == exitcodes.USAGE
    assert code not in (exitcodes.LOSSLESS, exitcodes.LOSSY, exitcodes.GATE_FAILED)


def test_cli_gate_exits_3_without_key(tmp_path):
    """`--align key` 缺 `--key` → exit 3（K4 在门禁入口同样成立）。"""
    code = main([
        "gate", "--run-id", "whatever", "--out-dir", str(tmp_path),
        "--expected", str(GOLDEN / EXPECTED_NAME),
    ])
    assert code == exitcodes.USAGE


def test_cli_gate_exits_3_on_unknown_run(tmp_path, capsys):
    code = main([
        "gate", "--run-id", "does-not-exist", "--out-dir", str(tmp_path),
        "--expected", str(GOLDEN / EXPECTED_NAME), "--key", "id",
    ])
    assert code == exitcodes.USAGE
    assert "读不到该 run" in capsys.readouterr().err


def test_cli_gate_exit_code_matches_process_exit_code(tmp_path):
    """`main()` 返回值与真实进程退出码一致（M5 交付态四条测试的机制提前验一次）。"""
    import os
    import subprocess
    import sys

    run = _channel_run("json_sqlite_csv", tmp_path)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUTF8"] = "1"
    result = subprocess.run(
        [
            sys.executable, "-m", "tripwire", "gate", "--run-id", run.run_id,
            "--out-dir", str(tmp_path / "runs"), "--expected", str(GOLDEN / EXPECTED_NAME), "--key", "id",
        ],
        cwd=str(REPO_ROOT), capture_output=True, text=True, encoding="utf-8", timeout=300, env=env,
    )
    assert result.returncode == exitcodes.LOSSY, result.stderr
    assert "GATE: recall 1.00" in result.stdout