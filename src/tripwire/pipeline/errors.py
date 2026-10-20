"""管线层失败路径：全部映射到**用法通道 exit 3**，一条也不许降级成"0 差异"。

为什么这些错误必须"响"：一条静默跳过的阶段会让报告显示"无损"，而事实是**没测**。
D1（宁可 unclassified，不伪造归因）在 M1 的同构形态就是：宁可 exit 3，不伪造"跑过了"。
"""

from __future__ import annotations

from pathlib import Path


class StageUnavailable(Exception):
    """阶段缺依赖 / 环境不支持。**终止整条管线**，不得回落到另一个引擎（D1）。

    `stages.json` 里必须先落一条 `{"stage_name": ..., "status": "failed", "reason": ...}`，
    再抛本异常——否则"失败过"这件事在产物里不留痕。
    """

    def __init__(self, stage_name: str, reason: str, stages_path: Path | None = None) -> None:
        self.stage_name = stage_name
        self.reason = reason
        self.stages_path = stages_path
        super().__init__(f"{stage_name}: {reason}")


class StageFailed(Exception):
    """阶段跑起来了但产出不可用（非 UTF-8 输出 / 引擎抛错）。同样终止管线、exit 3。"""

    def __init__(self, stage_name: str, reason: str, stages_path: Path | None = None) -> None:
        self.stage_name = stage_name
        self.reason = reason
        self.stages_path = stages_path
        super().__init__(f"{stage_name}: {reason}")


class RunIdCollision(Exception):
    """同 `run_id` 但内容不同——同 id 必须同内容（D7），否则跨机对账失效。"""


class InputNotUtf8(Exception):
    """输入不是合法 UTF-8 文本。首期只承诺 UTF-8：换编码猜原意会破坏确定性纪律。"""


class RunNotFound(Exception):
    """`runs/<run_id>/` 不存在、`stages.json` 不可解析、或它记录的阶段快照不在目录里。

    与 `RunIdCollision` 分开：前者是"同 id 不同内容"（写入侧的冲突），
    后者是"读不到这一份 run"（读取侧的缺失）。把两者混成一类，CLI 就没法给出
    "该目录不完整"这种可行动的提示。
    """


__all__ = [
    "StageUnavailable",
    "StageFailed",
    "RunIdCollision",
    "InputNotUtf8",
    "RunNotFound",
]
