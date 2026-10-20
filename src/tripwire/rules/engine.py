"""归因规则引擎（M3）：`attribute(...) -> list[Attribution]`。

**归因不是猜**（D2）：规则只给 `possible_stages` 候选集，真正的环节由 M1 的快照序列
**筛掉**不可能的阶段。两条硬纪律：

- **K6**：一条差异命中多条规则时，按 `id` 升序取**首条**，其余写进 `evidence.also_matched`
  —— 不静默丢弃（"这条差异还像什么"本身是证据）。
- **D1**：候选阶段与该 run 的实际阶段名**无交集** → `resolved_stage = None` 且 `rule` 降级为
  `unclassified`。**宁可 unclassified，不伪造归因**：`openpyxl_csv` 跑出的 15 位截断
  绝不能被写成"Excel 干的"。

`fingerprint` 的口径（K10）唯一来源是 `data/README.md` §6.4：
`sha256(f"{row_key}\\x1f{col}\\x1f{rule}").hexdigest()[:16]`。
不含时间戳 / run_id / 路径 / 机器名——所以同一输入在不同机器、不同 run 下 fingerprint 相同，
报告才能跨 run diff。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from tripwire.diff.engine import DiffRecord
from tripwire.pipeline.model import INPUT_STAGE_NAME, RunStages
from tripwire.rules.predicates import predicate_for, rules_by_id

#: 无规则命中时的规则名（一等公民，单独计数；不是 `None`，避免下游到处判空）
UNCLASSIFIED = "unclassified"

FINGERPRINT_LENGTH = 16


@dataclass(frozen=True)
class Attribution:
    """一条差异的归因结果。

    `first_seen_at` 是 1-based 的**输出阶段序号**（`stage-1` = 第一份输出），与 `stages.json`
    的 `stage_index` 同一套编号；拿不到阶段序列时为 `None`（离线只比两份文件的情况）。
    """

    diff: DiffRecord
    rule: str
    first_seen_at: int | None = None
    candidates: tuple[str, ...] = ()
    resolved_stage: str | None = None
    also_matched: tuple[str, ...] = ()
    stage_meta: Mapping[str, Any] | None = None
    #: 首次观察到变化的阶段名（日志括号里写的就是它）。与 `resolved_stage` **不是同一个东西**：
    #: 前者是"实际在哪一步变的"，后者是"规则候选里的哪一个"。两者不同恰恰是最有信息量的情形，
    #: 所以不能用一个字段兼表两件事。
    first_seen_stage: str | None = None

    @property
    def fingerprint(self) -> str:
        """K10：`sha256(row_key \\x1f col \\x1f rule)[:16]`。

        `fingerprint` 是 **property** 而不是字段：存成字段就有"两处口径"的风险，
        而它必须是 `(row_key, col, rule)` 的纯函数——改规则名即改 fingerprint，是期望行为。
        """
        return make_fingerprint(self.diff.row_key, self.diff.col, self.rule)

    @property
    def unclassified(self) -> bool:
        return self.rule == UNCLASSIFIED

    def evidence(self) -> dict[str, Any]:
        """证据三元组 + 其余命中。空字段在这里**不允许**出现（下游 `test_every_attribution_has_evidence` 会查）。"""
        return {
            "orig_text": self.diff.orig_text,
            "got_text": self.diff.got_text,
            "also_matched": list(self.also_matched),
            "stage_meta": dict(self.stage_meta or {}),
        }

    def to_json(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "rule": self.rule,
            "row_key": self.diff.row_key,
            "col": self.diff.col,
            "col_index": self.diff.col_index,
            "first_seen_at": self.first_seen_at,
            "first_seen_stage": self.first_seen_stage,
            "candidates": list(self.candidates),
            "resolved_stage": self.resolved_stage,
            "evidence": self.evidence(),
        }


def make_fingerprint(row_key: str, col: str, rule: str) -> str:
    """K10 的唯一实现。任何别处再拼一次就是第二份口径。"""
    material = f"{row_key}\x1f{col}\x1f{rule}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:FINGERPRINT_LENGTH]


def stage_texts(run: RunStages) -> tuple[tuple[int, str, Any], ...]:
    """把一次 run 的快照按 `stage_index` 升序读成 `(index, stage_name, CsvTable)`。

    只读 `stage-<k>.csv` 的**原始文本**（K1）：归因要回答"值在哪一步变的"，
    任何一次重新序列化都会让"变没变"这个问题本身失真。
    """
    from tripwire.csvio import read_csv

    texts = []
    for snapshot in sorted(run.stages, key=lambda item: item.stage_index):
        if not snapshot.ok:
            continue
        path = run.out_dir / f"stage-{snapshot.stage_index}.csv"
        if not path.is_file():
            continue
        table, _ = read_csv(path)
        texts.append((snapshot.stage_index, snapshot.stage_name, table))
    return tuple(texts)


def attribute(
    diffs: Sequence[DiffRecord],
    run: RunStages | None = None,
    *,
    stages: Sequence[tuple[int, str, Any]] | None = None,
    key: str | None = None,
    strategy: str = "key",
) -> list[Attribution]:
    """对每条差异跑规则并定环节。

    参数二选一：
    - `run`：一次真实 run（有快照序列，可算 `first_seen_at` 与 `resolved_stage`）；
    - `stages`：`(stage_index, stage_name, CsvTable)` 序列（测试与离线场景用）。

    两者都不给 → 只跑规则，`first_seen_at` / `resolved_stage` 全为 `None`，
    `candidates` 照常写出（"这条规则可能出现在哪些阶段"**不依赖**本次 run）。

    `key` / `strategy` **必须与产出这批差异时用的那套一致**：`row_key` 是在定位行时
    唯一的线索（主键值 / `#<index>` / 行指纹），拿错策略去定位会找不到行，
    于是 `first_seen_at` 退化成 `unknown`——那不是在说"没有快照序列"，是在说"找错了"。
    两者混起来会让归因静默降级，所以这里显式收参数而不是猜。
    """
    sequence = tuple(stages) if stages is not None else (stage_texts(run) if run is not None else ())
    catalogue = rules_by_id()
    attributions: list[Attribution] = []
    for record in diffs:
        attributions.append(_attribute_one(record, catalogue, sequence, key, strategy))
    return attributions


def _attribute_one(
    record: DiffRecord,
    catalogue: Sequence[dict],
    sequence: Sequence[tuple[int, str, Any]],
    key: str | None,
    strategy: str,
) -> Attribution:
    meta = {"orig_missing": record.orig_missing, "got_missing": record.got_missing}
    hits = [
        rule
        for rule in catalogue
        if predicate_for(rule["predicate"])(record.orig_text, record.got_text, record.declared_type, meta)
    ]
    if not hits:
        return Attribution(diff=record, rule=UNCLASSIFIED, stage_meta=meta)

    first, *rest = hits
    candidates = tuple(first["possible_stages"])
    also_matched = tuple(rule["name"] for rule in rest)

    if not sequence:
        # 没有阶段序列就只报"规则 + 候选"，不编造环节（D1 的离线形态）
        return Attribution(
            diff=record,
            rule=first["name"],
            candidates=candidates,
            also_matched=also_matched,
            stage_meta=meta,
        )

    first_seen_at, observed_stage = _first_seen(record, sequence, key, strategy)
    if observed_stage is None:
        # 该单元格在整条序列里都没变成 got_text（例如只比了两份孤立文件）→ 不编造环节
        resolved = None
    elif observed_stage in candidates:
        resolved = observed_stage
    else:
        # 观察到变化的阶段名不在候选里：按实际运行顺序取候选中最早出现的那个；
        # 候选与本次 run 的阶段名无交集 → 降级 unclassified（宁可 unclassified，不伪造归因）
        resolved = next((name for _, name, _ in sequence if name in candidates), None)
        if resolved is None:
            return Attribution(
                diff=record,
                rule=UNCLASSIFIED,
                first_seen_at=first_seen_at,
                first_seen_stage=observed_stage,
                candidates=candidates,
                resolved_stage=None,
                also_matched=also_matched,
                stage_meta=meta,
            )

    return Attribution(
        diff=record,
        rule=first["name"],
        first_seen_at=first_seen_at,
        first_seen_stage=observed_stage,
        candidates=candidates,
        resolved_stage=resolved,
        also_matched=also_matched,
        stage_meta=meta,
    )


def _first_seen(
    record: DiffRecord,
    sequence: Sequence[tuple[int, str, Any]],
    key: str | None,
    strategy: str,
) -> tuple[int | None, str | None]:
    """在快照序列里找"这个单元格第一次变成 `got_text`"的那一步。

    返回 `(stage_index, stage_name)`；`stage_index` 取**产出该值的那一步**（跳到新值的那一步），
    这正是给用户看的"它在哪一步变的"。

    `stage-0`（输入副本）只作为基线：它没有"变"，只是起点。所以从序列第 1 项起比。
    找不到返回 `(None, None)` —— 例如把两份孤立 CSV 直接交给 `diff` 时没有序列可筛。
    """
    if not sequence:
        return None, None
    baseline = sequence[0][2]
    position = _find_row(baseline, record.row_key, record.col, key, strategy)
    previous_text = baseline.cell(*position) if position is not None else record.orig_text

    for index, name, table in sequence[1:]:
        position = _find_row(table, record.row_key, record.col, key, strategy)
        if position is None:
            continue
        current = table.cell(*position)
        if current == record.got_text and previous_text != record.got_text:
            return index, name
        previous_text = current
    return None, None


def _find_row(
    table,
    row_key: str,
    col: str,
    key: str | None,
    strategy: str,
) -> tuple[int, int] | None:
    """在快照里按**产出这批差异时的同一套策略**定位那一行。

    - `key` 策略：拿主键列比 `row_key`。主键列名来自调用方——不从 `row_key` 反推
      （一个主键值可能恰好等于别的列里的某个值，反推就是猜）。
    - `position` 策略：`#<index>`。
    - `lcs` 策略：行指纹（`~` 前缀表示"只在往返后出现"，同样按指纹找）。

    找不到就返回 `None`：这条差异在本阶段没有对应行（例如行是后来才出现的），
    调用方据此写 `unknown`，而不是编一个阶段。
    """
    from tripwire.diff.align import row_fingerprint

    if col not in table.header:
        return None
    col_index = table.column_index(col)

    if strategy == "position":
        if row_key.startswith("#") and row_key[1:].isdigit():
            index = int(row_key[1:])
            return (index, col_index) if index < table.row_count else None
        return None

    if strategy == "lcs":
        target = row_key[1:] if row_key.startswith("~") else row_key
        for index, row in enumerate(table.rows):
            if row_fingerprint(row) == target:
                return index, col_index
        return None

    # key 策略
    if not key or key not in table.header:
        return None
    key_index = table.column_index(key)
    for index in range(table.row_count):
        if table.cell(index, key_index) == row_key:
            return index, col_index
    return None


def explain(attribution: Attribution) -> str:
    """`--explain` 的日志行。**格式写死**（`plan/03` M3，逐字对齐）：

    `rule=<name>, first_seen_at=stage 2 (excel_com_csv), candidates=[...] -> resolved to excel_com_csv`

    括号里是**实际**首次观察到变化的阶段；`resolved to` 后面是规则候选里选中的那个。
    两者不同不是 bug，恰恰是最有信息量的情形（"在 A 步变的，但规则说只可能是 B"）。
    """
    if attribution.first_seen_at is not None:
        stage_part = f"stage {attribution.first_seen_at} ({attribution.first_seen_stage or 'unknown'})"
    else:
        stage_part = "unknown"
    candidates = ", ".join(attribution.candidates)
    resolved = attribution.resolved_stage or UNCLASSIFIED
    line = (
        f"rule={attribution.rule}, first_seen_at={stage_part}, "
        f"candidates=[{candidates}] -> resolved to {resolved}"
    )
    if attribution.also_matched:
        line += f"  (also_matched=[{', '.join(attribution.also_matched)}])"
    return line


__all__ = [
    "FINGERPRINT_LENGTH",
    "UNCLASSIFIED",
    "Attribution",
    "attribute",
    "explain",
    "make_fingerprint",
    "stage_texts",
]
