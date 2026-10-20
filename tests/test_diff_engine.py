"""M2 差异引擎测试（出口门 E2）：`python -m pytest -q tests/test_diff_engine.py`。

这组测试的靶子是 **K4 + K5 + G3 + G9 的 M2 部分**：
- 原型基线（14 单元格 / 9 条差异）必须复现——不是"跑通了"，是**数目对得上**；
- 四项结构差异**各自独立成记录**，不折算进单元格差异数；
- 无主键 / 主键重复 / 主键列不存在 → 拒绝运行（exit 3），**不产出 `diffs: []`**；
- 差异排序 `(row_key, col_index)` 稳定，两次运行序列化逐字节一致。

原型样本用**真 Excel COM** 现场产出（本机可用时）；不可用时用冻结的往返后文本，
并在测试名/断言里写清"用的是冻结产物，不是真机复现"——不把跳过写成通过。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from tripwire import exitcodes
from tripwire.cli import main
from tripwire.csvio import parse_csv_text, read_csv
from tripwire.diff import (
    DiffError,
    DuplicateKey,
    MissingKeyColumn,
    NoKeyForAlign,
    align,
    diff_tables,
)
from tripwire.pipeline import stages
from tripwire.pipeline.errors import StageUnavailable
from tripwire.pipeline.runner import run_pipeline
from tripwire.pipeline.schema import load_pipeline
from tripwire.serialization import write_json

REPO_ROOT = Path(__file__).resolve().parents[1]
PIPELINES = REPO_ROOT / "pipelines"

#: 原型样本：14 个数据单元格（2 行 × 7 列）。取值全部来自 `data/README` 的事实台账。
PROTO_HEADER = ["id", "bigint", "zip", "decimal", "exponent", "date", "note"]
PROTO_ROWS = [
    ["r1", "12345678901234567890", "02114", "19.90", "1e-7", "2024-01-02", "plain"],
    ["r2", "1234567890123456", "02114", "1.005", "1E5", "1900-02-29", "keep"],
]

#: Excel COM 实测往返后（Excel 16.0 Build 20326，2026-10-21 本机）。**冻结产物**：
#: 真机不可用时用它保证断言可跑，但它不是"真机复现"——测试会分别标注来源。
PROTO_AFTER_EXCEL = [
    ["r1", "1.23457E+19", "2114", "19.9", "1.00E-07", "2024/1/2", "plain"],
    ["r2", "1.23457E+15", "2114", "1.005", "1.00E+05", "1900/2/29", "keep"],
]


def _write_csv(path: Path, header, rows) -> Path:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerows([header, *rows])
    return path


@pytest.fixture()
def proto_csv(tmp_path: Path) -> Path:
    return _write_csv(tmp_path / "proto.csv", PROTO_HEADER, PROTO_ROWS)


@pytest.fixture()
def proto_tables(tmp_path: Path):
    orig = parse_csv_text(_write_csv(tmp_path / "orig.csv", PROTO_HEADER, PROTO_ROWS).read_text(encoding="utf-8"))
    got = parse_csv_text(
        _write_csv(tmp_path / "got.csv", PROTO_HEADER, PROTO_AFTER_EXCEL).read_text(encoding="utf-8")
    )
    return orig, got


# ── 原型基线：14 单元格 / 9 条差异 ────────────────────────────────────────

def test_prototype_nine_diffs(proto_tables):
    """`plan/03` M2：原型 14 单元格样本 → **9 条差异**（冻结的 Excel 往返产物）。"""
    orig, got = proto_tables
    result = diff_tables(orig, got, strategy="key", key="id")
    assert result.cells_compared == 14, "分母必须是 14 个数据单元格"
    assert len(result.diffs) == 9, [record.to_json() for record in result.diffs]
    assert result.structures == (), "原型样本结构未变，不该有结构记录"


def test_prototype_diffs_are_the_expected_cells(proto_tables):
    """不只数条数：逐条钉住 (row_key, col) 与原文/往返后文本。"""
    orig, got = proto_tables
    result = diff_tables(orig, got, strategy="key", key="id")
    actual = {(record.row_key, record.col): (record.orig_text, record.got_text) for record in result.diffs}
    assert actual == {
        ("r1", "bigint"): ("12345678901234567890", "1.23457E+19"),
        ("r1", "zip"): ("02114", "2114"),
        ("r1", "decimal"): ("19.90", "19.9"),
        ("r1", "exponent"): ("1e-7", "1.00E-07"),
        ("r1", "date"): ("2024-01-02", "2024/1/2"),
        ("r2", "bigint"): ("1234567890123456", "1.23457E+15"),
        ("r2", "zip"): ("02114", "2114"),
        ("r2", "exponent"): ("1E5", "1.00E+05"),
        ("r2", "date"): ("1900-02-29", "1900/2/29"),
    }


def test_prototype_nine_diffs_on_real_excel(proto_csv, tmp_path):
    """真机复现：同一份原型样本走 **`excel_com_csv`** 通道，再交给差异引擎。

    跳过纪律：Excel COM 不可用时 `pytest.skip` 并写明原因——不得改写成"通过"
    （`plan/05` §四 已把 Linux CI 上该阶段登记为未验证项）。
    """
    if not stages.probe("excel_com_csv")[0]:
        pytest.skip("Excel COM 不可用：本条真机复现跳过并标注（冻结产物那条仍会跑）")

    decl = load_pipeline(PIPELINES / "excel_com.json")
    try:
        run = run_pipeline(decl, proto_csv, tmp_path / "runs")
    except StageUnavailable as error:  # 探针绿但真跑失败：也算不可用，如实跳过
        pytest.skip(f"excel_com_csv 真跑失败: {error.reason}")

    orig, _ = read_csv(run.out_dir / "stage-0.csv")
    got, _ = read_csv(run.out_dir / "stage-1.csv")
    result = diff_tables(orig, got, strategy="key", key="id", stage_index=1)
    assert result.cells_compared == 14
    assert len(result.diffs) == 9, [record.to_json() for record in result.diffs]
    assert {record.stage_index for record in result.diffs} == {1}, "真机差异必须带上产出它的阶段序号"


# ── 四项结构差异：各自独立成记录 ──────────────────────────────────────────

def test_structure_changes_reported_separately(tmp_path):
    """行数 / 列数 / 列序 / 表头 各一条结构记录，且**不混进单元格差异率**。"""
    orig = parse_csv_text("id,a,b,c\n1,x,y,z\n2,p,q,r\n")
    got = parse_csv_text("id,b,a,d,e\n1,y,x,zz,9\n")  # 少一行、多一列、a/b 换序、c 换名成 d

    result = diff_tables(orig, got, strategy="key", key="id")
    kinds = [record.kind for record in result.structures]
    assert kinds == ["row_count", "col_count", "col_order", "header"], kinds

    by_kind = {record.kind: record.detail for record in result.structures}
    assert (by_kind["row_count"]["orig"], by_kind["row_count"]["got"]) == (2, 1)
    assert by_kind["row_count"]["missing_rows"] == ["2"], "消失的行要点名，不能只给个数"
    assert (by_kind["col_count"]["orig"], by_kind["col_count"]["got"]) == (4, 5)
    # 列序只比两侧都有的列（`c`→`d` 是 header 事实，不重复算进列序）
    assert (by_kind["col_order"]["orig"], by_kind["col_order"]["got"]) == (["id", "a", "b"], ["id", "b", "a"])
    assert by_kind["header"]["added"] == ["d", "e"]
    assert by_kind["header"]["removed"] == ["c"]


def test_structure_kinds_do_not_duplicate_into_cell_diffs(tmp_path):
    """整行消失不该膨胀成 N 条单元格差异（同一问题只计一次）。"""
    orig = parse_csv_text("id,a\n1,x\n2,y\n")
    got = parse_csv_text("id,a\n1,x\n")
    result = diff_tables(orig, got, strategy="key", key="id")
    assert result.diffs == ()
    assert [record.kind for record in result.structures] == ["row_count"]


def test_identical_tables_have_no_records():
    table = parse_csv_text("id,a\n1,x\n")
    result = diff_tables(table, table, strategy="key", key="id")
    assert result.diffs == () and result.structures == ()
    assert result.rows_compared == 1 and result.cells_compared == 2


# ── K4 / G3：拒绝运行的三种形态 ───────────────────────────────────────────

def test_no_key_refuses_to_run(proto_tables):
    """K4：`--align key` 无 `--key` → `NoKeyForAlign`，**不产出 `diffs: []`**。"""
    orig, got = proto_tables
    with pytest.raises(NoKeyForAlign):
        diff_tables(orig, got, strategy="key", key=None)


def test_duplicate_key_refuses_to_run(tmp_path):
    """主键重复 → `DuplicateKey`（不"取第一个"：那会把任意选择藏进结论）。"""
    orig = parse_csv_text("id,a\n1,x\n1,y\n")
    got = parse_csv_text("id,a\n1,x\n")
    with pytest.raises(DuplicateKey) as info:
        diff_tables(orig, got, strategy="key", key="id")
    assert info.value.value == "1" and info.value.count == 2


def test_duplicate_key_on_got_side_also_refuses(tmp_path):
    """往返后重复同样拒绝：一对一映射的两侧都得唯一。"""
    orig = parse_csv_text("id,a\n1,x\n")
    got = parse_csv_text("id,a\n1,x\n1,y\n")
    with pytest.raises(DuplicateKey) as info:
        diff_tables(orig, got, strategy="key", key="id")
    assert info.value.side == "往返后"


def test_missing_key_column_names_the_column(proto_tables):
    """`--key` 列不存在 → 报列名（不猜"最像的那一列"）。"""
    orig, got = proto_tables
    with pytest.raises(MissingKeyColumn) as info:
        diff_tables(orig, got, strategy="key", key="nope")
    assert info.value.column == "nope"
    assert "id" in str(info.value), "错误信息里要列出可用列名"


# ── 三策略 ────────────────────────────────────────────────────────────────

def test_position_strategy_keys_are_row_indices(proto_tables):
    """`position` 下 `row_key = #<row_index>`（`plan/03` M2 的语义表）。"""
    orig, got = proto_tables
    result = diff_tables(orig, got, strategy="position")
    assert {record.row_key for record in result.diffs} == {"#0", "#1"}


def test_lcs_strategy_keys_are_original_row_fingerprints(tmp_path):
    """`lcs` 下 `row_key` = 匹配到的**原行**指纹；只在往返后出现的行带 `~` 前缀。"""
    from tripwire.diff.align import row_fingerprint

    orig = parse_csv_text("id,a\n1,x\n2,y\n")
    got = parse_csv_text("id,a\n1,x\n2,z\n3,w\n")
    result = diff_tables(orig, got, strategy="lcs")
    keys = {record.row_key for record in result.diffs}
    assert row_fingerprint(("2", "y")) in keys, "改动行的 row_key 仍是它匹配到的原行指纹"
    assert all(not key.startswith("~") for key in keys), "改动行有原行，不该带 `~`"


def test_lcs_absorbs_insertion_without_cell_diffs(tmp_path):
    """精确 LCS 的价值：中间插一行不会让后面每行都变成差异（position 会）。

    插进来的行**不被当成任何原行**（不做相似度），它落进 `row_count` 结构记录。
    """
    orig = parse_csv_text("id,a\n1,x\n2,y\n3,z\n")
    got = parse_csv_text("id,a\n1,x\n9,new\n2,y\n3,z\n")
    result = diff_tables(orig, got, strategy="lcs")
    assert result.diffs == (), "锚点之间的插行不该污染后面每一行的单元格"
    assert [record.kind for record in result.structures] == ["row_count"]
    assert result.structures[0].detail["extra_rows"]


def test_lcs_reports_modified_row_as_cell_diff(tmp_path):
    """改动的行不被"相似"匹配，但在锚点空隙里按位置成对 → 单元格差异落在它该落的地方。"""
    orig = parse_csv_text("id,a\n1,x\n2,y\n")
    got = parse_csv_text("id,a\n1,x\n2,z\n")
    result = diff_tables(orig, got, strategy="lcs")
    assert [(record.col, record.orig_text, record.got_text) for record in result.diffs] == [("a", "y", "z")]
    assert result.structures == (), "行数没变，不该报结构差异"


def test_position_alignment_reports_insertion_avalanche(tmp_path):
    """D3 的反面证据：`position` 遇插行会雪崩式误报——这正是默认不用它的理由。

    这条测试**不是**在说 position 坏了，而是在钉住"它为什么会骗人"：
    插一行 → 后面每行都变成差异。报告里必须标注所用策略（M5）。
    """
    orig = parse_csv_text("id,a\n1,x\n2,y\n3,z\n")
    got = parse_csv_text("id,a\n1,x\n9,new\n2,y\n3,z\n")
    result = diff_tables(orig, got, strategy="position")
    # 插行后行号全错位：第 2 行起每格都对不上
    assert len(result.diffs) >= 4, "位置对齐的雪崩必须可见，而不是被抹平成 1 条"
    keyed = diff_tables(orig, got, strategy="key", key="id")
    # 同一输入换 key 对齐 → **零条**单元格差异，只有一条"多了一行"的结构记录
    assert keyed.diffs == (), "插进来的行不是任何原行的改动，不该产生单元格差异"
    assert [record.kind for record in keyed.structures] == ["row_count"]
    assert keyed.structures[0].detail["extra_rows"] == ["9"]


def test_align_returns_pairs_for_both_sides(tmp_path):
    """`align()` 是纯位置对：消失的行给 `(i, None)`，多出的行给 `(None, j)`。"""
    orig = parse_csv_text("id,a\n1,x\n2,y\n")
    got = parse_csv_text("id,a\n1,x\n3,z\n")
    pairs = align(orig, got, "key", "id")
    assert pairs == [(0, 0), (1, None), (None, 1)]


# ── 空值三态：缺格 vs 空串（M3 第 9 条规则的证据面）─────────────────────────

def test_missing_cell_differs_from_empty_cell(tmp_path):
    """`1,x`（缺格）vs `1,x,`（空串）必须报一条差异。

    两者文本都是 `""`：只比文本的话，M3 的 `empty_vs_null_vs_missing` 永远不命中。
    `orig_missing` / `got_missing` 就是为这件事带的标记。
    """
    orig = parse_csv_text("id,a,b\n1,x\n")
    got = parse_csv_text("id,a,b\n1,x,\n")
    result = diff_tables(orig, got, strategy="key", key="id")
    assert len(result.diffs) == 1
    record = result.diffs[0]
    assert (record.col, record.orig_text, record.got_text) == ("b", "", "")
    assert (record.orig_missing, record.got_missing) == (True, False)


def test_empty_and_null_token_differ_by_text(tmp_path):
    """`''` 与 `NULL` 的差别在文本里，差异层照实传（判定归 M3 谓词 9/10）。"""
    orig = parse_csv_text("id,a\n1,\n")
    got = parse_csv_text("id,a\n1,NULL\n")
    result = diff_tables(orig, got, strategy="key", key="id")
    assert [(record.orig_text, record.got_text) for record in result.diffs] == [("", "NULL")]
    assert not result.diffs[0].orig_missing and not result.diffs[0].got_missing


def test_missing_flags_survive_json_round_trip(proto_tables, tmp_path):
    """标记必须进 JSON（否则 M3 读 `--json` 产物时就丢了证据）。"""
    orig, got = proto_tables
    payload = diff_tables(orig, got, strategy="key", key="id").to_json()
    for record in payload["diffs"]:
        assert "orig_missing" in record and "got_missing" in record


# ── K5 / G9：排序稳定 + 双跑逐字节一致 ────────────────────────────────────

def test_diff_order_stable(proto_tables, tmp_path):
    """两次运行序列化**逐字节**一致（K5 + G9 的 M2 部分）。"""
    orig, got = proto_tables
    first = diff_tables(orig, got, strategy="key", key="id").to_json()
    second = diff_tables(orig, got, strategy="key", key="id").to_json()
    a = write_json(tmp_path / "a.json", first)
    b = write_json(tmp_path / "b.json", second)
    assert a.read_bytes() == b.read_bytes()


def test_diffs_sorted_by_row_key_then_col_index(tmp_path):
    """排序键 = `(row_key, col_index)`：先主键，再列序号（不是列名字典序）。"""
    orig = parse_csv_text("id,b,a\nz,1,2\na,3,4\n")
    got = parse_csv_text("id,b,a\nz,9,8\na,7,6\n")
    result = diff_tables(orig, got, strategy="key", key="id")
    assert [(record.row_key, record.col_index) for record in result.diffs] == [
        ("a", 1), ("a", 2), ("z", 1), ("z", 2)
    ]


def test_diff_does_not_depend_on_dict_order(tmp_path):
    """同内容、不同构造顺序的两张表 → 同结果（不依赖字典插入序）。"""
    left = parse_csv_text("id,a,b\n1,x,y\n2,p,q\n")
    right = parse_csv_text("id,a,b\n1,x,Y\n2,p,Q\n")
    again = parse_csv_text("id,a,b\n1,x,y\n2,p,q\n")
    assert diff_tables(left, right, strategy="key", key="id").to_json() == diff_tables(
        again, right, strategy="key", key="id"
    ).to_json()


# ── `--batch` dtype 漂移 ──────────────────────────────────────────────────

def test_batch_reports_dtype_drift(tmp_path):
    """`--batch N`：同列在不同 chunk 推断不一致 → 一条 `dtype_drift` 结构记录。"""
    table = parse_csv_text("id,v\n1,10\n2,20\n3,abc\n4,40\n")
    result = diff_tables(table, table, strategy="key", key="id", batch=2)
    kinds = [record.kind for record in result.structures]
    assert "dtype_drift" in kinds, kinds
    drift = next(record for record in result.structures if record.kind == "dtype_drift")
    assert drift.detail["col"] == "v"
    assert set(drift.detail["types"]) == {"int", "text"}


def test_batch_absent_means_no_dtype_drift(tmp_path):
    """不给 `--batch` 就不产 `dtype_drift`（默认路径不多嘴）。"""
    table = parse_csv_text("id,v\n1,10\n2,20\n3,abc\n")
    assert diff_tables(table, table, strategy="key", key="id").structures == ()


def test_batch_rejects_non_positive(tmp_path):
    table = parse_csv_text("id,v\n1,10\n")
    with pytest.raises(DiffError):
        diff_tables(table, table, strategy="key", key="id", batch=0)


# ── CLI 接线 ──────────────────────────────────────────────────────────────

def test_cli_diff_prints_nine_and_refuses_verdict(proto_csv, tmp_path, capsys):
    """`tripwire diff` 跑通：报 9 条差异，但**拒绝判定**（门禁在 M4）→ exit 3。"""
    orig = _write_csv(tmp_path / "orig.csv", PROTO_HEADER, PROTO_ROWS)
    got = _write_csv(tmp_path / "got.csv", PROTO_HEADER, PROTO_AFTER_EXCEL)
    code = main(["diff", "--orig", str(orig), "--got", str(got), "--key", "id"])
    out = capsys.readouterr().out
    assert code == exitcodes.USAGE
    assert code not in exitcodes.VERDICT_CODES
    assert "diffs 9" in out
    assert "不产出有损/无损判定" in out


def test_cli_diff_without_key_refuses_and_writes_nothing(proto_csv, tmp_path, capsys):
    """K4：CLI 层同样拒绝——exit 3，且**不落 --json 产物**。"""
    orig = _write_csv(tmp_path / "orig.csv", PROTO_HEADER, PROTO_ROWS)
    got = _write_csv(tmp_path / "got.csv", PROTO_HEADER, PROTO_AFTER_EXCEL)
    target = tmp_path / "out.json"
    code = main(["diff", "--orig", str(orig), "--got", str(got), "--json", str(target)])
    err = capsys.readouterr().err
    assert code == exitcodes.USAGE
    assert "未声明主键" in err or "需要 --key" in err
    assert not target.exists(), "拒绝运行时不该落下任何产物"


def test_cli_diff_writes_json_via_serialization(proto_csv, tmp_path):
    """`--json` 产物走 `serialization.write_json`：LF、排序键、结尾换行（K11）。"""
    orig = _write_csv(tmp_path / "orig.csv", PROTO_HEADER, PROTO_ROWS)
    got = _write_csv(tmp_path / "got.csv", PROTO_HEADER, PROTO_AFTER_EXCEL)
    target = tmp_path / "out.json"
    assert main(["diff", "--orig", str(orig), "--got", str(got), "--key", "id", "--json", str(target)]) == exitcodes.USAGE
    raw = target.read_bytes()
    assert b"\r\n" not in raw
    assert raw.endswith(b"\n")
    payload = json.loads(raw.decode("utf-8"))
    assert payload["strategy"] == "key"
    assert len(payload["diffs"]) == 9
    assert payload["cells_compared"] == 14


def test_cli_diff_missing_file_is_usage_error(tmp_path):
    code = main(["diff", "--orig", str(tmp_path / "nope.csv"), "--got", str(tmp_path / "nope2.csv"), "--key", "id"])
    assert code == exitcodes.USAGE


def test_cli_diff_rejects_unknown_strategy(tmp_path):
    """策略是枚举：argparse 层就挡掉（未知值 → exit 3，不是 2）。"""
    orig = _write_csv(tmp_path / "orig.csv", PROTO_HEADER, PROTO_ROWS)
    assert main(["diff", "--orig", str(orig), "--got", str(orig), "--align", "fuzzy"]) == exitcodes.USAGE
