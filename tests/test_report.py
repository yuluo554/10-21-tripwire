"""M5 报告测试（出口门 E5 的一半：`pytest -q tests/test_report.py tests/test_exit_codes.py`）。

这组测试的靶子是 **G7 + G9 + G10 + G11 + G12 + K9 + K11**：

- **首屏三段**：`VERDICT:` / `FIRST LOSS AT:` / `GATE:` 的字面与**顺序**，且第三段
  **等于** `Gate.line()`——不是三处渲染器各拼一份格式串（"换一个格式，这一行会变吗？"）；
- **G7 三格式同源**：MD / JSON / SARIF 的 finding 集合按 `fingerprint` 一一相等；
- **G9 双跑逐字节一致**：同输入两次 run（不同 out-dir）的三个报告文件逐字节相同；
  同一 `RunResult` 渲染两次也逐字节相同 —— 报告不含时间戳、不读时钟；
- **G10 零网络**：AST 扫描 `src/tripwire/**` 无 `requests` / `urllib*` / `http` / `socket`；
- **"渲染器只读 `RunResult`"**：AST 扫描三个渲染器 —— 不 import 差异层 / 规则层 / 门禁 /
  管线，也不 `open()` / `read_text()` 回头读 `runs/`；首屏三段的字面只出现在 `model.py`；
- **K11 写盘单点**：`src/tripwire/**` 里不出现文件式裸 `json.dump(`；
- **SARIF 2.1.0** 的逐条形状 + **不写绝对路径**；
- **G12**：`rules.json` 能从**包内**读到（`importlib.resources` 的机制面）。

真机通道以 `json_sqlite_csv` 为主（stdlib、快、确定），`openpyxl_csv` / `excel_com_csv`
各跑一条"阶段名 + 运行时指纹"的对照；不可用时**显式 skip 并标注**，不假绿。
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from tripwire import exitcodes
from tripwire.cli import main
from tripwire.csvio import parse_csv_text
from tripwire.diff import diff_tables
from tripwire.gate import compute_gate
from tripwire.pipeline import stages
from tripwire.pipeline.model import RuntimeMeta
from tripwire.pipeline.runner import load_run, run_pipeline
from tripwire.pipeline.schema import load_pipeline
from tripwire.report import (
    FORMATS,
    REPORT_FILENAMES,
    build_run_result,
    load_expected,
    render_json,
    render_md,
    render_sarif,
    runtime_label,
    write_reports,
)
from tripwire.report.model import RunResult
from tripwire.rules.engine import attribute

REPO_ROOT = Path(__file__).resolve().parents[1]
PIPELINES = REPO_ROOT / "pipelines"
GOLDEN = REPO_ROOT / "fixtures" / "golden"
PACKAGE = REPO_ROOT / "src" / "tripwire"
REPORT_DIR = PACKAGE / "report"
MODULES = ("model.py", "render_md.py", "render_json.py", "render_sarif.py")
RENDERERS = ("render_md.py", "render_json.py", "render_sarif.py")

#: 首屏三段的第二段：三种合法形态（`docs/report-schema.md` §三）
FIRST_LOSS_RE = re.compile(
    r"^FIRST LOSS AT: (none|unknown \(no snapshot stage carried the change\)|"
    r"stage \d+ = [A-Za-z0-9_]+ \(.+\))$"
)
GATE_RE = re.compile(r"^GATE: recall \d\.\d\d precision \d\.\d\d unclassified \d+$")


# ── 夹具 ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def golden_run(tmp_path_factory) -> tuple[Path, object]:
    """金样本走 `json_sqlite_csv` 真机跑一次（module 级：这一组测试共用同一份产物）。"""
    available, reason = stages.probe("json_sqlite_csv")
    if not available:
        pytest.skip(f"json_sqlite_csv 不可用，跳过并标注: {reason}")
    out_dir = tmp_path_factory.mktemp("m5-runs")
    run = run_pipeline(load_pipeline(PIPELINES / "json_sqlite.json"), GOLDEN / "orig.csv", out_dir)
    return out_dir, run


def _golden_expected() -> list:
    return load_expected(GOLDEN / "expected.json")


def _report_cli(run, out_dir: Path, extra: list[str] | None = None) -> int:
    return main(
        [
            "report",
            "--run-id",
            run.run_id,
            "--out-dir",
            str(out_dir),
            "--expected",
            str(GOLDEN / "expected.json"),
            "--key",
            "id",
            *(extra or []),
        ]
    )


def _read_reports(run_dir: Path) -> tuple[str, dict, dict]:
    md = (run_dir / REPORT_FILENAMES["md"]).read_text(encoding="utf-8")
    payload = json.loads((run_dir / REPORT_FILENAMES["json"]).read_text(encoding="utf-8"))
    sarif = json.loads((run_dir / REPORT_FILENAMES["sarif"]).read_text(encoding="utf-8"))
    return md, payload, sarif


def _fingerprints(md: str, payload: dict, sarif: dict) -> tuple[list[str], list[str], list[str]]:
    """三格式各自的 finding 集合（都按 `fingerprint` 对齐，见 K10 / G7）。"""
    from_md = re.findall(r"^\| `([0-9a-f]{16})` \|", md, re.MULTILINE)
    from_json = [item["fingerprint"] for item in payload["findings"]]
    from_sarif = [
        item["partialFingerprints"]["primaryLocationLineHash"]
        for item in sarif["runs"][0]["results"]
    ]
    return sorted(from_md), sorted(from_json), sorted(from_sarif)


def _import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _tripwire_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names if alias.name.startswith("tripwire"))
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("tripwire"):
            names.add(node.module)
    return names


def _package_files() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def _empty_result(**overrides) -> RunResult:
    """一份"无损"内存结果：只用来钉字面，不触盘。"""
    gate = compute_gate([], [], stage_name="pandas_csv")
    values = dict(
        run_id="0123456789abcdef",
        pipeline="pandas",
        stage_index=1,
        stage_name="pandas_csv",
        stage_runtime=RuntimeMeta(pandas_version="3.0.6"),
        strategy="key",
        key="id",
        stages=(),
        diffs=(),
        structures=(),
        attributions=(),
        gate=gate,
        rows_compared=0,
        cells_compared=0,
    )
    values.update(overrides)
    return RunResult(**values)


# ── 首屏三段（字面 + 顺序）───────────────────────────────────────────────

def test_first_screen_three_lines(golden_run, capsys):
    """`report` 的前三行就是首屏三段，顺序固定（`plan/03` M5）。"""
    out_dir, run = golden_run
    code = _report_cli(run, out_dir)
    lines = capsys.readouterr().out.splitlines()[:3]
    assert code == exitcodes.LOSSY
    assert re.fullmatch(r"VERDICT: LOSSY \(\d+/\d+ cells, \d+ rules\)", lines[0])
    assert lines[1].startswith("FIRST LOSS AT: stage 1 = json_sqlite_csv (")
    assert FIRST_LOSS_RE.match(lines[1]), lines[1]
    assert lines[2] == "GATE: recall 1.00 precision 1.00 unclassified 0"
    assert GATE_RE.match(lines[2])


def test_gate_line_comes_from_gate_not_reassembled(golden_run):
    """第三段整行**等于** `Gate.line()`：三处渲染器不许各拼一份格式串（K9 的判据）。"""
    out_dir, run = golden_run
    result = build_run_result(run, _golden_expected(), key="id", strategy="key")
    assert result.first_screen()[2] == result.gate.line()

    _report_cli(run, out_dir)
    md, payload, sarif = _read_reports(run.out_dir)
    gate_line = result.gate.line()
    assert md.splitlines()[2] == gate_line
    assert payload["first_screen"][2] == gate_line
    assert sarif["runs"][0]["properties"]["firstScreen"][2] == gate_line
    # 数字也来自同一个 Gate（不是渲染器自己算的 recall / precision）
    assert payload["gate"]["recall"] == result.gate.recall == 1.0
    assert payload["gate"]["precision"] == result.gate.precision == 1.0
    assert payload["gate"]["counts"]["reported"] == len(result.attributions)


def test_lossless_first_screen_literals():
    """无损时的三段字面（`plan/03` M5 只写了 VERDICT 行，另两行在 `docs/report-schema.md` §三）。"""
    result = _empty_result()
    assert result.first_screen() == (
        "VERDICT: LOSSLESS (0/0 cells, 0 rules)",
        "FIRST LOSS AT: none",
        "GATE: recall 1.00 precision 1.00 unclassified 0",
    )
    assert result.verdict == "LOSSLESS"
    assert result.exit_code == exitcodes.LOSSLESS


def test_vacuous_gate_does_not_fake_coverage():
    """空跑（`reported == 0`）不算"覆盖了样本"：`Gate.vacuous` 必须标出来（M4 不变量 29）。"""
    result = _empty_result()
    assert result.gate.vacuous is True
    assert result.gate.passed is True
    assert result.exit_code == exitcodes.LOSSLESS
    md = render_md.render(result)
    assert "空跑" in md and "不代表覆盖了任何样本" in md


def test_runtime_label_per_channel():
    """括号里的运行时指纹按通道分族；拼不出任何一部分就写 `unknown`（**不省略整行**）。"""
    assert runtime_label("excel_com_csv", RuntimeMeta(excel_version="16.0", excel_build="20326")) == (
        "Excel 16.0 Build 20326"
    )
    assert runtime_label("pandas_csv", RuntimeMeta(pandas_version="3.0.6")) == "pandas 3.0.6"
    assert runtime_label("openpyxl_csv", RuntimeMeta(openpyxl_version="3.1.5")) == "openpyxl 3.1.5"
    assert runtime_label("json_sqlite_csv", RuntimeMeta(sqlite_version="3.49.1")) == "SQLite 3.49.1"
    assert runtime_label("excel_com_csv", RuntimeMeta()) == "unknown"
    assert runtime_label("input", RuntimeMeta(pandas_version="3.0.6")) == "unknown"

    # 阶段 runtime 为空时写 unknown，**不省略整行**
    blank = _empty_result(
        stage_name="excel_com_csv",
        stage_runtime=RuntimeMeta(),
        diffs=(_diff_record(),),
        attributions=(attribute((_diff_record(),))[0],),
    )
    assert "FIRST LOSS AT: unknown" in blank.first_loss_line()


def _diff_record():
    from tripwire.diff import DiffRecord

    return DiffRecord(row_key="ctl-1", col="zip", col_index=1, orig_text="a", got_text="b")


def test_lossless_run_says_vacuous_clearly(control_only_csv, tmp_path, capsys):
    """0 = 无损 + 门禁通过；但空跑要**说清楚**（`Gate.vacuous` 的 M5 落地）。"""
    empty = tmp_path / "empty_expected.json"
    empty.write_text('{\n  "cells": []\n}\n', encoding="utf-8")
    code = main(
        [
            "run",
            "--pipeline",
            str(PIPELINES / "json_sqlite.json"),
            "--input",
            str(control_only_csv),
            "--key",
            "id",
            "--out-dir",
            str(tmp_path / "runs"),
            "--expected",
            str(empty),
        ]
    )
    out = capsys.readouterr().out
    lines = out.splitlines()[:3]
    assert code == exitcodes.LOSSLESS
    assert lines[0] == "VERDICT: LOSSLESS (0/480 cells, 0 rules)"
    assert lines[1] == "FIRST LOSS AT: none"
    assert lines[2] == "GATE: recall 1.00 precision 1.00 unclassified 0"
    assert "空跑通过" in out, "空跑不许被读成'门禁通过且覆盖了样本'"


def test_stage_name_is_the_real_one(golden_run, capsys):
    """`FIRST LOSS AT` 必须是 M1 的真实 stage 名（K3：`openpyxl_csv` 不得写成 `excel_csv`）。"""
    out_dir, run = golden_run
    _report_cli(run, out_dir)
    second = capsys.readouterr().out.splitlines()[1]
    assert "json_sqlite_csv" in second
    assert "excel" not in second.lower()


@pytest.mark.parametrize("pipeline_file", ["openpyxl.json", "excel_com.json"])
def test_first_loss_names_other_channels(pipeline_file, tmp_path, capsys):
    """`openpyxl_csv` / `excel_com_csv` 各跑一条：阶段名与运行时指纹都要写对（不可用则 skip）。"""
    stage_name = {"openpyxl.json": "openpyxl_csv", "excel_com.json": "excel_com_csv"}[pipeline_file]
    available, reason = stages.probe(stage_name)
    if not available:
        pytest.skip(f"{stage_name} 不可用，跳过并标注: {reason}")
    code = main(
        [
            "run",
            "--pipeline",
            str(PIPELINES / pipeline_file),
            "--input",
            str(GOLDEN / "orig.csv"),
            "--key",
            "id",
            "--out-dir",
            str(tmp_path / "runs"),
            "--expected",
            str(GOLDEN / "expected.json"),
        ]
    )
    second = capsys.readouterr().out.splitlines()[1]
    assert code == exitcodes.LOSSY
    assert second.startswith(f"FIRST LOSS AT: stage 1 = {stage_name} (")
    if stage_name == "openpyxl_csv":
        assert "excel" not in second.lower()
    else:
        assert re.search(r"\(Excel \d+\.\d+ Build \d+\)$", second), second


# ── G7：三格式同源 ────────────────────────────────────────────────────────

def test_three_formats_same_findings(golden_run):
    """MD / JSON / SARIF 的 finding 集合按 `fingerprint` 相等（G7 的判据）。"""
    out_dir, run = golden_run
    assert _report_cli(run, out_dir) == exitcodes.LOSSY
    md, payload, sarif = _read_reports(run.out_dir)
    from_md, from_json, from_sarif = _fingerprints(md, payload, sarif)
    expected = build_run_result(run, _golden_expected(), key="id", strategy="key")
    assert from_json == from_sarif == from_md
    assert len(from_json) == len(expected.attributions)
    assert len(from_json) > 0, "金样本必须真的产出 finding（空集相等是假同源）"


def test_first_screen_carried_by_all_three_formats(golden_run):
    """首屏三段三格式都在，且是**同一串字符**（换格式不改这一行）。"""
    out_dir, run = golden_run
    _report_cli(run, out_dir)
    md, payload, sarif = _read_reports(run.out_dir)
    lines = payload["first_screen"]
    assert md.splitlines()[:3] == lines
    assert sarif["runs"][0]["properties"]["firstScreen"] == lines


def test_unclassified_is_a_first_class_finding(tmp_path):
    """`unclassified` 也是 finding：三格式都带上它（D4：不塞进"其他"、不静默丢弃）。"""
    baseline = parse_csv_text("id,zip,note\nctl-1,94016,lorem\nctl-2,94016,ipsum\n")
    got = parse_csv_text("id,zip,note\nctl-1,94016,changed\nctl-2,94016,ipsum\n")
    result = diff_tables(baseline, got, strategy="key", key="id")
    attributions = attribute(result.diffs)
    assert [item.rule for item in attributions] == ["unclassified"]

    run_result = _empty_result(
        diffs=tuple(result.diffs),
        attributions=tuple(attributions),
        gate=compute_gate([], attributions, stage_name="pandas_csv"),
    )
    assert run_result.unclassified_count == 1
    assert run_result.verdict == "LOSSY"
    # 一条 unclassified 就够判门禁失败（D4：unclassified 是**条数**不是比例）
    assert run_result.exit_code == exitcodes.GATE_FAILED

    written = write_reports(run_result, tmp_path)
    assert len(written) == len(FORMATS)
    md, payload, sarif = _read_reports(tmp_path)
    from_md, from_json, from_sarif = _fingerprints(md, payload, sarif)
    assert from_json == from_sarif == from_md and len(from_json) == 1
    assert payload["findings"][0]["rule"] == "unclassified"
    results = sarif["runs"][0]["results"]
    assert {item["ruleId"] for item in results} == {"unclassified"}
    assert "unclassified" in [rule["id"] for rule in sarif["runs"][0]["tool"]["driver"]["rules"]]
    assert from_sarif == [results[0]["partialFingerprints"]["primaryLocationLineHash"]]


# ── SARIF 形状（plan/03 M5）───────────────────────────────────────────────

def test_sarif_shape_and_no_absolute_paths(golden_run):
    """SARIF 2.1.0 的逐条形状 + **不写绝对路径**（uri 只有 `stage-<k>.csv`）。"""
    out_dir, run = golden_run
    assert _report_cli(run, out_dir) == exitcodes.LOSSY
    _, payload, sarif = _read_reports(run.out_dir)
    assert sarif["version"] == "2.1.0"
    assert sarif["$schema"] == "https://json.schemastore.org/sarif-2.1.0.json"
    block = sarif["runs"][0]
    assert block["tool"]["driver"]["name"] == "tripwire"
    declared = {rule["id"] for rule in block["tool"]["driver"]["rules"]}
    assert block["results"], "金样本必须真的产出 SARIF result"
    artifact = f"stage-{payload['stage']['index']}.csv"
    for item in block["results"]:
        assert item["ruleId"] in declared
        assert item["level"] == "warning"
        assert item["message"]["text"]
        assert re.fullmatch(
            r"[0-9a-f]{16}", item["partialFingerprints"]["primaryLocationLineHash"]
        )
        uri = item["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
        assert uri == artifact
        assert "/" not in uri and "\\" not in uri and ":" not in uri
    assert block["artifacts"][0]["location"]["uri"] == artifact
    assert block["invocations"][0]["exitCode"] == payload["exit_code"]
    assert block["invocations"][0]["executionSuccessful"] is payload["gate"]["passed"]

    for name in REPORT_FILENAMES.values():
        text = (run.out_dir / name).read_text(encoding="utf-8")
        assert str(run.out_dir) not in text, f"{name} 写进了 run 目录的绝对路径"
        assert not re.search(r"\b[A-Za-z]:[\\/]", text), f"{name} 写进了盘符绝对路径"
        assert "\r\n" not in text, f"{name} 含 CRLF（K11：报告一律 LF）"


# ── G9：双跑 / 两次渲染逐字节一致 ─────────────────────────────────────────

def test_render_is_clock_free(golden_run):
    """同一 `RunResult` 渲染两次逐字节相同；报告层 AST 里没有时钟/随机/网络。"""
    _, run = golden_run
    result = build_run_result(run, _golden_expected(), key="id", strategy="key")
    assert render_md.render(result) == render_md.render(result)
    assert render_json.render(result) == render_json.render(result)
    assert render_sarif.render(result) == render_sarif.render(result)
    assert render_md.render(result) == render_md.render(
        build_run_result(run, _golden_expected(), key="id", strategy="key")
    )

    forbidden_modules = {"time", "datetime", "random", "secrets", "uuid", "socket", "urllib", "requests"}
    forbidden_calls = {"now", "today", "utcnow", "monotonic", "time", "random", "uuid1", "uuid4"}
    for name in MODULES:
        path = REPORT_DIR / name
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_modules, f"{name}: {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in forbidden_modules, f"{name}: {node.module}"
            elif isinstance(node, ast.Call):
                called = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                assert called not in forbidden_calls, f"{name} 里出现读时钟/随机的调用: {called}"


def test_same_input_two_runs_byte_identical(golden_run, tmp_path):
    """G9：同输入两次 run（不同 out-dir）→ 三个报告文件逐字节一致，fingerprint 集合也相等。"""
    _, run = golden_run
    again = run_pipeline(
        load_pipeline(PIPELINES / "json_sqlite.json"), GOLDEN / "orig.csv", tmp_path / "other"
    )
    assert again.run_id == run.run_id, "run_id 由内容派生（K2）：同输入必须同 id"

    first = build_run_result(run, _golden_expected(), key="id", strategy="key")
    second = build_run_result(load_run(again.out_dir), _golden_expected(), key="id", strategy="key")
    assert first.rules_used == second.rules_used
    assert sorted(item.fingerprint for item in first.attributions) == sorted(
        item.fingerprint for item in second.attributions
    )

    write_reports(first, run.out_dir, FORMATS)
    write_reports(second, again.out_dir, FORMATS)
    for name in REPORT_FILENAMES.values():
        assert (run.out_dir / name).read_bytes() == (again.out_dir / name).read_bytes(), name


# ── 渲染器只读 RunResult（结构守门）───────────────────────────────────────

def test_renderers_only_read_run_result():
    """三个渲染器不 import 差异/规则/门禁/管线，也不回头读 `runs/`（`plan/02` §一 红线 4）。"""
    forbidden_prefixes = (
        "tripwire.diff",
        "tripwire.rules",
        "tripwire.gate",
        "tripwire.pipeline",
        "tripwire.csvio",
        "tripwire.fixtures",
        "tripwire.cli",
    )
    for name in RENDERERS:
        path = REPORT_DIR / name
        text = path.read_text(encoding="utf-8")
        for imported in _tripwire_imports(path):
            assert not imported.startswith(forbidden_prefixes), f"{name} import {imported}（各自重算了）"
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Call):
                called = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                assert called not in {"open", "read_text", "read_bytes", "read_csv"}, (
                    f"{name} 回头读了盘（{called}）——渲染器只许读 RunResult"
                )
        for literal in ("VERDICT:", "FIRST LOSS AT:", "GATE: recall"):
            assert literal not in text, f"{name} 自己拼了一份格式串: {literal}"

    # 首屏三段的字面只在 model.py 里拼一次（gate.py 是 GATE 行的唯一来源，不在本目录）
    model_text = (REPORT_DIR / "model.py").read_text(encoding="utf-8")
    for literal in ("VERDICT:", "FIRST LOSS AT:"):
        assert literal in model_text, f"首屏字面不在 model.py 里（跑丢了？）: {literal}"


def test_no_network_imports_in_package():
    """G10：`src/tripwire/**` 不 import 任何网络库（纯本地、零网络是红线）。"""
    forbidden = {"requests", "urllib", "http", "socket", "httpx", "aiohttp", "ftplib", "smtplib"}
    offenders = []
    for path in _package_files():
        bad = _import_roots(path) & forbidden
        if bad:
            offenders.append(f"{path.relative_to(REPO_ROOT)}: {sorted(bad)}")
    assert offenders == [], offenders
    assert len(_package_files()) >= 15, "扫描面太小（判据可能空跑）"


def test_no_bare_json_dump_in_package():
    """K11：文件式落盘一律走 `serialization`，`src/tripwire/**` 里不许出现裸 `json.dump(`。"""
    offenders = []
    for path in _package_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "dump"
                and getattr(node.func.value, "id", None) == "json"
            ):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    assert offenders == [], offenders


# ── report 接线 / 拒绝判定 ────────────────────────────────────────────────

def test_report_writes_three_files_and_keeps_stages_json(golden_run):
    """产物落 `runs/<run_id>/report.{md,json,sarif}`；**不改写** `stages.json` 与快照。"""
    out_dir, run = golden_run
    before = {path.name: path.read_bytes() for path in run.out_dir.iterdir() if path.is_file()}
    assert _report_cli(run, out_dir) == exitcodes.LOSSY
    after = {path.name: path.read_bytes() for path in run.out_dir.iterdir() if path.is_file()}
    for name in REPORT_FILENAMES.values():
        assert name in after and after[name], f"缺 {name}"
    for name, payload in before.items():
        assert after[name] == payload, f"{name} 被报告改写（报告只读产物）"
    assert after[REPORT_FILENAMES["json"]].endswith(b"\n")
    assert b"\r\n" not in after[REPORT_FILENAMES["json"]]


def test_report_format_selection(golden_run):
    """`--format` 只写被点名的格式；未知格式 → exit 3（用法通道，不是门禁失败）。"""
    out_dir, run = golden_run
    for name in REPORT_FILENAMES.values():
        (run.out_dir / name).unlink(missing_ok=True)
    assert _report_cli(run, out_dir, ["--format", "json"]) == exitcodes.LOSSY
    assert (run.out_dir / "report.json").is_file()
    assert not (run.out_dir / "report.md").exists()
    assert not (run.out_dir / "report.sarif").exists()
    assert _report_cli(run, out_dir, ["--format", "md,md,json"]) == exitcodes.LOSSY
    assert _report_cli(run, out_dir, ["--format", "yaml"]) == exitcodes.USAGE
    assert _report_cli(run, out_dir, ["--format", ""]) == exitcodes.USAGE
    _report_cli(run, out_dir)  # 复原三份产物，后面的测试按"三件齐"读


def test_report_refuses_without_truth(golden_run, tmp_path, capsys):
    """没有真值就没有 recall/precision → 拒绝判定（exit 3），而不是编一个 GATE 行。"""
    out_dir, run = golden_run
    # 1) 不给 --expected：argparse 直接挡（`--expected` 必填）
    assert main(["report", "--run-id", run.run_id, "--out-dir", str(out_dir)]) == exitcodes.USAGE
    # 2) run 不存在
    assert (
        main(
            [
                "report",
                "--run-id",
                "does-not-exist",
                "--out-dir",
                str(out_dir),
                "--expected",
                str(GOLDEN / "expected.json"),
                "--key",
                "id",
            ]
        )
        == exitcodes.USAGE
    )
    assert "读不到该 run" in capsys.readouterr().err
    # 3) 真值文件不存在
    assert (
        main(
            [
                "report",
                "--run-id",
                run.run_id,
                "--out-dir",
                str(out_dir),
                "--expected",
                str(tmp_path / "nope.json"),
                "--key",
                "id",
            ]
        )
        == exitcodes.USAGE
    )
    err = capsys.readouterr().err
    assert "真值文件不可读" in err
    assert "GATE:" not in err


def test_report_refuses_without_key(golden_run):
    """K4 在报告入口同样成立：`--align key` 缺 `--key` → exit 3（且不产出报告）。"""
    out_dir, run = golden_run
    (run.out_dir / REPORT_FILENAMES["md"]).unlink(missing_ok=True)
    code = main(
        [
            "report",
            "--run-id",
            run.run_id,
            "--out-dir",
            str(out_dir),
            "--expected",
            str(GOLDEN / "expected.json"),
        ]
    )
    assert code == exitcodes.USAGE
    assert not (run.out_dir / REPORT_FILENAMES["md"]).exists(), "拒绝判定时不该产出报告"
    _report_cli(run, out_dir)  # 复原三份产物


# ── G12：装好的包能读到 rules.json ────────────────────────────────────────

def test_rules_json_readable_from_package():
    """G12 的机制面：`rules.json` 走 `importlib.resources` 从**包内**读到 18 条。

    真正的"干净 venv"由收尾的 sdist / wheel 复核动作覆盖（本机无远端，写"本地等价校验"）。
    """
    from importlib import resources

    text = resources.files("tripwire.rules").joinpath("rules.json").read_text(encoding="utf-8")
    payload = json.loads(text)
    assert len(payload["rules"]) == 18
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'tripwire = ["rules/*.json"]' in pyproject, "package-data 没声明 rules.json"