"""CLI 入口（骨架期）。

骨架期的约定：**未实现的子命令返回 exit 3（用法通道），不伪造空结果**。
`argparse` 的 `SystemExit(2)` 一律在 `main()` 内转成 3——否则"参数写错"会被读成"门禁失败"。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tripwire import __version__
from tripwire import exitcodes
from tripwire.pipeline.schema import PipelineDeclError, load_pipeline, load_pipeline_dict, validate_pipeline_dict
from tripwire.rules.predicates import load_rules, rule_count

PROG = "tripwire"


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
    diff.add_argument("--orig", required=True)
    diff.add_argument("--got", required=True)
    diff.add_argument("--key")
    diff.add_argument("--align", choices=("key", "position", "lcs"), default="key")

    attribute = subparsers.add_parser("attribute", help="对差异做规则归因（M3）")
    attribute.add_argument("--run-id", required=True)

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


def _cmd_selftest() -> int:
    """离线自检：只验内部不变量，不读网络、不写 runs/。"""
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
        return _not_implemented("run", "M1–M5")
    if command == "diff":
        return _not_implemented("diff", "M2")
    if command == "attribute":
        return _not_implemented("attribute", "M3")
    if command == "gen-fixture":
        return _not_implemented("gen-fixture", "M4")
    if command == "report":
        return _not_implemented("report", "M5")

    sys.stderr.write(f"{PROG}: 未知子命令 {command}\n")
    return exitcodes.USAGE


if __name__ == "__main__":
    sys.exit(main())
