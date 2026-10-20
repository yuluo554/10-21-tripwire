"""退出码测试。

**分工**：`plan/05` §三 E5 把"0/1/2/3 各一条"判给 M5（判定通道要等 M2–M4 的差异与门禁）。
M1 这里只钉两件事，且都要经**真实 CLI 入口**（`main(argv)` 与子进程各一遍）：

1. 用法通道 3 的全部来源：参数写错 / 声明非法 / 缺依赖 / 无主键 / 输入不可读；
2. **`run` 在 M1 期间不许返回 0**——0 的语义是"无损"，而此刻没有任何差异被算过。
   这条是防"跑通即绿"的守卫：一旦有人给 `run` 加个 `return LOSSLESS`，
   本文件立刻红，且 M5 接线时必须显式改写这里（而不是悄悄漂过去）。
"""

from __future__ import annotations

import csv
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tripwire import exitcodes
from tripwire.cli import main
from tripwire.pipeline import stages

REPO_ROOT = Path(__file__).resolve().parents[1]
PIPELINES = REPO_ROOT / "pipelines"

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


# ── 判定通道在 M1 期间不得被伪造 ──────────────────────────────────────────

def test_run_does_not_claim_lossless_in_m1(sample_csv, tmp_path, capsys):
    """守卫：`run` 跑通了也不许返回 0——0 是"无损"结论，M1 还没有差异引擎。

    M5 接线后本测试必须被**显式改写**（连同 `NO_VERDICT_NOTE` 一起删），
    不允许为了让测试变绿而放宽断言。
    """
    code = main([
        "run", "--pipeline", str(PIPELINES / "json_sqlite.json"),
        "--input", str(sample_csv), "--key", "id", "--out-dir", str(tmp_path / "runs"),
    ])
    captured = capsys.readouterr()
    assert code == exitcodes.USAGE
    assert code not in exitcodes.VERDICT_CODES, "M1 的 run 不许落入判定通道"
    assert "pass" not in captured.err.lower() or "FAIL" not in captured.out
    assert "PASS" in captured.out, "跑通了就要明说跑通了（与'拒绝判定'分开写）"
    assert "不产出有损/无损判定" in captured.out


def test_run_exit_code_matches_process_exit_code(sample_csv, tmp_path):
    """`main()` 返回值与真实进程退出码一致（交付态四条测试的机制，M1 先验一个码）。"""
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
