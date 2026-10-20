"""M3 归因引擎测试（出口门 E3）：`python -m pytest -q tests/test_rules.py`。

这组测试的靶子是 **G4 + K6 + K7 + D1 + K10**：
- 原型 9 条差异 **9/9 命中命名规则、`unclassified == 0`**（跑真机 `excel_com_csv` 管线，
  不是拿冻结字符串硬编码）；
- 每条归因都**有证据**（`orig_text` / `got_text` / `stage_meta` 都在）；
- "同规则不同环节"两例 `resolved_stage` **不同**（证明环节是筛出来的，不是规则写死的）；
- `openpyxl_csv` 跑出的 15 位截断**不得**归因到 `excel_15_digit_truncation`（D1）；
- 一条差异命中多条规则时其余命中**不丢**（K6）；
- `fingerprint` 是 `(row_key, col, rule)` 的纯函数，跨 run 稳定（K10）。
"""

from __future__ import annotations

import ast
import csv
import json
from pathlib import Path

import pytest

from tripwire import exitcodes
from tripwire.cli import main
from tripwire.csvio import parse_csv_text, read_csv
from tripwire.diff import diff_tables
from tripwire.pipeline import stages
from tripwire.pipeline.errors import RunNotFound, StageUnavailable
from tripwire.pipeline.runner import load_run, run_pipeline
from tripwire.pipeline.schema import load_pipeline
from tripwire.rules.engine import UNCLASSIFIED, Attribution, attribute, explain, make_fingerprint
from tripwire.rules.predicates import (
    PREDICATES,
    predicate_for,
    rule_count,
    rules_by_id,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PIPELINES = REPO_ROOT / "pipelines"
PREDICATES_PATH = REPO_ROOT / "src" / "tripwire" / "rules" / "predicates.py"

#: 原型样本（与 M2 同源）：14 个数据单元格，真 Excel 往返后 9 个被改
PROTO_HEADER = ["id", "bigint", "zip", "decimal", "exponent", "date", "note"]
PROTO_ROWS = [
    ["r1", "12345678901234567890", "02114", "19.90", "1e-7", "2024-01-02", "plain"],
    ["r2", "1234567890123456", "02114", "1.005", "1E5", "1900-02-29", "keep"],
]


@pytest.fixture()
def proto_csv(tmp_path: Path) -> Path:
    path = tmp_path / "proto.csv"
    with open(path, "w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerows([PROTO_HEADER, *PROTO_ROWS])
    return path


def _excel_run(csv_path: Path, out_dir: Path):
    if not stages.probe("excel_com_csv")[0]:
        pytest.skip("Excel COM 不可用：真机原型复现跳过并标注（本机可用时这条必须真跑）")
    try:
        return run_pipeline(load_pipeline(PIPELINES / "excel_com.json"), csv_path, out_dir)
    except StageUnavailable as error:
        pytest.skip(f"excel_com_csv 真跑失败: {error.reason}")


def _attributions_for(run, *, key="id", strategy="key", stage_index=1):
    orig, _ = read_csv(run.out_dir / "stage-0.csv")
    got, _ = read_csv(run.out_dir / f"stage-{stage_index}.csv")
    result = diff_tables(orig, got, strategy=strategy, key=key, stage_index=stage_index)
    return result, attribute(result.diffs, run, key=key, strategy=strategy)


# ── 规则表自洽（G11 的 M3 部分）──────────────────────────────────────────

def test_rules_table_has_18():
    """`rules.json` 恰好 18 条、四族 8/2/4/4。"""
    assert rule_count() == 18
    families = {}
    for rule in rules_by_id():
        families[rule["family"]] = families.get(rule["family"], 0) + 1
    assert families == {"numeric": 8, "null": 2, "text": 4, "time": 4}


def test_every_rule_has_a_real_predicate():
    """`rules.json` 里点名的每个谓词都必须在 `predicates.py` 里存在且**不再是占位**。"""
    assert set(PREDICATES) == {rule["predicate"] for rule in rules_by_id()}
    assert len(PREDICATES) == 18
    for rule in rules_by_id():
        function = predicate_for(rule["predicate"])
        assert callable(function)
        # 占位实现会 raise NotImplementedError；这里用一组必不命中的输入探一次
        assert function("__x__", "__x__", None, {}) is False


def test_every_predicate_is_pure_function():
    """K6：谓词不得读网络 / 时钟 / 随机 / 文件系统（AST 扫描，不看 import 顶层而是全树）。

    `datetime` 只允许出现在 `parse_date` 里（把文本解析成日期对象，不读当前时间）。
    所以这里禁的是 `datetime.datetime.now/today/utcnow`、`time.` 调用与 `random.`。
    """
    tree = ast.parse(PREDICATES_PATH.read_text(encoding="utf-8"))
    forbidden_calls = {"now", "today", "utcnow", "time", "monotonic", "random", "uuid1", "uuid4"}
    forbidden_modules = {"socket", "urllib", "http", "requests", "random", "time", "secrets"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root not in forbidden_modules, f"谓词模块不得 import {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            assert root not in forbidden_modules, f"谓词模块不得 from {node.module} import"
        elif isinstance(node, ast.Call):
            target = node.func
            name = getattr(target, "attr", None) or getattr(target, "id", None)
            assert name not in forbidden_calls, f"谓词里出现疑似读时钟/随机的调用: {name}"


def test_predicate_signature_is_the_documented_one():
    """签名统一为 `(orig, got, declared_type, stage_meta)`（K6）。"""
    import inspect

    for name, function in PREDICATES.items():
        parameters = list(inspect.signature(function).parameters)
        assert parameters == ["orig", "got", "declared_type", "stage_meta"], f"{name}: {parameters}"


def test_every_rule_counterexample_holds():
    """`rules.json` 的 `counterexample` 不是摆设：能机读的那几条必须真的不命中。

    只覆盖"原文 -> 往返后"写得出来的条目（散文型反例——例如"openpyxl 的同类截断"——
    由专门的测试覆盖，不在这里假装解析）。
    """
    cases = {
        "leading_zero_lost": ("0", "0"),
        "scientific_notation_coercion": ("ABC123", "1E5"),
        "float_precision_truncated": ("19.90", "19.9"),
        "negative_zero_sign_lost": ("-0.5", "-0.5"),
        "decimal_trailing_zero_dropped": ("19.9", "19.9"),
        "exponent_form_normalized": ("1e-7", "2e-7"),
        "empty_vs_null_vs_missing": ("0", ""),
        "null_token_collision": ("NULLY", ""),
        "unicode_normalization_changed": ("cafe", "cafe"),
        "whitespace_collapsed": (" a b ", " a b "),
        "bom_prepended": ("\ufeffx", "x"),
        "encoding_mojibake": ("é", "é"),
        "date_retyped_to_text": ("2024-01-02", "2024-01-02"),
    }
    by_name = {rule["name"]: rule for rule in rules_by_id()}
    for name, (orig, got) in cases.items():
        assert by_name[name]["counterexample"], f"{name} 缺反例"
        assert predicate_for(name)(orig, got, None, {}) is False, f"{name} 反例误命中: {orig!r}->{got!r}"


def test_int53_boundary_counterexample():
    """#4 的边界反例：2^53−1 同值 → 不命中；2^53 超界 → 命中（若变了）。"""
    assert predicate_for("int53_overflow")("9007199254740991", "9007199254740991", None, {}) is False
    assert predicate_for("int53_overflow")("9007199254740992", "9007199254740990", None, {}) is True


def test_serial_59_counterexample():
    """#17 反例：serial 59 → `1900-02-28` 不命中。"""
    assert predicate_for("serial_60_phantom_date")("59", "1900-02-28", None, {}) is False
    assert predicate_for("serial_60_phantom_date")("60", "1900-02-29", None, {}) is True


def test_1904_shift_needs_exactly_1462_days():
    """#16：只有恰好相差 1462 天才命中（`data/README` F3）。"""
    rule = predicate_for("date_system_shift_1904")
    assert rule("2024-01-02", "2028-01-03", None, {}) is True
    assert rule("2024-01-02", "2024-01-03", None, {}) is False


def test_number_format_rule_needs_stage_meta():
    """#18：拿不到 `number_format` 就**不归因**（D1：没有证据不判）。"""
    rule = predicate_for("number_format_dropped")
    assert rule("0.15", "0.15", None, {}) is False
    assert rule("0.15", "0.15", None, None) is False
    # 有证据时才命中（二期 xlsx 通道接入后走这条分支）
    assert rule("0.15", "0.15", None, {"orig_number_format": "0%", "got_number_format": "General"}) is True


# ── 原型基线：9/9 命中、unclassified == 0（G4）────────────────────────────

def test_nine_of_nine_classified(proto_csv, tmp_path):
    """真机 Excel 管线 → 9 条差异 → **9 条全部命中命名规则，`unclassified == 0`**。"""
    run = _excel_run(proto_csv, tmp_path / "runs")
    result, attributions = _attributions_for(run)

    assert len(result.diffs) == 9, "原型基线是 9 条差异"
    assert len(attributions) == 9
    unclassified = [item for item in attributions if item.unclassified]
    assert unclassified == [], [item.diff.to_json() for item in unclassified]
    assert {item.rule for item in attributions} >= {
        "int53_overflow",
        "leading_zero_lost",
        "decimal_trailing_zero_dropped",
        "exponent_form_normalized",
        "date_retyped_to_text",
        "excel_15_digit_truncation",
        "serial_60_phantom_date",
    }


def test_every_attribution_has_evidence(proto_csv, tmp_path):
    """每条归因都有 `orig_text` / `got_text` / `stage_meta`，且 `resolved_stage` 指到真跑过的阶段名。"""
    run = _excel_run(proto_csv, tmp_path / "runs")
    _, attributions = _attributions_for(run)
    stage_names = {snapshot.stage_name for snapshot in run.stages}
    for item in attributions:
        payload = item.to_json()
        evidence = payload["evidence"]
        assert evidence["orig_text"] != "" or item.diff.orig_missing, "原文证据为空"
        assert evidence["got_text"] != "" or item.diff.got_missing, "往返后证据为空"
        assert isinstance(evidence["stage_meta"], dict)
        assert payload["resolved_stage"] in stage_names, "环节必须是本次 run 真跑过的阶段名"
        assert payload["resolved_stage"] == "excel_com_csv"


def test_first_seen_at_is_one_based_output_index(proto_csv, tmp_path):
    """`first_seen_at` 用 1-based 输出序号（`stage-1` = 第一份输出），与 `stages.json` 同一套编号。"""
    run = _excel_run(proto_csv, tmp_path / "runs")
    _, attributions = _attributions_for(run)
    for item in attributions:
        assert item.first_seen_at == 1
        assert item.first_seen_stage == "excel_com_csv"


def test_explain_log_format_is_frozen(proto_csv, tmp_path):
    """`--explain` 的日志格式写死（`plan/03` M3）。"""
    run = _excel_run(proto_csv, tmp_path / "runs")
    _, attributions = _attributions_for(run)
    line = explain(attributions[0])
    assert line.startswith("rule=")
    assert ", first_seen_at=stage 1 (excel_com_csv), candidates=[" in line
    assert "-> resolved to excel_com_csv" in line


# ── D1：候选与本次 run 无交集 → 降级 unclassified ────────────────────────

def test_candidate_stage_not_in_run_degrades_to_unclassified(proto_csv, tmp_path):
    """`openpyxl_csv` 跑出的 16 位科学计数法**不得**归因到 `excel_15_digit_truncation`。

    这条是 D1 的正面守卫：原型样本里的 20 位整数在 openpyxl 通道产出
    `1.234567890123457e+19`（有效位 16），形态上像"截断"但不是 Excel 的 15 位行为。
    结论落 `unclassified` 才是诚实的。
    """
    if not stages.probe("openpyxl_csv")[0]:
        pytest.skip("openpyxl 不可用")
    run = run_pipeline(load_pipeline(PIPELINES / "openpyxl.json"), proto_csv, tmp_path / "runs")
    _, attributions = _attributions_for(run)

    bigint = [item for item in attributions if item.diff.col == "bigint"]
    assert bigint, "openpyxl 通道必须改掉那个 20 位整数"
    for item in bigint:
        assert item.rule != "excel_15_digit_truncation", "openpyxl 的产出被伪造成了 Excel 行为"
        assert item.resolved_stage != "excel_com_csv"
    assert any(item.unclassified for item in attributions), "候选无交集的形态必须落 unclassified"


def test_no_stage_sequence_does_not_invent_stage(tmp_path):
    """没有快照序列（只比两份孤立文件）→ `resolved_stage` 为 `None`，不编造环节。"""
    orig = parse_csv_text("id,a\n1,02114\n")
    got = parse_csv_text("id,a\n1,2114\n")
    result = diff_tables(orig, got, strategy="key", key="id")
    attributions = attribute(result.diffs)
    assert attributions[0].rule == "leading_zero_lost"
    assert attributions[0].resolved_stage is None
    assert attributions[0].first_seen_at is None
    assert attributions[0].candidates  # 候选照常给出（不依赖本次 run）


# ── K6：一差多命中按 id 升序取首条，其余进 also_matched ──────────────────

def test_also_matched_recorded():
    """一条差异命中多条规则时，其余命中**不丢**，且首条是 **id 最小**的那条。"""
    orig = parse_csv_text("id,a\n1,12345678901234567890\n")
    got = parse_csv_text("id,a\n1,1.23457E+19\n")
    result = diff_tables(orig, got, strategy="key", key="id")
    attributions = attribute(result.diffs)
    item = attributions[0]
    # id 4 = int53_overflow 先于 id 5 = excel_15_digit_truncation
    assert item.rule == "int53_overflow"
    assert "excel_15_digit_truncation" in item.also_matched
    payload = item.to_json()
    assert payload["evidence"]["also_matched"] == ["excel_15_digit_truncation"]


def test_first_hit_is_lowest_id_not_alphabetical():
    """首条按 `id` 升序，不是按规则名字典序（`int53_overflow` < `excel_...` 字典序会反过来）。"""
    catalogue = rules_by_id()
    assert [rule["id"] for rule in catalogue] == sorted(rule["id"] for rule in catalogue)
    first = catalogue[0]
    assert first["id"] == 1 and first["name"] == "leading_zero_lost"


def test_unclassified_is_counted_not_silently_dropped():
    """无规则命中 → `rule == "unclassified"`、`resolved_stage is None`，但仍是一条归因记录。"""
    orig = parse_csv_text("id,a\n1,hello\n")
    got = parse_csv_text("id,a\n1,goodbye\n")
    result = diff_tables(orig, got, strategy="key", key="id")
    attributions = attribute(result.diffs)
    assert len(attributions) == 1
    assert attributions[0].rule == UNCLASSIFIED
    assert attributions[0].unclassified is True
    assert attributions[0].resolved_stage is None
    assert attributions[0].to_json()["evidence"]["orig_text"] == "hello"


# ── 同规则不同环节（归因由快照序列筛，不硬编码顺序）────────────────────────

def test_first_seen_stage_from_snapshot_sequence():
    """`same` 形态在**不同环节**出现 → `resolved_stage` 必须不同。

    两条链路都用 `leading_zero_lost`：一条在 `pandas_csv` 丢零，一条在 `json_sqlite_csv` 丢零。
    规则名相同、`possible_stages` 相同，唯一的区分依据是**快照序列**。
    """
    zero_kept = parse_csv_text("id,a\n1,02114\n")
    zero_lost = parse_csv_text("id,a\n1,2114\n")
    original = parse_csv_text("id,a\n1,02114\n")

    via_pandas = [
        (0, "input", original),
        (1, "pandas_csv", zero_lost),
    ]
    via_sqlite = [
        (0, "input", original),
        (1, "pandas_csv", zero_kept),  # 第一步没动
        (2, "json_sqlite_csv", zero_lost),  # 第二步才丢
    ]

    first = attribute(diff_tables(original, zero_lost, strategy="key", key="id").diffs,
                      stages=via_pandas, key="id")[0]
    second = attribute(diff_tables(original, zero_lost, strategy="key", key="id").diffs,
                       stages=via_sqlite, key="id")[0]

    assert first.rule == second.rule == "leading_zero_lost"
    assert first.resolved_stage == "pandas_csv"
    assert second.resolved_stage == "json_sqlite_csv"
    assert first.first_seen_at == 1 and second.first_seen_at == 2


def test_candidate_not_first_observed_falls_back_in_run_order():
    """观察到变化的阶段不在候选里 → 按实际运行顺序取候选最早者（不报 `None` 了事）。"""
    original = parse_csv_text("id,a\n1,02114\n")
    changed = parse_csv_text("id,a\n1,2114\n")
    # `leading_zero_lost` 的候选含 pandas_csv；这里第一步是某个候选外的阶段
    sequence = [
        (0, "input", original),
        (1, "some_other_csv", changed),
        (2, "pandas_csv", changed),
    ]
    item = attribute(diff_tables(original, changed, strategy="key", key="id").diffs,
                     stages=sequence, key="id")[0]
    assert item.first_seen_at == 1 and item.first_seen_stage == "some_other_csv"
    assert item.resolved_stage == "pandas_csv", "候选里本次 run 真跑过的那个"


# ── K10：fingerprint 是 (row_key, col, rule) 的纯函数 ────────────────────

def test_fingerprint_matches_documented_formula():
    """K10：`sha256(row_key \\x1f col \\x1f rule)[:16]`，唯一实现在 `make_fingerprint`。"""
    import hashlib

    # 逐字对齐 data/README §6.4 的公式：三段用 \x1f 连接（不是 "_"、不是 ""）
    expected = hashlib.sha256(b"r1\x1fzip\x1fleading_zero_lost").hexdigest()[:16]
    assert make_fingerprint("r1", "zip", "leading_zero_lost") == expected
    assert len(make_fingerprint("r1", "zip", "leading_zero_lost")) == 16


def test_fingerprint_is_stable_across_runs(proto_csv, tmp_path):
    """同输入两跑 → fingerprint 集合相等（跨 run diff 的前提）。"""
    first = _excel_run(proto_csv, tmp_path / "a")
    second = _excel_run(proto_csv, tmp_path / "b")
    _, left = _attributions_for(first)
    _, right = _attributions_for(second)
    assert {item.fingerprint for item in left} == {item.fingerprint for item in right}


def test_fingerprint_changes_when_rule_changes(proto_csv, tmp_path):
    """规则名变了 fingerprint 就变——这是**期望行为**（规则改名应当被看见）。"""
    a = make_fingerprint("r1", "zip", "leading_zero_lost")
    b = make_fingerprint("r1", "zip", "decimal_trailing_zero_dropped")
    c = make_fingerprint("r1", "bigint", "leading_zero_lost")
    assert len({a, b, c}) == 3


def test_fingerprint_has_no_time_or_path_inputs():
    """K10：fingerprint 只吃三个参数——多一个就会把时间/路径带进跨 run 对账。"""
    import inspect

    parameters = list(inspect.signature(make_fingerprint).parameters)
    assert parameters == ["row_key", "col", "rule"]


# ── CLI 接线 ──────────────────────────────────────────────────────────────

def test_cli_attribute_reports_and_refuses_verdict(proto_csv, tmp_path, capsys):
    """`tripwire attribute --run-id` 跑通：报归因，但**拒绝判定**（门禁在 M4）→ exit 3。"""
    run = _excel_run(proto_csv, tmp_path / "runs")
    code = main([
        "attribute", "--run-id", run.run_id, "--out-dir", str(tmp_path / "runs"), "--key", "id", "--explain",
    ])
    out = capsys.readouterr().out
    assert code == exitcodes.USAGE
    assert "ATTRIBUTE" in out
    assert "unclassified 0" in out
    assert "rule=leading_zero_lost" in out


def test_cli_attribute_fail_on_unclassified_exits_2(proto_csv, tmp_path):
    """`--fail-on unclassified` 且有 unclassified → **exit 2**（门禁失败通道）。

    用 openpyxl 通道构造真实场景：它会把 20 位整数写成 16 位科学计数法，
    而 `excel_15_digit_truncation` 的候选不含它 → 落 unclassified。
    """
    if not stages.probe("openpyxl_csv")[0]:
        pytest.skip("openpyxl 不可用")
    run = run_pipeline(load_pipeline(PIPELINES / "openpyxl.json"), proto_csv, tmp_path / "runs")
    code = main([
        "attribute", "--run-id", run.run_id, "--out-dir", str(tmp_path / "runs"), "--key", "id",
        "--fail-on", "unclassified",
    ])
    assert code == exitcodes.GATE_FAILED


def test_cli_attribute_fail_on_is_silent_when_all_classified(proto_csv, tmp_path):
    """全部命中规则时 `--fail-on unclassified` **不**触发：仍是拒绝判定 3，不是 2。

    这条与上一条成对：只测"有 unclassified → 2"的话，把 `--fail-on` 写成无条件下 2 也绿。
    """
    run = _excel_run(proto_csv, tmp_path / "runs")
    code = main([
        "attribute", "--run-id", run.run_id, "--out-dir", str(tmp_path / "runs"), "--key", "id",
        "--fail-on", "unclassified",
    ])
    assert code == exitcodes.USAGE
    assert code != exitcodes.GATE_FAILED


def test_cli_attribute_missing_run_is_usage_error(tmp_path):
    assert main(["attribute", "--run-id", "does-not-exist", "--out-dir", str(tmp_path)]) == exitcodes.USAGE


def test_cli_attribute_writes_json_via_serialization(proto_csv, tmp_path):
    """`--json` 产物走 `serialization.write_json`：LF、结尾换行（K11），且带 fingerprint。"""
    run = _excel_run(proto_csv, tmp_path / "runs")
    target = tmp_path / "attr.json"
    assert main([
        "attribute", "--run-id", run.run_id, "--out-dir", str(tmp_path / "runs"),
        "--key", "id", "--json", str(target),
    ]) == exitcodes.USAGE
    raw = target.read_bytes()
    assert b"\r\n" not in raw and raw.endswith(b"\n")
    payload = json.loads(raw.decode("utf-8"))
    assert payload["unclassified"] == 0
    assert len(payload["attributions"]) == 9
    for item in payload["attributions"]:
        assert len(item["fingerprint"]) == 16
        assert item["evidence"]["orig_text"] is not None


def test_cli_attribute_requires_key_for_key_alignment(proto_csv, tmp_path, capsys):
    """无 `--key` 且策略是 key → exit 3（K4 在归因入口同样成立）。"""
    run = _excel_run(proto_csv, tmp_path / "runs")
    code = main(["attribute", "--run-id", run.run_id, "--out-dir", str(tmp_path / "runs")])
    err = capsys.readouterr().err
    assert code == exitcodes.USAGE
    assert "未声明主键" in err or "需要 --key" in err


# ── run 状态重建 ──────────────────────────────────────────────────────────

def test_load_run_rebuilds_without_rerunning(proto_csv, tmp_path):
    """`load_run` 只读产物重建，不重跑管线：`stages.json` 与快照都不被改写。"""
    run = _excel_run(proto_csv, tmp_path / "runs")
    before = {path.name: path.read_bytes() for path in run.out_dir.iterdir() if path.is_file()}
    rebuilt = load_run(run.out_dir)
    after = {path.name: path.read_bytes() for path in run.out_dir.iterdir() if path.is_file()}
    assert before == after
    assert rebuilt.run_id == run.run_id
    assert [snapshot.stage_index for snapshot in rebuilt.stages] == [0, 1]


def test_load_run_rejects_missing_snapshot(proto_csv, tmp_path):
    """`stages.json` 说有 stage-1 但快照不在 → 显式 `RunNotFound`（不静默返回半份状态）。"""
    run = _excel_run(proto_csv, tmp_path / "runs")
    (run.out_dir / "stage-1.csv").unlink()
    with pytest.raises(RunNotFound):
        load_run(run.out_dir)


def test_load_run_rejects_missing_stages_json(tmp_path):
    with pytest.raises(RunNotFound):
        load_run(tmp_path / "nope")


def test_load_run_rejects_malformed_stages_json(tmp_path):
    """`stages.json` 是合法 JSON 但形状不对（缺 stages）→ `RunNotFound`，不抛 `KeyError`。"""
    run_dir = tmp_path / "runs" / "abc"
    run_dir.mkdir(parents=True)
    (run_dir / "stages.json").write_text('{"run_id": "abc"}', encoding="utf-8")
    with pytest.raises(RunNotFound):
        load_run(run_dir)
