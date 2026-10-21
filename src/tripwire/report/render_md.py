"""Markdown 渲染（M5）：**只读** `RunResult`，不重算任何结论、不读 `runs/`。

首屏三段原样放在文件头（第一行起），后面才是给人细看的分节——CI 与人都先读那三行。
任何"值"都取 `RunResult` 已经算好的字段；本模块**不 import** diff / rules / gate /
pipeline（`tests/test_report.py` 有 AST 守门），否则"三格式同源"就只剩纪律、不靠结构。
"""

from __future__ import annotations

from tripwire.report.model import RunResult, runtime_label


def _cell(text: str) -> str:
    """把一段文本放进 Markdown 表格单元格：竖线要转义、换行要显形（否则表格会被撕开）。"""
    escaped = text.replace("\\", "\\\\").replace("|", "\\|")
    return escaped.replace("\r\n", "⏎").replace("\n", "⏎").replace("\r", "⏎")


def _quote(text: str) -> str:
    return text.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


def render(result: RunResult) -> str:
    """`RunResult` -> Markdown 文本。三次渲染输入相同则输出逐字节相同（K9）。"""
    lines: list[str] = [*result.first_screen(), ""]
    lines.append(f"# tripwire 报告 — run `{result.run_id}`")
    lines.append("")

    stage = result.stage(result.stage_index)
    lines.append("> 管线 `%s`；判定阶段 `stage %d = %s`（运行时 `%s`）；对齐策略 `%s`%s。"
                 % (
                     result.pipeline,
                     result.stage_index,
                     result.stage_name,
                     runtime_label(result.stage_name, result.stage_runtime),
                     result.strategy,
                     f"（主键 `{result.key}`）" if result.key else "（按位置/指纹对齐）",
                 ))
    lines.append("")
    lines.append("> 本报告由一次 run 的内存结果生成；`fingerprint` 跨 run 稳定，可用于两次报告对账。")
    lines.append("")

    # 一、结论
    lines.append("## 一、结论")
    lines.append("")
    lines.append("| 项 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| 判定 | `{result.verdict}` |")
    lines.append(f"| 单元格差异 | {len(result.diffs)} / {result.cells_compared} |")
    lines.append(f"| 结构差异 | {len(result.structures)} |")
    lines.append(f"| 命中规则 | {len(result.rules_used)} |")
    lines.append(f"| unclassified | {result.unclassified_count} |")
    lines.append(f"| 门禁 | {'通过' if result.gate.passed else '失败'} |")
    lines.append(f"| 退出码 | {result.exit_code} |")
    lines.append("")

    # 二、门禁三数（明细不折算，三类分开列）
    lines.append("## 二、门禁三数（recall / precision / unclassified）")
    lines.append("")
    lines.append(f"- `{result.gate.line()}`")
    lines.append(
        f"- 期望 {result.gate.expected} / 上报 {result.gate.reported} / 命中 {result.gate.matched}"
    )
    if result.gate.vacuous:
        lines.append("- **空跑**：本次 0 条上报差异，门禁「通过」不代表覆盖了任何样本。")
    lines.append(f"- `missing` {len(result.gate.missing)} / `unexpected` {len(result.gate.unexpected)}"
                 f" / `wrong_rule` {len(result.gate.wrong_rule)}")
    lines.append("")
    for label, items, describe in (
        ("MISSING（真值说会变，本次没报到）", result.gate.missing, _describe_miss),
        ("UNEXPECTED（报了但真值里没有）", result.gate.unexpected, _describe_surprise),
        ("WRONG RULE（变化对上、规则名不对）", result.gate.wrong_rule, _describe_wrong_rule),
    ):
        if not items:
            continue
        lines.append(f"### {label}（{len(items)} 条）")
        lines.append("")
        for item in items:
            lines.append(f"- {describe(item)}")
        lines.append("")

    # 三、逐条归因
    lines.append(f"## 三、逐条归因（{len(result.attributions)} 条）")
    lines.append("")
    lines.append("| fingerprint | rule | row_key | col | orig -> got | first_seen_at | resolved_stage |")
    lines.append("|---|---|---|---|---|---|---|")
    for item in result.attributions:
        lines.append(
            "| `%s` | %s | %s | %s | `%s` -> `%s` | %s | %s |"
            % (
                item.fingerprint,
                item.rule,
                _cell(item.diff.row_key),
                _cell(item.diff.col),
                _cell(_quote(item.diff.orig_text)),
                _cell(_quote(item.diff.got_text)),
                "unknown" if item.first_seen_at is None else f"stage {item.first_seen_at}",
                item.resolved_stage or "-",
            )
        )
    lines.append("")
    if result.unclassified_count:
        lines.append(
            f"> **unclassified {result.unclassified_count} 条**：本 seed / 本样本形态下没有谓词命中，"
            "这是产品特性（D4），不是缺陷——它单独计数，可 `--fail-on unclassified` 拦新形态。"
        )
        lines.append("")

    # 四、结构差异
    lines.append(f"## 四、结构差异（{len(result.structures)} 条）")
    lines.append("")
    if result.structures:
        for item in result.structures:
            lines.append(f"- `{item.kind}`：`{_cell(str(dict(item.detail)))}`")
    else:
        lines.append("- 无（行数 / 列数 / 列序 / 表头四项均未变）")
    lines.append("")

    # 五、逐段快照
    lines.append("## 五、逐段快照")
    lines.append("")
    lines.append("| stage | stage_name | rows | cols | sha256（前 12）| runtime |")
    lines.append("|---|---|---|---|---|---|")
    for snapshot in result.stages:
        lines.append(
            "| %d | %s | %s | %s | %s | %s |"
            % (
                snapshot.stage_index,
                snapshot.stage_name,
                snapshot.rows,
                snapshot.cols,
                (snapshot.sha256 or "")[:12],
                runtime_label(snapshot.stage_name, snapshot.runtime),
            )
        )
    lines.append("")

    # 六、边界与承诺（固定句，`README.md` 与 `plan/01` §六同源）
    lines.append("## 六、边界与承诺")
    lines.append("")
    lines.append("- **归因上限是「环节」，不是「代码行」**：本报告能证明「值在哪一步变成这样」，"
                 "不能证明「是某个引擎的那一行代码」。")
    lines.append("- **纯本地、零网络**：本报告不含网络访问、不含遥测、不含时间戳。")
    if result.strategy != "key":
        lines.append(f"- 本次对齐策略是 `{result.strategy}`（非主键）：插行 / 改行会产生连带差异。")
    lines.append("- 样本为**合成数据**；本报告不构成对常规数据损失率的承诺（`data/README` §6.7）。")
    if result.unclassified_count:
        lines.append(
            f"- `unclassified = {result.unclassified_count}`：未归因条数，单独计数、不并入「其他」。"
        )
    lines.append("")
    return "\n".join(lines)


def _describe_miss(item) -> str:
    return (
        f"`{_cell(item.row_key)}` / `{_cell(item.col)}`：期望 `{_cell(_quote(item.expected_text))}`"
        f"（规则 `{item.rule}`）"
    )


def _describe_surprise(item) -> str:
    return (
        f"`{_cell(item.row_key)}` / `{_cell(item.col)}`：实际上报 `{_cell(_quote(item.got_text))}`"
        f"（规则 `{item.rule}`）"
    )


def _describe_wrong_rule(item) -> str:
    return (
        f"`{_cell(item.row_key)}` / `{_cell(item.col)}`：期望规则 `{item.expected_rule}`，"
        f"实际 `{item.actual_rule}`"
    )


__all__ = ["render"]