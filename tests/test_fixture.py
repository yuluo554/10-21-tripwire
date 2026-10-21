"""M4 夹具生成器测试（出口门 E4 的一半：`pytest -q tests/test_fixture.py`）。

这组测试的靶子是 **K8（确定性）+ G5（同 seed 逐字节一致，两层）+ 真值纪律**：

- **两层守门**：① 冻结产物形态正确；② **重跑生成器到临时目录 → 与冻结产物逐字节 `cmp`**。
  只做第 ① 层是假门——被测对象是生成器，断言读的却是它上次的产出。
- `expected.json` 出现 `observed_*` / `actual_*` 字段即红（"冻结观测"会让基准引擎全坏也全绿）。
- 生成器**不可与引擎同源**：AST 扫描断言它不 import 任何阶段实现 / pandas。
- 部分运行（`--pool`）**不写清单**——这是"一次普通 pytest 静默改坏入仓文件"的检出面。
"""

from __future__ import annotations

import ast
import csv
import io
import json
from pathlib import Path

import pytest

from tripwire import serialization
from tripwire.cli import main
from tripwire.fixtures import (
    COLUMNS,
    DEFAULT_ROWS,
    DEFAULT_SEED,
    EXPECTED_NAME,
    FILLER,
    GENERATOR_VERSION,
    KEY_COLUMN,
    MANIFEST_NAME,
    NUMERIC_FORMS,
    ORIG_NAME,
    POOLS,
    POOL_CONTROL,
    POOL_NUMERIC,
    POOL_PREFIX,
    POOL_SEMANTIC,
    SEMANTIC_FORMS,
    SplitMix64,
    generate,
    pool_counts,
)
from tripwire.rules.predicates import rule_names

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN = REPO_ROOT / "fixtures" / "golden"
FIXTURES_PATH = REPO_ROOT / "src" / "tripwire" / "fixtures.py"


@pytest.fixture()
def golden_expected() -> dict:
    return json.loads((GOLDEN / EXPECTED_NAME).read_text(encoding="utf-8"))


# ── 冻结产物形态（第 ① 层）───────────────────────────────────────────────

def test_golden_files_exist():
    """金样本三件齐：`orig.csv` + `expected.json` + `manifest.json`（`plan/04` §一）。"""
    for name in (ORIG_NAME, EXPECTED_NAME, MANIFEST_NAME):
        assert (GOLDEN / name).is_file(), f"缺 {name}"


def test_golden_manifest_sha256_matches(golden_expected):
    """`manifest.json` 登记的 sha256 必须与两个文件**复算**一致（生成物的每一格都要能复算）。"""
    import hashlib

    manifest = json.loads((GOLDEN / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["seed"] == DEFAULT_SEED
    assert manifest["rows"] == DEFAULT_ROWS
    assert manifest["generator_version"] == GENERATOR_VERSION
    for name, digest in manifest["files"].items():
        actual = hashlib.sha256((GOLDEN / name).read_bytes()).hexdigest()
        assert actual == digest, f"{name} 的 sha256 与 manifest 不符（生成器改了没重生成？）"


def test_golden_orig_is_utf8_lf_no_bom():
    """`orig.csv`：UTF-8 **无 BOM**、**LF** 行尾、带表头（`plan/04` §二）。"""
    raw = (GOLDEN / ORIG_NAME).read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "orig.csv 带了 BOM"
    assert b"\r\n" not in raw, "orig.csv 有 CRLF（生成端必须归一为 LF）"
    text = raw.decode("utf-8")
    assert text.splitlines()[0] == ",".join(COLUMNS)
    assert text.endswith("\n")


def test_golden_expected_has_no_observed_fields():
    """**真值纪律**：`expected.json` 里不许出现 `observed_*` / `actual_*`（出现即红）。

    把"观测"冻结进真值，基准就退化成"比对两份预先算好的答案"——引擎全坏也全绿。
    """
    raw = (GOLDEN / EXPECTED_NAME).read_text(encoding="utf-8")
    for forbidden in ("observed_", "actual_"):
        assert forbidden not in raw, f"expected.json 出现 {forbidden}（冻结观测）"


def test_golden_expected_shape(golden_expected):
    """`expected.json` 的形状：`{cell, orig, rule, p_after}`，字段一个不多一个不少。"""
    assert golden_expected["seed"] == DEFAULT_SEED
    assert golden_expected["rows"] == DEFAULT_ROWS
    assert golden_expected["pools"] == {POOL_NUMERIC: 60, POOL_SEMANTIC: 80, POOL_CONTROL: 60}
    assert golden_expected["columns"] == list(COLUMNS)
    assert golden_expected["key"] == KEY_COLUMN
    assert isinstance(golden_expected["uncovered_rules"], list)
    for cell in golden_expected["cells"]:
        assert set(cell) == {"cell", "pool", "orig", "rule", "p_after"}
        assert len(cell["cell"]) == 2
        assert cell["rule"] in rule_names()
        assert isinstance(cell["p_after"], dict) and cell["p_after"]


def test_every_expected_rule_exists_in_rules_json(golden_expected):
    """每条 `rule` 必须存在于 `rules.json`（`plan/04` §二.4）。"""
    known = set(rule_names())
    for cell in golden_expected["cells"]:
        assert cell["rule"] in known, f"期望规则不在 rules.json: {cell['rule']}"


def test_control_pool_has_no_expected_cells(golden_expected):
    """控制组的行**不出现在 `cells` 里**——它没有期望差异（`plan/04` §二.3）。

    它的零差异靠 precision 判：控制行一旦上报差异就是 `unexpected`。
    """
    assert all(cell["pool"] != POOL_CONTROL for cell in golden_expected["cells"])
    assert all(cell["pool"] in POOLS for cell in golden_expected["cells"])


def test_expected_cells_are_sorted(golden_expected):
    """`cells` 按 `(row_key, col)` 排序（与 K5 同序，便于人工对读）。"""
    keys = [(cell["cell"][0], cell["cell"][1]) for cell in golden_expected["cells"]]
    assert keys == sorted(keys)


def test_golden_table_is_dense(golden_expected):
    """表是**稠密**的：每行每列都有值（见 `docs/fixture-pools.md` §二）。

    稀疏表会让 pandas 把整列推断成 `float64`，控制组的整数被写成 `94016.0` —— 一条假差异。
    """
    with open(GOLDEN / ORIG_NAME, "r", encoding="utf-8", newline="") as handle:
        records = list(csv.reader(handle))
    assert records[0] == list(COLUMNS)
    body = records[1:]
    assert len(body) == DEFAULT_ROWS
    for index, record in enumerate(body):
        assert len(record) == len(COLUMNS), f"第 {index} 行不是稠密的"
        assert all(cell != "" for cell in record), f"第 {index} 行有空单元格"


def test_golden_id_prefixes_and_counts(golden_expected):
    """三组混在一张表：`id` 前缀区分，且各池行数与 `pools` 声明一致。"""
    with open(GOLDEN / ORIG_NAME, "r", encoding="utf-8", newline="") as handle:
        records = list(csv.reader(handle))
    header = records[0]
    key_index = header.index(KEY_COLUMN)
    ids = [record[key_index] for record in records[1:]]
    assert len(ids) == len(set(ids)), "主键重复"
    for pool, prefix in POOL_PREFIX.items():
        matched = [value for value in ids if value.startswith(prefix)]
        assert len(matched) == golden_expected["pools"][pool], f"{pool} 行数不符"
    assert all(value for value in ids)
    assert all(not value.lstrip(prefix).startswith("0") for value in ids for prefix in POOL_PREFIX.values() if value.startswith(prefix))


# ── 生成器确定性（第 ② 层：真跑生成器）───────────────────────────────────

def test_same_seed_byte_identical(tmp_path):
    """同 seed 两次生成 → 逐字节一致（K8/G5 的第一层）。

    **这条真跑两遍生成器**，不是读盘上的冻结产物——后者在生成器被改坏时照常绿。
    """
    first = generate(DEFAULT_SEED, DEFAULT_ROWS, tmp_path / "a")
    second = generate(DEFAULT_SEED, DEFAULT_ROWS, tmp_path / "b")
    for name in (ORIG_NAME, EXPECTED_NAME, MANIFEST_NAME):
        assert (first.out_dir / name).read_bytes() == (second.out_dir / name).read_bytes(), name


def test_golden_matches_generator(tmp_path):
    """**G5 第二层**：重跑生成器（seed 42 / 200 行）→ 与入仓金样本逐字节一致。

    这条是"生成器确定性"的真正守门：变异项 = 改坏生成器（如把某个形态的期望算错）→ 本测试必红。
    """
    regenerated = generate(DEFAULT_SEED, DEFAULT_ROWS, tmp_path / "regen")
    for name in (ORIG_NAME, EXPECTED_NAME, MANIFEST_NAME):
        assert (regenerated.out_dir / name).read_bytes() == (GOLDEN / name).read_bytes(), (
            f"{name} 与入仓金样本不一致（改了生成器要整目录重生成）"
        )


def test_golden_has_zero_crlf(golden_expected):
    """`fixtures/golden/` 零 CRLF：生成端行尾由我们决定，不由平台默认决定。"""
    for name in (ORIG_NAME, EXPECTED_NAME, MANIFEST_NAME):
        assert b"\r\n" not in (GOLDEN / name).read_bytes(), f"{name} 有 CRLF"


def test_different_seed_changes_bytes(tmp_path):
    """不同 seed → 不同字节（否则"seed 参与选择"是假的）。"""
    a = generate(42, DEFAULT_ROWS, tmp_path / "a")
    b = generate(43, DEFAULT_ROWS, tmp_path / "b")
    assert (a.out_dir / ORIG_NAME).read_bytes() != (b.out_dir / ORIG_NAME).read_bytes()


def test_rows_scaling(tmp_path):
    """`--rows` 按比例缩放三池，和恰为 rows（最大余数法）。"""
    result = generate(7, 100, tmp_path / "small")
    assert sum(result.pools.values()) == 100
    with open(result.orig_path, "r", encoding="utf-8", newline="") as handle:
        records = list(csv.reader(handle))
    assert len(records) - 1 == 100


def test_pool_counts_sum_to_rows():
    for rows in (1, 7, 60, 200, 999):
        counts = pool_counts(rows)
        assert sum(counts.values()) == rows
        assert set(counts) == set(POOLS)


def test_pool_counts_rejects_non_positive():
    with pytest.raises(ValueError):
        pool_counts(0)


# ── 部分运行不写全集清单（`plan/04` §五.5）─────────────────────────────

def test_partial_run_writes_only_orig(tmp_path):
    """`--pool` 局部生成 **不写** `expected.json` / `manifest.json`。

    否则一次调试用的局部生成会把入仓清单静默改小，且当场全绿。
    """
    result = generate(42, 60, tmp_path / "partial", pools=[POOL_NUMERIC])
    assert (result.out_dir / ORIG_NAME).is_file()
    assert not (result.out_dir / EXPECTED_NAME).exists(), "部分运行不许写 expected.json"
    assert not (result.out_dir / MANIFEST_NAME).exists(), "部分运行不许写 manifest.json"
    assert result.wrote_manifest is False
    assert result.pools_included == (POOL_NUMERIC,)


def test_partial_run_does_not_touch_existing_manifest(tmp_path):
    """局部生成**不会改写**已存在的入仓清单（同一目录内）。"""
    generate(42, DEFAULT_ROWS, tmp_path)
    manifest_before = (tmp_path / MANIFEST_NAME).read_bytes()
    expected_before = (tmp_path / EXPECTED_NAME).read_bytes()
    generate(42, 60, tmp_path, pools=[POOL_CONTROL])
    assert (tmp_path / MANIFEST_NAME).read_bytes() == manifest_before
    assert (tmp_path / EXPECTED_NAME).read_bytes() == expected_before


def test_unknown_pool_rejected(tmp_path):
    with pytest.raises(ValueError):
        generate(42, 60, tmp_path, pools=["nope"])


# ── 真值不可与引擎同源（AST 守门）───────────────────────────────────────

def test_generator_does_not_import_stage_implementations():
    """生成器**不得** import 任何阶段实现 / pandas——否则期望值就与引擎同源。

    判别 = "把阶段实现全注释掉，真值还推得出来吗？"推不出来 = 同源 = 基准在引擎坏掉时也不变色。
    """
    tree = ast.parse(FIXTURES_PATH.read_text(encoding="utf-8"))
    forbidden = {"pandas", "tripwire.pipeline.stages"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] != "pandas", "生成器不得 import pandas"
                assert not alias.name.startswith("tripwire.pipeline.stages")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert not module.startswith("tripwire.pipeline.stages"), f"生成器不得 from {module} import"
            assert module.split(".")[0] != "pandas"
            for alias in node.names:
                assert alias.name not in forbidden


def test_generator_does_not_read_clock_or_random():
    """K8：生成器不读时钟、不用 stdlib `random`、不用 `uuid`（自研 splitmix64）。"""
    tree = ast.parse(FIXTURES_PATH.read_text(encoding="utf-8"))
    forbidden_modules = {"random", "time", "datetime", "secrets", "uuid"}
    forbidden_calls = {"now", "today", "utcnow", "time", "monotonic", "random"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden_modules, f"生成器不得 import {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            assert module not in forbidden_modules, f"生成器不得 from {node.module} import"
        elif isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            assert name not in forbidden_calls, f"生成器出现疑似读时钟/随机的调用: {name}"


# ── 自研 splitmix64 ───────────────────────────────────────────────────────

def test_splitmix64_is_deterministic():
    """同 seed 同序列；不同 seed 不同序列。"""
    assert [SplitMix64(42).next_u64() for _ in range(1)] == [SplitMix64(42).next_u64()]
    assert SplitMix64(1).next_u64() != SplitMix64(2).next_u64()


def test_splitmix64_known_sequence():
    """splitmix64 的标准首个输出（钉死算法，防"换成另一个 RNG 也绿"）。

    splitmix64 的参考实现对 seed=0 的第一个输出是 `0xE220A8397B1DCDAF`。
    """
    assert SplitMix64(0).next_u64() == 0xE220A8397B1DCDAF


def test_splitmix64_below_is_in_range():
    rng = SplitMix64(11)
    for bound in (1, 2, 7, 1000):
        for _ in range(50):
            assert 0 <= rng.below(bound) < bound


def test_splitmix64_below_rejects_non_positive():
    with pytest.raises(ValueError):
        SplitMix64(1).below(0)


def test_splitmix64_shuffle_is_deterministic():
    left = list(range(20))
    right = list(range(20))
    SplitMix64(5).shuffle(left)
    SplitMix64(5).shuffle(right)
    assert left == right
    assert sorted(left) == list(range(20))


# ── 形态表自洽 ────────────────────────────────────────────────────────────

def test_numeric_forms_are_pure_and_expected():
    """数值形态表：每条规则的形态都真的产出了期望（`_after` 不返回空）。"""
    from tripwire.fixtures import _after

    for form in NUMERIC_FORMS + SEMANTIC_FORMS:
        if not form.rule:
            continue
        for literal in form.variants:
            after = _after(form.rule, literal)
            assert after, f"{form.name}: {literal!r} 的期望为空"


def test_forms_columns_are_known():
    for form in NUMERIC_FORMS + SEMANTIC_FORMS:
        assert form.column in COLUMNS
    for column in FILLER:
        assert column in COLUMNS


def test_expected_stage_keys_are_real_stage_names(golden_expected):
    """`p_after` 的阶段键必须是四个真实 stage 名之一（不得混称 Excel）。"""
    known = {"pandas_csv", "json_sqlite_csv", "openpyxl_csv", "excel_com_csv"}
    for cell in golden_expected["cells"]:
        assert set(cell["p_after"]) <= known, f"{cell['cell']} 有未知阶段键"


# ── CLI 接线 ──────────────────────────────────────────────────────────────

def test_cli_gen_fixture_writes_golden_shape(tmp_path, capsys):
    code = main([
        "gen-fixture", "--seed", "42", "--rows", "200", "--out-dir", str(tmp_path / "out"),
    ])
    out = capsys.readouterr().out
    assert code == 0
    assert "PASS" in out and "canary-numeric=60" in out
    assert (tmp_path / "out" / ORIG_NAME).is_file()
    assert (tmp_path / "out" / MANIFEST_NAME).is_file()


def test_cli_gen_fixture_partial_is_explicit(tmp_path, capsys):
    """局部生成的输出里要**明说**不写清单（否则用户以为拿到了全集）。"""
    code = main([
        "gen-fixture", "--seed", "42", "--rows", "60", "--out-dir", str(tmp_path / "p"),
        "--pool", "numeric",
    ])
    out = capsys.readouterr().out
    assert code == 0
    assert "不写" in out and MANIFEST_NAME in out
    assert not (tmp_path / "p" / MANIFEST_NAME).exists()


def test_cli_gen_fixture_reports_uncovered(tmp_path, capsys):
    main(["gen-fixture", "--seed", "42", "--rows", "200", "--out-dir", str(tmp_path / "out")])
    out = capsys.readouterr().out
    assert "UNCOVERED" in out, "没正例的规则必须被点名（不假装覆盖）"


def test_cli_gen_fixture_default_seed_and_rows(tmp_path):
    """缺省就是金样本口径（seed 42 / 200 行），不需要用户记数字。"""
    from tripwire.fixtures import generate as gen

    result = gen(DEFAULT_SEED, DEFAULT_ROWS, tmp_path / "d")
    manifest = json.loads((result.out_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["seed"] == DEFAULT_SEED and manifest["rows"] == DEFAULT_ROWS