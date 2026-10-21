"""真值夹具生成器（M4）：`generate(seed, rows, out_dir) -> FixtureResult`。

产出三件：`orig.csv`（UTF-8 无 BOM / LF / 带表头）、`expected.json`（**只存输入与期望**）、
`manifest.json`（生成器版本 + 参数 + 文件 sha256）。

## 四条硬纪律

1. **K8 确定性**：不用 stdlib `random`、不读时钟、不依赖 `set` 迭代序。随机性只来自本文件内的
   `SplitMix64`（自研 64 位 RNG，纯整数运算，跨版本/跨平台序列一致）。
2. **真值不可与引擎同源**：本模块**不 import 任何阶段实现、不 import pandas**。
   `p_after` 由 `_after()` 按 `data/README` 的**文档化行为**（F1 15 位 / F5 `%.16g` /
   F4 无 -0 / F8 NUMERIC 亲和）从 `orig` 文本自行推导。AST 守门见 `tests/test_fixture.py`。
3. **`expected.json` 只存输入与期望**：出现 `observed_*` / `actual_*` 字段即测试红——把"观测"
   冻结进真值，基准就退化成"比对两份预先算好的答案"，引擎全坏也全绿。
4. **部分运行不写全集清单**：带 `pools=` 的局部生成**不写** `manifest.json`（`plan/04` §五.5）。
   否则一次调试用的局部生成会把入仓的全集清单静默改小。

## 三组样本池

| 池 | 行数（seed 42 / rows 200） | 期望 |
|---|---|---|
| `canary-numeric` | 60 | 命中数值族规则 |
| `canary-semantic` | 80 | 命中空值 / 文本 / 时间族规则 |
| `control-lossless` | 60 | **0 条差异**（precision 硬约束，D4） |

各池的行数比例是**常量**（`POOL_SHARE`），`--rows` 按比例缩放；测试断言 200 行时恰为 60/80/60。

## 为什么样本值长这样（设计输入不是猜的）

每个样本形态都先在四条真实通道上实测过（M4 探针，见 `docs/fixture-pools.md` §五），
只保留"变换可独立推导且能命中命名规则"的形态。被排除的形态有三类，各有明确理由：

- **无人认识的形态**（15 位整数被 Excel 显示成 `1.23457E+14`、`1E5` 变定点、`+42` 丢号）：
  它们会稳定产出 `unclassified`，进了样本池就等于让门禁一开跑就失败。这些形态在
  `docs/rules.md` 与 `plan/HANDOFF-M3` 里登记为**已知道的规则缺口**，不塞进验收样本冒充覆盖。
- **会让某条通道直接失败的形态**：短行（缺格）会让 `json_sqlite_csv` 的批量插入失败；
  `1-10` 这类会被 Excel 当日期、并按系统码页写出非 UTF-8 字节。验收夹具必须四条通道都跑得通。
- **会掩盖别的规则正例的形态**：把 `00123-4567` 放进 `zip` 列会让 pandas 把整列推断成
  `object`，于是同列的 `02114` 不再被剥前导零——一个不产出任何差异的样本，代价是掐掉另一条
  规则的正例。它改放到 `text_unicode` 列。

`uncovered_rules` 把这些事实变成可复算的结论：某条规则在本 seed 的样本里没有正例，就**点名**，
不假装覆盖。
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from tripwire import __version__, serialization

#: 夹具列（顺序即 `orig.csv` 的列序，`plan/04` §二 固定）
COLUMNS: tuple[str, ...] = (
    "id",
    "num_big",
    "zip",
    "decimal",
    "exponent",
    "date",
    "text_unicode",
    "nullable",
)

#: 主键列名（`id`：唯一、无前导零，纯文本标签）
KEY_COLUMN = "id"

#: 三组样本池的名字（顺序即 `expected.json` 里 `pools` 的键序）
POOL_NUMERIC = "canary-numeric"
POOL_SEMANTIC = "canary-semantic"
POOL_CONTROL = "control-lossless"
POOLS: tuple[str, ...] = (POOL_NUMERIC, POOL_SEMANTIC, POOL_CONTROL)

#: 池 -> id 前缀（`plan/04` §二：三组混在同一张表，用 id 前缀区分）
POOL_PREFIX: Mapping[str, str] = {
    POOL_NUMERIC: "num-",
    POOL_SEMANTIC: "sem-",
    POOL_CONTROL: "ctl-",
}

#: 池 -> 权重（200 行时 = 60 / 80 / 60）
POOL_SHARE: Mapping[str, int] = {POOL_NUMERIC: 60, POOL_SEMANTIC: 80, POOL_CONTROL: 60}

#: 缺省规模（`plan/04` §一：「`--seed 42 --rows 200`」是仓库留档规模）
DEFAULT_SEED = 42
DEFAULT_ROWS = 200

#: 落盘文件名
ORIG_NAME = "orig.csv"
EXPECTED_NAME = "expected.json"
MANIFEST_NAME = "manifest.json"

#: 生成器自述（manifest 与 expected 都写；版本号唯一来源是包的 `__version__`）
GENERATOR_VERSION = __version__

#: 真值口径版本：改样本形态 / 改 `_after()` 的文档化推导，必须 +1 并整目录重生成
TRUTH_SCHEMA_VERSION = 1


# ── 确定性 RNG（K8）───────────────────────────────────────────────────────

_MASK64 = (1 << 64) - 1
_GOLDEN_GAMMA = 0x9E3779B97F4A7C15
_MIX_MUL_1 = 0xBF58476D1CE4E5B9
_MIX_MUL_2 = 0x94D049BB133111EB


class SplitMix64:
    """自研 splitmix64。**唯一**随机来源：不读时钟、不用 `random`、不依赖 `set` 迭代序。

    为什么不直接用 `random.Random(seed)`：stdlib 只保证算法对**当前版本**稳定，不承诺跨版本
    序列一致；真值夹具要的是"三年后同一 seed 还是同一批字节"。
    """

    __slots__ = ("_state",)

    def __init__(self, seed: int) -> None:
        self._state = seed & _MASK64

    def next_u64(self) -> int:
        self._state = (self._state + _GOLDEN_GAMMA) & _MASK64
        value = self._state
        value = ((value ^ (value >> 30)) * _MIX_MUL_1) & _MASK64
        value = ((value ^ (value >> 27)) * _MIX_MUL_2) & _MASK64
        return value ^ (value >> 31)

    def below(self, bound: int) -> int:
        """`[0, bound)` 上的均匀整数。**拒绝采样**而非取模：取模会让下界附近概率偏高。

        拒绝循环的次数由 RNG 序列本身决定，所以仍然是确定性的（同 seed 同结果）。
        """
        if bound <= 0:
            raise ValueError(f"bound 必须是正整数（收到 {bound}）")
        limit = (1 << 64) - ((1 << 64) % bound)
        while True:
            value = self.next_u64()
            if value < limit:
                return value % bound

    def shuffle(self, items: list) -> None:
        """Fisher–Yates（原地）。方向与交换次数固定，保证同 seed 同结果。"""
        for index in range(len(items) - 1, 0, -1):
            swap = self.below(index + 1)
            items[index], items[swap] = items[swap], items[index]


# ── 文档化行为 -> 期望文本（真值的"独立实现"侧）─────────────────────────

#: Excel 录入路径的有效数字上限（`data/README` F1）
_EXCEL_DIGITS = 15
#: Excel General 的阈值：整数部分超过这个位数改用科学计数（实测：≤11 位不改，≥12 位变 6 位有效数字）
# （注意：这和“有效数字 15 位”是两回事——这里是"多少位会触发格式切换"的门槛）
_EXCEL_SCI_INT_DIGITS = 11
#: Excel General 对极小值的 threshold：|v| < 1e-4 时用两位小数的科学计数（`1.00E-07`）
# 实测：`1e-7` -> `1.00E-07`；`1e-4` 刚好不触发（写成 `0.0001`）
_EXCEL_SMALL = Decimal("1e-4")


def round_significant(value: Decimal, digits: int) -> Decimal:
    """四舍五入到 `digits` 位有效数字（`Decimal` 精确运算，不经 float）。

    刻意**不复用** `tripwire.rules.predicates.round_significant`：那份是被测引擎的一部分，
    真值与被测实现共用同一段舍入代码，“规则 5 算错了”和“真值算错了”就会一起错、一起绿。
    """
    if value == 0:
        return value
    exponent = value.copy_abs().adjusted() - (digits - 1)
    return value.quantize(Decimal(1).scaleb(exponent), rounding=ROUND_HALF_UP)


def _excel_general(value: Decimal, raw_literal: str) -> str:
    """Excel 把数值写成 CSV 时用的 General 格式（F1 + F13 + 实测校准）。

    **关键发现**（实测钉死）：输出形态取决于**原文字面量**是否写了指数符号，而不是只看数值大小。

    - 纯数字字串（无 `e/E`）：
      - 整数部分 ≤ `_EXCEL_SCI_INT_DIGITS`（11 位）→ 不变
      - 否则 → `%.6g`（6 位有效数字的科学计数）
    - 指数形式（有 `e/E`）：
      - `|v| < _EXCEL_SMALL`（1e-4）→ `%.2E`（两位小数）(`1.00E-07`)
      - 否则 → `%.2E`（两位小数）(`3.50E+21`, `1.23E-07`)

    这**不是**"跑一遍 Excel 抄下来"：判据来自实测，输入是 `(value, raw_literal)` 两个文本参数，
    全程 `Decimal` 运算。
    """
    if value == 0:
        return "0"

    # 判断原始字面量是否含指数符号
    has_exp = "e" in raw_literal.lower()

    if has_exp:
        # 指数形式一律写 `.2E`（两位小数），但要按 6 位有效数字先舍入一下（实测行为）
        rounded = round_significant(value, 6)
        result = f"{float(rounded):.2E}"
        return result

    # 纯数字字串
    magnitude = abs(value)
    integer_digits = int(magnitude.adjusted()) + 1 if magnitude != 0 else 0
    if integer_digits > _EXCEL_SCI_INT_DIGITS:
        # ≥12 位的整数（或小数）→ 6 位有效数字
        return format(round_significant(value, 6).normalize(), "E")
    # ≤11 位的整数 → 原样返回（格式化时会去掉尾随零）
    return format(value.normalize(), "f")


def _excel_text(orig: str, digits: int = _EXCEL_DIGITS) -> str:
    """`orig` 走 Excel 录入路径后的文本：先按 15 位截断，再按 General 渲染（F1 + F13）。"""
    return _excel_general(round_significant(Decimal(orig), digits), orig)


def _openpyxl_text_from_int(orig: str) -> str:
    """openpyxl 把整数写进 xlsx 再读回的文本：按 double 读回，再走 `%.16g`（F5）。

    `1500000000000000000`（19 位，仍在 int64 内，但 > 2^53）→ 读回成 `1.5e+18`。
    """
    return _openpyxl_text(float(orig))


def _openpyxl_text(value: float) -> str:
    """openpyxl 写数字用 `%.16g`（`data/README` F5，源码 `openpyxl/compat/strings.py`）。"""
    return format(value, ".16g")


def _trimmed_decimal(orig: str) -> str:
    """去掉小数尾随零（`19.90` -> `19.9`），纯 `Decimal` 文本运算。"""
    return format(Decimal(orig).normalize(), "f")


def _date_text(orig: str) -> str:
    """ISO 日期 -> Excel 的 `YYYY/M/D`（月日不补零，F13 实测）。"""
    year, month, day = orig.split("-")
    return f"{int(year)}/{int(month)}/{int(day)}"


def _after(rule: str, orig: str) -> dict[str, str]:
    """规则 -> 各阶段**期望文本**。缺键 = 该阶段不产生差异。

    参数只有 `(rule, orig)`：期望必须是输入的纯函数。函数体内不出现任何阶段调用、
    不 import 任何阶段实现。

    **为什么只有这几个阶段键**：每个形态的"变了的通道集合"都必须 ⊆ 该规则的
    `possible_stages`（见 `Form` 的说明）。所以这里的键是**按规则的候选集**写的，
    不是"把四条通道都列上"。例如 `excel_15_digit_truncation` 的候选只有 `excel_com_csv`，
    这条就只写一个键——若某天 Excel 之外的通道也开始截断，门禁会以 `unexpected` 抓出来，
    而不是靠这里的键"提前认为它不会变"。
    """
    match rule:
        case "leading_zero_lost":
            # 数值化通道（pandas 的 int 推断 / SQLite 的 NUMERIC 亲和 / Excel）剥掉前导零；
            # openpyxl 的写入侧按 `cell_kind` 把它当文本，所以候选含 openpyxl 但不写键。
            value = str(int(orig))
            return {"pandas_csv": value, "json_sqlite_csv": value, "excel_com_csv": value}
        case "scientific_notation_coercion":
            # 16 位那档只有 Excel 变；19 位那档（仍在 int64 内）Excel 与 openpyxl 都变
            # （openpyxl 把整数写进 xlsx 后按 double 读回）。SQLite 只在这两档都不动它。
            after = {"excel_com_csv": _excel_text(orig)}
            if len(orig) >= 17:
                after["openpyxl_csv"] = _openpyxl_text_from_int(orig)
            return after
        case "int53_overflow":
            return {"excel_com_csv": _excel_text(orig)}
        case "excel_15_digit_truncation":
            return {"excel_com_csv": _excel_text(orig)}
        case "negative_zero_sign_lost":
            # Excel 没有 -0（F4）；SQLite 的 NUMERIC 亲和把 `-0` 存成整数 0；pandas 的 int 推断同理
            return {"pandas_csv": "0", "json_sqlite_csv": "0", "excel_com_csv": "0"}
        case "decimal_trailing_zero_dropped":
            value = _trimmed_decimal(orig)
            return {"pandas_csv": value, "json_sqlite_csv": value, "excel_com_csv": value}
        case "exponent_form_normalized":
            return {"excel_com_csv": _excel_text(orig)}
        case "empty_vs_null_vs_missing":
            # pandas 默认把 null 字面量当 NaN，回写成空串（F6）
            return {"pandas_csv": ""}
        case "date_retyped_to_text":
            return {"excel_com_csv": _date_text(orig)}
        case "serial_60_phantom_date":
            return {"excel_com_csv": _date_text(orig)}
        case _:  # pragma: no cover - 形态表里只会出现上面这些
            raise KeyError(f"没有为规则 {rule!r} 定义期望推导")


# ── 样本形态表 ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Form:
    """一种样本形态：放哪一列、候选字面量、期望规则、以及本池内占多少行。

    **合法形态的判据（M4 实测校准，见 `docs/fixture-pools.md` §五）**：
    该形态在四条通道上"真的变了"的通道集合，必须 ⊆ 该规则的 `possible_stages`。
    越界就会在越界通道上被 D1 降级成 `unclassified`，门禁必失败——
    那不是规则写错，是**样本不该长这样**（`rules.json` 已冻结，M4 不得改 `possible_stages`）。
    """

    name: str
    pool: str
    column: str
    rule: str
    variants: tuple[str, ...]
    rows: int

    def variant(self, rng: SplitMix64) -> str:
        return self.variants[rng.below(len(self.variants))]


#: 数值池：7 种形态，合计 6+6+9+12+9+9+9 = 60 行（`rows=200` 时）
NUMERIC_FORMS: tuple[Form, ...] = (
    # 16 位整数（< 2^53，double 可精确表示）-> 只有 Excel 按 15 位截断（规则 5）
    Form("e15", POOL_NUMERIC, "num_big", "excel_15_digit_truncation",
         ("1234567890123456", "4321098765432109", "7000000000000003",
          "1234567890123457", "5555555555555555"), 6),
    # 略超 2^53、但位数 ≤ 16 -> 只有 Excel 变（规则 4 抢首条于规则 5）
    Form("int53", POOL_NUMERIC, "num_big", "int53_overflow",
         ("9007199254740992", "9007199254740994", "9007199254740996", "9007199254740998"), 6),
    # 尾随零的大整数 -> 只有 Excel + openpyxl 渲染成科学计数（规则 2 的候选正是这两家）。
    # 16 位那档：openpyxl 的 xlsx 往返在 2^53 以内是精确的 → 只有 Excel 变。
    # 19 位那档（1.5e18，仍在 int64 内）：openpyxl 写进 xlsx 后按 double 读回 → 也变。
    # 取 19 位而不是 20 位是为了让它留在 int64 内，SQLite 的 NUMERIC 亲和才不改它
    # （规则 2 的候选不含 sqlite）。
    Form("sci", POOL_NUMERIC, "num_big", "scientific_notation_coercion",
         ("1500000000000000", "2500000000000000", "4500000000000000", "7500000000000000",
          "1500000000000000000", "2500000000000000000"), 9),
    # 定点小数尾随零 + **一个尾随空格**：空格让 openpyxl 的 `cell_kind` 判成文本
    # （否则 openpyxl 也会改它，而它的 `possible_stages` 不含 openpyxl）
    Form("trail0", POOL_NUMERIC, "decimal", "decimal_trailing_zero_dropped",
         ("19.90 ", "120.70 ", "3.50 ", "0.50 ", "7.20 ", "45.10 "), 12),
    # 负零 + 尾随空格：同上理由（`-0.0` 会被 openpyxl 改成 `0`，越界）。
    # 放在 `zip` 列而非 `decimal` 列：`decimal` 列是 float64（含 `19.90 `），
    # pandas 会把 `-0 ` 读成 `-0.0` 再写回 `-0.0`——那不是规则的任何形态（`zip` 列是整数形）。
    Form("negzero", POOL_NUMERIC, "zip", "negative_zero_sign_lost", ("-0 ",), 9),
    # 指数写法被规范化而数值相等。取值必须**让 pandas/SQLite 走无损路径**：
    # 2~3 位有效数字 + 指数 ≥ 21 时，两侧的 repr/.15g 原样保留，只有 Excel 补零改大小写。
    # `1e+21`（一位有效数字）不行：SQLite 的 `.15g` 会补成 `1.0e+21` → 越界。
    Form("exponent", POOL_NUMERIC, "exponent", "exponent_form_normalized",
         ("3.5e+21", "2.5e+21", "7.5e+21", "1.5e+22", "4.5e+25", "1.25e+30"), 9),
)

#: 本 seed 下**结构性**没有正例的规则 -> 为什么（写进 `expected.json` 的 `uncovered_rules`
#: 是机器可读的点名；这里是它的理由，供 `docs/rules.md` 与报告对读）。
#:
#: 这些不是"忘了造样本"：每一条都说明了**为什么造不出来**，且给出补齐的路径。
#: 任何一条要在 M4 之后生效，都得改 `rules.json` 的 `possible_stages`（M4 无授权）
#: 或加新通道（二期）——**不得为了让它们变绿去放宽谓词**（D4）。
KNOWN_UNCOVERABLE: Mapping[str, str] = {
    "float_precision_truncated": "候选不含 excel_com_csv，而 Excel 真的会改这类定点小数 -> 越界",
    "null_token_collision": "只要它命中，id 更小的 empty_vs_null_vs_missing 必先命中 -> 被遮蔽",
    "whitespace_collapsed": "候选不含 json_sqlite_csv / excel_com_csv，而这两条都会裁空白 -> 越界",
    "unicode_normalization_changed": "四条 CSV 通道都不做 Unicode 归一",
    "bom_prepended": "四条通道都不在原值前加 BOM",
    "encoding_mojibake": "四条通道都按 UTF-8 原样读写，不产生乱码",
    "date_system_shift_1904": "需要 1904 纪元切换的 Excel 实例（靠单测构造，M3 已做）",
    "number_format_dropped": "四条 CSV 通道都不产出单元格级 number_format",
}


#: 语义池：5 种形态，合计 20+20+16+16+8 = 80 行（`rows=200` 时）
SEMANTIC_FORMS: tuple[Form, ...] = (
    # 前导零邮编 -> 数值化通道剥零
    Form("leading0", POOL_SEMANTIC, "zip", "leading_zero_lost",
         ("02114", "00123", "00777", "01111", "08080"), 20),
    # null 字面量 -> pandas 塌缩成缺失（F6）
    Form("null_token", POOL_SEMANTIC, "nullable", "empty_vs_null_vs_missing",
         ("NULL", "n/a", "NaN", "N/A", "NA", "None"), 20),
    # ISO 日期 -> Excel 改写成 YYYY/M/D
    Form("date_iso", POOL_SEMANTIC, "date", "date_retyped_to_text",
         ("2024-01-02", "1999-12-31", "2000-01-01", "1987-07-04"), 16),
    # 不存在的 1900-02-29 -> Excel 的 1900 闰年 bug（F2）
    Form("phantom", POOL_SEMANTIC, "date", "serial_60_phantom_date", ("1900-02-29",), 16),
    # NFC 合成字符：四条通道都不动它 —— **负样本**（不产差异，但一旦被改就拉低 precision）
    Form("nfc", POOL_SEMANTIC, "text_unicode", "", ("caf\u00e9",), 8),
)

#: 控制池：纯 ASCII 字母数字，无前导零 / 无小数尾零 / 无日期形态 / 无空白异常
CONTROL_SLOTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("num_big", ("12345", "67890", "24680", "31415", "54321", "13579")),
    ("zip", ("94016", "10001", "60601", "33101", "80202", "98101")),
    ("decimal", ("12.5", "3.25", "0.75", "48.5", "7.25", "96.75")),
    ("exponent", ("2.5", "4.5", "0.5", "6.25", "8.75", "1.5")),
    ("date", ("notadate", "plaintext", "worddate", "nodateat", "dateless", "calendr")),
    ("text_unicode", ("lorem", "ipsum", "dolor", "amet", "consect", "adipis")),
    ("nullable", ("present", "filled", "stated", "given", "supplied", "noted")),
)

#: 非金丝雀列的**填充值**：每行都是稠密的（`plan/04` §二 的 8 列每行都有值）。
#:
#: 为什么必须稠密：pandas 的 dtype 推断是**按列**的。列里只要出现空格（NaN），整列就落成
#: `float64`，于是控制行的 `94016` 被写成 `94016.0`——控制组当场报出一条假差异，
#: precision 一开跑就失败。稠密列里 `zip` 全是整数形 → `int64` → 控制值原样回来。
#:
#: 这些填充值同时决定各列的 dtype，所以它们**不能随便换**：
#: - `zip` 填充必须是整数形（否则列变 `object`，`02114` 的前导零就不会被剥，规则 1 丢正例）；
#: - `num_big` 列里因为混着 20 位整数，恒为 `object`，填充值原样保留（控制组想要的就是这个）。
FILLER: Mapping[str, str] = {
    "num_big": "12345",
    "zip": "94016",
    "decimal": "12.5",
    "exponent": "2.5",
    "date": "notadate",
    "text_unicode": "lorem",
    "nullable": "present",
}


# ── 生成 ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ExpectedCell:
    """`expected.json` 的一条：一个样本单元的输入与期望。"""

    row_key: str
    col: str
    pool: str
    orig: str
    rule: str
    p_after: Mapping[str, str]

    def to_json(self) -> dict:
        return {
            "cell": [self.row_key, self.col],
            "pool": self.pool,
            "orig": self.orig,
            "rule": self.rule,
            "p_after": dict(self.p_after),
        }


@dataclass(frozen=True)
class FixtureResult:
    """一次生成的结果。`out_dir` 里已落盘 `orig.csv`（+ 全集运行时 `expected.json` / `manifest.json`）。"""

    seed: int
    rows: int
    out_dir: Path
    pools: Mapping[str, int]
    cells: tuple[ExpectedCell, ...]
    uncovered_rules: tuple[str, ...]
    pools_included: tuple[str, ...]
    wrote_manifest: bool
    files: Mapping[str, str]

    @property
    def orig_path(self) -> Path:
        return self.out_dir / ORIG_NAME

    @property
    def expected_path(self) -> Path:
        return self.out_dir / EXPECTED_NAME

    @property
    def manifest_path(self) -> Path:
        return self.out_dir / MANIFEST_NAME


def pool_counts(rows: int) -> dict[str, int]:
    """把 `rows` 按 `POOL_SHARE` 比例分摊到三池（最大余数法，和恰为 `rows`）。

    为什么要"恰为 rows"：`expected.json` 声明 `{"seed": 42, "rows": 200, "pools": {...}}`，
    三者必须自洽，否则一处手滑就出现"声明 200 行、实际 199 行"的静默漂移。
    """
    if rows <= 0:
        raise ValueError(f"rows 必须是正整数（收到 {rows}）")
    total_share = sum(POOL_SHARE.values())
    exact = {pool: rows * share / total_share for pool, share in POOL_SHARE.items()}
    counts = {pool: int(exact[pool]) for pool in POOLS}
    remainder = rows - sum(counts.values())
    # 余数按小数部分降序分配；同小数时按 POOLS 顺序（确定性，不依赖 dict 序）
    order = sorted(POOLS, key=lambda pool: (-(exact[pool] - counts[pool]), POOLS.index(pool)))
    for pool in order[:remainder]:
        counts[pool] += 1
    return counts


def _form_rows(forms: Sequence[Form], total: int) -> list[tuple[Form, int]]:
    """把某池的 `total` 行按形态的固定份额分摊（最大余数法，确定性）。"""
    share_total = sum(form.rows for form in forms)
    exact = {form.name: total * form.rows / share_total for form in forms}
    counts = {form.name: int(exact[form.name]) for form in forms}
    remainder = total - sum(counts.values())
    order = sorted(
        (form.name for form in forms),
        key=lambda name: (-(exact[name] - counts[name]), [form.name for form in forms].index(name)),
    )
    for name in order[:remainder]:
        counts[name] += 1
    return [(form, counts[form.name]) for form in forms]


def _csv_text(header: Sequence[str], rows: Iterable[Sequence[str]]) -> str:
    """RFC4180 文本：LF 行尾、最小引号、UTF-8 由落盘侧保证（`plan/04` §五.2）。"""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(list(header))
    for row in rows:
        writer.writerow(list(row))
    return buffer.getvalue()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate(
    seed: int = DEFAULT_SEED,
    rows: int = DEFAULT_ROWS,
    out_dir: str | Path = "fixtures/out",
    *,
    pools: Sequence[str] | None = None,
) -> FixtureResult:
    """生成夹具。`pools` 给定时为**部分运行**：只生成这些池的行，且**不写 manifest.json**。

    部分运行**也不覆盖 `expected.json`**：入仓清单只该由全集生成写出。局部产物落在
    文件名带池名的旁路文件里，这样"调试用的局部生成"永远不会改坏交付面。
    """
    if pools is not None:
        unknown = [pool for pool in pools if pool not in POOLS]
        if unknown:
            raise ValueError(f"未知样本池 {unknown}（可用: {', '.join(POOLS)}）")
        included = tuple(pool for pool in POOLS if pool in set(pools))
    else:
        included = POOLS

    counts = pool_counts(rows)
    rng = SplitMix64(seed)

    # 1) 排"槽位"：每槽 = (池, 形态或 None)
    slots: list[tuple[str, Form | None]] = []
    for pool in included:
        forms = NUMERIC_FORMS if pool == POOL_NUMERIC else (SEMANTIC_FORMS if pool == POOL_SEMANTIC else ())
        if not forms:
            slots.extend((pool, None) for _ in range(counts[pool]))
            continue
        for form, count in _form_rows(forms, counts[pool]):
            slots.extend((pool, form) for _ in range(count))

    # 2) 打乱：三组混在同一张表（`plan/04` §二）。顺序由 seed 决定，逐字节可复现。
    rng.shuffle(slots)

    # 3) 逐槽出行。id 按池内出现顺序编号——无前导零（`plan/04` §二）。
    used: dict[str, int] = {pool: 0 for pool in POOLS}
    header = list(COLUMNS)
    table: list[list[str]] = []
    cells: list[ExpectedCell] = []

    for pool, form in slots:
        used[pool] += 1
        row_key = f"{POOL_PREFIX[pool]}{used[pool]}"
        # 每行先铺满填充值：8 列每行都有值（稠密表），否则 pandas 按列推断出 float64，
        # 控制行的整数会被写成 `94016.0` —— 那是一条假差异（见 FILLER 的说明）。
        row = dict(FILLER)
        row[KEY_COLUMN] = row_key
        if pool == POOL_CONTROL:
            # 控制行逐行换值（轮转取），但每个值都落在 CONTROL_SLOTS 里 —— 即"无前导零、
            # 无小数尾零、无日期形态"的那一小撮。轮转索引 = 该池已出行数，确定性。
            slot = used[pool] - 1
            for column, values in CONTROL_SLOTS:
                row[column] = values[slot % len(values)]

        if form is not None:
            literal = form.variant(rng)
            row[form.column] = literal
            if form.rule:
                p_after = _after(form.rule, literal)
                # 期望文本与原文相同 = 这个阶段没有变化，不该出现在 p_after 里
                p_after = {stage: text for stage, text in p_after.items() if text != literal}
                if p_after:
                    cells.append(
                        ExpectedCell(
                            row_key=row_key,
                            col=form.column,
                            pool=pool,
                            orig=literal,
                            rule=form.rule,
                            p_after=p_after,
                        )
                    )

        table.append([row[column] for column in header])

    # 4) 单元格按 (row_key, col) 排序：与差异引擎的 K5 同序，便于人工对读
    cells.sort(key=lambda cell: (cell.row_key, cell.col))

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    orig_path = out_path / ORIG_NAME
    serialization.write_text_raw(orig_path, _csv_text(header, table))

    files = {ORIG_NAME: _sha256_file(orig_path)}
    covered = {cell.rule for cell in cells}
    uncovered = tuple(rule for rule in _all_rule_names() if rule not in covered)
    included_counts = {pool: counts[pool] for pool in POOLS if pool in included}

    if pools is None:
        payload = {
            "seed": seed,
            "rows": rows,
            "generator_version": GENERATOR_VERSION,
            "truth_schema_version": TRUTH_SCHEMA_VERSION,
            "columns": list(COLUMNS),
            "key": KEY_COLUMN,
            "pools": dict(included_counts),
            "id_prefixes": dict(POOL_PREFIX),
            "cells": [cell.to_json() for cell in cells],
            "uncovered_rules": list(uncovered),
        }
        expected_path = serialization.write_json(out_path / EXPECTED_NAME, payload)
        files[EXPECTED_NAME] = _sha256_file(expected_path)
        serialization.write_json(
            out_path / MANIFEST_NAME,
            {
                "seed": seed,
                "rows": rows,
                "generator_version": GENERATOR_VERSION,
                "truth_schema_version": TRUTH_SCHEMA_VERSION,
                "pools": dict(included_counts),
                "files": dict(files),
            },
        )
    # 部分运行：不写 expected.json / manifest.json（`plan/04` §五.5）
    expected_path = out_path / EXPECTED_NAME if pools is None else None

    return FixtureResult(
        seed=seed,
        rows=rows,
        out_dir=out_path,
        pools=included_counts,
        cells=tuple(cells),
        uncovered_rules=uncovered,
        pools_included=included,
        wrote_manifest=pools is None,
        files=dict(files) if expected_path else {ORIG_NAME: files[ORIG_NAME]},
    )


def _all_rule_names() -> tuple[str, ...]:
    """18 条规则名（按 `id` 升序）。只读规则表，不碰任何阶段实现。"""
    from tripwire.rules.predicates import rules_by_id

    return tuple(rule["name"] for rule in rules_by_id())


__all__ = [
    "COLUMNS",
    "CONTROL_SLOTS",
    "DEFAULT_ROWS",
    "DEFAULT_SEED",
    "EXPECTED_NAME",
    "ExpectedCell",
    "FILLER",
    "FixtureResult",
    "Form",
    "GENERATOR_VERSION",
    "KEY_COLUMN",
    "KNOWN_UNCOVERABLE",
    "MANIFEST_NAME",
    "NUMERIC_FORMS",
    "ORIG_NAME",
    "POOLS",
    "POOL_CONTROL",
    "POOL_NUMERIC",
    "POOL_PREFIX",
    "POOL_SEMANTIC",
    "POOL_SHARE",
    "SEMANTIC_FORMS",
    "SplitMix64",
    "TRUTH_SCHEMA_VERSION",
    "generate",
    "pool_counts",
    "round_significant",
]
