"""CLI 入口。

两条退出码纪律（口径单点是 `data/README.md` §6.3，代码侧单点是 `exitcodes.py`）：
1. `argparse` 的 `SystemExit(2)` 一律在 `main()` 内转成 3——否则"参数写错"会被读成"门禁失败"。
2. **判定通道只在真有判定时才用**：0/1/2 的定义里都带"门禁三数"，而门禁要有真值文件。
   因此 M5 之后的出口是：`run --expected`、`report`、`gate`（都是 0/1/2），
   而 `run`（无真值）、`diff`、`attribute` 一律走用法通道 3 并**明说为什么拒绝判定**：
   跑通 ≠ 判为无损（D18）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tripwire import __version__
from tripwire import exitcodes
from tripwire.csvio import read_csv
from tripwire.diff import DiffError, diff_tables
from tripwire.pipeline import runner, stages
from tripwire.pipeline.errors import (
    InputNotUtf8,
    RunIdCollision,
    RunNotFound,
    StageFailed,
    StageUnavailable,
)
from tripwire.pipeline.schema import PipelineDeclError, load_pipeline, load_pipeline_dict, validate_pipeline_dict
from tripwire.report import (
    FORMATS,
    ReportError,
    build_run_result,
    load_expected,
    write_reports,
)
from tripwire.rules.engine import attribute, explain as explain_line
from tripwire.rules.predicates import load_rules, rule_count
from tripwire import serialization

PROG = "tripwire"

#: `run` **未给 `--expected` 真值文件**时的说明：没有真值就没有 recall/precision，
#: 门禁三数无从产生 → 拒绝判定（exit 3），但管线与逐段快照照常落盘。
NO_TRUTH_NOTE = (
    "NOTE: 未给 --expected 真值文件 → **不产出有损/无损判定**（没有 recall/precision 就没有门禁三数），"
    "退出码走用法通道 3。要看判定与三格式报告，请补真值："
    "`tripwire run ... --expected expected.json` 或 `tripwire report --run-id <id> --expected expected.json`。"
)

#: `diff` 的同类说明：差异算出来了，但没有真值就没有门禁三数。
NO_GATE_NOTE = (
    "NOTE: 差异已算出；门禁三数与判定由 `gate` / `report`（或 `run --expected`）产出，"
    "本条命令**不产出有损/无损判定**，退出码走用法通道 3（拒绝判定）而非 0/1。"
)


class _Parser(argparse.ArgumentParser):
    """把 argparse 的 SystemExit(2) 收成 `UsageError`，由 `main()` 统一转 exit 3。"""

    def error(self, message: str):  # type: ignore[override]
        raise _UsageError(message)


class _UsageError(Exception):
    pass


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog=PROG, description="结构化数据往返保真审计器（纯本地、零网络）")
    parser.add_argument("--version", action="version", version=f"{PROG} {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    run = subparsers.add_parser("run", help="执行往返管线并出报告（M1–M5）")
    run.add_argument("--pipeline", required=True, help="管线声明 JSON")
    run.add_argument("--input", required=True, help="原始 CSV")
    run.add_argument("--key", help="主键列名（默认对齐策略 key 必需）")
    run.add_argument("--align", choices=("key", "position", "lcs"), default="key")
    run.add_argument("--out-dir", default="runs", help="运行产物目录（默认 runs/）")
    run.add_argument(
        "--expected",
        help="真值文件（expected.json）：**给出即产出判定与报告**（0/1/2）；不给则不判定（exit 3）",
    )
    run.add_argument("--stage-index", type=int, help="判定哪个输出阶段（默认取最后一份输出）")
    run.add_argument("--format", default="md,json,sarif", help="报告格式（默认 md,json,sarif）")

    diff = subparsers.add_parser("diff", help="对两份快照做单元格级差异（M2）")
    diff.add_argument("--orig", required=True, help="原始快照 CSV（通常是 stage-0.csv）")
    diff.add_argument("--got", required=True, help="往返后快照 CSV（通常是 stage-<k>.csv）")
    diff.add_argument("--key", help="主键列名（--align key 必需）")
    diff.add_argument("--align", choices=("key", "position", "lcs"), default="key")
    diff.add_argument("--batch", type=int, help="按 N 行分块推断类型，不一致落 dtype_drift 结构记录")
    diff.add_argument("--stage-index", type=int, help="把该差异归属到哪个输出阶段序号（1-based）")
    diff.add_argument("--json", dest="json_out", help="把 DiffResult 写成 JSON（走 serialization.write_json）")

    attribute = subparsers.add_parser("attribute", help="对差异做规则归因（M3）")
    attribute.add_argument("--run-id", required=True)
    attribute.add_argument("--out-dir", default="runs", help="运行产物目录（默认 runs/）")
    attribute.add_argument("--key", help="主键列名（必须与产出该 run 时一致；--align key 必需）")
    attribute.add_argument("--align", choices=("key", "position", "lcs"), default="key")
    attribute.add_argument("--stage-index", type=int, help="只归因该阶段相对 stage-0 的差异（默认取最后一份输出）")
    attribute.add_argument("--explain", action="store_true", help="逐条打印归因日志（格式写死）")
    attribute.add_argument("--fail-on", choices=("unclassified",), help="有 unclassified 即 exit 2（门禁失败）")
    attribute.add_argument("--json", dest="json_out", help="把归因结果写成 JSON（走 serialization.write_json）")

    fixture = subparsers.add_parser("gen-fixture", help="生成真值夹具（M4）")
    fixture.add_argument("--seed", type=int, default=42, help="随机种子（默认 42：金样本留档值）")
    fixture.add_argument("--rows", type=int, default=200, help="总行数（默认 200：金样本留档规模）")
    fixture.add_argument("--out-dir", default="fixtures/out", help="落点目录（默认 fixtures/out/）")
    fixture.add_argument(
        "--pool",
        dest="pools",
        action="append",
        choices=("numeric", "semantic", "control"),
        help="只生成某个池（可重复）：**部分运行不写 manifest.json**，也不覆盖 expected.json",
    )

    gate = subparsers.add_parser("gate", help="对一次 run 算门禁三数（M4）")
    gate.add_argument("--run-id", required=True)
    gate.add_argument("--out-dir", default="runs", help="运行产物目录（默认 runs/）")
    gate.add_argument("--expected", required=True, help="真值文件（expected.json）")
    gate.add_argument("--key", help="主键列名（必须与产出该 run 时一致）")
    gate.add_argument("--align", choices=("key", "position", "lcs"), default="key")
    gate.add_argument("--stage-index", type=int, help="只对该阶段算（默认取最后一份输出）")

    report = subparsers.add_parser("report", help="渲染 MD/JSON/SARIF 并判定（M5）")
    report.add_argument("--run-id", required=True)
    report.add_argument("--out-dir", default="runs", help="运行产物目录（默认 runs/）")
    report.add_argument(
        "--expected",
        required=True,
        help="真值文件（expected.json）：首屏第三段 GATE 行的来源（没有真值就不判定）",
    )
    report.add_argument("--key", help="主键列名（必须与产出该 run 时一致；--align key 必需）")
    report.add_argument("--align", choices=("key", "position", "lcs"), default="key")
    report.add_argument("--stage-index", type=int, help="判定哪个输出阶段（默认取最后一份输出）")
    report.add_argument("--format", default="md,json,sarif", help="报告格式（默认 md,json,sarif）")

    subparsers.add_parser("rules", help="列出规则表").add_argument(
        "--count", action="store_true", help="只打印条数"
    )

    validate = subparsers.add_parser("validate-pipeline", help="校验管线声明（不执行）")
    validate.add_argument("declarations", nargs="+", metavar="FILE")

    subparsers.add_parser("selftest", help="离线自检（不读网络、不写 runs/）")

    return parser


def _cmd_validate_pipeline(files: list[str]) -> int:
    failed = False
    for name in files:
        raw = load_pipeline_dict(name)
        problems = validate_pipeline_dict(raw) if raw else ["不是合法 JSON 对象"]
        if problems:
            failed = True
            sys.stderr.write(f"FAIL  {name}\n")
            for problem in problems:
                sys.stderr.write(f"      - {problem}\n")
        else:
            decl = load_pipeline(name)
            stages = ", ".join(stage.stage_name for stage in decl.stages)
            sys.stdout.write(f"PASS  {name}  name={decl.name}  stages=[{stages}]\n")
    return exitcodes.USAGE if failed else exitcodes.LOSSLESS


def _cmd_rules(count_only: bool) -> int:
    rules = load_rules()["rules"]
    if count_only:
        sys.stdout.write(f"{len(rules)}\n")
        return exitcodes.LOSSLESS
    for rule in rules:
        sys.stdout.write(f"{rule['id']:>2}  {rule['family']:<8}  {rule['name']}\n")
    sys.stdout.write(f"total {len(rules)}\n")
    return exitcodes.LOSSLESS


#: `attribute` 的说明：归因有了，但门禁三数（recall/precision）要有真值文件。
#: 没有 expected.json 就无法算 recall，报 0/1 等于把"没验过"写成"验过了"。
NO_GATE_NOTE_ATTRIBUTE = (
    "NOTE: 归因已算出；门禁三数（recall/precision/unclassified 口径）与判定由 `gate` / `report`"
    "（或 `run --expected`）产出。`unclassified` 计数已给出，但本条命令**不产出有损/无损判定**"
    "——退出码走用法通道 3，除非显式 `--fail-on unclassified` 且有 unclassified（门禁失败 → 2）。"
)


def _parse_formats(value: str) -> list[str] | None:
    """`--format md,json,sarif` -> `["md", "json", "sarif"]`；未知格式返回 `None`（CLI 转 exit 3）。

    顺序保留用户给的顺序（落盘与打印都按它），重复项去掉：同一份报告写两次没有意义，
    而且会让"写了哪几份"的计数说谎。
    """
    names = [part.strip() for part in value.split(",") if part.strip()]
    if not names or any(name not in FORMATS for name in names):
        return None
    ordered: list[str] = []
    for name in names:
        if name not in ordered:
            ordered.append(name)
    return ordered


def _print_first_screen(result) -> None:
    """首屏三段：**必须是最先打印的三行**（顺序与字面固定，`plan/03` M5）。"""
    for line in result.first_screen():
        sys.stdout.write(line + "\n")


def _print_gate_notes(result) -> None:
    """空跑要说清楚（`Gate.vacuous` 不许被当成"门禁通过且覆盖了样本"）。"""
    if result.gate.vacuous:
        sys.stdout.write(
            "NOTE: 本次 0 条差异 —— 门禁「通过」是空跑通过，不代表覆盖了任何样本。\n"
        )
    if not result.gate.passed:
        sys.stderr.write(
            f"GATE FAILED  recall {result.gate.recall:.2f} / precision {result.gate.precision:.2f} / "
            f"unclassified {result.gate.unclassified}（三者须同时满足，data/README §6.2）\n"
        )


def _print_report_tail(result, written) -> None:
    sys.stdout.write(
        f"REPORT  run_id {result.run_id}  pipeline {result.pipeline}  "
        f"stage {result.stage_index} ({result.stage_name})\n"
        f"           strategy={result.strategy}  rows {result.rows_compared}  "
        f"cells {len(result.diffs)}/{result.cells_compared}  structures {len(result.structures)}  "
        f"rules {len(result.rules_used)}  unclassified {result.unclassified_count}\n"
    )
    for path in written:
        sys.stdout.write(f"      {path.name:<12} {path}\n")


def _build_report(run, expected_path, key, align, stage_index):
    """读真值 -> 建内存结果。失败一律 `ReportError`（调用方转 exit 3）。"""
    return build_run_result(
        run,
        load_expected(expected_path),
        key=key,
        strategy=align,
        stage_index=stage_index,
    )


def _cmd_run(
    pipeline: str,
    input_csv: str,
    key: str | None,
    align: str,
    out_dir: str,
    expected_path: str | None,
    stage_index: int | None,
    formats_raw: str,
) -> int:
    """执行管线；**给了真值才判定**（M5 起 `run` 串起 M1→M2→M3→M5，见 plan/02 §一）。

    - 给了 `--expected`：跑管线 → 差异 → 归因 → 门禁 → 三格式报告 → 首屏三段 → 0/1/2。
    - 没给 `--expected`：只跑管线与快照，**拒绝判定**（exit 3，见 `NO_TRUTH_NOTE`）。
    """
    formats = _parse_formats(formats_raw)
    if formats is None:
        sys.stderr.write(f"FAIL  未知 --format {formats_raw!r}（可用: {', '.join(FORMATS)}）\n")
        return exitcodes.USAGE

    try:
        decl = load_pipeline(pipeline)
    except PipelineDeclError as error:
        sys.stderr.write(f"FAIL  管线声明非法: {pipeline}\n      - {error}\n")
        return exitcodes.USAGE

    # 主键纪律（K4/D3）在这里先挡一次：缺 --key 的 key 对齐即使 M2 才实现，也不该先跑一分钟管线
    if align == "key" and not key:
        sys.stderr.write(
            "FAIL  未声明主键：--align key 需要 --key <列名>；"
            "不猜对齐（若要按位置比，请显式 --align position）。\n"
        )
        return exitcodes.USAGE

    try:
        run = runner.run_pipeline(decl, input_csv, out_dir)
    except InputNotUtf8 as error:
        sys.stderr.write(f"FAIL  {error}\n")
        return exitcodes.USAGE
    except StageUnavailable as error:
        sys.stderr.write(f"FAIL  阶段不可用: {error.stage_name}: {error.reason}\n")
        _write_failure_hint(error)
        return exitcodes.USAGE
    except StageFailed as error:
        sys.stderr.write(f"FAIL  阶段失败: {error.stage_name}: {error.reason}\n")
        _write_failure_hint(error)
        return exitcodes.USAGE
    except RunIdCollision as error:
        sys.stderr.write(f"FAIL  {error}\n")
        return exitcodes.USAGE

    if expected_path is not None:
        try:
            result = _build_report(run, expected_path, key, align, stage_index)
        except ReportError as error:
            # 管线已跑完（产物是合法留档），但判定无从产生 → 拒绝判定，退出码 3
            sys.stderr.write(f"FAIL  {error}\n")
            return exitcodes.USAGE
        written = write_reports(result, run.out_dir, formats)
        _print_first_screen(result)
        _print_gate_notes(result)
        _print_pipeline_lines(run)
        _print_report_tail(result, written)
        return result.exit_code

    _print_pipeline_lines(run)
    sys.stdout.write(NO_TRUTH_NOTE + "\n")
    return exitcodes.USAGE


def _print_pipeline_lines(run) -> None:
    sys.stdout.write(
        f"PASS  pipeline {run.pipeline_name}  run_id {run.run_id}"
        f"{'  (reused)' if run.reused else ''}  stages {len(run.outputs)}\n"
    )
    for snapshot in run.stages:
        sha = (snapshot.sha256 or "")[:12]
        sys.stdout.write(
            f"      stage {snapshot.stage_index} = {snapshot.stage_name:<14} "
            f"rows {snapshot.rows}  cols {snapshot.cols}  sha256 {sha}\n"
        )
    sys.stdout.write(f"      out  {run.out_dir}\n")


def _cmd_report(
    run_id: str,
    out_dir: str,
    expected_path: str,
    key: str | None,
    align: str,
    stage_index: int | None,
    formats_raw: str,
) -> int:
    """对一次已存在的 run 重算判定并渲染 MD/JSON/SARIF（M5 的判定出口，0/1/2/3）。

    为什么 `report` 也要 `--expected`：首屏第三段就是门禁三数，没有真值就只能编一个。
    差异与归因照旧从**当时那批快照**重算（`load_run` 只读产物），不重跑管线。
    """
    formats = _parse_formats(formats_raw)
    if formats is None:
        sys.stderr.write(f"FAIL  未知 --format {formats_raw!r}（可用: {', '.join(FORMATS)}）\n")
        return exitcodes.USAGE

    run_dir = Path(out_dir) / run_id
    try:
        run = runner.load_run(run_dir)
    except (RunNotFound, OSError) as error:
        sys.stderr.write(f"FAIL  读不到该 run: {run_dir}\n      - {error}\n")
        return exitcodes.USAGE

    try:
        result = _build_report(run, expected_path, key, align, stage_index)
    except ReportError as error:
        sys.stderr.write(f"FAIL  {error}\n")
        return exitcodes.USAGE

    written = write_reports(result, run_dir, formats)
    _print_first_screen(result)
    _print_gate_notes(result)
    _print_report_tail(result, written)
    return result.exit_code


def _cmd_diff(
    orig_path: str,
    got_path: str,
    key: str | None,
    align: str,
    batch: int | None,
    stage_index: int | None,
    json_out: str | None,
) -> int:
    """对两份快照做单元格级差异（M2）。**不产出判定**（门禁在 M4；见 `NO_GATE_NOTE`）。"""
    try:
        orig, _ = read_csv(orig_path)
        got, _ = read_csv(got_path)
    except (FileNotFoundError, UnicodeDecodeError) as error:
        sys.stderr.write(f"FAIL  快照不可读: {error}\n")
        return exitcodes.USAGE

    try:
        result = diff_tables(
            orig,
            got,
            strategy=align,
            key=key,
            batch=batch,
            stage_index=stage_index,
        )
    except DiffError as error:
        # K4/D3：拒绝运行要走 exit 3，且**不产出任何差异结论**（不写 --json，也不打印 0 条）
        sys.stderr.write(f"FAIL  {error}\n")
        return exitcodes.USAGE

    sys.stdout.write(
        f"DIFF  strategy={result.strategy}  rows {result.rows_compared}  cells {result.cells_compared}  "
        f"diffs {len(result.diffs)}  structures {len(result.structures)}\n"
    )
    for record in result.diffs:
        sys.stdout.write(
            f"      {record.row_key}  {record.col}[{record.col_index}]  "
            f"{record.orig_text!r} -> {record.got_text!r}\n"
        )
    for structure in result.structures:
        sys.stdout.write(f"      STRUCT {structure.kind}  {_structure_summary(structure.detail)}\n")

    if json_out:
        serialization.write_json(json_out, result.to_json())
        sys.stdout.write(f"      json  {json_out}\n")

    sys.stdout.write(NO_GATE_NOTE + "\n")
    return exitcodes.USAGE


def _cmd_attribute(
    run_id: str,
    out_dir: str,
    key: str | None,
    align: str,
    stage_index: int | None,
    explain: bool,
    fail_on: str | None,
    json_out: str | None,
) -> int:
    """对一次 run 的差异做规则归因（M3）。**不产出判定**（门禁三数在 M4；见 `NO_GATE_NOTE_ATTRIBUTE`）。"""
    run_dir = Path(out_dir) / run_id
    try:
        run = runner.load_run(run_dir)
    except (RunNotFound, OSError) as error:
        sys.stderr.write(f"FAIL  读不到该 run: {run_dir}\n      - {error}\n")
        return exitcodes.USAGE

    outputs = [snapshot for snapshot in run.stages if snapshot.stage_index > 0 and snapshot.ok]
    if not outputs:
        sys.stderr.write(f"FAIL  {run_dir} 里没有任何成功的输出阶段，无从归因。\n")
        return exitcodes.USAGE
    target = stage_index if stage_index is not None else outputs[-1].stage_index
    if target not in {snapshot.stage_index for snapshot in outputs}:
        sys.stderr.write(
            f"FAIL  指定阶段 {target} 不在该 run 的输出里（可用: "
            f"{', '.join(str(snapshot.stage_index) for snapshot in outputs)}）。\n"
        )
        return exitcodes.USAGE

    try:
        orig, _ = read_csv(run.out_dir / "stage-0.csv")
        got, _ = read_csv(run.out_dir / f"stage-{target}.csv")
    except (FileNotFoundError, UnicodeDecodeError) as error:
        sys.stderr.write(f"FAIL  快照不可读: {error}\n")
        return exitcodes.USAGE

    try:
        result = diff_tables(orig, got, strategy=align, key=key, stage_index=target)
    except DiffError as error:
        sys.stderr.write(f"FAIL  {error}\n")
        return exitcodes.USAGE

    attributions = attribute(result.diffs, run, key=key, strategy=align)
    unclassified = sum(1 for item in attributions if item.unclassified)
    rules_used = len({item.rule for item in attributions if not item.unclassified})

    sys.stdout.write(
        f"ATTRIBUTE  run_id {run.run_id}  pipeline {run.pipeline_name}  stage {target} "
        f"({run.stage(target).stage_name})\n"
        f"           strategy={result.strategy}  diffs {len(result.diffs)}  "
        f"rules {rules_used}  unclassified {unclassified}\n"
    )
    for item in attributions:
        sys.stdout.write(
            f"      {item.fingerprint}  {item.diff.row_key}  {item.diff.col}  "
            f"{item.rule}"
            + ("  [UNCLASSIFIED]" if item.unclassified else "")
            + "\n"
        )
        if explain:
            sys.stdout.write(f"        {explain_line(item)}\n")

    if json_out:
        serialization.write_json(
            json_out,
            {
                "run_id": run.run_id,
                "pipeline": run.pipeline_name,
                "stage_index": target,
                "strategy": result.strategy,
                "diffs": len(result.diffs),
                "unclassified": unclassified,
                "attributions": [item.to_json() for item in attributions],
            },
        )
        sys.stdout.write(f"      json  {json_out}\n")

    if fail_on == "unclassified" and unclassified:
        sys.stderr.write(f"GATE FAILED  unclassified {unclassified} > 0（--fail-on unclassified）\n")
        return exitcodes.GATE_FAILED

    sys.stdout.write(NO_GATE_NOTE_ATTRIBUTE + "\n")
    return exitcodes.USAGE


def _cmd_gen_fixture(seed: int, rows: int, out_dir: str, pools: list[str] | None) -> int:
    """生成真值夹具（M4）。**不产出判定**：夹具是门禁的输入，不是门禁的结论。"""
    from tripwire.fixtures import generate, POOL_CONTROL, POOL_NUMERIC, POOL_SEMANTIC

    alias = {"numeric": POOL_NUMERIC, "semantic": POOL_SEMANTIC, "control": POOL_CONTROL}
    selected = [alias[name] for name in pools] if pools else None

    try:
        result = generate(seed, rows, out_dir, pools=selected)
    except (ValueError, OSError) as error:
        sys.stderr.write(f"FAIL  夹具生成失败: {error}\n")
        return exitcodes.USAGE

    sys.stdout.write(
        f"PASS  gen-fixture  seed {result.seed}  rows {result.rows}  "
        f"pools {', '.join(f'{name}={count}' for name, count in result.pools.items())}\n"
    )
    sys.stdout.write(f"      cells {len(result.cells)}  orig {result.orig_path}\n")
    if result.wrote_manifest:
        sys.stdout.write(f"      expected {result.expected_path}\n      manifest {result.manifest_path}\n")
    else:
        sys.stdout.write(
            "      NOTE: 部分运行（--pool）**不写** manifest.json / expected.json："
            "入仓清单只该由全集生成写出（plan/04 §五.5）。\n"
        )
    if result.uncovered_rules:
        sys.stdout.write(
            f"      UNCOVERED  {len(result.uncovered_rules)} 条规则在本 seed 下无正例: "
            f"{', '.join(result.uncovered_rules)}\n"
        )
    return exitcodes.LOSSLESS


def _cmd_gate(
    run_id: str,
    out_dir: str,
    expected_path: str,
    key: str | None,
    align: str,
    stage_index: int | None,
) -> int:
    """算门禁三数并判定（M4）。**第一条真正的判定通道**：0/1/2。

    - 0 = 无损（0 条差异 且 门禁通过）
    - 1 = 有损（有差异 且 门禁通过）
    - 2 = 门禁失败（recall / precision / unclassified 任一不满足）
    - 3 = 用法错误（读不到 run / 真值文件 / 缺 --key）

    M5 起 `gate` 与 `report` / `run --expected` 共用同一套"差异→归因→门禁"实现
    （`report.model.build_run_result`）：这里只保留它自己的打印形态。
    """
    run_dir = Path(out_dir) / run_id
    try:
        run = runner.load_run(run_dir)
    except (RunNotFound, OSError) as error:
        sys.stderr.write(f"FAIL  读不到该 run: {run_dir}\n      - {error}\n")
        return exitcodes.USAGE

    try:
        result = _build_report(run, expected_path, key, align, stage_index)
    except ReportError as error:
        sys.stderr.write(f"FAIL  {error}\n")
        return exitcodes.USAGE

    gate = result.gate
    target = result.stage_index
    stage_name = result.stage_name

    sys.stdout.write(
        f"GATE RUN  run_id {run.run_id}  pipeline {run.pipeline_name}  "
        f"stage {target} ({stage_name})\n"
    )
    sys.stdout.write(f"           {gate.line()}\n")
    sys.stdout.write(
        f"           cells expected {gate.expected}  reported {gate.reported}  matched {gate.matched}"
        f"  missing {len(gate.missing)}  unexpected {len(gate.unexpected)}"
        f"  wrong_rule {len(gate.wrong_rule)}\n"
    )
    for item in gate.missing[:20]:
        sys.stdout.write(
            f"      MISSING     {item.row_key}  {item.col}  expected {item.expected_text!r}"
            f"  rule {item.rule}\n"
        )
    for item in gate.unexpected[:20]:
        sys.stdout.write(
            f"      UNEXPECTED  {item.row_key}  {item.col}  got {item.got_text!r}  rule {item.rule}\n"
        )
    for item in gate.wrong_rule[:20]:
        sys.stdout.write(
            f"      WRONG RULE  {item.row_key}  {item.col}  expected {item.expected_rule}"
            f"  actual {item.actual_rule}\n"
        )

    if gate.vacuous:
        sys.stdout.write(
            "      NOTE: 本次 0 条差异 —— 门禁「通过」是空跑通过，不代表覆盖了任何样本。\n"
        )

    if not gate.passed:
        sys.stderr.write(
            f"GATE FAILED  recall {gate.recall:.2f} / precision {gate.precision:.2f} / "
            f"unclassified {gate.unclassified}（三者须同时满足，data/README §6.2）\n"
        )
    return result.exit_code


def _structure_summary(detail) -> str:
    """结构记录的一句话摘要。只写**这一条结构差异**的信息，不掺单元格差异数。"""
    parts = []
    for key in ("orig", "got", "added", "removed", "side", "col", "types"):
        if key in detail:
            value = detail[key]
            parts.append(f"{key}={value}")
    if "missing_rows" in detail and detail["missing_rows"]:
        parts.append(f"missing_rows={detail['missing_rows']}")
    if "extra_rows" in detail and detail["extra_rows"]:
        parts.append(f"extra_rows={detail['extra_rows']}")
    return " ".join(parts)


def _write_failure_hint(error: StageUnavailable | StageFailed) -> None:
    """把"失败已留痕"这件事说出来；没有留痕就明说没有，不含糊。"""
    path = getattr(error, "stages_path", None)
    if path is not None:
        sys.stderr.write(f"      已在 {path} 写入 failed 记录；整条管线已终止（不跳过、不回落）。\n")
    else:
        sys.stderr.write("      未写出 stages.json（失败发生在阶段记录之前）。\n")


def _cmd_selftest() -> int:
    """离线自检：只验内部不变量，不读网络、不写 runs/。

    M1 起同时报告**四条通道的本机可用性**：不可用的通道在这里显式写出来，
    这样"Linux 上 excel_com_csv 跑不了"是一件看得见的事实，而不是靠人记住的约定。
    """
    problems = []
    if rule_count() != 18:
        problems.append(f"rules.json 条数应为 18，实际 {rule_count()}")
    for name in ("pipelines/pandas.json", "pipelines/excel_com.json", "pipelines/json_sqlite.json", "pipelines/openpyxl.json"):
        if not Path(name).is_file():
            problems.append(f"缺管线声明: {name}")
            continue
        try:
            load_pipeline(name)
        except PipelineDeclError as error:
            problems.append(f"{name}: {error}")
    for problem in problems:
        sys.stderr.write(f"FAIL  {problem}\n")
    if problems:
        return exitcodes.USAGE
    sys.stdout.write(f"selftest OK  version={__version__}  rules={rule_count()}  pipelines=4\n")
    for stage_name in sorted(stages.PROBES):
        ok, reason = stages.probe(stage_name)
        sys.stdout.write(
            f"      stage {stage_name:<14} {'available' if ok else 'UNAVAILABLE'}"
            + ("" if ok else f"  ({reason})")
            + "\n"
        )
    return exitcodes.LOSSLESS


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except _UsageError as error:
        sys.stderr.write(f"{PROG}: 用法错误: {error}\n")
        sys.stderr.write(parser.format_usage())
        return exitcodes.USAGE
    except SystemExit as error:  # --help / --version 走这里（0）；其余走 _UsageError
        return int(error.code or 0)

    command = args.command
    if command is None:
        sys.stderr.write(f"{PROG}: 需要子命令\n")
        sys.stderr.write(parser.format_usage())
        return exitcodes.USAGE

    if command == "validate-pipeline":
        return _cmd_validate_pipeline(args.declarations)
    if command == "rules":
        return _cmd_rules(args.count)
    if command == "selftest":
        return _cmd_selftest()
    if command == "run":
        return _cmd_run(
            args.pipeline,
            args.input,
            args.key,
            args.align,
            args.out_dir,
            args.expected,
            args.stage_index,
            args.format,
        )
    if command == "diff":
        return _cmd_diff(args.orig, args.got, args.key, args.align, args.batch, args.stage_index, args.json_out)
    if command == "attribute":
        return _cmd_attribute(
            args.run_id,
            args.out_dir,
            args.key,
            args.align,
            args.stage_index,
            args.explain,
            args.fail_on,
            args.json_out,
        )
    if command == "gen-fixture":
        return _cmd_gen_fixture(args.seed, args.rows, args.out_dir, args.pools)
    if command == "gate":
        return _cmd_gate(
            args.run_id,
            args.out_dir,
            args.expected,
            args.key,
            args.align,
            args.stage_index,
        )
    if command == "report":
        return _cmd_report(
            args.run_id,
            args.out_dir,
            args.expected,
            args.key,
            args.align,
            args.stage_index,
            args.format,
        )

    sys.stderr.write(f"{PROG}: 未知子命令 {command}\n")
    return exitcodes.USAGE


if __name__ == "__main__":
    sys.exit(main())
