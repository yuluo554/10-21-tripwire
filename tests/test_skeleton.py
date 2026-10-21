"""骨架冒烟测试（M0）。

覆盖：版本单点、CLI 用法通道（exit 3）、声明校验、规则表 18 条、写盘单点的确定性。
M1–M5 的功能测试在各自里程碑补齐。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tripwire import __version__
from tripwire import exitcodes
from tripwire.cli import main
from tripwire.pipeline.schema import PipelineDeclError, load_pipeline, validate_pipeline_dict
from tripwire.rules.predicates import load_rules, rule_count
from tripwire.serialization import dumps_json, write_json, write_text

REPO_ROOT = Path(__file__).resolve().parents[1]
PIPELINES = REPO_ROOT / "pipelines"


def test_version_matches_pyproject():
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "dynamic = [\"version\"]" in text
    assert "version = { attr = \"tripwire.__version__\" }" in text
    assert main(["--version"]) == 0


def test_help_exits_zero(capsys):
    # `main()` 把 argparse 的 SystemExit 收成返回值：--help 必须答 0，而不是抛出去或答 3
    assert main(["--help"]) == 0
    assert "validate-pipeline" in capsys.readouterr().out


def test_no_subcommand_is_usage_error():
    assert main([]) == exitcodes.USAGE


def test_unknown_subcommand_is_usage_error():
    assert main(["nope"]) == exitcodes.USAGE


def test_missing_required_arg_is_usage_error_not_gate_failure():
    # argparse 原生是 SystemExit(2)；必须被转成 3，否则"参数写错"被读成"门禁失败"
    assert main(["run"]) == exitcodes.USAGE
    assert main(["run", "--pipeline", "x.json"]) == exitcodes.USAGE


def test_unimplemented_commands_exit_3():
    """仍在骨架期的子命令走用法通道。`diff`(M2) / `attribute`(M3) / `gen-fixture`(M4) 都已接线，不在此列。

    **`gen-fixture` 特意不在这里**：它一跑就会往 `fixtures/out/` 落文件——测试有副作用正是
    方法论要防的形态（"一次普通 pytest 静默改坏工作树"）。它的行为由 `tests/test_fixture.py`
    在 `tmp_path` 里测。
    """
    assert main(["attribute", "--run-id", "x"]) == exitcodes.USAGE
    assert main(["report", "--run-id", "x"]) == exitcodes.USAGE


def test_validate_pipeline_all_samples():
    files = sorted(str(path) for path in PIPELINES.glob("*.json"))
    assert len(files) == 4
    assert main(["validate-pipeline", *files]) == exitcodes.LOSSLESS


def test_validate_pipeline_rejects_unknown_stage(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps({"name": "x", "input": "csv", "schema_version": 1,
                    "stages": [{"stage_name": "excel_csv", "engine": "excel_com"}]}),
        encoding="utf-8",
    )
    assert main(["validate-pipeline", str(bad)]) == exitcodes.USAGE


def test_validate_pipeline_rejects_engine_stage_mismatch(tmp_path):
    # D1：禁止把 openpyxl 的结果标成 excel_com_csv
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps({"name": "x", "input": "csv", "schema_version": 1,
                    "stages": [{"stage_name": "excel_com_csv", "engine": "openpyxl"}]}),
        encoding="utf-8",
    )
    problems = validate_pipeline_dict(json.loads(bad.read_text(encoding="utf-8")))
    assert any("必须配 engine" in p for p in problems)


def test_load_pipeline_missing_file():
    with pytest.raises(PipelineDeclError):
        load_pipeline(REPO_ROOT / "pipelines" / "does-not-exist.json")


def test_rules_table_has_18():
    rules = load_rules()
    assert len(rules["rules"]) == 18
    assert rule_count() == 18
    families = {}
    for rule in rules["rules"]:
        families[rule["family"]] = families.get(rule["family"], 0) + 1
    assert families == {"numeric": 8, "null": 2, "text": 4, "time": 4}
    assert rules["families"] == families


def test_rules_cli_count(capsys):
    assert main(["rules", "--count"]) == exitcodes.LOSSLESS
    assert capsys.readouterr().out.strip() == "18"


def test_selftest_green():
    assert main(["selftest"]) == exitcodes.LOSSLESS


def test_serialization_is_deterministic(tmp_path):
    payload = {"b": 1, "a": ["中", 2], "c": {"z": None}}
    first = write_json(tmp_path / "one.json", payload)
    second = write_json(tmp_path / "two.json", payload)
    assert first.read_bytes() == second.read_bytes()
    assert b"\r\n" not in first.read_bytes()
    assert first.read_text(encoding="utf-8").endswith("\n")
    assert "中" in first.read_text(encoding="utf-8")  # ensure_ascii=False


def test_write_text_normalizes_newlines(tmp_path):
    target = write_text(tmp_path / "x.txt", "a\r\nb")
    assert target.read_bytes() == b"a\nb\n"


def test_dumps_json_is_sorted():
    assert dumps_json({"b": 1, "a": 2}).splitlines()[1].strip() == '"a": 2,'


def test_cli_runs_as_module_subprocess():
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-m", "tripwire", "--version"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert __version__ in result.stdout
