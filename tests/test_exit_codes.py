"""退出码测试（**交付态四条**：M5 出口门 E5 的另一半）。

分工：`plan/05` §三 E5 把"0/1/2/3 各一条"判给 M5。四条都走**真实 CLI 入口**
（`main(argv)` **与**真实进程各一遍，并断言两者一致）。

M4 收尾时的守卫是"`run` 不许返回 0"。**M5 显式改写它**（原测试连同 `NO_VERDICT_NOTE`
一起删）：判定通道 M5 起接到 `run --expected` / `report` / `gate` 上，
所以守卫变成**两条都要成立**——

1. 无真值时 `run` 仍**拒绝判定**（exit 3，且不打印 `VERDICT:` 行）：拿不到 recall/precision
   就没有门禁三数，报 0/1 就是把"没验过"写成"验过了"；
2. 给真值时 `run` **落进判定通道**（0/1/2，且第一行是 `VERDICT:`）：`run` 的码来自
   `compute_gate`，不是"跑通即绿"——给 `run` 加个 `return LOSSLESS` 会两条一起红。
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tripwire import exitcodes
from tripwire.cli import main
from tripwire.fixtures import EXPECTED_NAME
from tripwire.pipeline import stages

REPO_ROOT = Path(__file__).resolve().parents[1]
PIPELINES = REPO_ROOT / "pipelines"
GOLDEN = REPO_ROOT / "fixtures" / "golden"

SAMPLE_ROWS = [
    ["id", "num_big", "zip", "decimal", "exponent", "date", "text_unicode", "nullable"],
    ["num-0001", "12345678901234567890", "02114", "19.90", "1e-7", "2024-01-02", "caf\u00e9", ""],
    ["num-0002", "1125899906842624", "00123-4567", "1.005", "1E5", "1900-02-29", "e\u0301", "NULL"],
]


@pytest.fixture()
def sample_csv(tmp_path: Path) -> Path:
    path = tmp_path / "sample.csv"
    with open(path, "w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerows(SAMPLE_ROWS)
    return path


def _subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUTF8"] = "1"
    return env


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "tripwire", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=600,
        env=_subprocess_env(),
    )


# ── 用法通道 3 的来源 ──────────────────────────────────────────────────────

def test_usage_error_for_missing_required_args():
    assert main(["run"]) == exitcodes.USAGE
    assert main(["run", "--pipeline", str(PIPELINES / "pandas.json")]) == exitcodes.USAGE


def test_usage_error_for_invalid_declaration(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"name": "x", "schema_version": 99, "stages": []}', encoding="utf-8")
    assert main(["run", "--pipeline", str(bad), "--input", "whatever.csv", "--key", "id"]) == exitcodes.USAGE


def test_no_key_refuses_to_run_and_writes_nothing(sample_csv, tmp_path, capsys):
    """K4/D3：`--align key` 无 `--key` → exit 3，且**不产出任何** run 目录（不伪造结论）。"""
    out = tmp_path / "runs"
    code = main([
        "run", "--pipeline", str(PIPELINES / "pandas.json"),
        "--input", str(sample_csv), "--out-dir", str(out),
    ])
    assert code == exitcodes.USAGE
    assert not out.exists(), "拒绝运行时不该落下任何产物"
    assert "未声明主键" in capsys.readouterr().err


def test_position_align_does_not_require_key(sample_csv, tmp_path):
    """显式 `--align position` 不要求 `--key`（对齐策略的选择权在人手里）。"""
    code = main([
        "run", "--pipeline", str(PIPELINES / "pandas.json"),
        "--input", str(sample_csv), "--align", "position", "--out-dir", str(tmp_path / "runs"),
    ])
    assert code == exitcodes.USAGE  # 仍是"拒绝判定"，但不是因为缺主键
    assert (tmp_path / "runs").is_dir(), "position 对齐应真的跑起来"


def test_missing_input_file_is_usage_error(tmp_path):
    code = main([
        "run", "--pipeline", str(PIPELINES / "pandas.json"),
        "--input", str(tmp_path / "nope.csv"), "--key", "id", "--out-dir", str(tmp_path / "runs"),
    ])
    assert code == exitcodes.USAGE


def test_missing_dependency_is_usage_error_and_recorded(sample_csv, tmp_path, monkeypatch, capsys):
    """缺依赖 → exit 3（不是 1/2），且 stages.json 里有 failed 记录。"""
    from tripwire.pipeline import stages as stages_pkg
    from tripwire.pipeline.errors import StageUnavailable

    def _unavailable(_text):
        raise StageUnavailable("pandas_csv", "pandas 未安装（模拟）")

    monkeypatch.setitem(stages_pkg.RUNNERS, "pandas_csv", _unavailable)
    out = tmp_path / "runs"
    code = main([
        "run", "--pipeline", str(PIPELINES / "pandas.json"),
        "--input", str(sample_csv), "--key", "id", "--out-dir", str(out),
    ])
    assert code == exitcodes.USAGE
    err = capsys.readouterr().err
    assert "阶段不可用" in err
    stages_json = next(out.glob("*/stages.json"))
    assert '"failed"' in stages_json.read_text(encoding="utf-8")


# ── 交付态四条：0 / 1 / 2 / 3（M5 DoD；全部走真实 CLI 入口）──────────────

def _run_or_report(args: list[str]) -> int:
    """`main(argv)` 与真实进程各跑一遍，断言两者一致（同一条命令、同一串参数）。"""
    from_main = main(list(args))
    result = _run_cli(args)
    assert result.returncode == from_main, (
        f"main() 返回 {from_main}，真实进程退出码 {result.returncode}\n"
        f"stdout={result.stdout[:400]}\nstderr={result.stderr[:400]}"
    )
    return from_main


def test_exit_0_lossless_and_gate_passed(control_only_csv, tmp_path, capsys):
    """**0 = 无损（无差异 且 门禁通过）**：控制组单独成表 + 本阶段 0 条真值。

    `LOSSLESS` 与"空跑通过"是同一件事的两面（`expected.json` 只登记会变的格），
    所以这一条同时要看到 exit 0 **与** "空跑"的显式提示（不许被读成"覆盖了样本"）。
    """
    empty = tmp_path / "empty_expected.json"
    empty.write_text('{\n  "cells": []\n}\n', encoding="utf-8")
    out_dir = tmp_path / "runs"
    args = [
        "run", "--pipeline", str(PIPELINES / "json_sqlite.json"),
        "--input", str(control_only_csv), "--key", "id",
        "--out-dir", str(out_dir), "--expected", str(empty),
    ]
    code = _run_or_report(args)
    out = capsys.readouterr().out
    assert code == exitcodes.LOSSLESS
    assert out.splitlines()[0].startswith("VERDICT: LOSSLESS ")
    assert "空跑通过" in out
    assert (out_dir / _run_id_of(out_dir) / "report.json").is_file()


def test_exit_1_lossy_and_gate_passed(tmp_path, capsys):
    """**1 = 有损（存在差异 且 门禁通过）**：金样本走 `json_sqlite_csv`。"""
    out_dir = tmp_path / "runs"
    args = [
        "run", "--pipeline", str(PIPELINES / "json_sqlite.json"),
        "--input", str(GOLDEN / "orig.csv"), "--key", "id",
        "--out-dir", str(out_dir), "--expected", str(GOLDEN / EXPECTED_NAME),
    ]
    code = _run_or_report(args)
    out = capsys.readouterr().out
    assert code == exitcodes.LOSSY
    assert out.splitlines()[0].startswith("VERDICT: LOSSY ")
    assert out.splitlines()[1].startswith("FIRST LOSS AT: stage 1 = json_sqlite_csv (")
    assert out.splitlines()[2] == "GATE: recall 1.00 precision 1.00 unclassified 0"


def test_exit_2_gate_failed(tmp_path, capsys):
    """**2 = 门禁失败**：真值只留一条期望 → recall 1.00 但 precision 崩（有真值、没对上）。"""
    payload = json.loads((GOLDEN / EXPECTED_NAME).read_text(encoding="utf-8"))
    doctored = tmp_path / "doctored.json"
    doctored.write_text(
        json.dumps({"cells": payload["cells"][:1]}, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "runs"
    args = [
        "run", "--pipeline", str(PIPELINES / "json_sqlite.json"),
        "--input", str(GOLDEN / "orig.csv"), "--key", "id",
        "--out-dir", str(out_dir), "--expected", str(doctored),
    ]
    code = _run_or_report(args)
    captured = capsys.readouterr()
    assert code == exitcodes.GATE_FAILED
    assert "GATE FAILED" in captured.err
    # 报告仍然产出：门禁失败是**判定**，不是"拒绝运行"——留档要看得到为什么失败
    assert (out_dir / _run_id_of(out_dir) / "report.sarif").is_file()
    sarif = json.loads((out_dir / _run_id_of(out_dir) / "report.sarif").read_text(encoding="utf-8"))
    assert sarif["runs"][0]["invocations"][0]["executionSuccessful"] is False
    assert sarif["runs"][0]["invocations"][0]["exitCode"] == exitcodes.GATE_FAILED


def test_exit_3_usage_channel(tmp_path, capsys):
    """**3 = 用法错误 / 拒绝运行**：拼不出判定就一律 3，绝不混进 0/1/2。"""
    # 1) `run` 没给真值：没有 recall/precision 就没有门禁三数 → 拒绝判定
    code = main([
        "run", "--pipeline", str(PIPELINES / "json_sqlite.json"),
        "--input", str(GOLDEN / "orig.csv"), "--key", "id",
        "--out-dir", str(tmp_path / "runs"),
    ])
    assert code == exitcodes.USAGE
    assert code not in exitcodes.VERDICT_CODES
    # 2) `report` 没给真值（`--expected` 必填 → argparse → 3）
    assert main(["report", "--run-id", "x", "--out-dir", str(tmp_path)]) == exitcodes.USAGE
    # 3) 无主键 + key 对齐（K4）
    assert main([
        "run", "--pipeline", str(PIPELINES / "json_sqlite.json"),
        "--input", str(GOLDEN / "orig.csv"), "--out-dir", str(tmp_path / "runs"),
    ]) == exitcodes.USAGE
    # 4) 未知报告格式
    assert main([
        "report", "--run-id", "x", "--out-dir", str(tmp_path),
        "--expected", str(GOLDEN / EXPECTED_NAME), "--key", "id", "--format", "xml",
    ]) == exitcodes.USAGE
    assert capsys.readouterr().err  # 拒绝时要在 stderr 说清原因


def _run_id_of(out_dir: Path) -> str:
    """`runs/` 下唯一的 run 目录名（`run_id` 由内容派生，测试不该手抄）。"""
    dirs = [path.name for path in out_dir.iterdir() if path.is_dir()]
    assert len(dirs) == 1, dirs
    return dirs[0]


# ── 判定通道：M5 的显式改写 ──────────────────────────────────────────────

def test_run_refuses_verdict_without_truth_and_uses_gate_with_it(sample_csv, tmp_path, capsys):
    """**显式改写 M1 的守卫**（原断言"不产出有损/无损判定"随 `NO_VERDICT_NOTE` 一起删）。

    M5 把判定通道接到了 `run --expected` 上，所以守卫必须**两条都成立**：

    - 无真值：exit 3、**不打印** `VERDICT:` 行、并把"怎么拿到判定"写清楚；
    - 有真值：落进判定通道（0/1/2），第一行就是 `VERDICT:` —— 码来自 `compute_gate`。
    """
    # ① 无真值：拒绝判定，且不许伪造三段
    out_dir = tmp_path / "runs"
    code = main([
        "run", "--pipeline", str(PIPELINES / "json_sqlite.json"),
        "--input", str(sample_csv), "--key", "id", "--out-dir", str(out_dir),
    ])
    captured = capsys.readouterr()
    assert code == exitcodes.USAGE
    assert code not in exitcodes.VERDICT_CODES, "无真值的 run 不许落入判定通道"
    assert "VERDICT:" not in captured.out, "无真值却打印了判定三段（伪造结论）"
    assert "PASS" in captured.out, "跑通了就要明说跑通了（与'拒绝判定'分开写）"
    assert "不产出有损/无损判定" in captured.out
    assert "--expected" in captured.out

    # ② 有真值：判定通道 + 首屏三段（金样本在 json_sqlite 上是有损且门禁通过）
    with_truth = tmp_path / "runs2"
    code = main([
        "run", "--pipeline", str(PIPELINES / "json_sqlite.json"),
        "--input", str(GOLDEN / "orig.csv"), "--key", "id",
        "--out-dir", str(with_truth), "--expected", str(GOLDEN / EXPECTED_NAME),
    ])
    captured = capsys.readouterr()
    assert code in exitcodes.VERDICT_CODES
    assert code == exitcodes.LOSSY
    assert captured.out.splitlines()[0].startswith("VERDICT: LOSSY ")
    assert captured.out.splitlines()[2].startswith("GATE: recall ")  # 来自 Gate.line()


def test_run_exit_code_matches_process_exit_code(sample_csv, tmp_path):
    """`main()` 返回值与真实进程退出码一致（无真值 → 用法通道）。"""
    result = _run_cli([
        "run", "--pipeline", str(PIPELINES / "json_sqlite.json"),
        "--input", str(sample_csv), "--key", "id", "--out-dir", str(tmp_path / "runs"),
    ])
    assert result.returncode == exitcodes.USAGE
    assert "PASS" in result.stdout


def test_unavailable_stage_via_subprocess_exits_3(sample_csv, tmp_path):
    """缺依赖在**真实进程**里也是 3，且不会因为未捕获异常变成 1。"""
    if stages.probe("excel_com_csv")[0]:
        # 本机有 Excel：改用一条不存在的声明路径来验"同一出口"
        result = _run_cli([
            "run", "--pipeline", str(tmp_path / "nope.json"),
            "--input", str(sample_csv), "--key", "id", "--out-dir", str(tmp_path / "runs"),
        ])
        assert result.returncode == exitcodes.USAGE
        assert "管线声明非法" in result.stderr
        return
    result = _run_cli([
        "run", "--pipeline", str(PIPELINES / "excel_com.json"),
        "--input", str(sample_csv), "--key", "id", "--out-dir", str(tmp_path / "runs"),
    ])
    assert result.returncode == exitcodes.USAGE
    assert result.returncode != 1, "traceback 未被接住时会变成 1——那会被读成'有损'"
    assert "阶段不可用" in result.stderr


# ── 其它既有通道不许回归 ──────────────────────────────────────────────────

def test_validate_pipeline_and_selftest_still_green():
    files = sorted(str(path) for path in PIPELINES.glob("*.json"))
    assert main(["validate-pipeline", *files]) == exitcodes.LOSSLESS
    assert main(["selftest"]) == exitcodes.LOSSLESS


def test_selftest_reports_stage_availability(capsys):
    """`selftest` 要把四条通道的可用性写出来：不可用是事实，不是"忘了提"。"""
    assert main(["selftest"]) == exitcodes.LOSSLESS
    out = capsys.readouterr().out
    for name in ("pandas_csv", "excel_com_csv", "openpyxl_csv", "json_sqlite_csv"):
        assert name in out
    assert "UNAVAILABLE" not in out or "Excel COM" in out or "pywin32" in out
