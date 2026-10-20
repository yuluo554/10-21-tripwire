"""规则谓词：**纯函数**，签名 `(orig_text, got_text, declared_type, stage_meta) -> bool`（K6）。

禁令（K6）：谓词不得读网络、读时钟、读随机数、读文件系统——它们必须是输入的确定函数。
一切"看起来像类型/日期/数字"的判断都在本文件内自算，**不 import pandas**：
差异与归因必须在没装 pandas 的机器上也能跑（`plan/02` §三只允许**阶段**因缺依赖失败）。

`stage_meta` 是本层的证据面，键全部可选（缺键 = 该证据不可用 → 谓词返回 `False`，
落 `unclassified`，即 D1"宁可 unclassified，不伪造归因"）：

| 键 | 含义 | 谁填 |
|---|---|---|
| `orig_missing` / `got_missing` | 该格是否**不存在**（行短于表头） | M2 的 `DiffRecord` |
| `orig_number_format` / `got_number_format` | 单元格 `number_format` | 具备该信息的阶段（首期通道均不产出 → 谓词 18 恒 `False`） |

**数值一律经 `decimal.Decimal`**：用 `float` 比较 20 位整数会把"真的不等"读成"相等"，
那样谓词 4/5 就永远不命中，而归因会悄悄变成 `unclassified`。
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import lru_cache
from importlib import resources
from typing import Callable, Mapping

Predicate = Callable[[str, str, "str | None", "Mapping[str, object] | None"], bool]

# ── 文本形态 ──────────────────────────────────────────────────────────────

_INT_RE = re.compile(r"^[+-]?\d+$")
_DEC_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")
_EXP_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)[eE][+-]?\d+$")
_NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_NEG_ZERO_RE = re.compile(r"^-0(?:\.0+)?$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SLASH_DATE_RE = re.compile(r"^\d{4}/\d{1,2}/\d{1,2}$")
_OTHER_DATE_RE = re.compile(r"^\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}$")

#: 1900 与 1904 两个日期系统相差的天数（`data/README` F3，官方原文）
_1904_SHIFT_DAYS = 1462

#: Excel 录入路径的有效数字上限（`data/README` F1，官方原文 "Number precision = 15 digits"）
_EXCEL_SIGNIFICANT_DIGITS = 15

#: pandas / pandas-like 引擎当作缺失的字面量（`data/README` F6 的集合是本文件的超集，
#: 这里只列**跨引擎都算缺失**的那一小撮：判断"是不是 null token"不该依赖某个引擎的列表）
NULL_TOKENS = frozenset({"NULL", "N/A", "NA", "NAN", "NONE", "#N/A", "#NA", "NIL", "<NA>"})

#: 典型的"把 UTF-8 当 Latin-1 解"的残渣（`encoding_mojibake` 的检出信号，**只检出、不修复**）
_MOJIBAKE_MARKERS = ("\ufffd", "Ã", "Â", "â€", "ï»¿")


# ── 小工具（全部纯函数）────────────────────────────────────────────────────

def as_decimal(text: str) -> Decimal | None:
    """文本 -> `Decimal`；不是数字形态返回 `None`。

    不走 `float`：`float('12345678901234567890') == float('1.23457E+19')` 是 **True**，
    用它比较会把"真的丢了位"读成"相等"，谓词 4/5 就永远不命中。
    """
    stripped = text.strip()
    if not _NUMBER_RE.match(stripped):
        return None
    try:
        return Decimal(stripped)
    except InvalidOperation:
        return None


def significant_digits(text: str) -> int:
    """有效数字位数（去掉符号、小数点、前导零；指数部分不计）。"""
    mantissa = re.split(r"[eE]", text.strip(), maxsplit=1)[0].lstrip("+-")
    digits = mantissa.replace(".", "")
    stripped = digits.lstrip("0")
    return len(stripped) if stripped else (1 if digits else 0)


def round_significant(value: Decimal, digits: int) -> Decimal:
    """把 `value` 四舍五入到 `digits` 位有效数字（`Decimal` 精确运算，不经 float）。"""
    if value == 0:
        return value
    exponent = value.copy_abs().adjusted() - (digits - 1)
    return value.quantize(Decimal(1).scaleb(exponent), rounding=ROUND_HALF_UP)


def parse_date(text: str) -> _dt.date | None:
    """认三种文本日期：`YYYY-MM-DD` / `YYYY/M/D` / `DD/MM/YYYY` 之类的短形态。

    **`1900-02-29` 解析失败是刻意的**：那一天不存在（Excel 的 1900 闰年 bug 造的假日期）。
    用 `date(1900, 2, 29)` 会抛 `ValueError`，于是"幽灵日期"只能由谓词 17 按**文本**识别，
    不会被误当成一个合法日期参与天数差计算。
    """
    stripped = text.strip()
    if _ISO_DATE_RE.match(stripped):
        return _safe_date(*(int(part) for part in stripped.split("-")))
    if _SLASH_DATE_RE.match(stripped):
        year, month, day = stripped.split("/")
        return _safe_date(int(year), int(month), int(day))
    if _OTHER_DATE_RE.match(stripped):
        first, second, third = re.split(r"[/.\-]", stripped)
        for year, month, day in ((int(third), int(first), int(second)), (int(third), int(second), int(first))):
            parsed = _safe_date(year, month, day)
            if parsed is not None:
                return parsed
    return None


def _safe_date(year: int, month: int, day: int) -> _dt.date | None:
    try:
        return _dt.date(year, month, day)
    except ValueError:
        return None


def null_state(text: str, missing: bool = False) -> str | None:
    """空值三态：`missing` / `empty` / `null`；都不是则 `None`。"""
    if missing:
        return "missing"
    if text == "":
        return "empty"
    if text.strip().upper() in NULL_TOKENS:
        return "null"
    return None


def _meta(stage_meta: Mapping[str, object] | None, key: str) -> object:
    if not stage_meta:
        return None
    return stage_meta.get(key)


def _same_value(left: str, right: str) -> bool | None:
    """两侧数值是否相等；任一侧不是数字形态返回 `None`（"不知道"，不是"相等"）。"""
    a, b = as_decimal(left), as_decimal(right)
    if a is None or b is None:
        return None
    return a == b


# ── 数值族（8 条）──────────────────────────────────────────────────────────

def leading_zero_lost(orig: str, got: str, declared_type: str | None, stage_meta) -> bool:
    """原文有前导零、往返后数值相等但零没了。

    反例：`orig='0', got='0'` → 不命中（单个 `0` 不是"前导零"）。
    """
    body = orig.strip().lstrip("+-")
    if not body.isdigit() or len(body) < 2 or not body.startswith("0"):
        return False
    got_body = got.strip().lstrip("+-")
    if not got_body.isdigit():
        return False
    if len(got_body) > 1 and got_body.startswith("0"):
        return False  # 零还在，不是"丢失"
    return int(body) == int(got_body)


def scientific_notation_coercion(orig: str, got: str, declared_type: str | None, stage_meta) -> bool:
    """原文是纯数字串，往返后变成科学计数法且**数值等价**。

    反例：`orig='ABC123', got='1E5'` → 不命中（原文非纯数字串）。
    数值**不等**的情形不归这里——那是 `int53_overflow` / `excel_15_digit_truncation`。
    """
    if not orig.strip().isdigit():
        return False
    if not _EXP_RE.match(got.strip()):
        return False
    return _same_value(orig, got) is True


def float_precision_truncated(orig: str, got: str, declared_type: str | None, stage_meta) -> bool:
    """原文**定点小数**，往返后有效数字变少**且数值不严格相等**。

    反例：`orig='19.90', got='19.9'` → 不命中（数值相等，归 `decimal_trailing_zero_dropped`）。

    **必须带小数点**：纯整数不是"定点小数"。这一条不是措辞洁癖——`12345678901234567890`
    这种整数走 Excel 会被 15 位截断，若本谓词也认，它就会按 id 抢在
    `excel_15_digit_truncation` 之前命中；而本规则的 `possible_stages` 不含 `excel_com_csv`，
    于是一次真实的 Excel 截断随后会被"候选阶段无交集"降级成 `unclassified`——
    把一个已看清的形态写成"没规则认识它"（D1 的反面）。
    """
    stripped = orig.strip()
    if "." not in stripped or "e" in stripped.lower():
        return False
    if not _DEC_RE.match(stripped):
        return False
    equal = _same_value(orig, got)
    if equal is None or equal is True:
        return False
    return significant_digits(got) < significant_digits(orig)


def int53_overflow(orig: str, got: str, declared_type: str | None, stage_meta) -> bool:
    """原文整数绝对值 > 2^53−1，往返后**不相等**。

    反例：`orig='9007199254740991'`（=2^53−1）→ 不命中（边界内）。
    """
    stripped = orig.strip()
    if not _INT_RE.match(stripped):
        return False
    if abs(int(stripped)) <= 2**53 - 1:
        return False
    equal = _same_value(orig, got)
    return equal is False


def excel_15_digit_truncation(orig: str, got: str, declared_type: str | None, stage_meta) -> bool:
    """原文整数有效位 > 15，往返后落在 ≤15 位，且**恰好是原文按该位数四舍五入的结果**。

    为什么要求"恰好等于四舍五入结果"而不是"看起来变短了"：那才是 Excel 的可复现行为
    （`12345678901234567890` → `1.23457E+19`），也是唯一能把这个规则与"随便改了个数"
    区分开的判据。反例见 `rules.json`：openpyxl 跑出的同类截断不得归因到本规则。
    """
    stripped = orig.strip()
    if not _INT_RE.match(stripped):
        return False
    if significant_digits(stripped) <= _EXCEL_SIGNIFICANT_DIGITS:
        return False
    value = as_decimal(got)
    if value is None:
        return False
    digits = significant_digits(got)
    if digits >= _EXCEL_SIGNIFICANT_DIGITS:
        return False
    return round_significant(Decimal(stripped), digits) == value


def negative_zero_sign_lost(orig: str, got: str, declared_type: str | None, stage_meta) -> bool:
    """原文是负零（`-0` / `-0.0`…），往返后符号没了。

    反例：`orig='-0.5'` → 不命中（非零值）。
    """
    if not _NEG_ZERO_RE.match(orig.strip()):
        return False
    stripped = got.strip()
    if stripped.startswith("-"):
        return False
    value = as_decimal(stripped)
    return value is not None and value == 0


def decimal_trailing_zero_dropped(orig: str, got: str, declared_type: str | None, stage_meta) -> bool:
    """原文小数有尾随零，往返后数值相等但精度更短。

    反例：`orig='19.9', got='19.9'` → 不命中（无尾随零）。
    """
    stripped = orig.strip()
    if "." not in stripped:
        return False
    mantissa = re.split(r"[eE]", stripped, maxsplit=1)[0]
    fraction = mantissa.split(".", 1)[1]
    if not fraction.endswith("0"):
        return False
    if _same_value(orig, got) is not True:
        return False
    return len(got.strip()) < len(stripped)


def exponent_form_normalized(orig: str, got: str, declared_type: str | None, stage_meta) -> bool:
    """原文含指数，往返后指数写法变了（大小写 / 补零 / 加号）而数值相等。

    反例：`orig='1e-7', got='2e-7'` → 不命中（数值不等）。
    """
    if not _EXP_RE.match(orig.strip()) or not _EXP_RE.match(got.strip()):
        return False
    if orig.strip() == got.strip():
        return False
    return _same_value(orig, got) is True


# ── 空值族（2 条）──────────────────────────────────────────────────────────

def empty_vs_null_vs_missing(orig: str, got: str, declared_type: str | None, stage_meta) -> bool:
    """空串 / null 字面量 / 缺格 三者之一变成了另一种。

    反例：`orig='0', got=''` → 不命中（**原文不是空态**；"值被清空"是另一回事，落 unclassified）。
    """
    before = null_state(orig, bool(_meta(stage_meta, "orig_missing")))
    if before is None:
        return False
    after = null_state(got, bool(_meta(stage_meta, "got_missing")))
    return after != before


def null_token_collision(orig: str, got: str, declared_type: str | None, stage_meta) -> bool:
    """原文是 `NULL` / `N/A` / `NaN` 之类字面量，往返后塌缩成缺失。

    反例：`orig='NULLY', got=''` → 不命中（字面量不匹配）。
    """
    if orig.strip().upper() not in NULL_TOKENS:
        return False
    if _meta(stage_meta, "got_missing"):
        return True
    return got == "" or null_state(got) == "null" and got.strip().upper() != orig.strip().upper()


# ── 文本族（4 条）──────────────────────────────────────────────────────────

def unicode_normalization_changed(orig: str, got: str, declared_type: str | None, stage_meta) -> bool:
    """NFC/NFD 等价但码点序列不同。

    反例：`orig='cafe', got='cafe'` → 不命中（无分解差异）。
    """
    if orig == got:
        return False
    return unicodedata.normalize("NFC", orig) == unicodedata.normalize("NFC", got)


def whitespace_collapsed(orig: str, got: str, declared_type: str | None, stage_meta) -> bool:
    """首尾空白被裁，或连续空白被压缩。

    反例：两侧完全一样 → 不命中（空白未变）。
    """
    if orig == got:
        return False
    if orig.strip() == got.strip():
        return any(character.isspace() for character in orig)
    return re.sub(r"\s+", " ", orig).strip() == re.sub(r"\s+", " ", got).strip()


def bom_prepended(orig: str, got: str, declared_type: str | None, stage_meta) -> bool:
    """往返后文本以 `U+FEFF` 开头而原文不是。

    反例：`orig='\\ufeffx', got='x'` → 不命中（BOM 是**移除**而非添加）。
    """
    return got.startswith("\ufeff") and not orig.startswith("\ufeff")


def encoding_mojibake(orig: str, got: str, declared_type: str | None, stage_meta) -> bool:
    """往返后出现典型替换字符 / 乱码残渣。**只检出，不修复**（弃选项已写死）。"""
    if any(marker in orig for marker in _MOJIBAKE_MARKERS):
        return False
    return any(marker in got for marker in _MOJIBAKE_MARKERS)


# ── 时间族（4 条）──────────────────────────────────────────────────────────

def date_retyped_to_text(orig: str, got: str, declared_type: str | None, stage_meta) -> bool:
    """原文是 ISO 日期，往返后变成另一种文本日期形态（`2024-01-02` → `2024/1/2`）。

    反例：两侧同形 → 不命中（形态未变）。

    **目标日期不存在时不命中**（例如 `1900-02-29` → `1900/2/29`）：那不是一个"换了写法的
    日期"，是 Excel 1900 闰年 bug 造出来的假日期，归 `serial_60_phantom_date` 更准确。
    K6 按 id 升序取首条，本条 id 15 会抢在 id 17 前面，所以这条排除必须写在这里。
    """
    stripped = orig.strip()
    if not _ISO_DATE_RE.match(stripped):
        return False
    if stripped == got.strip():
        return False
    got_stripped = got.strip()
    if not (_SLASH_DATE_RE.match(got_stripped) or _OTHER_DATE_RE.match(got_stripped)):
        return False
    return parse_date(got_stripped) is not None


def date_system_shift_1904(orig: str, got: str, declared_type: str | None, stage_meta) -> bool:
    """两个可解析日期恰好相差 1462 天（1900/1904 纪元之差）。

    反例：普通日期格式变化（差值不是 1462 天）→ 不命中。
    """
    before, after = parse_date(orig), parse_date(got)
    if before is None or after is None:
        return False
    return abs((after - before).days) == _1904_SHIFT_DAYS


def serial_60_phantom_date(orig: str, got: str, declared_type: str | None, stage_meta) -> bool:
    """往返后渲染出 `1900-02-29` —— 那一天不存在，是 Excel 1900 闰年 bug 的产物。

    反例：`serial 59 -> '1900-02-28'` → 不命中。
    """
    stripped = got.strip()
    if not (_ISO_DATE_RE.match(stripped) or _SLASH_DATE_RE.match(stripped)):
        return False
    parts = re.split(r"[-/]", stripped)
    if [int(part) for part in parts] != [1900, 2, 29]:
        return False
    return orig.strip() != stripped


def number_format_dropped(orig: str, got: str, declared_type: str | None, stage_meta) -> bool:
    """值本身没变，但 `number_format` 的语义丢了（`0%` / `@` 变 General）。

    这条**只有拿到 `number_format` 才能判**：`stage_meta` 缺这两个键时返回 `False`，
    于是这类差异落 `unclassified` —— D1"宁可 unclassified，不伪造归因"。
    首期四条通道都不上报单元格级 `number_format`，所以本谓词在本轮的真实管线里恒为 `False`，
    `test_number_format_rule_needs_stage_meta` 把这条事实钉住（不假装它覆盖了）。
    """
    original_format = _meta(stage_meta, "orig_number_format")
    if not original_format or str(original_format) == "General":
        return False
    got_format = _meta(stage_meta, "got_number_format")
    return got_format is None or str(got_format) == "General"


# ── 注册表与规则表 ────────────────────────────────────────────────────────

PREDICATES: dict[str, Predicate] = {
    "leading_zero_lost": leading_zero_lost,
    "scientific_notation_coercion": scientific_notation_coercion,
    "float_precision_truncated": float_precision_truncated,
    "int53_overflow": int53_overflow,
    "excel_15_digit_truncation": excel_15_digit_truncation,
    "negative_zero_sign_lost": negative_zero_sign_lost,
    "decimal_trailing_zero_dropped": decimal_trailing_zero_dropped,
    "exponent_form_normalized": exponent_form_normalized,
    "empty_vs_null_vs_missing": empty_vs_null_vs_missing,
    "null_token_collision": null_token_collision,
    "unicode_normalization_changed": unicode_normalization_changed,
    "whitespace_collapsed": whitespace_collapsed,
    "bom_prepended": bom_prepended,
    "encoding_mojibake": encoding_mojibake,
    "date_retyped_to_text": date_retyped_to_text,
    "date_system_shift_1904": date_system_shift_1904,
    "serial_60_phantom_date": serial_60_phantom_date,
    "number_format_dropped": number_format_dropped,
}


@lru_cache(maxsize=1)
def load_rules() -> dict:
    """从包内 `rules.json` 读 18 条规则（`importlib.resources` 保证装好的 wheel 里也能读到）。"""
    text = resources.files("tripwire.rules").joinpath("rules.json").read_text(encoding="utf-8")
    return json.loads(text)


def rule_count() -> int:
    return len(load_rules()["rules"])


def rule_names() -> list[str]:
    return [rule["name"] for rule in load_rules()["rules"]]


def rules_by_id() -> tuple[dict, ...]:
    """按 `id` 升序的规则列表：K6 的"取首条"就是取这里的第一个命中。"""
    return tuple(sorted(load_rules()["rules"], key=lambda rule: rule["id"]))


def predicate_for(name: str) -> Predicate:
    try:
        return PREDICATES[name]
    except KeyError as error:
        raise KeyError(f"rules.json 里的谓词 {name!r} 在 predicates.py 里不存在") from error


__all__ = [
    "NULL_TOKENS",
    "PREDICATES",
    "Predicate",
    "as_decimal",
    "load_rules",
    "null_state",
    "parse_date",
    "predicate_for",
    "round_significant",
    "rule_count",
    "rule_names",
    "rules_by_id",
    "significant_digits",
]
