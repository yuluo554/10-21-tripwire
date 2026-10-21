"""门禁三数（M4）：`compute_gate(expected, attributions) -> Gate`。

**口径不在本文件定义**：`recall` / `precision` / `unclassified` 的唯一定义是
`data/README.md` §6.2，退出码是 §6.3。本模块只**实现**它，并把"为什么不通过"说清楚。

```
GATE = (recall == 1.0) AND (precision == 1.0) AND (unclassified == 0)
```

- `recall    = 命中且规则正确的差异 / expected.json 中属于本阶段的差异`
- `precision = 命中且规则正确的差异 / 全部上报差异`
- `unclassified` = 上报但无规则命中的差异**条数**（不是比例）

四条实现纪律：

1. **分母只取"本阶段真会变"的期望**。`expected.json` 的 `p_after` 按阶段名分键——
   同一形态在 `pandas_csv` 与 `excel_com_csv` 的期望不同（`19.90` 两边都变，
   但 16 位整数只在 Excel 变）。拿全表去算 `excel_com_csv` 的 recall 会凭空少一半。
2. **`control-lossless` 零差异是 precision 的推论，不是另立一条规则**：控制行不在
   `expected.json` 的 `cells` 里，所以它们一旦上报差异就是 `unexpected` → precision < 1。
   把它写成独立判断会让"控制组有没有被测到"变成一个可以两边都对的空断言。
3. **空分母不等于通过**：`reported == 0` 时 precision 记 1.0（没有误报），但 `Gate.vacuous`
   会标出"这次什么都没比"。测试据此断言金样本的运行**不是**空跑——否则"全绿"可能只是"什么都没查"。
4. **不通过要说清是怎么不通过**：`missing`（该变的没变 / 期望正确却没报）与
   `unexpected`（报了但真值里没有）分开列，`wrong_rule`（报了、也在真值里，但规则名不对）
   再单列。三者混成一个数，报告只能写"门禁失败"，无法指向唯一样本。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from tripwire.rules.engine import UNCLASSIFIED, Attribution

#: 期望判定用的小数位（`data/README` §6.2 的 `1.00` 写法）
GATE_DIGITS = 2

#: `recall` / `precision` 的通过线（§6.2 里写死为 1.0，不做"差不多"）
PASS_RATIO = 1.0


@dataclass(frozen=True)
class GateMiss:
    """一条"该变没变"：真值里有、本次没报到。"""

    row_key: str
    col: str
    stage_name: str
    expected_text: str
    rule: str

    def to_json(self) -> dict:
        return {
            "row_key": self.row_key,
            "col": self.col,
            "stage_name": self.stage_name,
            "expected_text": self.expected_text,
            "rule": self.rule,
        }


@dataclass(frozen=True)
class GateSurprise:
    """一条"报了但真值里没有"：precision 的失分点。"""

    row_key: str
    col: str
    stage_name: str
    got_text: str
    rule: str

    def to_json(self) -> dict:
        return {
            "row_key": self.row_key,
            "col": self.col,
            "stage_name": self.stage_name,
            "got_text": self.got_text,
            "rule": self.rule,
        }


@dataclass(frozen=True)
class GateWrongRule:
    """一条"变化对上了、规则名不对"：既不是漏报也不是误报，是归因错。"""

    row_key: str
    col: str
    stage_name: str
    expected_rule: str
    actual_rule: str

    def to_json(self) -> dict:
        return {
            "row_key": self.row_key,
            "col": self.col,
            "stage_name": self.stage_name,
            "expected_rule": self.expected_rule,
            "actual_rule": self.actual_rule,
        }


@dataclass(frozen=True)
class Gate:
    """门禁三数 + 三族的失败明细。`passed` 是唯一的判定出口。"""

    stage_name: str
    recall: float
    precision: float
    unclassified: int
    expected: int
    reported: int
    matched: int
    missing: tuple[GateMiss, ...] = ()
    unexpected: tuple[GateSurprise, ...] = ()
    wrong_rule: tuple[GateWrongRule, ...] = ()

    @property
    def vacuous(self) -> bool:
        """这次"门禁通过"是不是因为什么都没查（`reported == 0`）。"""
        return self.reported == 0

    @property
    def passed(self) -> bool:
        return (
            self.recall >= PASS_RATIO
            and self.precision >= PASS_RATIO
            and self.unclassified == 0
        )

    def line(self) -> str:
        """首屏那一行。**字面写死**（`plan/03` M5 / `data/README` §6.2）。"""
        return (
            f"GATE: recall {self.recall:.{GATE_DIGITS}f} "
            f"precision {self.precision:.{GATE_DIGITS}f} "
            f"unclassified {self.unclassified}"
        )

    def to_json(self) -> dict:
        return {
            "stage_name": self.stage_name,
            "recall": self.recall,
            "precision": self.precision,
            "unclassified": self.unclassified,
            "passed": self.passed,
            "vacuous": self.vacuous,
            "counts": {
                "expected": self.expected,
                "reported": self.reported,
                "matched": self.matched,
            },
            "missing": [item.to_json() for item in self.missing],
            "unexpected": [item.to_json() for item in self.unexpected],
            "wrong_rule": [item.to_json() for item in self.wrong_rule],
        }


def expected_for_stage(
    expected: Iterable[Mapping[str, str]],
    stage_name: str,
) -> dict[tuple[str, str], str]:
    """把 `expected.json` 的 `p_after` 摊平成 `{(row_key, col): 期望文本}`（只取本阶段）。

    `expected` 每项形状 = `{"cell": [row_key, col], "rule": ..., "p_after": {stage: text}}`。
    没有本阶段键的条目**不是**"期望不变"，而是"本阶段不管这一格"——两者都不进分母，
    但含义不同：前者该由 `unexpected` 抓（它若变了就是误报），后者没人管。
    这里只负责前者：只返回 `p_after` 里有本阶段键的那些。
    """
    table: dict[tuple[str, str], str] = {}
    for item in expected:
        after = item.get("p_after") or {}
        if stage_name not in after:
            continue
        row_key, col = item["cell"]
        table[(row_key, col)] = after[stage_name]
    return table


def rules_for_stage(
    expected: Iterable[Mapping[str, str]],
    stage_name: str,
) -> dict[tuple[str, str], str]:
    """`{(row_key, col): 规则名}`，同样只取本阶段有期望的条目。"""
    table: dict[tuple[str, str], str] = {}
    for item in expected:
        after = item.get("p_after") or {}
        if stage_name not in after:
            continue
        row_key, col = item["cell"]
        table[(row_key, col)] = item["rule"]
    return table


def compute_gate(
    expected: Sequence[Mapping[str, str]],
    attributions: Sequence[Attribution],
    *,
    stage_name: str,
) -> Gate:
    """算门禁三数。`expected` 是 `expected.json` 的 `cells` 列表，`attributions` 是本次 run 的归因。"""
    wanted_text = expected_for_stage(expected, stage_name)
    wanted_rule = rules_for_stage(expected, stage_name)

    missing: list[GateMiss] = []
    unexpected: list[GateSurprise] = []
    wrong_rule: list[GateWrongRule] = []
    matched = 0
    unclassified = 0

    seen: set[tuple[str, str]] = set()
    for item in attributions:
        key = (item.diff.row_key, item.diff.col)
        seen.add(key)
        if item.unclassified:
            unclassified += 1
        if key not in wanted_text:
            unexpected.append(
                GateSurprise(
                    row_key=item.diff.row_key,
                    col=item.diff.col,
                    stage_name=stage_name,
                    got_text=item.diff.got_text,
                    rule=item.rule,
                )
            )
            continue
        if item.diff.got_text != wanted_text[key]:
            # 值对不上：真值说会变成 A，实际是 B —— 这是夹具/引擎两边必有一错，按未命中计
            unexpected.append(
                GateSurprise(
                    row_key=item.diff.row_key,
                    col=item.diff.col,
                    stage_name=stage_name,
                    got_text=item.diff.got_text,
                    rule=item.rule,
                )
            )
            continue
        if item.rule != wanted_rule.get(key):
            wrong_rule.append(
                GateWrongRule(
                    row_key=item.diff.row_key,
                    col=item.diff.col,
                    stage_name=stage_name,
                    expected_rule=wanted_rule.get(key, ""),
                    actual_rule=item.rule,
                )
            )
            continue
        matched += 1

    for key, text in sorted(wanted_text.items()):
        if key in seen:
            continue
        missing.append(
            GateMiss(
                row_key=key[0],
                col=key[1],
                stage_name=stage_name,
                expected_text=text,
                rule=wanted_rule.get(key, ""),
            )
        )

    expected_count = len(wanted_text)
    reported_count = len(attributions)
    recall = matched / expected_count if expected_count else PASS_RATIO
    precision = matched / reported_count if reported_count else PASS_RATIO

    return Gate(
        stage_name=stage_name,
        recall=recall,
        precision=precision,
        unclassified=unclassified,
        expected=expected_count,
        reported=reported_count,
        matched=matched,
        missing=tuple(missing),
        unexpected=tuple(unexpected),
        wrong_rule=tuple(wrong_rule),
    )


__all__ = [
    "GATE_DIGITS",
    "PASS_RATIO",
    "Gate",
    "GateMiss",
    "GateSurprise",
    "GateWrongRule",
    "compute_gate",
    "expected_for_stage",
    "rules_for_stage",
]
