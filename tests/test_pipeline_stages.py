"""M1 阶段测试（出口门 E1）：四条通道都能跑通，且**损失形态各自不同**。

跳过纪律：`excel_com_csv` 在非 Windows / 无 Excel 的机器上**显式 skip 并写明原因**，
不得改写成"通过"（`plan/05` §四 已登记为未验证项）。其余三条在任何平台都必须真跑。

样本刻意包含会触发已知失真的值（`02114` 前导零、`1125899906842624`=2^50、
`2024-01-02` 日期、NFC/NFD 的 `é`、空串 / `NULL`），这样"某通道 0 差异"才是可解释的，
而不是"因为我们喂了干净数据"。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tripwire.csvio import read_text
from tripwire.pipeline import stages
from tripwire.pipeline.errors import StageUnavailable
from tripwire.pipeline.runner import run_pipeline
from tripwire.pipeline.schema import load_pipeline

REPO_ROOT = Path(__file__).resolve().parents[1]
PIPELINES = REPO_ROOT / "pipelines"

SAMPLE_ROWS = [
    ["id", "num_big", "zip", "decimal", "exponent", "date", "text_unicode", "nullable"],
    ["num-0001", "12345678901234567890", "02114", "19.90", "1e-7", "2024-01-02", "caf\u00e9", ""],
    ["num-0002", "1125899906842624", "00123-4567", "1.005", "1E5", "1900-02-29", "e\u0301", "NULL"],
    ["ctl-0001", "42", "90210", "10.5", "100000", "hello", "ascii", "x"],
]

PIPELINE_NAMES = ["pandas", "json_sqlite", "openpyxl", "excel_com"]


@pytest.fixture()
def sample_csv(tmp_path: Path) -> Path:
    import csv

    path = tmp_path / "sample.csv"
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerows(SAMPLE_ROWS)
    return path


def _require(stage_name: str) -> None:
    ok, reason = stages.probe(stage_name)
    if not ok:
        pytest.skip(f"{stage_name} 在本机不可用: {reason}（跳过并标注，不算已验证）")


# ── G1：三族管线可跑通 ────────────────────────────────────────────────────

def test_three_families_produce_stages(sample_csv, tmp_path):
    """`plan/03` M1 测试点：三条声明各跑一次，stage 数正确。

    stage 数 = 1（输入副本）+ len(decl.stages)。四条通道都单阶段声明，故都是 2。
    这里对四条通道全跑一遍（`plan/05` §六 DoD 要"三族各跑通一次"，
    第四条是 Excel 的 openpyxl fallback，同样算一条独立通道）。
    """
    produced = []
    for name in PIPELINE_NAMES:
        decl = load_pipeline(PIPELINES / f"{name}.json")
        try:
            run = run_pipeline(decl, sample_csv, tmp_path / "runs")
        except StageUnavailable as error:
            pytest.skip(f"{name} 不可用: {error.reason}（跳过并标注，不算已验证）")
        assert len(run.stages) == 1 + len(decl.stages)
        assert run.stages[0].stage_name == "input"
        assert [s.stage_name for s in run.outputs] == [s.stage_name for s in decl.stages]
        produced.append(name)
    assert produced, "一条通道都没跑成"


def test_stage_names_are_not_conflated(sample_csv, tmp_path):
    """D1/K3：excel_com 与 openpyxl 的 stage 名必须各自出现在自己的产物里。"""
    excel_ok = stages.probe("excel_com_csv")[0]
    openpyxl_ok = stages.probe("openpyxl_csv")[0]
    if not (excel_ok and openpyxl_ok):
        pytest.skip("需要 Excel COM 与 openpyxl 同时可用才能做『两条通道不混称』的对照")

    excel_run = run_pipeline(load_pipeline(PIPELINES / "excel_com.json"), sample_csv, tmp_path / "e")
    openpyxl_run = run_pipeline(load_pipeline(PIPELINES / "openpyxl.json"), sample_csv, tmp_path / "o")

    assert [s.stage_name for s in excel_run.outputs] == ["excel_com_csv"]
    assert [s.stage_name for s in openpyxl_run.outputs] == ["openpyxl_csv"]
    # 两个 stage 名不同 -> run_id 必须不同（否则跨通道对账会撞车）
    assert excel_run.run_id != openpyxl_run.run_id


def test_excel_and_openpyxl_differ_on_2_pow_50(sample_csv, tmp_path):
    """F1a 的机器化断言：同一格在两条通道下**损失形态不同**，证明它们不是一回事。

    `1125899906842624` = 2^50 可被 double 精确表示；Excel 仍按 15 位有效数字录入截断，
    输出 `1.1259E+15`；openpyxl 保留 `1125899906842624`。若这条断言哪天变得"相同"，
    说明有人把两条通道混成了一条——必须看见红灯，而不是悄悄放过。
    """
    if not (stages.probe("excel_com_csv")[0] and stages.probe("openpyxl_csv")[0]):
        pytest.skip("需要 Excel COM 与 openpyxl 同时可用")

    def cell_at1(run, column: str, row: int) -> str:
        from tripwire.csvio import parse_csv_text

        text = read_text(run.out_dir / "stage-1.csv")
        table = parse_csv_text(text)
        return table.cell(row, table.column_index(column))

    excel_run = run_pipeline(load_pipeline(PIPELINES / "excel_com.json"), sample_csv, tmp_path / "e")
    openpyxl_run = run_pipeline(load_pipeline(PIPELINES / "openpyxl.json"), sample_csv, tmp_path / "o")

    excel_cell = cell_at1(excel_run, "num_big", 1)
    openpyxl_cell = cell_at1(openpyxl_run, "num_big", 1)

    assert excel_cell != openpyxl_cell
    assert excel_cell.startswith("1.1259") or "E+15" in excel_cell.upper()
    assert openpyxl_cell == "1125899906842624"


# ── 各通路的已知损失形态（可解释性） ──────────────────────────────────────

def test_json_sqlite_eats_leading_zero(sample_csv, tmp_path):
    """F8：NUMERIC 亲和把 `02114` 变成 `2114`；affinity NONE 的列则保文本。"""
    run = run_pipeline(load_pipeline(PIPELINES / "json_sqlite.json"), sample_csv, tmp_path / "runs")
    from tripwire.csvio import parse_csv_text

    table = parse_csv_text(read_text(run.out_dir / "stage-1.csv"))
    zip_col = table.column_index("zip")
    assert table.cell(0, zip_col) == "2114"          # 纯数字前导零被吃
    assert table.cell(1, zip_col) == "00123-4567"    # 带连字符 -> 不是数字 -> 原样


def test_pandas_collapses_null_and_reformats_decimals(sample_csv, tmp_path):
    """F6：`''` 与 `NULL` 在默认 read_csv 后塌缩为 NaN；`19.90` -> `19.9`。"""
    run = run_pipeline(load_pipeline(PIPELINES / "pandas.json"), sample_csv, tmp_path / "runs")
    from tripwire.csvio import parse_csv_text

    table = parse_csv_text(read_text(run.out_dir / "stage-1.csv"))
    decimal_col = table.column_index("decimal")
    assert table.cell(0, decimal_col) == "19.9"
    # 空串与 NULL 落到同一形态：都是空
    nullable_col = table.column_index("nullable")
    assert table.cell(0, nullable_col) == ""
    assert table.cell(1, nullable_col) == ""


def test_openpyxl_keeps_text_and_reformats_floats(sample_csv, tmp_path):
    """openpyxl 通道：文本原样保留，数字走 `%.16g` 语义（`19.90` -> `19.9`）。"""
    _require("openpyxl_csv")
    run = run_pipeline(load_pipeline(PIPELINES / "openpyxl.json"), sample_csv, tmp_path / "runs")
    from tripwire.csvio import parse_csv_text

    table = parse_csv_text(read_text(run.out_dir / "stage-1.csv"))

    # `00123-4567` 不是数字 -> 文本原样
    assert table.cell(1, table.column_index("zip")) == "00123-4567"
    # 日期字符串不是数字 -> 原样（不变成 Excel 的 2024/1/2）
    assert table.cell(0, table.column_index("date")) == "2024-01-02"
    # 数字被重新格式化
    assert table.cell(0, table.column_index("decimal")) == "19.9"


def test_cell_kind_policy_is_pinned():
    """写入侧类型决策是我们自己的代码，必须钉死（否则归因会记到自己头上）。"""
    from tripwire.pipeline.stages.common import cell_kind

    assert cell_kind("") == "empty"
    assert cell_kind("42") == "int"
    assert cell_kind("-7") == "int"
    assert cell_kind("02114") == "text"        # 前导零 -> 文本，不替用户丢零
    assert cell_kind("19.90") == "float"
    assert cell_kind("1e-7") == "float"
    assert cell_kind("1E5") == "float"
    assert cell_kind("2024-01-02") == "text"
    assert cell_kind("1900-02-29") == "text"
    assert cell_kind("00123-4567") == "text"
    assert cell_kind("NULL") == "text"


def test_format_float_is_reversible_not_g16():
    """浮点回写必须是可逆最短表示：`%.16g` 会在读取侧再截一次，把两处损失混成一条。"""
    from tripwire.pipeline.stages.common import format_float

    for value in (0.1, 1 / 3, 1.005, 0.30000000000000004, 1.234567890123457e19):
        assert format_float(value) == repr(value)
    assert format_float(100000.0) == "100000"   # 整数型浮点写整数
    assert format_float(-0.0) == "0"


# ── 缺依赖：显式失败，不回落、不跳过 ──────────────────────────────────────

def test_missing_engine_fails_loudly(sample_csv, tmp_path, monkeypatch):
    """`plan/03` M1 测试点 + D1：monkeypatch 让 excel_com 不可用 -> exit 3 且 stages.json 有 failed 记录。"""
    from tripwire.pipeline import stages as stages_pkg

    def _boom(_text):
        raise StageUnavailable("excel_com_csv", "模拟：本机没有 Excel COM")

    monkeypatch.setitem(stages_pkg.RUNNERS, "excel_com_csv", _boom)

    decl = load_pipeline(PIPELINES / "excel_com.json")
    with pytest.raises(StageUnavailable) as caught:
        run_pipeline(decl, sample_csv, tmp_path / "runs")

    stages_path = caught.value.stages_path
    assert stages_path is not None and Path(stages_path).is_file()
    data = json.loads(Path(stages_path).read_text(encoding="utf-8"))
    failed = [s for s in data["stages"] if s["status"] == "failed"]
    assert len(failed) == 1
    assert failed[0]["stage_name"] == "excel_com_csv"
    assert "Excel COM" in failed[0]["reason"]
    # 失败阶段之后不许再有阶段（终止整条管线）
    assert data["stages"][-1]["status"] == "failed"


def test_unexpected_stage_exception_becomes_failed_record(sample_csv, tmp_path, monkeypatch):
    """阶段抛任意异常也必须留痕（否则产物里像"没跑过"，而不是"跑到这里被挡住"）。"""
    from tripwire.pipeline import stages as stages_pkg
    from tripwire.pipeline.errors import StageFailed

    def _boom(_text):
        raise ZeroDivisionError("引擎内部炸了")

    monkeypatch.setitem(stages_pkg.RUNNERS, "json_sqlite_csv", _boom)
    decl = load_pipeline(PIPELINES / "json_sqlite.json")
    with pytest.raises(StageFailed) as caught:
        run_pipeline(decl, sample_csv, tmp_path / "runs")

    assert caught.value.stages_path is not None
    data = json.loads(Path(caught.value.stages_path).read_text(encoding="utf-8"))
    assert data["stages"][-1]["status"] == "failed"
    assert "未预期异常" in data["stages"][-1]["reason"]


def test_excel_stage_does_not_fall_back_to_openpyxl(monkeypatch):
    """D1：COM 不可用时 `excel_com_csv.run` 必须抛 `StageUnavailable`，**不得**偷偷走 openpyxl。"""
    import tripwire.pipeline.stages.excel_com_csv as excel_stage

    monkeypatch.setattr(excel_stage.sys, "platform", "linux")
    with pytest.raises(StageUnavailable) as caught:
        excel_stage.run("a,b\n1,2\n")
    assert "Windows" in caught.value.reason
