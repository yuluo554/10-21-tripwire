"""规则谓词：纯函数，签名 `(orig_text, got_text, declared_type, stage_meta) -> bool`。

**M3 实现**。本文件现在只有注册表与占位，`rules.json` 已冻结 18 条清单。
禁令（K6）：谓词不得读网络、读时钟、读随机数、读文件系统——它们必须是输入的确定函数。
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Callable, Mapping

Predicate = Callable[[str, str, str | None, Mapping[str, object] | None], bool]


def _not_implemented(orig: str, got: str, declared_type: str | None, stage_meta: Mapping[str, object] | None) -> bool:
    raise NotImplementedError("谓词将在 M3 实现")


#: 谓词名 -> 函数。M3 逐条替换 `_not_implemented`。
PREDICATES: dict[str, Predicate] = {}


@lru_cache(maxsize=1)
def load_rules() -> dict:
    """从包内 `rules.json` 读 18 条规则（`importlib.resources` 保证装好的 wheel 里也能读到）。"""
    text = resources.files("tripwire.rules").joinpath("rules.json").read_text(encoding="utf-8")
    return json.loads(text)


def rule_count() -> int:
    return len(load_rules()["rules"])


def rule_names() -> list[str]:
    return [rule["name"] for rule in load_rules()["rules"]]
