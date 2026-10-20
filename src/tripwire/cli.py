"""CLI 入口。

两条退出码纪律（口径单点是 `data/README.md` §6.3，代码侧单点是 `exitcodes.py`）：
1. `argparse` 的 `SystemExit(2)` 一律在 `main()` 内转成 3——否则"参数写错"会被读成"门禁失败"。
2. **判定通道只在真有判定时才用**：0/1 的定义里都带"门禁通过"，而门禁在 M4。
   因此 M1 的 `run` 与 M2 的 `diff` 都**不返回 0/1**——差异算出来了也只说"算出来了多少条"，
   不说"无损/有损"。M1 期间 `run` 连差异都没算，M2 起 `diff` 算了差异但没有门禁；
   两者都走用法通道 3，并在输出里把"做了什么"与"拒绝判定"分开写。
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
from tripwire.rules.engine import attribute, explain as explain_line
from tripwire.rules.predicates import load_rules, rule_count
from tripwire import serialization

PROG = "tripwire"

#: 判定通道尚未接线时 `run` 的说明（M5 接线后随 `_cmd_run` 的对应分支一起删除）
NO_VERDICT_NOTE = (
    "NOTE: 本次只执行管线（M1）；差异引擎与门禁在 M2–M5，故**不产出有损/无损判定**，"
    "退出码走用法通道 3（拒绝判定）而非 0（无损）。"
)

#: `diff` 的同类说明：差异算出来了，但 0/1 的语义里带"门禁通过"，而门禁在 M4。
#: 没有门禁就报 0 或 1，等于把"没验过"写成"验过了"。
NO_GATE_NOTE = (
    "NOTE: 差异已算出（M2）；门禁三数与判定在 M4–M5，故**不产出有损/无损判定**，"
    "退出码走用法通道 3（拒绝判定）而非 0/1。"
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

    subparsers.add_parser("gen-fixture", help="生成真值夹具（M4）").add_argument(
        "--seed", type=int, required=True
    )

    report = subparsers.add_parser("report", help="渲染 MD/JSON/SARIF（M5）")
    report.add_argument("--run-id", required=True)
    report.add_argument("--format", default="md,json,sarif")

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


def _cmd_run(pipeline: str, input_csv: str, key: str | None, align: str, out_dir: str) -> int:
    """执行管线并落快照。**不产出判定**（M1 只做到快照；见 `NO_VERDICT_NOTE`）。"""
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
    sys.stdout.write(NO_VERDICT_NOTE + "\n")
    return exitcodes.USAGE


#: `attribute` 的说明：归因有了，但门禁三数（recall/precision）在 M4。
#: 没有 expected.json 就无法算 recall，报 0/1 等于把"没验过"写成"验过了"。
NO_GATE_NOTE_ATTRIBUTE = (
    "NOTE: 归因已算出（M3）；门禁三数（recall/precision/unclassified 口径）与判定在 M4–M5。"
    "`unclassified` 计数已给出，但**不产出有损/无损判定**——退出码走用法通道 3，"
    "除非显式 `--fail-on unclassified` 且有 unclassified（门禁失败 → 2）。"
)


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


def _not_implemented(command: str, milestone: str) -> int:
    sys.stderr.write(
        f"tripwire {command}: 未实现（{milestone}）。\n"
        f"当前为骨架期：本命令不产出任何结论，退出码 {exitcodes.USAGE}（用法通道）。\n"
    )
    return exitcodes.USAGE


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
        return _cmd_run(args.pipeline, args.input, args.key, args.align, args.out_dir)
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
        return _not_implemented("gen-fixture", "M4")
    if command == "report":
        return _not_implemented("report", "M5")

    sys.stderr.write(f"{PROG}: 未知子命令 {command}\n")
    return exitcodes.USAGE


if __name__ == "__main__":
    sys.exit(main())
