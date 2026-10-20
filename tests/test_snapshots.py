"""M1 快照测试（出口门 E1）：`stage-<k>.csv` 是原始文本、哈希可独立复算、`stages.json` 字段齐全。

这组测试的靶子是 **K1 + K2 + G2 + G9**：
- K1 快照存原始文本（不是 DataFrame 的再序列化）：用"CRLF 必须被保留"来验证——
  任何一次"顺手归一"都会让它变绿为红；
- K2 `run_id` 内容派生：同输入两次 → 同 id；**跨进程**也同 id（这里用子进程验）；
- G2 sha256 可复算：不复用 `stages.json` 里的值，直接从字节重算；
- G9 双跑逐字节一致：两次全产物 `cmp`。
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tripwire.csvio import read_text
from tripwire.pipeline import stages
from tripwire.pipeline.errors import StageUnavailable
from tripwire.pipeline.model import RUNTIME_KEYS
from tripwire.pipeline.runner import compute_run_id, run_pipeline
from tripwire.pipeline.schema import load_pipeline

REPO_ROOT = Path(__file__).resolve().parents[1]
PIPELINES = REPO_ROOT / "pipelines"

SAMPLE_ROWS = [
    ["id", "num_big", "zip", "decimal", "exponent", "date", "text_unicode", "nullable"],
    ["num-0001", "12345678901234567890", "02114", "19.90", "1e-7", "2024-01-02", "caf\u00e9", ""],
    ["num-0002", "1125899906842624", "00123-4567", "1.005", "1E5", "1900-02-29", "e\u0301", "NULL"],
    ["ctl-0001", "42", "90210", "10.5", "100000", "hello", "ascii", "x"],
]

#: 纯 stdlib 通道：在任何平台都必须真跑（不做跳过）
ALWAYS = ["pandas", "json_sqlite"]


@pytest.fixture()
def sample_csv(tmp_path: Path) -> Path:
    path = tmp_path / "sample.csv"
    with open(path, "w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerows(SAMPLE_ROWS)
    return path


def _run(name: str, csv_path: Path, out_dir: Path):
    decl = load_pipeline(PIPELINES / f"{name}.json")
    try:
        return run_pipeline(decl, csv_path, out_dir)
    except StageUnavailable as error:
        pytest.skip(f"{name} 不可用: {error.reason}（跳过并标注，不算已验证）")


def _all_runs(csv_path: Path, out_dir: Path):
    """跑所有本机可用的通道；返回 [(名字, RunStages)]。"""
    produced = []
    for name in ("pandas", "json_sqlite", "openpyxl", "excel_com"):
        decl = load_pipeline(PIPELINES / f"{name}.json")
        try:
            produced.append((name, run_pipeline(decl, csv_path, out_dir)))
        except StageUnavailable:
            continue
    assert produced, "本机一条通道都跑不了，这组测试没有意义"
    return produced


# ── G2：快照 sha256 可独立复算 ─────────────────────────────────────────────

def test_stage_text_sha256_matches(sample_csv, tmp_path):
    for name, run in _all_runs(sample_csv, tmp_path / "runs"):
        for snapshot in run.stages:
            path = run.out_dir / f"stage-{snapshot.stage_index}.csv"
            assert path.is_file(), f"{name}: 缺快照 {path.name}"
            raw = path.read_bytes()
            recomputed = hashlib.sha256(raw.decode("utf-8").encode("utf-8")).hexdigest()
            assert recomputed == snapshot.sha256, f"{name}: {path.name} 的 sha256 与 stages.json 不符"


def test_snapshot_is_raw_text_not_reserialized(sample_csv, tmp_path):
    """K1：CRLF / 无结尾换行 / 尾随空格都是**被测形态**，不许在落盘时被归一。

    证据取 Excel 通道（它天然产出 CRLF）：若 `stage-1.csv` 里一个 `\\r\\n` 都没有，
    说明快照落盘把行尾改了，审计器自己成了失真源。
    """
    if not stages.probe("excel_com_csv")[0]:
        pytest.skip("Excel COM 不可用：本机无法产出天然 CRLF 的样本（跳过并标注）")

    run = _run("excel_com", sample_csv, tmp_path / "runs")
    raw = (run.out_dir / "stage-1.csv").read_bytes()
    assert b"\r\n" in raw, "Excel 输出应为 CRLF；快照里没有 CRLF 说明被归一了"
    # 输入副本也必须逐字节等于源文件
    assert (run.out_dir / "stage-0.csv").read_bytes() == sample_csv.read_bytes()


def test_stage0_is_verbatim_input_copy(sample_csv, tmp_path):
    """`stage-0` = 输入原文副本，且**不改源文件**。"""
    before = sample_csv.read_bytes()
    run = _run("json_sqlite", sample_csv, tmp_path / "runs")
    assert (run.out_dir / "stage-0.csv").read_bytes() == before
    assert sample_csv.read_bytes() == before, "源文件被改写了"
    assert run.stages[0].stage_name == "input"


# ── 字段齐全性 ────────────────────────────────────────────────────────────

def test_runtime_fingerprint_fields(sample_csv, tmp_path):
    """`plan/03`：`runtime` 键齐全，不适用字段为 `null` 而非缺键。"""
    for name, run in _all_runs(sample_csv, tmp_path / "runs"):
        data = json.loads((run.out_dir / "stages.json").read_text(encoding="utf-8"))
        for item in data["stages"]:
            assert set(item["runtime"]) >= set(RUNTIME_KEYS), f"{name}: runtime 缺键 {item['runtime'].keys()}"
            for key in RUNTIME_KEYS:
                assert key in item["runtime"], f"{name}: runtime 缺 {key}"


def test_required_stages_json_fields(sample_csv, tmp_path):
    """`data/README` §6.5 的必填字段一个不许少（`columns` 内含 name + declared_type）。"""
    required = {"stage_index", "stage_name", "columns", "rows", "cols", "sha256", "runtime"}
    for name, run in _all_runs(sample_csv, tmp_path / "runs"):
        data = json.loads((run.out_dir / "stages.json").read_text(encoding="utf-8"))
        assert data["run_id"] == run.run_id
        assert data["pipeline"] == name
        for item in data["stages"]:
            assert required <= set(item), f"{name}: 缺字段 {required - set(item)}"
            assert isinstance(item["columns"], list) and item["columns"]
            for column in item["columns"]:
                assert set(column) == {"name", "declared_type"}
            assert isinstance(item["rows"], int) and isinstance(item["cols"], int)


def test_runtime_records_the_engine_that_actually_ran(sample_csv, tmp_path):
    """各通道只填自己那一组版本键（证明"跑的是哪个引擎"有据可查，K3）。

    `excel_com` 是唯一合法的双键通道（`excel_version` + `excel_build`）——
    M5 首屏的括号写的就是这两个，缺 build 就只能写半句。
    """
    expectations = {
        "pandas": ({"pandas_version", "dtypes"}, stages.probe("pandas_csv")[0]),
        "openpyxl": ({"openpyxl_version"}, stages.probe("openpyxl_csv")[0]),
        "excel_com": ({"excel_version", "excel_build"}, stages.probe("excel_com_csv")[0]),
        "json_sqlite": ({"sqlite_version"}, True),
    }
    for name, run in _all_runs(sample_csv, tmp_path / "runs"):
        allowed, available = expectations[name]
        if not available:
            continue
        runtime = json.loads((run.out_dir / "stages.json").read_text(encoding="utf-8"))["stages"][1]["runtime"]
        for key in allowed:
            assert runtime[key], f"{name}: runtime.{key} 为空，无法证明跑的是哪个引擎"
        for other in set(RUNTIME_KEYS) - allowed:
            assert runtime[other] is None, f"{name}: 不该填 {other}（会给人混用的错觉）"


def test_pandas_runtime_includes_dtypes(sample_csv, tmp_path):
    run = _run("pandas", sample_csv, tmp_path / "runs")
    runtime = json.loads((run.out_dir / "stages.json").read_text(encoding="utf-8"))["stages"][1]["runtime"]
    assert runtime["dtypes"], "pandas 通道必须记录读入侧 dtype（F6/F7 的证据）"
    assert set(runtime["dtypes"]) == set(SAMPLE_ROWS[0])  # 表头那一行就是列名


# ── K2 / G9：run_id 与双跑一致性 ──────────────────────────────────────────

def test_same_input_same_run_id(sample_csv, tmp_path):
    """同输入两次 → 同 `run_id`（且产物逐字节一致）。"""
    first = _run("json_sqlite", sample_csv, tmp_path / "a")
    second = _run("json_sqlite", sample_csv, tmp_path / "b")
    assert first.run_id == second.run_id
    assert (first.out_dir / "stages.json").read_bytes() == (second.out_dir / "stages.json").read_bytes()
    assert (first.out_dir / "stage-1.csv").read_bytes() == (second.out_dir / "stage-1.csv").read_bytes()


def test_run_id_ignores_timestamp_and_path():
    """K2：`run_id` 是 `(name, input_sha, decl_sha)` 的纯函数——同一组入参永远同一 id。"""
    a = compute_run_id("pandas", "input-sha", "decl-sha")
    b = compute_run_id("pandas", "input-sha", "decl-sha")
    assert a == b and len(a) == 16
    assert a != compute_run_id("openpyxl", "input-sha", "decl-sha")
    assert a != compute_run_id("pandas", "other-input", "decl-sha")
    assert a != compute_run_id("pandas", "input-sha", "other-decl")


def test_run_id_stable_across_processes(sample_csv, tmp_path):
    """跨进程同 id：证明 id 不依赖 PYTHONHASHSEED / 进程内状态。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    code = (
        "import sys;"
        "from tripwire.pipeline.runner import run_pipeline;"
        "from tripwire.pipeline.schema import load_pipeline;"
        f"r=run_pipeline(load_pipeline(r'{PIPELINES / 'json_sqlite.json'}'), r'{sample_csv}', r'{tmp_path / 'proc'}');"
        "print(r.run_id)"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=300)
    assert proc.returncode == 0, proc.stderr
    in_process = _run("json_sqlite", sample_csv, tmp_path / "here")
    assert proc.stdout.strip() == in_process.run_id


def test_double_run_is_byte_identical(sample_csv, tmp_path):
    """G9：同输入双跑，**全产物**逐字节一致（含 stages.json）。"""
    for name in ALWAYS:
        a = _run(name, sample_csv, tmp_path / f"a-{name}")
        b = _run(name, sample_csv, tmp_path / f"b-{name}")
        assert a.run_id == b.run_id
        for filename in ("stages.json", "stage-0.csv", "stage-1.csv"):
            assert (a.out_dir / filename).read_bytes() == (b.out_dir / filename).read_bytes(), (
                f"{name}: {filename} 两次运行不一致"
            )


def test_rerun_same_out_dir_is_idempotent(sample_csv, tmp_path):
    """同 `run_id` 目录已存在 → 复用，不重跑、不报错；产物不变。"""
    out = tmp_path / "runs"
    first = _run("pandas", sample_csv, out)
    snapshot = (first.out_dir / "stages.json").read_bytes()
    second = _run("pandas", sample_csv, out)
    assert second.reused is True
    assert (second.out_dir / "stages.json").read_bytes() == snapshot


def test_decl_fingerprint_ignores_file_location(sample_csv, tmp_path):
    """同一份语义声明换个文件位置/文件名 → 同 `decl_sha256` → 同 `run_id`。"""
    import shutil

    original = PIPELINES / "json_sqlite.json"
    copy = tmp_path / "renamed-decl.json"
    shutil.copyfile(original, copy)

    a = _run("json_sqlite", sample_csv, tmp_path / "a")
    from tripwire.pipeline.runner import run_pipeline as rp

    b = rp(load_pipeline(copy), sample_csv, tmp_path / "b")
    assert a.run_id == b.run_id


def test_stages_json_has_no_timestamp(sample_csv, tmp_path):
    """确定性硬约束：`stages.json` 里不许有时间字段（否则跨天双跑就不一致了）。"""
    run = _run("pandas", sample_csv, tmp_path / "runs")
    data = json.loads((run.out_dir / "stages.json").read_text(encoding="utf-8"))
    for forbidden in ("generated_at", "timestamp", "created_at", "started_at", "finished_at"):
        assert forbidden not in data
    text = read_text(run.out_dir / "stages.json")
    assert "\r\n" not in text, "JSON 产物必须是 LF 行尾（K11）"
